"""Small persistent language and POSIX timezone file contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time
from typing import Any, Mapping


REGIONAL_SCHEMA = "msys.settings.regional.v1"
LANGUAGES = ("system", "zh-CN", "en-US")
COMMON_TIMEZONES = (
    "UTC",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "Europe/London",
    "Europe/Berlin",
    "America/New_York",
    "America/Los_Angeles",
)
_TIMEZONE = re.compile(r"[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*")
_TIMEZONE_REASON_CODES = {
    "zoneinfo database unavailable": "zoneinfo-unavailable",
    "localtime directory unavailable": "localtime-directory-unavailable",
    "localtime path is a directory": "localtime-path-invalid",
    "localtime file is read-only": "localtime-read-only",
}


def default_state_path(environ: Mapping[str, str] | None = None) -> Path:
    selected = os.environ if environ is None else environ
    root = (
        selected.get("MSYS_COMPONENT_STATE_DIR")
        or selected.get("MSYS_APP_STATE_DIR")
    )
    if root:
        return Path(root) / "regional.json"
    return Path.home() / ".local/state/msys-settings/regional.json"


class RegionalSettingsStore:
    """Persist UI language and update ``/etc/localtime`` without a daemon."""

    def __init__(
        self,
        state_path: str | os.PathLike[str] | None = None,
        *,
        zoneinfo_dir: str | os.PathLike[str] | None = None,
        localtime_path: str | os.PathLike[str] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        selected = os.environ if environ is None else environ
        self.state_path = Path(state_path) if state_path else default_state_path(selected)
        self.zoneinfo_dir = Path(
            zoneinfo_dir or selected.get("MSYS_ZONEINFO_DIR", "/usr/share/zoneinfo")
        )
        self.localtime_path = Path(
            localtime_path or selected.get("MSYS_LOCALTIME_PATH", "/etc/localtime")
        )

    def load(self) -> dict[str, str]:
        result = {"language": "system", "timezone": self._installed_timezone()}
        try:
            document = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
            return result
        if not isinstance(document, dict) or document.get("schema") != REGIONAL_SCHEMA:
            return result
        language = document.get("language")
        if language in LANGUAGES:
            result["language"] = str(language)
        # /etc/localtime is authoritative.  A stale application preference
        # must never claim that the system uses a zone different from the
        # symlink that every new process will actually consume.
        return result

    def status(self) -> dict[str, Any]:
        state = self.load()
        available, reason = self.timezone_capability()
        return {
            "schema": REGIONAL_SCHEMA,
            **state,
            "resolved_language": state["language"],
            "timezone_writable": available,
            "timezone_reason": reason,
            "timezone_reason_code": _TIMEZONE_REASON_CODES.get(
                reason,
                "unknown" if reason else "",
            ),
            "timezones": self.available_timezones(),
        }

    def set_language(self, language: str) -> dict[str, Any]:
        if language not in LANGUAGES:
            raise ValueError("unsupported language")
        state = self.load()
        state["language"] = language
        self._save(state)
        return self.status()

    def set_timezone(self, timezone: str) -> dict[str, Any]:
        candidate = self._zone_path(timezone)
        available, reason = self.timezone_capability()
        if not available:
            raise OSError(reason)
        parent = self.localtime_path.parent
        temporary = parent / f".{self.localtime_path.name}.msys-{os.getpid()}"
        try:
            temporary.unlink(missing_ok=True)
            os.symlink(str(candidate), temporary)
            os.replace(temporary, self.localtime_path)
        finally:
            temporary.unlink(missing_ok=True)
        if hasattr(time, "tzset"):
            time.tzset()
        state = self.load()
        state["timezone"] = timezone
        try:
            self._save(state)
            state_persisted = True
            warning = ""
        except OSError as exc:
            # /etc/localtime itself is the persistent system setting.  A
            # failure to update the Settings-local cache cannot roll back the
            # already-committed atomic symlink and must not report that the
            # real time-zone mutation failed.
            state_persisted = False
            warning = str(exc)
        return {
            **self.status(),
            "state_persisted": state_persisted,
            "state_warning": warning,
        }

    def validate_timezone(self, timezone: str) -> bool:
        try:
            self._zone_path(timezone)
        except (OSError, ValueError):
            return False
        return True

    def available_timezones(self) -> list[str]:
        current = self.load()["timezone"]
        ordered = ([current] if current else []) + list(COMMON_TIMEZONES)
        return list(dict.fromkeys(item for item in ordered if self.validate_timezone(item)))

    def timezone_capability(self) -> tuple[bool, str]:
        if not self.zoneinfo_dir.is_dir():
            return False, "zoneinfo database unavailable"
        parent = self.localtime_path.parent
        if not parent.is_dir():
            return False, "localtime directory unavailable"
        if self.localtime_path.is_dir():
            return False, "localtime path is a directory"
        if not os.access(parent, os.W_OK):
            return False, "localtime file is read-only"
        return True, ""

    def _zone_path(self, timezone: str) -> Path:
        if not isinstance(timezone, str) or _TIMEZONE.fullmatch(timezone) is None:
            raise ValueError("invalid timezone name")
        if ".." in timezone.split("/"):
            raise ValueError("invalid timezone path")
        root = self.zoneinfo_dir.resolve(strict=True)
        candidate = (root / timezone).resolve(strict=True)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("timezone escapes zoneinfo directory") from exc
        if not candidate.is_file():
            raise ValueError("timezone data is unavailable")
        return candidate

    def _installed_timezone(self) -> str:
        try:
            target = self.localtime_path.resolve(strict=True)
            root = self.zoneinfo_dir.resolve(strict=True)
            return target.relative_to(root).as_posix()
        except (OSError, ValueError):
            return "UTC" if self.validate_timezone("UTC") else ""

    def _save(self, state: Mapping[str, str]) -> None:
        document = {
            "schema": REGIONAL_SCHEMA,
            "language": state.get("language", "system"),
            "timezone": state.get("timezone", ""),
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.tmp-{os.getpid()}")
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(document, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
        finally:
            temporary.unlink(missing_ok=True)


__all__ = [
    "COMMON_TIMEZONES",
    "LANGUAGES",
    "REGIONAL_SCHEMA",
    "RegionalSettingsStore",
    "default_state_path",
]
