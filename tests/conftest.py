import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from config import Config  # noqa: E402


@pytest.fixture
def test_config(tmp_path):
    class TestConfig(Config):
        TESTING = True
        DATABASE_PATH = str(tmp_path / "test.db")
        MQTT_ENABLED = False
        MOISTURE_THRESHOLD = 60.0
        FILL_LOW_THRESHOLD = 30.0
        FILL_HIGH_THRESHOLD = 80.0
        FILL_INCREMENT = 5.0

    return TestConfig


@pytest.fixture
def app(test_config):
    return create_app(test_config, start_mqtt=False)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def system(app):
    return app.extensions["waste_system"]
