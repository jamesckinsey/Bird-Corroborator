from datetime import datetime,timezone
from fastapi import APIRouter,Depends,Request
from sqlalchemy import func,select,text
from sqlalchemy.orm import Session
from app.api.dependencies import db
from app.api.schemas import StatusOut
from app.db.models import EnrichmentState,LocalDetection
router=APIRouter()
@router.get("/status",response_model=StatusOut)
async def status(request:Request,session:Session=Depends(db)):
    ok=True
    try:session.execute(text("SELECT 1"))
    except Exception:ok=False
    state=request.app.state.health
    minimum=request.app.state.settings.birdnet_min_confidence
    pending=session.scalar(select(func.count()).select_from(LocalDetection).where(LocalDetection.confidence>=minimum,LocalDetection.enrichment_state!=EnrichmentState.COMPLETE)) if ok else 0
    retries=session.scalar(select(func.count()).select_from(LocalDetection).where(LocalDetection.confidence>=minimum,LocalDetection.enrichment_state==EnrichmentState.TEMPORARILY_UNAVAILABLE)) if ok else 0
    metrics=request.app.state.metrics.sample()
    recent_poll=state.last_birdnet_poll and (datetime.now(timezone.utc)-state.last_birdnet_poll).total_seconds()<=request.app.state.settings.birdnet_poll_seconds*2+30
    connected=bool(state.birdnet_connected or recent_poll)
    return StatusOut(status="ok" if ok else "degraded",birdnet_connected=connected,birdweather_available=state.birdweather_available,last_birdnet_poll=state.last_birdnet_poll,last_birdweather_request=state.last_birdweather_request,database_ok=ok,pending_enrichments=pending or 0,retry_enrichments=retries or 0,**metrics)
