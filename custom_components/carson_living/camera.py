"""This component provides support to the Ring Door Bell camera."""
from datetime import timedelta
import io
import logging

from homeassistant.components.camera import CameraEntityFeature, Camera
from homeassistant.const import ATTR_ATTRIBUTION

from .const import (
    ATTRIBUTION,
    CONF_LIST_FROM_EAGLE_EYE,
    DEFAULT_CONF_LIST_FROM_EAGLE_EYE,
    DOMAIN,
)
from .entity import CarsonEntityMixin

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Create the Cameras for the Carson devices."""
    _LOGGER.debug("Setting up Carson Camera entries")
    carson = hass.data[DOMAIN][config_entry.entry_id]["api"]
    cameras = []
    for building in carson.buildings:
        building.eagleeye_api.update()
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
            if camera.get("provider") == "eagle_eye"
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

    async_add_entities(
        [EagleEyeCamera(config_entry.entry_id, camera, hass) for camera in cameras]
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
        """Return bytes of camera image."""
        _LOGGER.debug("Getting live camera image for %s", self.name)
        buffer = io.BytesIO()
        self._ee_camera.get_image(buffer)
        return buffer.getvalue()

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
