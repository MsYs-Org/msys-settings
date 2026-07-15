"""Manual Xvfb probe for in-process language switching and UI rebuilding."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from msys_settings.regional import RegionalSettingsStore
from msys_settings.ui import SettingsApplication


class ProbeClient:
    def set_session_language(self, language: str) -> dict[str, object]:
        return {"language": language, "resolved_language": language, "changed": True}


class ProbeModel:
    """Constructors only retain this object; deferred refresh performs no RPC."""

    client = ProbeClient()


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        zoneinfo = root / "zoneinfo"
        zoneinfo.mkdir()
        (zoneinfo / "UTC").write_bytes(b"utc")
        etc = root / "etc"
        etc.mkdir()
        store = RegionalSettingsStore(
            root / "state" / "regional.json",
            zoneinfo_dir=zoneinfo,
            localtime_path=etc / "localtime",
            environ={},
        )
        app = SettingsApplication(
            ProbeModel(),  # type: ignore[arg-type]
            defer_initial_refresh=True,
            regional_store=store,
        )
        app.root.withdraw()
        zh = app._apply_regional_call("set_language", {"language": "zh-CN"})
        app.root.update_idletasks()
        zh_result = {
            "ok": zh.get("ok"),
            "locale": app.i18n.locale,
            "page": app._active_page,
            "title": app.page_title.get(),
            "window": app.root.title(),
            "back": app.navigate_back(),
        }
        en = app._apply_regional_call("set_language", {"language": "en-US"})
        app.root.update_idletasks()
        en_result = {
            "ok": en.get("ok"),
            "locale": app.i18n.locale,
            "page": app._active_page,
            "title": app.page_title.get(),
            "window": app.root.title(),
        }
        app.close()
    result = {"zh-CN": zh_result, "en-US": en_result}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if (
        zh_result == {
            "ok": True,
            "locale": "zh-CN",
            "page": "regional",
            "title": "语言和区域",
            "window": "设置",
            "back": True,
        }
        and en_result == {
            "ok": True,
            "locale": "en-US",
            "page": "regional",
            "title": "Language & region",
            "window": "Settings",
        }
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
