from pathlib import Path
import pytest
from app.config import Settings
@pytest.fixture
def settings(tmp_path:Path):
    return Settings(database_url=f"sqlite:///{tmp_path}/test.db",birdnet_base_url="http://birdnet",home_latitude=40,home_longitude=-75,worker_enabled=False,local_timezone="America/New_York")
