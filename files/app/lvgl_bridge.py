#!/usr/bin/env python3
"""UI-neutral bridge between the existing Settings model and native LVGL.

The protocol is intentionally tiny: UTF-8 ``key<TAB>percent-encoded value``
rows are grouped by BEGIN/END.  No UI state or HAL contract is duplicated in
the native renderer; all reads and mutations still pass through SettingsModel.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import sys
import threading
from typing import Any, Callable
from urllib.parse import quote, unquote

from msys_settings.client import SettingsClient
from msys_settings.ipc import ComponentChannel, PublicMipcClient
from msys_settings.model import OperationResult, SettingsModel
from msys_settings.radio import radio_domain_view, radio_state_summary
from msys_settings.regional import RegionalSettingsStore


class Bridge:
    def __init__(self, model: SettingsModel) -> None:
        self.model = model
        self.regional = RegionalSettingsStore()
        self._write_lock = threading.Lock()
        self._collect_lock = threading.Lock()
        self._sequence = 0
        self._radio: dict[str, dict[str, Any]] = {}
        self._audio: dict[str, Any] = {}

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
        display_devices = [
            row for row in inventory.get("devices", [])
            if isinstance(row, dict)
            and row.get("domain") in {"display", "display-output"}
        ]
        fields["display.hal"] = f"{len(display_devices)} 个显示设备"
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

    def collect_layout(self) -> dict[str, object]:
        result = self.model.get_layout()
        if not result.ok:
            return {
                "display.summary": "不可用",
                "display.detail": self._failure(result),
            }
        data = result.data
        profile = str(data.get("profile") or "unknown")
        orientation = str(data.get("orientation") or "unknown")
        return {
            "display.summary": f"{profile} · {orientation}",
            "display.detail": f"布局：{profile}\n方向：{orientation}",
        }

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
        return {
            "audio.summary": summary,
            "audio.detail": (
                f"后端：{data.get('backend') or 'unknown'}\n"
                f"输出：{output_name or '未连接'}\n"
                f"音量：{volume if isinstance(volume, int) else '不可用'}"
            ),
            "audio.toggle.available": "1" if isinstance(data.get("muted"), bool) else "0",
            "audio.toggle.value": "1" if data.get("muted") is True else "0",
        }

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
        }

    def collect_apps(self) -> dict[str, object]:
        result = self.model.installed_packages()
        if not result.ok:
            return {
                "apps.summary": "软件管理不可用",
                "apps.detail": self._failure(result),
                "updates.summary": "更新服务不可用",
                "updates.detail": self._failure(result),
            }
        packages = result.data.get("packages", [])
        names = [
            str(row.get("id") or row.get("package") or "")
            for row in packages[:12] if isinstance(row, dict)
        ]
        return {
            "apps.summary": f"{len(packages)} 个已安装包",
            "apps.detail": "\n".join(item for item in names if item) or "没有已安装包",
            "updates.summary": "签名更新与回退",
            "updates.detail": "通过现有 Install/Update Agent 检查、安装和回退。",
        }

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

    def action(self, name: str, value: str) -> None:
        result: OperationResult
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
            self.emit(self.collect_hal())
            return
        if name == "storage_toggle":
            result = self.model.storage_set_auto_mount(value == "1")
            self.emit(
                {"toast": "自动挂载已更新" if result.ok else f"设置失败：{self._failure(result)}"}
            )
            self.emit(self.collect_storage())
            return
        if name == "audio_toggle":
            result = self.model.audio_set_muted(value == "1")
            self.emit(
                {"toast": "静音状态已更新" if result.ok else f"设置失败：{self._failure(result)}"}
            )
            self.emit(self.collect_audio())
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
        channel.start(lambda _event: None)
    worker = threading.Thread(target=bridge.collect_all, name="settings-lvgl-load", daemon=True)
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
                threading.Thread(
                    target=bridge.collect_all,
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
