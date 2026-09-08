from datetime import datetime,timezone
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException,Query,Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func,select
from sqlalchemy.orm import Session
from app.api.dependencies import db
from app.api.routes_detections import query_rows,serialize
from app.api.routes_species import summaries
from app.db.models import LocalDetection,SpeciesImage
from app.images.presentation import image_fields,image_map
templates=Jinja2Templates(directory=str(Path(__file__).resolve().parents[1]/"templates"))
router=APIRouter()
def context(request,**values):return {"request":request,"now":datetime.now(timezone.utc),**values}

@router.get("/")
async def dashboard(request:Request,session:Session=Depends(db)):
    return templates.TemplateResponse(request,"species.html",context(request,species=summaries(request,session),settings=request.app.state.settings))

@router.get("/detections")
async def detections_page(request:Request,limit:int=Query(50,ge=1,le=200),session:Session=Depends(db)):
    rows=query_rows(session,select(LocalDetection).order_by(LocalDetection.detected_at.desc()).limit(limit));images=image_map(session,(x.species_scientific for x in rows))
    return templates.TemplateResponse(request,"detections.html",context(request,detections=[serialize(x,image=images.get(x.species_scientific),excluded_station_ids=request.app.state.settings.excluded_station_ids) for x in rows],limit=limit))

@router.get("/species")
async def species_page(request:Request,session:Session=Depends(db)):
    return templates.TemplateResponse(request,"species.html",context(request,species=summaries(request,session),settings=request.app.state.settings))

@router.get("/system")
async def system_page(request:Request,session:Session=Depends(db)):
    from app.api.routes_status import status
    status_data=await status(request,session);complete=session.scalar(select(func.count()).select_from(SpeciesImage).where(SpeciesImage.retrieval_status=="COMPLETE")) or 0;retry=session.scalar(select(func.count()).select_from(SpeciesImage).where(SpeciesImage.retrieval_status=="RETRY")) or 0
    return templates.TemplateResponse(request,"system.html",context(request,status=status_data,image_count=complete,image_retries=retry,image_error=request.app.state.image_service.last_error))

@router.get("/media/species/{key}")
async def species_media(key:str,session:Session=Depends(db)):
    row=db_image=session.get(SpeciesImage,key)
    if not row or row.retrieval_status!="COMPLETE" or not row.cached_image_path:raise HTTPException(404,"Species image not cached")
    path=Path(row.cached_image_path)
    if not path.is_file():raise HTTPException(404,"Species image file missing")
    return Response(path.read_bytes(),media_type=row.media_type,headers={"Cache-Control":"public, max-age=86400, immutable","X-Content-Type-Options":"nosniff"})

@router.get("/static/{asset_path:path}",name="static")
async def static_asset(asset_path:str):
    root=(Path(__file__).resolve().parents[1]/"static").resolve();path=(root/asset_path.lstrip("/")).resolve()
    if root not in path.parents or not path.is_file():raise HTTPException(404,"Static asset not found")
    media={".css":"text/css",".js":"text/javascript",".svg":"image/svg+xml"}.get(path.suffix.lower(),"application/octet-stream")
    return Response(path.read_bytes(),media_type=media,headers={"Cache-Control":"public, max-age=3600","X-Content-Type-Options":"nosniff"})
