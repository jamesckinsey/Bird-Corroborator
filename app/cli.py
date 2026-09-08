import argparse,asyncio
from datetime import datetime,timezone
from pathlib import Path
from sqlalchemy import delete,func,select,update
from app.birdnet.client import BirdNetClient
from app.birdweather.client import BirdWeatherClient
from app.config import get_settings
from app.main import create_app
from app.database import make_engine,make_session_factory
from app.db.models import LocalDetection,SpeciesImage
from app.migrations import initialize_database
async def catchup(hours:int):
    settings=get_settings().model_copy(update={"worker_enabled":False,"birdnet_catchup_hours":hours})
    bn=BirdNetClient(settings);bw=BirdWeatherClient(settings);app=create_app(settings,bn,bw)
    try:print(f"Imported {await app.state.ingestion.poll(catchup=True,hours=hours)} new detections")
    finally:await bn.close();await bw.close()
def main():
    parser=argparse.ArgumentParser(description="Bird Corroborator maintenance")
    sub=parser.add_subparsers(dest="command",required=True);p=sub.add_parser("catchup",help="manually import a larger BirdNET history window");p.add_argument("--hours",type=int,required=True);sub.add_parser("images-reset",help="move cached image files aside and queue every species for retrieval");purge=sub.add_parser("purge-low-confidence",help="purge historical detections below BIRDNET_MIN_CONFIDENCE");purge.add_argument("--yes",action="store_true",help="perform the purge (otherwise report only)")
    args=parser.parse_args()
    if args.command=="catchup":asyncio.run(catchup(args.hours))
    elif args.command=="images-reset":reset_images()
    elif args.command=="purge-low-confidence":purge_low_confidence(args.yes)
def reset_images():
    settings=get_settings();cache=Path(settings.image_cache_dir)
    if cache.exists():
        backup=cache.with_name(f"{cache.name}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}");cache.rename(backup);print(f"Moved cached files to {backup}")
    engine=make_engine(settings);initialize_database(engine);sessions=make_session_factory(engine)
    with sessions() as db:
        db.execute(update(SpeciesImage).values(cached_image_path=None,media_type=None,retrieval_status="PENDING",retry_after=datetime.now(timezone.utc),error_message=None));db.commit()
    engine.dispose();print("Queued species images for low-priority retrieval")
def purge_low_confidence(confirm=False):
    settings=get_settings();engine=make_engine(settings);initialize_database(engine);sessions=make_session_factory(engine)
    with sessions() as db:
        condition=LocalDetection.confidence<settings.birdnet_min_confidence
        count=db.scalar(select(func.count()).select_from(LocalDetection).where(condition)) or 0
        if confirm:
            db.execute(delete(LocalDetection).where(condition));db.commit();print(f"Purged {count} detections below {settings.birdnet_min_confidence:.0%}")
        else:print(f"Would purge {count} detections below {settings.birdnet_min_confidence:.0%}; rerun with --yes to proceed")
    engine.dispose()
if __name__=="__main__":main()
