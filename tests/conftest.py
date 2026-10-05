from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.unifi_sms.api import generate_key

PRIVATE_KEY, PUBLIC_KEY = generate_key()
HOST_KEY = generate_key()[1]
IMEI = "350000000000001"
SIM = {"spn": "Test Mobile", "slot": 1, "esim": False, "active": True, "iccid": "8900000000000000001"}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def modem():
    """Patch U5GModem everywhere it is constructed."""
    instance = MagicMock()
    instance.device_info = AsyncMock(return_value={"imei": IMEI})
    instance.sim_state = AsyncMock(return_value=SIM)
    instance.read_spool = AsyncMock(return_value=[])
    instance.ack_spool = AsyncMock()
    instance.remove_hook = AsyncMock()
    instance.send = AsyncMock(return_value=1)
    instance.close = AsyncMock()
    instance.server_host_key = MagicMock(return_value=HOST_KEY)
    with (
        patch("custom_components.unifi_sms.U5GModem", return_value=instance),
        patch("custom_components.unifi_sms.config_flow.U5GModem", return_value=instance),
    ):
        yield instance
