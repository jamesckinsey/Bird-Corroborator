import asyncio, logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.db.repositories import insert_detection
from app.db.models import AppState
from app.system_metrics import load_is_high
log=logging.getLogger(__name__)
class IngestionService:
    def __init__(self,sessions,birdnet,enrichment,settings,status): self.sessions=sessions;self.bn=birdnet;self.enrichment=enrichment;self.s=settings;self.status=status
    async def poll(self,catchup=False,hours=None):
        now=datetime.now(timezone.utc)
        with self.sessions() as db:
            checkpoint=db.get(AppState,"birdnet_checkpoint_at")
        if catchup:
            since=now-timedelta(hours=hours or self.s.birdnet_catchup_hours)
        elif not checkpoint:
            since=now-timedelta(seconds=self.s.birdnet_poll_seconds*2)
        else:
            saved=datetime.fromisoformat(checkpoint.value.replace("Z","+00:00"));since=saved-timedelta(seconds=5)
        try:rows=await self.bn.recent(since,catchup=catchup)
        except Exception as exc:
            response_at=getattr(self.bn,"last_http_success_at",None)
            if response_at and response_at>=now:self.status.birdnet_connected=True;self.status.last_birdnet_response=response_at
            else:self.status.birdnet_connected=False
            self.status.birdnet_ingestion_ok=False;self.status.birdnet_ingestion_error=str(exc)[:500]
            raise
        new=[]
        with self.sessions() as db:
            for item in rows:
                row,created=insert_detection(db,item)
                if created:new.append(row.id)
            newest=max((x.detected_at for x in rows),default=now)
            state=db.get(AppState,"birdnet_checkpoint_at") or AppState(key="birdnet_checkpoint_at",value=newest.isoformat())
            state.value=max(newest,since).isoformat();db.merge(state);db.commit()
        self.status.birdnet_connected=True;self.status.birdnet_ingestion_ok=True;self.status.birdnet_ingestion_error=None;self.status.last_birdnet_response=getattr(self.bn,"last_http_success_at",None) or datetime.now(timezone.utc);self.status.last_birdnet_poll=datetime.now(timezone.utc)
        log.info("BirdNET poll complete: %s detections, %s new",len(rows),len(new))
        if new:getattr(self,"invalidate_summary",lambda:None)()
        return len(new)
    def startup_requires_catchup(self):
        with self.sessions() as db:return db.get(AppState,"birdnet_checkpoint_at") is None
    async def run(self):
        log.info("ingestion worker started")
        first=True;needs_catchup=self.startup_requires_catchup()
        while True:
            try:
                if first and needs_catchup and load_is_high(self.s):
                    log.info("System load high: startup catch-up deferred; polling recent detections only")
                    await self.poll(catchup=False)
                else:
                    await self.poll(catchup=first and needs_catchup);first=False
            except asyncio.CancelledError: raise
            except Exception as exc:log.warning("BirdNET poll failed; retrying next cycle: %s",exc)
            await asyncio.sleep(self.s.birdnet_poll_seconds)
