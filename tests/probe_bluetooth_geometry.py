"""Manual 320x480 Tk probe for role-backed Bluetooth lifecycle controls."""

from __future__ import annotations

import json

from msys_settings.model import OperationResult
from msys_settings.ui import BluetoothPage, SettingsApplication


class NoopModel:
    """Initial refresh is deferred, so the probe never touches mIPC."""


def main() -> int:
    app = SettingsApplication(NoopModel(), defer_initial_refresh=True)  # type: ignore[arg-type]
    app.show_page("bluetooth")
    app.root.update_idletasks()
    page = app._pages["bluetooth"]
    if not isinstance(page, BluetoothPage):
        app.close()
        return 2
    page._bluetooth_powered = True
    page._bluetooth_audio_result(OperationResult(True, {
        "schema": "msys.audio-devices.v1",
        "controller_registered": True,
        "reason": "no-connected-a2dp-output",
        "backend": "bluealsa",
        "devices": [{
            "address": "AA:BB:CC:DD:EE:FF",
            "name": "MSYS Test Headset",
            "alias": "Test Headset",
            "icon": "audio-card",
            "paired": True,
            "trusted": True,
            "connected": False,
        }],
    }))
    row = page.bluetooth_tree.get_children()[0]
    page.bluetooth_tree.selection_set(row)
    page.bluetooth_tree.focus(row)
    page._update_bluetooth_actions()
    app.root.update_idletasks()
    bounds = page.radio_surface.canvas.bbox("all") or (0, 0, 0, 0)
    canvas_width = max(1, int(page.radio_surface.canvas.winfo_width()))
    content_width = max(0, int(bounds[2] - bounds[0]))
    content_height = max(0, int(bounds[3] - bounds[1]))
    result = {
        "compact": app.compact,
        "window": [app.root.winfo_width(), app.root.winfo_height()],
        "content": [content_width, content_height],
        "canvas": [canvas_width, page.radio_surface.canvas.winfo_height()],
        "rows": len(page.bluetooth_tree.get_children()),
        "scan": str(page.bluetooth_scan_button.cget("state")),
        "pair": str(page.bluetooth_pair_button.cget("state")),
        "connect": str(page.bluetooth_connect_button.cget("state")),
        "disconnect": str(page.bluetooth_disconnect_button.cget("state")),
        "forget": str(page.bluetooth_forget_button.cget("state")),
        "scroll_required": content_height > page.radio_surface.canvas.winfo_height(),
    }
    ok = (
        result["compact"] is True
        and content_width <= canvas_width
        and result["rows"] == 1
        and result["scan"] == "normal"
        and result["pair"] == "disabled"
        and result["connect"] == "normal"
        and result["disconnect"] == "disabled"
        and result["forget"] == "normal"
        and result["scroll_required"] is True
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    app.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
