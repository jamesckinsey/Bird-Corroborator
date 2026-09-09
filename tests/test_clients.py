from datetime import datetime,timezone
import httpx,pytest
from app.birdnet.client import BirdNetClient
from app.birdweather.client import BirdWeatherClient
@pytest.mark.asyncio
async def test_birdnet_parse_and_catchup(settings):
    async def handler(req):return httpx.Response(200,json={"detections":[{"id":7,"timestamp":"2026-09-03T18:00:00Z","commonName":"Robin","scientificName":"Turdus migratorius","confidence":.91,"clipName":"x.wav"}]})
    c=BirdNetClient(settings,httpx.MockTransport(handler));rows=await c.recent(datetime(2026,9,3,tzinfo=timezone.utc),catchup=True);await c.close();assert rows[0].source_detection_id=="7" and rows[0].audio_reference=="x.wav"
@pytest.mark.asyncio
async def test_birdnet_recent_accepts_top_level_list(settings):
    async def handler(req):return httpx.Response(200,json=[{"id":8,"timestamp":"2026-09-03T18:00:00Z","commonName":"Robin","scientificName":"Turdus migratorius","confidence":.72}])
    client=BirdNetClient(settings,httpx.MockTransport(handler));rows=await client.recent(datetime(2026,9,3,tzinfo=timezone.utc));await client.close()
    assert [row.source_detection_id for row in rows]==["8"]
@pytest.mark.asyncio
async def test_birdnet_uses_configured_remote_lan_base_url(settings):
    settings=settings.model_copy(update={"birdnet_base_url":"http://birdnet-remote.test:8080"});seen=[]
    async def handler(req):seen.append(req.url);return httpx.Response(200,json=[])
    client=BirdNetClient(settings,httpx.MockTransport(handler));await client.recent(datetime(2026,9,3,tzinfo=timezone.utc));await client.close()
    assert seen[0].host=="birdnet-remote.test" and seen[0].port==8080 and seen[0].path==settings.birdnet_recent_path
@pytest.mark.asyncio
@pytest.mark.parametrize("payload",[{"results":[]},{"detections":[]},{"data":{"items":[]}}])
async def test_birdnet_recent_accepts_compatible_object_wrappers(settings,payload):
    async def handler(req):return httpx.Response(200,json=payload)
    client=BirdNetClient(settings,httpx.MockTransport(handler));assert await client.recent(datetime(2026,9,3,tzinfo=timezone.utc))==[];await client.close()
@pytest.mark.asyncio
async def test_birdnet_malformed_response_warns_instead_of_being_swallowed(settings,caplog):
    async def handler(req):return httpx.Response(200,json={"unexpected":[]})
    caplog.set_level("WARNING");client=BirdNetClient(settings,httpx.MockTransport(handler))
    with pytest.raises(ValueError):await client.recent(datetime(2026,9,3,tzinfo=timezone.utc))
    await client.close();assert "BirdNET recent response could not be parsed" in caplog.text
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

@pytest.mark.asyncio
async def test_birdweather_excludes_stable_station_id_and_logs_diagnostics(settings,caplog):
    settings=settings.model_copy(update={"birdweather_excluded_station_ids":"self-1,self-2"});calls=0
    async def handler(req):
        nonlocal calls;calls+=1
        if calls==1:return httpx.Response(200,json={"data":{"searchSpecies":{"nodes":[{"id":"1","commonName":"Robin","scientificName":"Turdus migratorius"}]}}})
        node=lambda id_,station:{"id":id_,"timestamp":"2026-09-03T18:00:00Z","confidence":.8,"coords":{"lat":40.01,"lon":-75},"species":{"commonName":"Robin","scientificName":"Turdus migratorius"},"station":{"id":station,"name":"Yard"}}
        return httpx.Response(200,json={"data":{"detections":{"nodes":[node("9","self-1"),node("10","other")]}}})
    caplog.set_level("DEBUG");client=BirdWeatherClient(settings,httpx.MockTransport(handler));rows=await client.lookup("Turdus migratorius","Robin");await client.close()
    assert [row.station_id for row in rows]==["other"]
    assert "station_id=self-1" in caplog.text and "excluded=True" in caplog.text
    assert "BirdWeather lookup complete: species=Turdus migratorius stations=1 observations=1" in caplog.text
