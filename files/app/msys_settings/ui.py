"""Touch-friendly Tk frontend for the MSYS Settings model."""

from __future__ import annotations

import json
import os
import queue
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from .focus import hal_focus_target, role_focus_target
from .localization import SettingsI18n
from .material import MaterialCardButton, MaterialStatusCard, ScrollableSurface
from .model import (
    CH347_CALIBRATION_BOOLEAN_FIELDS,
    CH347_CALIBRATION_INTEGER_FIELDS,
    CH347_CONTROL_SCHEMA,
    CH347_DEBUG_OVERLAY_ITEMS,
    CH347_DEVICE,
    DEFAULT_CH347_DEBUG_OVERLAY,
    DESKTOP_LAYOUTS,
    DESKTOP_SORTS,
    DISPLAY_MIGRATION_TERMINAL_PHASES,
    DisplayMigrationTracker,
    LAYOUT_PROFILES,
    NAVIGATION_MODES,
    ORIENTATIONS,
    OperationResult,
    SettingsModel,
    hal_state_changes,
    normalise_desktop_preferences,
)
from .radio import (
    radio_domain_view,
    radio_state_summary,
    wifi_connect_changes,
    wifi_forget_changes,
    wifi_network_rows,
)
from .responsive import filter_navigation, layout_metrics, text_wrap_length
from .regional import LANGUAGES, RegionalSettingsStore
from .theme import (
    ACCENT,
    ACCENT_CONTAINER,
    ACCENT_HOVER,
    BG,
    DISABLED,
    ERROR,
    ERROR_CONTAINER,
    FIELD_BG,
    MUTED,
    OUTLINE,
    PANEL,
    PANEL_ALT,
    SUCCESS,
    SUCCESS_CONTAINER,
    TEXT,
)
from msys_sdk.ui_fonts import configure_tk_fonts, font_spec
from .viewport import is_compact, window_size


DISPLAY_PROFILE_LABEL_KEYS = {
    "mobile": "display.profile_mobile",
    "kiosk": "display.profile_kiosk",
    "desktop": "display.profile_desktop",
}
ORIENTATION_LABEL_KEYS = {
    "auto": "display.orientation_auto",
    "portrait": "display.orientation_portrait",
    "landscape": "display.orientation_landscape",
}
PHYSICAL_ROTATIONS = ("normal", "right", "left", "inverted")
PHYSICAL_ROTATION_LABEL_KEYS = {
    "normal": "display.physical_normal",
    "right": "display.physical_right",
    "left": "display.physical_left",
    "inverted": "display.physical_inverted",
}
DEBUG_OVERLAY_ITEM_LABEL_KEYS = {
    "fps": "display.debug_overlay_item_fps",
    "dirty": "display.debug_overlay_item_dirty",
    "bytes": "display.debug_overlay_item_bytes",
    "cpu": "display.debug_overlay_item_cpu",
    "bbox": "display.debug_overlay_item_bbox",
    "memory": "display.debug_overlay_item_memory",
}
DESKTOP_LAYOUT_LABEL_KEYS = {
    "profile": "appearance.layout_profile",
    "auto": "appearance.layout_auto",
    "mobile": "appearance.layout_mobile",
    "desktop": "appearance.layout_desktop",
    "kiosk": "appearance.layout_kiosk",
    "embedded": "appearance.layout_embedded",
}
DESKTOP_SORT_LABEL_KEYS = {
    "name": "appearance.sort_name",
    "component": "appearance.sort_component",
}
NAVIGATION_MODE_LABEL_KEYS = {
    "buttons": "appearance.navigation_buttons",
    "pill": "appearance.navigation_pill",
}


def _localized_choice_labels(
    app: "SettingsApplication",
    values: tuple[str, ...],
    keys: dict[str, str],
) -> dict[str, str]:
    """Render protocol values for a chooser without changing their wire value."""

    return {
        value: app.tr(keys[value], fallback=value) if value in keys else value
        for value in values
    }


def _choice_value(selected: str, labels: dict[str, str]) -> str:
    """Return the protocol value represented by a localized chooser label."""

    return next(
        (value for value, label in labels.items() if label == selected),
        selected,
    )


def _known_state_label(app: "SettingsApplication", value: object) -> str:
    """Translate stable state values while preserving unknown provider values."""

    raw = str(value or "")
    key = {
        "available": "common.available",
        "unavailable": "common.unavailable",
        "unknown": "common.unknown",
        "running": "ch347.running",
        "stopped": "ch347.stopped",
    }.get(raw)
    return app.tr(key) if key else raw


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _replace_text(widget: tk.Text, value: Any) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", value if isinstance(value, str) else _json(value))
    widget.configure(state="disabled")


def _configure_if_changed(widget: Any, **options: Any) -> bool:
    """Configure only options whose rendered Tcl value actually changed."""

    changed: dict[str, Any] = {}
    for name, value in options.items():
        try:
            current = widget.cget(name)
        except (KeyError, tk.TclError):
            changed[name] = value
            continue
        if current != value and str(current) != str(value):
            changed[name] = value
    if not changed:
        return False
    widget.configure(**changed)
    return True


def _replace_after(
    scheduler: Any,
    previous: Any,
    delay_ms: int,
    callback: Callable[[], None],
) -> Any:
    """Replace one short debounce timer without retaining obsolete callbacks."""

    if previous is not None:
        try:
            scheduler.after_cancel(previous)
        except tk.TclError:
            pass
    return scheduler.after(delay_ms, callback)


def _insets_text(value: Any) -> str:
    if value is None or value == "auto":
        return "auto"
    if isinstance(value, dict):
        return ",".join(
            str(value.get(edge, 0)) for edge in ("top", "right", "bottom", "left")
        )
    return str(value)


class SettingsApplication:
    EVENT_TOPICS = (
        "msys.activation",
        "msys.hal.changed",
        "msys.shell.preferences.changed",
        "msys.session.preferences.changed",
        "msys.update.checked",
        "msys.update.applied",
        "msys.update.error",
        "msys.install.package_changed",
        "msys.install.error",
        "msys.display.migration",
        "msys.audio.changed",
        "msys.hal.storage.changed",
    )
    SOFTWARE_CENTER_EVENT_TOPICS = (
        "msys.activation",
        "msys.update.checked",
        "msys.update.applied",
        "msys.update.error",
        "msys.install.package_changed",
        "msys.install.error",
    )

    def __init__(
        self,
        model: SettingsModel,
        *,
        defer_initial_refresh: bool = False,
        i18n: SettingsI18n | None = None,
        regional_store: RegionalSettingsStore | None = None,
    ) -> None:
        self.model = model
        self.regional_store = regional_store or RegionalSettingsStore()
        stored_language = self.regional_store.load().get("language", "system")
        self.i18n = i18n or SettingsI18n(
            locale=None if stored_language == "system" else stored_language
        )
        # A supervised component uses one private socket reader for both
        # events and RPC replies. The application must exist before that
        # reader can receive ``post_event`` as its callback, so main()
        # deliberately defers the first page refresh until after
        # ComponentChannel.start(). Standalone callers retain the immediate
        # refresh used by earlier releases.
        self._initial_refresh_enabled = not defer_initial_refresh
        self.mode = os.environ.get("MSYS_SETTINGS_MODE", "settings")
        self.event_topics = (
            self.SOFTWARE_CENTER_EVENT_TOPICS
            if self.mode == "software-center"
            else self.EVENT_TOPICS
        )
        self._root_page = "apps" if self.mode == "software-center" else "home"
        class_name = os.environ.get("MSYS_WINDOW_IDENTITY", "org.msys.settings")
        self.root = tk.Tk(className=class_name)
        self.root.title(
            os.environ.get(
                "MSYS_WINDOW_TITLE",
                self.tr("software_center.title")
                if self.mode == "software-center"
                else self.tr("app.title"),
            )
        )
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._closed = False
        self._tasks = ThreadPoolExecutor(max_workers=3, thread_name_prefix="settings-rpc")
        self._ui_queue: queue.Queue[tuple[str, Any, Any]] = queue.Queue()
        self._busy = 0
        self._pages: dict[str, BasePage] = {}
        self._active_page = self._root_page
        self._page_history: list[str] = []
        self.compact = is_compact(self.root.winfo_screenwidth())
        configure_tk_fonts(
            self.root,
            default_size=9 if self.compact else 10,
        )
        self.metrics = layout_metrics(self.root.winfo_screenwidth())
        self._nav_buttons: dict[str, ttk.Button] = {}
        self._page_titles: dict[str, str] = {}
        self._nav_visible: frozenset[str] = frozenset()
        self._nav_filter_after: Any = None
        self._build_style()
        self._size_window()
        self._build_shell()
        self.root.after(50, self._poll_queue)

    def tr(
        self,
        key: str,
        params: dict[str, object] | None = None,
        *,
        fallback: str | None = None,
    ) -> str:
        return self.i18n.text(key, params, fallback=fallback)

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.root.option_add("*Font", "TkDefaultFont")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=font_spec(self.root, 14 if self.compact else 20, "bold"))
        style.configure("PageTitle.TLabel", background=PANEL, foreground=TEXT, font=font_spec(self.root, 14 if self.compact else 20, "bold"))
        style.configure("Section.TLabel", background=BG, foreground=TEXT, font=font_spec(self.root, 10 if self.compact else 12, "bold"))
        style.configure("Status.TLabel", background=BG, foreground=MUTED)
        style.configure("TButton", padding=((9, 8) if self.compact else (13, 9)), background=PANEL_ALT, foreground=TEXT, borderwidth=0)
        style.map("TButton", background=[("disabled", PANEL_ALT), ("active", ACCENT_CONTAINER), ("pressed", ACCENT_HOVER)], foreground=[("disabled", DISABLED), ("pressed", "#ffffff")])
        style.configure("Nav.TButton", anchor="w", padding=(15, 11), background=BG)
        style.configure("Selected.Nav.TButton", anchor="w", padding=(15, 11), background=ACCENT_CONTAINER, foreground=TEXT)
        style.map("Selected.Nav.TButton", background=[("active", ACCENT_CONTAINER), ("pressed", ACCENT)])
        style.configure("Icon.TButton", padding=(8, 5), background=BG)
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("pressed", "#293d94")], foreground=[("disabled", "#f4f4f4")])
        style.configure("TEntry", fieldbackground=FIELD_BG, foreground=TEXT, insertcolor=TEXT, bordercolor=OUTLINE, padding=7)
        style.configure("TCombobox", fieldbackground=FIELD_BG, foreground=TEXT, arrowsize=18, padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", FIELD_BG)])
        style.configure("TSpinbox", fieldbackground=FIELD_BG, foreground=TEXT, arrowsize=18)
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT, padding=5)
        style.map("TCheckbutton", background=[("active", PANEL_ALT)])
        style.configure(
            "Accent.TCheckbutton",
            background=ACCENT_CONTAINER,
            foreground=TEXT,
            padding=7,
            font=font_spec(self.root, 10, "bold"),
        )
        style.map(
            "Accent.TCheckbutton",
            background=[("active", ACCENT_CONTAINER), ("pressed", ACCENT_HOVER)],
        )
        style.configure("TLabelframe", background=PANEL, foreground=TEXT)
        style.configure("TLabelframe.Label", background=PANEL, foreground=MUTED)
        style.configure("TNotebook", background=PANEL, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=PANEL_ALT,
            foreground=TEXT,
            padding=(8, 7),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", ACCENT), ("active", ACCENT_CONTAINER)],
            foreground=[("selected", "#ffffff")],
        )
        style.configure("Error.TLabel", background=PANEL, foreground=ERROR)
        style.configure("Success.TLabel", background=PANEL, foreground=SUCCESS)
        style.configure(
            "Treeview",
            background=FIELD_BG,
            fieldbackground=FIELD_BG,
            foreground=TEXT,
            rowheight=34 if self.compact else 38,
        )
        style.configure("Treeview.Heading", background=PANEL_ALT, foreground=TEXT, padding=6)
        style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])

    def _size_window(self) -> None:
        width, height = window_size(
            self.root.winfo_screenwidth(),
            self.root.winfo_screenheight(),
        )
        self.root.geometry(f"{width}x{height}+0+0")

    def _build_shell(self) -> None:
        self.status = tk.StringVar(value=self.tr("common.ready"))
        self.page_title = tk.StringVar(value=self.tr("home.title"))
        if self.compact:
            header = ttk.Frame(self.root, padding=(8, 5))
            header.pack(fill="x")
            self.back_button: ttk.Button | None = ttk.Button(
                header,
                text="<",
                style="Icon.TButton",
                width=3,
                command=self.navigate_back,
            )
            self.back_button.pack(side="left")
            self.header_title = ttk.Label(
                header,
                textvariable=self.page_title,
                style="Title.TLabel",
            )
            self.header_title.pack(
                side="left", padx=(5, 0)
            )
            self.activity = ttk.Progressbar(header, mode="indeterminate", length=42)
            self.activity.pack(side="right")
        else:
            self.back_button = None
            self.activity = ttk.Progressbar(self.root, mode="indeterminate", length=72)

        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True)
        nav = ttk.Frame(body, padding=(14, 16))
        if not self.compact:
            nav.pack(side="left", fill="y")
            nav.configure(width=self.metrics.navigation_width)
            nav.pack_propagate(False)
            ttk.Label(
                nav,
                text=self.tr(
                    "software_center.title"
                    if self.mode == "software-center"
                    else "app.title"
                ),
                style="Title.TLabel",
            ).pack(
                anchor="w", pady=(0, 12)
            )
            ttk.Label(
                nav,
                text=self.tr("nav.search"),
                style="Status.TLabel",
            ).pack(anchor="w", pady=(0, 3))
            self.search = tk.StringVar()
            search = ttk.Entry(nav, textvariable=self.search)
            search.pack(fill="x", pady=(0, 12))
            self.search.trace_add("write", self._schedule_navigation_filter)
            self.search_empty = ttk.Label(
                nav,
                text=self.tr("nav.no_results"),
                style="Status.TLabel",
            )
        content = ttk.Frame(body, style="Panel.TFrame")
        content.pack(side="left", fill="both", expand=True, padx=(0 if self.compact else 1, 0))

        if self.mode == "software-center":
            page_types: list[tuple[str, str, type[BasePage]]] = [
                ("apps", "nav.apps", AppsPage),
                ("updates", "nav.updates", UpdatesPage),
            ]
        else:
            page_types = [
                ("home", "nav.home", HomePage),
                ("wifi", "nav.wifi", WifiPage),
                ("bluetooth", "nav.bluetooth", BluetoothPage),
                ("audio", "nav.audio", AudioPage),
                ("layout", "nav.display", LayoutPage),
                ("appearance", "nav.appearance", AppearancePage),
                ("storage", "nav.storage", StoragePage),
                ("apps", "nav.apps", AppsPage),
                ("roles", "nav.roles", RolesPage),
                ("hal", "nav.hal", HalPage),
                ("updates", "nav.updates", UpdatesPage),
                ("regional", "nav.regional", RegionalPage),
                ("system", "nav.system", SystemPage),
            ]
        self._nav_entries = tuple(
            (key, self.tr(label_key)) for key, label_key, _page in page_types
        )
        for key, label_key, page_type in page_types:
            label = self.tr(label_key)
            self._page_titles[key] = label
            if not self.compact:
                button = ttk.Button(
                    nav,
                    text=label,
                    style="Nav.TButton",
                    command=lambda selected=key: self.show_page(selected),
                )
                button.pack(fill="x", pady=2)
                self._nav_buttons[key] = button
            page = page_type(content, self)
            page.grid(row=0, column=0, sticky="nsew")
            self._pages[key] = page
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)
        self._nav_visible = frozenset(self._nav_buttons)
        footer = ttk.Frame(self.root, padding=(8, 3))
        footer.pack(fill="x", side="bottom")
        ttk.Label(footer, textvariable=self.status, style="Status.TLabel").pack(
            side="left", fill="x", expand=True
        )
        if not self.compact:
            self.activity.pack(in_=footer, side="right")
        self.show_page(self._root_page)

    def _schedule_navigation_filter(self, *_args: Any) -> None:
        if self.compact:
            return
        self._nav_filter_after = _replace_after(
            self.root,
            self._nav_filter_after,
            55,
            self._run_navigation_filter,
        )

    def _run_navigation_filter(self) -> None:
        self._nav_filter_after = None
        self._filter_navigation()

    def _filter_navigation(self) -> None:
        if self.compact:
            return
        visible = frozenset(filter_navigation(self.search.get(), self._nav_entries))
        if visible == self._nav_visible:
            return
        for key in self._nav_visible - visible:
            button = self._nav_buttons[key]
            if button.winfo_manager():
                button.pack_forget()
        ordered = [key for key, _label in self._nav_entries if key in visible]
        for position in range(len(ordered) - 1, -1, -1):
            key = ordered[position]
            button = self._nav_buttons[key]
            if button.winfo_manager():
                continue
            next_button = next(
                (
                    self._nav_buttons[candidate]
                    for candidate in ordered[position + 1 :]
                    if self._nav_buttons[candidate].winfo_manager()
                ),
                None,
            )
            if next_button is None:
                button.pack(fill="x", pady=2)
            else:
                button.pack(fill="x", pady=2, before=next_button)
        empty_visible = bool(self.search_empty.winfo_manager())
        if visible and empty_visible:
            self.search_empty.pack_forget()
        elif not visible and not empty_visible:
            self.search_empty.pack(anchor="w", pady=8)
        self._nav_visible = visible

    def show_page(self, name: str, *, record_history: bool = True) -> None:
        if name == "overview":  # compatibility with the pre-0.2 page key
            name = "system"
        page = self._pages[name]
        if (
            record_history
            and name != self._active_page
            and self._active_page in self._pages
        ):
            self._page_history.append(self._active_page)
            del self._page_history[:-16]
        self._active_page = name
        self.page_title.set(self._page_titles.get(name, self.tr("app.title")))
        if self.compact and self.back_button is not None:
            if name == self._root_page:
                self.back_button.pack_forget()
            elif not self.back_button.winfo_manager():
                self.back_button.pack(side="left", before=self.header_title)
        for key, button in self._nav_buttons.items():
            button.configure(
                style="Selected.Nav.TButton" if key == name else "Nav.TButton"
            )
        page.tkraise()
        if self._initial_refresh_enabled:
            page.on_show()

    def navigate_back(self) -> bool:
        """Return to the previous in-app page without ending the component."""

        root_page = getattr(self, "_root_page", "home")
        while self._page_history:
            target = self._page_history.pop()
            if target in self._pages and target != self._active_page:
                self.show_page(target, record_history=False)
                return True
        if self._active_page != root_page and root_page in self._pages:
            self.show_page(root_page, record_history=False)
            return True
        return False

    def handle_call(self, message: dict[str, Any]) -> dict[str, Any]:
        """Run the language-neutral application navigation call on Tk's thread."""

        method = str(message.get("method") or "")
        if method == "get_regional_settings":
            return {"ok": True, **self.regional_store.status()}
        if method in {"set_language", "set_timezone"}:
            payload = message.get("payload", {})
            if not isinstance(payload, dict):
                return {
                    "ok": False,
                    "schema": "msys.settings.regional.v1",
                    "code": "BAD_REQUEST",
                    "message": "payload must be an object",
                }
            reply: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._ui_queue.put(("regional", (method, payload), reply))
            try:
                return reply.get(timeout=2.0)
            except queue.Empty:
                return {
                    "ok": False,
                    "schema": "msys.settings.regional.v1",
                    "code": "UI_TIMEOUT",
                    "message": "regional settings UI timed out",
                }
        if method != "navigation_back":
            return {"handled": False, "reason": "method-not-supported"}
        reply: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        self._ui_queue.put(("navigation_back", None, reply))
        try:
            return reply.get(timeout=1.0)
        except queue.Empty:
            return {"handled": False, "reason": "ui-timeout"}

    def start_initial_refresh(self) -> None:
        """Enable page loading after the component RPC reader is running."""

        if self._initial_refresh_enabled:
            return
        self._initial_refresh_enabled = True
        self._pages[self._active_page].on_show()
        future = self._tasks.submit(self.model.client.get_session_preferences)

        def session_loaded(done: Any) -> None:
            try:
                payload = done.result()
            except BaseException:
                return
            if isinstance(payload, dict):
                self.post_event({
                    "type": "event",
                    "topic": "msys.session.preferences.changed",
                    "source": "msys.core",
                    "payload": payload,
                })

        future.add_done_callback(session_loaded)

    def set_status(self, message: str, *, error: bool = False) -> None:
        self.status.set(message)
        color = ERROR if error else MUTED
        ttk.Style(self.root).configure("Status.TLabel", foreground=color)

    def run_task(
        self,
        label: str,
        operation: Callable[[], OperationResult],
        callback: Callable[[OperationResult], bool | None],
    ) -> None:
        if self._closed:
            return
        self._busy += 1
        if self._busy == 1:
            self.activity.start(12)
        self.set_status(label)
        future = self._tasks.submit(operation)

        def completed(done: Any) -> None:
            try:
                result = done.result()
            except BaseException as exc:  # keep the Tk loop alive on provider bugs
                result = OperationResult(False, message=str(exc), code="CLIENT_ERROR")
            self._ui_queue.put(("result", callback, result))

        future.add_done_callback(completed)

    def post_event(self, event: dict[str, Any]) -> None:
        self._ui_queue.put(("event", event, None))

    def handle_display_migration(self, payload: dict[str, Any]) -> bool:
        roles = self._pages.get("roles")
        if not isinstance(roles, RolesPage):
            return False
        record = roles.display_migration(payload)
        if record is None:
            return False
        phase = str(record["phase"])
        migration_id = int(record["id"])
        if phase in DISPLAY_MIGRATION_TERMINAL_PHASES:
            for name in ("roles", "layout", "hal"):
                page = self._pages.get(name)
                if isinstance(page, BasePage):
                    page.refresh()
        if phase == "rolled-back":
            error = record.get("error", {})
            code = str(error.get("code") or "DISPLAY_MIGRATION_FAILED")
            message = str(
                error.get("message")
                or self.tr("roles.migration_rollback_fallback")
            )
            self.set_status(
                self.tr("status.display_rollback", {"code": code, "message": message}),
                error=True,
            )
        else:
            self.set_status(
                self.tr(
                    "status.display_migration",
                    {"id": migration_id, "phase": phase},
                )
            )
        return True

    def _poll_queue(self) -> None:
        if self._closed:
            return
        while True:
            try:
                kind, first, second = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "result":
                self._busy = max(0, self._busy - 1)
                if self._busy == 0:
                    self.activity.stop()
                callback = first
                result: OperationResult = second
                status_handled = callback(result) is True
                if not status_handled:
                    if result.ok:
                        self.set_status(result.message or self.tr("common.ready"))
                    else:
                        self.set_status(
                            result.message
                            or result.code
                            or self.tr("common.operation_failed"),
                            error=True,
                        )
            elif kind == "navigation_back":
                reply: queue.Queue[dict[str, Any]] = second
                result = {
                    "handled": self.navigate_back(),
                    "page": self._active_page,
                }
                try:
                    reply.put_nowait(result)
                except queue.Full:
                    pass
            elif kind == "regional":
                method, payload = first
                reply = second
                result = self._apply_regional_call(str(method), payload)
                try:
                    reply.put_nowait(result)
                except queue.Full:
                    pass
            elif kind == "event":
                event: dict[str, Any] = first
                topic = str(event.get("topic", ""))
                payload = event.get("payload", {})
                status_handled = False
                if topic == "msys.activation" and isinstance(payload, dict):
                    if self.mode == "software-center":
                        action = str(payload.get("action") or "")
                        panel = str(
                            payload.get("name")
                            or payload.get("panel")
                            or "apps"
                        )
                        selected = str(
                            payload.get("component")
                            or payload.get("selected_component")
                            or ""
                        )
                        page = "updates" if panel == "updates" else "apps"
                        self.show_page(page)
                        apps = self._pages.get("apps")
                        if (
                            isinstance(apps, AppsPage)
                            and selected
                            and panel in {"details", "uninstall", "apps"}
                        ):
                            apps.activate_package(selected, panel)
                        status_handled = action in {"", "software-center"}
                        continue
                    panel = str(payload.get("name", "system"))
                    page = (
                        "home"
                        if panel == ""
                        else "system"
                        if panel == "system"
                        else "layout"
                        if panel == "display"
                        else panel
                    )
                    if page in self._pages:
                        self.show_page(page)
                elif topic.startswith("msys.update.") or topic.startswith("msys.install."):
                    updates = self._pages.get("updates")
                    if isinstance(updates, UpdatesPage):
                        updates.append_event(event)
                    if topic == "msys.install.package_changed":
                        apps = self._pages.get("apps")
                        if isinstance(apps, AppsPage) and apps._loaded:
                            apps.refresh()
                elif topic == "msys.hal.changed":
                    hal = self._pages.get("hal")
                    if isinstance(hal, HalPage):
                        hal.external_change(payload if isinstance(payload, dict) else {})
                    for name in ("wifi", "bluetooth"):
                        radio = self._pages.get(name)
                        if isinstance(radio, RadioPage):
                            radio.external_change(
                                payload if isinstance(payload, dict) else {}
                            )
                elif topic == "msys.shell.preferences.changed":
                    appearance = self._pages.get("appearance")
                    if isinstance(appearance, AppearancePage):
                        appearance.external_change(
                            payload if isinstance(payload, dict) else {}
                        )
                elif topic == "msys.session.preferences.changed" and isinstance(payload, dict):
                    language = str(payload.get("language") or "")
                    if language in LANGUAGES:
                        current = self.regional_store.load().get("language", "system")
                        if current != language:
                            try:
                                self.regional_store.set_language(language)
                            except OSError as exc:
                                self.set_status(str(exc), error=True)
                            else:
                                active = self._active_page or "home"
                                self.i18n = SettingsI18n(
                                    locale=None if language == "system" else language
                                )
                                self._rebuild_shell(active)
                        status_handled = True
                elif topic == "msys.audio.changed":
                    audio = self._pages.get("audio")
                    if isinstance(audio, AudioPage):
                        audio.external_change()
                    bluetooth = self._pages.get("bluetooth")
                    if isinstance(bluetooth, BluetoothPage):
                        bluetooth.external_audio_change()
                    # This is an invalidation signal, not user-facing status.
                    # The active page refreshes itself and inactive pages are
                    # marked stale without exposing the raw event topic.
                    status_handled = True
                elif topic == "msys.hal.storage.changed":
                    storage = self._pages.get("storage")
                    if isinstance(storage, StoragePage) and storage._loaded:
                        storage.refresh()
                    status_handled = True
                elif topic == "msys.display.migration" and isinstance(payload, dict):
                    self.handle_display_migration(payload)
                    # A duplicate terminal/progress record is intentionally
                    # ignored without replacing the useful existing status.
                    status_handled = True
                if not status_handled:
                    self.set_status(topic or self.tr("status.event"))
        self.root.after(50, self._poll_queue)

    def _apply_regional_call(
        self,
        method: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            if method == "set_language":
                language = payload.get("language")
                if not isinstance(language, str) or language not in LANGUAGES:
                    raise ValueError("unsupported language")
                session = self.model.client.set_session_language(language)
                state = self.regional_store.set_language(language)
                if isinstance(session, dict):
                    state.update({
                        key: session[key]
                        for key in ("resolved_language", "changed")
                        if key in session
                    })
                self.i18n = SettingsI18n(
                    locale=None if language == "system" else language
                )
                self._rebuild_shell("regional")
            elif method == "set_timezone":
                timezone = payload.get("timezone")
                if not isinstance(timezone, str):
                    raise ValueError("timezone must be a string")
                state = self.regional_store.set_timezone(timezone)
                self.model.client.notify_timezone_changed(timezone)
                regional = self._pages.get("regional")
                if isinstance(regional, RegionalPage):
                    regional.refresh()
            else:
                raise ValueError("unsupported regional method")
            return {"ok": True, **state}
        except (OSError, ValueError) as exc:
            return {
                "ok": False,
                "schema": "msys.settings.regional.v1",
                "code": (
                    "BAD_REQUEST" if isinstance(exc, ValueError)
                    else "REGIONAL_UNAVAILABLE"
                ),
                "message": str(exc),
            }

    def _rebuild_shell(self, target: str) -> None:
        if self._nav_filter_after is not None:
            try:
                self.root.after_cancel(self._nav_filter_after)
            except tk.TclError:
                pass
            self._nav_filter_after = None
        for child in self.root.winfo_children():
            child.destroy()
        self._pages = {}
        self._nav_buttons = {}
        self._page_titles = {}
        self._nav_visible = frozenset()
        self._page_history = []
        self._active_page = ""
        refresh_enabled = self._initial_refresh_enabled
        self._initial_refresh_enabled = False
        self.root.title(
            self.tr(
                "software_center.title"
                if self.mode == "software-center"
                else "app.title"
            )
        )
        self._build_style()
        self._build_shell()
        self._initial_refresh_enabled = refresh_enabled
        if target in self._pages:
            self.show_page(target, record_history=False)
        self.set_status(self.tr("regional.language_applied"))

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._tasks.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


class BasePage(ttk.Frame):
    title_key = ""
    note_key = ""

    def __init__(self, parent: ttk.Frame, app: SettingsApplication) -> None:
        super().__init__(
            parent,
            style="Panel.TFrame",
            padding=((8, 7) if app.compact else (16, 12)),
        )
        self.app = app
        self._loaded = False
        title = app.tr(self.title_key) if self.title_key else ""
        note = app.tr(self.note_key) if self.note_key else ""
        if title and not app.compact:
            ttk.Label(self, text=title, style="PageTitle.TLabel").pack(anchor="w")
        if note:
            note_label = ttk.Label(
                self,
                text=note,
                style="Muted.TLabel",
                wraplength=text_wrap_length(
                    app.root.winfo_screenwidth(),
                    horizontal_padding=24 if app.compact else 80,
                    minimum=150,
                ),
                justify="left",
            )
            note_label.pack(anchor="w", fill="x", pady=(2, 10))
            note_label.bind(
                "<Configure>",
                lambda event, label=note_label: label.configure(
                    wraplength=text_wrap_length(
                        int(event.width), horizontal_padding=4
                    )
                ),
            )

    def on_show(self) -> None:
        if not self._loaded:
            self._loaded = True
            self.refresh()

    def refresh(self) -> None:
        pass


class HomePage(BasePage):
    """Scrollable card-based landing page for compact and desktop layouts."""

    title_key = "home.title"
    note_key = "home.note"

    def __init__(self, parent: ttk.Frame, app: SettingsApplication) -> None:
        super().__init__(parent, app)
        surface = ScrollableSurface(self, background=PANEL)
        surface.pack(fill="both", expand=True)
        content = surface.content
        padding = app.metrics.outer_padding

        self._section(content, app.tr("home.quick"), padding)
        quick = tk.Frame(content, background=PANEL)
        quick.pack(fill="x", padx=padding, pady=(0, app.metrics.card_gap))
        quick.columnconfigure(0, weight=1, uniform="quick")
        quick.columnconfigure(1, weight=1, uniform="quick")
        if not app.compact:
            quick.columnconfigure(2, weight=1, uniform="quick")
        quick_items = (
            ("wifi", "Wi", "nav.wifi", "home.wifi.note"),
            ("bluetooth", "Bt", "nav.bluetooth", "home.bluetooth.note"),
            ("layout", "D", "nav.display", "home.display.note"),
        )
        for index, (key, icon, title_key, note_key) in enumerate(quick_items):
            card = MaterialCardButton(
                quick,
                title=app.tr(title_key),
                subtitle=app.tr(note_key),
                icon=icon,
                command=lambda selected=key: app.show_page(selected),
                height=92 if app.compact else 104,
                accent=index == 0,
                scroll=surface.scroll_pixels,
            )
            if app.compact and index == 2:
                card.grid(
                    row=1,
                    column=0,
                    columnspan=2,
                    sticky="ew",
                    pady=(app.metrics.card_gap, 0),
                )
            else:
                card.grid(
                    row=0,
                    column=index,
                    sticky="ew",
                    padx=(0, app.metrics.card_gap) if index < 2 else 0,
                )

        self._section(content, app.tr("home.more"), padding)
        more = tk.Frame(content, background=PANEL)
        more.pack(fill="x", padx=padding, pady=(0, padding))
        self.keyboard_card = MaterialCardButton(
            more,
            title=app.tr("home.keyboard.title"),
            subtitle=app.tr("keyboard.unavailable"),
            icon="Kb",
            command=self.toggle_keyboard,
            height=62 if app.compact else 68,
            compact=True,
            scroll=surface.scroll_pixels,
        )
        self.keyboard_card.set_disabled(True)
        self.keyboard_card.pack(fill="x", pady=(0, app.metrics.card_gap))
        self.calibration_card = MaterialCardButton(
            more,
            title=app.tr("home.calibration.title"),
            subtitle=app.tr("home.calibration.checking"),
            icon="Tc",
            command=self.start_calibration,
            height=62 if app.compact else 68,
            compact=True,
            scroll=surface.scroll_pixels,
        )
        self.calibration_card.set_disabled(True)
        self.calibration_card.pack(fill="x", pady=(0, app.metrics.card_gap))
        more_items = (
            ("audio", "Au", "nav.audio", "home.audio.note"),
            ("appearance", "A", "nav.appearance", "home.appearance.note"),
            ("storage", "St", "nav.storage", "home.storage.note"),
            ("apps", "P", "nav.apps", "home.apps.note"),
            ("roles", "R", "nav.roles", "home.roles.note"),
            ("hal", "H", "nav.hal", "home.hal.note"),
            ("updates", "U", "nav.updates", "home.updates.note"),
            ("regional", "G", "nav.regional", "home.regional.note"),
            ("system", "S", "nav.system", "home.system.note"),
        )
        for key, icon, title_key, note_key in more_items:
            card = MaterialCardButton(
                more,
                title=app.tr(title_key),
                subtitle=app.tr(note_key),
                icon=icon,
                command=lambda selected=key: app.show_page(selected),
                height=62 if app.compact else 68,
                compact=True,
                scroll=surface.scroll_pixels,
            )
            card.pack(fill="x", pady=(0, app.metrics.card_gap))

    def on_show(self) -> None:
        self._loaded = True
        self.refresh()

    def refresh(self) -> None:
        self.keyboard_card.set_disabled(True)
        self.calibration_card.set_disabled(True)
        self.app.run_task(
            self.app.tr("status.loading_keyboard"),
            self.app.model.input_method_status,
            self._keyboard_result,
        )
        self.app.run_task(
            self.app.tr("status.checking_calibration"),
            self.app.model.touch_calibration_status,
            self._calibration_status,
        )

    def toggle_keyboard(self) -> None:
        self.keyboard_card.set_disabled(True)
        self.app.run_task(
            self.app.tr("status.toggling_keyboard"),
            self.app.model.toggle_input_method,
            self._keyboard_result,
        )

    def _keyboard_result(self, result: OperationResult) -> bool:
        if not result.ok:
            self.keyboard_card.set_text(subtitle=self.app.tr("keyboard.unavailable"))
            self.keyboard_card.set_disabled(True)
            self.app.set_status(self.app.tr("keyboard.unavailable"))
            return True
        self.keyboard_card.set_text(
            subtitle=self.app.tr(
                "keyboard.visible" if result.data.get("visible") else "keyboard.hidden"
            )
        )
        self.keyboard_card.set_disabled(False)
        self.app.set_status(self.app.tr("common.ready"))
        return True

    def start_calibration(self) -> None:
        self.calibration_card.set_disabled(True)
        self.app.run_task(
            self.app.tr("status.starting_calibration"),
            self.app.model.start_touch_calibration,
            self._calibration_started,
        )

    def _calibration_status(self, result: OperationResult) -> bool:
        available = result.ok and result.data.get("available") is True
        self.calibration_card.set_text(
            subtitle=self.app.tr(
                "home.calibration.ready"
                if available
                else "home.calibration.unavailable"
            )
        )
        self.calibration_card.set_disabled(not available)
        return True

    def _calibration_started(self, result: OperationResult) -> bool:
        if result.ok:
            self.app.set_status(self.app.tr("home.calibration.started"))
            self.calibration_card.set_disabled(False)
        else:
            self.app.set_status(
                result.message or self.app.tr("home.calibration.unavailable"),
                error=True,
            )
            self.calibration_card.set_disabled(False)
        return True

    @staticmethod
    def _section(parent: tk.Frame, text: str, padding: int) -> None:
        tk.Label(
            parent,
            text=text,
            background=PANEL,
            foreground=TEXT,
            font=font_spec(parent, 10, "bold"),
            anchor="w",
        ).pack(fill="x", padx=padding, pady=(8, 7))


class RegionalPage(BasePage):
    """Unified phone/desktop language and timezone secondary page."""

    title_key = "regional.title"
    note_key = "regional.note"

    def __init__(self, parent: ttk.Frame, app: SettingsApplication) -> None:
        super().__init__(parent, app)
        self.surface = ScrollableSurface(self, background=PANEL)
        self.surface.pack(fill="both", expand=True)
        content = self.surface.content
        self.summary_title = tk.StringVar(value=app.tr("common.loading"))
        self.summary_body = tk.StringVar(value=app.tr("common.not_loaded"))
        MaterialStatusCard(
            content,
            title=self.summary_title,
            body=self.summary_body,
            compact=app.compact,
        ).pack(fill="x", pady=(0, 10))

        self.language_labels = {
            "system": app.tr("regional.language_system"),
            "zh-CN": app.tr("regional.language_chinese"),
            "en-US": app.tr("regional.language_english"),
        }
        language_card = ttk.LabelFrame(
            content,
            text=app.tr("regional.language"),
            padding=(12, 10),
        )
        language_card.pack(fill="x", pady=(0, 10))
        ttk.Label(
            language_card,
            text=app.tr("regional.language_hint"),
            style="Panel.TLabel",
            wraplength=280 if app.compact else 680,
            justify="left",
        ).pack(fill="x", pady=(0, 8))
        self.language = tk.StringVar()
        self.language_combo = ttk.Combobox(
            language_card,
            textvariable=self.language,
            values=list(self.language_labels.values()),
            state="readonly",
        )
        self.language_combo.pack(fill="x", pady=(0, 8))
        self.language_apply = ttk.Button(
            language_card,
            text=app.tr("regional.apply_language"),
            command=self.apply_language,
            style="Accent.TButton",
        )
        self.language_apply.pack(fill="x" if app.compact else "none", anchor="e")

        timezone_card = ttk.LabelFrame(
            content,
            text=app.tr("regional.timezone"),
            padding=(12, 10),
        )
        timezone_card.pack(fill="x", pady=(0, 10))
        ttk.Label(
            timezone_card,
            text=app.tr("regional.timezone_hint"),
            style="Panel.TLabel",
            wraplength=280 if app.compact else 680,
            justify="left",
        ).pack(fill="x", pady=(0, 8))
        self.timezone = tk.StringVar()
        self.timezone_combo = ttk.Combobox(
            timezone_card,
            textvariable=self.timezone,
            state="readonly",
        )
        self.timezone_combo.pack(fill="x", pady=(0, 8))
        self.timezone_apply = ttk.Button(
            timezone_card,
            text=app.tr("regional.apply_timezone"),
            command=self.apply_timezone,
            style="Accent.TButton",
        )
        self.timezone_apply.pack(fill="x" if app.compact else "none", anchor="e")
        self.unavailable = ttk.Label(
            timezone_card,
            style="Muted.TLabel",
            justify="left",
            wraplength=280 if app.compact else 680,
        )

    def on_show(self) -> None:
        self._loaded = True
        self.refresh()

    def refresh(self) -> None:
        state = self.app.regional_store.status()
        language = str(state.get("language") or "system")
        timezone = str(state.get("timezone") or "")
        self.language.set(self.language_labels.get(language, self.language_labels["system"]))
        values = [str(item) for item in state.get("timezones", [])]
        self.timezone_combo.configure(values=values)
        self.timezone.set(timezone if timezone in values else (values[0] if values else ""))
        writable = state.get("timezone_writable") is True and bool(values)
        self.timezone_apply.configure(state="normal" if writable else "disabled")
        reason = str(state.get("timezone_reason") or "")
        if writable:
            self.unavailable.pack_forget()
        else:
            reason_key = {
                "zoneinfo-unavailable": "regional.timezone_reason_zoneinfo",
                "localtime-directory-unavailable": "regional.timezone_reason_directory",
                "localtime-path-invalid": "regional.timezone_reason_invalid_path",
                "localtime-read-only": "regional.timezone_reason_read_only",
            }.get(str(state.get("timezone_reason_code") or ""))
            localized_reason = (
                self.app.tr(reason_key, fallback=reason)
                if reason_key is not None
                else reason or self.app.tr("common.unavailable")
            )
            self.unavailable.configure(
                text=self.app.tr(
                    "regional.timezone_unavailable",
                    {"reason": localized_reason},
                )
            )
            self.unavailable.pack(fill="x", pady=(8, 0))
        self.summary_title.set(self.app.tr("regional.summary_title"))
        self.summary_body.set(
            self.app.tr(
                "regional.summary",
                {
                    "language": self.language_labels.get(language, language),
                    "timezone": timezone or self.app.tr("common.unavailable"),
                },
            )
        )

    def apply_language(self) -> None:
        reverse = {label: key for key, label in self.language_labels.items()}
        selected = reverse.get(self.language.get())
        result = self.app._apply_regional_call(
            "set_language", {"language": selected}
        )
        if not result.get("ok"):
            self.app.set_status(str(result.get("message") or ""), error=True)

    def apply_timezone(self) -> None:
        result = self.app._apply_regional_call(
            "set_timezone", {"timezone": self.timezone.get()}
        )
        if result.get("ok"):
            self.app.set_status(self.app.tr("regional.timezone_applied"))
        else:
            self.app.set_status(str(result.get("message") or ""), error=True)


class SystemPage(BasePage):
    title_key = "system.title"
    note_key = "system.note"

    def __init__(self, parent: ttk.Frame, app: SettingsApplication) -> None:
        super().__init__(parent, app)
        self.surface = ScrollableSurface(self, background=PANEL)
        self.surface.pack(fill="both", expand=True)
        content = self.surface.content
        toolbar = ttk.Frame(content, style="Panel.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        self.summary = tk.StringVar(value=app.tr("common.not_loaded"))
        ttk.Label(toolbar, textvariable=self.summary, style="Panel.TLabel").pack(
            side="top" if app.compact else "left",
            anchor="w",
            fill="x" if app.compact else "none",
        )
        ttk.Button(toolbar, text=app.tr("common.refresh"), command=self.refresh).pack(
            side="top" if app.compact else "right",
            anchor="e",
            pady=(4, 0) if app.compact else 0,
        )

        self.session_summary = tk.StringVar(value=app.tr("common.loading"))
        self.components_summary = tk.StringVar(value=app.tr("common.loading"))
        self.roles_summary = tk.StringVar(value=app.tr("common.loading"))
        self.services_summary = tk.StringVar(value=app.tr("common.loading"))
        self.isolation_summary = tk.StringVar(value=app.tr("common.loading"))
        for title_key, value in (
            ("system.session", self.session_summary),
            ("system.components", self.components_summary),
            ("system.roles", self.roles_summary),
            ("system.services", self.services_summary),
            ("system.isolation", self.isolation_summary),
        ):
            self._summary_card(content, app.tr(title_key), value)

        self.diagnostics_visible = False
        self.diagnostics_button_text = tk.StringVar(
            value=app.tr("system.show_diagnostics")
        )
        ttk.Button(
            content,
            textvariable=self.diagnostics_button_text,
            command=self.toggle_diagnostics,
        ).pack(anchor="w", pady=(2, 7))
        self.details_frame = ttk.Frame(content, style="Panel.TFrame")
        self.details = tk.Text(
            self.details_frame,
            bg=FIELD_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            padx=10,
            pady=8,
            wrap="word",
            height=9 if app.compact else 14,
        )
        details_scroll = ttk.Scrollbar(
            self.details_frame,
            orient="vertical",
            command=self.details.yview,
        )
        self.details.configure(yscrollcommand=details_scroll.set)
        self.details.pack(side="left", fill="both", expand=True)
        details_scroll.pack(side="right", fill="y")
        self.details.configure(state="disabled")

    def _summary_card(
        self,
        parent: tk.Misc,
        title: str,
        value: tk.StringVar,
    ) -> None:
        card = tk.Frame(
            parent,
            background=PANEL_ALT,
            highlightbackground=OUTLINE,
            highlightthickness=1,
            padx=12,
            pady=9,
        )
        card.pack(fill="x", pady=(0, 7))
        tk.Label(
            card,
            text=title,
            background=PANEL_ALT,
            foreground=TEXT,
            anchor="w",
            font=font_spec(card, 10, "bold"),
        ).pack(fill="x")
        body = tk.Label(
            card,
            textvariable=value,
            background=PANEL_ALT,
            foreground=MUTED,
            anchor="w",
            justify="left",
            wraplength=276 if self.app.compact else 650,
        )
        body.pack(fill="x", pady=(3, 0))
        body.bind(
            "<Configure>",
            lambda event, label=body: label.configure(
                wraplength=max(120, int(event.width) - 4)
            ),
        )

    def toggle_diagnostics(self) -> None:
        self.diagnostics_visible = not self.diagnostics_visible
        if self.diagnostics_visible:
            self.details_frame.pack(fill="both", expand=True, pady=(0, 7))
        else:
            self.details_frame.pack_forget()
        self.diagnostics_button_text.set(
            self.app.tr(
                "system.hide_diagnostics"
                if self.diagnostics_visible
                else "system.show_diagnostics"
            )
        )

    def refresh(self) -> None:
        self.app.run_task(
            self.app.tr("status.loading_system"),
            self.app.model.overview,
            self._loaded_result,
        )

    def _loaded_result(self, result: OperationResult) -> None:
        component_section = result.data.get("components", {})
        service_section = result.data.get("services", {})
        role_section = result.data.get("roles", {})
        components = (
            component_section.get("components", [])
            if isinstance(component_section, dict)
            else []
        )
        services = (
            service_section.get("services", [])
            if isinstance(service_section, dict)
            else []
        )
        roles = (
            role_section.get("roles", [])
            if isinstance(role_section, dict)
            else []
        )
        components = components if isinstance(components, list) else []
        services = services if isinstance(services, list) else []
        roles = roles if isinstance(roles, list) else []
        ready = sum(1 for item in components if isinstance(item, dict) and item.get("state") == "ready")
        if result.ok:
            self.summary.set(
                self.app.tr(
                    "system.summary",
                    {
                        "ready": ready,
                        "total": len(components),
                        "roles": len(roles),
                        "services": len(services),
                    },
                )
            )
        else:
            self.summary.set(self.app.tr("system.unavailable"))

        session = result.data.get("session", {})
        session = session if isinstance(session, dict) else {}
        self.session_summary.set(
            self.app.tr(
                "system.session_summary",
                {
                    "version": str(session.get("package_version") or "—"),
                    "component": str(session.get("component") or "—"),
                    "display": str(session.get("display") or "—"),
                },
            )
        )

        states: dict[str, int] = {}
        for item in components:
            if isinstance(item, dict):
                state = str(item.get("state") or "unknown")
                states[state] = states.get(state, 0) + 1
        attention = sum(
            count for state, count in states.items() if state not in {"ready", "declared"}
        )
        self.components_summary.set(
            self.app.tr(
                "system.components_summary",
                {
                    "ready": states.get("ready", 0),
                    "dormant": states.get("declared", 0),
                    "attention": attention,
                    "total": len(components),
                },
            )
        )

        active_roles = sum(
            1 for item in roles if isinstance(item, dict) and item.get("active")
        )
        self.roles_summary.set(
            self.app.tr(
                "system.roles_summary",
                {"active": active_roles, "total": len(roles)},
            )
        )

        service_kinds: dict[str, int] = {}
        for item in services:
            if isinstance(item, dict):
                kind = str(item.get("kind") or "unknown")
                service_kinds[kind] = service_kinds.get(kind, 0) + 1
        self.services_summary.set(
            self.app.tr(
                "system.services_summary",
                {
                    "interfaces": service_kinds.get("interface", 0),
                    "capabilities": service_kinds.get("capability", 0),
                    "total": len(services),
                },
            )
        )

        isolation = result.data.get("isolation", {})
        isolation = isolation if isinstance(isolation, dict) else {}
        namespaces = isolation.get("namespaces", {})
        namespace_count = (
            sum(value is True for value in namespaces.values())
            if isinstance(namespaces, dict)
            else 0
        )
        limits = isolation.get("rlimits", [])
        limit_count = len(limits) if isinstance(limits, list) else 0
        seccomp = isolation.get("seccomp", {})
        seccomp_available = (
            seccomp.get("available") is True if isinstance(seccomp, dict) else False
        )
        self.isolation_summary.set(
            self.app.tr(
                "system.isolation_summary",
                {
                    "privileges": self.app.tr(
                        "common.enabled"
                        if isolation.get("no_new_privs") is True
                        else "common.disabled"
                    ),
                    "namespaces": namespace_count,
                    "limits": limit_count,
                    "seccomp": self.app.tr(
                        "common.available" if seccomp_available else "common.unavailable"
                    ),
                },
            )
        )
        _replace_text(self.details, result.data or {"error": result.message, "code": result.code})


class RadioPage(BasePage):
    """HAL-backed radio UI that never invents availability or switch state."""

    domain = ""

    def __init__(self, parent: ttk.Frame, app: SettingsApplication) -> None:
        super().__init__(parent, app)
        self.devices: dict[str, dict[str, Any]] = {}
        self._state_generation = 0
        self._loaded_device = ""
        self._power_field = ""
        self._mutable: list[str] = []
        self._network_actions_enabled = False
        self._domain_available = False
        self._network_rows: dict[str, dict[str, Any]] = {}
        self._bluetooth_rows: dict[str, dict[str, Any]] = {}
        self._bluetooth_controller_registered = False
        self._bluetooth_powered: bool | None = None
        self._bluetooth_audio_busy = False
        self._confirmed_power: bool | None = None
        self._hard_blocked = False
        self._operation_error = ""
        self._radio_name = app.tr(f"radio.{self.domain}")
        self.radio_surface = ScrollableSurface(self, background=PANEL)
        self.radio_surface.pack(fill="both", expand=True)
        container = self.radio_surface.content

        self.status_title = tk.StringVar(value=app.tr("common.loading"))
        self.status_body = tk.StringVar(value="")
        self.status_card = MaterialStatusCard(
            container,
            title=self.status_title,
            body=self.status_body,
            compact=app.compact,
        )
        self.status_card.pack(fill="x", pady=(0, 8))
        self.status_title_label = self.status_card.title_label
        self.status_body_label = self.status_card.body_label

        toolbar = ttk.Frame(container, style="Panel.TFrame")
        toolbar.pack(fill="x", pady=(0, 7))
        ttk.Button(
            toolbar,
            text=app.tr("common.refresh"),
            command=self.refresh,
        ).pack(side="left")
        ttk.Button(
            toolbar,
            text=app.tr("common.open_hal"),
            command=self.manage_hal,
        ).pack(side="left", padx=(6, 0))
        if self.domain == "bluetooth":
            audio_parent = toolbar
            if app.compact:
                audio_parent = ttk.Frame(container, style="Panel.TFrame")
                audio_parent.pack(fill="x", pady=(0, 7))
            audio_button = ttk.Button(
                audio_parent,
                text=app.tr("audio.open_audio"),
                command=lambda: app.show_page("audio"),
            )
            audio_button.pack(
                fill="x" if app.compact else "none",
                side="top" if app.compact else "left",
                padx=(0, 0) if app.compact else (6, 0),
            )

        ttk.Label(container, text=app.tr("radio.devices"), style="Panel.TLabel").pack(
            anchor="w", pady=(0, 4)
        )
        device_tree_frame = ttk.Frame(container, style="Panel.TFrame")
        device_tree_frame.pack(fill="x")
        self.device_tree = ttk.Treeview(
            device_tree_frame,
            columns=("name", "kind", "status"),
            show="headings",
            height=2 if app.compact else 4,
            selectmode="browse",
        )
        self.device_tree.heading("name", text=app.tr("common.device"))
        self.device_tree.heading("kind", text=app.tr("common.kind"))
        self.device_tree.heading("status", text=app.tr("common.status"))
        self.device_tree.column("name", width=175 if app.compact else 280, anchor="w")
        self.device_tree.column("kind", width=90, anchor="w")
        self.device_tree.column("status", width=110, anchor="w")
        if app.compact:
            self.device_tree.configure(displaycolumns=("name",))
        device_scroll = ttk.Scrollbar(
            device_tree_frame,
            orient="vertical",
            command=self.device_tree.yview,
        )
        self.device_tree.configure(yscrollcommand=device_scroll.set)
        self.device_tree.pack(side="left", fill="x", expand=True)
        device_scroll.pack(side="right", fill="y")
        self.device_tree.bind("<<TreeviewSelect>>", self._selected)

        controls = ttk.Frame(container, style="Panel.TFrame")
        controls.pack(fill="x", pady=(7, 5))
        self.power = tk.BooleanVar(value=False)
        self.power_toggle = ttk.Checkbutton(
            controls,
            text=app.tr("radio.power"),
            variable=self.power,
            command=self.apply_power,
            state="disabled",
        )
        self.power_toggle.pack(side="left")

        self.network_actions = ttk.Frame(container, style="Panel.TFrame")
        if self.domain == "network":
            self.network_actions.pack(fill="x", pady=(0, 5))
        self.scan_button = ttk.Button(
            self.network_actions,
            text=app.tr("radio.scan"),
            command=lambda: self.apply_action("scan"),
            state="disabled",
        )
        self.scan_button.pack(side="left")
        self.disconnect_button = ttk.Button(
            self.network_actions,
            text=app.tr("radio.disconnect"),
            command=lambda: self.apply_action("disconnect"),
            state="disabled",
        )
        self.disconnect_button.pack(side="left", padx=(6, 0))
        network_secondary = self.network_actions
        if app.compact:
            network_secondary = ttk.Frame(container, style="Panel.TFrame")
            if self.domain == "network":
                network_secondary.pack(fill="x", pady=(0, 5))
        self.connect_button = ttk.Button(
            network_secondary,
            text=app.tr("radio.connect"),
            command=self.connect_network,
            state="disabled",
        )
        self.connect_button.pack(side="left")
        self.forget_button = ttk.Button(
            network_secondary,
            text=app.tr("radio.forget"),
            command=self.forget_network,
            state="disabled",
        )
        self.forget_button.pack(side="left", padx=(6, 0))

        self.network_panel = ttk.Frame(container, style="Panel.TFrame")
        if self.domain == "network":
            self.network_panel.pack(fill="both", expand=True)
        ttk.Label(
            self.network_panel,
            text=app.tr("radio.networks"),
            style="Panel.TLabel",
        ).pack(anchor="w")
        network_tree_frame = ttk.Frame(self.network_panel, style="Panel.TFrame")
        network_tree_frame.pack(fill="both", expand=True, pady=(3, 4))
        self.network_tree = ttk.Treeview(
            network_tree_frame,
            columns=("ssid", "signal", "security"),
            show="headings",
            height=2 if app.compact else 5,
            selectmode="browse",
        )
        self.network_tree.heading("ssid", text="SSID")
        self.network_tree.heading("signal", text="dBm")
        self.network_tree.heading("security", text=app.tr("common.security"))
        self.network_tree.column("ssid", width=160 if app.compact else 300, anchor="w")
        self.network_tree.column("signal", width=55, anchor="e")
        self.network_tree.column("security", width=130, anchor="w")
        if app.compact:
            self.network_tree.configure(displaycolumns=("ssid", "signal"))
        network_scroll = ttk.Scrollbar(
            network_tree_frame,
            orient="vertical",
            command=self.network_tree.yview,
        )
        self.network_tree.configure(yscrollcommand=network_scroll.set)
        self.network_tree.pack(side="left", fill="both", expand=True)
        network_scroll.pack(side="right", fill="y")
        self.network_tree.bind(
            "<<TreeviewSelect>>",
            lambda _event: self._update_network_actions(),
        )
        self.password = tk.StringVar()
        self.password.trace_add("write", lambda *_args: self._update_network_actions())
        password_row = ttk.Frame(self.network_panel, style="Panel.TFrame")
        password_row.pack(fill="x")
        ttk.Label(
            password_row,
            text=app.tr("radio.password"),
            style="Muted.TLabel",
        ).pack(side="left", padx=(0, 5))
        self.password_entry = ttk.Entry(
            password_row,
            textvariable=self.password,
            show="*",
            state="disabled",
        )
        self.password_entry.pack(
            side="left", fill="x", expand=True
        )
        self.operation_notice = tk.StringVar()
        self.operation_notice_label = ttk.Label(
            self.network_panel,
            textvariable=self.operation_notice,
            style="Muted.TLabel",
            wraplength=276 if app.compact else 650,
        )
        self.operation_notice_label.pack(anchor="w", fill="x", pady=(4, 0))

        self.bluetooth_panel = ttk.Frame(container, style="Panel.TFrame")
        if self.domain == "bluetooth":
            self.bluetooth_panel.pack(fill="both", expand=True, pady=(3, 0))
        bluetooth_toolbar = ttk.Frame(self.bluetooth_panel, style="Panel.TFrame")
        bluetooth_toolbar.pack(fill="x", pady=(0, 4))
        ttk.Label(
            bluetooth_toolbar,
            text=app.tr("radio.bluetooth_nearby"),
            style="Panel.TLabel",
        ).pack(side="left", fill="x", expand=True)
        self.bluetooth_scan_button = ttk.Button(
            bluetooth_toolbar,
            text=app.tr("radio.scan"),
            command=self.scan_bluetooth,
            state="disabled",
        )
        self.bluetooth_scan_button.pack(side="right")
        bluetooth_tree_frame = ttk.Frame(self.bluetooth_panel, style="Panel.TFrame")
        bluetooth_tree_frame.pack(fill="both", expand=True)
        self.bluetooth_tree = ttk.Treeview(
            bluetooth_tree_frame,
            columns=("name", "status", "address"),
            show="headings",
            height=3 if app.compact else 5,
            selectmode="browse",
        )
        self.bluetooth_tree.heading("name", text=app.tr("common.device"))
        self.bluetooth_tree.heading("status", text=app.tr("common.status"))
        self.bluetooth_tree.heading("address", text=app.tr("radio.address"))
        self.bluetooth_tree.column("name", width=155 if app.compact else 260, anchor="w")
        self.bluetooth_tree.column("status", width=105, anchor="w")
        self.bluetooth_tree.column("address", width=135, anchor="w")
        if app.compact:
            self.bluetooth_tree.configure(displaycolumns=("name", "status"))
        bluetooth_scroll = ttk.Scrollbar(
            bluetooth_tree_frame,
            orient="vertical",
            command=self.bluetooth_tree.yview,
        )
        self.bluetooth_tree.configure(yscrollcommand=bluetooth_scroll.set)
        self.bluetooth_tree.pack(side="left", fill="both", expand=True)
        bluetooth_scroll.pack(side="right", fill="y")
        self.bluetooth_tree.bind(
            "<<TreeviewSelect>>",
            lambda _event: self._update_bluetooth_actions(),
        )
        bluetooth_primary = ttk.Frame(self.bluetooth_panel, style="Panel.TFrame")
        bluetooth_primary.pack(fill="x", pady=(5, 0))
        self.bluetooth_pair_button = ttk.Button(
            bluetooth_primary,
            text=app.tr("radio.pair"),
            command=lambda: self.bluetooth_device_action("pair"),
            state="disabled",
        )
        self.bluetooth_pair_button.pack(side="left", fill="x", expand=True)
        self.bluetooth_connect_button = ttk.Button(
            bluetooth_primary,
            text=app.tr("radio.connect"),
            command=lambda: self.bluetooth_device_action("connect"),
            state="disabled",
        )
        self.bluetooth_connect_button.pack(side="left", fill="x", expand=True, padx=(5, 0))
        bluetooth_secondary = bluetooth_primary
        if app.compact:
            bluetooth_secondary = ttk.Frame(self.bluetooth_panel, style="Panel.TFrame")
            bluetooth_secondary.pack(fill="x", pady=(5, 0))
        self.bluetooth_disconnect_button = ttk.Button(
            bluetooth_secondary,
            text=app.tr("radio.disconnect"),
            command=lambda: self.bluetooth_device_action("disconnect"),
            state="disabled",
        )
        self.bluetooth_disconnect_button.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 0) if app.compact else (5, 0),
        )
        self.bluetooth_forget_button = ttk.Button(
            bluetooth_secondary,
            text=app.tr("radio.forget"),
            command=lambda: self.bluetooth_device_action("forget"),
            state="disabled",
        )
        self.bluetooth_forget_button.pack(side="left", fill="x", expand=True, padx=(5, 0))
        self.bluetooth_notice = tk.StringVar(value=app.tr("radio.bluetooth_scan_hint"))
        ttk.Label(
            self.bluetooth_panel,
            textvariable=self.bluetooth_notice,
            style="Muted.TLabel",
            wraplength=276 if app.compact else 650,
            justify="left",
        ).pack(anchor="w", fill="x", pady=(4, 0))

        self.details = tk.Text(
            container,
            height=4,
            bg=FIELD_BG,
            fg=TEXT,
            relief="flat",
            padx=9,
            pady=7,
            wrap="word",
        )
        if not app.compact or self.domain == "bluetooth":
            self.details.pack(fill="both", expand=True, pady=(4, 0))
        self.details.configure(state="disabled")
        _replace_text(self.details, app.tr("radio.select_device"))

    def refresh(self) -> None:
        self._disable_controls()
        self.operation_notice.set("")
        if self.domain == "bluetooth":
            self._refresh_bluetooth_audio()
        self.app.run_task(
            self.app.tr("status.loading_radio", {"radio": self._radio_name}),
            lambda: self.app.model.hal_inventory(refresh=True),
            self._inventory_result,
        )

    def _inventory_result(self, result: OperationResult) -> bool:
        self.devices.clear()
        for item in self.device_tree.get_children():
            self.device_tree.delete(item)
        if not result.ok:
            self._show_provider_state(
                "missing",
                provider="",
                status=result.code or "unavailable",
                reason=result.message,
            )
            _replace_text(self.details, result.data or {"code": result.code, "message": result.message})
            return False
        try:
            view = radio_domain_view(result.data, self.domain)
        except (TypeError, ValueError) as exc:
            self._show_provider_state("unavailable", provider="", status="invalid", reason=str(exc))
            self.app.set_status(str(exc), error=True)
            return True
        self._domain_available = bool(view["available"])
        if not view["installed"]:
            self._show_provider_state("missing", provider="", status="unavailable", reason="")
        elif self.domain == "network" and view["reason"] == "no-wifi-device":
            self._show_provider_state(
                "no-wifi",
                provider=str(view["provider"]),
                status=str(view["status"]),
                reason=str(view["reason"]),
            )
        elif not view["available"]:
            self._show_provider_state(
                "unavailable",
                provider=str(view["provider"]),
                status=str(view["status"]),
                reason=str(view["reason"]),
            )
        else:
            self._show_provider_state(
                "ready",
                provider=str(view["provider"]),
                status=str(view["status"]),
                reason=str(view["reason"]),
            )
        devices = list(view["devices"])
        if self.domain == "network":
            devices = [
                item
                for item in devices
                if isinstance(item.get("metadata"), dict)
                and item["metadata"].get("kind") == "wifi"
            ]
            devices.sort(
                key=lambda item: (
                    0
                    if isinstance(item.get("metadata"), dict)
                    and item["metadata"].get("kind") == "wifi"
                    else 1,
                    str(item.get("id") or ""),
                )
            )
        elif self.domain == "bluetooth":
            devices.sort(
                key=lambda item: (
                    0 if "powered" in item.get("mutable", []) else 1,
                    str(item.get("id") or ""),
                )
            )
        for device in devices:
            identifier = str(device.get("id") or "")
            if not identifier:
                continue
            self.devices[identifier] = device
            metadata = device.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            self.device_tree.insert(
                "",
                "end",
                iid=identifier,
                values=(
                    str(device.get("name") or identifier),
                    str(metadata.get("kind") or device.get("kind") or self.domain),
                    self.app.tr("common.available")
                    if device.get("available", True)
                    else self.app.tr("common.unavailable"),
                ),
            )
        children = self.device_tree.get_children()
        if children:
            self.device_tree.selection_set(children[0])
            self.device_tree.focus(children[0])
            self.read_state()
        elif view["available"]:
            self.status_body.set(self.app.tr("radio.no_devices"))
        return bool(children)

    def _show_provider_state(
        self,
        kind: str,
        *,
        provider: str,
        status: str,
        reason: str,
    ) -> None:
        if kind == "missing":
            title = self.app.tr("radio.provider_missing.title", {"radio": self._radio_name})
            body = self.app.tr(
                "radio.provider_missing.body",
                {"radio": self._radio_name, "domain": self.domain},
            )
            color = ERROR_CONTAINER
        elif kind == "no-wifi":
            title = self.app.tr("radio.no_wifi_title")
            body = self.app.tr("radio.no_wifi_body")
            color = ERROR_CONTAINER
        elif kind == "unavailable":
            title = self.app.tr("radio.provider_unavailable.title", {"radio": self._radio_name})
            body = self.app.tr(
                "radio.provider_unavailable.body",
                {
                    "provider": provider or self.app.tr("common.unavailable"),
                    "status": status,
                    "reason": reason,
                },
            )
            color = ERROR_CONTAINER
        else:
            title = self.app.tr("radio.provider_ready.title", {"radio": self._radio_name})
            body = self.app.tr("radio.provider_ready.body", {"provider": provider})
            color = SUCCESS_CONTAINER
        self.status_title.set(title)
        self.status_body.set(body)
        self._set_status_card_color(color)

    def _set_status_card_color(self, color: str) -> None:
        self.status_card.set_color(color)

    def selected_device(self) -> str:
        selection = self.device_tree.selection()
        return str(selection[0]) if selection else ""

    def _selected(self, _event: Any = None) -> None:
        self.read_state()

    def read_state(self) -> None:
        device = self.selected_device()
        if not device:
            return
        self._state_generation += 1
        generation = self._state_generation
        self._disable_controls(keep_inventory=True)
        self.app.run_task(
            self.app.tr("status.reading_radio", {"radio": self._radio_name}),
            lambda: self.app.model.hal_get_state(device),
            lambda result: self._state_result(result, device, generation),
        )

    def _state_result(
        self,
        result: OperationResult,
        device: str,
        generation: int,
    ) -> bool:
        if generation != self._state_generation or device != self.selected_device():
            return True
        if not result.ok:
            self.status_body.set(
                self.app.tr("radio.state_unavailable", {"message": result.message or result.code})
            )
            _replace_text(self.details, result.data or {"code": result.code, "message": result.message})
            return False
        try:
            state = radio_state_summary(result.data)
        except (TypeError, ValueError) as exc:
            self.status_body.set(self.app.tr("radio.state_unavailable", {"message": str(exc)}))
            self.app.set_status(str(exc), error=True)
            return True
        self._loaded_device = device
        self._power_field = str(state["power_field"])
        self._mutable = list(state["mutable"])
        enabled = state["enabled"]
        if isinstance(enabled, bool):
            self.power.set(enabled)
            self._confirmed_power = enabled
        self._hard_blocked = state["values"].get("hard_blocked") is True
        self.power_toggle.configure(
            state="normal"
            if self._domain_available
            and state["available"]
            and state["can_set_enabled"]
            and not self._hard_blocked
            else "disabled"
        )
        state_message = self.app.tr(
            "radio.state_loaded",
            {"provider": str(state["provider"] or self.app.tr("common.provider"))},
        )
        if self.domain == "bluetooth":
            if self._hard_blocked:
                state_message = self.app.tr("radio.hard_blocked")
                self._set_status_card_color(ERROR_CONTAINER)
            else:
                self._set_status_card_color(SUCCESS_CONTAINER)
        elif self.domain == "network":
            wifi_control = str(state["values"].get("wifi_control") or "unavailable")
            if wifi_control == "degraded":
                state_message = self.app.tr("radio.wifi_control_degraded")
                self._set_status_card_color(ERROR_CONTAINER)
            elif wifi_control != "available":
                state_message = self.app.tr("radio.wifi_control_unavailable")
                self._set_status_card_color(ERROR_CONTAINER)
            else:
                self._set_status_card_color(SUCCESS_CONTAINER)
        if self._operation_error:
            state_message += " · " + self._operation_error
        self.status_body.set(state_message)
        self._apply_network_state(state["values"], state["mutable"])
        self._apply_bluetooth_state(state["values"], state["mutable"])
        persisted = state["values"].get("configuration_persisted")
        if isinstance(persisted, bool):
            self.operation_notice.set(
                self.app.tr(
                    "radio.persistence_saved"
                    if persisted
                    else "radio.persistence_runtime_only"
                )
            )
            self.operation_notice_label.configure(
                style="Success.TLabel" if persisted else "Error.TLabel"
            )
        _replace_text(self.details, state["values"])
        return False

    def _apply_network_state(self, values: dict[str, Any], mutable: list[str]) -> None:
        previous = self.selected_network()
        preferred_ssid = str(previous.get("ssid") or "") if previous else ""
        wifi_status = values.get("wifi_status", {})
        if isinstance(wifi_status, dict) and wifi_status.get("ssid"):
            preferred_ssid = str(wifi_status["ssid"])
        for item in self.network_tree.get_children():
            self.network_tree.delete(item)
        self._network_rows.clear()
        can_act = self.domain == "network" and "action" in mutable
        wifi_control = str(values.get("wifi_control") or "unavailable")
        enabled = self._domain_available and can_act and wifi_control == "available"
        self._network_actions_enabled = enabled
        self.scan_button.configure(state="normal" if enabled else "disabled")
        self.disconnect_button.configure(state="normal" if enabled else "disabled")
        preferred_item = ""
        for index, row in enumerate(wifi_network_rows(values)):
            item = f"network-{index}"
            self._network_rows[item] = row
            display_ssid = str(row["ssid"])
            if row.get("configured") is True:
                display_ssid += " · " + self.app.tr("radio.saved")
            signal = row.get("signal_dbm")
            self.network_tree.insert(
                "",
                "end",
                iid=item,
                values=(
                    display_ssid,
                    "" if signal is None else str(signal),
                    self.app.tr(
                        "radio.security_open"
                        if row.get("security") == "open"
                        else "radio.security_saved"
                        if row.get("security") == "saved"
                        else "radio.security_secured"
                    ),
                ),
            )
            if not preferred_item and row.get("ssid") == preferred_ssid:
                preferred_item = item
        if preferred_item:
            self.network_tree.selection_set(preferred_item)
            self.network_tree.focus(preferred_item)
        self._update_network_actions()

    def selected_network(self) -> dict[str, Any] | None:
        selection = self.network_tree.selection()
        return self._network_rows.get(str(selection[0])) if selection else None

    def _apply_bluetooth_state(self, values: dict[str, Any], mutable: list[str]) -> None:
        if self.domain != "bluetooth":
            return
        powered = values.get("powered")
        self._bluetooth_powered = powered if isinstance(powered, bool) else None
        self._update_bluetooth_actions()

    def _refresh_bluetooth_audio(self) -> None:
        if self.domain != "bluetooth" or self._bluetooth_audio_busy:
            return
        self._bluetooth_audio_busy = True
        self._update_bluetooth_actions()
        self.app.run_task(
            self.app.tr("status.loading_bluetooth_devices"),
            lambda: self.app.model.audio_devices(refresh=True),
            self._bluetooth_audio_result,
        )

    def _bluetooth_audio_result(self, result: OperationResult) -> bool:
        self._bluetooth_audio_busy = False
        if not result.ok:
            self._bluetooth_controller_registered = False
            self._replace_bluetooth_devices([])
            message = result.message or result.code or self.app.tr("common.unavailable")
            self.bluetooth_notice.set(
                self.app.tr("radio.bluetooth_audio_unavailable", {"reason": message})
            )
            self._update_bluetooth_actions()
            return True
        self._bluetooth_controller_registered = (
            result.data.get("controller_registered") is True
        )
        devices = result.data.get("devices", [])
        self._replace_bluetooth_devices(devices if isinstance(devices, list) else [])
        if not self._bluetooth_controller_registered:
            reason = str(result.data.get("reason") or "controller-not-registered")
            reason_key = (
                "radio.bluetooth_controller_not_registered"
                if reason == "controller-not-registered"
                else "radio.bluetooth_audio_stack_unavailable"
                if reason == "audio-stack-unavailable"
                else "radio.bluetooth_audio_unavailable"
            )
            self.bluetooth_notice.set(self.app.tr(reason_key, {"reason": reason}))
        elif self._bluetooth_powered is False:
            self.bluetooth_notice.set(self.app.tr("radio.bluetooth_power_to_scan"))
        elif self._bluetooth_rows:
            self.bluetooth_notice.set(
                self.app.tr("radio.bluetooth_found", {"count": len(self._bluetooth_rows)})
            )
        else:
            self.bluetooth_notice.set(self.app.tr("radio.bluetooth_scan_hint"))
        self._update_bluetooth_actions()
        return True

    def _replace_bluetooth_devices(self, devices: list[dict[str, Any]]) -> None:
        selected = self.selected_bluetooth_device()
        selected_address = str(selected.get("address") or "") if selected else ""
        for item in self.bluetooth_tree.get_children():
            self.bluetooth_tree.delete(item)
        self._bluetooth_rows.clear()
        preferred_item = ""
        for index, raw in enumerate(devices):
            if not isinstance(raw, dict) or not raw.get("address"):
                continue
            row = dict(raw)
            item = f"bluetooth-{index}"
            self._bluetooth_rows[item] = row
            status_key = (
                "common.connected"
                if row.get("connected") is True
                else "radio.paired"
                if row.get("paired") is True
                else "radio.not_paired"
            )
            self.bluetooth_tree.insert(
                "",
                "end",
                iid=item,
                values=(
                    str(row.get("name") or row["address"]),
                    self.app.tr(status_key),
                    str(row["address"]),
                ),
            )
            if str(row["address"]) == selected_address:
                preferred_item = item
        if preferred_item:
            self.bluetooth_tree.selection_set(preferred_item)
            self.bluetooth_tree.focus(preferred_item)

    def selected_bluetooth_device(self) -> dict[str, Any] | None:
        selection = self.bluetooth_tree.selection()
        return self._bluetooth_rows.get(str(selection[0])) if selection else None

    def _update_bluetooth_actions(self) -> None:
        if self.domain != "bluetooth":
            return
        row = self.selected_bluetooth_device()
        usable = (
            self._bluetooth_controller_registered
            and self._bluetooth_powered is not False
            and not self._bluetooth_audio_busy
        )
        paired = bool(row and row.get("paired") is True)
        connected = bool(row and row.get("connected") is True)
        self.bluetooth_scan_button.configure(state="normal" if usable else "disabled")
        self.bluetooth_pair_button.configure(
            state="normal" if usable and row and not paired else "disabled"
        )
        self.bluetooth_connect_button.configure(
            state="normal" if usable and row and paired and not connected else "disabled"
        )
        self.bluetooth_disconnect_button.configure(
            state="normal" if usable and row and connected else "disabled"
        )
        self.bluetooth_forget_button.configure(
            state="normal" if usable and row and paired else "disabled"
        )

    def scan_bluetooth(self) -> None:
        if (
            self.domain != "bluetooth"
            or not self._bluetooth_controller_registered
            or self._bluetooth_powered is False
            or self._bluetooth_audio_busy
        ):
            return
        self._bluetooth_audio_busy = True
        self.bluetooth_notice.set(self.app.tr("radio.bluetooth_scanning"))
        self._update_bluetooth_actions()
        self.app.run_task(
            self.app.tr("status.scanning_bluetooth"),
            lambda: self.app.model.audio_scan_devices(15000),
            lambda result: self._bluetooth_mutation_result(result, "scan"),
        )

    def bluetooth_device_action(self, action: str) -> None:
        row = self.selected_bluetooth_device()
        if (
            row is None
            or action not in {"pair", "connect", "disconnect", "forget"}
            or not self._bluetooth_controller_registered
            or self._bluetooth_powered is False
            or self._bluetooth_audio_busy
        ):
            return
        address = str(row.get("address") or "")
        if action == "forget" and not messagebox.askyesno(
            self.app.tr("radio.bluetooth_forget_title"),
            self.app.tr(
                "radio.bluetooth_forget_prompt",
                {"device": str(row.get("name") or address)},
            ),
            icon="warning",
            default=messagebox.NO,
            parent=self.app.root,
        ):
            return
        self._bluetooth_audio_busy = True
        self.bluetooth_notice.set(
            self.app.tr(
                "radio.bluetooth_action_running",
                {"action": self.app.tr(f"radio.{action}")},
            )
        )
        self._update_bluetooth_actions()
        self.app.run_task(
            self.app.tr(
                "status.bluetooth_action",
                {"action": self.app.tr(f"radio.{action}")},
            ),
            lambda: self.app.model.audio_device_action(action, address),
            lambda result: self._bluetooth_mutation_result(result, action),
        )

    def _bluetooth_mutation_result(
        self,
        result: OperationResult,
        action: str,
    ) -> bool:
        self._bluetooth_audio_busy = False
        if result.ok:
            devices = result.data.get("devices", [])
            self._replace_bluetooth_devices(devices if isinstance(devices, list) else [])
            message_key = (
                "radio.bluetooth_no_devices"
                if action == "scan" and not self._bluetooth_rows
                else "radio.bluetooth_scan_complete"
                if action == "scan"
                else "radio.bluetooth_action_complete"
            )
            self.bluetooth_notice.set(
                self.app.tr(
                    message_key,
                    {
                        "count": len(self._bluetooth_rows),
                        "action": self.app.tr(f"radio.{action}"),
                    },
                )
            )
        else:
            message = result.message or result.code or self.app.tr("common.operation_failed")
            if result.code == "AUDIO_UNAVAILABLE":
                self._bluetooth_controller_registered = False
            self.bluetooth_notice.set(
                self.app.tr(
                    "radio.bluetooth_action_failed",
                    {
                        "action": self.app.tr(f"radio.{action}"),
                        "message": message,
                    },
                )
            )
            self.app.set_status(message, error=True)
        self._update_bluetooth_actions()
        return True

    def _update_network_actions(self) -> None:
        row = self.selected_network()
        configured = bool(row and row.get("configured") is True)
        open_network = bool(row and row.get("security") == "open")
        password = self.password.get()
        if (configured or open_network) and password:
            self.password.set("")
            password = ""
        password_ready = configured or open_network or bool(password)
        can_connect = bool(row) and self._network_actions_enabled and password_ready
        _configure_if_changed(
            self.connect_button,
            state="normal" if can_connect else "disabled",
        )
        can_forget = bool(
            row
            and configured
            and isinstance(row.get("network_id"), int)
            and not isinstance(row.get("network_id"), bool)
        )
        _configure_if_changed(
            self.forget_button,
            state="normal" if self._network_actions_enabled and can_forget else "disabled"
        )
        _configure_if_changed(
            self.password_entry,
            state="normal"
            if self._network_actions_enabled and row and not configured and not open_network
            else "disabled"
        )

    def apply_power(self) -> None:
        if not self._loaded_device or not self._power_field:
            return
        requested = bool(self.power.get())
        if requested and self._hard_blocked:
            if self._confirmed_power is not None:
                self.power.set(self._confirmed_power)
            self.status_body.set(self.app.tr("radio.hard_blocked"))
            self.app.set_status(self.app.tr("radio.hard_blocked"), error=True)
            return
        self._apply_changes(
            {self._power_field: requested},
            action="power",
        )

    def apply_action(self, action: str) -> None:
        if not self._loaded_device or "action" not in self._mutable:
            return
        self._apply_changes({"action": action}, action=action)

    def connect_network(self) -> None:
        row = self.selected_network()
        if row is None or not self._loaded_device:
            return
        password = self.password.get()
        try:
            changes = wifi_connect_changes(row, password)
        except ValueError as exc:
            key = (
                "radio.password_invalid"
                if str(exc) == "password-invalid"
                else "radio.password_required"
            )
            message = self.app.tr(key)
            self.operation_notice.set(message)
            self.operation_notice_label.configure(style="Error.TLabel")
            self.app.set_status(message, error=True)
            return
        self.password.set("")
        self._apply_changes(changes, action="connect")

    def forget_network(self) -> None:
        row = self.selected_network()
        if row is None or not self._loaded_device:
            return
        try:
            changes = wifi_forget_changes(row)
        except ValueError:
            return
        ssid = str(row.get("ssid") or "")
        if not messagebox.askyesno(
            self.app.tr("radio.forget_title"),
            self.app.tr("radio.forget_prompt", {"ssid": ssid}),
            icon="warning",
            default=messagebox.NO,
            parent=self.app.root,
        ):
            return
        self._apply_changes(changes, action="forget")

    def _apply_changes(self, changes: dict[str, Any], *, action: str) -> None:
        device = self._loaded_device
        self._state_generation += 1
        generation = self._state_generation
        self._disable_controls(keep_inventory=True)
        self.operation_notice.set("")
        self._operation_error = ""
        self.app.run_task(
            self.app.tr("status.applying_radio", {"radio": self._radio_name}),
            lambda: self.app.model.hal_set_state(device, changes),
            lambda result: self._change_result(
                result,
                device,
                generation,
                action,
            ),
        )

    def _change_result(
        self,
        result: OperationResult,
        device: str,
        generation: int,
        action: str,
    ) -> bool:
        if generation != self._state_generation or device != self.selected_device():
            return True
        handled = self._state_result(result, device, generation)
        if result.ok:
            if self.domain == "bluetooth" and action == "power":
                self._refresh_bluetooth_audio()
            if action == "scan":
                self.operation_notice.set(self.app.tr("radio.scan_refreshing"))
                self.operation_notice_label.configure(style="Muted.TLabel")
                page_key = self._page_key()
                self.app.root.after(
                    1200,
                    lambda: self._delayed_scan_refresh(
                        device,
                        generation,
                        page_key,
                    ),
                )
            return handled
        if action == "power" and self._confirmed_power is not None:
            self.power.set(self._confirmed_power)
        message = result.message or result.code or self.app.tr("common.operation_failed")
        self._operation_error = self.app.tr(
            "radio.apply_failed",
            {"radio": self._radio_name, "message": message},
        )
        self.operation_notice.set(self._operation_error)
        self.operation_notice_label.configure(style="Error.TLabel")
        self.app.set_status(message, error=True)
        self.app.root.after(
            0,
            lambda: self._recover_after_write_failure(device, generation),
        )
        return True

    def _page_key(self) -> str:
        return "wifi" if self.domain == "network" else "bluetooth"

    def _delayed_scan_refresh(
        self,
        device: str,
        generation: int,
        page_key: str,
    ) -> None:
        if (
            self.app._closed
            or generation != self._state_generation
            or device != self.selected_device()
            or page_key != self._page_key()
            or self.app._active_page != page_key
        ):
            return
        self.operation_notice.set("")
        self.read_state()

    def _recover_after_write_failure(self, device: str, generation: int) -> None:
        if (
            self.app._closed
            or generation != self._state_generation
            or device != self.selected_device()
        ):
            return
        self.read_state()

    def _disable_controls(self, *, keep_inventory: bool = False) -> None:
        self.power_toggle.configure(state="disabled")
        self.scan_button.configure(state="disabled")
        self.disconnect_button.configure(state="disabled")
        self.connect_button.configure(state="disabled")
        self.forget_button.configure(state="disabled")
        self.password_entry.configure(state="disabled")
        self.bluetooth_scan_button.configure(state="disabled")
        self.bluetooth_pair_button.configure(state="disabled")
        self.bluetooth_connect_button.configure(state="disabled")
        self.bluetooth_disconnect_button.configure(state="disabled")
        self.bluetooth_forget_button.configure(state="disabled")
        self._network_actions_enabled = False
        if not keep_inventory:
            self._loaded_device = ""
            self._power_field = ""
            self._mutable = []
            self._domain_available = False
            self._bluetooth_powered = None
            self._confirmed_power = None
            self._hard_blocked = False
            self._operation_error = ""

    def manage_hal(self) -> None:
        page = self.app._pages.get("hal")
        if isinstance(page, HalPage):
            page.focus_domain(self.domain)
            self.app.show_page("hal")

    def external_change(self, payload: dict[str, Any]) -> None:
        if str(payload.get("domain") or "") != self.domain:
            return
        page_key = self._page_key()
        if self.app._active_page == page_key:
            self.refresh()
        else:
            self._loaded = False
            self.app.set_status(
                self.app.tr("status.radio_changed", {"radio": self._radio_name})
            )


class WifiPage(RadioPage):
    domain = "network"
    title_key = "radio.wifi.title"
    note_key = "radio.wifi.note"


class BluetoothPage(RadioPage):
    domain = "bluetooth"
    title_key = "radio.bluetooth.title"
    note_key = "radio.bluetooth.note"

    def external_audio_change(self) -> None:
        if self.app._active_page == "bluetooth":
            self._refresh_bluetooth_audio()
        else:
            self._loaded = False


class AudioPage(BasePage):
    """Role-backed audio controls; Bluetooth pairing stays on BluetoothPage."""

    title_key = "audio.title"
    note_key = "audio.note"

    def __init__(self, parent: ttk.Frame, app: SettingsApplication) -> None:
        super().__init__(parent, app)
        self.state: dict[str, Any] = {}
        self.outputs: dict[str, dict[str, Any]] = {}
        self.surface = ScrollableSurface(self, background=PANEL)
        self.surface.pack(fill="both", expand=True)
        container = self.surface.content

        self.status_title = tk.StringVar(value=app.tr("common.loading"))
        self.status_body = tk.StringVar(value=app.tr("audio.not_loaded"))
        self.status_card = MaterialStatusCard(
            container,
            title=self.status_title,
            body=self.status_body,
            compact=app.compact,
        )
        self.status_card.pack(fill="x", pady=(0, 8))

        toolbar = ttk.Frame(container, style="Panel.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(
            toolbar,
            text=app.tr("common.refresh"),
            command=self.refresh,
        ).pack(side="left")
        ttk.Button(
            toolbar,
            text=app.tr("audio.manage_bluetooth"),
            command=lambda: app.show_page("bluetooth"),
        ).pack(side="left", padx=(6, 0))

        stack_card = tk.Frame(
            container,
            background=PANEL_ALT,
            highlightbackground=OUTLINE,
            highlightthickness=1,
            padx=10,
            pady=9,
        )
        stack_card.pack(fill="x", pady=(0, 8))
        tk.Label(
            stack_card,
            text=app.tr("audio.stack"),
            background=PANEL_ALT,
            foreground=TEXT,
            font=font_spec(stack_card, 10, "bold"),
            anchor="w",
        ).pack(fill="x")
        self.stack_summary = tk.StringVar(value=app.tr("audio.stack_not_loaded"))
        self.stack_label = tk.Label(
            stack_card,
            textvariable=self.stack_summary,
            background=PANEL_ALT,
            foreground=MUTED,
            anchor="w",
            justify="left",
            wraplength=276 if app.compact else 650,
        )
        self.stack_label.pack(fill="x", pady=(4, 0))
        self.stack_label.bind(
            "<Configure>",
            lambda event: self.stack_label.configure(
                wraplength=text_wrap_length(int(event.width), horizontal_padding=4)
            ),
        )

        ttk.Label(
            container,
            text=app.tr("audio.outputs"),
            style="Panel.TLabel",
        ).pack(anchor="w", pady=(0, 4))
        output_frame = ttk.Frame(container, style="Panel.TFrame")
        output_frame.pack(fill="x")
        self.output_tree = ttk.Treeview(
            output_frame,
            columns=("name", "volume", "status"),
            show="headings",
            height=3 if app.compact else 5,
            selectmode="browse",
        )
        self.output_tree.heading("name", text=app.tr("audio.output"))
        self.output_tree.heading("volume", text=app.tr("audio.volume"))
        self.output_tree.heading("status", text=app.tr("common.status"))
        self.output_tree.column("name", width=175 if app.compact else 350, anchor="w")
        self.output_tree.column("volume", width=70, anchor="center")
        self.output_tree.column("status", width=120, anchor="w")
        if app.compact:
            self.output_tree.configure(displaycolumns=("name", "volume"))
        output_scroll = ttk.Scrollbar(
            output_frame,
            orient="vertical",
            command=self.output_tree.yview,
        )
        self.output_tree.configure(yscrollcommand=output_scroll.set)
        self.output_tree.pack(side="left", fill="x", expand=True)
        output_scroll.pack(side="right", fill="y")
        self.output_tree.bind("<<TreeviewSelect>>", self._selected_output)
        self.output_notice = tk.StringVar(value=app.tr("audio.no_outputs"))
        self.output_notice_label = ttk.Label(
            container,
            textvariable=self.output_notice,
            style="Muted.TLabel",
            justify="left",
            wraplength=276 if app.compact else 650,
        )
        self.output_notice_label.pack(anchor="w", fill="x", pady=(4, 6))
        self.output_notice_label.bind(
            "<Configure>",
            lambda event: self.output_notice_label.configure(
                wraplength=text_wrap_length(int(event.width), horizontal_padding=4)
            ),
        )

        output_actions = ttk.Frame(container, style="Panel.TFrame")
        output_actions.pack(fill="x", pady=(0, 8))
        self.select_button = ttk.Button(
            output_actions,
            text=app.tr("audio.use_output"),
            command=self.select_output,
            state="disabled",
        )
        self.select_button.pack(fill="x" if app.compact else "none", side="top" if app.compact else "left")

        volume_card = tk.Frame(
            container,
            background=PANEL_ALT,
            highlightbackground=OUTLINE,
            highlightthickness=1,
            padx=10,
            pady=9,
        )
        volume_card.pack(fill="x", pady=(0, 8))
        tk.Label(
            volume_card,
            text=app.tr("audio.volume_and_mute"),
            background=PANEL_ALT,
            foreground=TEXT,
            font=font_spec(volume_card, 10, "bold"),
            anchor="w",
        ).pack(fill="x")
        self.volume_text = tk.StringVar(value=app.tr("common.unavailable"))
        tk.Label(
            volume_card,
            textvariable=self.volume_text,
            background=PANEL_ALT,
            foreground=MUTED,
            anchor="w",
        ).pack(fill="x", pady=(3, 5))
        volume_actions = ttk.Frame(volume_card, style="Panel.TFrame")
        volume_actions.pack(fill="x")
        self.volume_down = ttk.Button(
            volume_actions,
            text=app.tr("audio.volume_down"),
            command=lambda: self.adjust_volume(-10),
            state="disabled",
        )
        self.volume_down.pack(side="left", fill="x", expand=app.compact)
        self.volume_up = ttk.Button(
            volume_actions,
            text=app.tr("audio.volume_up"),
            command=lambda: self.adjust_volume(10),
            state="disabled",
        )
        self.volume_up.pack(side="left", fill="x", expand=app.compact, padx=(6, 0))
        mute_actions = volume_actions
        if app.compact:
            mute_actions = ttk.Frame(volume_card, style="Panel.TFrame")
            mute_actions.pack(fill="x", pady=(6, 0))
        self.muted = tk.BooleanVar(value=False)
        self.mute_button = ttk.Checkbutton(
            mute_actions,
            text=app.tr("audio.muted"),
            variable=self.muted,
            command=self.apply_muted,
            state="disabled",
        )
        self.mute_button.pack(
            side="left",
            fill="x" if app.compact else "none",
            padx=(0 if app.compact else 6, 0),
        )

        player_card = tk.Frame(
            container,
            background=PANEL_ALT,
            highlightbackground=OUTLINE,
            highlightthickness=1,
            padx=10,
            pady=9,
        )
        player_card.pack(fill="x", pady=(0, 8))
        tk.Label(
            player_card,
            text=app.tr("audio.player"),
            background=PANEL_ALT,
            foreground=TEXT,
            font=font_spec(player_card, 10, "bold"),
            anchor="w",
        ).pack(fill="x")
        self.player_status = tk.StringVar(value=app.tr("audio.player_not_loaded"))
        player_status_label = tk.Label(
            player_card,
            textvariable=self.player_status,
            background=PANEL_ALT,
            foreground=MUTED,
            anchor="w",
            justify="left",
            wraplength=276 if app.compact else 650,
        )
        player_status_label.pack(fill="x", pady=(3, 5))
        player_status_label.bind(
            "<Configure>",
            lambda event: player_status_label.configure(
                wraplength=text_wrap_length(int(event.width), horizontal_padding=4)
            ),
        )
        self.player_enabled = tk.BooleanVar(value=False)
        self.player_toggle = ttk.Checkbutton(
            player_card,
            text=app.tr("audio.player_enabled"),
            variable=self.player_enabled,
        )
        self.player_toggle.pack(anchor="w")
        self.player_server = tk.StringVar()
        self.player_name = tk.StringVar(value="MSYS Audio")
        self._entry_row(
            player_card,
            app.tr("audio.player_server"),
            self.player_server,
        )
        self._entry_row(
            player_card,
            app.tr("audio.player_name"),
            self.player_name,
        )
        self.player_apply = ttk.Button(
            player_card,
            text=app.tr("audio.save_player"),
            command=self.configure_player,
            state="disabled",
        )
        self.player_apply.pack(fill="x" if app.compact else "none", anchor="w", pady=(7, 0))

    def _entry_row(
        self,
        parent: tk.Frame,
        label: str,
        variable: tk.StringVar,
    ) -> None:
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill="x", pady=(4, 0))
        ttk.Label(row, text=label, style="Muted.TLabel").pack(
            anchor="w",
            side="top" if self.app.compact else "left",
        )
        ttk.Entry(row, textvariable=variable).pack(
            side="top" if self.app.compact else "left",
            fill="x",
            expand=True,
            padx=(0, 0) if self.app.compact else (8, 0),
            pady=(2, 0) if self.app.compact else 0,
        )

    def refresh(self) -> None:
        self._disable_output_controls()
        self.player_apply.configure(state="disabled")
        self.app.run_task(
            self.app.tr("status.loading_audio"),
            lambda: self.app.model.audio_state(refresh=True),
            self._state_result,
        )

    def _state_result(self, result: OperationResult) -> bool:
        if not result.ok:
            self.state = {}
            self.outputs.clear()
            self._clear_outputs()
            self.status_title.set(self.app.tr("audio.unavailable"))
            self.status_body.set(result.message or result.code or self.app.tr("audio.unavailable"))
            self.status_card.set_color(ERROR_CONTAINER)
            self.stack_summary.set(self.app.tr("audio.stack_unavailable"))
            self.output_notice.set(self.app.tr("audio.no_outputs"))
            self.player_status.set(self.app.tr("audio.player_unavailable"))
            self._disable_output_controls()
            self.player_apply.configure(state="disabled")
            self.app.set_status(
                result.message or result.code or self.app.tr("audio.unavailable"),
                error=True,
            )
            return True

        self.state = result.data
        reason = str(result.data.get("reason") or "")
        reason_key = {
            "audio-stack-unavailable": "audio.reason_stack",
            "controller-not-registered": "audio.reason_controller",
            "no-connected-a2dp-output": "audio.reason_no_output",
        }.get(reason)
        reason_text = self.app.tr(reason_key) if reason_key else reason
        available = result.data.get("available") is True
        self.status_title.set(
            self.app.tr("audio.ready" if available else "audio.unavailable")
        )
        self.status_body.set(
            self.app.tr(
                "audio.status_ready" if available else "audio.status_unavailable",
                {
                    "backend": str(result.data.get("backend") or ""),
                    "reason": reason_text or self.app.tr("common.unavailable"),
                },
            )
        )
        self.status_card.set_color(SUCCESS_CONTAINER if available else ERROR_CONTAINER)
        self._render_stack(result.data.get("stack", []))
        self._render_outputs(result.data.get("outputs", []))
        player = result.data.get("player", {})
        self.player_enabled.set(player.get("enabled") is True)
        self.player_server.set(str(player.get("server") or ""))
        self.player_name.set(str(player.get("name") or "MSYS Audio"))
        self.player_status.set(
            self.app.tr(
                "audio.player_status",
                {
                    "enabled": self.app.tr(
                        "common.enabled" if player.get("enabled") else "common.disabled"
                    ),
                    "running": self.app.tr(
                        "audio.running" if player.get("running") else "audio.stopped"
                    ),
                },
            )
        )
        self.player_apply.configure(state="normal")
        self.app.set_status(self.app.tr("common.ready"))
        return True

    def _render_stack(self, rows: object) -> None:
        stack = rows if isinstance(rows, list) else []
        if not stack:
            self.stack_summary.set(self.app.tr("audio.stack_unavailable"))
            return
        rendered = []
        for row in stack:
            if not isinstance(row, dict):
                continue
            status = self.app.tr(
                "audio.running" if row.get("running") else "audio.stopped"
            )
            if row.get("returncode") is not None:
                status += " · " + self.app.tr(
                    "audio.returncode", {"code": int(row["returncode"])}
                )
            rendered.append(f"{row.get('name', '')}: {status}")
        self.stack_summary.set("\n".join(rendered))

    def _clear_outputs(self) -> None:
        for item in self.output_tree.get_children():
            self.output_tree.delete(item)

    def _render_outputs(self, rows: object) -> None:
        self._clear_outputs()
        self.outputs.clear()
        outputs = rows if isinstance(rows, list) else []
        active = str(self.state.get("active_output") or "")
        selected = ""
        for row in outputs:
            if not isinstance(row, dict):
                continue
            identifier = str(row.get("id") or "")
            if not identifier:
                continue
            self.outputs[identifier] = row
            volume = row.get("volume_percent")
            volume_text = "—" if volume is None else f"{volume}%"
            status = self.app.tr(
                "audio.active" if identifier == active else "common.connected"
            )
            self.output_tree.insert(
                "",
                "end",
                iid=identifier,
                values=(str(row.get("name") or identifier), volume_text, status),
            )
            if identifier == active:
                selected = identifier
        if not selected and self.outputs:
            selected = next(iter(self.outputs))
        if selected:
            self.output_tree.selection_set(selected)
            self.output_tree.focus(selected)
            self.output_notice.set(self.app.tr("audio.select_hint"))
        else:
            self.output_notice.set(self.app.tr("audio.no_outputs"))
        self._update_output_controls()

    def selected_output(self) -> tuple[str, dict[str, Any] | None]:
        selection = self.output_tree.selection()
        identifier = str(selection[0]) if selection else ""
        return identifier, self.outputs.get(identifier)

    def _selected_output(self, _event: Any = None) -> None:
        self._update_output_controls()

    def _disable_output_controls(self) -> None:
        self.select_button.configure(state="disabled")
        self.volume_down.configure(state="disabled")
        self.volume_up.configure(state="disabled")
        self.mute_button.configure(state="disabled")

    def _update_output_controls(self) -> None:
        identifier, output = self.selected_output()
        if output is None:
            self.volume_text.set(self.app.tr("common.unavailable"))
            self._disable_output_controls()
            return
        active = identifier == str(self.state.get("active_output") or "")
        volume = output.get("volume_percent")
        muted = output.get("muted")
        mixer = bool(output.get("mixer_control"))
        volume_label = (
            f"{int(volume)}%"
            if isinstance(volume, int)
            else self.app.tr("common.unavailable")
        )
        mute_label = (
            self.app.tr("audio.muted" if muted else "audio.unmuted")
            if isinstance(muted, bool)
            else self.app.tr("common.unavailable")
        )
        self.volume_text.set(
            self.app.tr(
                "audio.volume_value",
                {
                    "volume": volume_label,
                    "mute": mute_label,
                },
            )
        )
        if isinstance(muted, bool):
            self.muted.set(muted)
        self.select_button.configure(state="disabled" if active else "normal")
        volume_state = "normal" if mixer and isinstance(volume, int) else "disabled"
        self.volume_down.configure(state=volume_state)
        self.volume_up.configure(state=volume_state)
        self.mute_button.configure(
            state="normal" if mixer and isinstance(muted, bool) else "disabled"
        )

    def _run_state_change(
        self,
        label: str,
        operation: Callable[[], OperationResult],
    ) -> None:
        self._disable_output_controls()
        self.player_apply.configure(state="disabled")
        self.app.run_task(label, operation, self._state_result)

    def select_output(self) -> None:
        identifier, _output = self.selected_output()
        if not identifier:
            return
        self._run_state_change(
            self.app.tr("status.selecting_audio_output"),
            lambda: self.app.model.audio_select_output(identifier),
        )

    def adjust_volume(self, delta: int) -> None:
        identifier, output = self.selected_output()
        if output is None or not isinstance(output.get("volume_percent"), int):
            return
        percent = max(0, min(100, int(output["volume_percent"]) + delta))
        self._run_state_change(
            self.app.tr("status.setting_audio_volume"),
            lambda: self.app.model.audio_set_volume(percent, identifier),
        )

    def apply_muted(self) -> None:
        identifier, output = self.selected_output()
        if output is None:
            return
        requested = bool(self.muted.get())
        self._run_state_change(
            self.app.tr("status.setting_audio_mute"),
            lambda: self.app.model.audio_set_muted(requested, identifier),
        )

    def configure_player(self) -> None:
        enabled = bool(self.player_enabled.get())
        server = self.player_server.get().strip()
        name = self.player_name.get().strip()
        self._run_state_change(
            self.app.tr("status.saving_audio_player"),
            lambda: self.app.model.audio_configure_player(enabled, server, name),
        )

    def external_change(self) -> None:
        if self.app._active_page == "audio":
            self.refresh()
        else:
            self._loaded = False


class LayoutPage(BasePage):
    title_key = "display.title"
    note_key = "display.note"

    def __init__(self, parent: ttk.Frame, app: SettingsApplication) -> None:
        super().__init__(parent, app)
        surface = ScrollableSurface(self, background=PANEL)
        surface.pack(fill="both", expand=True)
        container = surface.content
        self.display_summary = tk.StringVar(value=app.tr("common.not_loaded"))
        ttk.Label(
            container,
            textvariable=self.display_summary,
            style="Muted.TLabel",
        ).pack(anchor="w", fill="x", pady=(0, 6))
        logical_card = tk.Frame(
            container,
            background=PANEL_ALT,
            highlightbackground=OUTLINE,
            highlightthickness=1,
            padx=10,
            pady=9,
        )
        logical_card.pack(fill="x", pady=(0, 8))
        tk.Label(
            logical_card,
            text=app.tr("display.logical_layout"),
            background=PANEL_ALT,
            foreground=TEXT,
            anchor="w",
            font=font_spec(logical_card, 11, "bold"),
        ).pack(fill="x")
        tk.Label(
            logical_card,
            text=app.tr("display.logical_layout_note"),
            background=PANEL_ALT,
            foreground=MUTED,
            anchor="w",
            justify="left",
            wraplength=276 if app.compact else 650,
        ).pack(fill="x", pady=(2, 7))
        form = ttk.Frame(logical_card, style="Panel.TFrame")
        form.pack(fill="x", pady=(0, 8))
        self._profile_labels = _localized_choice_labels(
            app,
            LAYOUT_PROFILES,
            DISPLAY_PROFILE_LABEL_KEYS,
        )
        self._orientation_labels = _localized_choice_labels(
            app,
            ORIENTATIONS,
            ORIENTATION_LABEL_KEYS,
        )
        self.profile = tk.StringVar(value=self._profile_labels["mobile"])
        self.orientation = tk.StringVar(value=self._orientation_labels["auto"])
        self.insets = tk.StringVar(value="auto")
        fields = (
            (app.tr("display.profile"), ttk.Combobox(
                form,
                textvariable=self.profile,
                values=tuple(self._profile_labels[value] for value in LAYOUT_PROFILES),
                state="readonly",
                width=14,
            )),
            (app.tr("display.orientation"), ttk.Combobox(
                form,
                textvariable=self.orientation,
                values=tuple(
                    self._orientation_labels[value] for value in ORIENTATIONS
                ),
                state="readonly",
                width=14,
            )),
            (app.tr("display.insets"), ttk.Entry(form, textvariable=self.insets, width=24)),
        )
        if app.compact:
            for row, (label, control) in enumerate(fields):
                self._compact_field(form, label, control, row * 2)
        else:
            for column, (label, control) in enumerate(fields):
                self._field(form, label, control, column)
        actions = ttk.Frame(logical_card, style="Panel.TFrame")
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text=app.tr("common.refresh"), command=self.refresh).pack(side="left")
        self.apply_button = ttk.Button(
            actions,
            text=app.tr("display.apply"),
            style="Accent.TButton",
            command=self.apply,
            state="disabled",
        )
        self.apply_button.pack(
            side="left", padx=8
        )
        secondary_actions = actions
        if app.compact:
            secondary_actions = ttk.Frame(logical_card, style="Panel.TFrame")
            secondary_actions.pack(fill="x", pady=(0, 8))
        self.output_button = ttk.Button(
            secondary_actions,
            text=app.tr("display.outputs"),
            command=self.manage_output,
            state="disabled",
        )
        self.output_button.pack(side="left")
        self.hal_button = ttk.Button(
            secondary_actions,
            text=app.tr("display.hal"),
            command=self.manage_hal,
            state="disabled",
        )
        self.hal_button.pack(side="left", padx=(6, 0))

        self._physical_labels = _localized_choice_labels(
            app,
            PHYSICAL_ROTATIONS,
            PHYSICAL_ROTATION_LABEL_KEYS,
        )
        self.physical_device = ""
        self.physical_rotation = tk.StringVar(
            value=self._physical_labels["normal"]
        )
        self.physical_status = tk.StringVar(
            value=app.tr("display.physical_loading")
        )
        physical_card = tk.Frame(
            container,
            background=PANEL_ALT,
            highlightbackground=OUTLINE,
            highlightthickness=1,
            padx=10,
            pady=9,
        )
        physical_card.pack(fill="x", pady=(0, 8))
        tk.Label(
            physical_card,
            text=app.tr("display.physical_rotation"),
            background=PANEL_ALT,
            foreground=TEXT,
            anchor="w",
            font=font_spec(physical_card, 11, "bold"),
        ).pack(fill="x")
        tk.Label(
            physical_card,
            text=app.tr("display.physical_note"),
            background=PANEL_ALT,
            foreground=MUTED,
            anchor="w",
            justify="left",
            wraplength=276 if app.compact else 650,
        ).pack(fill="x", pady=(2, 7))
        physical_controls = ttk.Frame(physical_card, style="Panel.TFrame")
        physical_controls.pack(fill="x")
        self.physical_combo = ttk.Combobox(
            physical_controls,
            textvariable=self.physical_rotation,
            values=tuple(
                self._physical_labels[value] for value in PHYSICAL_ROTATIONS
            ),
            state="disabled",
            width=18,
        )
        self.physical_combo.pack(side="left", fill="x", expand=True)
        self.physical_apply = ttk.Button(
            physical_controls,
            text=app.tr("common.apply"),
            command=self.apply_physical_rotation,
            state="disabled",
        )
        self.physical_apply.pack(side="left", padx=(6, 0))
        tk.Label(
            physical_card,
            textvariable=self.physical_status,
            background=PANEL_ALT,
            foreground=MUTED,
            anchor="w",
            justify="left",
            wraplength=276 if app.compact else 650,
        ).pack(fill="x", pady=(5, 0))

        self._debug_loaded = False
        self._debug_busy = False
        self._confirmed_debug_enabled = False
        self._overlay_available = False
        self._cursor_available = False
        self._confirmed_cursor_enabled = False
        self._confirmed_debug_overlay: dict[str, Any] = {
            **DEFAULT_CH347_DEBUG_OVERLAY,
            "items": list(DEFAULT_CH347_DEBUG_OVERLAY["items"]),
        }
        debug_card = tk.Frame(
            container,
            background=PANEL_ALT,
            highlightbackground=OUTLINE,
            highlightthickness=1,
            padx=10,
            pady=9,
        )
        debug_card.pack(fill="x", pady=(0, 8))
        tk.Label(
            debug_card,
            text=app.tr("display.debug_title"),
            background=PANEL_ALT,
            foreground=TEXT,
            anchor="w",
            font=font_spec(debug_card, 11, "bold"),
        ).pack(fill="x")
        tk.Label(
            debug_card,
            text=app.tr("display.debug_note"),
            background=PANEL_ALT,
            foreground=MUTED,
            anchor="w",
            justify="left",
            wraplength=276 if app.compact else 650,
        ).pack(fill="x", pady=(2, 7))

        self.debug_enabled = tk.BooleanVar(value=False)
        self.debug_cursor_enabled = tk.BooleanVar(value=False)
        self.debug_overlay_enabled = tk.BooleanVar(value=False)
        self.debug_overlay_alpha = tk.StringVar(value="176")
        self.debug_overlay_scale = tk.StringVar(value="1")
        self.debug_overlay_interval = tk.StringVar(value="1000")
        self.debug_overlay_items = {
            item: tk.BooleanVar(
                value=item in set(DEFAULT_CH347_DEBUG_OVERLAY["items"])
            )
            for item in CH347_DEBUG_OVERLAY_ITEMS
        }
        self.debug_fps = tk.StringVar()
        self.debug_idle_fps = tk.StringVar()
        self.debug_max_fps = tk.StringVar(value=app.tr("common.not_loaded"))
        self.debug_observed = tk.StringVar(value=app.tr("common.not_loaded"))
        self.debug_generation = tk.StringVar(value=app.tr("common.not_loaded"))
        self.debug_application = tk.StringVar(value=app.tr("common.not_loaded"))
        self.debug_dirty_frames = tk.StringVar(value=app.tr("common.not_loaded"))
        self.debug_dirty_refreshes = tk.StringVar(value=app.tr("common.not_loaded"))
        self.debug_dirty_pixels = tk.StringVar(value=app.tr("common.not_loaded"))
        self.debug_feedback = tk.StringVar(value=app.tr("display.debug_loading"))
        self.debug_inputs: list[tk.Widget] = []
        self.debug_overlay_inputs: list[tk.Widget] = []
        self.debug_cursor_inputs: list[tk.Widget] = []

        debug_form = ttk.Frame(debug_card, style="Panel.TFrame")
        debug_form.pack(fill="x")
        for row, (label_key, variable, start, end) in enumerate((
            ("display.debug_target_fps", self.debug_fps, 1, 240),
            ("display.debug_idle_fps", self.debug_idle_fps, 0, 60),
        )):
            ttk.Label(debug_form, text=app.tr(label_key)).grid(
                row=row,
                column=0,
                sticky="w",
                pady=3,
            )
            control = ttk.Spinbox(
                debug_form,
                from_=start,
                to=end,
                textvariable=variable,
                width=8,
                state="disabled",
            )
            control.grid(row=row, column=1, sticky="e", padx=(8, 0), pady=3)
            self.debug_inputs.append(control)
        for row, (label_key, variable) in enumerate((
            ("display.debug_capture_limit", self.debug_max_fps),
            ("display.debug_observed_fps", self.debug_observed),
            ("display.debug_generation", self.debug_generation),
            ("display.debug_application", self.debug_application),
            ("display.debug_dirty_frames", self.debug_dirty_frames),
            ("display.debug_dirty_refreshes", self.debug_dirty_refreshes),
            ("display.debug_dirty_pixels", self.debug_dirty_pixels),
        ), start=2):
            ttk.Label(debug_form, text=app.tr(label_key)).grid(
                row=row,
                column=0,
                sticky="nw",
                pady=3,
            )
            ttk.Label(
                debug_form,
                textvariable=variable,
                style="Muted.TLabel",
                justify="right",
                wraplength=158 if app.compact else 430,
            ).grid(row=row, column=1, sticky="e", padx=(8, 0), pady=3)
        debug_form.columnconfigure(0, weight=1)
        tk.Label(
            debug_card,
            text=app.tr("display.debug_dirty_note"),
            background=PANEL_ALT,
            foreground=MUTED,
            anchor="w",
            justify="left",
            wraplength=276 if app.compact else 650,
        ).pack(fill="x", pady=(4, 2))

        debug_toggle = ttk.Checkbutton(
            debug_card,
            text=app.tr("display.debug_logging_enabled"),
            variable=self.debug_enabled,
            state="disabled",
        )
        debug_toggle.pack(anchor="w", fill="x", pady=(6, 2))
        self.debug_inputs.append(debug_toggle)
        tk.Label(
            debug_card,
            text=app.tr("display.debug_restart_note"),
            background=PANEL_ALT,
            foreground=MUTED,
            anchor="w",
            justify="left",
            wraplength=276 if app.compact else 650,
        ).pack(fill="x", pady=(0, 6))

        cursor_panel = tk.Frame(
            debug_card,
            background=FIELD_BG,
            highlightbackground=OUTLINE,
            highlightthickness=1,
            padx=8,
            pady=7,
        )
        cursor_panel.pack(fill="x", pady=(4, 7))
        tk.Label(
            cursor_panel,
            text=app.tr("display.debug_cursor_title"),
            background=FIELD_BG,
            foreground=TEXT,
            anchor="w",
            font=font_spec(cursor_panel, 10, "bold"),
        ).pack(fill="x")
        tk.Label(
            cursor_panel,
            text=app.tr("display.debug_cursor_note"),
            background=FIELD_BG,
            foreground=MUTED,
            anchor="w",
            justify="left",
            wraplength=258 if app.compact else 620,
        ).pack(fill="x", pady=(2, 4))
        cursor_toggle = ttk.Checkbutton(
            cursor_panel,
            text=app.tr("display.debug_cursor_enabled"),
            variable=self.debug_cursor_enabled,
            state="disabled",
        )
        cursor_toggle.pack(anchor="w", fill="x")
        self.debug_cursor_inputs.append(cursor_toggle)
        self.debug_cursor_status = tk.StringVar(
            value=app.tr("display.debug_cursor_checking")
        )
        tk.Label(
            cursor_panel,
            textvariable=self.debug_cursor_status,
            background=FIELD_BG,
            foreground=MUTED,
            anchor="w",
            justify="left",
            wraplength=258 if app.compact else 620,
        ).pack(fill="x", pady=(4, 3))
        self.debug_cursor_apply_button = ttk.Button(
            cursor_panel,
            text=app.tr("display.debug_apply_cursor"),
            command=self.apply_debug_cursor,
            state="disabled",
        )
        self.debug_cursor_apply_button.pack(
            fill="x" if app.compact else "none",
            anchor="w",
            pady=(3, 0),
        )
        self.debug_cursor_inputs.append(self.debug_cursor_apply_button)

        overlay_panel = tk.Frame(
            debug_card,
            background=FIELD_BG,
            highlightbackground=OUTLINE,
            highlightthickness=1,
            padx=8,
            pady=7,
        )
        overlay_panel.pack(fill="x", pady=(4, 7))
        tk.Label(
            overlay_panel,
            text=app.tr("display.debug_overlay_title"),
            background=FIELD_BG,
            foreground=TEXT,
            anchor="w",
            font=font_spec(overlay_panel, 10, "bold"),
        ).pack(fill="x")
        overlay_toggle = ttk.Checkbutton(
            overlay_panel,
            text=app.tr("display.debug_overlay_enabled"),
            variable=self.debug_overlay_enabled,
            state="disabled",
        )
        overlay_toggle.pack(anchor="w", fill="x", pady=(4, 3))
        self.debug_overlay_inputs.append(overlay_toggle)
        overlay_form = ttk.Frame(overlay_panel, style="Field.TFrame")
        overlay_form.pack(fill="x")
        for row, (label_key, variable, start, end) in enumerate((
            ("display.debug_overlay_alpha", self.debug_overlay_alpha, 0, 255),
            ("display.debug_overlay_scale", self.debug_overlay_scale, 1, 2),
            ("display.debug_overlay_interval", self.debug_overlay_interval, 250, 5000),
        )):
            ttk.Label(overlay_form, text=app.tr(label_key)).grid(
                row=row, column=0, sticky="w", pady=2,
            )
            control = ttk.Spinbox(
                overlay_form,
                from_=start,
                to=end,
                textvariable=variable,
                width=8,
                state="disabled",
            )
            control.grid(row=row, column=1, sticky="e", padx=(8, 0), pady=2)
            self.debug_overlay_inputs.append(control)
        overlay_form.columnconfigure(0, weight=1)
        ttk.Label(
            overlay_panel,
            text=app.tr("display.debug_overlay_items"),
        ).pack(anchor="w", pady=(5, 1))
        item_grid = ttk.Frame(overlay_panel, style="Field.TFrame")
        item_grid.pack(fill="x")
        for index, item in enumerate(CH347_DEBUG_OVERLAY_ITEMS):
            item_control = ttk.Checkbutton(
                item_grid,
                text=app.tr(DEBUG_OVERLAY_ITEM_LABEL_KEYS[item]),
                variable=self.debug_overlay_items[item],
                state="disabled",
                style="Accent.TCheckbutton" if item == "cpu" else "TCheckbutton",
            )
            item_control.grid(
                row=index // 2,
                column=index % 2,
                sticky="w",
                padx=(0, 8),
                pady=1,
            )
            self.debug_overlay_inputs.append(item_control)
        item_grid.columnconfigure(0, weight=1)
        item_grid.columnconfigure(1, weight=1)
        self.debug_overlay_status = tk.StringVar(
            value=app.tr("display.debug_overlay_checking")
        )
        tk.Label(
            overlay_panel,
            textvariable=self.debug_overlay_status,
            background=FIELD_BG,
            foreground=MUTED,
            anchor="w",
            justify="left",
            wraplength=258 if app.compact else 620,
        ).pack(fill="x", pady=(4, 3))
        self.debug_overlay_apply_button = ttk.Button(
            overlay_panel,
            text=app.tr("display.debug_apply_overlay"),
            command=self.apply_debug_overlay,
            state="disabled",
        )
        self.debug_overlay_apply_button.pack(
            fill="x" if app.compact else "none",
            anchor="w",
            pady=(3, 0),
        )
        self.debug_overlay_inputs.append(self.debug_overlay_apply_button)

        debug_actions = ttk.Frame(debug_card, style="Panel.TFrame")
        debug_actions.pack(fill="x")
        self.debug_refresh_button = ttk.Button(
            debug_actions,
            text=app.tr("display.debug_check_fps"),
            command=self.refresh_debug,
            state="disabled",
        )
        self.debug_refresh_button.pack(side="left")
        self.debug_apply_fps_button = ttk.Button(
            debug_actions,
            text=app.tr("display.debug_apply_fps"),
            command=self.apply_debug_fps,
            state="disabled",
        )
        self.debug_apply_fps_button.pack(side="left", padx=(6, 0))
        debug_mode_actions = debug_actions
        if app.compact:
            debug_mode_actions = ttk.Frame(debug_card, style="Panel.TFrame")
            debug_mode_actions.pack(fill="x", pady=(6, 0))
        self.debug_apply_button = ttk.Button(
            debug_mode_actions,
            text=app.tr("display.debug_apply_mode"),
            style="Accent.TButton",
            command=self.apply_debug_mode,
            state="disabled",
        )
        if app.compact:
            self.debug_apply_button.pack(fill="x")
        else:
            self.debug_apply_button.pack(side="left", padx=(6, 0))
        self.debug_inputs.extend((
            self.debug_apply_fps_button,
            self.debug_apply_button,
        ))
        self.debug_feedback_label = tk.Label(
            debug_card,
            textvariable=self.debug_feedback,
            background=PANEL_ALT,
            foreground=MUTED,
            anchor="w",
            justify="left",
            wraplength=276 if app.compact else 650,
        )
        self.debug_feedback_label.pack(fill="x", pady=(6, 0))

        self.effective = tk.Text(
            container,
            height=7,
            bg=FIELD_BG,
            fg=TEXT,
            relief="flat",
            padx=10,
            pady=8,
            wrap="word",
        )
        self.effective.pack(fill="x")
        self.effective.configure(state="disabled")

    @staticmethod
    def _field(parent: ttk.Frame, label: str, control: ttk.Widget, column: int) -> None:
        ttk.Label(parent, text=label, style="Muted.TLabel").grid(
            row=0,
            column=column,
            sticky="w",
            padx=(0, 12),
        )
        control.grid(
            row=1,
            column=column,
            sticky="ew",
            padx=(0, 12),
            pady=(3, 0),
        )
        parent.columnconfigure(column, weight=1)

    @staticmethod
    def _compact_field(
        parent: ttk.Frame,
        label: str,
        control: ttk.Widget,
        row: int,
    ) -> None:
        ttk.Label(parent, text=label, style="Muted.TLabel").grid(
            row=row, column=0, sticky="w", pady=(3 if row else 0, 0)
        )
        control.grid(row=row + 1, column=0, sticky="ew", pady=(2, 0))
        parent.columnconfigure(0, weight=1)

    def refresh(self) -> None:
        self.app.run_task(
            self.app.tr("status.reading_display"),
            lambda: self.app.model.display_settings(refresh=False),
            self._show_snapshot,
        )
        self.physical_apply.configure(state="disabled")
        self.physical_combo.configure(state="disabled")
        self.physical_status.set(self.app.tr("display.physical_loading"))
        self.app.run_task(
            self.app.tr("status.reading_physical_rotation"),
            lambda: self.app.model.physical_rotation(refresh=False),
            self._show_physical_rotation,
        )
        self.refresh_debug()

    def _set_debug_controls(self, enabled: bool) -> None:
        state = "normal" if enabled and not self._debug_busy else "disabled"
        for widget in self.debug_inputs:
            widget.configure(state=state)
        overlay_state = (
            "normal"
            if enabled and self._overlay_available and not self._debug_busy
            else "disabled"
        )
        for widget in self.debug_overlay_inputs:
            widget.configure(state=overlay_state)
        cursor_state = (
            "normal"
            if enabled and self._cursor_available and not self._debug_busy
            else "disabled"
        )
        for widget in self.debug_cursor_inputs:
            widget.configure(state=cursor_state)
        self.debug_refresh_button.configure(
            state="disabled" if self._debug_busy else "normal"
        )

    def refresh_debug(self) -> None:
        if self._debug_busy:
            return
        self._debug_busy = True
        self._set_debug_controls(False)
        self.debug_feedback.set(self.app.tr("display.debug_loading"))
        self.debug_feedback_label.configure(foreground=MUTED)
        self.app.run_task(
            self.app.tr("status.reading_ch347_debug"),
            self.app.model.ch347_get_debug,
            self._show_debug,
        )

    def _show_debug(self, result: OperationResult) -> bool:
        self._debug_busy = False
        if not result.ok:
            self._debug_loaded = False
            self._overlay_available = False
            self._cursor_available = False
            self.debug_overlay_status.set(
                self.app.tr("display.debug_overlay_unavailable")
            )
            self.debug_cursor_status.set(
                self.app.tr("display.debug_cursor_unavailable")
            )
            self._set_debug_controls(False)
            self._set_debug_dirty_counters(None)
            message = self.app.tr(
                "display.debug_unavailable",
                {"message": result.message or result.code or self.app.tr("common.unavailable")},
            )
            self.debug_feedback.set(message)
            self.debug_feedback_label.configure(foreground=ERROR)
            self.app.set_status(message, error=True)
            return True
        debug = result.data.get("debug")
        if not isinstance(debug, dict):
            return self._show_debug(OperationResult(
                False,
                message=self.app.tr("display.debug_invalid_response"),
                code="CH347_BAD_RESPONSE",
            ))
        self._load_debug_state(debug)
        self.app.set_status(self.app.tr("display.debug_loaded"))
        return True

    def _load_debug_state(self, debug: dict[str, Any]) -> None:
        self._debug_loaded = True
        self._confirmed_debug_enabled = bool(debug["enabled"])
        self.debug_enabled.set(self._confirmed_debug_enabled)
        self.debug_fps.set(str(debug["fps"]))
        self.debug_idle_fps.set(str(debug["idle_fps"]))
        self.debug_max_fps.set(self.app.tr(
            "display.debug_fps_value",
            {"fps": debug["max_fps"]},
        ))
        generation = debug.get("provider_generation")
        self.debug_generation.set(
            str(generation)
            if generation is not None
            else self.app.tr("display.debug_not_running")
        )
        configured = self.app.tr(
            "common.enabled" if debug["enabled"] else "common.disabled"
        )
        if debug["applied"]:
            application = self.app.tr("display.debug_runtime_applied")
        elif debug["requires_restart"]:
            application = self.app.tr("display.debug_runtime_pending")
        else:
            application = self.app.tr("display.debug_runtime_not_applied")
        self.debug_application.set(self.app.tr(
            "display.debug_application_value",
            {"configured": configured, "application": application},
        ))
        self._set_debug_dirty_counters(debug)
        overlay = debug.get("overlay")
        if not isinstance(overlay, dict):
            overlay = {
                **DEFAULT_CH347_DEBUG_OVERLAY,
                "available": False,
                "items": list(DEFAULT_CH347_DEBUG_OVERLAY["items"]),
            }
        self._overlay_available = overlay.get("available") is True
        self._confirmed_debug_overlay = {
            "enabled": bool(overlay.get("enabled", False)),
            "alpha": int(overlay.get("alpha", 176)),
            "scale": int(overlay.get("scale", 1)),
            "items": list(
                overlay.get("items", DEFAULT_CH347_DEBUG_OVERLAY["items"])
            ),
            "interval_ms": int(overlay.get("interval_ms", 1000)),
        }
        self.debug_overlay_enabled.set(self._confirmed_debug_overlay["enabled"])
        self.debug_overlay_alpha.set(str(self._confirmed_debug_overlay["alpha"]))
        self.debug_overlay_scale.set(str(self._confirmed_debug_overlay["scale"]))
        self.debug_overlay_interval.set(
            str(self._confirmed_debug_overlay["interval_ms"])
        )
        selected_items = set(self._confirmed_debug_overlay["items"])
        for item, variable in self.debug_overlay_items.items():
            variable.set(item in selected_items)
        self.debug_overlay_status.set(self.app.tr(
            "display.debug_overlay_ready"
            if self._overlay_available
            else "display.debug_overlay_unavailable"
        ))
        cursor = debug.get("touch_cursor")
        if not isinstance(cursor, dict):
            cursor = {"available": False, "enabled": False}
        self._cursor_available = cursor.get("available") is True
        self._confirmed_cursor_enabled = bool(cursor.get("enabled", False))
        self.debug_cursor_enabled.set(self._confirmed_cursor_enabled)
        self.debug_cursor_status.set(self._debug_cursor_state(cursor))

        observed = debug.get("observed_fps")
        panel_fps = debug.get("panel_fps")
        frames = debug.get("frames")
        window_ms = debug.get("window_ms")
        if observed is None and panel_fps is None:
            self.debug_observed.set(self.app.tr("display.debug_no_sample"))
        else:
            sample_parts: list[str] = []
            if observed is not None:
                sample_parts.append(self.app.tr(
                    "display.debug_capture_value",
                    {"fps": f"{float(observed):.1f}"},
                ))
            if panel_fps is not None:
                sample_parts.append(self.app.tr(
                    "display.debug_panel_value",
                    {"fps": f"{float(panel_fps):.1f}"},
                ))
            if frames is not None:
                sample_parts.append(self.app.tr(
                    "display.debug_frames_value",
                    {"frames": frames},
                ))
            if window_ms is not None:
                sample_parts.append(self.app.tr(
                    "display.debug_window_value",
                    {"window_ms": window_ms},
                ))
            self.debug_observed.set(" · ".join(sample_parts))
        status_key = {
            "active": "display.debug_status_active",
            "idle": "display.debug_status_idle",
            "unavailable": "display.debug_status_unavailable",
        }.get(str(debug.get("status")), "display.debug_status_unavailable")
        reason = str(debug.get("reason") or "").strip()
        reason_key = {
            "debug-disabled": "display.debug_reason_disabled",
            "configuration-not-applied": "display.debug_reason_pending",
            "awaiting-debug-sample": "display.debug_reason_awaiting",
            "sink-debug-log": "display.debug_reason_measured",
        }.get(reason)
        if reason_key is not None:
            reason = self.app.tr(reason_key)
        self.debug_feedback.set(self.app.tr(
            "display.debug_check_result",
            {
                "status": self.app.tr(status_key),
                "reason": reason or self.app.tr("display.debug_reason_none"),
            },
        ))
        self.debug_feedback_label.configure(
            foreground=ERROR if debug.get("status") == "unavailable" else MUTED
        )
        self._set_debug_controls(True)

    def _debug_cursor_state(self, cursor: dict[str, Any]) -> str:
        if cursor.get("available") is not True:
            return self.app.tr("display.debug_cursor_unavailable")
        configured = self.app.tr(
            "common.enabled" if cursor.get("enabled") else "common.disabled"
        )
        if cursor.get("applied") is True:
            application = self.app.tr("display.debug_runtime_applied")
        elif cursor.get("requires_restart") is True:
            application = self.app.tr("display.debug_runtime_pending")
        else:
            application = self.app.tr("display.debug_runtime_not_applied")
        generation = cursor.get("provider_generation")
        generation_text = (
            str(generation)
            if generation is not None
            else self.app.tr("display.debug_not_running")
        )
        state = self.app.tr(
            "display.debug_cursor_state",
            {
                "configured": configured,
                "application": application,
                "generation": generation_text,
            },
        )
        reason = str(cursor.get("reason") or "").strip()
        if reason:
            state = self.app.tr(
                "display.debug_cursor_state_reason",
                {"state": state, "reason": reason},
            )
        return state

    def _set_debug_dirty_counters(self, debug: dict[str, Any] | None) -> None:
        def value(field: str) -> str:
            counter = debug.get(field) if debug is not None else None
            return (
                str(counter)
                if counter is not None
                else self.app.tr("common.unavailable")
            )

        self.debug_dirty_frames.set(self.app.tr(
            "display.debug_dirty_frames_value",
            {
                "sent_frames": value("sent_frames"),
                "zero_damage": value("zero_damage"),
            },
        ))
        self.debug_dirty_refreshes.set(self.app.tr(
            "display.debug_dirty_refreshes_value",
            {
                "full_refreshes": value("full_refreshes"),
                "large_refreshes": value("large_refreshes"),
            },
        ))
        self.debug_dirty_pixels.set(self.app.tr(
            "display.debug_dirty_pixels_value",
            {
                "sent_pixels": value("sent_pixels"),
                "last_sent_pixels": value("last_sent_pixels"),
                "last_rects": value("last_rects"),
            },
        ))

    def _debug_integer(self, variable: tk.StringVar, field: str) -> int:
        try:
            return int(variable.get().strip(), 10)
        except ValueError as exc:
            raise ValueError(self.app.tr(
                "ch347.whole_number_required",
                {"field": field},
            )) from exc

    def apply_debug_fps(self) -> None:
        try:
            fps = self._debug_integer(
                self.debug_fps,
                self.app.tr("display.debug_target_fps"),
            )
            idle_fps = self._debug_integer(
                self.debug_idle_fps,
                self.app.tr("display.debug_idle_fps"),
            )
        except ValueError as exc:
            self.debug_feedback.set(str(exc))
            self.debug_feedback_label.configure(foreground=ERROR)
            return
        self._debug_busy = True
        self._set_debug_controls(False)
        self.debug_feedback.set(self.app.tr("status.applying_ch347_fps"))
        self.app.run_task(
            self.app.tr("status.applying_ch347_fps"),
            lambda: self.app.model.ch347_set_fps(fps, idle_fps),
            self._debug_fps_applied,
        )

    def _debug_fps_applied(self, result: OperationResult) -> bool:
        self._debug_busy = False
        if not result.ok:
            self._set_debug_controls(self._debug_loaded)
            message = self.app.tr(
                "display.debug_apply_failed",
                {"message": result.message or result.code},
            )
            self.debug_feedback.set(message)
            self.debug_feedback_label.configure(foreground=ERROR)
            self.app.set_status(message, error=True)
            return True
        self.debug_fps.set(str(result.data["fps"]))
        self.debug_idle_fps.set(str(result.data["idle_fps"]))
        self.debug_feedback.set(self.app.tr(
            "ch347.frame_rates_applied",
            {"fps": result.data["fps"], "idle_fps": result.data["idle_fps"]},
        ))
        self.debug_feedback_label.configure(foreground=MUTED)
        self.app.root.after(100, self.refresh_debug)
        return True

    def apply_debug_mode(self) -> None:
        selected = bool(self.debug_enabled.get())
        if selected == self._confirmed_debug_enabled:
            self.debug_feedback.set(self.app.tr("display.debug_unchanged"))
            self.debug_feedback_label.configure(foreground=MUTED)
            return
        if not messagebox.askyesno(
            self.app.tr("display.debug_confirm_title"),
            self.app.tr("display.debug_confirm_body"),
            parent=self.app.root,
            icon="warning",
            default=messagebox.NO,
        ):
            self.debug_enabled.set(self._confirmed_debug_enabled)
            self.debug_feedback.set(self.app.tr("display.debug_cancelled"))
            self.debug_feedback_label.configure(foreground=MUTED)
            return
        self._debug_busy = True
        self._set_debug_controls(False)
        self.debug_feedback.set(self.app.tr("status.applying_ch347_debug"))
        self.app.run_task(
            self.app.tr("status.applying_ch347_debug"),
            lambda: self.app.model.ch347_set_debug(selected),
            self._debug_mode_applied,
        )

    def apply_debug_cursor(self) -> None:
        if not self._cursor_available:
            self.debug_cursor_status.set(
                self.app.tr("display.debug_cursor_unavailable")
            )
            return
        selected = bool(self.debug_cursor_enabled.get())
        if selected == self._confirmed_cursor_enabled:
            self.debug_cursor_status.set(
                self.app.tr("display.debug_cursor_unchanged")
            )
            return
        self._debug_busy = True
        self._set_debug_controls(False)
        self.debug_cursor_status.set(
            self.app.tr("status.applying_ch347_touch_cursor")
        )
        self.app.run_task(
            self.app.tr("status.applying_ch347_touch_cursor"),
            lambda: self.app.model.ch347_set_debug({"cursor_enabled": selected}),
            lambda result: self._debug_cursor_applied(result, selected),
        )

    def _debug_cursor_applied(
        self,
        result: OperationResult,
        selected: bool,
    ) -> bool:
        self._debug_busy = False
        if not result.ok:
            self.debug_cursor_enabled.set(self._confirmed_cursor_enabled)
            self._set_debug_controls(self._debug_loaded)
            message = self.app.tr(
                "display.debug_cursor_apply_failed",
                {"message": result.message or result.code},
            )
            self.debug_cursor_status.set(message)
            self.app.set_status(message, error=True)
            return True
        debug = result.data.get("debug")
        cursor = debug.get("touch_cursor") if isinstance(debug, dict) else None
        if (
            not isinstance(cursor, dict)
            or cursor.get("available") is not True
            or cursor.get("enabled") is not selected
        ):
            self._cursor_available = bool(
                isinstance(cursor, dict) and cursor.get("available") is True
            )
            self.debug_cursor_enabled.set(self._confirmed_cursor_enabled)
            self._set_debug_controls(self._debug_loaded)
            message = self.app.tr("display.debug_cursor_not_applied")
            self.debug_cursor_status.set(message)
            self.app.set_status(message, error=True)
            return True
        if cursor.get("applied") is not True and cursor.get("requires_restart") is not True:
            self.debug_cursor_enabled.set(self._confirmed_cursor_enabled)
            self._set_debug_controls(self._debug_loaded)
            message = self.app.tr("display.debug_cursor_not_applied")
            self.debug_cursor_status.set(message)
            self.app.set_status(message, error=True)
            return True
        self._load_debug_state(debug)
        message = self.app.tr(
            "display.debug_cursor_saved_restart"
            if cursor.get("requires_restart") is True
            else "display.debug_cursor_applied"
        )
        self.debug_cursor_status.set(
            self.app.tr(
                "display.debug_cursor_result",
                {"message": message, "state": self._debug_cursor_state(cursor)},
            )
        )
        self.app.set_status(message)
        return True

    def _selected_debug_overlay(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.debug_overlay_enabled.get()),
            "alpha": self._debug_integer(
                self.debug_overlay_alpha,
                self.app.tr("display.debug_overlay_alpha"),
            ),
            "scale": self._debug_integer(
                self.debug_overlay_scale,
                self.app.tr("display.debug_overlay_scale"),
            ),
            "items": [
                item
                for item in CH347_DEBUG_OVERLAY_ITEMS
                if self.debug_overlay_items[item].get()
            ],
            "interval_ms": self._debug_integer(
                self.debug_overlay_interval,
                self.app.tr("display.debug_overlay_interval"),
            ),
        }

    def apply_debug_overlay(self) -> None:
        if not self._overlay_available:
            self.debug_overlay_status.set(
                self.app.tr("display.debug_overlay_unavailable")
            )
            return
        try:
            selected = self._selected_debug_overlay()
        except ValueError as exc:
            self.debug_overlay_status.set(str(exc))
            return
        if selected == self._confirmed_debug_overlay:
            self.debug_overlay_status.set(
                self.app.tr("display.debug_overlay_unchanged")
            )
            return
        if not messagebox.askyesno(
            self.app.tr("display.debug_overlay_confirm_title"),
            self.app.tr("display.debug_overlay_confirm_body"),
            parent=self.app.root,
            icon="warning",
            default=messagebox.NO,
        ):
            self._load_debug_overlay_controls(self._confirmed_debug_overlay)
            self.debug_overlay_status.set(
                self.app.tr("display.debug_overlay_cancelled")
            )
            return
        self._debug_busy = True
        self._set_debug_controls(False)
        self.debug_overlay_status.set(
            self.app.tr("status.applying_ch347_debug_overlay")
        )
        self.app.run_task(
            self.app.tr("status.applying_ch347_debug_overlay"),
            lambda: self.app.model.ch347_set_debug({
                "enabled": self._confirmed_debug_enabled,
                "overlay": selected,
            }),
            self._debug_overlay_applied,
        )

    def _load_debug_overlay_controls(self, overlay: dict[str, Any]) -> None:
        self.debug_overlay_enabled.set(bool(overlay["enabled"]))
        self.debug_overlay_alpha.set(str(overlay["alpha"]))
        self.debug_overlay_scale.set(str(overlay["scale"]))
        self.debug_overlay_interval.set(str(overlay["interval_ms"]))
        selected_items = set(overlay["items"])
        for item, variable in self.debug_overlay_items.items():
            variable.set(item in selected_items)

    def _debug_overlay_applied(self, result: OperationResult) -> bool:
        self._debug_busy = False
        if not result.ok:
            self._load_debug_overlay_controls(self._confirmed_debug_overlay)
            self._set_debug_controls(self._debug_loaded)
            message = self.app.tr(
                "display.debug_overlay_apply_failed",
                {"message": result.message or result.code},
            )
            self.debug_overlay_status.set(message)
            self.app.set_status(message, error=True)
            return True
        debug = result.data.get("debug")
        overlay = debug.get("overlay") if isinstance(debug, dict) else None
        if not isinstance(overlay, dict) or overlay.get("available") is not True:
            self._overlay_available = False
            self._load_debug_overlay_controls(self._confirmed_debug_overlay)
            self._set_debug_controls(self._debug_loaded)
            message = self.app.tr("display.debug_overlay_not_applied")
            self.debug_overlay_status.set(message)
            self.app.set_status(message, error=True)
            return True
        self._load_debug_state(debug)
        message = self.app.tr("display.debug_overlay_applied")
        self.debug_overlay_status.set(message)
        self.app.set_status(message)
        return True

    def _debug_mode_applied(self, result: OperationResult) -> bool:
        self._debug_busy = False
        if not result.ok:
            self.debug_enabled.set(self._confirmed_debug_enabled)
            self._set_debug_controls(self._debug_loaded)
            message = self.app.tr(
                "display.debug_apply_failed",
                {"message": result.message or result.code},
            )
            self.debug_feedback.set(message)
            self.debug_feedback_label.configure(foreground=ERROR)
            self.app.set_status(message, error=True)
            return True
        debug = result.data.get("debug")
        if not isinstance(debug, dict):
            return self._show_debug(OperationResult(
                False,
                message=self.app.tr("display.debug_invalid_response"),
                code="CH347_BAD_RESPONSE",
            ))
        self._load_debug_state(debug)
        message = (
            self.app.tr("display.debug_saved_restart")
            if debug["requires_restart"]
            else self.app.tr("display.debug_applied")
        )
        self.debug_feedback.set(message)
        self.debug_feedback_label.configure(foreground=MUTED)
        self.app.set_status(message)
        return True

    def apply(self) -> None:
        self.app.run_task(
            self.app.tr("status.applying_layout"),
            lambda: self.app.model.set_layout(
                _choice_value(self.profile.get(), self._profile_labels),
                _choice_value(self.orientation.get(), self._orientation_labels),
                self.insets.get(),
            ),
            self._layout_applied,
        )

    def _layout_applied(self, result: OperationResult) -> bool | None:
        self._apply_layout(result.data if result.ok else {})
        if result.ok:
            self.refresh()
            return True
        _replace_text(
            self.effective,
            {"available": False, "code": result.code, "message": result.message},
        )
        return None

    def apply_physical_rotation(self) -> None:
        rotation = _choice_value(
            self.physical_rotation.get(),
            self._physical_labels,
        )
        self.physical_apply.configure(state="disabled")
        self.physical_combo.configure(state="disabled")
        self.app.run_task(
            self.app.tr("status.applying_physical_rotation"),
            lambda: self.app.model.set_physical_rotation(
                self.physical_device,
                rotation,
            ),
            self._physical_rotation_applied,
        )

    def _show_physical_rotation(self, result: OperationResult) -> bool:
        data = result.data if isinstance(result.data, dict) else {}
        available = result.ok and data.get("available") is True
        writable = available and data.get("writable") is True
        value = str(data.get("value") or "normal")
        if value in self._physical_labels:
            self.physical_rotation.set(self._physical_labels[value])
        self.physical_device = str(data.get("device") or "")
        self.physical_combo.configure(state="readonly" if writable else "disabled")
        self.physical_apply.configure(state="normal" if writable else "disabled")
        if writable:
            self.physical_status.set(self.app.tr("display.physical_ready"))
        elif available:
            self.physical_status.set(self.app.tr("display.physical_readonly"))
        else:
            reason = str(data.get("reason") or self.app.tr("common.unavailable"))
            reason_key = {
                "provider-does-not-expose-physical-rotation": (
                    "display.physical_reason_provider"
                ),
                "unavailable": "display.physical_reason_provider",
                "read-only": "display.physical_reason_readonly",
            }.get(reason)
            if reason_key:
                reason = self.app.tr(reason_key)
            self.physical_status.set(
                self.app.tr("display.physical_unavailable", {"reason": reason})
            )
        return True

    def _physical_rotation_applied(self, result: OperationResult) -> bool:
        if result.ok:
            self.physical_status.set(self.app.tr("display.physical_restarting"))
            self.app.root.after(250, self.refresh)
        else:
            self.physical_status.set(
                self.app.tr(
                    "display.physical_failed",
                    {"message": result.message or result.code},
                )
            )
            self.app.root.after(0, lambda: self._restore_physical_controls())
        return True

    def _restore_physical_controls(self) -> None:
        if self.physical_device:
            self.physical_combo.configure(state="readonly")
            self.physical_apply.configure(state="normal")

    def _apply_layout(self, data: dict[str, Any]) -> None:
        effective = data.get("effective", data) if isinstance(data, dict) else {}
        if isinstance(effective, dict):
            profile = effective.get("profile")
            orientation = effective.get("orientation_policy", effective.get("orientation"))
            insets = effective.get("insets_policy", effective.get("requested_insets"))
            if profile in LAYOUT_PROFILES:
                self.profile.set(self._profile_labels[profile])
            if orientation in ORIENTATIONS:
                self.orientation.set(self._orientation_labels[orientation])
            if insets is not None:
                self.insets.set(_insets_text(insets))

    def _show_snapshot(self, result: OperationResult) -> None:
        data = result.data if isinstance(result.data, dict) else {}
        layout = data.get("layout", {})
        output = data.get("output", {})
        hal = data.get("hal", {})
        layout_available = isinstance(layout, dict) and bool(layout.get("available"))
        output_available = isinstance(output, dict) and bool(output.get("available"))
        hal_available = isinstance(hal, dict) and bool(hal.get("available"))
        if layout_available:
            value = layout.get("value", {})
            if isinstance(value, dict):
                self._apply_layout(value)
        self.apply_button.configure(state="normal" if layout_available else "disabled")
        self.output_button.configure(state="normal" if output_available else "disabled")
        self.hal_button.configure(state="normal" if hal_available else "disabled")

        role = output.get("role", {}) if isinstance(output, dict) else {}
        active = str(role.get("active") or self.app.tr("common.unavailable")) if isinstance(role, dict) else self.app.tr("common.unavailable")
        devices = hal.get("devices", []) if isinstance(hal, dict) else []
        device_count = len(devices) if isinstance(devices, list) else 0
        if result.ok:
            self.display_summary.set(self.app.tr("display.summary", {
                "output": active,
                "layout": self.app.tr(
                    "display.layout_ready"
                    if layout_available
                    else "display.layout_unavailable"
                ),
                "count": device_count,
            }))
        else:
            self.display_summary.set(self.app.tr("display.services_unavailable"))
        _replace_text(
            self.effective,
            data
            or {
                "available": False,
                "code": result.code,
                "message": result.message,
            },
        )

    def manage_output(self) -> None:
        page = self.app._pages.get("roles")
        if isinstance(page, RolesPage):
            page.focus_role("display-output")
            self.app.show_page("roles")

    def manage_hal(self) -> None:
        page = self.app._pages.get("hal")
        if isinstance(page, HalPage):
            page.focus_domain(
                "display-output"
                if self.physical_device.startswith("display-output:")
                else "display"
            )
            self.app.show_page("hal")


class AppearancePage(BasePage):
    title_key = "appearance.title"
    note_key = "appearance.note"

    def __init__(self, parent: ttk.Frame, app: SettingsApplication) -> None:
        super().__init__(parent, app)
        surface = ScrollableSurface(self, background=PANEL)
        surface.pack(fill="both", expand=True)
        container = surface.content
        self._layout_labels = _localized_choice_labels(
            app,
            DESKTOP_LAYOUTS,
            DESKTOP_LAYOUT_LABEL_KEYS,
        )
        self._sort_labels = _localized_choice_labels(
            app,
            DESKTOP_SORTS,
            DESKTOP_SORT_LABEL_KEYS,
        )
        self.layout = tk.StringVar(value=self._layout_labels["profile"])
        self.wallpaper = tk.StringVar(value="#101419")
        self.accent = tk.StringVar(value="#55A8FF")
        self.icon_size = tk.StringVar(value="64")
        self.show_labels = tk.BooleanVar(value=True)
        self.sort = tk.StringVar(value=self._sort_labels["name"])
        self.wallpaper_path = tk.StringVar(value="")
        self.grid_columns = tk.StringVar(value="0")
        self.grid_rows = tk.StringVar(value="0")
        self.acrylic = tk.BooleanVar(value=False)
        self._navigation_labels = _localized_choice_labels(
            app,
            NAVIGATION_MODES,
            NAVIGATION_MODE_LABEL_KEYS,
        )
        self.navigation_mode = tk.StringVar(value=self._navigation_labels["pill"])
        self.icon_spacing = tk.StringVar(value="8")
        self.folders_enabled = tk.BooleanVar(value=True)
        self.large_folders_enabled = tk.BooleanVar(value=True)
        self.animations_enabled = tk.BooleanVar(value=True)
        self.reduce_motion = tk.BooleanVar(value=False)
        self.message = tk.StringVar(value=app.tr("common.not_loaded"))
        self._preview_after: Any = None
        self._preview_signature: tuple[Any, ...] | None = None

        form = ttk.Frame(container, style="Panel.TFrame")
        form.pack(fill="x")
        if app.compact:
            self._field(
                form,
                app.tr("appearance.layout"),
                ttk.Combobox(
                    form,
                    textvariable=self.layout,
                    values=tuple(
                        self._layout_labels[value] for value in DESKTOP_LAYOUTS
                    ),
                    state="readonly",
                ),
                0,
                0,
                span=2,
            )
            self._field(
                form,
                app.tr("appearance.wallpaper"),
                ttk.Entry(form, textvariable=self.wallpaper),
                2,
                0,
            )
            self._field(
                form,
                app.tr("appearance.accent"),
                ttk.Entry(form, textvariable=self.accent),
                2,
                1,
            )
            self._field(
                form,
                app.tr("appearance.icon_size"),
                ttk.Spinbox(
                    form,
                    textvariable=self.icon_size,
                    from_=40,
                    to=96,
                    increment=1,
                ),
                4,
                0,
            )
            self._field(
                form,
                app.tr("appearance.sort"),
                ttk.Combobox(
                    form,
                    textvariable=self.sort,
                    values=tuple(
                        self._sort_labels[value] for value in DESKTOP_SORTS
                    ),
                    state="readonly",
                ),
                4,
                1,
            )
            ttk.Checkbutton(
                form,
                text=app.tr("appearance.show_labels"),
                variable=self.show_labels,
                command=self._schedule_preview,
            ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))
        else:
            controls = (
                (
                    app.tr("appearance.layout"),
                    ttk.Combobox(
                        form,
                        textvariable=self.layout,
                        values=tuple(
                            self._layout_labels[value] for value in DESKTOP_LAYOUTS
                        ),
                        state="readonly",
                    ),
                ),
                (app.tr("appearance.wallpaper"), ttk.Entry(form, textvariable=self.wallpaper)),
                (app.tr("appearance.accent"), ttk.Entry(form, textvariable=self.accent)),
                (
                    app.tr("appearance.icon_size"),
                    ttk.Spinbox(
                        form,
                        textvariable=self.icon_size,
                        from_=40,
                        to=96,
                        increment=1,
                    ),
                ),
                (
                    app.tr("appearance.sort"),
                    ttk.Combobox(
                        form,
                        textvariable=self.sort,
                        values=tuple(
                            self._sort_labels[value] for value in DESKTOP_SORTS
                        ),
                        state="readonly",
                    ),
                ),
            )
            for index, (label, control) in enumerate(controls):
                row = (index // 3) * 2
                column = index % 3
                self._field(form, label, control, row, column)
            ttk.Checkbutton(
                form,
                text=app.tr("appearance.show_labels"),
                variable=self.show_labels,
                command=self._schedule_preview,
            ).grid(row=3, column=2, sticky="w", padx=4, pady=(3, 0))

        desktop_options = ttk.LabelFrame(
            container,
            text=app.tr("appearance.desktop_options"),
            padding=(9, 7),
        )
        desktop_options.pack(fill="x", pady=(9, 2))
        ttk.Label(
            desktop_options,
            text=app.tr("appearance.wallpaper_path_hint"),
            style="Panel.TLabel",
            justify="left",
            wraplength=270 if app.compact else 680,
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        self._field(
            desktop_options,
            app.tr("appearance.wallpaper_path"),
            ttk.Entry(desktop_options, textvariable=self.wallpaper_path),
            1,
            0,
            span=2,
        )
        self._field(
            desktop_options,
            app.tr("appearance.grid_columns"),
            ttk.Spinbox(
                desktop_options,
                textvariable=self.grid_columns,
                from_=0,
                to=8,
                increment=1,
            ),
            3,
            0,
        )
        self._field(
            desktop_options,
            app.tr("appearance.grid_rows"),
            ttk.Spinbox(
                desktop_options,
                textvariable=self.grid_rows,
                from_=0,
                to=6,
                increment=1,
            ),
            3,
            1,
        )
        self._field(
            desktop_options,
            app.tr("appearance.navigation_mode"),
            ttk.Combobox(
                desktop_options,
                textvariable=self.navigation_mode,
                values=tuple(
                    self._navigation_labels[value] for value in NAVIGATION_MODES
                ),
                state="readonly",
            ),
            5,
            0,
        )
        self._field(
            desktop_options,
            app.tr("appearance.icon_spacing"),
            ttk.Spinbox(
                desktop_options,
                textvariable=self.icon_spacing,
                from_=0,
                to=48,
                increment=1,
            ),
            5,
            1,
        )
        ttk.Checkbutton(
            desktop_options,
            text=app.tr("appearance.acrylic"),
            variable=self.acrylic,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(5, 0))
        for offset, (key, variable) in enumerate((
            ("appearance.folders_enabled", self.folders_enabled),
            ("appearance.large_folders_enabled", self.large_folders_enabled),
            ("appearance.animations_enabled", self.animations_enabled),
            ("appearance.reduce_motion", self.reduce_motion),
        )):
            ttk.Checkbutton(
                desktop_options,
                text=app.tr(key),
                variable=variable,
            ).grid(
                row=8 + offset,
                column=0,
                columnspan=2,
                sticky="w",
                pady=(3, 0),
            )
        ttk.Label(
            desktop_options,
            text=app.tr("appearance.live_apply_note"),
            style="Muted.TLabel",
            justify="left",
            wraplength=270 if app.compact else 680,
        ).grid(row=12, column=0, columnspan=2, sticky="ew", pady=(7, 0))

        actions = ttk.Frame(container, style="Panel.TFrame")
        actions.pack(fill="x", pady=(7, 4))
        ttk.Button(actions, text=app.tr("common.read"), command=self.refresh).pack(side="left")
        ttk.Button(
            actions,
            text=app.tr("common.apply"),
            style="Accent.TButton",
            command=self.apply,
        ).pack(side="left", padx=6)
        ttk.Label(actions, textvariable=self.message, style="Muted.TLabel").pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )

        self.preview = tk.Canvas(
            container,
            height=86 if app.compact else 150,
            bg="#101419",
            highlightthickness=1,
            highlightbackground=PANEL_ALT,
        )
        self.preview.pack(fill="x", pady=(2, 0))
        self._preview_bar = self.preview.create_rectangle(
            0, 0, 1, 1, fill=ACCENT, outline=""
        )
        preview_labels = (
            self.app.tr("appearance.preview_settings"),
            self.app.tr("appearance.preview_files"),
            self.app.tr("appearance.preview_app"),
        )
        self._preview_icons = tuple(
            self.preview.create_rectangle(
                0, 0, 1, 1, fill=ACCENT, outline="#eef4fa"
            )
            for _label in preview_labels
        )
        self._preview_labels = tuple(
            self.preview.create_text(
                0, 0, text=label, fill=TEXT, font=font_spec(self.preview, 8)
            )
            for label in preview_labels
        )
        self.preview.bind("<Configure>", self._schedule_preview)
        for variable in (self.wallpaper, self.accent, self.icon_size):
            variable.trace_add("write", self._schedule_preview)
        self._schedule_preview()

    @staticmethod
    def _field(
        parent: ttk.Frame,
        label: str,
        control: ttk.Widget,
        row: int,
        column: int,
        *,
        span: int = 1,
    ) -> None:
        ttk.Label(parent, text=label, style="Muted.TLabel").grid(
            row=row,
            column=column,
            columnspan=span,
            sticky="w",
            padx=4,
            pady=(2, 0),
        )
        control.grid(
            row=row + 1,
            column=column,
            columnspan=span,
            sticky="ew",
            padx=4,
            pady=(2, 0),
        )
        for item in range(column, column + span):
            parent.columnconfigure(item, weight=1)

    @staticmethod
    def _preview_color(value: str, fallback: str) -> str:
        value = value.strip()
        if len(value) == 7 and value.startswith("#"):
            try:
                int(value[1:], 16)
            except ValueError:
                pass
            else:
                return value
        return fallback

    def _schedule_preview(self, *_args: Any) -> None:
        self._preview_after = _replace_after(
            self,
            self._preview_after,
            50,
            self._draw_preview,
        )

    def _draw_preview(self) -> None:
        self._preview_after = None
        if not hasattr(self, "preview"):
            return
        canvas = self.preview
        width = max(canvas.winfo_width(), 180)
        height = max(canvas.winfo_height(), 80)
        wallpaper = self._preview_color(self.wallpaper.get(), BG)
        accent = self._preview_color(self.accent.get(), ACCENT)
        try:
            requested = max(40, min(96, int(self.icon_size.get())))
        except ValueError:
            requested = 64
        show_labels = self.show_labels.get()
        signature = (width, height, wallpaper, accent, requested, show_labels)
        if signature == self._preview_signature:
            return
        self._preview_signature = signature
        _configure_if_changed(canvas, bg=wallpaper)
        canvas.coords(self._preview_bar, 0, 0, width, 8)
        canvas.itemconfigure(self._preview_bar, fill=accent)
        icon = max(18, min(42, int(requested * 0.44)))
        spacing = width / 4
        y = max(14, (height - icon - (18 if show_labels else 0)) / 2)
        for index, (icon_item, label_item) in enumerate(
            zip(self._preview_icons, self._preview_labels), start=1
        ):
            center = int(spacing * index)
            canvas.coords(
                icon_item,
                center - icon // 2,
                y,
                center + icon // 2,
                y + icon,
            )
            canvas.itemconfigure(icon_item, fill=accent)
            canvas.coords(label_item, center, y + icon + 9)
            canvas.itemconfigure(label_item, state="normal" if show_labels else "hidden")

    def refresh(self) -> None:
        self.app.run_task(
            self.app.tr("status.reading_desktop"),
            self.app.model.desktop_preferences,
            self._show_result,
        )

    def apply(self) -> None:
        self.app.run_task(
            self.app.tr("status.applying_desktop"),
            lambda: self.app.model.set_desktop_preferences(
                self._layout_value(),
                self.wallpaper.get(),
                self.accent.get(),
                self.icon_size.get(),
                self.show_labels.get(),
                self._sort_value(),
                self.wallpaper_path.get().strip(),
                self.grid_columns.get(),
                self.grid_rows.get(),
                self.acrylic.get(),
                _choice_value(
                    self.navigation_mode.get(), self._navigation_labels
                ).strip().lower(),
                self.icon_spacing.get(),
                self.folders_enabled.get(),
                self.large_folders_enabled.get(),
                self.animations_enabled.get(),
                self.reduce_motion.get(),
            ),
            self._show_result,
        )

    def _show_result(self, result: OperationResult) -> None:
        if not result.ok:
            self.message.set(f"{result.code}: {result.message}".strip(": "))
            return
        preferences = result.data.get("preferences", {})
        if not isinstance(preferences, dict):
            self.message.set(self.app.tr("appearance.invalid_response"))
            return
        self._apply_preferences(preferences)
        if "revision" in result.data:
            self.message.set(
                self.app.tr(
                    "appearance.revision",
                    {"revision": result.data["revision"]},
                )
            )
        else:
            self.message.set(self.app.tr("appearance.loaded"))

    def _apply_preferences(self, preferences: dict[str, Any]) -> None:
        layout = str(preferences.get("layout", "profile"))
        self.layout.set(self._layout_labels.get(layout, layout))
        self.wallpaper.set(str(preferences.get("wallpaper_color", "#101419")))
        self.accent.set(str(preferences.get("accent_color", "#55A8FF")))
        self.icon_size.set(str(preferences.get("icon_size", 64)))
        self.show_labels.set(bool(preferences.get("show_labels", True)))
        self.wallpaper_path.set(str(preferences.get("wallpaper_path", "")))
        self.grid_columns.set(str(preferences.get("grid_columns", 0)))
        self.grid_rows.set(str(preferences.get("grid_rows", 0)))
        self.acrylic.set(bool(preferences.get("acrylic", False)))
        navigation_mode = str(preferences.get("navigation_mode", "pill"))
        self.navigation_mode.set(
            self._navigation_labels.get(navigation_mode, navigation_mode)
        )
        self.icon_spacing.set(str(preferences.get("icon_spacing", 8)))
        self.folders_enabled.set(bool(preferences.get("folders_enabled", True)))
        self.large_folders_enabled.set(
            bool(preferences.get("large_folders_enabled", True))
        )
        self.animations_enabled.set(
            bool(preferences.get("animations_enabled", True))
        )
        self.reduce_motion.set(bool(preferences.get("reduce_motion", False)))
        sort = str(preferences.get("sort", "name"))
        self.sort.set(self._sort_labels.get(sort, sort))
        self._schedule_preview()

    def _layout_value(self) -> str:
        return _choice_value(self.layout.get(), self._layout_labels).strip().lower()

    def _sort_value(self) -> str:
        return _choice_value(self.sort.get(), self._sort_labels).strip().lower()

    def external_change(self, payload: dict[str, Any]) -> None:
        try:
            data = normalise_desktop_preferences(payload)
        except (TypeError, ValueError):
            self._loaded = False
            self.message.set(self.app.tr("appearance.changed_elsewhere"))
            return
        self._apply_preferences(data["preferences"])
        self.message.set(self.app.tr("appearance.updated"))


class RolesPage(BasePage):
    title_key = "roles.title"
    note_key = "roles.note"

    def __init__(self, parent: ttk.Frame, app: SettingsApplication) -> None:
        super().__init__(parent, app)
        self.roles: dict[str, dict[str, Any]] = {}
        self._requested_role: str | None = None
        self.migration = DisplayMigrationTracker()
        self._display_request_pending = False
        self._poll_scheduled_for: int | None = None
        self.surface = ScrollableSurface(self, background=PANEL)
        self.surface.pack(fill="both", expand=True)
        container = self.surface.content
        tree_frame = ttk.Frame(container, style="Panel.TFrame")
        tree_frame.pack(fill="x")
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("active", "preferred"),
            show="headings",
            height=7,
            selectmode="browse",
        )
        self.tree.heading("active", text=app.tr("roles.role_active"))
        self.tree.heading("preferred", text=app.tr("roles.preferred"))
        self.tree.column("active", width=380, anchor="w")
        self.tree.column("preferred", width=230, anchor="w")
        if app.compact:
            self.tree.configure(displaycolumns=("active",), height=5)
            self.tree.column("active", width=280, minwidth=100, stretch=True)
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="x", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        controls = ttk.Frame(container, style="Panel.TFrame")
        controls.pack(fill="x", pady=8)
        self.provider = tk.StringVar()
        self.provider_box = ttk.Combobox(
            controls, textvariable=self.provider, state="readonly"
        )
        self.provider_box.pack(side="left", fill="x", expand=True)
        self.provider_box.bind("<<ComboboxSelected>>", self._update_actions)
        actions = controls
        if app.compact:
            actions = ttk.Frame(container, style="Panel.TFrame")
            actions.pack(fill="x", pady=(0, 6))
        self.switch_button = ttk.Button(
            actions,
            text=app.tr("common.switch"),
            style="Accent.TButton",
            command=self.switch,
            state="disabled",
        )
        self.switch_button.pack(
            side="left", padx=(0 if app.compact else 6, 6)
        )
        self.reset_button = ttk.Button(
            actions,
            text=app.tr("common.reset" if app.compact else "common.reset_default"),
            command=self.reset,
            state="disabled",
        )
        self.reset_button.pack(side="left")
        ttk.Button(actions, text=app.tr("common.refresh"), command=self.refresh).pack(side="left", padx=(6, 0))
        self.migration_status = tk.StringVar(value=app.tr("roles.no_migration"))
        self.migration_status_label = ttk.Label(
            container,
            textvariable=self.migration_status,
            style="Muted.TLabel",
            justify="left",
            wraplength=276 if app.compact else 650,
        )
        self.migration_status_label.pack(anchor="w", fill="x", pady=(0, 6))
        self.migration_status_label.bind(
            "<Configure>",
            lambda event: self.migration_status_label.configure(
                wraplength=text_wrap_length(
                    int(event.width), horizontal_padding=4
                )
            ),
        )
        details_frame = ttk.Frame(container, style="Panel.TFrame")
        details_frame.pack(fill="x")
        self.details = tk.Text(
            details_frame,
            bg=FIELD_BG,
            fg=TEXT,
            relief="flat",
            padx=10,
            pady=8,
            wrap="word",
            height=8,
        )
        details_scroll = ttk.Scrollbar(details_frame, orient="vertical", command=self.details.yview)
        self.details.configure(yscrollcommand=details_scroll.set)
        self.details.pack(side="left", fill="both", expand=True)
        details_scroll.pack(side="right", fill="y")
        self.details.configure(state="disabled")

    def refresh(self) -> None:
        self.app.run_task(self.app.tr("status.loading_roles"), self.app.model.list_roles, self._loaded_result)

    def _loaded_result(self, result: OperationResult) -> None:
        selected = self.selected_role()
        self.tree.delete(*self.tree.get_children())
        self.roles = {}
        if not result.ok:
            self._update_actions()
            _replace_text(self.details, {"available": False, "code": result.code, "message": result.message})
            return
        for raw in result.data.get("roles", []):
            if not isinstance(raw, dict):
                continue
            role = str(raw.get("role", ""))
            if not role:
                continue
            self.roles[role] = raw
            active = str(raw.get("active") or "—")
            preferred = str(raw.get("preferred") or "—")
            self.tree.insert("", "end", iid=role, values=(f"{role}  →  {active}", preferred))
        if self._requested_role in self.roles:
            self.tree.selection_set(str(self._requested_role))
            self._requested_role = None
        elif selected in self.roles:
            self.tree.selection_set(selected)
        elif self.roles:
            self.tree.selection_set(next(iter(self.roles)))
        self._selected()
        if (
            self.selected_role() == "display-output"
            and self.migration.record.get("phase") == "rolled-back"
        ):
            _replace_text(
                self.details,
                {
                    "display_migration": self.migration.record,
                    "active_role": self.roles.get("display-output", {}),
                    "note": self.app.tr("roles.migration_not_selected"),
                },
            )

    def selected_role(self) -> str:
        selection = self.tree.selection()
        return selection[0] if selection else ""

    def focus_role(self, role: str) -> None:
        target = role_focus_target(role, self.roles)
        self._requested_role = role if target is None else None
        if target is not None:
            self.tree.selection_set(target)
            self.tree.see(target)
            self._selected()

    def _selected(self, _event: Any = None) -> None:
        role = self.selected_role()
        info = self.roles.get(role, {})
        candidates = [
            str(item.get("component"))
            for item in info.get("candidates", [])
            if isinstance(item, dict) and item.get("component")
        ]
        self.provider_box.configure(values=candidates)
        current = str(info.get("preferred") or info.get("active") or "")
        self.provider.set(current if current in candidates else (candidates[0] if candidates else ""))
        self._update_actions()
        _replace_text(
            self.details,
            info or {"hint": self.app.tr("roles.select_role")},
        )

    def _update_actions(self, _event: Any = None) -> None:
        role = self.selected_role()
        has_role = role in self.roles
        display_pending = role == "display-output" and (
            self._display_request_pending or self.migration.active_id is not None
        )
        self.switch_button.configure(
            state=(
                "normal"
                if has_role and bool(self.provider.get()) and not display_pending
                else "disabled"
            )
        )
        self.reset_button.configure(
            state="normal" if has_role and not display_pending else "disabled"
        )

    def switch(self) -> None:
        role, provider = self.selected_role(), self.provider.get()
        if role == "display-output":
            self._display_request_started(provider)
        self.app.run_task(
            self.app.tr("status.switching_role"),
            lambda: self.app.model.select_role(role, provider),
            lambda result: self._changed(result, role),
        )

    def reset(self) -> None:
        role = self.selected_role()
        if role == "display-output":
            self._display_request_started(self.app.tr("roles.default_provider"))
        self.app.run_task(
            self.app.tr("status.resetting_role"),
            lambda: self.app.model.reset_role(role),
            lambda result: self._changed(result, role),
        )

    def _changed(self, result: OperationResult, role: str) -> bool:
        if result.ok and role == "display-output":
            migration = result.data.get("migration")
            if isinstance(migration, dict):
                handled = self.app.handle_display_migration(migration)
                migration_id = migration.get("id")
                if handled or migration_id in {
                    self.migration.active_id,
                    self.migration.last_terminal_id,
                }:
                    return True
            self._display_request_pending = False
            self._restore_display_choice()
            self.migration_status.set(self.app.tr("roles.migration_invalid"))
            self.migration_status_label.configure(style="Error.TLabel")
            _replace_text(
                self.details,
                {
                    "code": "DISPLAY_MIGRATION_BAD_RESPONSE",
                    "message": self.app.tr("roles.migration_bad_response"),
                    "response": result.data,
                },
            )
            self._update_actions()
            self.app.set_status(
                self.app.tr("roles.migration_core_invalid"),
                error=True,
            )
            return True
        elif result.ok:
            self.refresh()
            return True
        else:
            self._display_request_pending = False
            if role == "display-output":
                self._restore_display_choice()
                self.migration_status.set(
                    self.app.tr(
                        "roles.migration_request_failed",
                        {"code": result.code or "RPC_ERROR"},
                    )
                )
                self.migration_status_label.configure(style="Error.TLabel")
            _replace_text(
                self.details,
                {
                    "code": result.code,
                    "message": result.message,
                    "details": result.data,
                },
            )
            self._update_actions()
        return False

    def _display_request_started(self, requested: str) -> None:
        self._display_request_pending = True
        self.migration_status.set(
            self.app.tr(
                "roles.migration_pending_request",
                {"provider": requested},
            )
        )
        self.migration_status_label.configure(style="Muted.TLabel")
        _replace_text(
            self.details,
            {
                "phase": "requesting",
                "role": "display-output",
                "requested_provider": requested,
                "active_provider": self.roles.get("display-output", {}).get("active"),
            },
        )
        self._update_actions()

    def display_migration(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            record = self.migration.consume(payload)
        except (TypeError, ValueError) as exc:
            self.migration_status.set(self.app.tr("roles.migration_event_invalid"))
            self.migration_status_label.configure(style="Error.TLabel")
            _replace_text(
                self.details,
                {
                    "code": "DISPLAY_MIGRATION_BAD_RESPONSE",
                    "message": str(exc),
                    "payload": payload,
                },
            )
            self.app.set_status(str(exc), error=True)
            return None
        if record is None:
            return None

        self._display_request_pending = False
        migration_id = int(record["id"])
        phase = str(record["phase"])
        source = str(
            record.get("from_provider") or self.app.tr("common.unavailable")
        )
        target = str(
            record.get("to_provider") or self.app.tr("roles.default_provider")
        )
        if phase in {"planned", "switching"}:
            self.migration_status.set(
                self.app.tr(
                    "roles.migration_pending",
                    {
                        "id": migration_id,
                        "phase": phase,
                        "source": source,
                        "target": target,
                    },
                )
            )
            self.migration_status_label.configure(style="Muted.TLabel")
            _replace_text(
                self.details,
                {
                    "display_migration": record,
                    "note": self.app.tr("roles.migration_active_unchanged"),
                },
            )
            self._schedule_migration_poll(migration_id)
        elif phase == "succeeded":
            self.migration_status.set(
                self.app.tr(
                    "roles.migration_succeeded",
                    {"id": migration_id, "provider": target},
                )
            )
            self.migration_status_label.configure(style="Success.TLabel")
            _replace_text(self.details, {"display_migration": record})
        else:
            error = record.get("error", {})
            code = str(error.get("code") or "DISPLAY_MIGRATION_FAILED")
            message = str(
                error.get("message")
                or self.app.tr("roles.migration_rollback_fallback")
            )
            self._restore_display_choice()
            self.migration_status.set(
                self.app.tr(
                    "roles.migration_rolled_back",
                    {"id": migration_id, "code": code, "message": message},
                )
            )
            self.migration_status_label.configure(style="Error.TLabel")
            _replace_text(
                self.details,
                {
                    "display_migration": record,
                    "active_provider": self.roles.get("display-output", {}).get("active"),
                    "note": self.app.tr("roles.migration_not_selected"),
                },
            )
        self._update_actions()
        return record

    def _restore_display_choice(self) -> None:
        if self.selected_role() != "display-output":
            return
        info = self.roles.get("display-output", {})
        active = str(info.get("active") or "")
        candidates = tuple(self.provider_box.cget("values"))
        self.provider.set(active if active in candidates else "")

    def _schedule_migration_poll(self, migration_id: int) -> None:
        if self._poll_scheduled_for == migration_id:
            return
        self._poll_scheduled_for = migration_id
        self.app.root.after(
            600,
            lambda selected=migration_id: self._poll_migration(selected),
        )

    def _poll_migration(self, migration_id: int) -> None:
        self._poll_scheduled_for = None
        if self.migration.active_id != migration_id or self.app._closed:
            return
        self.app.run_task(
            self.app.tr("status.checking_migration", {"id": migration_id}),
            lambda: self.app.model.display_migration_status(migration_id),
            lambda result: self._migration_status_result(migration_id, result),
        )

    def _migration_status_result(
        self,
        migration_id: int,
        result: OperationResult,
    ) -> bool:
        if self.migration.active_id != migration_id:
            return True
        if result.ok:
            handled = self.app.handle_display_migration(result.data)
        else:
            handled = False
            self.migration_status.set(
                self.app.tr(
                    "roles.migration_status_unavailable",
                    {"id": migration_id},
                )
            )
            _replace_text(
                self.details,
                {
                    "display_migration": self.migration.record,
                    "status_error": {
                        "code": result.code,
                        "message": result.message,
                        "details": result.data,
                    },
                },
            )
        if self.migration.active_id == migration_id:
            self._schedule_migration_poll(migration_id)
        return handled


class HalPage(BasePage):
    title_key = "hal.title"
    note_key = "hal.note"

    def __init__(self, parent: ttk.Frame, app: SettingsApplication) -> None:
        super().__init__(parent, app)
        self.devices: dict[str, dict[str, Any]] = {}
        self.domains: dict[str, dict[str, Any]] = {}
        self._requested_domain: str | None = None
        self.provider_management = False
        self.provider_status: dict[str, Any] = {"available": False}
        self._provider_candidates: dict[str, dict[str, Any]] = {}
        self._provider_revision = 0
        self._provider_notice = ""
        self._loaded_values: dict[str, Any] = {}
        self._mutable_fields: list[str] = []
        self._loaded_device = ""
        self._loaded_revision = 0
        self._state_generation = 0
        self._ch347_generation = 0
        self._ch347_state: dict[str, Any] = {}
        self._ch347_dialog: Ch347ControlDialog | None = None
        self.surface = ScrollableSurface(self, background=PANEL)
        self.surface.pack(fill="both", expand=True)
        container = self.surface.content
        self.hal_card_title = tk.StringVar(value=app.tr("common.status"))
        self.hal_summary = tk.StringVar(value=app.tr("common.not_loaded"))
        self.hal_status_card = MaterialStatusCard(
            container,
            title=self.hal_card_title,
            body=self.hal_summary,
            compact=app.compact,
        )
        self.hal_status_card.pack(fill="x", pady=(0, 8))
        domain_row = ttk.Frame(container, style="Panel.TFrame")
        domain_row.pack(fill="x", pady=(0, 4))
        ttk.Label(domain_row, text=app.tr("hal.domain"), style="Muted.TLabel").pack(side="left")
        self.domain = tk.StringVar()
        self.domain_box = ttk.Combobox(
            domain_row,
            textvariable=self.domain,
            state="readonly",
            width=18,
        )
        self.domain_box.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.domain_box.bind("<<ComboboxSelected>>", self._domain_selected)
        self.domain_status = tk.StringVar(value="")
        self.domain_status_label = ttk.Label(
            container,
            textvariable=self.domain_status,
            style="Muted.TLabel",
            justify="left",
            wraplength=286 if app.compact else 720,
        )
        self.domain_status_label.pack(anchor="w", fill="x", pady=(0, 4))

        provider_row = ttk.Frame(container, style="Panel.TFrame")
        provider_row.pack(fill="x", pady=(0, 4))
        ttk.Label(provider_row, text=app.tr("common.provider"), style="Muted.TLabel").pack(side="left")
        self.provider = tk.StringVar()
        self.provider_box = ttk.Combobox(
            provider_row,
            textvariable=self.provider,
            state="readonly",
        )
        self.provider_box.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.provider_box.bind("<<ComboboxSelected>>", self._provider_selected)
        self.provider_detail = tk.StringVar(value=app.tr("hal.provider_health_not_loaded"))
        self.provider_detail_label = ttk.Label(
            container,
            textvariable=self.provider_detail,
            style="Muted.TLabel",
            justify="left",
            wraplength=286 if app.compact else 720,
        )
        self.provider_detail_label.pack(anchor="w", fill="x", pady=(0, 4))
        for label in (self.domain_status_label, self.provider_detail_label):
            label.bind(
                "<Configure>",
                lambda event, target=label: target.configure(
                    wraplength=text_wrap_length(
                        int(event.width), horizontal_padding=4
                    )
                ),
            )
        provider_actions = ttk.Frame(container, style="Panel.TFrame")
        provider_actions.pack(fill="x", pady=(0, 6))
        self.switch_button = ttk.Button(
            provider_actions,
            text=app.tr("common.select" if app.compact else "common.use_provider"),
            command=self.select_provider,
            state="disabled",
        )
        self.switch_button.pack(side="left")
        self.reset_button = ttk.Button(
            provider_actions,
            text=app.tr("common.automatic" if app.compact else "common.use_automatic"),
            command=self.reset_provider,
            state="disabled",
        )
        self.reset_button.pack(side="left", padx=6)

        tree_frame = ttk.Frame(container, style="Panel.TFrame")
        tree_frame.pack(fill="x")
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("device", "kind", "provider"),
            show="headings",
            height=2 if app.compact else 5,
            selectmode="browse",
        )
        for column, label, width in (
            ("device", app.tr("common.device"), 240),
            ("kind", app.tr("common.kind"), 120),
            ("provider", app.tr("common.provider"), 260),
        ):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, anchor="w")
        if app.compact:
            self.tree.configure(displaycolumns=("device",))
            self.tree.column("device", width=210, minwidth=80, stretch=True)
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="x", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        self.ch347_panel = ttk.Frame(container, style="Panel.TFrame")
        self.ch347_summary = tk.StringVar(value=app.tr("ch347.not_loaded"))
        self.ch347_status_label = ttk.Label(
            self.ch347_panel,
            textvariable=self.ch347_summary,
            style="Muted.TLabel",
            justify="left",
            wraplength=205 if app.compact else 620,
        )
        self.ch347_status_label.pack(side="left", fill="x", expand=True)
        self.ch347_button = ttk.Button(
            self.ch347_panel,
            text=app.tr("common.control") if app.compact else app.tr("ch347.controls"),
            command=self.open_ch347_controls,
            state="disabled",
        )
        self.ch347_button.pack(side="right", padx=(6, 0))
        state_actions = ttk.Frame(container, style="Panel.TFrame")
        state_actions.pack(fill="x", pady=(6, 4))
        ttk.Button(
            state_actions,
            text=app.tr("common.refresh" if app.compact else "common.refresh_inventory"),
            command=self.refresh,
        ).pack(side="left")
        self.read_button = ttk.Button(
            state_actions,
            text=app.tr("common.read" if app.compact else "common.read_state"),
            command=self.read_state,
            state="disabled",
        )
        self.read_button.pack(side="left", padx=6)
        self.apply_button = ttk.Button(
            state_actions,
            text=app.tr("common.apply" if app.compact else "common.apply_changes"),
            style="Accent.TButton",
            command=self.apply_state,
            state="disabled",
        )
        self.apply_button.pack(side="left")
        self.ch347_compact_button: ttk.Button | None = None
        if app.compact:
            self.ch347_compact_button = ttk.Button(
                state_actions,
                text="CH347",
                command=self.open_ch347_controls,
                state="disabled",
            )
        state_box = ttk.Frame(container, style="Panel.TFrame")
        state_box.pack(fill="x")
        self.state = tk.Text(
            state_box,
            bg=FIELD_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            padx=10,
            pady=8,
            wrap="word",
            height=4,
        )
        state_scroll = ttk.Scrollbar(
            state_box,
            orient="vertical",
            command=self.state.yview,
        )
        self.state.configure(yscrollcommand=state_scroll.set)
        state_scroll.pack(side="right", fill="y")
        self.state.pack(side="left", fill="both", expand=True)
        self._show_state_document(
            {"hint": app.tr("hal.select_device_hint")},
            editable=False,
        )

    def refresh(self) -> None:
        self.hal_status_card.set_color(PANEL_ALT)
        self.app.run_task(
            self.app.tr("status.reading_hal_inventory"),
            lambda: self.app.model.hal_inventory(refresh=True),
            self._loaded_result,
        )

    def _loaded_result(self, result: OperationResult) -> None:
        selected = self.selected_device()
        selected_domain = self.domain.get()
        requested_domain = self._requested_domain
        self.tree.delete(*self.tree.get_children())
        self.devices = {}
        self.domains = {}
        self.provider_management = False
        self.provider_status = {"available": False}
        self._provider_candidates = {}
        self._provider_revision = 0
        self._invalidate_state()
        if not result.ok:
            self.hal_status_card.set_color(ERROR_CONTAINER)
            notice = self._provider_notice
            self._provider_notice = ""
            self.domain_box.configure(values=[])
            self.domain.set("")
            self.provider_box.configure(values=[])
            self.provider.set("")
            self.provider_detail.set(self.app.tr("hal.provider_health_unavailable"))
            self.domain_status.set(self.app.tr("hal.manager_unavailable"))
            self.domain_status_label.configure(style="Error.TLabel")
            self.hal_summary.set(
                self.app.tr("hal.reload_failed", {"notice": notice})
                if notice
                else self.app.tr("hal.hardware_unavailable")
            )
            if notice:
                self.app.set_status(
                    self.app.tr("hal.reload_failed", {"notice": notice}),
                    error=True,
                )
            self._update_actions()
            self._show_state_document({
                "available": False,
                "interface": "org.msys.hal.manager.v1",
                "code": result.code,
                "message": result.message
                or self.app.tr("hal.manager_not_running"),
                "details": result.data,
                "hint": self.app.tr("hal.other_pages_available"),
            }, editable=False)
            return
        self.hal_status_card.set_color(PANEL_ALT)
        self.provider_management = bool(
            result.data.get("provider_management", {}).get("available")
        )
        raw_management = result.data.get("provider_management", {})
        self.provider_status = (
            dict(raw_management) if isinstance(raw_management, dict) else {"available": False}
        )
        revision = result.data.get("revision", 0)
        self._provider_revision = (
            revision
            if isinstance(revision, int)
            and not isinstance(revision, bool)
            and revision >= 0
            else 0
        )
        for item in result.data.get("domains", []):
            if not isinstance(item, dict) or not item.get("domain"):
                continue
            self.domains[str(item["domain"])] = item
        unavailable = sum(
            1 for item in self.domains.values() if item.get("status") == "unavailable"
        )
        domain_names = list(self.domains)
        self.domain_box.configure(values=domain_names)
        if requested_domain in self.domains:
            self.domain.set(str(requested_domain))
        elif selected_domain in self.domains:
            self.domain.set(selected_domain)
        elif domain_names:
            self.domain.set(domain_names[0])
        else:
            self.domain.set("")
        for device in result.data.get("devices", []):
            device_id = str(device.get("id", ""))
            if not device_id:
                continue
            self.devices[device_id] = device
            self.tree.insert(
                "", "end", iid=device_id,
                values=(device.get("name", device_id), device.get("kind", "device"), device.get("provider", "—")),
            )
        summary = self.app.tr(
            "hal.summary",
            {"domains": len(self.domains), "devices": len(self.devices)},
        )
        if unavailable:
            summary += " · " + self.app.tr(
                "hal.summary_unavailable",
                {"count": unavailable},
            )
        inventory_status = result.data.get("inventory_status", {})
        inventory_available = not isinstance(inventory_status, dict) or bool(
            inventory_status.get("available", True)
        )
        if not inventory_available:
            summary += " · " + self.app.tr("hal.summary_inventory_unavailable")
        if not self.provider_management:
            summary += " · " + self.app.tr(
                "hal.summary_provider_controls_unavailable"
            )
        self.hal_summary.set(summary)
        selected_info = self.devices.get(selected, {})
        if selected in self.devices and (
            requested_domain not in self.domains
            or selected_info.get("domain") == requested_domain
        ):
            self.tree.selection_set(selected)
        elif requested_domain in self.domains:
            matching = next(
                (
                    identifier
                    for identifier, device in self.devices.items()
                    if device.get("domain") == requested_domain
                ),
                None,
            )
            if matching is not None:
                self.tree.selection_set(matching)
        elif self.devices:
            self.tree.selection_set(next(iter(self.devices)))
        if requested_domain in self.domains:
            self._requested_domain = None
        if self.selected_device():
            self._selected()
        else:
            self._update_ch347_panel({})
            self._domain_selected()
        management = result.data.get("provider_management", {})
        if not inventory_available and self.provider_management:
            self.app.set_status(
                self.app.tr("hal.inventory_partial"),
                error=True,
            )
        elif not self.provider_management and isinstance(management, dict):
            self.app.set_status(
                str(
                    management.get("message")
                    or self.app.tr("hal.provider_management_unavailable")
                ),
                error=True,
            )
        if self._provider_notice:
            notice = self._provider_notice
            self._provider_notice = ""
            self.hal_summary.set(f"{summary} | {notice}")
            self.app.set_status(notice, error=True)

    def selected_device(self) -> str:
        selection = self.tree.selection()
        return selection[0] if selection else ""

    def focus_domain(self, domain: str) -> None:
        target_domain, target_device = hal_focus_target(
            domain,
            self.domains,
            self.devices,
        )
        self._requested_domain = domain if target_domain is None else None
        if target_domain is None:
            return
        self.domain.set(target_domain)
        if target_device is not None:
            self.tree.selection_set(target_device)
            self.tree.see(target_device)
            self._selected()
        else:
            self._domain_selected()

    def _selected(self, _event: Any = None) -> None:
        device = self.devices.get(self.selected_device(), {})
        device_domain = str(device.get("domain", ""))
        if device_domain in self.domains:
            self.domain.set(device_domain)
        self._domain_selected(show_details=False)
        self._update_ch347_panel(device)
        self._update_actions()
        self._invalidate_state()
        self._show_state_document({
            "device": device.get("id", ""),
            "available": device.get("available", False),
            "mutable": device.get("mutable", []),
            "metadata": device.get("metadata", {}),
            **(
                {"provider_management": self.provider_status}
                if not self.provider_management
                else {}
            ),
            "hint": (
                self.app.tr("hal.read_editable_hint")
                if device.get("available", False)
                else self.app.tr("hal.device_unavailable_hint")
            ),
        }, editable=False)

    def _domain_selected(self, _event: Any = None, *, show_details: bool = True) -> None:
        info = self.domains.get(self.domain.get(), {})
        self._provider_candidates = {
            str(item.get("component")): dict(item)
            for item in info.get("candidates", [])
            if isinstance(item, dict) and item.get("component")
        }
        candidates = list(self._provider_candidates)
        active = str(info.get("active") or "")
        if active and active not in candidates:
            candidates.insert(0, active)
            self._provider_candidates[active] = {
                "component": active,
                "capabilities": [],
                "health": {
                    "status": "unknown",
                    "reason": "not-reported",
                    "reported": False,
                },
                "selectable": True,
                "active": True,
            }
        self.provider_box.configure(values=candidates)
        self.provider.set(active if active else (candidates[0] if candidates else ""))
        self._show_provider_detail()
        status = str(info.get("status") or "unknown")
        reason = str(info.get("reason") or info.get("error") or "")
        self.domain_status.set(
            " · ".join(
                part
                for part in (
                    self.domain.get(),
                    _known_state_label(self.app, status),
                    reason,
                )
                if part
            )
        )
        self.domain_status_label.configure(
            style="Error.TLabel" if status == "unavailable" else "Muted.TLabel"
        )
        self._update_actions()
        if show_details:
            self._invalidate_state()
            self._show_state_document(
                {
                    **(info if info else {
                    "available": False,
                    "message": self.app.tr("hal.no_domains"),
                    }),
                    **(
                        {"provider_management": self.provider_status}
                        if not self.provider_management
                        else {}
                    ),
                },
                editable=False,
            )

    def _provider_selected(self, _event: Any = None) -> None:
        self._show_provider_detail()
        self._update_actions()

    def _show_provider_detail(self) -> None:
        candidate = self._provider_candidates.get(self.provider.get(), {})
        if not candidate:
            self.provider_detail.set(self.app.tr("hal.no_candidate"))
            self.provider_detail_label.configure(style="Muted.TLabel")
            return
        health = candidate.get("health", {})
        health = health if isinstance(health, dict) else {}
        status = str(health.get("status") or "unknown")
        reason = str(health.get("reason") or "")
        parts = [_known_state_label(self.app, status)]
        if reason and reason not in {"healthy", "not-reported"}:
            parts.append(reason)
        latency = health.get("latency_ms")
        if isinstance(latency, int) and not isinstance(latency, bool):
            parts.append(self.app.tr("hal.provider_latency", {"latency": latency}))
        capabilities = candidate.get("capabilities", [])
        capabilities = capabilities if isinstance(capabilities, list) else []
        limit = 2 if self.app.compact else 4
        if capabilities:
            shown = ", ".join(str(item) for item in capabilities[:limit])
            if len(capabilities) > limit:
                shown += f" (+{len(capabilities) - limit})"
            parts.append(shown)
        elif not health.get("reported", False):
            parts.append(self.app.tr("hal.legacy_health_not_reported"))
        if not candidate.get("selectable", True):
            parts.append(self.app.tr("hal.selection_disabled"))
        self.provider_detail.set(" | ".join(parts))
        self.provider_detail_label.configure(
            style="Error.TLabel" if status == "unavailable" else "Muted.TLabel"
        )

    def _update_actions(self) -> None:
        domain = self.domain.get()
        candidates = tuple(self.provider_box.cget("values"))
        can_manage = self.provider_management and bool(domain)
        candidate = self._provider_candidates.get(self.provider.get(), {})
        can_select = (
            can_manage
            and bool(self.provider.get())
            and bool(candidates)
            and bool(candidate.get("selectable", True))
        )
        self.switch_button.configure(state="normal" if can_select else "disabled")
        self.reset_button.configure(state="normal" if can_manage else "disabled")
        device = self.devices.get(self.selected_device(), {})
        can_read = bool(device) and bool(device.get("available", False))
        self.read_button.configure(state="normal" if can_read else "disabled")
        self.apply_button.configure(state="disabled")

    @staticmethod
    def _is_ch347_device(device: dict[str, Any]) -> bool:
        metadata = device.get("metadata", {})
        return (
            device.get("id") == CH347_DEVICE
            and isinstance(metadata, dict)
            and metadata.get("control_interface") == CH347_CONTROL_SCHEMA
        )

    def _update_ch347_panel(self, device: dict[str, Any]) -> None:
        self._ch347_generation += 1
        generation = self._ch347_generation
        if not self._is_ch347_device(device):
            self.ch347_panel.pack_forget()
            self.ch347_button.configure(state="disabled")
            if self.ch347_compact_button is not None:
                self.ch347_compact_button.pack_forget()
            self._ch347_state = {}
            if self._ch347_dialog is not None:
                self._ch347_dialog.close()
            return
        if self.app.compact:
            if self.ch347_compact_button is not None:
                self.ch347_compact_button.pack(side="left", padx=(6, 0))
        else:
            self.ch347_panel.pack(
                fill="x",
                pady=(6, 0),
                before=self.read_button.master,
            )
        self.ch347_summary.set(self.app.tr("status.reading_ch347"))
        if self.app.compact:
            self.hal_summary.set(self.ch347_summary.get())
        self.ch347_status_label.configure(style="Muted.TLabel")
        self.ch347_button.configure(state="normal")
        if self.ch347_compact_button is not None:
            self.ch347_compact_button.configure(state="normal")
        self.app.run_task(
            self.app.tr("status.reading_ch347"),
            self.app.model.ch347_status,
            lambda result: self._ch347_status_result(result, generation),
        )

    def _ch347_status_result(
        self,
        result: OperationResult,
        generation: int,
    ) -> bool:
        if generation != self._ch347_generation:
            return True
        if not result.ok:
            self._ch347_state = {}
            self.ch347_summary.set(
                self.app.tr(
                    "ch347.control_unavailable",
                    {"message": result.message or result.code},
                )
            )
            self.ch347_status_label.configure(style="Error.TLabel")
            if self.app.compact:
                self.hal_summary.set(self.app.tr("ch347.typed_unavailable"))
            if self._ch347_dialog is not None:
                self._ch347_dialog.show_result(result)
            return True
        state = result.data.get("state", {})
        self._ch347_state = dict(state) if isinstance(state, dict) else {}
        status = str(self._ch347_state.get("status") or "unavailable")
        running = "running" if self._ch347_state.get("running") else "stopped"
        fps = self._ch347_state.get("fps", "?")
        idle = self._ch347_state.get("idle_fps", "?")
        self.ch347_summary.set(
            self.app.tr(
                "ch347.summary",
                {
                    "status": _known_state_label(self.app, status),
                    "running": _known_state_label(self.app, running),
                    "fps": fps,
                    "idle_fps": idle,
                },
            )
        )
        self.ch347_status_label.configure(
            style="Error.TLabel" if status != "available" else "Success.TLabel"
        )
        if self.app.compact:
            self.hal_summary.set(self.ch347_summary.get())
        if self._ch347_dialog is not None:
            self._ch347_dialog.load_state(self._ch347_state)
        return True

    def open_ch347_controls(self) -> None:
        if self._ch347_dialog is not None:
            self._ch347_dialog.window.deiconify()
            self._ch347_dialog.window.lift()
            return
        self._ch347_dialog = Ch347ControlDialog(
            self.app,
            self._ch347_state,
            on_close=self._ch347_dialog_closed,
            on_state=self._ch347_dialog_state,
        )

    def _ch347_dialog_closed(self) -> None:
        self._ch347_dialog = None

    def _ch347_dialog_state(self, state: dict[str, Any]) -> None:
        self._ch347_state = dict(state)
        status = str(state.get("status") or "unavailable")
        running = "running" if state.get("running") else "stopped"
        self.ch347_summary.set(
            self.app.tr(
                "ch347.summary",
                {
                    "status": _known_state_label(self.app, status),
                    "running": _known_state_label(self.app, running),
                    "fps": state.get("fps", "?"),
                    "idle_fps": state.get("idle_fps", "?"),
                },
            )
        )
        self.ch347_status_label.configure(
            style="Error.TLabel" if status != "available" else "Success.TLabel"
        )
        if self.app.compact:
            self.hal_summary.set(self.ch347_summary.get())

    def read_state(self) -> None:
        device = self.selected_device()
        self._state_generation += 1
        generation = self._state_generation
        self.apply_button.configure(state="disabled")
        self.app.run_task(
            self.app.tr("status.reading_hal_state"),
            lambda: self.app.model.hal_get_state(device),
            lambda result: self._state_result(result, device, generation),
        )

    def apply_state(self) -> None:
        device = self.selected_device()
        if not device or device != self._loaded_device:
            messagebox.showerror(
                self.app.tr("hal.state_changed_title"),
                self.app.tr("hal.state_changed_body"),
                parent=self.app.root,
            )
            return
        try:
            state = json.loads(self.state.get("1.0", "end-1c"))
        except json.JSONDecodeError as exc:
            messagebox.showerror(self.app.tr("hal.invalid_json"), str(exc), parent=self.app.root)
            return
        if not isinstance(state, dict):
            messagebox.showerror(
                self.app.tr("hal.invalid_changes"),
                self.app.tr("hal.changes_object"),
                parent=self.app.root,
            )
            return
        try:
            changes = hal_state_changes(
                self._loaded_values,
                state,
                self._mutable_fields,
            )
        except ValueError as exc:
            messagebox.showerror(self.app.tr("hal.invalid_changes"), str(exc), parent=self.app.root)
            self.app.set_status(str(exc), error=True)
            return
        self._state_generation += 1
        generation = self._state_generation
        self.apply_button.configure(state="disabled")
        self.app.run_task(
            self.app.tr("status.applying_hal_state"),
            lambda: self.app.model.hal_set_state(device, changes),
            lambda result: self._state_result(result, device, generation),
        )

    def select_provider(self) -> None:
        domain, provider = self.domain.get(), self.provider.get()
        expected_revision = self._provider_revision
        self._invalidate_state()
        self.apply_button.configure(state="disabled")
        self.app.run_task(
            self.app.tr("status.switching_hal_provider"),
            lambda: self.app.model.select_hal_provider(
                domain,
                provider,
                expected_revision=expected_revision,
            ),
            self._provider_result,
        )

    def reset_provider(self) -> None:
        domain = self.domain.get()
        expected_revision = self._provider_revision
        self._invalidate_state()
        self.apply_button.configure(state="disabled")
        self.app.run_task(
            self.app.tr("status.resetting_hal_provider"),
            lambda: self.app.model.reset_hal_provider(
                domain,
                expected_revision=expected_revision,
            ),
            self._provider_result,
        )

    def _state_result(
        self,
        result: OperationResult,
        requested_device: str,
        generation: int,
    ) -> None:
        if (
            generation != self._state_generation
            or requested_device != self.selected_device()
        ):
            return
        if result.ok:
            values = result.data.get("values", {})
            mutable = result.data.get("mutable", [])
            self._loaded_values = dict(values) if isinstance(values, dict) else {}
            self._mutable_fields = list(mutable) if isinstance(mutable, list) else []
            self._loaded_device = requested_device
            revision = result.data.get("revision", 0)
            self._loaded_revision = (
                revision
                if isinstance(revision, int) and not isinstance(revision, bool)
                else 0
            )
            available = bool(result.data.get("available", True))
            self._show_state_document(
                self._loaded_values,
                editable=available and bool(self._mutable_fields),
            )
            self.apply_button.configure(
                state="normal" if available and self._mutable_fields else "disabled"
            )
            if not available:
                self.hal_summary.set(self.app.tr("hal.selected_unavailable"))
            elif not self._mutable_fields:
                self.hal_summary.set(self.app.tr("hal.state_readonly"))
            else:
                self.hal_summary.set(
                    self.app.tr(
                        "hal.editable",
                        {"fields": ", ".join(self._mutable_fields)},
                    )
                )
        else:
            self._loaded_values = {}
            self._mutable_fields = []
            self._loaded_device = ""
            self._loaded_revision = 0
            self.apply_button.configure(state="disabled")
            self._show_state_document({
                "available": False,
                "code": result.code,
                "message": result.message,
                "details": result.data,
            }, editable=False)

    def _provider_result(self, result: OperationResult) -> None:
        if result.ok:
            self.refresh()
        elif result.code == "HAL_CONFLICT":
            self._provider_notice = self.app.tr("hal.provider_conflict_reloaded")
            self.hal_summary.set(self._provider_notice)
            self.app.set_status(self._provider_notice, error=True)
            self._invalidate_state()
            self.apply_button.configure(state="disabled")
            self.refresh()
        else:
            self._invalidate_state()
            self.apply_button.configure(state="disabled")
            self._show_state_document({
                "available": False,
                "code": result.code,
                "message": result.message,
                "details": result.data,
            }, editable=False)

    def _invalidate_state(self) -> None:
        self._state_generation += 1
        self._loaded_device = ""
        self._loaded_revision = 0
        self._loaded_values = {}
        self._mutable_fields = []

    def _show_state_document(self, value: Any, *, editable: bool) -> None:
        self.state.configure(state="normal")
        self.state.delete("1.0", "end")
        self.state.insert("1.0", _json(value))
        if not editable:
            self.state.configure(state="disabled")

    def external_change(self, payload: dict[str, Any]) -> None:
        domain = str(payload.get("domain") or "hardware")
        revision = payload.get("revision")
        if (
            isinstance(revision, int)
            and not isinstance(revision, bool)
            and revision <= max(self._loaded_revision, self._provider_revision)
        ):
            return
        if str(self.state.cget("state")) == "disabled" and self.app._active_page == "hal":
            self.refresh()
            return
        self.hal_summary.set(
            self.app.tr("hal.domain_changed", {"domain": domain})
        )


class Ch347ControlDialog:
    """Touch-friendly editor for the optional typed CH347 control contract."""

    TOUCH_LABEL_KEYS = {
        "enabled": "ch347.touch.enabled",
        "swap_xy": "ch347.touch.swap_xy",
        "invert_x": "ch347.touch.invert_x",
        "invert_y": "ch347.touch.invert_y",
        "x_min": "ch347.touch.x_min",
        "x_max": "ch347.touch.x_max",
        "y_min": "ch347.touch.y_min",
        "y_max": "ch347.touch.y_max",
        "width": "ch347.touch.width",
        "height": "ch347.touch.height",
        "z_min": "ch347.touch.z_min",
        "pressure_min": "ch347.touch.pressure_min",
        "pressure_max": "ch347.touch.pressure_max",
    }

    def __init__(
        self,
        app: SettingsApplication,
        initial_state: dict[str, Any],
        *,
        on_close: Callable[[], None],
        on_state: Callable[[dict[str, Any]], None],
    ) -> None:
        self.app = app
        self.on_close = on_close
        self.on_state = on_state
        self.state: dict[str, Any] = {}
        self._closed = False
        self._busy = False
        self.window = tk.Toplevel(app.root, bg=BG, class_="org.msys.settings.ch347")
        self.window.title(app.tr("ch347.window_title"))
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.transient(app.root)
        if app.compact:
            self.window.geometry("320x480+0+0")
        else:
            self.window.geometry("660x620+40+40")

        header = ttk.Frame(self.window, padding=(10, 8))
        header.pack(fill="x")
        ttk.Label(
            header,
            text=app.tr("ch347.control_title"),
            style="Title.TLabel",
        ).pack(side="left")
        self.refresh_button = ttk.Button(
            header,
            text=app.tr("common.refresh"),
            command=self.refresh,
        )
        self.refresh_button.pack(side="right")

        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        output = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 8))
        touch = ttk.Frame(self.notebook, style="Panel.TFrame")
        self.notebook.add(output, text=app.tr("ch347.output"))
        self.notebook.add(touch, text=app.tr("ch347.touch"))

        self.status = tk.StringVar(value=app.tr("ch347.typed_not_loaded"))
        self.status_label = ttk.Label(
            output,
            textvariable=self.status,
            style="Muted.TLabel",
            font=font_spec(self.window, 11 if app.compact else 13, "bold"),
        )
        self.status_label.pack(anchor="w", fill="x")
        self.details = tk.StringVar(value=app.tr("ch347.reading_live"))
        ttk.Label(
            output,
            textvariable=self.details,
            style="Muted.TLabel",
            wraplength=280 if app.compact else 590,
            justify="left",
        ).pack(anchor="w", fill="x", pady=(3, 12))

        fps_group = ttk.LabelFrame(output, text=app.tr("ch347.frame_rate"), padding=(8, 7))
        fps_group.pack(fill="x", pady=(0, 10))
        self.fps = tk.StringVar()
        self.idle_fps = tk.StringVar()
        self.fps_inputs: list[tk.Widget] = []
        for row, (label, variable, start, end) in enumerate((
            (app.tr("ch347.active_fps"), self.fps, 1, 240),
            (app.tr("ch347.idle_fps"), self.idle_fps, 0, 60),
        )):
            ttk.Label(fps_group, text=label).grid(row=row, column=0, sticky="w", pady=3)
            spin = ttk.Spinbox(
                fps_group,
                from_=start,
                to=end,
                textvariable=variable,
                width=8,
            )
            spin.grid(row=row, column=1, sticky="e", padx=(8, 0), pady=3)
            self.fps_inputs.append(spin)
        fps_group.columnconfigure(0, weight=1)
        self.apply_fps_button = ttk.Button(
            fps_group,
            text=app.tr("ch347.apply_frame_rates"),
            style="Accent.TButton",
            command=self.apply_fps,
        )
        self.apply_fps_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        self.fps_inputs.append(self.apply_fps_button)

        restart_group = ttk.LabelFrame(output, text=app.tr("ch347.driver"), padding=(8, 7))
        restart_group.pack(fill="x")
        ttk.Label(
            restart_group,
            text=app.tr("ch347.restart_note"),
            wraplength=260 if app.compact else 560,
            justify="left",
        ).pack(anchor="w", fill="x")
        self.restart_button = ttk.Button(
            restart_group,
            text=app.tr("ch347.restart"),
            command=self.restart,
        )
        self.restart_button.pack(fill="x", pady=(7, 0))

        touch_canvas = tk.Canvas(
            touch,
            bg=PANEL,
            highlightthickness=0,
            borderwidth=0,
        )
        touch_scroll = ttk.Scrollbar(
            touch,
            orient="vertical",
            command=touch_canvas.yview,
        )
        touch_canvas.configure(yscrollcommand=touch_scroll.set)
        touch_scroll.pack(side="right", fill="y")
        touch_canvas.pack(side="left", fill="both", expand=True)
        touch_inner = ttk.Frame(touch_canvas, style="Panel.TFrame", padding=(10, 8))
        touch_window = touch_canvas.create_window((0, 0), window=touch_inner, anchor="nw")
        touch_inner.bind(
            "<Configure>",
            lambda _event: touch_canvas.configure(scrollregion=touch_canvas.bbox("all")),
        )
        touch_canvas.bind(
            "<Configure>",
            lambda event: touch_canvas.itemconfigure(touch_window, width=event.width),
        )
        touch_canvas.bind(
            "<MouseWheel>",
            lambda event: touch_canvas.yview_scroll(int(-event.delta / 120), "units"),
        )
        touch_canvas.bind(
            "<ButtonPress-1>",
            lambda event: touch_canvas.scan_mark(event.x, event.y),
        )
        touch_canvas.bind(
            "<B1-Motion>",
            lambda event: touch_canvas.scan_dragto(event.x, event.y, gain=1),
        )

        ttk.Label(
            touch_inner,
            text=app.tr("ch347.calibration_note"),
            style="Muted.TLabel",
            wraplength=260 if app.compact else 560,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 7))
        self.touch_booleans = {
            field: tk.BooleanVar(value=False)
            for field in CH347_CALIBRATION_BOOLEAN_FIELDS
        }
        self.touch_integers = {
            field: tk.StringVar()
            for field in CH347_CALIBRATION_INTEGER_FIELDS
        }
        self.touch_inputs: list[tk.Widget] = []
        row = 1
        for field in CH347_CALIBRATION_BOOLEAN_FIELDS:
            check = ttk.Checkbutton(
                touch_inner,
                text=app.tr(self.TOUCH_LABEL_KEYS[field]),
                variable=self.touch_booleans[field],
            )
            check.grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
            self.touch_inputs.append(check)
            row += 1
        ttk.Separator(touch_inner).grid(
            row=row,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=6,
        )
        row += 1
        for field in CH347_CALIBRATION_INTEGER_FIELDS:
            ttk.Label(touch_inner, text=app.tr(self.TOUCH_LABEL_KEYS[field])).grid(
                row=row,
                column=0,
                sticky="w",
                pady=3,
            )
            entry = ttk.Entry(
                touch_inner,
                textvariable=self.touch_integers[field],
                width=10,
            )
            entry.grid(row=row, column=1, sticky="e", padx=(8, 0), pady=3)
            self.touch_inputs.append(entry)
            row += 1
        touch_inner.columnconfigure(0, weight=1)
        self.apply_touch_button = ttk.Button(
            touch_inner,
            text=app.tr("ch347.apply_touch"),
            style="Accent.TButton",
            command=self.apply_touch,
        )
        self.apply_touch_button.grid(
            row=row,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(9, 8),
        )
        self.touch_inputs.append(self.apply_touch_button)

        self.feedback = tk.StringVar(value=app.tr("ch347.waiting_status"))
        self.feedback_label = ttk.Label(
            self.window,
            textvariable=self.feedback,
            style="Muted.TLabel",
            wraplength=300 if app.compact else 620,
            justify="left",
            padding=(9, 4),
        )
        self.feedback_label.pack(fill="x")

        self._set_control_state(False, False)
        if initial_state:
            self.load_state(initial_state)
        self.window.after(20, self.refresh)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.window.destroy()
        self.on_close()

    def _set_control_state(self, can_configure: bool, can_restart: bool) -> None:
        configure_state = "normal" if can_configure and not self._busy else "disabled"
        for widget in (*self.fps_inputs, *self.touch_inputs):
            widget.configure(state=configure_state)
        self.restart_button.configure(
            state="normal" if can_restart and not self._busy else "disabled"
        )
        self.refresh_button.configure(state="disabled" if self._busy else "normal")

    def _availability(self) -> tuple[bool, bool]:
        can_configure = (
            self.state.get("status") != "unavailable"
            and bool(self.state.get("configuration_provisioned"))
        )
        can_restart = self.state.get("component_state") == "ready"
        return can_configure, can_restart

    def _set_feedback(self, message: str, *, error: bool = False) -> None:
        self.feedback.set(message)
        self.feedback_label.configure(style="Error.TLabel" if error else "Success.TLabel")
        self.app.set_status(message, error=error)

    def load_state(self, state: dict[str, Any]) -> None:
        if self._closed:
            return
        self.state = dict(state)
        status = str(state.get("status") or "unavailable")
        running = bool(state.get("running"))
        self.status.set(
            self.app.tr(
                "ch347.status",
                {
                    "status": _known_state_label(self.app, status),
                    "running": self.app.tr(
                        "ch347.running" if running else "ch347.stopped"
                    ),
                },
            )
        )
        self.status_label.configure(
            style="Success.TLabel" if status == "available" else "Error.TLabel"
        )
        details = [
            str(state.get("reason") or self.app.tr("ch347.reason_unknown")),
            self.app.tr(
                "ch347.detail_component",
                {
                    "component": _known_state_label(
                        self.app,
                        state.get("component_state") or "unknown",
                    )
                },
            ),
            self.app.tr(
                "ch347.detail_processes",
                {"count": state.get("live_processes", 0)},
            ),
        ]
        version = str(state.get("package_version") or "")
        if version:
            details.append(self.app.tr("ch347.detail_package", {"version": version}))
        errors = state.get("configuration_errors", [])
        if isinstance(errors, list) and errors:
            details.append(
                self.app.tr(
                    "ch347.detail_configuration",
                    {"errors": "; ".join(str(item) for item in errors)},
                )
            )
        if not state.get("configuration_provisioned", False):
            details.append(self.app.tr("ch347.configuration_not_provisioned"))
        self.details.set(" · ".join(details))
        self.fps.set(str(state.get("fps", "")))
        self.idle_fps.set(str(state.get("idle_fps", "")))
        calibration = state.get("touch_calibration", {})
        calibration = calibration if isinstance(calibration, dict) else {}
        for field, variable in self.touch_booleans.items():
            variable.set(bool(calibration.get(field, False)))
        for field, variable in self.touch_integers.items():
            variable.set(str(calibration.get(field, "")))
        self._busy = False
        self._set_control_state(*self._availability())
        if status == "available":
            self.feedback.set(self.app.tr("ch347.controls_ready"))
            self.feedback_label.configure(style="Success.TLabel")
        else:
            self.feedback.set(
                self.app.tr("ch347.controls_disabled")
            )
            self.feedback_label.configure(style="Error.TLabel")
        self.on_state(self.state)

    def show_result(self, result: OperationResult) -> bool:
        if self._closed:
            return True
        self._busy = False
        self._set_control_state(False, False)
        self.status.set(self.app.tr("ch347.typed_unavailable"))
        self.status_label.configure(style="Error.TLabel")
        self.details.set(
            f"{result.code or 'UNAVAILABLE'}: "
            f"{result.message or self.app.tr('ch347.provider_not_responding')}"
        )
        self._set_feedback(self.details.get(), error=True)
        return True

    def refresh(self) -> None:
        if self._closed or self._busy:
            return
        self._busy = True
        self._set_control_state(False, False)
        self.feedback.set(self.app.tr("status.reading_ch347"))
        self.feedback_label.configure(style="Muted.TLabel")
        self.app.run_task(
            self.app.tr("status.reading_ch347"),
            self.app.model.ch347_status,
            self._status_result,
        )

    def _status_result(self, result: OperationResult) -> bool:
        self._busy = False
        if not result.ok:
            return self.show_result(result)
        state = result.data.get("state", {})
        if not isinstance(state, dict):
            return self.show_result(OperationResult(
                False,
                message=self.app.tr("ch347.no_state"),
                code="CH347_BAD_RESPONSE",
            ))
        self.load_state(state)
        return True

    def _parse_whole_number(self, variable: tk.StringVar, field: str) -> int:
        raw = variable.get().strip()
        try:
            return int(raw, 10)
        except ValueError as exc:
            raise ValueError(
                self.app.tr("ch347.whole_number_required", {"field": field})
            ) from exc

    def apply_fps(self) -> None:
        try:
            fps = self._parse_whole_number(self.fps, self.app.tr("ch347.active_fps"))
            idle_fps = self._parse_whole_number(
                self.idle_fps,
                self.app.tr("ch347.idle_fps"),
            )
        except ValueError as exc:
            self._set_feedback(str(exc), error=True)
            return
        self._busy = True
        self._set_control_state(False, False)
        self.feedback.set(self.app.tr("status.applying_ch347_fps"))
        self.feedback_label.configure(style="Muted.TLabel")
        self.app.run_task(
            self.app.tr("status.applying_ch347_fps"),
            lambda: self.app.model.ch347_set_fps(fps, idle_fps),
            self._fps_result,
        )

    def _fps_result(self, result: OperationResult) -> bool:
        if self._closed:
            return True
        self._busy = False
        if not result.ok:
            self._set_control_state(*self._availability())
            self._set_feedback(
                f"{result.code or 'CH347_ERROR'}: "
                f"{result.message or self.app.tr('ch347.frame_rate_update_failed')}",
                error=True,
            )
            return True
        self.state["fps"] = result.data["fps"]
        self.state["idle_fps"] = result.data["idle_fps"]
        self.fps.set(str(result.data["fps"]))
        self.idle_fps.set(str(result.data["idle_fps"]))
        self._set_control_state(*self._availability())
        self._set_feedback(
            self.app.tr(
                "ch347.frame_rates_applied",
                {"fps": result.data["fps"], "idle_fps": result.data["idle_fps"]},
            )
        )
        self.on_state(self.state)
        return True

    def apply_touch(self) -> None:
        calibration: dict[str, Any] = {
            field: variable.get()
            for field, variable in self.touch_booleans.items()
        }
        try:
            calibration.update({
                field: self._parse_whole_number(
                    variable,
                    self.app.tr(self.TOUCH_LABEL_KEYS[field]),
                )
                for field, variable in self.touch_integers.items()
            })
        except ValueError as exc:
            self._set_feedback(str(exc), error=True)
            return
        if not messagebox.askyesno(
            self.app.tr("ch347.confirm_touch_title"),
            self.app.tr("ch347.confirm_touch_body"),
            parent=self.window,
            default=messagebox.NO,
            icon="warning",
        ):
            self._set_feedback(self.app.tr("ch347.touch_cancelled"))
            return
        self._touch_was_running = bool(self.state.get("running"))
        self._busy = True
        self._set_control_state(False, False)
        self.feedback.set(self.app.tr("ch347.saving_calibration"))
        self.feedback_label.configure(style="Muted.TLabel")
        self.app.run_task(
            self.app.tr("status.applying_ch347_touch"),
            lambda: self.app.model.ch347_set_touch_calibration(calibration),
            self._touch_result,
        )

    def _touch_result(self, result: OperationResult) -> bool:
        if self._closed:
            return True
        self._busy = False
        if not result.ok:
            self._set_control_state(*self._availability())
            self._set_feedback(
                f"{result.code or 'CH347_ERROR'}: "
                f"{result.message or self.app.tr('ch347.calibration_update_failed')}",
                error=True,
            )
            return True
        calibration = result.data["touch_calibration"]
        self.state["touch_calibration"] = dict(calibration)
        if result.data.get("status"):
            self.state["status"] = result.data["status"]
        self._set_control_state(*self._availability())
        self._set_feedback(
            (
                self.app.tr("ch347.touch_applied_running")
                if getattr(self, "_touch_was_running", False)
                else self.app.tr("ch347.touch_saved")
            )
        )
        self.on_state(self.state)
        return True

    def restart(self) -> None:
        if not messagebox.askyesno(
            self.app.tr("ch347.confirm_restart_title"),
            self.app.tr("ch347.confirm_restart_body"),
            parent=self.window,
            default=messagebox.NO,
            icon="warning",
        ):
            self._set_feedback(self.app.tr("ch347.restart_cancelled"))
            return
        self._busy = True
        self._set_control_state(False, False)
        self.feedback.set(self.app.tr("status.restarting_ch347"))
        self.feedback_label.configure(style="Muted.TLabel")
        self.app.run_task(
            self.app.tr("status.restarting_ch347"),
            self.app.model.ch347_restart,
            self._restart_result,
        )

    def _restart_result(self, result: OperationResult) -> bool:
        if self._closed:
            return True
        self._busy = False
        if not result.ok:
            self._set_control_state(*self._availability())
            self._set_feedback(
                f"{result.code or 'CH347_ERROR'}: "
                f"{result.message or self.app.tr('ch347.restart_failed')}",
                error=True,
            )
            return True
        state = result.data.get("state", {})
        if isinstance(state, dict):
            self.load_state(state)
        self._set_feedback(self.app.tr("ch347.output_ready"))
        return True


def _storage_size(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return ""
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024.0 or unit == "TiB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024.0
    return ""


class StoragePage(BasePage):
    title_key = "storage.title"
    note_key = "storage.note"

    def __init__(self, parent: ttk.Frame, app: SettingsApplication) -> None:
        super().__init__(parent, app)
        self.auto_mount = tk.BooleanVar(value=False)
        self.surface = ScrollableSurface(self, background=PANEL)
        self.surface.pack(fill="both", expand=True)
        container = self.surface.content

        self.summary_title = tk.StringVar(value=app.tr("storage.not_loaded"))
        self.summary_body = tk.StringVar(value=app.tr("storage.waiting"))
        self.summary_card = MaterialStatusCard(
            container,
            title=self.summary_title,
            body=self.summary_body,
            compact=app.compact,
        )
        self.summary_card.pack(fill="x", pady=(0, 9))

        controls = ttk.Frame(container, style="Panel.TFrame")
        controls.pack(fill="x", pady=(0, 9))
        self.auto_button = ttk.Checkbutton(
            controls,
            text=app.tr("storage.auto_mount"),
            variable=self.auto_mount,
            command=self.set_auto_mount,
        )
        self.auto_button.pack(side="top" if app.compact else "left", anchor="w")
        ttk.Button(
            controls,
            text=app.tr("common.refresh"),
            command=self.refresh_now,
        ).pack(
            side="top" if app.compact else "right",
            anchor="e",
            fill="x" if app.compact else "none",
            pady=(5, 0) if app.compact else 0,
        )

        self.volumes = tk.Frame(container, background=PANEL)
        self.volumes.pack(fill="x")

    def refresh(self) -> None:
        self._load(self.app.model.storage_state)

    def refresh_now(self) -> None:
        self._load(self.app.model.storage_refresh)

    def _load(self, operation: Callable[[], OperationResult]) -> None:
        self.auto_button.state(["disabled"])
        self.app.run_task(
            self.app.tr("status.loading_storage"),
            operation,
            self._loaded_result,
        )

    def _loaded_result(self, result: OperationResult) -> bool:
        for child in self.volumes.winfo_children():
            child.destroy()
        if not result.ok:
            self.summary_title.set(self.app.tr("storage.unavailable"))
            self.summary_body.set(result.message or result.code or self.app.tr("common.unavailable"))
            self.summary_card.set_color(ERROR_CONTAINER)
            self.auto_button.state(["disabled"])
            return True

        self.auto_mount.set(result.data.get("auto_mount") is True)
        self.auto_button.state(["!disabled"])
        rows = result.data.get("volumes", [])
        count = len(rows) if isinstance(rows, list) else 0
        self.summary_title.set(self.app.tr("storage.ready"))
        self.summary_body.set(
            self.app.tr(
                "storage.summary",
                {
                    "count": count,
                    "root": str(result.data.get("mount_root") or ""),
                },
            )
        )
        self.summary_card.set_color(SUCCESS_CONTAINER)
        if not rows:
            ttk.Label(
                self.volumes,
                text=self.app.tr("storage.no_volumes"),
                style="Muted.TLabel",
                wraplength=280 if self.app.compact else 680,
                justify="left",
            ).pack(fill="x", pady=12)
            return True
        for volume in rows:
            if isinstance(volume, dict):
                self._volume_card(volume)
        return True

    def _volume_card(self, volume: dict[str, Any]) -> None:
        card = tk.Frame(
            self.volumes,
            background=PANEL_ALT,
            highlightbackground=OUTLINE,
            highlightthickness=1,
            padx=10,
            pady=9,
        )
        card.pack(fill="x", pady=(0, 8))
        name = str(volume.get("name") or volume.get("id") or "")
        tk.Label(
            card,
            text=name,
            background=PANEL_ALT,
            foreground=TEXT,
            anchor="w",
            font=font_spec(card, 10, "bold"),
        ).pack(fill="x")
        mounted = volume.get("mounted") is True
        details = [
            self.app.tr("storage.mounted" if mounted else "storage.not_mounted"),
            str(volume.get("transport") or ""),
            _storage_size(volume.get("size_bytes")),
            str(volume.get("mount_point") or volume.get("preferred_mount_point") or ""),
        ]
        error = volume.get("error")
        if isinstance(error, dict):
            details.append(
                self.app.tr(
                    "storage.volume_error",
                    {"reason": str(error.get("reason") or error.get("code") or "")},
                )
            )
        tk.Label(
            card,
            text=" · ".join(item for item in details if item),
            background=PANEL_ALT,
            foreground=ERROR if isinstance(error, dict) else MUTED,
            anchor="w",
            justify="left",
            wraplength=270 if self.app.compact else 650,
        ).pack(fill="x", pady=(3, 7))
        action = ttk.Button(
            card,
            text=self.app.tr("storage.unmount" if mounted else "storage.mount"),
            command=(
                lambda identifier=str(volume.get("id") or ""): self.unmount(identifier)
            )
            if mounted
            else (
                lambda identifier=str(volume.get("id") or ""), read_only=volume.get("read_only") is True: self.mount(identifier, read_only)
            ),
        )
        # Keep externally mounted volumes visible, but do not offer a false
        # unmount action that the provider will reject as unmanaged.
        if mounted and volume.get("managed") is not True:
            action.state(["disabled"])
        action.pack(fill="x" if self.app.compact else "none", anchor="e")

    def set_auto_mount(self) -> None:
        selected = bool(self.auto_mount.get())
        self.auto_button.state(["disabled"])
        self.app.run_task(
            self.app.tr("status.saving_storage"),
            lambda: self.app.model.storage_set_auto_mount(selected),
            self._loaded_result,
        )

    def mount(self, identifier: str, read_only: bool) -> None:
        self.app.run_task(
            self.app.tr("status.mounting_storage"),
            lambda: self.app.model.storage_mount(identifier, read_only=read_only),
            self._loaded_result,
        )

    def unmount(self, identifier: str) -> None:
        self.app.run_task(
            self.app.tr("status.unmounting_storage"),
            lambda: self.app.model.storage_unmount(identifier),
            self._loaded_result,
        )


class AppsPage(BasePage):
    title_key = "apps.title"
    note_key = "apps.note"

    def __init__(self, parent: ttk.Frame, app: SettingsApplication) -> None:
        super().__init__(parent, app)
        self.packages: dict[str, dict[str, Any]] = {}
        self._last_result: dict[str, Any] | None = None
        self._pending_activation: tuple[str, str] | None = None
        self._registry_loaded = False
        self.surface = ScrollableSurface(self, background=PANEL)
        self.surface.pack(fill="both", expand=True)
        container = self.surface.content

        toolbar = ttk.Frame(container, style="Panel.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        self.summary = tk.StringVar(value=app.tr("common.not_loaded"))
        ttk.Label(
            toolbar,
            textvariable=self.summary,
            style="Muted.TLabel",
        ).pack(side="top" if app.compact else "left", anchor="w", fill="x")
        actions = ttk.Frame(toolbar, style="Panel.TFrame")
        actions.pack(
            side="top" if app.compact else "right",
            anchor="e",
            pady=(5, 0) if app.compact else 0,
        )
        ttk.Button(actions, text=app.tr("common.refresh"), command=self.refresh).pack(side="left")
        self.rollback_button = ttk.Button(
            actions,
            text=app.tr("common.rollback"),
            command=self.rollback,
        )
        self.rollback_button.pack(side="left", padx=(6, 0))
        self.rollback_button.state(["disabled"])
        self.uninstall_button = ttk.Button(
            actions,
            text=app.tr("common.uninstall"),
            command=self.uninstall,
        )
        self.uninstall_button.pack(side="left", padx=(6, 0))
        self.uninstall_button.state(["disabled"])
        if app.mode == "software-center":
            updates_button = ttk.Button(
                toolbar if app.compact else actions,
                text=app.tr("nav.updates"),
                command=lambda: app.show_page("updates"),
            )
            if app.compact:
                updates_button.pack(fill="x", pady=(6, 0))
            else:
                updates_button.pack(side="left", padx=(6, 0))

        tree_frame = ttk.Frame(container, style="Panel.TFrame")
        tree_frame.pack(fill="x")
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("package", "version", "status"),
            show="headings",
            selectmode="browse",
            height=5 if app.compact else 8,
        )
        self.tree.heading("package", text=app.tr("common.package"))
        self.tree.heading("version", text=app.tr("common.version"))
        self.tree.heading("status", text=app.tr("common.status"))
        self.tree.column("package", width=145 if app.compact else 370, anchor="w")
        self.tree.column("version", width=70 if app.compact else 125, anchor="w")
        self.tree.column("status", width=65 if app.compact else 120, anchor="w")
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)

        details_frame = ttk.Frame(container, style="Panel.TFrame")
        details_frame.pack(fill="x", pady=(8, 0))
        self.details = tk.Text(
            details_frame,
            height=6,
            bg=FIELD_BG,
            fg=TEXT,
            relief="flat",
            padx=10,
            pady=8,
            wrap="word",
        )
        details_scroll = ttk.Scrollbar(details_frame, orient="vertical", command=self.details.yview)
        self.details.configure(yscrollcommand=details_scroll.set)
        self.details.pack(side="left", fill="both", expand=True)
        details_scroll.pack(side="right", fill="y")
        self.details.configure(state="disabled")
        _replace_text(self.details, app.tr("apps.select_inspect"))

    def refresh(self) -> None:
        self._registry_loaded = False
        self.uninstall_button.state(["disabled"])
        self.rollback_button.state(["disabled"])
        self.app.run_task(
            self.app.tr("status.loading_apps"),
            self.app.model.installed_packages,
            self._loaded_result,
        )

    def _loaded_result(self, result: OperationResult) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.packages.clear()
        if not result.ok:
            self._registry_loaded = True
            self.summary.set(result.message or self.app.tr("apps.unavailable"))
            _replace_text(self.details, {
                "ok": False,
                "code": result.code,
                "message": result.message,
                "response": result.data,
                "last_operation": self._last_result,
            })
            return
        rows = result.data.get("packages", [])
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            package = str(row.get("package", ""))
            if not package:
                continue
            self.packages[package] = row
            self.tree.insert(
                "",
                "end",
                iid=package,
                values=(
                    package,
                    str(row.get("version", "")),
                    self.app.tr("apps.installed"),
                ),
            )
        self.summary.set(
            self.app.tr("apps.summary", {"count": len(self.packages)})
        )
        self._registry_loaded = True
        _replace_text(self.details, {
            "packages": len(self.packages),
            "last_operation": self._last_result,
        })
        self._apply_pending_activation()

    def activate_package(self, component: str, panel: str = "details") -> None:
        package = component.split(":", 1)[0].strip()
        if not package:
            return
        self._pending_activation = (package, panel)
        if self._registry_loaded:
            self._apply_pending_activation()

    def _apply_pending_activation(self) -> None:
        if self._pending_activation is None:
            return
        package, panel = self._pending_activation
        if package not in self.packages:
            if self._registry_loaded:
                self.app.set_status(
                    self.app.tr("apps.package_not_found", {"package": package}),
                    error=True,
                )
                self._pending_activation = None
            return
        self._pending_activation = None
        self.tree.selection_set(package)
        self.tree.focus(package)
        self.tree.see(package)
        self._selection_changed()
        if panel == "uninstall":
            self.app.root.after_idle(self.uninstall)

    def _selected_package(self) -> dict[str, Any] | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.packages.get(str(selection[0]))

    def _selection_changed(self, _event: Any = None) -> None:
        selected = self._selected_package()
        if selected is None:
            self.uninstall_button.state(["disabled"])
            self.rollback_button.state(["disabled"])
            return
        self.uninstall_button.state(["!disabled"])
        self.rollback_button.state(["!disabled"])
        _replace_text(self.details, {
            "selected": selected,
            "last_operation": self._last_result,
        })

    def uninstall(self) -> None:
        selected = self._selected_package()
        if selected is None:
            messagebox.showerror(
                self.app.tr("apps.uninstall_title"),
                self.app.tr("apps.select_first"),
                parent=self.app.root,
            )
            return
        package = str(selected["package"])
        version = str(selected.get("version", ""))
        title = self.app.tr("apps.uninstall_title")
        prompt = self.app.tr(
            "apps.uninstall_prompt",
            {"package": package, "version": version},
        )
        confirmed = messagebox.askyesno(
            title,
            prompt,
            icon="warning",
            default=messagebox.NO,
            parent=self.app.root,
        )
        if not confirmed:
            return
        self.uninstall_button.state(["disabled"])
        self.app.run_task(
            self.app.tr("status.uninstalling", {"package": package}),
            lambda: self.app.model.request_uninstall(package),
            lambda result: self._uninstall_result(package, result),
        )

    def rollback(self) -> None:
        selected = self._selected_package()
        if selected is None:
            messagebox.showerror(
                self.app.tr("updates.rollback_title"),
                self.app.tr("apps.select_first"),
                parent=self.app.root,
            )
            return
        package = str(selected["package"])
        if not messagebox.askyesno(
            self.app.tr("updates.rollback_title"),
            self.app.tr("updates.rollback_prompt", {"package": package}),
            parent=self.app.root,
        ):
            return
        self.rollback_button.state(["disabled"])
        self.app.run_task(
            self.app.tr("status.waiting_rollback"),
            lambda: self.app.model.request_rollback(package),
            lambda result: self._rollback_result(package, result),
        )

    def _rollback_result(self, package: str, result: OperationResult) -> bool:
        self._last_result = {
            "request": "rollback",
            "package": package,
            "terminal": True,
            "ok": result.ok,
            "response": result.data,
            **(
                {
                    "error": {
                        "code": result.code,
                        "message": result.message,
                    }
                }
                if not result.ok
                else {}
            ),
        }
        _replace_text(self.details, self._last_result)
        if result.ok:
            self.refresh()
        else:
            self.rollback_button.state(["!disabled"])
        return True

    def _uninstall_result(self, package: str, result: OperationResult) -> bool:
        record: dict[str, Any] = {
            "request": "uninstall",
            "package": package,
            "terminal": True,
            "ok": result.ok,
            "response": result.data,
        }
        if not result.ok:
            record["error"] = {
                "code": result.code,
                "message": result.message,
                "payload": result.data,
            }
        self._last_result = record
        _replace_text(self.details, record)
        if result.ok:
            self.summary.set(
                self.app.tr("apps.uninstalled_refreshing", {"package": package})
            )
            self.refresh()
        else:
            self.summary.set(
                self.app.tr(
                    "apps.uninstall_failed",
                    {"reason": result.code or result.message},
                )
            )
            self.uninstall_button.state(["!disabled"])
        return True


class UpdatesPage(BasePage):
    title_key = "updates.title"
    note_key = "updates.note"

    def __init__(self, parent: ttk.Frame, app: SettingsApplication) -> None:
        super().__init__(parent, app)
        self.source = tk.StringVar(value=os.environ.get("MSYS_UPDATE_SOURCE", ""))
        self.package = tk.StringVar(value="all")
        self.surface = ScrollableSurface(self, background=PANEL)
        self.surface.pack(fill="both", expand=True)
        container = self.surface.content
        form = ttk.Frame(container, style="Panel.TFrame")
        form.pack(fill="x")
        if app.compact:
            ttk.Label(form, text=app.tr("updates.index_source"), style="Muted.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Entry(form, textvariable=self.source).grid(row=1, column=0, sticky="ew")
            ttk.Label(form, text=app.tr("updates.package_filter"), style="Muted.TLabel").grid(
                row=2, column=0, sticky="w", pady=(5, 0)
            )
            ttk.Entry(form, textvariable=self.package).grid(row=3, column=0, sticky="ew")
            form.columnconfigure(0, weight=1)
        else:
            ttk.Label(form, text=app.tr("updates.index_source"), style="Muted.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Entry(form, textvariable=self.source).grid(row=1, column=0, sticky="ew", padx=(0, 8))
            ttk.Label(form, text=app.tr("updates.package_filter"), style="Muted.TLabel").grid(row=0, column=1, sticky="w")
            ttk.Entry(form, textvariable=self.package, width=28).grid(row=1, column=1, sticky="ew")
            form.columnconfigure(0, weight=3)
            form.columnconfigure(1, weight=2)
        actions = ttk.Frame(container, style="Panel.TFrame")
        actions.pack(fill="x", pady=8)
        if app.mode == "software-center":
            ttk.Button(
                actions,
                text=app.tr("nav.apps"),
                command=lambda: app.show_page("apps"),
            ).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text=app.tr("common.check"), command=lambda: self.request("check")).pack(side="left")
        ttk.Button(actions, text=app.tr("common.apply"), style="Accent.TButton", command=lambda: self.request("apply")).pack(
            side="left", padx=6
        )
        ttk.Button(
            actions,
            text=app.tr("common.rollback" if app.compact else "common.rollback_package"),
            command=self.rollback,
        ).pack(side="left")
        events_frame = ttk.Frame(container, style="Panel.TFrame")
        events_frame.pack(fill="x")
        self.events = tk.Text(
            events_frame,
            bg=FIELD_BG,
            fg=TEXT,
            relief="flat",
            padx=10,
            pady=8,
            wrap="word",
            height=10 if app.compact else 18,
        )
        events_scroll = ttk.Scrollbar(events_frame, orient="vertical", command=self.events.yview)
        self.events.configure(yscrollcommand=events_scroll.set)
        self.events.pack(side="left", fill="both", expand=True)
        events_scroll.pack(side="right", fill="y")
        self.events.insert("end", app.tr("updates.no_request") + "\n")
        self.events.configure(state="disabled")

    def refresh(self) -> None:
        pass

    def request(self, action: str) -> None:
        self.app.run_task(
            self.app.tr("status.waiting_update", {"action": action}),
            lambda: self.app.model.request_update(action, self.source.get(), self.package.get()),
            lambda result: self._request_result(action, result),
        )

    def rollback(self) -> None:
        package = self.package.get().strip()
        if not package or package == "all":
            messagebox.showerror(
                self.app.tr("updates.rollback_title"),
                self.app.tr("updates.rollback_concrete"),
                parent=self.app.root,
            )
            return
        if not messagebox.askyesno(
            self.app.tr("updates.rollback_title"),
            self.app.tr("updates.rollback_prompt", {"package": package}),
            parent=self.app.root,
        ):
            return
        self.app.run_task(
            self.app.tr("status.waiting_rollback"),
            lambda: self.app.model.request_rollback(package),
            lambda result: self._request_result("rollback", result),
        )

    def _request_result(self, action: str, result: OperationResult) -> None:
        entry = {
            "request": action,
            "terminal": True,
            "ok": result.ok,
            "response": result.data,
        }
        if not result.ok:
            entry["error"] = {
                "code": result.code,
                "message": result.message,
                "payload": result.data,
            }
        self._append(entry)

    def append_event(self, event: dict[str, Any]) -> None:
        self._append({"topic": event.get("topic"), "payload": event.get("payload", {})})

    def _append(self, value: Any) -> None:
        self.events.configure(state="normal")
        self.events.insert("end", _json(value) + "\n\n")
        self.events.see("end")
        self.events.configure(state="disabled")
