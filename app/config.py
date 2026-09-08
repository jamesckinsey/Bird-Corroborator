from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    birdnet_base_url: str = "http://127.0.0.1:8080"
    birdnet_detections_path: str = "/api/v2/detections"
    birdnet_recent_path: str = "/api/v2/detections/recent"
    birdnet_ping_path: str = "/api/v2/ping"
    birdnet_poll_seconds: int = Field(300, ge=10)
    birdnet_catchup_hours: int = Field(12, ge=1)
    birdnet_page_size: int = Field(100, ge=1, le=500)
    birdnet_min_confidence: float = Field(0.70, ge=0, le=1)
    home_latitude: float | None = Field(None, ge=-90, le=90)
    home_longitude: float | None = Field(None, ge=-180, le=180)
    birdweather_graphql_url: str = "https://app.birdweather.com/graphql"
    birdweather_radius_miles: float = Field(10, gt=0, le=100)
    birdweather_lookback_hours: int = Field(24, ge=1, le=168)
    birdweather_cache_minutes: int = Field(15, ge=1, le=1440)
    birdweather_timeout_seconds: float = Field(15, gt=0)
    birdweather_excluded_station_ids: str = ""
    enrichment_retry_seconds: int = Field(900, ge=60)
    enrichment_max_attempts: int = Field(12, ge=1)
    enrichment_concurrency: int = Field(1, ge=1, le=1)
    load_shedding_enabled: bool = True
    load_shedding_threshold: float = Field(3.0, gt=0)
    image_provider_api_url: str = "https://commons.wikimedia.org/w/api.php"
    image_cache_dir: str = "data/species-images"
    image_retry_hours: int = Field(24, ge=1, le=720)
    image_thumbnail_width: int = Field(640, ge=160, le=1280)
    image_max_bytes: int = Field(5_000_000, ge=100_000, le=20_000_000)
    local_timezone: str = "America/New_York"
    database_url: str = "sqlite:///data/birds.db"
    log_level: str = "INFO"
    api_port: int = Field(8000, ge=1, le=65535)
    api_host: str = "0.0.0.0"
    worker_enabled: bool = True

    @field_validator("birdnet_base_url", "birdweather_graphql_url", "image_provider_api_url")
    @classmethod
    def trim_url(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def location_configured(self) -> bool:
        return self.home_latitude is not None and self.home_longitude is not None

    @property
    def birdweather_cache_seconds(self) -> int:
        return self.birdweather_cache_minutes * 60

    @property
    def excluded_station_ids(self) -> frozenset[str]:
        return frozenset(value.strip() for value in self.birdweather_excluded_station_ids.split(",") if value.strip())

@lru_cache
def get_settings() -> Settings:
    return Settings()
