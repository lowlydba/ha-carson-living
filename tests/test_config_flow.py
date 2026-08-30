"""Test the Carson config flow."""
from unittest.mock import patch, Mock
from carson_living import CarsonAuthenticationError, CarsonCommunicationError

from homeassistant import config_entries, setup
from homeassistant.data_entry_flow import FlowResultType
from custom_components.carson_living.const import CONF_LIST_FROM_EAGLE_EYE, DOMAIN

from tests.common import MockConfigEntry
from .common import CONF_AND_FORM_CREDS


async def test_form(hass):
    """Test we get the form."""
    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    with patch(
        "custom_components.carson_living.config_flow.CarsonAuth",
        return_value=Mock(update_token=Mock(), token="test-token"),
    ), patch(
        "custom_components.carson_living.async_setup", return_value=True
    ) as mock_setup, patch(
        "custom_components.carson_living.async_setup_entry", return_value=True,
    ) as mock_setup_entry:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], CONF_AND_FORM_CREDS,
        )

    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["title"] == CONF_AND_FORM_CREDS["username"]
    assert result2["data"] == {
        "username": CONF_AND_FORM_CREDS["username"],
        "password": CONF_AND_FORM_CREDS["password"],
        "token": "test-token",
    }
    await hass.async_block_till_done()
    assert len(mock_setup.mock_calls) == 1
    assert len(mock_setup_entry.mock_calls) == 1


async def test_form_with_token(hass):
    """Test we can sign in with a token instead of a password (e.g. Google/SSO-only accounts)."""
    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    token_input = {"username": "foo@bar.com", "password": "", "token": "test-jwt-token"}

    with patch(
        "custom_components.carson_living.config_flow.Carson",
        return_value=Mock(token="test-jwt-token"),
    ) as mock_carson, patch(
        "custom_components.carson_living.async_setup", return_value=True
    ) as mock_setup, patch(
        "custom_components.carson_living.async_setup_entry", return_value=True,
    ) as mock_setup_entry:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], token_input,
        )

    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["title"] == token_input["username"]
    assert result2["data"] == {
        "username": token_input["username"],
        "password": "",
        "token": "test-jwt-token",
    }
    mock_carson.assert_called_once_with(
        token_input["username"], token_input["password"], token_input["token"]
    )
    await hass.async_block_till_done()
    assert len(mock_setup.mock_calls) == 1
    assert len(mock_setup_entry.mock_calls) == 1


async def test_form_invalid_auth(hass):
    """Test we handle invalid auth."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.carson_living.config_flow.CarsonAuth.update_token",
        side_effect=CarsonAuthenticationError,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], CONF_AND_FORM_CREDS,
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_auth"}


async def test_form_cannot_connect(hass):
    """Test we handle cannot connect error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.carson_living.config_flow.CarsonAuth.update_token",
        side_effect=CarsonCommunicationError,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], CONF_AND_FORM_CREDS,
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_form_both_password_and_token(hass):
    """Test both a password and a token being set is rejected.

    A password and a token are two different login paths (native Carson
    account vs. a captured Google/SSO token) and only one should ever be
    in play at a time.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    both_input = {
        "username": "foo@bar.com",
        "password": "bar",
        "token": "test-jwt-token",
    }
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], both_input,
    )

    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "both_credentials"}


async def test_reauth_flow_updates_existing_entry(hass):
    """Test reauth lets a fresh token be pasted in without a duplicate entry.

    This is the main "ease of use later" path: once a captured Google/SSO
    token expires, the user shouldn't have to delete and recreate the whole
    integration (losing entity IDs/history) just to paste in a new one.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "foo@bar.com", "password": "", "token": "stale-token"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data=entry.data,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch(
        "custom_components.carson_living.config_flow.Carson",
        return_value=Mock(token="fresh-token"),
    ) as mock_carson, patch(
        "custom_components.carson_living.async_setup_entry", return_value=True,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "", "token": "fresh-token"},
        )
        await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "reauth_successful"
    assert entry.data["username"] == "foo@bar.com"
    assert entry.data["token"] == "fresh-token"
    mock_carson.assert_called_once_with("foo@bar.com", "", "fresh-token")


async def test_reauth_flow_invalid_auth(hass):
    """Test reauth surfaces invalid_auth errors instead of silently failing."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "foo@bar.com", "password": "", "token": "stale-token"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data=entry.data,
    )

    with patch(
        "custom_components.carson_living.config_flow.Carson",
        side_effect=CarsonAuthenticationError,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "", "token": "still-bad"},
        )

    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "reauth_confirm"
    assert result2["errors"] == {"base": "invalid_auth"}
    assert entry.data["token"] == "stale-token"


async def test_reauth_flow_both_password_and_token(hass):
    """Test reauth also rejects a password and a token being set together."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "foo@bar.com", "password": "", "token": "stale-token"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data=entry.data,
    )

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "bar", "token": "fresh-token"},
    )

    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "reauth_confirm"
    assert result2["errors"] == {"base": "both_credentials"}
    assert entry.data["token"] == "stale-token"


async def test_option_flow(hass):
    """Test config flow options."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    flow = await hass.config_entries.options.async_create_flow(
        entry.entry_id, context={"source": "test"}, data=None
    )

    result = await flow.async_step_init()
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "carson_devices"

    result = await flow.async_step_carson_devices(
        user_input={CONF_LIST_FROM_EAGLE_EYE: False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_LIST_FROM_EAGLE_EYE: False,
    }
