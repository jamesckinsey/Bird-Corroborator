from datetime import datetime,timedelta,timezone
import httpx,pytest
from sqlalchemy import select
from app.birdweather.models import BirdWeatherDetection
from app.corroboration.scorer import score_detection
from app.db.models import LocalDetection,SpeciesImage
from app.main import create_app
from tests.test_service_api import FakeBN,FakeBW,detection

def nearby(source,station,distance,minutes):
    now=datetime.now(timezone.utc)
    return BirdWeatherDetection(source_detection_id=source,station_id=station,station_name=station,species_common="Northern Cardinal",species_scientific="Cardinalis cardinalis",detected_at=now+timedelta(minutes=minutes),latitude=42.362,longitude=-71.449,distance_miles=distance,source_confidence=.9)

@pytest.mark.asyncio
async def test_ingestion_threshold_rejects_69_accepts_70_and_95(settings):
    rows=[detection("69"),detection("70"),detection("95")];rows[0].confidence=.69;rows[1].confidence=.70;rows[2].confidence=.95
    app=create_app(settings,FakeBN(rows),FakeBW());assert await app.state.ingestion.poll(True)==2
    with app.state.sessions() as db:assert list(db.scalars(select(LocalDetection.source_detection_id).order_by(LocalDetection.source_detection_id)))==["70","95"]
    app.state.image_service.discover()
    with app.state.sessions() as db:assert db.scalar(select(SpeciesImage)) is not None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        summary=(await client.get("/api/v1/species/today")).json();assert len(summary)==1 and summary[0]["local_detection_count"]==2
        assert (await client.get("/")).text.count('class="species-card"')==1

@pytest.mark.asyncio
async def test_historical_low_confidence_hidden_from_pages_and_apis(settings):
    app=create_app(settings,FakeBN([]),FakeBW())
    with app.state.sessions() as db:
        low=LocalDetection(source_detection_id="old-low",species_common="Low Bird",species_scientific="Lowus birdus",detected_at=datetime.now(timezone.utc),confidence=.69,raw_metadata={});db.add(low);db.commit();low_id=low.id
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        assert (await client.get("/api/v1/detections/latest")).json()==[]
        assert (await client.get("/api/v1/species/today")).json()==[]
        assert (await client.get(f"/api/v1/detections/{low_id}")).status_code==404
        assert "Low Bird" not in (await client.get("/")).text

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
