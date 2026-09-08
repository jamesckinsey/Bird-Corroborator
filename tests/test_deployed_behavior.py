from datetime import datetime,timedelta,timezone
import httpx,pytest
from sqlalchemy import select
from app.birdweather.models import BirdWeatherDetection
from app.corroboration.scorer import score_detection
from app.db.models import LocalDetection
from app.main import create_app
from tests.test_service_api import FakeBN,FakeBW,detection

def nearby(source,station,distance,minutes):
    now=datetime.now(timezone.utc)
    return BirdWeatherDetection(source_detection_id=source,station_id=station,station_name=station,species_common="Northern Cardinal",species_scientific="Cardinalis cardinalis",detected_at=now+timedelta(minutes=minutes),latitude=42.362,longitude=-71.449,distance_miles=distance,source_confidence=.9)

@pytest.mark.asyncio
async def test_low_medium_and_high_confidence_all_ingest_enrich_and_appear(settings):
    rows=[]
    for id_,confidence,name,scientific in (("low",.35,"Low Bird","Lowus birdus"),("medium",.65,"Medium Bird","Mediumus birdus"),("high",.95,"High Bird","Highus birdus")):
        row=detection(id_);row.confidence=confidence;row.species_common=name;row.species_scientific=scientific;rows.append(row)
    class CountingBW(FakeBW):
        def __init__(self):super().__init__([nearby("nearby","station",2,5)]);self.calls=0
        async def lookup(self,*args):self.calls+=1;return self.rows
    birdweather=CountingBW();app=create_app(settings,FakeBN(rows),birdweather);assert await app.state.ingestion.poll(True)==3
    for _ in rows:assert await app.state.enrichment.retry_due()==1
    with app.state.sessions() as db:
        stored=list(db.scalars(select(LocalDetection).order_by(LocalDetection.confidence)))
        assert [row.confidence for row in stored]==[.35,.65,.95]
        assert all(row.corroboration is not None for row in stored)
        assert stored[0].corroboration.score<stored[-1].corroboration.score
    assert birdweather.calls==3
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        latest=(await client.get("/api/v1/detections/latest")).json();assert sorted(row["birdnet_confidence"] for row in latest)==[.35,.65,.95]
        summary=(await client.get("/api/v1/species/today")).json();assert len(summary)==3
        detections=(await client.get("/detections")).text;landing=(await client.get("/")).text
        assert all(value in detections for value in ("35%","65%","95%"))
        assert all(name in landing for name in ("Low Bird","Medium Bird","High Bird"))

@pytest.mark.asyncio
async def test_excluded_station_contributes_no_evidence_and_duplicates_count_correctly(settings):
    settings=settings.model_copy(update={"birdweather_excluded_station_ids":"own-station"})
    excluded=nearby("own-1","own-station",.1,1);included=[nearby("other-1","other-station",5,30),nearby("other-2","other-station",6,40)]
    app=create_app(settings,FakeBN([detection()]),FakeBW([excluded,*included]));await app.state.ingestion.poll(True);await app.state.enrichment.retry_due()
    with app.state.sessions() as db:
        row=db.scalar(select(LocalDetection));result=row.corroboration
        expected=score_detection(row.confidence,row.detected_at,included)
        assert result.unique_station_count==1 and result.match_count==2
        assert result.nearest_match_distance==5 and result.closest_time_difference_minutes==expected.closest_minutes
        assert result.score==expected.score
        assert {m.station_id for m in row.matches}=={"other-station"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        summary=(await client.get("/api/v1/species/today")).json()[0]
        assert summary["nearby_unique_stations"]==1 and summary["nearby_total_detections"]==2

@pytest.mark.asyncio
async def test_recent_successful_poll_drives_birdnet_health(settings):
    app=create_app(settings,FakeBN([detection()]),FakeBW());await app.state.ingestion.poll(True);app.state.health.birdnet_connected=False
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        assert (await client.get("/api/v1/status")).json()["birdnet_connected"] is True
