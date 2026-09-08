import asyncio,hashlib,logging,time
from io import BytesIO
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sqlalchemy import func,or_,select
from app.db.models import LocalDetection,SpeciesImage
from app.system_metrics import load_is_high
from PIL import Image,ImageOps
log=logging.getLogger(__name__)
DASHBOARD_THUMBNAIL_WIDTH=320

def species_key(scientific_name):return hashlib.sha256(scientific_name.casefold().strip().encode()).hexdigest()[:24]
def safe_cache_path(cache_dir,key):
    if not re_full_key(key):raise ValueError("invalid species image key")
    root=Path(cache_dir).resolve();path=(root/f"{key}.webp").resolve()
    if root not in path.parents:raise ValueError("unsafe cache path")
    return path
def re_full_key(key):return len(key)==24 and all(c in "0123456789abcdef" for c in key)
def thumbnail_bytes(content,max_width=DASHBOARD_THUMBNAIL_WIDTH):
    with Image.open(BytesIO(content)) as source:
        image=ImageOps.exif_transpose(source);image.thumbnail((max_width,max_width),Image.Resampling.LANCZOS)
        if image.mode not in {"RGB","RGBA"}:image=image.convert("RGB")
        output=BytesIO();image.save(output,format="WEBP",quality=78,method=4)
        return output.getvalue(),image.width,image.height

class SpeciesImageService:
    def __init__(self,sessions,provider,settings):self.sessions=sessions;self.provider=provider;self.s=settings;self.last_error=None
    def discover(self):
        with self.sessions() as db:
            species=db.execute(select(LocalDetection.species_scientific,func.max(LocalDetection.species_common)).group_by(LocalDetection.species_scientific)).all()
            existing=set(db.scalars(select(SpeciesImage.species_scientific)))
            for scientific,common in species:
                if scientific not in existing:db.add(SpeciesImage(species_key=species_key(scientific),species_scientific=scientific,species_common=common,retrieval_status="PENDING",retry_after=datetime.now(timezone.utc)))
            db.commit()
    async def process_one(self):
        if load_is_high(self.s):return False
        self.discover();now=datetime.now(timezone.utc)
        if self.optimize_existing_one():return True
        with self.sessions() as db:
            row=db.scalar(select(SpeciesImage).where(SpeciesImage.retrieval_status!="COMPLETE",or_(SpeciesImage.retry_after==None,SpeciesImage.retry_after<=now)).order_by(SpeciesImage.retry_after).limit(1))
            if not row:return False
            key=row.species_key;scientific=row.species_scientific;row.last_retrieval_attempt=now;db.commit()
        try:
            candidate=await self.provider.find(scientific)
            if not candidate:raise LookupError("no Wikimedia Commons image found")
            content,_media=await self.provider.download(candidate["download_url"]);thumbnail,_width,_height=thumbnail_bytes(content);path=safe_cache_path(self.s.image_cache_dir,key);path.parent.mkdir(parents=True,exist_ok=True)
            temporary=path.with_suffix(".tmp");temporary.write_bytes(thumbnail);temporary.replace(path)
            with self.sessions() as db:
                row=db.get(SpeciesImage,key);row.cached_image_path=str(path);row.media_type="image/webp";row.source_url=candidate["source_url"];row.source_provider=candidate["provider"];row.creator=candidate["creator"];row.license=candidate["license"];row.attribution=candidate["attribution"];row.retrieval_status="COMPLETE";row.retrieved_at=now;row.retry_after=None;row.error_message=None;db.commit()
            getattr(self,"invalidate_summary",lambda:None)()
            return True
        except Exception as exc:
            self.last_error=str(exc)[:500];log.warning("Species image unavailable for %s: %s",scientific,exc)
            with self.sessions() as db:
                row=db.get(SpeciesImage,key);row.retrieval_status="RETRY";row.error_message=self.last_error;row.retry_after=now+timedelta(hours=self.s.image_retry_hours);db.commit()
            return False
    def optimize_existing_one(self):
        with self.sessions() as db:
            row=db.scalar(select(SpeciesImage).where(SpeciesImage.retrieval_status=="COMPLETE",SpeciesImage.cached_image_path.is_not(None),SpeciesImage.cached_image_path.not_like("%.webp")).limit(1))
            if not row:return False
            old_path=Path(row.cached_image_path);key=row.species_key
            try:
                thumbnail,_width,_height=thumbnail_bytes(old_path.read_bytes());path=safe_cache_path(self.s.image_cache_dir,key);path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix(".tmp");temporary.write_bytes(thumbnail);temporary.replace(path)
                row.cached_image_path=str(path);row.media_type="image/webp";db.commit();getattr(self,"invalidate_summary",lambda:None)();log.info("Optimized cached species image: %s",row.species_scientific);return True
            except Exception as exc:
                self.last_error=str(exc)[:500];row.retrieval_status="RETRY";row.cached_image_path=None;row.media_type=None;row.retry_after=datetime.now(timezone.utc);row.error_message=self.last_error;db.commit();return False
    async def run(self):
        log.info("serialized species image worker started")
        while True:
            try:worked=await self.process_one();await asyncio.sleep(5 if worked else 60)
            except asyncio.CancelledError:raise
            except Exception as exc:self.last_error=str(exc)[:500];log.warning("Species image worker deferred: %s",exc);await asyncio.sleep(60)
