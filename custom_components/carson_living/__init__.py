"""The Carson integration."""
import asyncio
from functools import partial
import logging

from carson_living import Carson, CarsonAuthenticationError
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
import homeassistant.helpers.config_validation as cv
from homeassistant.util.async_ import run_callback_threadsafe

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional(DOMAIN): vol.Schema(
            {
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

PLATFORMS = ["lock", "camera"]

# The Carson API can be slow to respond on the initial login. Wait at least
# this long before warning, so a normal-but-slow startup isn't logged as if
# something were wrong.
SLOW_INIT_WARNING = 30


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Carson component."""
    _LOGGER.debug("async def async_setup(hass: HomeAssistant, config: dict) called")
    if DOMAIN not in config:
        return True

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={
                "username": config[DOMAIN][CONF_USERNAME],
                "password": config[DOMAIN][CONF_PASSWORD],
            },
        )
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Carson from a config entry."""
    _LOGGER.debug("async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) called")

    def token_updater(token):
        """Handle from sync context when token is updated."""
        run_callback_threadsafe(
            hass.loop,
            partial(
                hass.config_entries.async_update_entry,
                entry,
                data={**entry.data, "token": token},
            ),
        ).result()

    carson_task = hass.async_create_task(
        hass.async_add_executor_job(
            Carson,
            entry.data["username"],
            entry.data["password"],
            entry.data["token"],
            token_updater,
        )
    )

    async def _warn_if_slow():
        """Log a warning only if init is still running after SLOW_INIT_WARNING."""
        await asyncio.sleep(SLOW_INIT_WARNING)
        _LOGGER.warning(
            "Carson API initialization has taken longer than %s seconds; "
            "the Carson service can be slow to respond, setup is still in "
            "progress",
            SLOW_INIT_WARNING,
        )

    warn_task = hass.async_create_task(_warn_if_slow())

    try:
        carson = await carson_task
    except CarsonAuthenticationError as error:
        # Surface this as a reauth flow instead of a silent setup failure, so
        # the UI prompts for a fresh token (e.g. once a captured Google/SSO
        # JWT expires) without requiring the whole integration to be deleted
        # and re-added from scratch.
        raise ConfigEntryAuthFailed(
            "Carson token/password no longer valid; please re-authenticate"
        ) from error
    finally:
        warn_task.cancel()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api": carson,
        "ha_entities": {},
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if hass.services.has_service(DOMAIN, "update"):
        return True

    async def async_carson_api(_):
        """Refresh all carson data."""
        _LOGGER.debug("Updating all carson ")
        for info in hass.data[DOMAIN].values():
            await hass.async_add_executor_job(info["api"].update)
            for building in info["api"].buildings:
                await hass.async_add_executor_job(building.eagleeye_api.update)
            for ha_entity in info["ha_entities"].values():
                ha_entity.async_schedule_update_ha_state()

    # register service
    hass.services.async_register(DOMAIN, "update", async_carson_api)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    _LOGGER.debug(
        "async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) called"
    )
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
