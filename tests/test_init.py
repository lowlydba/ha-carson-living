"""Initialization Test for the Carson Component."""
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

from custom_components import carson_living
from .common import CONF_AND_FORM_CREDS


VALID_CONFIG = {carson_living.DOMAIN: CONF_AND_FORM_CREDS}


async def test_creating_entry_sets_up_devices(hass, success_requests_mock):  # pylint: disable=unused-argument
    """Test setting up carson loads device entities."""

    with patch(
        "custom_components.carson_living.lock.async_setup_entry",
        new=AsyncMock(return_value=True),
    ) as lock_mock_setup, patch(
        "custom_components.carson_living.camera.async_setup_entry",
        new=AsyncMock(return_value=True),
    ) as camera_mock_setup:
        result = await hass.config_entries.flow.async_init(
            carson_living.DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        # Confirmation form
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CONF_AND_FORM_CREDS
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY

        await hass.async_block_till_done()

    assert len(lock_mock_setup.mock_calls) == 1
    assert len(camera_mock_setup.mock_calls) == 1


async def test_configuring_carson_creates_entry(hass, success_requests_mock):  # pylint: disable=unused-argument
    """Test that specifying config will create an entry."""

    with patch(
        "custom_components.carson_living.async_setup_entry",
        new=AsyncMock(return_value=True),
    ) as mock_setup:
        await async_setup_component(hass, carson_living.DOMAIN, VALID_CONFIG)
        await hass.async_block_till_done()

    assert len(mock_setup.mock_calls) == 1


async def test_configuring_carson_wrong_creds_creates_no_entry(hass, requests_mock):
    """Test that a configuration with wrong credential will not create entry."""

    requests_mock.post(
        "https://api.carson.live/api/v1.4.1/auth/login/", status_code=401
    )

    with patch(
        "custom_components.carson_living.async_setup_entry",
        new=AsyncMock(return_value=True),
    ) as mock_setup:
        await async_setup_component(hass, carson_living.DOMAIN, VALID_CONFIG)
        await hass.async_block_till_done()

    assert len(mock_setup.mock_calls) == 0
