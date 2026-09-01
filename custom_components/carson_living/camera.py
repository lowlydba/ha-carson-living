"""This component provides support to the Ring Door Bell camera."""
from datetime import timedelta
import io
import logging
import time

from carson_living import CarsonError
from homeassistant.components.camera import (
    DOMAIN as CAMERA_DOMAIN,
    CameraEntityFeature,
    Camera,
)
from homeassistant.const import ATTR_ATTRIBUTION
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
import homeassistant.util.dt as dt_util

from .const import (
    ATTRIBUTION,
    CONF_LIST_FROM_EAGLE_EYE,
    DEFAULT_CONF_LIST_FROM_EAGLE_EYE,
    DOMAIN,
)
from .entity import CarsonEntityMixin

_LOGGER = logging.getLogger(__name__)

# Minimum time between snapshot fetches from Eagle Eye. Still-image polling
# cards (camera_view: auto/glance/picture-entity) call camera_image() on the
# frontend's poll cadence; without this, every poll is a full round-trip to
# EEN's cloud (~4-6s), causing visible lag. Live view via stream_source() is
# unaffected by this and always pulls a fresh RTSP/HLS URL.
MIN_TIME_BETWEEN_IMAGE_UPDATES = timedelta(seconds=10)

# Eagle Eye's session API is intermittently flaky. A single failed update()
# call used to drop every camera for that building for the entire HA
# session (until restart), even though the entity registry entries and any
# dashboard cards still referenced them - causing "Camera not found"
# websocket errors on every poll. Retry a few times before giving up.
EAGLE_EYE_UPDATE_ATTEMPTS = 3
EAGLE_EYE_UPDATE_RETRY_DELAY = timedelta(seconds=1)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Create the Cameras for the Carson devices."""
    _LOGGER.debug("Setting up Carson Camera entries")
    carson = hass.data[DOMAIN][config_entry.entry_id]["api"]
    # building.eagleeye_api.update() performs blocking network I/O, so the
    # whole per-building lookup/filter must run off the event loop.
    cameras, all_buildings_ok = await hass.async_add_executor_job(
        _get_cameras, carson, config_entry
    )

    async_add_entities(
        [EagleEyeCamera(config_entry.entry_id, camera, hass) for camera in cameras]
    )

    # Only trust the camera list enough to flag removals when every building
    # actually reported in this round; a building skipped above due to a
    # transient Eagle Eye failure would otherwise look like all of its
    # cameras had been deleted.
    if all_buildings_ok:
        _async_repair_stale_cameras(hass, config_entry, cameras)


def _update_eagleeye_session_with_retries(building):
    """Update a building's Eagle Eye session, retrying transient failures.

    Returns the last CarsonError if every attempt failed, or None once an
    attempt succeeds.
    """
    error = None
    for attempt in range(1, EAGLE_EYE_UPDATE_ATTEMPTS + 1):
        try:
            building.eagleeye_api.update()
            return None
        except CarsonError as retry_error:
            error = retry_error
            if attempt < EAGLE_EYE_UPDATE_ATTEMPTS:
                _LOGGER.debug(
                    "Eagle Eye session update failed for building %s (%s), "
                    "retrying (attempt %d/%d): %s",
                    building.name,
                    building.entity_id,
                    attempt,
                    EAGLE_EYE_UPDATE_ATTEMPTS,
                    retry_error,
                )
                time.sleep(EAGLE_EYE_UPDATE_RETRY_DELAY.total_seconds())
    return error


def _get_cameras(carson, config_entry):
    """Return the Eagle Eye camera entities to expose for this config entry.

    Also returns whether every building's Eagle Eye session updated
    successfully this round, so callers can tell a building that reported
    zero cameras apart from one that was skipped due to a transient error.
    """
    cameras = []
    all_buildings_ok = True
    for building in carson.buildings:
        error = _update_eagleeye_session_with_retries(building)
        if error is not None:
            # Don't let one building's failure take down camera setup for
            # every other building on this account.
            _LOGGER.warning(
                "Skipping cameras for building %s (%s): unable to update "
                "Eagle Eye session after %d attempts: %s",
                building.name,
                building.entity_id,
                EAGLE_EYE_UPDATE_ATTEMPTS,
                error,
            )
            all_buildings_ok = False
            continue
        _LOGGER.debug(
            "Building %s (%s) raw entity_payload cameras: %s",
            building.name,
            building.entity_id,
            building.entity_payload.get("cameras"),
        )
        _LOGGER.debug(
            "Building %s (%s) Eagle Eye account cameras: %s",
            building.name,
            building.entity_id,
            [(cam.entity_id, cam.name) for cam in building.eagleeye_api.cameras],
        )
        if get_list_een_option(config_entry):
            cameras.extend(list(building.eagleeye_api.cameras))
            continue

        allowed_camera_ids = {
            camera["liveViewId"]
            for camera in building.entity_payload.get("cameras", [])
            if str(camera.get("provider", "")).startswith("eagle_eye")
        }
        _LOGGER.debug(
            "Building %s (%s) allowed camera liveViewIds from Carson: %s",
            building.name,
            building.entity_id,
            allowed_camera_ids,
        )
        cameras.extend(
            camera
            for camera in building.eagleeye_api.cameras
            if camera.entity_id in allowed_camera_ids
        )
    return cameras, all_buildings_ok


def _async_repair_stale_cameras(hass, config_entry, cameras):
    """Offer a repair to remove camera entities Carson/Eagle Eye dropped.

    Only called when every building updated successfully this round, so
    any registered camera entity missing from `cameras` is genuinely gone
    rather than skipped due to a transient error.
    """
    current_unique_ids = {camera.unique_entity_id for camera in cameras}
    entity_registry = er.async_get(hass)
    stale_entity_ids = [
        entry.entity_id
        for entry in er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )
        if entry.domain == CAMERA_DOMAIN
        and entry.unique_id not in current_unique_ids
    ]

    issue_id = f"stale_cameras_{config_entry.entry_id}"
    if not stale_entity_ids:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return

    _LOGGER.warning(
        "%d camera(s) no longer reported by Carson/Eagle Eye; creating a "
        "repair to remove them: %s",
        len(stale_entity_ids),
        stale_entity_ids,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="stale_cameras",
        translation_placeholders={"count": str(len(stale_entity_ids))},
        data={"entity_ids": ",".join(stale_entity_ids)},
    )


def get_list_een_option(config_entry):
    """Return config option load cameras from EEN vs Carson."""
    return config_entry.options.get(
        CONF_LIST_FROM_EAGLE_EYE, DEFAULT_CONF_LIST_FROM_EAGLE_EYE
    )


class EagleEyeCamera(CarsonEntityMixin, Camera):
    """An implementation of a Eagle Eye camera."""

    def __init__(self, config_entry_id, ee_camera, hass):
        """Initialize the lock."""
        super().__init__(config_entry_id, ee_camera)
        self._ee_camera = ee_camera
        self._hass = hass
        self._last_image = None
        self._last_image_time = dt_util.utc_from_timestamp(0)

    @property
    def name(self):
        """Return the name of this camera."""
        return self._ee_camera.name

    @property
    def extra_state_attributes(self):
        """Return the device state attributes."""
        return {
            ATTR_ATTRIBUTION: ATTRIBUTION,
            "account_id": self._ee_camera.account_id,
            "guid": self._ee_camera.guid,
            "tags": self._ee_camera.tags,
            "utc_offset": self._ee_camera.utc_offset,
            "timezone": self._ee_camera.timezone,
        }

    def camera_image(self, width=None, height=None):
        """Return bytes of camera image, cached for MIN_TIME_BETWEEN_IMAGE_UPDATES."""
        now = dt_util.utcnow()
        if (
            self._last_image is not None
            and now - self._last_image_time < MIN_TIME_BETWEEN_IMAGE_UPDATES
        ):
            _LOGGER.debug("Returning cached camera image for %s", self.name)
            return self._last_image

        _LOGGER.debug("Getting live camera image for %s", self.name)
        buffer = io.BytesIO()
        self._ee_camera.get_image(buffer)
        self._last_image = buffer.getvalue()
        self._last_image_time = now
        return self._last_image

    @property
    def supported_features(self):
        """Return supported features."""
        return CameraEntityFeature.STREAM

    async def stream_source(self):
        """Return the stream source."""
        _LOGGER.debug("Getting live camera video stream for %s", self.name)
        return await self._hass.async_add_executor_job(self._ee_camera.get_video_url, timedelta(minutes=5))

    def turn_off(self):
        """Turn off camera."""
        raise NotImplementedError("Eagle Eye cannot be turned off")

    def turn_on(self):
        """Turn off camera."""
        raise NotImplementedError("Eagle Eye is always on")

    def enable_motion_detection(self):
        """Enable motion detection in the camera."""
        raise NotImplementedError("Eagle Eye does not support motion detection")

    def disable_motion_detection(self):
        """Disable motion detection in camera."""
        raise NotImplementedError("Eagle Eye does not support motion detection")
