import html,re
import httpx

def plain(value):
    if isinstance(value,dict):value=value.get("value")
    if not value:return None
    return html.unescape(re.sub(r"<[^>]+>","",str(value))).strip() or None

class WikimediaCommonsProvider:
    name="Wikimedia Commons"
    def __init__(self,settings,transport=None):
        self.s=settings
        self.http=httpx.AsyncClient(timeout=15,transport=transport,headers={"User-Agent":"BirdCorroborator/1.0 (home dashboard image cache)"})
    async def close(self):await self.http.aclose()
    async def find(self,scientific_name):
        params={"action":"query","format":"json","formatversion":2,"generator":"search","gsrsearch":scientific_name,"gsrnamespace":6,"gsrlimit":1,"prop":"imageinfo","iiprop":"url|mime|extmetadata","iiurlwidth":self.s.image_thumbnail_width,"iiextmetadatafilter":"Artist|Credit|LicenseShortName|LicenseUrl|AttributionRequired"}
        response=await self.http.get(self.s.image_provider_api_url,params=params);response.raise_for_status()
        pages=response.json().get("query",{}).get("pages",[])
        if not pages or not pages[0].get("imageinfo"):return None
        info=pages[0]["imageinfo"][0];meta=info.get("extmetadata",{})
        creator=plain(meta.get("Artist")) or plain(meta.get("Credit"));license_name=plain(meta.get("LicenseShortName"))
        return {"download_url":info.get("thumburl") or info.get("url"),"source_url":info.get("descriptionurl") or info.get("url"),"creator":creator,"license":license_name,"attribution":" · ".join(x for x in (creator,license_name) if x) or "Wikimedia Commons","provider":self.name}
    async def download(self,url):
        async with self.http.stream("GET",url) as response:
            response.raise_for_status();media=response.headers.get("content-type","").split(";",1)[0].lower()
            if media not in {"image/jpeg","image/png","image/webp"}:raise ValueError(f"unsupported image type: {media}")
            declared=int(response.headers.get("content-length",0) or 0)
            if declared>self.s.image_max_bytes:raise ValueError("image exceeds configured size limit")
            chunks=[];size=0
            async for chunk in response.aiter_bytes():
                size+=len(chunk)
                if size>self.s.image_max_bytes:raise ValueError("image exceeds configured size limit")
                chunks.append(chunk)
            return b"".join(chunks),media
