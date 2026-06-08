"""Sensor platform for UFC Fight Tracker."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import UFCDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the UFC Fight Tracker sensors."""
    coordinator: UFCDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = []
    for i in range(15):
        sensors.append(UFCFightSensor(coordinator, i, entry.entry_id))

    async_add_entities(sensors)


class UFCFightSensor(CoordinatorEntity[UFCDataUpdateCoordinator], SensorEntity):
    """Representation of a UFC Fight Tracker sensor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: UFCDataUpdateCoordinator, index: int, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._index = index
        self._attr_unique_id = f"{entry_id}_ufc_fight_{index:02d}"
        self._attr_name = f"{index:02d}"
        self._attr_icon = "mdi:karate"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="UFC Fight Tracker",
            manufacturer="Community",
            model="Smart Polling Tracker"
        )

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        if self.coordinator.data is None or len(self.coordinator.data) <= self._index:
            return "Unknown"
        return self.coordinator.data[self._index].get("state", "Unknown")

    @property
    def extra_state_attributes(self) -> dict[str, any]:
        """Return the state attributes."""
        if self.coordinator.data is None or len(self.coordinator.data) <= self._index:
            return {}
        
        # Exclude state and friendly_name from attributes as they are base properties
        attrs = self.coordinator.data[self._index].copy()
        attrs.pop("state", None)
        attrs.pop("friendly_name", None)
        attrs.pop("icon", None)
        return attrs
