import asyncio,logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from fastapi import FastAPI
from app.api import routes_detections,routes_nearby,routes_species,routes_status
from app.birdnet.client import BirdNetClient
from app.birdweather.client import BirdWeatherClient
from app.config import get_settings
from app.database import make_engine,make_session_factory
from app.migrations import initialize_database
from app.system_metrics import MetricsSampler
from app.images.provider import WikimediaCommonsProvider
from app.images.service import SpeciesImageService
from app.web import routes as web_routes
from app.services.enrichment import EnrichmentService
from app.services.ingestion import IngestionService
@dataclass
class Health:
    birdnet_connected:bool=False;birdweather_available:bool=False;last_birdnet_poll:datetime|None=None;last_birdweather_request:datetime|None=None
def create_app(settings=None,birdnet=None,birdweather=None,image_provider=None):
    s=settings or get_settings(); logging.basicConfig(level=s.log_level,format="%(asctime)s %(levelname)s %(name)s %(message)s")
    engine=make_engine(s);sessions=make_session_factory(engine);initialize_database(engine)
    bn=birdnet or BirdNetClient(s);bw=birdweather or BirdWeatherClient(s);health=Health();enrichment=EnrichmentService(sessions,bw,s,health);ingestion=IngestionService(sessions,bn,enrichment,s,health);image_provider=image_provider or WikimediaCommonsProvider(s);image_service=SpeciesImageService(sessions,image_provider,s);summary_cache={"expires":0.0,"species":None}
    def invalidate_summary():summary_cache.update(expires=0.0,species=None)
    ingestion.invalidate_summary=invalidate_summary;enrichment.invalidate_summary=invalidate_summary;image_service.invalidate_summary=invalidate_summary
    @asynccontextmanager
    async def lifespan(app):
        tasks=[asyncio.create_task(ingestion.run(),name="birdnet-ingestion"),asyncio.create_task(enrichment.run(),name="birdweather-enrichment"),asyncio.create_task(image_service.run(),name="species-images")] if s.worker_enabled else []
        yield
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        await bn.close();await bw.close();await image_provider.close();engine.dispose()
    app=FastAPI(title="Bird Corroborator",version="1.0.0",lifespan=lifespan)
    app.state.settings=s;app.state.sessions=sessions;app.state.health=health;app.state.ingestion=ingestion;app.state.enrichment=enrichment;app.state.metrics=MetricsSampler();app.state.image_service=image_service;app.state.summary_cache=summary_cache
    for router in (routes_status.router,routes_detections.router,routes_species.router,routes_nearby.router):app.include_router(router,prefix="/api/v1")
    app.include_router(web_routes.router)
    return app
app=create_app()
