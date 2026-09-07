from datetime import datetime,timezone
from pathlib import Path
import pytest
from sqlalchemy import select
from app.birdnet.models import BirdNetDetection
from app.database import make_engine,make_session_factory
from app.db.models import LocalDetection
from app.db.repositories import insert_detection
from app.migrations import initialize_database
from app.system_metrics import MetricsSampler
from app.main import create_app
from tests.test_service_api import FakeBN,FakeBW,detection

@pytest.mark.asyncio
async def test_load_shedding_defers_enrichment_but_not_ingestion(settings,monkeypatch):
    monkeypatch.setattr("app.system_metrics.os.getloadavg",lambda:(99.0,1.0,1.0))
    app=create_app(settings,FakeBN([detection()]),FakeBW())
    assert await app.state.ingestion.poll(True)==1
    assert await app.state.enrichment.retry_due()==0
    with app.state.sessions() as db:assert db.scalar(select(LocalDetection)).enrichment_state=="PENDING"

@pytest.mark.asyncio
async def test_enrichment_processes_only_one_due_record(settings):
    app=create_app(settings,FakeBN([detection("1"),detection("2")]),FakeBW())
    await app.state.ingestion.poll(True)
    assert await app.state.enrichment.retry_due()==1
    with app.state.sessions() as db:
        states=[x.enrichment_state for x in db.scalars(select(LocalDetection).order_by(LocalDetection.id))]
    assert states.count("COMPLETE")==1 and states.count("PENDING")==1

def test_metrics_gracefully_unavailable(monkeypatch):
    monkeypatch.setattr("app.system_metrics.os.getloadavg",lambda:(_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(Path,"read_text",lambda self:(_ for _ in ()).throw(OSError()))
    values=MetricsSampler().sample();assert all(value is None for value in values.values())

def test_additive_migration_preserves_existing_record(settings):
    engine=make_engine(settings);initialize_database(engine);sessions=make_session_factory(engine)
    with sessions() as db:insert_detection(db,detection("preserved"))
    initialize_database(engine)
    with sessions() as db:assert db.scalar(select(LocalDetection.source_detection_id))=="preserved"

def test_systemd_unit_never_controls_birdnet():
    unit=Path("deploy/bird-corroborator.service").read_text().lower()
    assert "birdnet-go.service" not in unit and "execstop" not in unit
    assert "nice=10" in unit and "cpuweight=20" in unit and "memorymax=256m" in unit
