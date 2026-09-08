from fastapi import APIRouter,Depends,Request
from sqlalchemy import func,select
from sqlalchemy.orm import Session,selectinload
from app.api.dependencies import db
from app.api.routes_detections import bounds
from app.api.schemas import SpeciesSummary
from app.db.models import BirdWeatherMatch,CorroborationResult,LocalDetection
from app.images.presentation import image_fields,image_map
from app.corroboration.scorer import score_detection
router=APIRouter(prefix="/species")
RANK={None:0,"UNVERIFIED":1,"POSSIBLE":2,"LIKELY":3,"STRONGLY_CORROBORATED":4}
def display_score(raw_score:int|None)->int|None:
    if raw_score is None:return None
    return max(1,min(10,int(raw_score/10+.5)))
def score_band(score:int|None)->str:
    if score is None:return "pending"
    if score>=9:return "very-high"
    if score>=7:return "high"
    if score>=5:return "medium"
    if score>=3:return "low"
    return "very-low"
def summary_sort_key(item:SpeciesSummary):
    return (item.best_corroboration_score is not None,item.best_corroboration_score or -1,item.local_detection_count,item.latest_detection)
@router.get("/today",response_model=list[SpeciesSummary])
async def today(request:Request,session:Session=Depends(db)):
    return summaries(request,session)
def summaries(request:Request,session:Session):
    settings=request.app.state.settings;start,end=bounds(settings.local_timezone); rows=list(session.scalars(select(LocalDetection).where(LocalDetection.detected_at>=start,LocalDetection.detected_at<=end).options(selectinload(LocalDetection.corroboration),selectinload(LocalDetection.matches)).order_by(LocalDetection.detected_at.desc())))
    groups={}
    for d in rows:
        key=d.species_scientific; g=groups.setdefault(key,{"species_common":d.species_common,"species_scientific":key,"local_detection_count":0,"highest_birdnet_confidence":0,"latest_detection":d.detected_at,"best_corroboration_level":None,"best_corroboration_score":None,"stations":set(),"observations":set()})
        g["local_detection_count"]+=1;g["highest_birdnet_confidence"]=max(g["highest_birdnet_confidence"],d.confidence);g["latest_detection"]=max(g["latest_detection"],d.detected_at)
        independent=[m for m in d.matches if m.station_id not in settings.excluded_station_ids]
        recalculated=score_detection(d.confidence,d.detected_at,independent) if d.corroboration else None
        if recalculated and (g["best_corroboration_score"] is None or recalculated.score>g["best_corroboration_score"]):g["best_corroboration_score"]=recalculated.score;g["best_corroboration_level"]=recalculated.level
        g["stations"].update(m.station_id for m in independent);g["observations"].update(m.source_detection_id for m in independent)
    images=image_map(session,groups)
    output=[SpeciesSummary(**{**{k:v for k,v in g.items() if k not in {"stations","observations"}},"display_corroboration_score":display_score(g["best_corroboration_score"]),"nearby_unique_stations":len(g["stations"]),"nearby_total_detections":len(g["observations"]),**image_fields(images.get(g["species_scientific"]))}) for g in groups.values()]
    return sorted(output,key=summary_sort_key,reverse=True)
