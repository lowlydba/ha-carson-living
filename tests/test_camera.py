"""Tests for the Carson Camera platform."""
from datetime import timedelta
from unittest.mock import patch

from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
from homeassistant.helpers import entity_registry as er
import homeassistant.util.dt as dt_util

from .common import (
    CARSON_API_VERSION,
    carson_load_fixture,
    fixture_building_id,
    fixture_een_subdomain,
    setup_platform,
)


async def test_entity_registry(hass, success_requests_mock):  # pylint: disable=unused-argument
    """Tests that the devices are registered in the entity registry."""
    await setup_platform(hass, CAMERA_DOMAIN)
    entity_registry = er.async_get(hass)

    entry = entity_registry.async_get("camera.camera_name_1")
    assert entry.unique_id == "eagleeye_camera_c0"
    entry = entity_registry.async_get("camera.camera_name_2")
    assert entry.unique_id == "eagleeye_camera_c1"
    entry = entity_registry.async_get("camera.camera_name_3")
    # camera.camera_name_3 does NOT exist
    assert entry is None


async def test_entity_registry_een_option_enabled(hass, success_requests_mock):  # pylint: disable=unused-argument
    """Tests that the devices are registered in the entity registry."""
    with patch(
        "custom_components.carson_living.camera.get_list_een_option", return_value=True
    ) as mock_setup:
        await setup_platform(hass, CAMERA_DOMAIN)
        entity_registry = er.async_get(hass)

        entry = entity_registry.async_get("camera.camera_name_1")
        assert entry.unique_id == "eagleeye_camera_c0"
        entry = entity_registry.async_get("camera.camera_name_2")
        assert entry.unique_id == "eagleeye_camera_c1"
        entry = entity_registry.async_get("camera.camera_name_3")
        # camera.camera_name_3 exists
        assert entry.unique_id == "eagleeye_camera_c2"
        assert mock_setup.call_count == 1


async def test_camera_can_be_updated(hass, success_requests_mock):
    """Tests that the camera returns a binary image."""
    await setup_platform(hass, CAMERA_DOMAIN)

    state = hass.states.get("camera.camera_name_1")
    assert state.attributes.get("friendly_name") == "Camera Name 1"

    een_subdomain = fixture_een_subdomain()
    success_requests_mock.get(
        f"https://{een_subdomain}.eagleeyenetworks.com/g/device/list",
        text=carson_load_fixture("een_device_list_update.json"),
    )

    await hass.services.async_call("carson_living", "update", {})

    await hass.async_block_till_done()

    state = hass.states.get("camera.camera_name_1")
    assert state.attributes.get("friendly_name") == "Camera Name 1 Updated"


async def test_camera_returns_image(hass, success_requests_mock):
    """Test that a camera returns in binary image."""
    await setup_platform(hass, CAMERA_DOMAIN)
    component = hass.data.get(CAMERA_DOMAIN)

    data = b"image as binary data"
    een_subdomain = fixture_een_subdomain()
    success_requests_mock.get(
        f"https://{een_subdomain}.eagleeyenetworks.com/asset/prev/image.jpeg",
        content=data,
    )

    camera = component.get_entity("camera.camera_name_1")

    img = camera.camera_image()

    assert img is not None
    assert data == img


async def test_camera_image_is_throttled(hass, success_requests_mock):
    """Test that a repeat call within the throttle window returns cached bytes."""
    await setup_platform(hass, CAMERA_DOMAIN)
    component = hass.data.get(CAMERA_DOMAIN)

    data = b"image as binary data"
    een_subdomain = fixture_een_subdomain()
    image_mock = success_requests_mock.get(
        f"https://{een_subdomain}.eagleeyenetworks.com/asset/prev/image.jpeg",
        content=data,
    )

    camera = component.get_entity("camera.camera_name_1")

    first = camera.camera_image()
    second = camera.camera_image()

    assert first == data
    assert second == data
    assert image_mock.call_count == 1


async def test_camera_image_refetches_after_throttle_window(hass, success_requests_mock):
    """Test that a new image is fetched once the throttle window has elapsed."""
    await setup_platform(hass, CAMERA_DOMAIN)
    component = hass.data.get(CAMERA_DOMAIN)

    data = b"image as binary data"
    een_subdomain = fixture_een_subdomain()
    image_mock = success_requests_mock.get(
        f"https://{een_subdomain}.eagleeyenetworks.com/asset/prev/image.jpeg",
        content=data,
    )

    camera = component.get_entity("camera.camera_name_1")

    now = dt_util.utcnow()
    with patch("custom_components.carson_living.camera.dt_util.utcnow", return_value=now):
        camera.camera_image()

    later = now + timedelta(seconds=11)
    with patch("custom_components.carson_living.camera.dt_util.utcnow", return_value=later):
        camera.camera_image()

    assert image_mock.call_count == 2


async def test_setup_continues_when_eagleeye_session_is_unavailable(
    hass, success_requests_mock, caplog
):
    """A malformed Eagle Eye session response shouldn't fail camera setup."""
    building_id = fixture_building_id()
    success_requests_mock.get(
        f"https://api.carson.live/api/v{CARSON_API_VERSION}/properties/"
        f"buildings/{building_id}/eagleeye/session/",
        text="",
    )

    await setup_platform(hass, CAMERA_DOMAIN)

    entity_registry = er.async_get(hass)
    assert entity_registry.async_get("camera.camera_name_1") is None
    assert "unable to update Eagle Eye session" in caplog.text


async def test_camera_returns_stream_url(hass, success_requests_mock):
    """Test that the camera returns stream URL."""
    await setup_platform(hass, CAMERA_DOMAIN)
    component = hass.data.get(CAMERA_DOMAIN)

    camera = component.get_entity("camera.camera_name_1")

    een_subdomain = fixture_een_subdomain()
    success_requests_mock.get(
        f"https://{een_subdomain}.eagleeyenetworks.com/g/aaa/isauth", text="true"
    )

    url = await camera.stream_source()

    assert f"https://{een_subdomain}.eagleeyenetworks.com/asset/play/video.flv" in url
    assert "id=" in url
    assert "start_timestamp=" in url
    assert "end_timestamp=" in url
    assert "A=" in url
