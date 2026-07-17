#!/usr/bin/env python3
"""UI-neutral bridge between the existing Settings model and native LVGL.

The protocol is intentionally tiny: UTF-8 ``key<TAB>percent-encoded value``
rows are grouped by BEGIN/END.  No UI state or HAL contract is duplicated in
the native renderer; all reads and mutations still pass through SettingsModel.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import sys
import threading
from typing import Any, Callable
from urllib.parse import quote, unquote

from msys_settings.client import SettingsClient
from msys_settings.ipc import ComponentChannel, PublicMipcClient
from msys_settings.model import OperationResult, SettingsModel
from msys_settings.radio import (
    radio_domain_view,
    radio_state_summary,
    wifi_connect_changes,
    wifi_forget_changes,
    wifi_network_rows,
)
from msys_settings.regional import RegionalSettingsStore


class Bridge:
    def __init__(self, model: SettingsModel) -> None:
        self.model = model
        self.regional = RegionalSettingsStore()
        self._write_lock = threading.Lock()
        self._collect_lock = threading.Lock()
        self._operation_lock = threading.Lock()
        self._desktop_lock = threading.Lock()
        self._sequence = 0
        self._radio: dict[str, dict[str, Any]] = {}
        self._audio: dict[str, Any] = {}
        self._hal: dict[str, Any] = {}
        self._physical: dict[str, Any] = {}
        self.mode = os.environ.get("MSYS_SETTINGS_MODE", "settings")
        self.update_source = os.environ.get("MSYS_UPDATE_SOURCE", "").strip()
        self._software_page = "apps"
        self._settings_page = "home"

    def emit(self, fields: dict[str, object]) -> None:
        with self._write_lock:
            self._sequence += 1
            print(f"BEGIN\t{self._sequence}")
            for key, value in fields.items():
                text = str(value if value is not None else "")
                print(f"{key}\t{quote(text, safe=' -._~:/')}")
            print(f"END\t{self._sequence}", flush=True)

    @staticmethod
    def _failure(result: OperationResult) -> str:
        return result.message or result.code or "不可用"

    @staticmethod
    def _item_fields(panel: str, rows: list[tuple[str, str, str]]) -> dict[str, object]:
        fields: dict[str, object] = {"items.panel": panel, "items.count": len(rows)}
        for index, (identifier, label, meta) in enumerate(rows[:64]):
            fields[f"items.{index}.id"] = identifier
            fields[f"items.{index}.label"] = label
            fields[f"items.{index}.meta"] = meta
        fields["items.count"] = min(len(rows), 64)
        return fields

    def local_fields(self) -> dict[str, object]:
        regional = self.regional.status()
        language = str(regional.get("language") or "system")
        timezone = str(regional.get("timezone") or "UTC")
        version = os.environ.get("MSYS_PACKAGE_VERSION", "development")
        return {
            "locale": language,
            "system.summary": f"MSYS Settings {version}",
            "system.detail": (
                f"component={os.environ.get('MSYS_COMPONENT_ID', 'standalone')}\n"
                f"display={os.environ.get('DISPLAY', 'unset')}"
            ),
            "regional.summary": f"{language} · {timezone}",
            "regional.detail": (
                f"语言：{language}\n时区：{timezone}\n"
                f"可写入时区：{'是' if regional.get('timezone_writable') else '否'}"
            ),
            "regional.available": "1",
            "regional.language": language,
            "regional.timezone": timezone,
            "software.source": self.update_source or "未配置更新源",
            "software.operation": "尚未执行更新操作。",
            "software.busy": "0",
        }

    def collect_hal(self) -> dict[str, object]:
        result = self.model.hal_inventory(refresh=False)
        if not result.ok:
            reason = self._failure(result)
            return {
                "wifi.summary": "不可用",
                "wifi.detail": reason,
                "bluetooth.summary": "不可用",
                "bluetooth.detail": reason,
                "display.hal": "HAL 不可用",
            }
        fields: dict[str, object] = {}
        inventory = result.data
        self._hal = dict(inventory)
        display_devices = [
            row for row in inventory.get("devices", [])
            if isinstance(row, dict)
            and row.get("domain") in {"display", "display-output"}
        ]
        fields["display.hal"] = f"{len(display_devices)} 个显示设备"
        domains = inventory.get("domains", [])
        provider_rows: list[str] = []
        provider_items: list[tuple[str, str, str]] = []
        mutable_domains = 0
        for row in domains if isinstance(domains, list) else []:
            if not isinstance(row, dict):
                continue
            domain = str(row.get("domain") or "")
            active = str(row.get("active") or row.get("provider") or "未选择")
            candidates = row.get("candidates", row.get("providers", []))
            candidate_count = len(candidates) if isinstance(candidates, list) else 0
            if candidate_count > 1:
                mutable_domains += 1
            if domain:
                provider_rows.append(f"{domain}：{active}（{candidate_count or 1} 个候选）")
            for candidate in candidates if isinstance(candidates, list) else []:
                if not isinstance(candidate, dict) or not candidate.get("component"):
                    continue
                component = str(candidate["component"])
                health = candidate.get("health", {})
                health_status = str(health.get("status") or "未知") if isinstance(health, dict) else "未知"
                flags = []
                if candidate.get("active"):
                    flags.append("当前")
                if candidate.get("selectable") is False:
                    flags.append("不可用")
                provider_items.append((
                    f"{domain}\x1f{component}",
                    str(candidate.get("name") or component),
                    f"{domain} · {health_status}" + (f" · {'/'.join(flags)}" if flags else ""),
                ))
        fields["hal.summary"] = f"{len(domains) if isinstance(domains, list) else 0} 个硬件域"
        fields["hal.detail"] = "\n".join(provider_rows) or "HAL 未报告任何硬件域"
        fields["hal.available"] = "1" if provider_rows else "0"
        fields["hal.mutable"] = "1" if mutable_domains else "0"
        fields.update(self._item_fields("hal", provider_items))
        for panel, domain in (("wifi", "network"), ("bluetooth", "bluetooth")):
            try:
                view = radio_domain_view(inventory, domain)
            except (TypeError, ValueError) as exc:
                fields[f"{panel}.summary"] = "不可用"
                fields[f"{panel}.detail"] = str(exc)
                continue
            devices = view.get("devices", [])
            device = next(
                (
                    row for row in devices
                    if isinstance(row, dict)
                    and (
                        domain != "network"
                        or (
                            isinstance(row.get("metadata"), dict)
                            and row["metadata"].get("kind") == "wifi"
                        )
                    )
                ),
                None,
            )
            if not view.get("available") or not isinstance(device, dict):
                reason = str(view.get("reason") or view.get("status") or "无设备")
                fields[f"{panel}.summary"] = "不可用"
                fields[f"{panel}.detail"] = reason
                continue
            identifier = str(device.get("id") or "")
            state_result = self.model.hal_get_state(identifier, refresh=False)
            if not state_result.ok:
                fields[f"{panel}.summary"] = "状态读取失败"
                fields[f"{panel}.detail"] = self._failure(state_result)
                continue
            try:
                state = radio_state_summary(state_result.data)
            except (TypeError, ValueError) as exc:
                fields[f"{panel}.summary"] = "状态无效"
                fields[f"{panel}.detail"] = str(exc)
                continue
            self._radio[panel] = {"device": identifier, **state}
            enabled = state.get("enabled")
            values = state.get("values", {})
            if panel == "wifi":
                wifi_status = values.get("wifi_status", {})
                if not isinstance(wifi_status, dict):
                    wifi_status = {}
                network = str(
                    values.get("current_ssid")
                    or values.get("ssid")
                    or values.get("connected_network")
                    or wifi_status.get("ssid")
                    or ""
                )
                signal = values.get("signal_dbm")
                if not isinstance(signal, int) and network:
                    candidates = [
                        row.get("signal_dbm")
                        for row in values.get("scan_results", [])
                        if isinstance(row, dict)
                        and row.get("ssid") == network
                        and isinstance(row.get("signal_dbm"), int)
                    ]
                    signal = max(candidates) if candidates else None
                suffix = f" · {signal} dBm" if isinstance(signal, int) else ""
                summary = network + suffix if network else ("已开启" if enabled else "已关闭")
                detail = (
                    f"设备：{identifier}\n提供者：{state.get('provider') or view.get('provider')}\n"
                    f"网络：{network or '未连接'}"
                )
                try:
                    networks = wifi_network_rows(values)
                except (TypeError, ValueError):
                    networks = []
                if networks:
                    detail += "\n\n可用网络：\n" + "\n".join(
                        f"{row.get('ssid')}  {row.get('signal_dbm', '')} dBm"
                        for row in networks[:12]
                    )
            else:
                summary = "已开启" if enabled else "已关闭"
                detail = (
                    f"设备：{identifier}\n提供者：{state.get('provider') or view.get('provider')}\n"
                    f"控制器：{'可用' if state.get('available') else '不可用'}"
                )
            fields[f"{panel}.summary"] = summary
            fields[f"{panel}.detail"] = detail
            fields[f"{panel}.toggle.available"] = "1" if state.get("can_set_enabled") else "0"
            fields[f"{panel}.toggle.value"] = "1" if enabled else "0"
        return fields

    def collect_layout(self, *, details: bool = True) -> dict[str, object]:
        result = self.model.get_layout()
        fields: dict[str, object] = {}
        if not result.ok:
            fields.update({
                "display.summary": "不可用",
                "display.detail": self._failure(result),
                "appearance.orientation": "auto",
            })
        else:
            data = result.data
            effective = data.get("effective", data)
            if not isinstance(effective, dict):
                effective = {}
            profile = str(effective.get("profile") or "unknown")
            orientation = str(
                effective.get("orientation_policy")
                or effective.get("orientation")
                or "auto"
            )
            fields.update({
                "display.summary": f"{profile} · {orientation}",
                "display.detail": f"布局：{profile}\n方向：{orientation}",
                "appearance.orientation": orientation,
            })
        if not details:
            return fields
        physical = (
            self.model.physical_rotation(refresh=False)
            if callable(getattr(self.model, "physical_rotation", None)) else None
        )
        if physical is not None and physical.ok:
            self._physical = dict(physical.data)
            fields["display.detail"] = (
                fields.get("display.detail", "")
                + f"\n物理面板：{physical.data.get('value', '不可用')}"
                + ("（可写）" if physical.data.get("writable") else "（只读）")
            )
            fields["display.physical.available"] = "1" if physical.data.get("writable") else "0"
        preferences = self.model.desktop_preferences()
        if not preferences.ok:
            fields.update({
                "appearance.summary": "Launcher 设置不可用",
                "appearance.detail": self._failure(preferences),
                "appearance.contract.available": "0",
            })
            return fields
        values = preferences.data.get("preferences", {})
        if not isinstance(values, dict):
            fields.update({
                "appearance.summary": "Launcher 返回无效状态",
                "appearance.detail": "preferences 不是对象",
                "appearance.contract.available": "0",
            })
            return fields
        fields["appearance.contract.available"] = "1"
        for key, value in values.items():
            fields[f"appearance.preference.{key}"] = (
                "1" if value is True else "0" if value is False else value
            )
        fields["appearance.summary"] = (
            f"{values.get('layout', 'profile')} · "
            f"{values.get('navigation_mode', 'pill')} · "
            f"{values.get('grid_columns', 0)}×{values.get('grid_rows', 0)}"
        )
        fields["appearance.detail"] = (
            f"图标：{values.get('icon_size', 64)} px · "
            f"间距：{values.get('icon_spacing', 8)} px\n"
            f"壁纸：{values.get('wallpaper_path') or values.get('wallpaper_color', '#F4F6FA')}\n"
            "由 Launcher 角色实时应用，不重启 X11/SPI。"
        )
        return fields

    def collect_wifi(self) -> dict[str, object]:
        fields = self.collect_hal()
        state = self._radio.get("wifi", {})
        try:
            networks = wifi_network_rows(state.get("values", {}))
        except (TypeError, ValueError):
            networks = []
        rows = []
        for row in networks:
            ssid = str(row.get("ssid") or "")
            network_id = row.get("network_id")
            signal = row.get("signal_dbm")
            security = str(row.get("security") or "")
            saved = " · 已保存" if row.get("configured") else ""
            identifier = f"{network_id if isinstance(network_id, int) and not isinstance(network_id, bool) else ''}\x1e{ssid}"
            rows.append((identifier, ssid, f"{signal if isinstance(signal, int) else '—'} dBm · {security}{saved}"))
        fields.update(self._item_fields("wifi", rows))
        return fields

    def collect_bluetooth(self) -> dict[str, object]:
        result = self.model.audio_devices(refresh=False)
        if not result.ok:
            return {
                "bluetooth.summary": "蓝牙音频不可用",
                "bluetooth.detail": self._failure(result),
                **self._item_fields("bluetooth", []),
            }
        devices = result.data.get("devices", [])
        rows = []
        details = []
        for row in devices if isinstance(devices, list) else []:
            if not isinstance(row, dict) or not row.get("address"):
                continue
            address = str(row["address"])
            label = str(row.get("name") or address)
            state = "已连接" if row.get("connected") else "已配对" if row.get("paired") else "未配对"
            rows.append((address, label, f"{state} · {address}"))
            details.append(f"{label} · {state}\n{address}")
        registered = result.data.get("controller_registered") is True
        return {
            "bluetooth.summary": f"{len(rows)} 个设备" if registered else "控制器不可用",
            "bluetooth.detail": "\n\n".join(details) or str(result.data.get("reason") or "尚未发现设备"),
            **self._item_fields("bluetooth", rows),
        }

    def collect_bluetooth_panel(self) -> dict[str, object]:
        fields = self.collect_hal()
        fields.update(self.collect_bluetooth())
        return fields

    def _emit_desktop_result(self, result: OperationResult) -> None:
        if not result.ok:
            self.emit({"toast": f"桌面设置失败：{self._failure(result)}"})
            self.emit(self.collect_layout())
            return
        preferences = result.data.get("preferences", {})
        fields: dict[str, object] = {"toast": "桌面设置已实时应用"}
        if isinstance(preferences, dict):
            for key, value in preferences.items():
                fields[f"appearance.preference.{key}"] = (
                    "1" if value is True else "0" if value is False else value
                )
        self.emit(fields)

    @staticmethod
    def _layout_values(payload: dict[str, Any]) -> tuple[str, str]:
        effective = payload.get("effective", payload)
        if not isinstance(effective, dict):
            effective = {}
        profile = str(effective.get("profile") or "mobile")
        if profile not in {"mobile", "desktop", "kiosk"}:
            profile = "mobile"
        insets = effective.get("insets_policy", "auto")
        if isinstance(insets, dict):
            try:
                insets = ",".join(
                    str(int(insets[edge]))
                    for edge in ("top", "right", "bottom", "left")
                )
            except (KeyError, TypeError, ValueError):
                insets = "auto"
        if not isinstance(insets, str):
            insets = "auto"
        return profile, insets

    def collect_audio(self) -> dict[str, object]:
        result = self.model.audio_state(refresh=False)
        if not result.ok:
            return {
                "audio.summary": "不可用",
                "audio.detail": self._failure(result),
            }
        self._audio = dict(result.data)
        data = result.data
        active_id = str(data.get("active_output") or "")
        active = next(
            (
                row for row in data.get("outputs", [])
                if isinstance(row, dict) and row.get("id") == active_id
            ),
            None,
        )
        output_name = str(active.get("name") if isinstance(active, dict) else "")
        volume = data.get("volume_percent")
        summary = output_name or ("音频已就绪" if data.get("available") else "无输出")
        if isinstance(volume, int):
            summary += f" · {volume}%"
        fields: dict[str, object] = {
            "audio.summary": summary,
            "audio.detail": (
                f"后端：{data.get('backend') or 'unknown'}\n"
                f"输出：{output_name or '未连接'}\n"
                f"音量：{volume if isinstance(volume, int) else '不可用'}"
            ),
            "audio.toggle.available": "1" if isinstance(data.get("muted"), bool) else "0",
            "audio.toggle.value": "1" if data.get("muted") is True else "0",
            "audio.volume": volume if isinstance(volume, int) else 50,
        }
        output_rows = []
        for row in data.get("outputs", []):
            if not isinstance(row, dict) or not row.get("id"):
                continue
            identifier = str(row["id"])
            name = str(row.get("name") or identifier)
            suffix = "当前输出" if identifier == active_id else str(row.get("backend") or "可用")
            output_rows.append((identifier, name, suffix))
        fields.update(self._item_fields("audio", output_rows))
        devices = self.model.audio_devices(refresh=False)
        if devices.ok:
            rows = devices.data.get("devices", [])
            details = []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                address = str(row.get("address") or "")
                name = str(row.get("name") or address)
                state = "已连接" if row.get("connected") else "已配对" if row.get("paired") else "未配对"
                details.append(f"{name} · {state}\n{address}")
            fields["bluetooth.detail"] = "\n\n".join(details) or str(
                devices.data.get("reason") or "尚未发现蓝牙音频设备"
            )
            fields["bluetooth.summary"] = (
                f"{len(details)} 个音频设备"
                if devices.data.get("controller_registered") else "控制器不可用"
            )
        return fields

    def collect_storage(self) -> dict[str, object]:
        result = self.model.storage_state()
        if not result.ok:
            return {
                "storage.summary": "不可用",
                "storage.detail": self._failure(result),
            }
        data = result.data
        volumes = data.get("volumes", [])
        mounted = [row for row in volumes if isinstance(row, dict) and row.get("mounted")]
        rows = [
            f"{row.get('name') or row.get('id')}：{row.get('mount_point') or '未挂载'}"
            for row in volumes[:10] if isinstance(row, dict)
        ]
        return {
            "storage.summary": f"{len(mounted)}/{len(volumes)} 已挂载",
            "storage.detail": "\n".join(rows) or "未发现 U 盘或 TF 卡",
            "storage.toggle.available": "1",
            "storage.toggle.value": "1" if data.get("auto_mount") else "0",
            **self._item_fields("storage", [
                (
                    str(row.get("id") or ""),
                    str(row.get("name") or row.get("id") or "未命名卷"),
                    str(row.get("mount_point") or "未挂载"),
                )
                for row in volumes[:32]
                if isinstance(row, dict) and row.get("id")
            ]),
        }

    def collect_apps(self) -> dict[str, object]:
        result = self.model.installed_packages()
        if not result.ok:
            return {
                "apps.summary": "软件管理不可用",
                "apps.detail": self._failure(result),
                "updates.summary": "更新服务不可用",
                "updates.detail": self._failure(result),
                "software.available": "0",
                "software.status": f"软件管理不可用：{self._failure(result)}",
                "software.package_count": "0",
            }
        packages = result.data.get("packages", [])
        names = [
            str(row.get("package") or row.get("id") or "")
            for row in packages[:12] if isinstance(row, dict)
        ]
        fields: dict[str, object] = {
            "apps.summary": f"{len(packages)} 个已安装包",
            "apps.detail": "\n".join(item for item in names if item) or "没有已安装包",
            "updates.summary": "签名更新与回退",
            "updates.detail": "通过现有 Install/Update Agent 检查、安装和回退。",
            "software.available": "1",
            "software.status": f"{len(packages)} 个已安装软件包",
            "software.package_count": str(len(packages)),
        }
        for index, row in enumerate(packages[:96]):
            if not isinstance(row, dict):
                continue
            prefix = f"software.package.{index}"
            fields[f"{prefix}.id"] = str(row.get("package") or row.get("id") or "")
            fields[f"{prefix}.version"] = str(row.get("version") or "")
            fields[f"{prefix}.path"] = str(row.get("path") or "")
        return fields

    @staticmethod
    def _operation_text(action: str, result: OperationResult) -> str:
        label = {
            "check": "检查更新",
            "apply": "应用更新",
            "rollback": "回退",
            "uninstall": "卸载",
        }.get(action, action)
        state = "成功" if result.ok else "失败"
        details = result.data if isinstance(result.data, dict) else {"response": result.data}
        encoded = json.dumps(details, ensure_ascii=False, sort_keys=True, indent=2)
        if len(encoded) > 2400:
            encoded = encoded[:2399] + "…"
        reason = ""
        if not result.ok:
            reason = f"\n错误：{result.code or 'UNKNOWN'} · {result.message or '无说明'}"
        return f"{label}：{state}{reason}\n{encoded}"

    def software_action(self, action: str, package: str) -> None:
        if not self._operation_lock.acquire(blocking=False):
            self.emit({"toast": "已有安装或更新操作正在进行"})
            return
        try:
            labels = {
                "software_check": "正在等待 Update Agent 检查终态…",
                "software_apply": "正在等待 Update Agent 安装和健康检查终态…",
                "software_rollback": f"正在回退 {package}…",
                "software_uninstall": f"正在卸载 {package}…",
            }
            success_labels = {
                "software_check": "更新检查完成",
                "software_apply": "更新应用完成",
                "software_rollback": "软件包回退完成",
                "software_uninstall": "软件包卸载完成",
            }
            self.emit({"software.busy": "1", "software.operation": labels[action]})
            if action == "software_check":
                result = self.model.request_update("check", self.update_source, package)
                operation = "check"
            elif action == "software_apply":
                result = self.model.request_update("apply", self.update_source, package)
                operation = "apply"
            elif action == "software_rollback":
                result = self.model.request_rollback(package)
                operation = "rollback"
            else:
                result = self.model.request_uninstall(package)
                operation = "uninstall"
            self.emit({
                "software.operation": self._operation_text(operation, result),
                "software.busy": "0",
                "toast": (
                    success_labels[action]
                    if result.ok
                    else f"操作失败：{self._failure(result)}"
                ),
            })
            if result.ok and operation in {"apply", "rollback", "uninstall"}:
                self.emit(self.collect_apps())
        except Exception as exc:
            self.emit({
                "software.busy": "0",
                "software.operation": f"操作异常：{exc}",
                "toast": f"操作异常：{exc}",
            })
        finally:
            self._operation_lock.release()

    def collect_system(self) -> dict[str, object]:
        calibration = self.model.touch_calibration_status()
        input_state = self.model.input_method_status()
        return {
            "system.detail": (
                f"触摸校准：{'可用' if calibration.ok and calibration.data.get('available') else '不可用'}\n"
                f"输入法：{'显示' if input_state.ok and input_state.data.get('visible') else '隐藏'}"
            ),
            "calibration.summary": (
                "触摸校准可用"
                if calibration.ok and calibration.data.get("available")
                else "未安装触摸校准"
            ),
            "calibration.available": (
                "1" if calibration.ok and calibration.data.get("available") else "0"
            ),
            "input.summary": (
                "触摸键盘已显示"
                if input_state.ok and input_state.data.get("visible") else
                "触摸键盘自动隐藏" if input_state.ok else "输入法不可用"
            ),
            "input.detail": (
                "输入焦点出现时自动显示，失去焦点时自动隐藏。\n"
                f"当前状态：{'显示' if input_state.data.get('visible') else '隐藏'}"
                if input_state.ok else self._failure(input_state)
            ),
            "input.toggle.available": "1" if input_state.ok else "0",
            "input.toggle.value": (
                "1" if input_state.ok and input_state.data.get("visible") else "0"
            ),
        }

    def collect_developer(self) -> dict[str, object]:
        status = self.model.ch347_status()
        debug = self.model.ch347_get_debug()
        if not status.ok and not debug.ok:
            reason = self._failure(status if not status.ok else debug)
            return {
                "developer.summary": "调试接口不可用",
                "developer.detail": reason,
                "developer.available": "0",
            }
        status_data = status.data if status.ok else {}
        status_state = status_data.get("state", status_data)
        if not isinstance(status_state, dict):
            status_state = {}
        debug_data = debug.data if debug.ok else {}
        configured = debug_data.get("configured", debug_data)
        if not isinstance(configured, dict):
            configured = {}
        fps = status_state.get("fps", status_state.get("configured_fps", 60))
        enabled = configured.get("enabled") is True
        cursor = configured.get("cursor_enabled") is True
        counters = status_state.get("dirty", status_state.get("counters", {}))
        return {
            "developer.summary": f"{fps} FPS · {'调试开启' if enabled else '调试关闭'}",
            "developer.detail": (
                f"捕捉上限：{fps} FPS\n调试叠加层：{'开' if enabled else '关'}\n"
                f"触摸光标：{'开' if cursor else '关'}\n脏区计数：{json.dumps(counters, ensure_ascii=False)[:480]}"
            ),
            "developer.available": "1",
            "developer.fps": fps,
            "developer.debug": "1" if enabled else "0",
            "developer.cursor": "1" if cursor else "0",
        }

    def collect_all(self) -> None:
        if not self._collect_lock.acquire(blocking=False):
            return
        try:
            self.emit({"status": "正在读取真实系统状态…"})
            operations: tuple[Callable[[], dict[str, object]], ...] = (
                self.collect_hal,
                self.collect_layout,
                self.collect_audio,
                self.collect_storage,
                self.collect_apps,
                self.collect_system,
                self.collect_developer,
            )
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix="settings-lvgl") as pool:
                futures = [pool.submit(operation) for operation in operations]
                for future in as_completed(futures):
                    try:
                        self.emit(future.result())
                    except Exception as exc:  # keep other independent sections alive
                        self.emit({"toast": f"状态读取失败：{exc}"})
            self.emit({"status": "已连接现有 SettingsModel"})
        finally:
            self._collect_lock.release()

    def collect_home(self) -> None:
        """Load only contracts that cannot wake optional application roles."""
        self.emit({
            **self.local_fields(),
            "wifi.summary": "点按查看网络",
            "bluetooth.summary": "点按查看设备",
            "audio.summary": "点按查看输出",
            "storage.summary": "点按查看卷",
            "apps.summary": "点按管理软件",
            "updates.summary": "点按检查更新",
            "input.summary": "按需读取输入法",
            "hal.summary": "点按查看提供者",
            "developer.summary": "点按查看显示诊断",
            "calibration.summary": "点按检查校准工具",
        })
        try:
            self.emit(self.collect_layout(details=False))
        except Exception as exc:
            self.emit({"display.summary": f"布局读取失败：{exc}"})
        self.emit({"status": "设置已就绪；二级页面按需读取"})

    def collect_panel(self, panel: str) -> None:
        collectors: dict[str, tuple[Callable[[], dict[str, object]], ...]] = {
            "wifi": (self.collect_wifi,),
            "bluetooth": (self.collect_bluetooth_panel,),
            "audio": (self.collect_audio,),
            "display": (self.collect_layout,),
            "appearance": (self.collect_layout,),
            "storage": (self.collect_storage,),
            "apps": (self.collect_apps,),
            "updates": (self.collect_apps,),
            "hal": (self.collect_hal,),
            "developer": (self.collect_developer,),
            "input": (self.collect_system,),
            "calibration": (self.collect_system,),
            "system": (self.collect_system,),
        }
        if panel == "regional":
            self.emit(self.local_fields())
            return
        selected = collectors.get(panel, ())
        if not selected:
            return
        if not self._collect_lock.acquire(blocking=False):
            return
        try:
            for collector in selected:
                self.emit(collector())
        except Exception as exc:
            self.emit({"toast": f"状态读取失败：{exc}"})
        finally:
            self._collect_lock.release()

    def action(self, name: str, value: str) -> None:
        result: OperationResult
        if name == "appearance_wallpaper":
            color, path = value[:7], value[7:]
            with self._desktop_lock:
                result = self.model.update_desktop_preferences({
                    "wallpaper_color": color,
                    "wallpaper_path": path,
                })
                self._emit_desktop_result(result)
            return
        if name == "settings_page":
            self._settings_page = value if value else "home"
            return
        desktop_fields = {
            "appearance_set_layout": "layout",
            "appearance_set_navigation_mode": "navigation_mode",
            "icon_size": "icon_size",
            "icon_spacing": "icon_spacing",
            "grid_columns": "grid_columns",
            "grid_rows": "grid_rows",
            "show_labels": "show_labels",
            "folders_enabled": "folders_enabled",
            "large_folders_enabled": "large_folders_enabled",
            "acrylic": "acrylic",
            "animations_enabled": "animations_enabled",
            "reduce_motion": "reduce_motion",
        }
        if name in desktop_fields:
            field = desktop_fields[name]
            typed: object = value
            if field in {
                "show_labels", "folders_enabled", "large_folders_enabled",
                "acrylic", "animations_enabled", "reduce_motion",
            }:
                typed = value in {"1", "true"}
            with self._desktop_lock:
                result = self.model.update_desktop_preferences({field: typed})
                self._emit_desktop_result(result)
            return
        if name == "appearance_orientation":
            with self._desktop_lock:
                current = self.model.get_layout()
                if not current.ok:
                    self.emit({"toast": f"方向设置失败：{self._failure(current)}"})
                    return
                profile, insets = self._layout_values(current.data)
                result = self.model.set_layout(profile, value, insets)
                if result.ok:
                    self.emit({
                        "appearance.orientation": value,
                        "toast": "屏幕方向已实时应用",
                    })
                else:
                    self.emit({"toast": f"方向设置失败：{self._failure(result)}"})
                    self.emit(self.collect_layout())
            return
        if name == "physical_rotation":
            device = str(self._physical.get("device") or "")
            if not self._physical.get("writable") or not device:
                self.emit({"toast": "当前显示提供者不支持物理旋转"})
                return
            result = self.model.set_physical_rotation(device, value)
            self.emit({"toast": "面板与触摸矩阵已同步旋转" if result.ok else f"物理旋转失败：{self._failure(result)}"})
            self.emit(self.collect_layout())
            return
        if name == "software_page":
            if value in {"apps", "updates", "detail"}:
                self._software_page = value
            return
        if name in {
            "software_check",
            "software_apply",
            "software_rollback",
            "software_uninstall",
        }:
            self.software_action(name, value.strip() or "all")
            return
        if name in {"wifi_toggle", "bluetooth_toggle"}:
            panel = name.removesuffix("_toggle")
            state = self._radio.get(panel, {})
            field = str(state.get("power_field") or "")
            device = str(state.get("device") or "")
            if not field or not device:
                self.emit({"toast": "此开关当前不可写"})
                return
            result = self.model.hal_set_state(device, {field: value == "1"})
            self.emit(
                {"toast": "设置已应用" if result.ok else f"设置失败：{self._failure(result)}"}
            )
            self.emit(self.collect_wifi() if panel == "wifi" else self.collect_bluetooth_panel())
            return
        if name == "storage_toggle":
            result = self.model.storage_set_auto_mount(value == "1")
            self.emit(
                {"toast": "自动挂载已更新" if result.ok else f"设置失败：{self._failure(result)}"}
            )
            self.emit(self.collect_storage())
            return
        if name == "storage_refresh":
            result = self.model.storage_refresh()
            self.emit({"toast": "存储设备已刷新" if result.ok else f"刷新失败：{self._failure(result)}"})
            self.emit(self.collect_storage())
            return
        if name in {"storage_mount", "storage_unmount"}:
            volume_id = value.split("\x1f", 1)[0].strip()
            result = (
                self.model.storage_mount(volume_id)
                if name == "storage_mount" else self.model.storage_unmount(volume_id)
            )
            self.emit({"toast": "存储操作完成" if result.ok else f"存储操作失败：{self._failure(result)}"})
            self.emit(self.collect_storage())
            return
        if name == "audio_toggle":
            result = self.model.audio_set_muted(value == "1")
            self.emit(
                {"toast": "静音状态已更新" if result.ok else f"设置失败：{self._failure(result)}"}
            )
            self.emit(self.collect_audio())
            return
        if name == "audio_volume":
            result = self.model.audio_set_volume(value)
            self.emit({"toast": "音量已更新" if result.ok else f"音量设置失败：{self._failure(result)}"})
            self.emit(self.collect_audio())
            return
        if name == "audio_output":
            output = value.split("\x1f", 1)[0].strip()
            result = self.model.audio_select_output(output)
            self.emit({"toast": "音频输出已切换" if result.ok else f"切换失败：{self._failure(result)}"})
            self.emit(self.collect_audio())
            return
        if name == "input_toggle":
            result = self.model.toggle_input_method()
            self.emit({"toast": "输入法状态已更新" if result.ok else f"输入法不可用：{self._failure(result)}"})
            self.emit(self.collect_system())
            return
        if name in {"wifi_scan", "wifi_disconnect", "wifi_connect", "wifi_forget"}:
            state = self._radio.get("wifi", {})
            device = str(state.get("device") or "")
            if not device:
                self.emit({"toast": "Wi-Fi 设备不可用"})
                return
            if name == "wifi_scan":
                changes: dict[str, Any] = {"action": "scan"}
            elif name == "wifi_disconnect":
                changes = {"action": "disconnect"}
            else:
                selection, _, password = value.partition("\x1f")
                network_text, _, ssid = selection.partition("\x1e")
                rows = wifi_network_rows(state.get("values", {}))
                network_id = int(network_text) if network_text.isdigit() else None
                row = next(
                    (
                        item for item in rows
                        if item.get("ssid") == ssid.strip()
                        and (network_id is None or item.get("network_id") == network_id)
                    ),
                    None,
                )
                if row is None:
                    self.emit({"toast": "请先扫描并输入列表中的网络名称"})
                    return
                try:
                    changes = (
                        wifi_forget_changes(row)
                        if name == "wifi_forget" else wifi_connect_changes(row, password)
                    )
                except ValueError as exc:
                    message = "密码需要 8–63 个 ASCII 字符" if str(exc) in {"password-required", "password-invalid"} else str(exc)
                    self.emit({"toast": message})
                    return
            result = self.model.hal_set_state(device, changes)
            self.emit({"toast": "Wi-Fi 操作完成" if result.ok else f"Wi-Fi 操作失败：{self._failure(result)}"})
            self.emit(self.collect_wifi())
            return
        if name == "bluetooth_scan" or name.startswith("bluetooth_") and name.removeprefix("bluetooth_") in {"pair", "connect", "disconnect", "forget"}:
            action = name.removeprefix("bluetooth_")
            result = (
                self.model.audio_scan_devices(15000)
                if action == "scan" else self.model.audio_device_action(action, value.strip())
            )
            self.emit({"toast": "蓝牙操作完成" if result.ok else f"蓝牙操作失败：{self._failure(result)}"})
            self.emit(self.collect_bluetooth_panel())
            return
        if name == "regional_language":
            try:
                regional = self.regional.set_language(value)
                self.model.client.set_session_language(value)
            except (OSError, ValueError, RuntimeError) as exc:
                self.emit({"toast": f"语言设置失败：{exc}"})
                return
            self.emit({
                "regional.language": regional["language"],
                "regional.summary": f"{regional['language']} · {regional['timezone']}",
                "toast": "语言已应用，新应用将继承该语言",
            })
            return
        if name == "regional_timezone":
            timezone = value.split("\x1f", 1)[0].strip()
            try:
                regional = self.regional.set_timezone(timezone)
                self.model.client.notify_timezone_changed(timezone)
            except (OSError, ValueError, RuntimeError) as exc:
                self.emit({"toast": f"时区设置失败：{exc}"})
                return
            self.emit({
                "regional.timezone": regional["timezone"],
                "regional.summary": f"{regional['language']} · {regional['timezone']}",
                "toast": "时区已原子更新",
            })
            return
        if name in {"hal_select", "hal_reset"}:
            domain, _, provider = value.partition("\x1f")
            domain = domain.strip()
            row = next(
                (item for item in self._hal.get("domains", []) if isinstance(item, dict) and item.get("domain") == domain),
                None,
            )
            if not isinstance(row, dict):
                self.emit({"toast": "请先刷新并输入真实 HAL 域"})
                return
            candidates = row.get("candidates", [])
            if name == "hal_select":
                selectable = [item for item in candidates if isinstance(item, dict) and item.get("selectable") is not False]
                if len(selectable) <= 1:
                    self.emit({"toast": "该域只有一个提供者，无需切换"})
                    return
                if provider.strip() not in {str(item.get("component")) for item in selectable}:
                    self.emit({"toast": "提供者不存在或当前不可用"})
                    return
                result = self.model.select_hal_provider(domain, provider.strip())
            else:
                result = self.model.reset_hal_provider(domain)
            self.emit({"toast": "HAL 提供者已更新" if result.ok else f"HAL 操作失败：{self._failure(result)}"})
            self.emit(self.collect_hal())
            return
        if name == "developer_fps":
            current = self.model.ch347_status()
            current_state = current.data.get("state", current.data) if current.ok else {}
            idle = current_state.get("idle_fps", 0) if isinstance(current_state, dict) else 0
            result = self.model.ch347_set_fps(value, idle)
            self.emit({"toast": "捕捉上限已更新" if result.ok else f"FPS 设置失败：{self._failure(result)}"})
            self.emit(self.collect_developer())
            return
        if name in {"developer_debug_toggle", "developer_cursor_toggle"}:
            current = self.model.ch347_get_debug()
            configured = current.data.get("configured", current.data) if current.ok else {}
            if not isinstance(configured, dict):
                configured = {}
            request = (
                {"enabled": configured.get("enabled") is not True}
                if name == "developer_debug_toggle" else
                {"cursor_enabled": configured.get("cursor_enabled") is not True}
            )
            result = self.model.ch347_set_debug(request)
            self.emit({"toast": "调试显示已更新" if result.ok else f"调试设置失败：{self._failure(result)}"})
            self.emit(self.collect_developer())
            return
        if name in {"open_software", "open_updates"}:
            try:
                response = self.model.client.start_component("org.msys.settings:software-center")
                ok = isinstance(response, dict)
            except Exception as exc:
                ok = False
                response = {"error": str(exc)}
            if ok and name == "open_updates":
                try:
                    self.model.client.rpc.call(
                        "msys.core",
                        "broadcast",
                        {
                            "topic": "msys.activation",
                            "payload": {
                                "action": "software-center",
                                "name": "updates",
                                "component": "org.msys.settings:software-center",
                            },
                        },
                        timeout=5.0,
                    )
                except Exception:
                    pass
            self.emit({"toast": "软件中心已启动" if ok else f"启动失败：{response.get('error', 'unknown')}"})
            return
        if name == "calibration_start":
            result = self.model.start_touch_calibration()
            self.emit(
                {"toast": "已启动触摸校准" if result.ok else f"启动失败：{self._failure(result)}"}
            )
            return
        self.emit({"toast": "第一阶段暂不支持此操作"})


def main() -> int:
    channel = ComponentChannel.from_env()
    rpc = channel if channel is not None else PublicMipcClient()
    bridge = Bridge(SettingsModel(SettingsClient(rpc)))
    bridge.emit(bridge.local_fields())
    if channel is not None:
        channel.handshake()
        def event_received(event: dict[str, Any]) -> None:
            topic = str(event.get("topic") or "")
            payload = event.get("payload", {})
            if (
                topic == "msys.activation"
                and bridge.mode != "software-center"
                and isinstance(payload, dict)
            ):
                target = str(payload.get("component") or payload.get("target") or "")
                if target and target not in {
                    "org.msys.settings:main",
                    os.environ.get("MSYS_COMPONENT_ID", ""),
                }:
                    return
                requested = str(payload.get("name") or payload.get("panel") or "home")
                panel = {"layout": "appearance", "roles": "hal"}.get(requested, requested)
                bridge._settings_page = panel
                bridge.emit({"settings.page": panel})
                return
            if (
                topic == "msys.activation"
                and bridge.mode == "software-center"
                and isinstance(payload, dict)
            ):
                panel = str(payload.get("name") or payload.get("panel") or "apps")
                component = str(
                    payload.get("component")
                    or payload.get("selected_component")
                    or ""
                )
                package = component.split(":", 1)[0].strip()
                fields: dict[str, object] = {
                    "software.page": (
                        "updates"
                        if panel == "updates"
                        else "detail"
                        if package and panel in {"details", "uninstall"}
                        else "apps"
                    )
                }
                bridge._software_page = str(fields["software.page"])
                if package:
                    fields["software.select"] = package
                if panel == "uninstall":
                    fields["software.intent"] = "uninstall"
                bridge.emit(fields)
                return
            if topic in {
                "msys.update.checked",
                "msys.update.applied",
                "msys.update.error",
                "msys.install.package_changed",
                "msys.install.error",
            }:
                if bridge.mode == "software-center" or bridge._settings_page in {"apps", "updates"}:
                    threading.Thread(
                        target=lambda: bridge.emit(bridge.collect_apps()),
                        name="settings-lvgl-package-event",
                        daemon=True,
                    ).start()
                return
            if bridge.mode != "software-center" and topic in {
                "msys.shell.preferences.changed",
                "msys.layout.changed",
            }:
                threading.Thread(
                    target=lambda: bridge.emit(bridge.collect_layout(
                        details=bridge._settings_page in {"display", "appearance"}
                    )),
                    name="settings-lvgl-desktop-event",
                    daemon=True,
                ).start()
                return
            active_refresh = {
                "msys.audio.changed": {"audio", "bluetooth"},
                "msys.hal.changed": {"wifi", "hal", "display"},
                "msys.hal.storage.changed": {"storage"},
            }
            if (
                bridge.mode != "software-center"
                and topic in active_refresh
                and bridge._settings_page in active_refresh[topic]
            ):
                threading.Thread(
                    target=lambda page=bridge._settings_page: bridge.collect_panel(page),
                    name="settings-lvgl-visible-event",
                    daemon=True,
                ).start()

        def call_received(message: dict[str, Any]) -> dict[str, Any]:
            method = str(message.get("method") or "")
            payload = message.get("payload", {})
            if method == "get_regional_settings" and bridge.mode != "software-center":
                return {"ok": True, **bridge.regional.status()}
            if method in {"set_language", "set_timezone"} and bridge.mode != "software-center":
                if not isinstance(payload, dict):
                    return {"ok": False, "schema": "msys.settings.regional.v1", "code": "BAD_REQUEST", "message": "payload must be an object"}
                try:
                    if method == "set_language":
                        selected = payload.get("language")
                        if not isinstance(selected, str):
                            raise ValueError("language must be a string")
                        state = bridge.regional.set_language(selected)
                        bridge.model.client.set_session_language(selected)
                    else:
                        selected = payload.get("timezone")
                        if not isinstance(selected, str):
                            raise ValueError("timezone must be a string")
                        state = bridge.regional.set_timezone(selected)
                        bridge.model.client.notify_timezone_changed(selected)
                    bridge.emit(bridge.local_fields())
                    return {"ok": True, **state}
                except (OSError, ValueError) as exc:
                    return {"ok": False, "schema": "msys.settings.regional.v1", "code": "BAD_REQUEST" if isinstance(exc, ValueError) else "REGIONAL_UNAVAILABLE", "message": str(exc)}
            if method != "navigation_back":
                return {"handled": False, "reason": "method-not-supported"}
            if bridge.mode == "software-center":
                if bridge._software_page == "apps":
                    return {"handled": False, "page": "apps"}
                bridge._software_page = "apps"
                bridge.emit({"software.page": "apps"})
                return {"handled": True, "page": "apps"}
            if bridge._settings_page == "home":
                return {"handled": False, "page": "home"}
            bridge._settings_page = "home"
            bridge.emit({"settings.page": "home"})
            return {"handled": True, "page": "home"}

        channel.start(event_received, call_handler=call_received)
    initial_collect = (
        (lambda: bridge.emit(bridge.collect_apps()))
        if bridge.mode == "software-center"
        else bridge.collect_home
    )
    worker = threading.Thread(target=initial_collect, name="settings-lvgl-load", daemon=True)
    worker.start()
    try:
        for raw in sys.stdin:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            parts = line.split("\t", 2)
            command = parts[0]
            if command == "QUIT":
                break
            if command == "REFRESH":
                panel = unquote(parts[1]) if len(parts) >= 2 else ""
                threading.Thread(
                    target=(
                        (lambda: bridge.emit(bridge.collect_apps()))
                        if bridge.mode == "software-center"
                        else (lambda selected=panel: bridge.collect_panel(selected))
                    ),
                    name="settings-lvgl-refresh",
                    daemon=True,
                ).start()
            elif command == "ACTION" and len(parts) >= 2:
                name = unquote(parts[1])
                value = unquote(parts[2]) if len(parts) > 2 else ""
                threading.Thread(
                    target=bridge.action,
                    args=(name, value),
                    name="settings-lvgl-action",
                    daemon=True,
                ).start()
    finally:
        if channel is not None:
            channel.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
