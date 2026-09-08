from fastapi import APIRouter,Depends,Request
from sqlalchemy import func,select
from sqlalchemy.orm import Session
from app.api.dependencies import db
from app.api.routes_detections import bounds
from app.api.schemas import SpeciesSummary
from app.db.models import BirdWeatherMatch,CorroborationResult,LocalDetection
from app.images.presentation import image_fields,image_map
router=APIRouter(prefix="/species")
RANK={None:0,"UNVERIFIED":1,"POSSIBLE":2,"LIKELY":3,"STRONGLY_CORROBORATED":4}
@router.get("/today",response_model=list[SpeciesSummary])
async def today(request:Request,session:Session=Depends(db)):
    start,end=bounds(request.app.state.settings.local_timezone); rows=list(session.scalars(select(LocalDetection).where(LocalDetection.detected_at>=start,LocalDetection.detected_at<=end).order_by(LocalDetection.detected_at.desc())))
    groups={}
    for d in rows:
        key=d.species_scientific; g=groups.setdefault(key,{"species_common":d.species_common,"species_scientific":key,"local_detection_count":0,"highest_birdnet_confidence":0,"latest_detection":d.detected_at,"best_corroboration_level":None,"stations":set()})
        g["local_detection_count"]+=1;g["highest_birdnet_confidence"]=max(g["highest_birdnet_confidence"],d.confidence);g["latest_detection"]=max(g["latest_detection"],d.detected_at)
        if d.corroboration and RANK[d.corroboration.classification]>RANK[g["best_corroboration_level"]]:g["best_corroboration_level"]=d.corroboration.classification
        g["stations"].update(m.station_id for m in d.matches)
    images=image_map(session,groups)
    return [SpeciesSummary(**{**{k:v for k,v in g.items() if k!="stations"},"nearby_unique_stations":len(g["stations"]),**image_fields(images.get(g["species_scientific"]))}) for g in groups.values()]
