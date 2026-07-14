"""Pure focus routing shared by the Tk frontend and headless tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def role_focus_target(
    requested_role: str,
    roles: Mapping[str, Any],
) -> str | None:
    """Return a loaded role target, or ``None`` when refresh must be deferred."""

    return requested_role if requested_role and requested_role in roles else None


def hal_focus_target(
    requested_domain: str,
    domains: Mapping[str, Any],
    devices: Mapping[str, Mapping[str, Any]],
) -> tuple[str | None, str | None]:
    """Resolve a loaded HAL domain and its first matching device."""

    if not requested_domain or requested_domain not in domains:
        return None, None
    device = next(
        (
            identifier
            for identifier, item in devices.items()
            if item.get("domain") == requested_domain
        ),
        None,
    )
    return requested_domain, device


__all__ = ["hal_focus_target", "role_focus_target"]
