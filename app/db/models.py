from datetime import datetime, timezone
from enum import StrEnum
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

def utcnow(): return datetime.now(timezone.utc)
class EnrichmentState(StrEnum): PENDING="PENDING"; COMPLETE="COMPLETE"; TEMPORARILY_UNAVAILABLE="TEMPORARILY_UNAVAILABLE"

class LocalDetection(Base):
    __tablename__="local_detections"
    id: Mapped[int]=mapped_column(primary_key=True)
    source: Mapped[str]=mapped_column(String(32), default="birdnet-go")
    source_detection_id: Mapped[str]=mapped_column(String(128), unique=True, index=True)
    species_common: Mapped[str]=mapped_column(String(200), index=True)
    species_scientific: Mapped[str]=mapped_column(String(200), index=True)
    detected_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), index=True)
    confidence: Mapped[float]=mapped_column(Float)
    audio_reference: Mapped[str|None]=mapped_column(String(500))
    raw_metadata: Mapped[dict]=mapped_column(JSON, default=dict)
    ingested_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)
    enrichment_state: Mapped[str]=mapped_column(String(32), default=EnrichmentState.PENDING, index=True)
    enrichment_attempts: Mapped[int]=mapped_column(Integer, default=0)
    next_enrichment_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True), default=utcnow)
    enrichment_error: Mapped[str|None]=mapped_column(String(500))
    matches: Mapped[list["BirdWeatherMatch"]]=relationship(cascade="all, delete-orphan", back_populates="detection")
    corroboration: Mapped["CorroborationResult|None"]=relationship(cascade="all, delete-orphan", back_populates="detection", uselist=False)

class BirdWeatherMatch(Base):
    __tablename__="birdweather_matches"; __table_args__=(UniqueConstraint("local_detection_id","source_detection_id"),)
    id: Mapped[int]=mapped_column(primary_key=True)
    local_detection_id: Mapped[int]=mapped_column(ForeignKey("local_detections.id", ondelete="CASCADE"), index=True)
    source_detection_id: Mapped[str]=mapped_column(String(128))
    station_id: Mapped[str]=mapped_column(String(128), index=True)
    station_name: Mapped[str|None]=mapped_column(String(200))
    species_common: Mapped[str]=mapped_column(String(200), index=True)
    species_scientific: Mapped[str]=mapped_column(String(200))
    detected_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), index=True)
    latitude: Mapped[float]=mapped_column(Float); longitude: Mapped[float]=mapped_column(Float)
    distance_miles: Mapped[float]=mapped_column(Float); source_confidence: Mapped[float|None]=mapped_column(Float)
    ingested_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)
    detection: Mapped[LocalDetection]=relationship(back_populates="matches")

class CorroborationResult(Base):
    __tablename__="corroboration_results"
    id: Mapped[int]=mapped_column(primary_key=True)
    local_detection_id: Mapped[int]=mapped_column(ForeignKey("local_detections.id", ondelete="CASCADE"), unique=True)
    score: Mapped[int]; classification: Mapped[str]=mapped_column(String(32), index=True)
    unique_station_count: Mapped[int]; match_count: Mapped[int]
    nearest_match_distance: Mapped[float|None]; closest_time_difference_minutes: Mapped[float|None]
    has_before_and_after: Mapped[bool]=mapped_column(default=False)
    algorithm_version: Mapped[str]=mapped_column(String(20), default="v1")
    calculated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)
    detection: Mapped[LocalDetection]=relationship(back_populates="corroboration")

class NearbyObservation(Base):
    __tablename__="nearby_observations"
    source_detection_id: Mapped[str]=mapped_column(String(128), primary_key=True)
    station_id: Mapped[str]=mapped_column(String(128), index=True); station_name: Mapped[str|None]
    species_common: Mapped[str]=mapped_column(String(200), index=True); species_scientific: Mapped[str]
    detected_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), index=True)
    distance_miles: Mapped[float]; source_confidence: Mapped[float|None]
    ingested_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)
class AppState(Base):
    __tablename__="app_state"
    key: Mapped[str]=mapped_column(String(100),primary_key=True)
    value: Mapped[str]=mapped_column(String(500))
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,onupdate=utcnow)
class SpeciesImage(Base):
    __tablename__="species_images"
    species_key: Mapped[str]=mapped_column(String(64),primary_key=True)
    species_common: Mapped[str]=mapped_column(String(200))
    species_scientific: Mapped[str]=mapped_column(String(200),unique=True,index=True)
    cached_image_path: Mapped[str|None]=mapped_column(String(500))
    media_type: Mapped[str|None]=mapped_column(String(100))
    source_url: Mapped[str|None]=mapped_column(String(1000))
    source_provider: Mapped[str|None]=mapped_column(String(100))
    creator: Mapped[str|None]=mapped_column(String(500))
    license: Mapped[str|None]=mapped_column(String(500))
    attribution: Mapped[str|None]=mapped_column(String(1000))
    retrieval_status: Mapped[str]=mapped_column(String(32),default="PENDING",index=True)
    last_retrieval_attempt: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    retry_after: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    error_message: Mapped[str|None]=mapped_column(String(500))
Index("ix_local_species_time", LocalDetection.species_scientific, LocalDetection.detected_at)
