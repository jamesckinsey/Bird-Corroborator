from datetime import datetime,timedelta,timezone
import httpx,pytest
from sqlalchemy import select
from app.birdweather.models import BirdWeatherDetection
from app.corroboration.scorer import score_detection
from app.api.routes_species import display_score,score_band,summary_sort_key
from app.api.schemas import SpeciesSummary
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
        assert all(row["display_corroboration_score"] is not None for row in summary)
        detections=(await client.get("/detections")).text;landing=(await client.get("/")).text
        assert all(value in detections for value in ("35%","65%","95%"))
        assert all(name in landing for name in ("Low Bird","Medium Bird","High Bird"))

def species_summary(name,score,count=1,minutes=0):
    return SpeciesSummary(species_common=name,species_scientific=f"{name} scientific",local_detection_count=count,highest_birdnet_confidence=.8,latest_detection=datetime.now(timezone.utc)+timedelta(minutes=minutes),best_corroboration_level=None if score is None else "LIKELY",best_corroboration_score=score,display_corroboration_score=display_score(score),nearby_unique_stations=0,nearby_total_detections=0)

def test_display_score_mapping_and_background_bands():
    assert [(raw,display_score(raw)) for raw in (0,1,14,15,34,35,54,55,74,75,94,95,100,None)]==[(0,1),(1,1),(14,1),(15,2),(34,3),(35,4),(54,5),(55,6),(74,7),(75,8),(94,9),(95,10),(100,10),(None,None)]
    assert [(value,score_band(value)) for value in (10,9,8,7,6,5,4,3,2,1,None)]==[(10,"very-high"),(9,"very-high"),(8,"high"),(7,"high"),(6,"medium"),(5,"medium"),(4,"low"),(3,"low"),(2,"very-low"),(1,"very-low"),(None,"pending")]

def test_species_sort_score_then_count_then_latest_with_pending_last():
    values=[species_summary("Pending",None,99,99),species_summary("Low",40,20,20),species_summary("High",90),species_summary("Tie older",70,2,0),species_summary("Tie newer",70,2,1),species_summary("Tie count",70,3,-1)]
    ordered=sorted(values,key=summary_sort_key,reverse=True)
    assert [item.species_common for item in ordered]==["High","Tie count","Tie newer","Tie older","Low","Pending"]

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
