"""Repair flows for the Carson integration."""
import logging

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)


class StaleCameraRepairFlow(RepairsFlow):
    """Confirm and remove camera entities Carson/Eagle Eye no longer reports."""

    def __init__(self, entity_ids):
        """Initialize with the stale entity_ids the issue was created for."""
        self._entity_ids = entity_ids

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        """Handle the first step of the fix flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None):
        """Remove the stale entities once the user confirms."""
        if user_input is not None:
            entity_registry = er.async_get(self.hass)
            for entity_id in self._entity_ids:
                if entity_registry.async_get(entity_id):
                    entity_registry.async_remove(entity_id)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"count": str(len(self._entity_ids))},
        )


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict):  # pylint: disable=unused-argument
    """Create the fix flow for a Carson repair issue."""
    entity_ids = data.get("entity_ids", "") if data else ""
    return StaleCameraRepairFlow(entity_ids.split(",") if entity_ids else [])
