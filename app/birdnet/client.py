import hashlib, json
from datetime import datetime, timezone
import httpx
from app.birdnet.models import BirdNetDetection
from app.config import Settings

class BirdNetClient:
    def __init__(self, settings: Settings, transport=None):
        self.s=settings; self.http=httpx.AsyncClient(base_url=settings.birdnet_base_url, timeout=15, transport=transport)
    async def close(self): await self.http.aclose()
    async def ping(self):
        r=await self.http.get(self.s.birdnet_ping_path); r.raise_for_status(); return True
    async def recent(self, since: datetime, catchup: bool = False) -> list[BirdNetDetection]:
        if not catchup:
            # The documented recent endpoint is the cheapest normal poll. Stable IDs and
            # the persisted timestamp checkpoint make its overlap safe and idempotent.
            r=await self.http.get(self.s.birdnet_recent_path,params={"limit":self.s.birdnet_page_size,"includeWeather":"false"})
            r.raise_for_status();payload=r.json();rows=payload.get("detections",payload.get("data",payload if isinstance(payload,list) else []))
            if isinstance(rows,dict):rows=rows.get("items",rows.get("detections",[]))
            return [item for row in rows if (item:=self._parse(row)).detected_at>=since]
        # Catch-up uses the date-ranged historical endpoint. The path remains configurable.
        params={"start_date":since.date().isoformat(),"limit":self.s.birdnet_page_size,"offset":0,"sort":"desc"}
        out=[]
        for _page in range(20):
            r=await self.http.get(self.s.birdnet_detections_path, params=params); r.raise_for_status(); payload=r.json()
            rows=payload.get("detections", payload.get("data", payload if isinstance(payload,list) else []))
            if isinstance(rows,dict): rows=rows.get("items",rows.get("detections",[]))
            for row in rows:
                item=self._parse(row)
                if item.detected_at >= since: out.append(item)
            if len(rows)<params["limit"]: break
            params["offset"] += params["limit"]
        return out
    @staticmethod
    def _parse(row: dict) -> BirdNetDetection:
        raw_ts=row.get("timestamp") or row.get("beginTime")
        if not raw_ts and row.get("date") and row.get("time"): raw_ts=f'{row["date"]}T{row["time"]}'
        dt=datetime.fromisoformat(str(raw_ts).replace("Z","+00:00"))
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        common=row.get("commonName") or row.get("common_name") or row.get("species",{}).get("commonName")
        scientific=row.get("scientificName") or row.get("scientific_name") or row.get("species",{}).get("scientificName")
        source_id=row.get("id") or row.get("ID")
        if source_id is None:
            stable=json.dumps([scientific or common,dt.isoformat(),row.get("source","")],separators=(",",":"))
            source_id="sha256:"+hashlib.sha256(stable.encode()).hexdigest()
        clip=row.get("clipName") or row.get("audio_reference") or row.get("audioUrl")
        return BirdNetDetection(source_detection_id=str(source_id),species_common=common or scientific,
          species_scientific=scientific or common,detected_at=dt,confidence=float(row.get("confidence",0)),audio_reference=clip,raw_metadata=row)
