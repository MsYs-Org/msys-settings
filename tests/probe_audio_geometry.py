"""Manual 320x480 Tk geometry probe for the scrollable Audio page."""

from __future__ import annotations

import json

from msys_settings.audio import normalise_audio_state
from msys_settings.model import OperationResult
from msys_settings.ui import AudioPage, SettingsApplication


class NoopModel:
    """The probe defers all page refreshes, so no RPC method may be called."""


def main() -> int:
    app = SettingsApplication(NoopModel(), defer_initial_refresh=True)  # type: ignore[arg-type]
    app.show_page("audio")
    app.root.update()
    app.root.update_idletasks()
    page = app._pages["audio"]
    if not isinstance(page, AudioPage):
        app.close()
        return 2
    output_id = "bluealsa:AA:BB:CC:DD:EE:FF:a2dp"
    page._state_result(OperationResult(True, normalise_audio_state({
        "schema": "msys.audio-state.v1",
        "backend": "bluealsa",
        "available": True,
        "reason": None,
        "controller_registered": True,
        "stack": [
            {"name": "bluetoothd", "pid": 10, "running": True, "returncode": None},
            {"name": "bluealsa", "pid": 11, "running": True, "returncode": None},
        ],
        "outputs": [{
            "id": output_id,
            "address": "AA:BB:CC:DD:EE:FF",
            "name": "MSYS Test Headset",
            "profile": "a2dp",
            "connected": True,
            "mixer_control": "Test Headset - A2DP",
            "volume_percent": 60,
            "muted": False,
        }],
        "active_output": {"id": output_id},
        "volume_percent": 60,
        "muted": False,
        "player": {
            "enabled": False,
            "server": "",
            "name": "MSYS Audio",
            "running": False,
        },
    })))
    app.root.update_idletasks()
    volume_enabled = str(page.volume_up.cget("state")) == "normal"
    player_enabled = str(page.player_apply.cget("state")) == "normal"
    unknown_state = dict(page.state)
    unknown_state["volume_percent"] = None
    unknown_state["muted"] = None
    unknown_state["outputs"] = [{
        **page.state["outputs"][0],
        "volume_percent": None,
        "muted": None,
    }]
    page._state_result(OperationResult(True, unknown_state))
    unavailable = app.tr("common.unavailable")
    unknown_volume_truthful = page.volume_text.get() == f"{unavailable} · {unavailable}"
    app.root.update_idletasks()
    bounds = page.surface.canvas.bbox("all") or (0, 0, 0, 0)
    canvas_width = max(1, int(page.surface.canvas.winfo_width()))
    content_width = max(0, int(bounds[2] - bounds[0]))
    content_height = max(0, int(bounds[3] - bounds[1]))
    result = {
        "compact": app.compact,
        "window": [app.root.winfo_width(), app.root.winfo_height()],
        "canvas": [canvas_width, page.surface.canvas.winfo_height()],
        "content": [content_width, content_height],
        "status_wrap": int(page.status_card.body_label.cget("wraplength")),
        "output_width": page.output_tree.winfo_width(),
        "scroll_required": content_height > page.surface.canvas.winfo_height(),
        "output_rows": len(page.output_tree.get_children()),
        "volume_enabled": volume_enabled,
        "player_enabled": player_enabled,
        "unknown_volume_truthful": unknown_volume_truthful,
    }
    ok = (
        result["compact"] is True
        and content_width <= canvas_width
        and result["output_width"] <= canvas_width
        and 120 <= result["status_wrap"] <= canvas_width
        and result["scroll_required"] is True
        and result["output_rows"] == 1
        and result["volume_enabled"] is True
        and result["player_enabled"] is True
        and result["unknown_volume_truthful"] is True
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    app.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
