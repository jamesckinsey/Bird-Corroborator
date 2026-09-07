from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, select
from app.corroboration.scorer import ALGORITHM_VERSION, score_detection
import asyncio,logging,time
from app.db.models import BirdWeatherMatch, CorroborationResult, EnrichmentState, LocalDetection, NearbyObservation
from app.system_metrics import load_is_high
log=logging.getLogger(__name__)

class EnrichmentService:
    def __init__(self,sessions,birdweather,settings,status=None): self.sessions=sessions; self.bw=birdweather; self.s=settings;self.status=status
    async def enrich(self,detection_id:int):
        with self.sessions() as db:
            d=db.get(LocalDetection,detection_id)
            if not d:return
            d.enrichment_attempts+=1; db.commit(); scientific=d.species_scientific; common=d.species_common; detected_at=d.detected_at
        try:
            matches=await self.bw.lookup(scientific,common)
            with self.sessions() as db:
                d=db.get(LocalDetection,detection_id); db.execute(delete(BirdWeatherMatch).where(BirdWeatherMatch.local_detection_id==d.id))
                for m in matches:
                    db.merge(NearbyObservation(source_detection_id=m.source_detection_id,station_id=m.station_id,station_name=m.station_name,species_common=m.species_common,species_scientific=m.species_scientific,detected_at=m.detected_at,distance_miles=m.distance_miles,source_confidence=m.source_confidence))
                    db.add(BirdWeatherMatch(local_detection_id=d.id,**m.model_dump()))
                result=score_detection(d.confidence,d.detected_at,matches)
                old=d.corroboration
                values=dict(score=result.score,classification=result.level,unique_station_count=result.unique_stations,match_count=result.matches,nearest_match_distance=result.nearest_miles,closest_time_difference_minutes=result.closest_minutes,has_before_and_after=result.before_and_after,algorithm_version=ALGORITHM_VERSION,calculated_at=datetime.now(timezone.utc))
                if old:
                    for k,v in values.items():setattr(old,k,v)
                else: db.add(CorroborationResult(local_detection_id=d.id,**values))
                d.enrichment_state=EnrichmentState.COMPLETE; d.enrichment_error=None; d.next_enrichment_at=None; db.commit()
        except Exception as exc:
            with self.sessions() as db:
                d=db.get(LocalDetection,detection_id); d.enrichment_state=EnrichmentState.TEMPORARILY_UNAVAILABLE; d.enrichment_error=str(exc)[:500]
                delay=self.s.enrichment_retry_seconds*(2**min(d.enrichment_attempts-1,5)); d.next_enrichment_at=datetime.now(timezone.utc)+timedelta(seconds=delay); db.commit()
            raise
    async def retry_due(self,limit=1):
        if load_is_high(self.s):
            log.info("System load high: BirdWeather enrichment deferred")
            return 0
        now=datetime.now(timezone.utc)
        with self.sessions() as db:
            ids=list(db.scalars(select(LocalDetection.id).where(LocalDetection.enrichment_state!=EnrichmentState.COMPLETE,LocalDetection.enrichment_attempts<self.s.enrichment_max_attempts,LocalDetection.next_enrichment_at<=now).order_by(LocalDetection.detected_at).limit(limit)))
        for id_ in ids:
            try:
                await self.enrich(id_)
                if self.status:self.status.birdweather_available=True;self.status.last_birdweather_request=datetime.now(timezone.utc)
            except Exception:
                if self.status:self.status.birdweather_available=False
        return len(ids)
    async def refresh_nearby(self):
        if load_is_high(self.s):return 0
        observations=await self.bw.lookup_all()
        with self.sessions() as db:
            for m in observations:
                db.merge(NearbyObservation(source_detection_id=m.source_detection_id,station_id=m.station_id,station_name=m.station_name,species_common=m.species_common,species_scientific=m.species_scientific,detected_at=m.detected_at,distance_miles=m.distance_miles,source_confidence=m.source_confidence))
            db.commit()
        return len(observations)
    async def run(self):
        log.info("single-concurrency enrichment worker started")
        next_snapshot=0.0
        while True:
            try:
                worked=await self.retry_due(limit=1)
                if time.monotonic()>=next_snapshot and not load_is_high(self.s):
                    await self.refresh_nearby();next_snapshot=time.monotonic()+self.s.birdweather_cache_seconds
                await asyncio.sleep(2 if worked else 15)
            except asyncio.CancelledError:raise
            except Exception as exc:
                if self.status:self.status.birdweather_available=False
                log.warning("BirdWeather unavailable: enrichment retained for retry: %s",exc)
                await asyncio.sleep(30)
