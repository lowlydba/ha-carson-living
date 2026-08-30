"""Config flow for Carson integration."""
import logging

from carson_living import (
    Carson,
    CarsonAuth,
    CarsonAuthenticationError,
    CarsonCommunicationError,
)
import voluptuous as vol

from homeassistant import config_entries, core, exceptions
from homeassistant.core import callback

from .const import (  # pylint: disable=unused-import
    CONF_LIST_FROM_EAGLE_EYE,
    DEFAULT_CONF_LIST_FROM_EAGLE_EYE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Password is optional and a "token" field is supported so accounts that only
# ever sign in via a federated provider (e.g. "Sign in with Google", which
# Carson's API has no direct login endpoint for) can authenticate with a JWT
# captured from an already-logged-in session (e.g. via a proxy such as
# mitmproxy or HTTP Toolkit) instead of a native Carson password. Password is
# still used afterwards, internally by the underlying carson_living library,
# to renew the token once it expires - if none is set, expect to supply a
# fresh token at that point.
DATA_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Optional("password", default=""): str,
        vol.Optional("token", default=""): str,
    }
)


async def validate_input(hass: core.HomeAssistant, data):
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    username = data["username"]
    password = data.get("password", "")
    token = data.get("token", "").strip()

    try:
        if token:
            # Token-first path: validate the supplied JWT directly against
            # the Carson API instead of doing a password login.
            carson = await hass.async_add_executor_job(
                Carson, username, password, token
            )
            return carson.token

        # Original path: real username/password login.
        auth = CarsonAuth(username, password)
        await hass.async_add_executor_job(auth.update_token)
        return auth.token
    except CarsonAuthenticationError as error:
        _LOGGER.warning("Authentication error for %s", username)
        raise InvalidAuth from error
    except CarsonCommunicationError as error:
        _LOGGER.warning("Communication error with Carson API.")
        raise CannotConnect from error


class CarsonConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Carson."""

    VERSION = 1

    def is_matching(self, other_flow) -> bool:
        """Return whether another flow represents the same discovery."""
        return False

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                token = await validate_input(self.hass, user_input)
                await self.async_set_unique_id(user_input["username"])

                return self.async_create_entry(
                    title=user_input["username"],
                    data={
                        "username": user_input["username"],
                        "password": user_input.get("password", ""),
                        "token": token,
                    },
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_import(self, user_input):
        """Handle import."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        return await self.async_step_user(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return CarsonOptionsFlowHandler(config_entry)


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""


class CarsonOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Carson options."""

    def __init__(self, config_entry):
        """Initialize Carson options flow."""
        self._config_entry = config_entry
        self.options = dict(config_entry.options)

    async def async_step_init(self, user_input=None):
        # pylint: disable=unused-argument
        """Manage the Carson options."""
        return await self.async_step_carson_devices()

    async def async_step_carson_devices(self, user_input=None):
        """Manage the Carson devices options."""
        if user_input is not None:
            self.options[CONF_LIST_FROM_EAGLE_EYE] = user_input[
                CONF_LIST_FROM_EAGLE_EYE
            ]
            return self.async_create_entry(title="", data=self.options)

        return self.async_show_form(
            step_id="carson_devices",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_LIST_FROM_EAGLE_EYE,
                        default=self._config_entry.options.get(
                            CONF_LIST_FROM_EAGLE_EYE, DEFAULT_CONF_LIST_FROM_EAGLE_EYE
                        ),
                    ): bool,
                }
            ),
        )
