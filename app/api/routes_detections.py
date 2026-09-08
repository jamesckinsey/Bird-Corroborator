from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter,Depends,HTTPException,Query,Request
from sqlalchemy import select
from sqlalchemy.orm import Session,selectinload
from app.api.dependencies import db
from app.api.schemas import CorroborationOut,DetectionDetail,DetectionOut,MatchOut
from app.db.models import CorroborationResult,LocalDetection
from app.images.presentation import image_fields,image_map
from app.corroboration.scorer import score_detection
router=APIRouter(prefix="/detections")
def bounds(tzname):
    now=datetime.now(ZoneInfo(tzname)); start=now.replace(hour=0,minute=0,second=0,microsecond=0); return start.astimezone(timezone.utc),now.astimezone(timezone.utc)
def serialize(d,detail=False,image=None,excluded_station_ids=frozenset()):
    c=d.corroboration;matches=[m for m in d.matches if m.station_id not in excluded_station_ids]
    recalculated=score_detection(d.confidence,d.detected_at,matches) if c else None
    cor=CorroborationOut(birdnet_confidence=d.confidence,corroboration_score=recalculated.score if recalculated else None,corroboration_level=recalculated.level if recalculated else None,unique_nearby_stations=recalculated.unique_stations if recalculated else 0,matching_detections=recalculated.matches if recalculated else 0,nearest_match_miles=recalculated.nearest_miles if recalculated else None,closest_time_difference_minutes=recalculated.closest_minutes if recalculated else None,algorithm_version=c.algorithm_version if c else None)
    data=dict(id=d.id,source=d.source,source_detection_id=d.source_detection_id,species_common=d.species_common,species_scientific=d.species_scientific,detected_at=d.detected_at,birdnet_confidence=d.confidence,audio_reference=d.audio_reference,enrichment_state=d.enrichment_state,corroboration=cor,**image_fields(image))
    if detail:data["nearby_matches"]=[MatchOut.model_validate(m) for m in sorted(matches,key=lambda x:x.detected_at,reverse=True)]
    return DetectionDetail(**data) if detail else DetectionOut(**data)
def query_rows(session,stmt):return list(session.scalars(stmt.options(selectinload(LocalDetection.corroboration),selectinload(LocalDetection.matches))))
@router.get("/latest",response_model=list[DetectionOut])
async def latest(request:Request,limit:int=Query(20,ge=1,le=200),session:Session=Depends(db)):
    settings=request.app.state.settings;rows=query_rows(session,select(LocalDetection).order_by(LocalDetection.detected_at.desc()).limit(limit));images=image_map(session,(x.species_scientific for x in rows));return [serialize(x,image=images.get(x.species_scientific),excluded_station_ids=settings.excluded_station_ids) for x in rows]
@router.get("/today",response_model=list[DetectionOut])
async def today(request:Request,species:str|None=None,corroboration_level:str|None=None,session:Session=Depends(db)):
    settings=request.app.state.settings;start,end=bounds(settings.local_timezone); stmt=select(LocalDetection).where(LocalDetection.detected_at>=start,LocalDetection.detected_at<=end)
    if species:stmt=stmt.where((LocalDetection.species_common.ilike(f"%{species}%"))|(LocalDetection.species_scientific.ilike(f"%{species}%")))
    if corroboration_level:stmt=stmt.join(CorroborationResult).where(CorroborationResult.classification==corroboration_level)
    rows=query_rows(session,stmt.order_by(LocalDetection.detected_at.desc()).limit(1000));images=image_map(session,(x.species_scientific for x in rows));return [serialize(x,image=images.get(x.species_scientific),excluded_station_ids=settings.excluded_station_ids) for x in rows]
@router.get("/{detection_id}",response_model=DetectionDetail)
async def detail(detection_id:int,request:Request,session:Session=Depends(db)):
    rows=query_rows(session,select(LocalDetection).where(LocalDetection.id==detection_id));
    if not rows:raise HTTPException(404,"Detection not found")
    settings=request.app.state.settings;images=image_map(session,[rows[0].species_scientific]);return serialize(rows[0],True,images.get(rows[0].species_scientific),settings.excluded_station_ids)
