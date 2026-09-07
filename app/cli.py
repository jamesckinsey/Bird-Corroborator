import argparse,asyncio
from app.birdnet.client import BirdNetClient
from app.birdweather.client import BirdWeatherClient
from app.config import get_settings
from app.main import create_app
async def catchup(hours:int):
    settings=get_settings().model_copy(update={"worker_enabled":False,"birdnet_catchup_hours":hours})
    bn=BirdNetClient(settings);bw=BirdWeatherClient(settings);app=create_app(settings,bn,bw)
    try:print(f"Imported {await app.state.ingestion.poll(catchup=True,hours=hours)} new detections")
    finally:await bn.close();await bw.close()
def main():
    parser=argparse.ArgumentParser(description="Bird Corroborator maintenance")
    sub=parser.add_subparsers(dest="command",required=True);p=sub.add_parser("catchup",help="manually import a larger BirdNET history window");p.add_argument("--hours",type=int,required=True)
    args=parser.parse_args()
    if args.command=="catchup":asyncio.run(catchup(args.hours))
if __name__=="__main__":main()
