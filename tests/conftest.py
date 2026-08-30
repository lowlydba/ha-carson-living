"""Configuration for Ring tests."""
import asyncio
import sys
import pytest
import pytest_socket
import requests_mock

from .common import (
    CARSON_API_VERSION,
    carson_load_fixture,
    fixture_building_id,
    fixture_een_subdomain,
)


if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if sys.platform == "win32":
    pytest_socket.disable_socket = lambda allow_unix_socket=False: None


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom_components during tests."""
    yield enable_custom_integrations


@pytest.fixture(name="success_requests_mock")
def requests_mock_fixture():
    """Fixture to provide a requests mocker."""
    with requests_mock.mock() as mock:
        # Default success Mock responses
        # Carson API
        mock.post(
            f"https://api.carson.live/api/v{CARSON_API_VERSION}/auth/login/",
            text=carson_load_fixture("carson_login.json"),
        )

        mock.get(
            f"https://api.carson.live/api/v{CARSON_API_VERSION}/me/",
            text=carson_load_fixture("carson_me.json"),
        )

        building_id = fixture_building_id()
        mock.get(
            f"https://api.carson.live/api/v{CARSON_API_VERSION}/properties/buildings/{building_id}/eagleeye/session/",
            text=carson_load_fixture("carson_eagleeye_session.json"),
        )

        # Eagle Eye API
        een_subdomain = fixture_een_subdomain()
        mock.get(
            f"https://{een_subdomain}.eagleeyenetworks.com/g/device/list",
            text=carson_load_fixture("een_device_list.json"),
        )

        yield mock
