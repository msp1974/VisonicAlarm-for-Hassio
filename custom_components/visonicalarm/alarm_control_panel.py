"""
Interfaces with the Visonic Alarm control panel.
"""
import asyncio
import logging

from homeassistant.components.alarm_control_panel import AlarmControlPanelEntity, AlarmControlPanelState
from homeassistant.components.alarm_control_panel.const import AlarmControlPanelEntityFeature, CodeFormat
from homeassistant.const import CONF_CODE
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA, DOMAIN
from .entity import BaseVisonicEntity

SUPPORT_VISONIC = (
    AlarmControlPanelEntityFeature.ARM_HOME
    | AlarmControlPanelEntityFeature.ARM_AWAY
    | AlarmControlPanelEntityFeature.TRIGGER
)

_LOGGER = logging.getLogger(__name__)

ATTR_SYSTEM_SERIAL_NUMBER = "serial_number"
ATTR_SYSTEM_MODEL = "model"
ATTR_SYSTEM_READY = "ready"
ATTR_SYSTEM_CONNECTED = "connected"
ATTR_SYSTEM_SESSION_TOKEN = "session_token"
ATTR_SYSTEM_LAST_UPDATE = "last_update"
ATTR_CHANGED_BY = "changed_by"
ATTR_CHANGED_TIMESTAMP = "changed_timestamp"
ATTR_ALARMS = "alarm"


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Visonic Alarm platform."""
    alarms = []
    coordinator = hass.data[DOMAIN][config_entry.entry_id][DATA]
    for partition in coordinator.status.partitions:
        alarms.append(VisonicAlarm(coordinator, hass, partition.id))
    async_add_entities(alarms)


class AlarmAction:
    """Alarm Actions"""

    DISARM = "DISARM"
    ARM_HOME = "ARM_HOME"
    ARM_AWAY = "ARM_AWAY"


class AlarmStatus:
    """Alarm Status"""

    EXIT = "EXIT"
    ENTRYDELAY = "ENTRYDELAY"
    ALARM = "ALARM"


class AlarmState:
    """Alarm State"""

    DISARM = "DISARM"
    AWAY = "AWAY"
    HOME = "HOME"


class VisonicAlarm(BaseVisonicEntity, AlarmControlPanelEntity, CoordinatorEntity):
    """Representation of a Visonic Alarm control panel."""

    def __init__(self, coordinator, hass, partition_id: int):
        """Initialize the Visonic Alarm panel."""
        super().__init__(coordinator)
        self._hass = hass
        self.coordinator = coordinator
        self._alarm = self.coordinator.alarm
        self._code = self.coordinator.config_entry.data[CONF_CODE]
        self._partition = self.coordinator.get_partition_info_by_id(partition_id)
        self._partition_status = self.coordinator.get_partition_status_by_id(partition_id)
        self._changed_by = None
        self._changed_timestamp = None
        self._arm_in_progress = False
        self._disarm_in_progress = False
        self._partition_id = partition_id
        self._state = self.get_partition_state(self._partition_status)

    @property
    def name(self):
        """Return the name of the device."""
        partition = f"{' ' + self._partition.name if self._partition_id != -1 else ''}"
        return f"Alarm Panel {self.coordinator.panel_info.serial}{partition}"

    @property
    def unique_id(self):
        """Return unique id."""
        return f"{DOMAIN}-{self.coordinator.panel_info.serial}-{self._partition_id}-panel"

    @property
    def extra_state_attributes(self):
        """Return the state attributes of the alarm system."""
        attrs = super().state_attributes
        attrs[ATTR_SYSTEM_SERIAL_NUMBER] = self.coordinator.panel_info.serial
        attrs[ATTR_SYSTEM_MODEL] = self.coordinator.panel_info.model
        attrs[ATTR_SYSTEM_READY] = self._partition_status.ready
        # ATTR_SYSTEM_CONNECTED: self._alarm.connected(),
        # ATTR_SYSTEM_SESSION_TOKEN: self._alarm.session_token,
        attrs[ATTR_SYSTEM_LAST_UPDATE] = self.coordinator.last_update
        # ATTR_CODE_FORMAT: self.code_format,
        # ATTR_CHANGED_BY: self.changed_by,
        # ATTR_CHANGED_TIMESTAMP: self._changed_timestamp,
        # ATTR_ALARMS: self._alarm.alarm,
        return attrs

    @property
    def icon(self):
        """Return icon"""
        if self._state == AlarmControlPanelState.ARMED_AWAY:
            return "mdi:shield-lock"
        elif self._state == AlarmControlPanelState.ARMED_HOME:
            return "mdi:shield-home"
        elif self._state == AlarmControlPanelState.DISARMED:
            return "mdi:shield-check"
        elif self._state == AlarmControlPanelState.ARMING:
            return "mdi:shield-outline"
        else:
            return "hass:bell-ring"

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def code_format(self) -> CodeFormat | None:
        """Return one or more digits/characters."""
        if (self.coordinator.pin_required_arm and self._state == AlarmControlPanelState.DISARMED) or (
            self.coordinator.pin_required_disarm and self._state in [AlarmControlPanelState.ARMED_HOME, AlarmControlPanelState.ARMED_AWAY]
        ):
            return CodeFormat.NUMBER

    @property
    def changed_by(self):
        """Return the last change triggered by."""
        return self._changed_by

    @property
    def changed_timestamp(self):
        """Return the last change triggered by."""
        return self._changed_timestamp

    async def async_force_update(self, delay: int = 0):
        """Force update from api"""
        _LOGGER.debug("Alarm update initiated by %s", self.name)
        if delay:
            await asyncio.sleep(delay)
        await self.coordinator.async_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._partition = self.coordinator.get_partition_info_by_id(self._partition_id)
        self._partition_status = self.coordinator.get_partition_status_by_id(self._partition_id)
        self._state = self.get_partition_state(self._partition_status)
        self.async_write_ha_state()

    def get_partition_ready(self, partition_id: int) -> bool:
        """Return if partition is ready."""
        return self.coordinator.get_partition_status_by_id(partition_id)

    def get_partition_state(self, partition_status) -> str | None:
        """Get current state of partition"""
        status = partition_status.status
        state = partition_status.state

        if self._disarm_in_progress:
            return AlarmControlPanelState.DISARMING

        if self._arm_in_progress:
            return AlarmControlPanelState.ARMING

        if status:
            if status == AlarmStatus.EXIT:
                return AlarmControlPanelState.ARMING
            elif status == AlarmStatus.ENTRYDELAY:
                return AlarmControlPanelState.PENDING
            elif status == AlarmStatus.ALARM:
                return AlarmControlPanelState.TRIGGERED
        else:
            if state == AlarmState.AWAY:
                return AlarmControlPanelState.ARMED_AWAY
            elif state == AlarmState.HOME:
                return AlarmControlPanelState.ARMED_HOME
            elif state == AlarmState.DISARM:
                return AlarmControlPanelState.DISARMED
            elif state == AlarmStatus.ALARM:
                return AlarmControlPanelState.TRIGGERED

    @property
    def code_arm_required(self):
        return False

    @property
    def supported_features(self) -> int:
        """Return the list of supported features."""
        return SUPPORT_VISONIC

    async def async_alarm_disarm(self, code=None):
        """Send disarm command."""
        if (not self._arm_in_progress) and (self.coordinator.pin_required_disarm and code != self._code):
            raise HomeAssistantError("Pin is required to disarm this alarm but no pin was provided")
        else:
            _LOGGER.debug("Disarming alarm...")

            process_token = await self.hass.async_add_executor_job(self._alarm.disarm, self._partition_id)
            self._disarm_in_progress = True
            self._state = AlarmControlPanelState.DISARMING
            self.async_write_ha_state()

            if await self.async_wait_for_process_success(self.coordinator, process_token):
                _LOGGER.debug("Disarming alarm completed successfully")
                self._disarm_in_progress = False
                await self.async_force_update()
            else:
                _LOGGER.error("Disarming alarm did not complete successfully.")

    async def async_alarm_arm_home(self, code=None):
        """Send arm home command."""
        await self.async_alarm_arm(AlarmAction.ARM_HOME, code)

    async def async_alarm_arm_away(self, code=None):
        """Send arm away command."""
        await self.async_alarm_arm(AlarmAction.ARM_AWAY, code)

    async def async_alarm_arm(self, action: AlarmAction, code):
        """Arm Alarm"""
        if self.coordinator.pin_required_arm and code != self._code:
            raise HomeAssistantError("Pin is required to arm this alarm but no pin was provided")
        else:
            _LOGGER.debug("Arming alarm...")

            # Get current status of partition
            await self.coordinator.async_update_status()
            if self.get_partition_ready(self._partition_id):
                try:
                    if action == AlarmAction.ARM_HOME:
                        process_token = await self.hass.async_add_executor_job(
                            self._alarm.arm_home, self._partition_id
                        )
                    elif action == AlarmAction.ARM_AWAY:
                        process_token = await self.hass.async_add_executor_job(
                            self._alarm.arm_away, self._partition_id
                        )

                    self._arm_in_progress = True
                    self._state = AlarmControlPanelState.ARMING
                    self.async_write_ha_state()

                    result = await self.async_wait_for_process_success(self.coordinator, process_token)
                    self._arm_in_progress = False
                    await self.async_force_update()
                    if result:
                        _LOGGER.debug("Arming alarm completed successfully")
                    else:
                        _LOGGER.error("%s did not complete successfully.", action)
                        raise HomeAssistantError("There was an error setting the alarm")

                except HomeAssistantError:
                    pass
                except Exception as ex:
                    _LOGGER.error("Unable to complete %s.  Error is %s", action, ex)
                    raise HomeAssistantError("Unknown error setting the alarm") from ex
            else:
                raise HomeAssistantError(
                    "The alarm system is not in a ready state. Maybe there are doors or windows open?"
                )
