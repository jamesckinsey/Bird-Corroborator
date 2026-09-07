from datetime import datetime,timezone
import httpx,pytest
from app.birdnet.client import BirdNetClient
from app.birdweather.client import BirdWeatherClient
@pytest.mark.asyncio
async def test_birdnet_parse_and_catchup(settings):
    async def handler(req):return httpx.Response(200,json={"detections":[{"id":7,"timestamp":"2026-09-03T18:00:00Z","commonName":"Robin","scientificName":"Turdus migratorius","confidence":.91,"clipName":"x.wav"}]})
    c=BirdNetClient(settings,httpx.MockTransport(handler));rows=await c.recent(datetime(2026,9,3,tzinfo=timezone.utc),catchup=True);await c.close();assert rows[0].source_detection_id=="7" and rows[0].audio_reference=="x.wav"
@pytest.mark.asyncio
async def test_birdnet_outage(settings):
    async def handler(req):return httpx.Response(503)
    c=BirdNetClient(settings,httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):await c.recent(datetime.now(timezone.utc))
    await c.close()
@pytest.mark.asyncio
async def test_birdweather_graphql_and_radius(settings):
    calls=0
    async def handler(req):
        nonlocal calls;calls+=1
        if calls==1:return httpx.Response(200,json={"data":{"searchSpecies":{"nodes":[{"id":"1","commonName":"Robin","scientificName":"Turdus migratorius"}]}}})
        return httpx.Response(200,json={"data":{"detections":{"nodes":[{"id":"9","timestamp":"2026-09-03T18:00:00Z","confidence":.8,"coords":{"lat":40.01,"lon":-75},"species":{"commonName":"Robin","scientificName":"Turdus migratorius"},"station":{"id":"s1","name":"Yard"}}]}}})
    c=BirdWeatherClient(settings,httpx.MockTransport(handler));rows=await c.lookup("Turdus migratorius","Robin");again=await c.lookup("Turdus migratorius","Robin");await c.close();assert rows[0].station_id=="s1" and calls==2 and again==rows
@pytest.mark.asyncio
async def test_birdweather_outage(settings):
    async def handler(req):raise httpx.ConnectError("offline",request=req)
    c=BirdWeatherClient(settings,httpx.MockTransport(handler))
    with pytest.raises(httpx.ConnectError):await c.lookup("X","Y")
    await c.close()
