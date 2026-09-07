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
        rows=await self.bn.recent(since,catchup=catchup); new=[]
        with self.sessions() as db:
            for item in rows:
                row,created=insert_detection(db,item)
                if created:new.append(row.id)
            newest=max((x.detected_at for x in rows),default=now)
            state=db.get(AppState,"birdnet_checkpoint_at") or AppState(key="birdnet_checkpoint_at",value=newest.isoformat())
            state.value=max(newest,since).isoformat();db.merge(state);db.commit()
        self.status.birdnet_connected=True; self.status.last_birdnet_poll=datetime.now(timezone.utc)
        log.info("BirdNET poll complete: %s detections, %s new",len(rows),len(new))
        return len(new)
    async def run(self):
        log.info("ingestion worker started")
        first=True
        while True:
            try:
                if first and load_is_high(self.s):
                    log.info("System load high: startup catch-up deferred; polling recent detections only")
                    await self.poll(catchup=False)
                else:
                    await self.poll(catchup=first);first=False
            except asyncio.CancelledError: raise
            except Exception as exc: self.status.birdnet_connected=False; log.warning("BirdNET poll failed; retrying next cycle: %s",exc)
            await asyncio.sleep(self.s.birdnet_poll_seconds)
