"""Tests for the Carson Camera platform."""
from datetime import timedelta
import json
from unittest.mock import MagicMock, patch

from carson_living import CarsonError
from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
import homeassistant.util.dt as dt_util

from custom_components.carson_living.camera import (
    _async_repair_stale_cameras,
    _building_has_eagleeye_cameras,
    _update_eagleeye_session_with_retries,
)
from custom_components.carson_living.const import DOMAIN
from custom_components.carson_living.repairs import async_create_fix_flow

from .common import (
    CARSON_API_VERSION,
    carson_load_fixture,
    fixture_building_id,
    fixture_een_subdomain,
    setup_platform,
)


class _FakeCamera:  # pylint: disable=too-few-public-methods
    """Stand-in exposing just the attribute _async_repair_stale_cameras needs."""

    def __init__(self, unique_entity_id):
        self.unique_entity_id = unique_entity_id


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

    with patch("custom_components.carson_living.camera.time.sleep"):
        await setup_platform(hass, CAMERA_DOMAIN)

    entity_registry = er.async_get(hass)
    assert entity_registry.async_get("camera.camera_name_1") is None
    assert "unable to update Eagle Eye session" in caplog.text

    # A building we skipped due to a transient error must not be treated as
    # if it had reported zero cameras, so no stale-camera repair fires.
    config_entry = hass.config_entries.async_entries(DOMAIN)[0]
    issue_registry = ir.async_get(hass)
    assert (
        issue_registry.async_get_issue(
            DOMAIN, f"stale_cameras_{config_entry.entry_id}"
        )
        is None
    )


def test_eagleeye_session_update_retries_transient_failure():
    """A transient failure is retried and succeeds without exhausting attempts."""
    building = MagicMock()
    building.name = "Test Building"
    building.entity_id = "b0"
    building.eagleeye_api.update.side_effect = [CarsonError("boom"), None]

    with patch("custom_components.carson_living.camera.time.sleep") as mock_sleep:
        error = _update_eagleeye_session_with_retries(building)

    assert error is None
    assert building.eagleeye_api.update.call_count == 2
    mock_sleep.assert_called_once()


def test_eagleeye_session_update_gives_up_after_max_attempts():
    """All attempts failing surfaces the last error and stops retrying."""
    building = MagicMock()
    building.name = "Test Building"
    building.entity_id = "b0"
    building.eagleeye_api.update.side_effect = CarsonError("still broken")

    with patch("custom_components.carson_living.camera.time.sleep") as mock_sleep:
        error = _update_eagleeye_session_with_retries(building)

    assert isinstance(error, CarsonError)
    assert building.eagleeye_api.update.call_count == 3
    assert mock_sleep.call_count == 2


def test_building_has_eagleeye_cameras_true_for_eagle_eye_provider():
    """A building whose Carson payload lists an eagle_eye* camera qualifies."""
    building = MagicMock()
    building.entity_payload = {
        "cameras": [{"provider": "eagle_eye_v2", "liveViewId": "c0"}]
    }

    assert _building_has_eagleeye_cameras(building) is True


def test_building_has_eagleeye_cameras_false_without_eagle_eye_provider():
    """A building with only non-Eagle-Eye cameras (or none) doesn't qualify."""
    building = MagicMock()
    building.entity_payload = {"cameras": [{"provider": "smartair", "liveViewId": "d0"}]}

    assert _building_has_eagleeye_cameras(building) is False

    building.entity_payload = {"cameras": []}
    assert _building_has_eagleeye_cameras(building) is False


def test_building_has_eagleeye_cameras_false_for_null_cameras():
    """An explicit `cameras: null` doesn't qualify (and doesn't raise)."""
    building = MagicMock()
    building.entity_payload = {"cameras": None}

    assert _building_has_eagleeye_cameras(building) is False


async def test_skips_eagleeye_session_when_building_has_no_eagleeye_cameras(
    hass, success_requests_mock
):
    """A building with no Eagle Eye camera never hits its session endpoint.

    Carson's own building payload is the source of truth for whether a
    building has an Eagle Eye account linked; querying the session
    endpoint anyway would just 404 every time (a permanent condition the
    retries in _update_eagleeye_session_with_retries aren't meant for).
    """
    building_id = fixture_building_id()
    me_payload = json.loads(carson_load_fixture("carson_me.json"))
    for camera in me_payload["data"]["properties"][0]["cameras"]:
        camera["provider"] = "smartair"
    success_requests_mock.get(
        f"https://api.carson.live/api/v{CARSON_API_VERSION}/me/",
        json=me_payload,
    )
    session_mock = success_requests_mock.get(
        f"https://api.carson.live/api/v{CARSON_API_VERSION}/properties/"
        f"buildings/{building_id}/eagleeye/session/",
        text=carson_load_fixture("carson_eagleeye_session.json"),
    )

    await setup_platform(hass, CAMERA_DOMAIN)

    entity_registry = er.async_get(hass)
    assert entity_registry.async_get("camera.camera_name_1") is None
    assert session_mock.call_count == 0


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


async def test_stale_camera_repair_created_for_removed_camera(
    hass, success_requests_mock
):  # pylint: disable=unused-argument
    """A camera Carson no longer reports gets a fixable repair issue."""
    await setup_platform(hass, CAMERA_DOMAIN)
    config_entry = hass.config_entries.async_entries(DOMAIN)[0]
    entity_registry = er.async_get(hass)

    # Simulate an entity from a camera Carson used to report but no longer does.
    stale_entry = entity_registry.async_get_or_create(
        CAMERA_DOMAIN,
        DOMAIN,
        "eagleeye_camera_gone",
        config_entry=config_entry,
    )

    _async_repair_stale_cameras(
        hass,
        config_entry,
        [_FakeCamera("eagleeye_camera_c0"), _FakeCamera("eagleeye_camera_c1")],
    )

    issue_registry = ir.async_get(hass)
    issue = issue_registry.async_get_issue(
        DOMAIN, f"stale_cameras_{config_entry.entry_id}"
    )
    assert issue is not None
    assert issue.is_fixable
    assert issue.translation_key == "stale_cameras"
    assert issue.data["entity_ids"] == stale_entry.entity_id


async def test_stale_camera_repair_cleared_when_no_longer_stale(
    hass, success_requests_mock
):  # pylint: disable=unused-argument
    """A previously created repair clears once every camera is accounted for."""
    await setup_platform(hass, CAMERA_DOMAIN)
    config_entry = hass.config_entries.async_entries(DOMAIN)[0]
    issue_registry = ir.async_get(hass)
    issue_id = f"stale_cameras_{config_entry.entry_id}"
    issue_registry.async_get_or_create(
        DOMAIN,
        issue_id,
        is_fixable=True,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="stale_cameras",
    )

    _async_repair_stale_cameras(
        hass,
        config_entry,
        [_FakeCamera("eagleeye_camera_c0"), _FakeCamera("eagleeye_camera_c1")],
    )

    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


async def test_stale_camera_repair_flow_removes_entity(
    hass, success_requests_mock
):  # pylint: disable=unused-argument
    """Confirming the repair flow removes the stale camera entity."""
    await setup_platform(hass, CAMERA_DOMAIN)
    config_entry = hass.config_entries.async_entries(DOMAIN)[0]
    entity_registry = er.async_get(hass)
    stale_entry = entity_registry.async_get_or_create(
        CAMERA_DOMAIN, DOMAIN, "eagleeye_camera_gone", config_entry=config_entry
    )

    flow = await async_create_fix_flow(
        hass, "issue_id", {"entity_ids": stale_entry.entity_id}
    )
    flow.hass = hass

    result = await flow.async_step_init()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "confirm"

    result = await flow.async_step_confirm(user_input={})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entity_registry.async_get(stale_entry.entity_id) is None
