"""Manual Xvfb probe for regional-page portrait, landscape and long text."""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from msys_sdk.ui_fonts import configure_tk_fonts
from msys_settings.localization import SettingsI18n
from msys_settings.ui import RegionalPage


class ProbeStore:
    def __init__(self, language: str) -> None:
        self.language = language

    def status(self) -> dict[str, object]:
        return {
            "schema": "msys.settings.regional.v1",
            "language": self.language,
            "timezone": "Asia/Shanghai",
            "timezone_writable": False,
            "timezone_reason": "a deliberately long unavailable capability reason",
            "timezone_reason_code": "zoneinfo-unavailable",
            "timezones": ["UTC", "Asia/Shanghai"],
        }


class ProbeApplication:
    def __init__(self, root: tk.Tk, locale: str) -> None:
        self.root = root
        self.compact = True
        self.regional_store = ProbeStore(locale)
        self._i18n = SettingsI18n(locale=locale)

    def tr(self, key: str, params=None, *, fallback=None) -> str:
        translated = self._i18n.text(key, params, fallback=fallback)
        if key in {"regional.note", "regional.language_hint", "regional.timezone_hint"}:
            return " ".join([translated] * 8)
        return translated

    def _apply_regional_call(self, _method: str, _payload: dict) -> dict[str, object]:
        return {"ok": False, "message": "probe is read-only"}

    def set_status(self, _message: str, *, error: bool = False) -> None:
        del error


def one_case(root: tk.Tk, width: int, height: int, locale: str) -> dict[str, object]:
    host = ttk.Frame(root)
    host.place(x=0, y=0, width=width, height=height)
    app = ProbeApplication(root, locale)
    page = RegionalPage(host, app)  # type: ignore[arg-type]
    page.place(x=0, y=0, width=width, height=height)
    page.on_show()
    root.update_idletasks()
    bounds = page.surface.canvas.bbox("all")
    viewport = page.surface.canvas.winfo_height()
    page.surface.scroll_pixels(100000)
    root.update_idletasks()
    result = {
        "size": [width, height],
        "locale": locale,
        "content_height": 0 if bounds is None else bounds[3] - bounds[1],
        "viewport_height": viewport,
        "overflow": bounds is not None and bounds[3] - bounds[1] > viewport,
        "scroll_bottom": page.surface.canvas.yview()[1],
        "language_action_width": page.language_apply.winfo_width(),
        "language_card_width": page.language_apply.master.winfo_width(),
        "timezone_action_width": page.timezone_apply.winfo_width(),
        "timezone_card_width": page.timezone_apply.master.winfo_width(),
        "page_width": page.winfo_width(),
    }
    page.destroy()
    host.destroy()
    return result


def main() -> int:
    root = tk.Tk(className="msys_settings_regional_probe")
    root.withdraw()
    root.geometry("480x480+0+0")
    configure_tk_fonts(root, default_size=9)
    results = [
        one_case(root, 320, 480, "zh-CN"),
        one_case(root, 480, 320, "en-US"),
    ]
    print(json.dumps(results, ensure_ascii=False, sort_keys=True))
    root.destroy()
    ok = all(
        item["overflow"]
        and float(item["scroll_bottom"]) > 0.99
        and int(item["language_action_width"]) >= int(item["language_card_width"]) - 32
        and int(item["timezone_action_width"]) >= int(item["timezone_card_width"]) - 32
        for item in results
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
