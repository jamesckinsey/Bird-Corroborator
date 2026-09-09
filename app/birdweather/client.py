import logging,math, time
from datetime import datetime
import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from app.birdweather.models import BirdWeatherDetection
from app.config import Settings

QUERY='''query Nearby($first:Int!,$period:InputDuration!,$ne:InputLocation!,$sw:InputLocation!,$speciesId:ID){detections(first:$first,period:$period,ne:$ne,sw:$sw,speciesId:$speciesId,sortBy:"timestamp_desc") {nodes {id timestamp confidence coords {lat lon} species {id commonName scientificName} station {id name coords {lat lon}}}}}'''
SEARCH='''query Search($query:String!){searchSpecies(first:10,query:$query){nodes{id commonName scientificName}}}'''
log=logging.getLogger(__name__)

def haversine_miles(lat1,lon1,lat2,lon2):
    p1,p2=math.radians(lat1),math.radians(lat2); dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 3958.7613*2*math.atan2(math.sqrt(a),math.sqrt(1-a))
def bounding_box(lat,lon,radius):
    dlat=radius/69.0; cos=max(.01,math.cos(math.radians(lat))); dlon=radius/(69.172*cos)
    return {"lat":lat+dlat,"lon":lon+dlon},{"lat":lat-dlat,"lon":lon-dlon}

class BirdWeatherClient:
    def __init__(self,s:Settings,transport=None):
        self.s=s; self.http=httpx.AsyncClient(timeout=s.birdweather_timeout_seconds,transport=transport); self.cache={}; self.species={}
    async def close(self): await self.http.aclose()
    async def _post(self,query,variables):
        r=await self.http.post(self.s.birdweather_graphql_url,json={"query":query,"variables":variables}); r.raise_for_status(); body=r.json()
        if body.get("errors"): raise RuntimeError(str(body["errors"])[:500])
        return body["data"]
    @retry(stop=stop_after_attempt(3),wait=wait_exponential(multiplier=.5,max=4),retry=retry_if_exception_type((httpx.HTTPError,RuntimeError)),reraise=True)
    async def lookup(self,scientific_name:str,common_name:str|None=None):
        if not self.s.location_configured: raise ValueError("HOME_LATITUDE and HOME_LONGITUDE are required")
        key=scientific_name.casefold(); hit=self.cache.get(key)
        if hit and time.monotonic()-hit[0]<self.s.birdweather_cache_seconds:
            log.info("BirdWeather cache hit: %s",common_name or scientific_name);return hit[1]
        log.info("BirdWeather lookup: %s",common_name or scientific_name)
        sid=self.species.get(key)
        if sid is None:
            data=await self._post(SEARCH,{"query":scientific_name}); nodes=data["searchSpecies"]["nodes"]
            exact=next((n for n in nodes if (n.get("scientificName") or "").casefold()==key),None)
            if not exact and common_name: exact=next((n for n in nodes if (n.get("commonName") or "").casefold()==common_name.casefold()),None)
            sid=str(exact["id"]) if exact else ""; self.species[key]=sid
        if not sid: self.cache[key]=(time.monotonic(),[]); return []
        result=await self._geographic_query(sid,common_name,scientific_name)
        self.cache[key]=(time.monotonic(),result); return result
    async def lookup_all(self):
        if not self.s.location_configured: raise ValueError("HOME_LATITUDE and HOME_LONGITUDE are required")
        key="__all__";hit=self.cache.get(key)
        if hit and time.monotonic()-hit[0]<self.s.birdweather_cache_seconds:return hit[1]
        result=await self._geographic_query(None,None,None);self.cache[key]=(time.monotonic(),result);return result
    @retry(stop=stop_after_attempt(3),wait=wait_exponential(multiplier=.5,max=4),retry=retry_if_exception_type((httpx.HTTPError,RuntimeError)),reraise=True)
    async def _geographic_query(self,sid,common_name,scientific_name):
        ne,sw=bounding_box(self.s.home_latitude,self.s.home_longitude,self.s.birdweather_radius_miles)
        data=await self._post(QUERY,{"first":500,"period":{"count":self.s.birdweather_lookback_hours,"unit":"hour"},"ne":ne,"sw":sw,"speciesId":sid})
        result=[]
        for n in data["detections"]["nodes"]:
            coords=n.get("coords") or (n.get("station") or {}).get("coords")
            if not coords: continue
            distance=haversine_miles(self.s.home_latitude,self.s.home_longitude,coords["lat"],coords["lon"])
            if distance>self.s.birdweather_radius_miles: continue
            dt=datetime.fromisoformat(n["timestamp"].replace("Z","+00:00")); sp=n["species"]; station=n.get("station") or {};station_id=str(station.get("id","unknown"))
            species_name=sp.get("scientificName") or scientific_name or sp.get("commonName") or "Unknown"
            log.debug("BirdWeather observation: station_id=%s species=%s distance=%.1fmi detected_at=%s excluded=%s",station_id,species_name,distance,dt.isoformat(),station_id in self.s.excluded_station_ids)
            if station_id in self.s.excluded_station_ids:continue
            result.append(BirdWeatherDetection(source_detection_id=str(n["id"]),station_id=station_id,station_name=station.get("name"),species_common=sp.get("commonName") or common_name or scientific_name or "Unknown",species_scientific=species_name,detected_at=dt,latitude=coords["lat"],longitude=coords["lon"],distance_miles=distance,source_confidence=n.get("confidence")))
        stations={item.station_id for item in result}
        log.info("BirdWeather lookup complete: species=%s stations=%s observations=%s radius=%.1fmi lookback=%sh",scientific_name or "all",len(stations),len(result),self.s.birdweather_radius_miles,self.s.birdweather_lookback_hours)
        return result
