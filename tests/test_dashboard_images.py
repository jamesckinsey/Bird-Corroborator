from datetime import datetime,timedelta,timezone
from pathlib import Path
from io import BytesIO
import httpx,pytest
from PIL import Image
from sqlalchemy import select
from app.db.models import SpeciesImage
from app.images.service import SpeciesImageService,safe_cache_path,species_key,thumbnail_bytes
from app.images.provider import WikimediaCommonsProvider
from app.main import create_app
from tests.test_service_api import FakeBN,FakeBW,detection

class FakeImages:
    def __init__(self,fail=False):self.find_calls=0;self.download_calls=0;self.fail=fail
    async def find(self,scientific):
        self.find_calls+=1
        if self.fail:raise httpx.ConnectError("offline")
        return {"download_url":"https://images.test/bird.jpg","source_url":"https://commons.test/file","creator":"Ada Birder","license":"CC BY-SA 4.0","attribution":"Ada Birder · CC BY-SA 4.0","provider":"Wikimedia Commons"}
    async def download(self,url):
        self.download_calls+=1;buffer=BytesIO();Image.new("RGB",(1200,800),(80,120,90)).save(buffer,"JPEG");return buffer.getvalue(),"image/jpeg"
    async def close(self):pass

@pytest.mark.asyncio
async def test_dashboard_pages_and_placeholder_do_not_call_birdweather(settings):
    class CountingBW(FakeBW):
        def __init__(self):super().__init__();self.calls=0
        async def lookup(self,*args):self.calls+=1;return []
        async def lookup_all(self):self.calls+=1;return []
    bw=CountingBW();app=create_app(settings,FakeBN([detection()]),bw,FakeImages());await app.state.ingestion.poll(True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        for path in ("/","/detections","/species","/system","/static/images/placeholder-bird.svg"):
            response=await client.get(path);assert response.status_code==200,path
        body=(await client.get("/")).text
        assert "Species Summary" in body and "BirdNET 82%" in body and "placeholder-bird.svg" in body
        assert 'class="species-row score-pending"' in body and "species-grid" not in body and "species-card" not in body
        assert "Corroboration score (1–10)" in body and "independent stations" in body and "detections within 10 mi / last 24h" in body
        assert (await client.get("/detections?limit=201")).status_code==422
    assert bw.calls==0

@pytest.mark.asyncio
async def test_species_summary_cache_invalidates_for_new_detection(settings):
    birdnet=FakeBN([detection("first")]);app=create_app(settings,birdnet,FakeBW(),FakeImages());await app.state.ingestion.poll(True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        assert "Second Bird" not in (await client.get("/")).text
        second=detection("second");second.species_common="Second Bird";second.species_scientific="Secondus birdus";birdnet.rows.append(second)
        assert await app.state.ingestion.poll(True)==1
        assert "Second Bird" in (await client.get("/")).text

@pytest.mark.asyncio
async def test_species_image_downloaded_once_and_attribution_stored(settings,tmp_path):
    settings=settings.model_copy(update={"image_cache_dir":str(tmp_path/"images")});provider=FakeImages();app=create_app(settings,FakeBN([detection()]),FakeBW(),provider);await app.state.ingestion.poll(True)
    assert await app.state.image_service.process_one()
    assert not await app.state.image_service.process_one()
    assert provider.find_calls==1 and provider.download_calls==1
    with app.state.sessions() as db:
        row=db.scalar(select(SpeciesImage));assert row.attribution=="Ada Birder · CC BY-SA 4.0" and row.source_provider=="Wikimedia Commons" and Path(row.cached_image_path).is_file() and row.cached_image_path.endswith(".webp") and row.media_type=="image/webp"
        with Image.open(row.cached_image_path) as image:assert image.width==320 and image.height<=320
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        response=await client.get(f"/media/species/{row.species_key}");assert response.status_code==200 and response.headers["cache-control"].startswith("public") and response.headers["content-type"]=="image/webp"
        api=(await client.get("/api/v1/detections/latest")).json()[0];assert api["image_source"]=="Wikimedia Commons" and api["image_url"].startswith("/media/species/")

@pytest.mark.asyncio
async def test_existing_cached_source_is_optimized_once_in_background(settings,tmp_path):
    settings=settings.model_copy(update={"image_cache_dir":str(tmp_path/"images")});app=create_app(settings,FakeBN([detection()]),FakeBW(),FakeImages());await app.state.ingestion.poll(True);app.state.image_service.discover()
    legacy=tmp_path/"legacy.img";buffer=BytesIO();Image.new("RGB",(1400,700),(70,100,80)).save(buffer,"JPEG");legacy.write_bytes(buffer.getvalue())
    with app.state.sessions() as db:
        row=db.scalar(select(SpeciesImage));row.cached_image_path=str(legacy);row.media_type="image/jpeg";row.retrieval_status="COMPLETE";db.commit();key=row.species_key
    assert await app.state.image_service.process_one()
    with app.state.sessions() as db:
        row=db.get(SpeciesImage,key);assert row.cached_image_path.endswith(".webp") and Path(row.cached_image_path).is_file() and row.media_type=="image/webp"
    assert not await app.state.image_service.process_one()

@pytest.mark.asyncio
async def test_failed_image_fetch_does_not_block_ingestion_and_backs_off(settings,tmp_path):
    settings=settings.model_copy(update={"image_cache_dir":str(tmp_path/"images")});provider=FakeImages(fail=True);app=create_app(settings,FakeBN([detection()]),FakeBW(),provider)
    assert await app.state.ingestion.poll(True)==1
    assert not await app.state.image_service.process_one()
    with app.state.sessions() as db:
        row=db.scalar(select(SpeciesImage));assert row.retrieval_status=="RETRY" and row.retry_after>datetime.now(timezone.utc).replace(tzinfo=None)
    assert not await app.state.image_service.process_one() and provider.find_calls==1

def test_image_cache_path_is_deterministic_and_sanitized(tmp_path):
    key=species_key("Falco peregrinus");assert safe_cache_path(tmp_path,key)==safe_cache_path(tmp_path,key) and safe_cache_path(tmp_path,key).suffix==".webp"
    with pytest.raises(ValueError):safe_cache_path(tmp_path,"../../etc/passwd")

def test_thumbnail_is_bounded_and_small_sources_are_not_upscaled():
    large=BytesIO();Image.new("RGB",(1600,900),(20,80,30)).save(large,"JPEG");content,width,height=thumbnail_bytes(large.getvalue());assert (width,height)==(320,180) and len(content)<len(large.getvalue())
    small=BytesIO();Image.new("RGB",(100,60),(20,80,30)).save(small,"PNG");_content,width,height=thumbnail_bytes(small.getvalue());assert (width,height)==(100,60)

def test_no_travel_speed_or_seasonal_scoring_logic():
    source=Path("app/corroboration/scorer.py").read_text().casefold()
    assert "speed" not in source and "season" not in source and "migration" not in source

@pytest.mark.asyncio
async def test_wikimedia_metadata_and_thumbnail_download(settings):
    calls=[];headers=[]
    async def handler(request):
        calls.append(str(request.url));headers.append(request.headers)
        if "w/api.php" in str(request.url):
            payload={"query":{"pages":[{"imageinfo":[{
                "thumburl":"https://upload.test/thumb.jpg",
                "descriptionurl":"https://commons.test/wiki/File:Robin.jpg",
                "mime":"image/jpeg",
                "extmetadata":{"Artist":{"value":"<b>Ada Birder</b>"},"LicenseShortName":{"value":"CC BY 4.0"}},
            }]}]}}
            return httpx.Response(200,json=payload)
        return httpx.Response(200,content=b"small-jpeg",headers={"content-type":"image/jpeg","content-length":"10"})
    provider=WikimediaCommonsProvider(settings,httpx.MockTransport(handler));candidate=await provider.find("Turdus migratorius");data,media=await provider.download(candidate["download_url"]);await provider.close()
    assert candidate["creator"]=="Ada Birder" and candidate["license"]=="CC BY 4.0" and data==b"small-jpeg" and media=="image/jpeg" and len(calls)==2
    assert all(h["user-agent"].startswith("Bird-Corroborator/1.0") for h in headers)

@pytest.mark.asyncio
async def test_wikimedia_403_is_graceful_and_backed_off(settings,tmp_path):
    async def handler(request):return httpx.Response(403,request=request)
    settings=settings.model_copy(update={"image_cache_dir":str(tmp_path/"images")});provider=WikimediaCommonsProvider(settings,httpx.MockTransport(handler));app=create_app(settings,FakeBN([detection()]),FakeBW(),provider);await app.state.ingestion.poll(True)
    assert not await app.state.image_service.process_one()
    with app.state.sessions() as db:
        row=db.scalar(select(SpeciesImage));assert row.retrieval_status=="RETRY" and row.retry_after is not None
    assert not await app.state.image_service.process_one()
    await provider.close()
