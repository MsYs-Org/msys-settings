from __future__ import annotations

import unittest

from msys_settings.ipc import MipcRemoteError
from msys_settings.model import (
    DISPLAY_MIGRATION_SCHEMA,
    DisplayMigrationTracker,
    SettingsModel,
    hal_state_changes,
    normalise_desktop_preferences,
    normalise_hal_domains,
    normalise_hal_inventory,
    normalise_hal_state,
    normalise_install_agent_result,
    normalise_role_catalog,
    validate_desktop_preferences,
    validate_layout,
)


class FakeClient:
    def list_components(self):
        return {"components": [{"id": "a", "state": "ready"}]}

    def discover(self):
        raise MipcRemoteError("NO_METHOD", "discovery disabled")

    def isolation_capabilities(self):
        return {"no_new_privs": True}

    def get_layout(self):
        return {"profile": "mobile"}

    def set_layout(self, profile, orientation, insets):
        return {"profile": profile, "orientation_policy": orientation, "insets_policy": insets}

    def get_desktop_preferences(self):
        return {
            "preferences": {
                "layout": "desktop",
                "wallpaper_color": "#101419",
                "accent_color": "#55A8FF",
                "icon_size": 64,
                "show_labels": True,
                "sort": "name",
            },
            "revision": 4,
        }

    def set_desktop_preferences(self, preferences):
        return {"preferences": preferences, "revision": 5}

    def list_roles(self):
        return {"roles": []}

    def select_role(self, role, provider):
        return {"role": role, "preferred": provider}

    def reset_role(self, role):
        return {"role": role}

    def hal_inventory(self, *, refresh=False):
        raise MipcRemoteError("NO_PROVIDER", "HAL manager unavailable")

    def hal_list_providers(self, domain=None, *, refresh=False, probe=None):
        raise MipcRemoteError("NO_PROVIDER", "HAL manager unavailable")

    def request_update_check(self, source, package):
        return {
            "schema": "msys.install-agent-result.v1",
            "operation": "check_updates",
            "ok": True,
            "result": {"source": source, "package": package, "updates": []},
        }

    def request_update_apply(self, source, package):
        return {
            "schema": "msys.install-agent-result.v1",
            "operation": "apply_updates",
            "ok": True,
            "result": {"applied": [], "errors": []},
        }

    def request_rollback(self, package):
        return {
            "schema": "msys.install-agent-result.v1",
            "operation": "rollback",
            "ok": True,
            "package": package,
            "version": "1.0.0",
        }

    def display_migration_status(self, migration_id):
        return {"migration": migration_record(migration_id, "switching")}


class PartialUpdateClient(FakeClient):
    def request_update_apply(self, source, package):
        return {
            "schema": "msys.install-agent-result.v1",
            "operation": "apply_updates",
            "ok": False,
            "result": {
                "applied": [],
                "errors": [{
                    "package": package,
                    "code": "UPDATE_DOWNLOAD_FAILED",
                    "message": "artifact digest mismatch",
                }],
            },
        }


class RollbackErrorClient(FakeClient):
    def request_rollback(self, package):
        raise MipcRemoteError(
            "INSTALL_COMMIT_HEALTH_FAILED",
            "critical component did not become ready",
            {
                "schema": "msys.install-agent-error.v1",
                "operation": "rollback",
                "details": {"package": package, "recovery_complete": True},
            },
        )


def migration_record(
    migration_id: int,
    phase: str,
    **fields,
):
    record = {
        "schema": DISPLAY_MIGRATION_SCHEMA,
        "id": migration_id,
        "phase": phase,
        "role": "display-output",
        "from_provider": "org.example:spi",
        "to_provider": "org.example:hdmi",
    }
    if phase == "rolled-back":
        record["error"] = {
            "code": "DISPLAY_TARGET_NOT_READY",
            "message": "HDMI provider did not become ready",
        }
        record["rollback_complete"] = True
    record.update(fields)
    return record


class WorkingHalClient(FakeClient):
    def __init__(self):
        self.hal_calls = []

    def hal_inventory(self, *, refresh=False):
        self.hal_calls.append(("inventory", refresh))
        return {
            "schema": "org.msys.hal.manager.v1",
            "revision": 3,
            "domains": [{
                "domain": "display",
                "status": "available",
                "provider": "org.example.hal:display",
                "selection": "automatic",
            }],
            "devices": [{
                "id": "display:primary",
                "domain": "display",
                "name": "Primary display",
                "available": True,
                "mutable": ["orientation"],
                "metadata": {"output": "SPI"},
                "provider": "org.example.hal:display",
            }],
        }

    def hal_list_providers(self, domain=None, *, refresh=False, probe=None):
        self.hal_calls.append(("list_providers", domain, refresh, probe))
        candidate = {
            "component": "org.example.hal:display",
            "name": "Board display",
            "version": "1.0.0",
            "priority": 100,
        }
        if domain is not None:
            candidate.update({
                "domains": ["display"],
                "capabilities": [
                    "display.inventory",
                    "display.layout.orientation",
                    "display.state.read",
                ],
                "health": {
                    "status": "available",
                    "reason": "healthy",
                    "checked_at_unix_ms": 1000,
                    "latency_ms": 2,
                    "device_count": 1,
                    "mutable": ["orientation"],
                    "mutable_truncated": False,
                },
            })
        return {
            "schema": "org.msys.hal.manager.v1",
            "revision": 3,
            "providers": [{
                "domain": "display",
                "selection": "automatic",
                "preferred": None,
                "active": "org.example.hal:display",
                "candidates": [candidate],
            }],
        }

    def hal_get_state(self, device, *, refresh=False):
        self.hal_calls.append(("get_state", device, refresh))
        return {
            "schema": "org.msys.hal.manager.v1",
            "revision": 3,
            "provider": "org.example.hal:display",
            "state": {
                "id": device,
                "domain": "display",
                "available": True,
                "values": {"orientation": "portrait"},
                "mutable": ["orientation"],
            },
        }

    def hal_set_state(self, device, changes):
        self.hal_calls.append(("set_state", device, changes))
        response = self.hal_get_state(device)
        response["state"]["values"].update(changes)
        return response

    def hal_select_provider(
        self,
        domain,
        provider,
        *,
        expected_revision=None,
        allow_unavailable=False,
    ):
        self.hal_calls.append((
            "select_provider",
            domain,
            provider,
            expected_revision,
            allow_unavailable,
        ))
        return {"providers": [{"domain": domain, "active": provider}]}

    def hal_reset_provider(self, domain, *, expected_revision=None):
        self.hal_calls.append(("reset_provider", domain, expected_revision))
        return {"providers": [{"domain": domain, "selection": "automatic"}]}


class PartialHalClient(WorkingHalClient):
    def hal_list_providers(self, domain=None, *, refresh=False, probe=None):
        raise MipcRemoteError("HAL_UNKNOWN_METHOD", "provider management unavailable")


class RotationHalClient(WorkingHalClient):
    def hal_inventory(self, *, refresh=False):
        response = super().hal_inventory(refresh=refresh)
        response["devices"][0]["mutable"] = ["physical_rotation"]
        response["devices"][0]["metadata"]["physical_rotation_control"] = "writable"
        return response

    def hal_get_state(self, device, *, refresh=False):
        self.hal_calls.append(("get_state", device, refresh))
        return {
            "schema": "org.msys.hal.manager.v1",
            "revision": 3,
            "provider": "org.example.hal:display",
            "state": {
                "id": device,
                "domain": "display",
                "available": True,
                "values": {
                    "physical_rotation": "right",
                    "physical_rotation_control": "writable",
                },
                "mutable": ["physical_rotation"],
            },
        }


class MalformedHalClient(WorkingHalClient):
    def hal_inventory(self, *, refresh=False):
        return {
            "domains": [{"domain": "power", "status": "broken"}],
            "devices": [],
        }

    def hal_list_providers(self, domain=None, *, refresh=False, probe=None):
        return {"providers": []}


class MalformedProviderClient(WorkingHalClient):
    def hal_list_providers(self, domain=None, *, refresh=False, probe=None):
        return {"providers": "not-a-list"}


class InventoryUnavailableClient(WorkingHalClient):
    def hal_inventory(self, *, refresh=False):
        self.hal_calls.append(("inventory", refresh))
        raise MipcRemoteError("HAL_PROVIDER_ERROR", "display provider failed")


class LegacyHalClient(WorkingHalClient):
    def hal_list_providers(self, domain=None, *, refresh=False, probe=None):
        if probe is not None:
            self.hal_calls.append(("list_providers", domain, refresh, probe))
            raise MipcRemoteError("HAL_BAD_PAYLOAD", "unknown field probe")
        response = super().hal_list_providers(
            domain,
            refresh=refresh,
            probe=None,
        )
        for row in response.get("providers", []):
            for candidate in row.get("candidates", []):
                candidate.pop("domains", None)
                candidate.pop("capabilities", None)
                candidate.pop("health", None)
        return response

    def hal_select_provider(
        self,
        domain,
        provider,
        *,
        expected_revision=None,
        allow_unavailable=False,
    ):
        if expected_revision is not None:
            self.hal_calls.append((
                "select_provider",
                domain,
                provider,
                expected_revision,
                allow_unavailable,
            ))
            raise MipcRemoteError("HAL_BAD_PAYLOAD", "unknown field expected_revision")
        return super().hal_select_provider(domain, provider)

    def hal_reset_provider(self, domain, *, expected_revision=None):
        if expected_revision is not None:
            self.hal_calls.append(("reset_provider", domain, expected_revision))
            raise MipcRemoteError("HAL_BAD_PAYLOAD", "unknown field expected_revision")
        return super().hal_reset_provider(domain)


class ConflictingHalClient(WorkingHalClient):
    def hal_select_provider(
        self,
        domain,
        provider,
        *,
        expected_revision=None,
        allow_unavailable=False,
    ):
        self.hal_calls.append((
            "select_provider",
            domain,
            provider,
            expected_revision,
            allow_unavailable,
        ))
        raise MipcRemoteError(
            "HAL_CONFLICT",
            "HAL provider selection changed concurrently",
            {"expected_revision": expected_revision, "actual_revision": 4},
        )


class ProbeFailureHalClient(WorkingHalClient):
    def hal_list_providers(self, domain=None, *, refresh=False, probe=None):
        if domain is not None and probe:
            self.hal_calls.append(("list_providers", domain, refresh, probe))
            raise MipcRemoteError("HAL_UNAVAILABLE", "provider probe timed out")
        return super().hal_list_providers(
            domain,
            refresh=refresh,
            probe=probe,
        )


class DisplaySettingsClient(WorkingHalClient):
    def get_layout(self):
        return {
            "schema": "msys.window-layout.v1",
            "effective": {
                "profile": "mobile",
                "orientation_policy": "portrait",
                "insets_policy": "auto",
            },
        }

    def list_roles(self):
        return {
            "roles": [{
                "role": "display-output",
                "exclusive": True,
                "preferred": "org.example.spi:output",
                "active": "org.example.spi:output",
                "active_providers": ["org.example.spi:output"],
                "candidates": [{
                    "component": "org.example.spi:output",
                    "priority": 100,
                    "exclusive": True,
                    "explicit": True,
                    "declared": True,
                    "state": "ready",
                }],
            }],
        }


class OfflineDisplayClient(FakeClient):
    def get_layout(self):
        raise MipcRemoteError("NO_PROVIDER", "window manager unavailable")

    def list_roles(self):
        raise MipcRemoteError("CONTROL_UNAVAILABLE", "core unavailable")


class MalformedRoleClient(FakeClient):
    def list_roles(self):
        return {"roles": [{"role": "display-output", "candidates": "bad"}]}


class SettingsModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = SettingsModel(FakeClient())  # type: ignore[arg-type]

    def test_overview_is_useful_when_one_optional_call_fails(self) -> None:
        result = self.model.overview()
        self.assertTrue(result.ok)
        self.assertEqual(result.data["components"]["components"][0]["state"], "ready")
        self.assertEqual(result.data["partial_errors"][0]["section"], "services")

    def test_missing_hal_is_a_page_result_not_an_exception(self) -> None:
        result = self.model.hal_inventory()
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "NO_PROVIDER")

    def test_overview_includes_dynamic_roles_without_name_errors(self) -> None:
        client = DisplaySettingsClient()
        result = SettingsModel(client).overview()  # type: ignore[arg-type]
        self.assertTrue(result.ok)
        self.assertEqual(
            result.data["roles"]["roles"][0]["role"],
            "display-output",
        )

    def test_malformed_role_catalog_is_a_structured_page_error(self) -> None:
        result = SettingsModel(MalformedRoleClient()).list_roles()  # type: ignore[arg-type]
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "ROLE_BAD_RESPONSE")
        self.assertIn("invalid candidates", result.message)

    def test_display_settings_combines_layout_output_role_and_hal(self) -> None:
        result = SettingsModel(DisplaySettingsClient()).display_settings()  # type: ignore[arg-type]
        self.assertTrue(result.ok)
        self.assertTrue(result.data["layout"]["available"])
        self.assertEqual(
            result.data["output"]["role"]["active"],
            "org.example.spi:output",
        )
        self.assertEqual(
            result.data["hal"]["devices"][0]["id"],
            "display:primary",
        )
        self.assertEqual(result.data["partial_errors"], [])

    def test_display_settings_degrades_all_independent_services(self) -> None:
        result = SettingsModel(OfflineDisplayClient()).display_settings()  # type: ignore[arg-type]
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "UNAVAILABLE")
        self.assertFalse(result.data["layout"]["available"])
        self.assertFalse(result.data["output"]["available"])
        self.assertFalse(result.data["hal"]["available"])
        self.assertEqual(
            {item["section"] for item in result.data["partial_errors"]},
            {"layout", "output", "hal"},
        )

    def test_display_settings_keeps_layout_when_optional_contracts_are_missing(self) -> None:
        result = self.model.display_settings()
        self.assertTrue(result.ok)
        self.assertTrue(result.data["layout"]["available"])
        self.assertFalse(result.data["output"]["available"])
        self.assertFalse(result.data["hal"]["available"])
        self.assertEqual(
            {item["section"] for item in result.data["partial_errors"]},
            {"output", "hal"},
        )
        self.assertIn("Some display settings", result.message)

    def test_hal_inventory_combines_domains_devices_and_provider_candidates(self) -> None:
        client = WorkingHalClient()
        result = SettingsModel(client).hal_inventory(refresh=True)  # type: ignore[arg-type]
        self.assertTrue(result.ok)
        self.assertTrue(result.data["provider_management"]["available"])
        self.assertEqual(result.data["domains"][0]["domain"], "display")
        self.assertEqual(
            result.data["devices"][0]["providers"],
            ["org.example.hal:display"],
        )
        self.assertEqual(
            client.hal_calls[:3],
            [
                ("inventory", True),
                ("list_providers", None, True, None),
                ("list_providers", "display", False, True),
            ],
        )
        candidate = result.data["domains"][0]["candidates"][0]
        self.assertEqual(candidate["health"]["status"], "available")
        self.assertIn("display.layout.orientation", candidate["capabilities"])
        self.assertTrue(candidate["selectable"])
        self.assertEqual(result.data["revision"], 3)

    def test_hal_provider_management_failure_keeps_inventory_usable(self) -> None:
        result = SettingsModel(PartialHalClient()).hal_inventory()  # type: ignore[arg-type]
        self.assertTrue(result.ok)
        self.assertFalse(result.data["provider_management"]["available"])
        self.assertEqual(len(result.data["devices"]), 1)
        self.assertIn("provider management", result.message)

    def test_hal_inventory_failure_keeps_provider_management_usable(self) -> None:
        client = InventoryUnavailableClient()
        result = SettingsModel(client).hal_inventory()  # type: ignore[arg-type]
        self.assertTrue(result.ok)
        self.assertFalse(result.data["inventory_status"]["available"])
        self.assertTrue(result.data["provider_management"]["available"])
        self.assertEqual(result.data["devices"], [])
        self.assertEqual(result.data["domains"][0]["domain"], "display")
        self.assertIn("provider management remains available", result.message)

    def test_malformed_provider_catalog_keeps_inventory_usable(self) -> None:
        result = SettingsModel(MalformedProviderClient()).hal_inventory()  # type: ignore[arg-type]
        self.assertTrue(result.ok)
        management = result.data["provider_management"]
        self.assertFalse(management["available"])
        self.assertEqual(management["code"], "HAL_BAD_RESPONSE")
        self.assertEqual(result.data["devices"][0]["id"], "display:primary")

    def test_malformed_hal_response_is_structured_page_error(self) -> None:
        result = SettingsModel(MalformedHalClient()).hal_inventory()  # type: ignore[arg-type]
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "HAL_BAD_RESPONSE")
        self.assertIn("invalid status", result.message)
        self.assertIn("inventory", result.data)

    def test_hal_state_and_provider_operations_use_manager_contract(self) -> None:
        client = WorkingHalClient()
        model = SettingsModel(client)  # type: ignore[arg-type]
        read = model.hal_get_state("display:primary")
        self.assertTrue(read.ok)
        self.assertEqual(read.data["values"], {"orientation": "portrait"})
        self.assertIn(("get_state", "display:primary", True), client.hal_calls)
        changed = model.hal_set_state(
            "display:primary", {"orientation": "landscape"}
        )
        self.assertTrue(changed.ok)
        self.assertEqual(changed.data["values"]["orientation"], "landscape")
        self.assertTrue(
            model.select_hal_provider("display", "org.example.hal:display").ok
        )
        self.assertTrue(model.reset_hal_provider("display").ok)
        self.assertIn(
            (
                "select_provider",
                "display",
                "org.example.hal:display",
                None,
                False,
            ),
            client.hal_calls,
        )
        self.assertIn(("reset_provider", "display", None), client.hal_calls)

    def test_hal_013_falls_back_without_losing_provider_management(self) -> None:
        client = LegacyHalClient()
        model = SettingsModel(client)  # type: ignore[arg-type]
        inventory = model.hal_inventory(refresh=True)
        self.assertTrue(inventory.ok)
        self.assertFalse(
            inventory.data["provider_management"]["probe_supported"]
        )
        candidate = inventory.data["domains"][0]["candidates"][0]
        self.assertEqual(candidate["health"]["status"], "unknown")
        self.assertFalse(candidate["health"]["reported"])
        self.assertTrue(candidate["selectable"])
        self.assertIn(
            ("list_providers", "display", False, True),
            client.hal_calls,
        )
        self.assertIn(
            ("list_providers", "display", False, None),
            client.hal_calls,
        )

        selected = model.select_hal_provider(
            "display",
            "org.example.hal:display",
            expected_revision=3,
        )
        reset = model.reset_hal_provider("display", expected_revision=3)
        self.assertTrue(selected.ok)
        self.assertTrue(reset.ok)
        self.assertIn(
            (
                "select_provider",
                "display",
                "org.example.hal:display",
                3,
                False,
            ),
            client.hal_calls,
        )
        self.assertIn(("reset_provider", "display", 3), client.hal_calls)

    def test_hal_conflict_is_never_retried_as_legacy_write(self) -> None:
        client = ConflictingHalClient()
        result = SettingsModel(client).select_hal_provider(  # type: ignore[arg-type]
            "display",
            "org.example.hal:display",
            expected_revision=3,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "HAL_CONFLICT")
        calls = [item for item in client.hal_calls if item[0] == "select_provider"]
        self.assertEqual(len(calls), 1)

    def test_unavailable_override_never_downgrades_to_legacy_unsafe_write(self) -> None:
        client = LegacyHalClient()
        result = SettingsModel(client).select_hal_provider(  # type: ignore[arg-type]
            "display",
            "org.example.hal:display",
            expected_revision=3,
            allow_unavailable=True,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "HAL_BAD_PAYLOAD")
        calls = [item for item in client.hal_calls if item[0] == "select_provider"]
        self.assertEqual(len(calls), 1)

    def test_failed_health_probe_disables_candidate_by_default(self) -> None:
        result = SettingsModel(ProbeFailureHalClient()).hal_inventory()  # type: ignore[arg-type]
        self.assertTrue(result.ok)
        self.assertTrue(result.data["provider_management"]["degraded"])
        candidate = result.data["domains"][0]["candidates"][0]
        self.assertFalse(candidate["selectable"])
        self.assertEqual(candidate["health"]["status"], "unavailable")
        self.assertEqual(candidate["health"]["error_code"], "HAL_UNAVAILABLE")

    def test_hal_operations_validate_empty_selection_and_changes(self) -> None:
        model = SettingsModel(WorkingHalClient())  # type: ignore[arg-type]
        self.assertFalse(model.hal_set_state("display:primary", {}).ok)
        self.assertFalse(model.select_hal_provider("", "provider").ok)
        self.assertFalse(model.select_hal_provider("display", "provider").ok)
        self.assertFalse(model.select_hal_provider(
            "display",
            "org.example.hal:display",
            expected_revision=True,
        ).ok)
        self.assertFalse(model.reset_hal_provider("bad domain").ok)
        self.assertFalse(model.reset_hal_provider(
            "display",
            expected_revision=-1,
        ).ok)

    def test_layout_is_validated_before_call(self) -> None:
        invalid = self.model.set_layout("tablet", "auto", "auto")
        self.assertFalse(invalid.ok)
        self.assertEqual(invalid.code, "INVALID_LAYOUT")
        valid = self.model.set_layout("desktop", "landscape", "10,20,30,40")
        self.assertTrue(valid.ok)
        self.assertEqual(valid.data["insets_policy"]["right"], 20)

    def test_physical_rotation_is_capability_gated_and_uses_hal_state(self) -> None:
        unavailable = SettingsModel(WorkingHalClient()).physical_rotation()  # type: ignore[arg-type]
        self.assertTrue(unavailable.ok)
        self.assertFalse(unavailable.data["available"])
        self.assertFalse(unavailable.data["writable"])

        client = RotationHalClient()
        model = SettingsModel(client)  # type: ignore[arg-type]
        capability = model.physical_rotation(refresh=True)
        self.assertTrue(capability.ok)
        self.assertTrue(capability.data["available"])
        self.assertTrue(capability.data["writable"])
        self.assertEqual(capability.data["value"], "right")
        changed = model.set_physical_rotation("display:primary", "left")
        self.assertTrue(changed.ok)
        self.assertIn(
            ("set_state", "display:primary", {"physical_rotation": "left"}),
            client.hal_calls,
        )
        self.assertFalse(model.set_physical_rotation("", "left").ok)
        self.assertFalse(
            model.set_physical_rotation("display:primary", "clockwise").ok
        )

    def test_desktop_preferences_are_validated_and_normalised(self) -> None:
        read = self.model.desktop_preferences()
        self.assertTrue(read.ok)
        self.assertEqual(read.data["preferences"]["layout"], "desktop")
        changed = self.model.set_desktop_preferences(
            "mobile", "#abcdef", "#123456", "72", False, "component"
        )
        self.assertTrue(changed.ok)
        self.assertEqual(changed.data["preferences"]["wallpaper_color"], "#ABCDEF")
        self.assertEqual(changed.data["preferences"]["icon_size"], 72)
        invalid = self.model.set_desktop_preferences(
            "tablet", "red", "#123456", 10, True, "recent"
        )
        self.assertFalse(invalid.ok)
        self.assertEqual(invalid.code, "INVALID_PREFERENCES")

    def test_update_requires_source_and_valid_package(self) -> None:
        self.assertFalse(self.model.request_update("check", "", "all").ok)
        self.assertFalse(self.model.request_update("check", "index.json", "Bad ID").ok)
        self.assertTrue(self.model.request_update("check", "index.json", "all").ok)

    def test_partial_apply_exposes_real_terminal_result_and_errors(self) -> None:
        result = SettingsModel(PartialUpdateClient()).request_update(  # type: ignore[arg-type]
            "apply", "index.json", "org.example.app"
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "UPDATE_DOWNLOAD_FAILED")
        self.assertEqual(result.data["schema"], "msys.install-agent-result.v1")
        self.assertFalse(result.data["ok"])
        self.assertEqual(
            result.data["result"]["errors"][0]["message"],
            "artifact digest mismatch",
        )

    def test_rpc_error_preserves_structured_install_agent_payload(self) -> None:
        result = SettingsModel(RollbackErrorClient()).request_rollback(  # type: ignore[arg-type]
            "org.example.app"
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "INSTALL_COMMIT_HEALTH_FAILED")
        self.assertEqual(result.data["schema"], "msys.install-agent-error.v1")
        self.assertTrue(result.data["details"]["recovery_complete"])

    def test_malformed_terminal_envelope_is_not_reported_as_success(self) -> None:
        result = normalise_install_agent_result(
            {"ok": True, "result": {"updates": []}},
            "check_updates",
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "INSTALL_AGENT_BAD_RESPONSE")

    def test_display_migration_status_is_validated(self) -> None:
        result = self.model.display_migration_status(9)
        self.assertTrue(result.ok)
        self.assertEqual(result.data["id"], 9)
        self.assertEqual(result.data["phase"], "switching")
        self.assertEqual(
            self.model.display_migration_status(0).code,
            "BAD_MIGRATION_ID",
        )


class NormalizationTests(unittest.TestCase):
    def test_current_core_role_summary_shape_is_accepted(self) -> None:
        catalog = normalise_role_catalog({
            "roles": [{
                "role": "display-output",
                "exclusive": True,
                "preferred": "org.msys.openstick.ch347:x11-spi-touch-output",
                "active": "org.msys.openstick.ch347:x11-spi-touch-output",
                "active_providers": [
                    "org.msys.openstick.ch347:x11-spi-touch-output"
                ],
                "candidates": [{
                    "component": "org.msys.openstick.ch347:x11-spi-touch-output",
                    "priority": 100,
                    "exclusive": True,
                    "explicit": True,
                    "declared": True,
                    "state": "ready",
                }],
            }, {
                "role": "vendor.status-source",
                "exclusive": False,
                "preferred": None,
                "active": None,
                "active_providers": [],
                "candidates": [],
            }],
        })
        output = catalog["roles"][0]
        self.assertEqual(output["active"], output["candidates"][0]["component"])
        self.assertTrue(output["available"])
        self.assertFalse(catalog["roles"][1]["available"])

    def test_role_catalog_rejects_duplicates_and_malformed_candidates(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate role"):
            normalise_role_catalog({
                "roles": [
                    {"role": "launcher", "candidates": []},
                    {"role": "launcher", "candidates": []},
                ]
            })
        with self.assertRaisesRegex(ValueError, "invalid candidate"):
            normalise_role_catalog({
                "roles": [{"role": "launcher", "candidates": [{}]}]
            })

    def test_display_migration_tracker_orders_and_deduplicates_phases(self) -> None:
        tracker = DisplayMigrationTracker()
        self.assertEqual(tracker.consume(migration_record(4, "planned"))["phase"], "planned")
        self.assertEqual(tracker.active_id, 4)
        self.assertEqual(
            tracker.consume(migration_record(4, "switching"))["phase"],
            "switching",
        )
        self.assertIsNone(tracker.consume(migration_record(4, "planned")))
        terminal = tracker.consume(migration_record(4, "rolled-back"))
        self.assertEqual(terminal["error"]["code"], "DISPLAY_TARGET_NOT_READY")
        self.assertIsNone(tracker.active_id)
        self.assertEqual(tracker.last_terminal_id, 4)
        self.assertIsNone(tracker.consume(migration_record(4, "rolled-back")))

    def test_display_migration_tracker_ignores_stale_other_transaction(self) -> None:
        tracker = DisplayMigrationTracker()
        tracker.consume(migration_record(7, "planned"))
        self.assertIsNone(tracker.consume(migration_record(6, "succeeded")))
        self.assertEqual(tracker.active_id, 7)

    def test_layout_contract(self) -> None:
        self.assertEqual(validate_layout("mobile", "auto", "auto"), "auto")
        self.assertEqual(
            validate_layout("kiosk", "portrait", "1,2,3,4"),
            {"top": 1, "right": 2, "bottom": 3, "left": 4},
        )
        for value in ("1, 2,3,4", "1,2,3", "1,2,3,-4"):
            with self.assertRaises(ValueError):
                validate_layout("mobile", "auto", value)

    def test_hal_inventory_accepts_map_and_candidate_objects(self) -> None:
        devices = normalise_hal_inventory(
            {
                "devices": {
                    "display.internal": {
                        "kind": "display",
                        "active_provider": "org.example:display",
                        "candidates": [{"component": "org.example:display"}],
                    }
                }
            }
        )
        self.assertEqual(devices[0]["id"], "display.internal")
        self.assertEqual(devices[0]["provider"], "org.example:display")
        self.assertEqual(devices[0]["providers"], ["org.example:display"])

    def test_hal_v1_domain_and_state_normalization(self) -> None:
        domains = normalise_hal_domains(
            {
                "domains": [{
                    "domain": "power",
                    "status": "unavailable",
                    "reason": "no-device",
                    "provider": "org.example:power",
                }]
            },
            {
                "providers": [{
                    "domain": "power",
                    "selection": "manual",
                    "preferred": "org.example:power",
                    "active": "org.example:power",
                    "candidates": [{"component": "org.example:power"}],
                }]
            },
        )
        self.assertEqual(domains[0]["status"], "unavailable")
        self.assertEqual(domains[0]["selection"], "manual")
        state = normalise_hal_state(
            {
                "provider": "org.example:power",
                "state": {
                    "id": "power:BAT0",
                    "domain": "power",
                    "available": True,
                    "values": {"capacity_percent": 80},
                    "mutable": [],
                },
            },
            "power:BAT0",
        )
        self.assertEqual(state["values"]["capacity_percent"], 80)
        with self.assertRaises(ValueError):
            normalise_hal_state(
                {"state": {"id": "power:BAT1", "values": {}, "mutable": []}},
                "power:BAT0",
            )

    def test_hal_014_candidate_health_controls_safe_selection(self) -> None:
        domains = normalise_hal_domains({}, {
            "providers": [{
                "domain": "display",
                "selection": "automatic",
                "active": "org.example.hal:display",
                "candidates": [{
                    "component": "org.example.hal:display",
                    "domains": ["display"],
                    "capabilities": [
                        "display.inventory",
                        "display.state.read",
                    ],
                    "health": {
                        "status": "unavailable",
                        "reason": "provider-error",
                        "latency_ms": 12,
                        "error_code": "HAL_PROVIDER_ERROR",
                    },
                }],
            }],
        })
        candidate = domains[0]["candidates"][0]
        self.assertFalse(candidate["selectable"])
        self.assertEqual(candidate["health"]["status"], "unavailable")
        self.assertEqual(candidate["capabilities"], [
            "display.inventory",
            "display.state.read",
        ])

    def test_hal_014_candidate_contract_is_bounded_and_domain_scoped(self) -> None:
        with self.assertRaisesRegex(ValueError, "capability"):
            normalise_hal_domains({}, {
                "providers": [{
                    "domain": "display",
                    "candidates": [{
                        "component": "org.example.hal:display",
                        "domains": ["display"],
                        "capabilities": ["power.state.read"],
                        "health": {"status": "available"},
                    }],
                }],
            })
        with self.assertRaisesRegex(ValueError, "health status"):
            normalise_hal_domains({}, {
                "providers": [{
                    "domain": "display",
                    "candidates": [{
                        "component": "org.example.hal:display",
                        "domains": ["display"],
                        "capabilities": [],
                        "health": {"status": "broken"},
                    }],
                }],
            })

    def test_desktop_preferences_contract(self) -> None:
        preferences = validate_desktop_preferences({
            "layout": "kiosk",
            "wallpaper_color": "#abcdef",
            "accent_color": "#123456",
            "icon_size": "80",
            "show_labels": False,
            "sort": "component",
        })
        self.assertEqual(preferences["wallpaper_color"], "#ABCDEF")
        self.assertEqual(preferences["icon_size"], 80)
        self.assertEqual(
            validate_desktop_preferences({**preferences, "layout": "profile"})["layout"],
            "profile",
        )
        self.assertEqual(
            normalise_desktop_preferences({"preferences": preferences, "revision": 9})["revision"],
            9,
        )
        direct = normalise_desktop_preferences({**preferences, "revision": 10})
        self.assertEqual(direct["preferences"], preferences)
        self.assertEqual(direct["revision"], 10)
        with self.assertRaises(ValueError):
            validate_desktop_preferences({**preferences, "icon_size": True})
        with self.assertRaisesRegex(ValueError, "unsupported preferences schema"):
            normalise_desktop_preferences({
                "schema": "msys.shell-preferences.v2",
                "preferences": preferences,
            })

    def test_hal_changes_only_include_modified_mutable_fields(self) -> None:
        original = {"brightness": 30, "maximum": 255, "enabled": True}
        self.assertEqual(
            hal_state_changes(
                original,
                {"brightness": 80, "maximum": 255, "enabled": True},
                ["brightness", "enabled"],
            ),
            {"brightness": 80},
        )
        with self.assertRaisesRegex(ValueError, "Read-only"):
            hal_state_changes(
                original,
                {"brightness": 30, "maximum": 1, "enabled": True},
                ["brightness", "enabled"],
            )
        with self.assertRaisesRegex(ValueError, "No mutable"):
            hal_state_changes(original, dict(original), ["brightness"])

    def test_hal_normalizers_reject_malformed_availability(self) -> None:
        with self.assertRaisesRegex(ValueError, "availability"):
            normalise_hal_inventory({
                "devices": [{"id": "power:BAT0", "available": "yes"}]
            })
        with self.assertRaisesRegex(ValueError, "invalid state"):
            normalise_hal_state(
                {
                    "state": {
                        "id": "power:BAT0",
                        "available": "yes",
                        "values": {},
                        "mutable": [],
                    }
                },
                "power:BAT0",
            )

    def test_hal_normalizers_reject_duplicate_contract_rows(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate inventory domains"):
            normalise_hal_domains(
                {
                    "domains": [
                        {"domain": "power", "status": "available"},
                        {"domain": "power", "status": "unavailable"},
                    ]
                },
                {},
            )
        with self.assertRaisesRegex(ValueError, "duplicate device id"):
            normalise_hal_inventory({
                "devices": [
                    {"id": "power:BAT0"},
                    {"id": "power:BAT0"},
                ]
            })


if __name__ == "__main__":
    unittest.main()
