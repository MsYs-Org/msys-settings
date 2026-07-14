from __future__ import annotations

import unittest

from msys_settings.radio import (
    radio_domain_view,
    radio_state_summary,
    wifi_connect_changes,
    wifi_forget_changes,
    wifi_network_rows,
)
from msys_settings.model import normalise_hal_state


class RadioPresentationModelTests(unittest.TestCase):
    def test_absent_domain_is_explicitly_not_installed(self) -> None:
        view = radio_domain_view({"domains": [], "devices": []}, "network")
        self.assertFalse(view["installed"])
        self.assertFalse(view["available"])
        self.assertEqual(view["devices"], [])

    def test_provider_requires_real_active_component_and_health(self) -> None:
        payload = {
            "domains": [{
                "domain": "bluetooth",
                "status": "available",
                "active": "org.msys.hal.radio:bluetooth",
            }],
            "devices": [{
                "id": "bluetooth:hci0",
                "domain": "bluetooth",
                "available": True,
            }],
        }
        view = radio_domain_view(payload, "bluetooth")
        self.assertTrue(view["installed"])
        self.assertTrue(view["available"])
        self.assertEqual(view["provider"], "org.msys.hal.radio:bluetooth")
        payload["domains"][0]["status"] = "unavailable"
        self.assertFalse(radio_domain_view(payload, "bluetooth")["available"])
        payload["domains"][0]["status"] = "degraded"
        self.assertFalse(radio_domain_view(payload, "bluetooth")["available"])

    def test_network_domain_requires_a_real_wifi_device_for_readiness(self) -> None:
        payload = {
            "domains": [{
                "domain": "network",
                "status": "available",
                "active": "org.msys.hal.linux:linux-network",
            }],
            "devices": [{
                "id": "network:eth0",
                "domain": "network",
                "metadata": {"kind": "ethernet"},
            }],
        }
        ethernet_only = radio_domain_view(payload, "network")
        self.assertFalse(ethernet_only["available"])
        self.assertEqual(ethernet_only["reason"], "no-wifi-device")
        payload["devices"].append({
            "id": "network:wlan0",
            "domain": "network",
            "metadata": {"kind": "wifi", "wifi_control": "available"},
        })
        self.assertTrue(radio_domain_view(payload, "network")["available"])

    def test_bluetooth_power_is_writable_only_when_typed_mutable_says_so(self) -> None:
        readonly = radio_state_summary({
            "available": True,
            "provider": "org.msys.hal.radio:bluetooth",
            "values": {"powered": False},
            "mutable": [],
        })
        self.assertFalse(readonly["can_set_enabled"])
        writable = radio_state_summary({
            "available": True,
            "provider": "org.msys.hal.radio:bluetooth",
            "values": {"powered": False},
            "mutable": ["powered"],
        })
        self.assertEqual(writable["power_field"], "powered")
        self.assertTrue(writable["can_set_enabled"])

    def test_network_action_contract_does_not_create_a_fake_power_switch(self) -> None:
        state = radio_state_summary({
            "available": True,
            "provider": "org.msys.hal.radio:network",
            "values": {"wifi_control": "available", "action": "idle"},
            "mutable": ["action"],
        })
        self.assertIsNone(state["enabled"])
        self.assertFalse(state["can_set_enabled"])
        self.assertEqual(state["mutable"], ["action"])

    def test_write_only_network_action_is_valid_hal_state(self) -> None:
        state = normalise_hal_state(
            {
                "provider": "org.msys.hal.radio:network",
                "state": {
                    "id": "network:wlan0",
                    "domain": "network",
                    "available": True,
                    "values": {"wifi_control": "available", "scan_results": []},
                    "mutable": ["action"],
                },
            },
            "network:wlan0",
        )
        self.assertEqual(state["mutable"], ["action"])
        self.assertNotIn("action", state["values"])

    def test_wifi_rows_merge_saved_profiles_and_keep_exact_forget_id(self) -> None:
        rows = wifi_network_rows({
            "scan_results": [
                {"ssid": "Known", "signal_dbm": -40, "flags": "[WPA2]"},
                {"ssid": "New", "signal_dbm": -50, "flags": "[WPA2]"},
            ],
            "configured_networks": [
                {"network_id": 2, "ssid": "Known", "bssid": "any", "flags": "[CURRENT]"},
                {"network_id": 7, "ssid": "Out of range", "bssid": "any", "flags": ""},
            ],
        })
        known = next(row for row in rows if row["ssid"] == "Known")
        out_of_range = next(row for row in rows if row["ssid"] == "Out of range")
        self.assertTrue(known["configured"])
        self.assertEqual(known["network_id"], 2)
        self.assertEqual(out_of_range["source"], "configured")
        self.assertEqual(
            wifi_forget_changes(out_of_range),
            {"action": "forget", "network_id": 7},
        )

    def test_connect_omits_psk_for_saved_supports_open_and_requires_secured_psk(self) -> None:
        saved = {"ssid": "Known", "configured": True, "network_id": 2}
        new = {"ssid": "New", "configured": False, "network_id": None, "security": "secured"}
        open_network = {
            "ssid": "Cafe",
            "configured": False,
            "network_id": None,
            "security": "open",
        }
        self.assertEqual(
            wifi_connect_changes(saved, "must-not-be-forwarded"),
            {"action": "connect", "ssid": "Known"},
        )
        with self.assertRaises(ValueError):
            wifi_connect_changes(new, "")
        self.assertEqual(
            wifi_connect_changes(new, "new-password"),
            {"action": "connect", "ssid": "New", "psk": "new-password"},
        )
        self.assertEqual(
            wifi_connect_changes(open_network, ""),
            {"action": "connect", "ssid": "Cafe", "security": "open"},
        )

    def test_forget_rejects_nonconfigured_or_inexact_rows(self) -> None:
        with self.assertRaises(ValueError):
            wifi_forget_changes({"ssid": "New", "configured": False})
        with self.assertRaises(ValueError):
            wifi_forget_changes({"ssid": "Saved", "configured": True})



if __name__ == "__main__":
    unittest.main()
