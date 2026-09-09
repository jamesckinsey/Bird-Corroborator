from datetime import datetime
from pydantic import BaseModel, ConfigDict
class MatchOut(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    station_id:str;station_name:str|None;species_common:str;species_scientific:str;detected_at:datetime;distance_miles:float;source_confidence:float|None
class CorroborationOut(BaseModel):
    birdnet_confidence:float;corroboration_score:int|None;corroboration_level:str|None;unique_nearby_stations:int;matching_detections:int;nearest_match_miles:float|None;closest_time_difference_minutes:float|None;algorithm_version:str|None
class DetectionOut(BaseModel):
    id:int;source:str;source_detection_id:str;species_common:str;species_scientific:str;detected_at:datetime;birdnet_confidence:float;audio_reference:str|None;enrichment_state:str;corroboration:CorroborationOut
    image_url:str|None=None;image_attribution:str|None=None;image_source:str|None=None
class DetectionDetail(DetectionOut): nearby_matches:list[MatchOut]
class StatusOut(BaseModel):
    status:str;birdnet_connected:bool;birdweather_available:bool;last_birdnet_poll:datetime|None;last_birdweather_request:datetime|None;database_ok:bool
    birdnet_ingestion_ok:bool=False;birdnet_ingestion_error:str|None=None;last_birdnet_response:datetime|None=None
    pending_enrichments:int=0;retry_enrichments:int=0;process_memory_mb:float|None=None;process_cpu_percent:float|None=None;system_load_1m:float|None=None;cpu_temperature_c:float|None=None;available_memory_mb:float|None=None;system_uptime_seconds:float|None=None
class SpeciesSummary(BaseModel):
    species_common:str;species_scientific:str;local_detection_count:int;highest_birdnet_confidence:float;latest_detection:datetime;best_corroboration_level:str|None;nearby_unique_stations:int
    nearby_total_detections:int=0;best_corroboration_score:int|None=None;display_corroboration_score:int|None=None
    image_url:str|None=None;image_attribution:str|None=None;image_source:str|None=None
class NearbySummary(BaseModel):
    species_common:str;species_scientific:str;nearby_unique_stations:int;nearest_station_miles:float;most_recent_detection:datetime
