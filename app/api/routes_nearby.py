from fastapi import APIRouter,Depends,Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.dependencies import db
from app.api.routes_detections import bounds
from app.api.schemas import NearbySummary
from app.db.models import LocalDetection,NearbyObservation
router=APIRouter(prefix="/nearby")
@router.get("/today",response_model=list[NearbySummary])
async def today(request:Request,session:Session=Depends(db)):
    settings=request.app.state.settings;start,end=bounds(settings.local_timezone)
    local=set(session.scalars(select(LocalDetection.species_scientific).where(LocalDetection.detected_at>=start,LocalDetection.detected_at<=end,LocalDetection.confidence>=settings.birdnet_min_confidence)))
    stmt=select(NearbyObservation).where(NearbyObservation.detected_at>=start,NearbyObservation.detected_at<=end)
    if settings.excluded_station_ids:stmt=stmt.where(NearbyObservation.station_id.not_in(settings.excluded_station_ids))
    rows=list(session.scalars(stmt))
    groups={}
    for o in rows:
        if o.species_scientific in local:continue
        g=groups.setdefault(o.species_scientific,{"species_common":o.species_common,"species_scientific":o.species_scientific,"stations":set(),"nearest_station_miles":o.distance_miles,"most_recent_detection":o.detected_at})
        g["stations"].add(o.station_id);g["nearest_station_miles"]=min(g["nearest_station_miles"],o.distance_miles);g["most_recent_detection"]=max(g["most_recent_detection"],o.detected_at)
    # Independent station count first, recency second; minimum two stations suppresses one-off noise.
    out=[NearbySummary(**{**{k:v for k,v in g.items() if k!="stations"},"nearby_unique_stations":len(g["stations"])}) for g in groups.values() if len(g["stations"])>=2]
    return sorted(out,key=lambda x:(x.nearby_unique_stations,x.most_recent_detection),reverse=True)[:50]
