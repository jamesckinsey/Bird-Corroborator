from datetime import datetime,timedelta,timezone
import httpx,pytest
from sqlalchemy import select
from app.birdnet.models import BirdNetDetection
from app.db.models import EnrichmentState,LocalDetection
from app.main import create_app
class FakeBN:
    def __init__(self,rows):self.rows=rows
    async def recent(self,since,catchup=False):return [x for x in self.rows if x.detected_at>=since]
    async def close(self):pass
class FakeBW:
    def __init__(self,rows=None,error=None):self.rows=rows or [];self.error=error
    async def lookup(self,*a):
        if self.error:raise self.error
        return self.rows
    async def lookup_all(self):
        if self.error:raise self.error
        return self.rows
    async def close(self):pass
def detection(id="1",when=None):return BirdNetDetection(source_detection_id=id,species_common="Northern Cardinal",species_scientific="Cardinalis cardinalis",detected_at=when or datetime.now(timezone.utc),confidence=.82)
@pytest.mark.asyncio
async def test_ingestion_idempotency_restart_and_serialization(settings):
    app=create_app(settings,FakeBN([detection()]),FakeBW());svc=app.state.ingestion
    assert await svc.poll(True)==1;assert await svc.poll(True)==0
    assert await app.state.enrichment.retry_due()==1
    transport=httpx.ASGITransport(app=app); client=httpx.AsyncClient(transport=transport,base_url="http://test")
    async with client as c:
        r=await c.get("/api/v1/detections/latest");assert r.status_code==200 and r.json()[0]["corroboration"]["algorithm_version"]=="v1"
        assert (await c.get("/api/v1/status")).json()["database_ok"]
    with app.state.sessions() as db:assert len(list(db.scalars(select(LocalDetection))))==1
@pytest.mark.asyncio
async def test_failed_enrichment_retained_and_retry(settings):
    bw=FakeBW(error=RuntimeError("offline"));app=create_app(settings,FakeBN([detection()]),bw);await app.state.ingestion.poll(True);await app.state.enrichment.retry_due()
    with app.state.sessions() as db:
        d=db.scalar(select(LocalDetection));assert d.enrichment_state==EnrichmentState.TEMPORARILY_UNAVAILABLE and d.enrichment_attempts==1
        d.next_enrichment_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit();did=d.id
    bw.error=None;await app.state.ingestion.enrichment.retry_due()
    with app.state.sessions() as db:assert db.get(LocalDetection,did).enrichment_state==EnrichmentState.COMPLETE
@pytest.mark.asyncio
async def test_today_timezone_boundary(settings):
    # 03:30Z is still previous day in New York; 05:00Z is today around DST season.
    now=datetime.now(timezone.utc);app=create_app(settings,FakeBN([]),FakeBW())
    with app.state.sessions() as db:
        from app.db.repositories import insert_detection
        insert_detection(db,detection("old",now-timedelta(days=2)));insert_detection(db,detection("new",now))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as c:
        body=(await c.get("/api/v1/detections/today")).json();assert [x["source_detection_id"] for x in body]==["new"]
