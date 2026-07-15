"""Manual target probe for the withdrawn 320x480 Chinese Display page.

This is intentionally not named ``test_*``: CI has no Tk/X11 dependency.  The
probe is copied to a target temporary directory and must never install or
start an MSYS component.
"""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from msys_settings.localization import SettingsI18n
from msys_settings.ui import LayoutPage


class ProbeApplication:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.compact = True
        self._i18n = SettingsI18n(locale="zh-CN")

    def tr(self, key: str, params=None, *, fallback=None) -> str:
        return self._i18n.text(key, params, fallback=fallback)


def geometry(widget: tk.Misc) -> dict[str, int]:
    return {
        "requested": int(widget.winfo_reqwidth()),
        "actual": int(widget.winfo_width()),
        "x": int(widget.winfo_x()),
    }


def main() -> int:
    root = tk.Tk(className="msys_settings_geometry_probe")
    root.withdraw()
    root.geometry("320x480+0+0")
    host = ttk.Frame(root, width=320, height=480)
    host.place(x=0, y=0, width=320, height=480)
    page = LayoutPage(host, ProbeApplication(root))
    page.place(x=0, y=0, width=320, height=480)
    root.update_idletasks()

    first_row = page.debug_refresh_button.master
    mode_row = page.debug_apply_button.master
    result = {
        "root_mapped": bool(root.winfo_ismapped()),
        "screen": [int(root.winfo_screenwidth()), int(root.winfo_screenheight())],
        "page": geometry(page),
        "first_row": geometry(first_row),
        "check_fps": geometry(page.debug_refresh_button),
        "apply_fps": geometry(page.debug_apply_fps_button),
        "mode_row": geometry(mode_row),
        "apply_debug": geometry(page.debug_apply_button),
        "apply_overlay": geometry(page.debug_overlay_apply_button),
        "overlay_row": geometry(page.debug_overlay_apply_button.master),
    }
    first_required = (
        result["check_fps"]["requested"]
        + result["apply_fps"]["requested"]
        + 6
    )
    result["first_row_required"] = first_required
    result["first_row_fits"] = first_required <= result["first_row"]["actual"]
    result["apply_debug_fits"] = (
        result["apply_debug"]["requested"] <= result["mode_row"]["actual"]
    )
    result["apply_overlay_fits"] = (
        result["apply_overlay"]["requested"] <= result["overlay_row"]["actual"]
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    root.destroy()
    return 0 if (
        not result["root_mapped"]
        and result["first_row_fits"]
        and result["apply_debug_fits"]
        and result["apply_overlay_fits"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
