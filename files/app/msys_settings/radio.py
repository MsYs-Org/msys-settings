"""Pure presentation model for optional network and Bluetooth HAL domains."""

from __future__ import annotations

import re
from typing import Any


RADIO_DOMAINS = ("network", "bluetooth")


def radio_domain_view(payload: dict[str, Any], domain: str) -> dict[str, Any]:
    if domain not in RADIO_DOMAINS:
        raise ValueError("unsupported radio domain")
    if not isinstance(payload, dict):
        raise TypeError("HAL snapshot must be an object")
    raw_domains = payload.get("domains", [])
    raw_devices = payload.get("devices", [])
    if not isinstance(raw_domains, list) or not isinstance(raw_devices, list):
        raise ValueError("HAL snapshot contains invalid domain or device lists")
    domain_row = next(
        (
            item
            for item in raw_domains
            if isinstance(item, dict) and item.get("domain") == domain
        ),
        None,
    )
    devices = [
        dict(item)
        for item in raw_devices
        if isinstance(item, dict) and item.get("domain") == domain
    ]
    if domain_row is None:
        return {
            "domain": domain,
            "installed": False,
            "available": False,
            "status": "unavailable",
            "provider": "",
            "reason": "",
            "devices": devices,
        }
    status = str(domain_row.get("status") or "unknown")
    provider = str(domain_row.get("active") or domain_row.get("provider") or "")
    reason = str(domain_row.get("reason") or domain_row.get("error") or "")
    if domain == "network":
        wifi_devices = [
            item
            for item in devices
            if isinstance(item.get("metadata"), dict)
            and item["metadata"].get("kind") == "wifi"
        ]
        if not wifi_devices and not reason:
            reason = "no-wifi-device"
    else:
        wifi_devices = devices
    # A degraded domain may expose inventory but must not be presented as a
    # healthy radio toggle.  Its devices remain inspectable in the details.
    available = status == "available" and bool(provider) and bool(wifi_devices)
    return {
        "domain": domain,
        "installed": True,
        "available": available,
        "status": status,
        "provider": provider,
        "reason": reason,
        "devices": devices,
    }


def radio_state_summary(state: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise TypeError("radio state must be an object")
    values = state.get("values", {})
    mutable = state.get("mutable", [])
    if not isinstance(values, dict) or not isinstance(mutable, list):
        raise ValueError("radio state contains invalid values or mutable fields")
    power_field = "enabled" if isinstance(values.get("enabled"), bool) else (
        "powered" if isinstance(values.get("powered"), bool) else ""
    )
    enabled = values.get(power_field) if power_field else None
    return {
        "available": bool(state.get("available", True)),
        "provider": str(state.get("provider") or ""),
        "enabled": enabled if isinstance(enabled, bool) else None,
        "power_field": power_field,
        "can_set_enabled": power_field in mutable and isinstance(enabled, bool),
        "values": dict(values),
        "mutable": list(mutable),
    }


def wifi_network_rows(values: dict[str, Any]) -> list[dict[str, Any]]:
    """Combine bounded scan/configured rows without inventing saved state."""

    if not isinstance(values, dict):
        raise TypeError("Wi-Fi values must be an object")
    scans = values.get("scan_results", [])
    configured = values.get("configured_networks", [])
    scans = scans if isinstance(scans, list) else []
    configured = configured if isinstance(configured, list) else []

    saved: list[dict[str, Any]] = []
    for raw in configured:
        if not isinstance(raw, dict):
            continue
        network_id = raw.get("network_id")
        ssid = raw.get("ssid")
        if (
            isinstance(network_id, bool)
            or not isinstance(network_id, int)
            or not 0 <= network_id <= 4095
            or not isinstance(ssid, str)
            or not ssid
        ):
            continue
        saved.append({
            "ssid": ssid,
            "network_id": network_id,
            "flags": str(raw.get("flags") or ""),
        })

    by_ssid: dict[str, list[dict[str, Any]]] = {}
    for row in saved:
        by_ssid.setdefault(str(row["ssid"]), []).append(row)

    result: list[dict[str, Any]] = []
    scanned_ssids: set[str] = set()
    for raw in scans:
        if not isinstance(raw, dict):
            continue
        ssid = raw.get("ssid")
        if not isinstance(ssid, str) or not ssid:
            continue
        scanned_ssids.add(ssid)
        matches = by_ssid.get(ssid, [])
        exact = matches[0] if len(matches) == 1 else None
        flags = str(raw.get("flags") or "")
        upper_flags = flags.upper()
        result.append({
            "ssid": ssid,
            "signal_dbm": raw.get("signal_dbm"),
            "flags": flags,
            "security": (
                "secured"
                if any(
                    marker in upper_flags
                    for marker in ("WPA", "WEP", "SAE", "EAP", "RSN", "OWE")
                )
                else "open"
            ),
            "configured": exact is not None,
            "network_id": exact.get("network_id") if exact else None,
            "source": "scan",
        })

    # A saved profile that is out of range must remain visible and forgettable.
    # Duplicate saved SSIDs are kept as distinct exact network-id rows because
    # the HAL deliberately refuses an ambiguous SSID-only operation.
    for row in saved:
        matches = by_ssid.get(str(row["ssid"]), [])
        if row["ssid"] in scanned_ssids and len(matches) == 1:
            continue
        result.append({
            "ssid": row["ssid"],
            "signal_dbm": None,
            "flags": row["flags"],
            "security": "saved",
            "configured": True,
            "network_id": row["network_id"],
            "source": "configured",
        })
    return result


def wifi_connect_changes(row: dict[str, Any], password: str) -> dict[str, Any]:
    if not isinstance(row, dict) or not isinstance(row.get("ssid"), str) or not row["ssid"]:
        raise ValueError("Select a Wi-Fi network")
    changes: dict[str, Any] = {"action": "connect", "ssid": row["ssid"]}
    if row.get("configured") is True:
        return changes
    if row.get("security") == "open":
        changes["security"] = "open"
        return changes
    if not isinstance(password, str) or not password:
        raise ValueError("password-required")
    valid_hex = len(password) == 64 and re.fullmatch(r"[0-9A-Fa-f]{64}", password)
    valid_passphrase = 8 <= len(password) <= 63 and all(
        32 <= ord(character) <= 126 for character in password
    )
    if not valid_hex and not valid_passphrase:
        raise ValueError("password-invalid")
    changes["psk"] = password
    return changes


def wifi_forget_changes(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict) or row.get("configured") is not True:
        raise ValueError("Select a configured Wi-Fi network")
    network_id = row.get("network_id")
    if isinstance(network_id, bool) or not isinstance(network_id, int) or not 0 <= network_id <= 4095:
        raise ValueError("Configured Wi-Fi network has no exact network id")
    return {"action": "forget", "network_id": network_id}


__all__ = [
    "RADIO_DOMAINS",
    "radio_domain_view",
    "radio_state_summary",
    "wifi_connect_changes",
    "wifi_forget_changes",
    "wifi_network_rows",
]
