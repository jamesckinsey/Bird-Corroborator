from datetime import datetime
from pydantic import BaseModel
class BirdWeatherDetection(BaseModel):
    source_detection_id:str; station_id:str; station_name:str|None=None
    species_common:str; species_scientific:str; detected_at:datetime
    latitude:float; longitude:float; distance_miles:float=0; source_confidence:float|None=None
