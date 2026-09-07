from datetime import datetime
from pydantic import BaseModel, Field
class BirdNetDetection(BaseModel):
    source_detection_id: str; species_common: str; species_scientific: str
    detected_at: datetime; confidence: float = Field(ge=0, le=1)
    audio_reference: str|None=None; raw_metadata: dict={}
