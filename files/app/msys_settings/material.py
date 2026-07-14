"""Small dependency-free Material-like widgets built on Tk Canvas."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from .theme import (
    ACCENT,
    ACCENT_CONTAINER,
    ACCENT_HOVER,
    DISABLED,
    MUTED,
    OUTLINE,
    PANEL,
    PANEL_ALT,
    TEXT,
)
from .responsive import needs_vertical_scroll, text_wrap_length
from msys_sdk.ui_fonts import font_spec


def rounded_rectangle(
    canvas: tk.Canvas,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    radius: int,
    **options: object,
) -> int:
    radius = max(0, min(radius, (x2 - x1) // 2, (y2 - y1) // 2))
    points = (
        x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
        x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
        x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
    )
    return int(canvas.create_polygon(points, smooth=True, splinesteps=20, **options))


class MaterialCardButton(tk.Canvas):
    """Rounded, keyboard-accessible card with pressed/disabled feedback."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        title: str,
        subtitle: str = "",
        icon: str = "",
        command: Callable[[], None] | None = None,
        height: int = 76,
        accent: bool = False,
        compact: bool = False,
        scroll: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(
            parent,
            height=height,
            background=str(parent.cget("background")),
            borderwidth=0,
            highlightthickness=0,
            takefocus=1,
            cursor="hand2",
        )
        self.title = title
        self.subtitle = subtitle
        self.icon = icon
        self.command = command
        self.accent = accent
        self.compact = compact
        self.scroll = scroll
        self._minimum_height = max(44, int(height))
        self._requested_height = self._minimum_height
        self.disabled = False
        self._pressed = False
        self._dragged = False
        self._last_y = 0
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Enter>", lambda _event: self._draw("hover"))
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<space>", lambda _event: self.invoke())
        self.bind("<Return>", lambda _event: self.invoke())

    def set_disabled(self, disabled: bool) -> None:
        self.disabled = bool(disabled)
        self.configure(cursor="arrow" if self.disabled else "hand2")
        self._draw("disabled" if self.disabled else "normal")

    def set_text(self, *, title: str | None = None, subtitle: str | None = None) -> None:
        if title is not None:
            self.title = title
        if subtitle is not None:
            self.subtitle = subtitle
        self._draw("disabled" if self.disabled else "normal")

    def invoke(self) -> None:
        if not self.disabled and self.command is not None:
            self.command()

    def _press(self, event: tk.Event[tk.Misc]) -> None:
        if self.disabled:
            return
        self.focus_set()
        self._pressed = True
        self._dragged = False
        self._last_y = int(event.y_root)
        self._draw("pressed")

    def _motion(self, event: tk.Event[tk.Misc]) -> None:
        if not self._pressed:
            return
        current = int(event.y_root)
        delta = self._last_y - current
        if abs(delta) >= 3:
            self._dragged = True
            self._last_y = current
            if self.scroll is not None:
                self.scroll(delta)
        self._draw("normal" if self._dragged else "pressed")

    def _release(self, _event: tk.Event[tk.Misc]) -> None:
        if not self._pressed:
            return
        should_invoke = not self._dragged and not self.disabled
        self._pressed = False
        self._draw("normal")
        if should_invoke:
            self.invoke()

    def _leave(self, _event: tk.Event[tk.Misc]) -> None:
        if not self._pressed:
            self._draw("normal")

    def _draw(self, state: str = "normal") -> None:
        width = max(40, int(self.winfo_width()))
        height = max(36, int(self.winfo_height()))
        if self.disabled or state == "disabled":
            fill, foreground, secondary = PANEL_ALT, DISABLED, DISABLED
        elif state == "pressed":
            fill, foreground, secondary = ACCENT_HOVER, "#ffffff", "#e7ebff"
        elif self.accent:
            fill = ACCENT if state != "hover" else ACCENT_HOVER
            foreground, secondary = "#ffffff", "#e7ebff"
        else:
            fill = ACCENT_CONTAINER if state == "hover" else PANEL
            foreground, secondary = TEXT, MUTED
        self.delete("all")
        rounded_rectangle(
            self,
            2,
            2,
            width - 2,
            height - 2,
            14,
            fill=fill,
            outline=OUTLINE if not self.accent and state != "pressed" else fill,
            width=1,
        )
        left = 16
        if self.icon:
            self._draw_icon(left + 9, 24, foreground)
            left += 29
        title_y = 13
        title_item = self.create_text(
            left,
            title_y,
            text=self.title,
            anchor="nw" if self.compact else "w",
            fill=foreground,
            font=font_spec(self, 10 if self.compact else 11, "bold"),
            width=max(35, width - left - 24),
        )
        lowest = self.bbox(title_item)[3] if self.bbox(title_item) else title_y + 16
        if self.subtitle:
            subtitle_item = self.create_text(
                left,
                lowest + 5,
                text=self.subtitle,
                anchor="nw",
                fill=secondary,
                font=font_spec(self, 8 if self.compact else 9),
                width=max(35, width - left - 24),
            )
            bounds = self.bbox(subtitle_item)
            if bounds:
                lowest = bounds[3]
        self.create_line(
            width - 19,
            height // 2 - 5,
            width - 14,
            height // 2,
            width - 19,
            height // 2 + 5,
            fill=secondary,
            width=2,
            capstyle="round",
            joinstyle="round",
        )
        if width > 100:
            requested = max(self._minimum_height, int(lowest + 13))
            if requested != self._requested_height:
                self._requested_height = requested
                self.configure(height=requested)

    def _draw_icon(self, x: int, y: int, color: str) -> None:
        """Draw small monochrome icons without font or image dependencies."""

        aliases = {
            "Wi": "wifi",
            "Bt": "bluetooth",
            "D": "display",
            "Kb": "keyboard",
            "A": "appearance",
            "P": "apps",
            "R": "roles",
            "H": "hardware",
            "U": "updates",
            "S": "system",
        }
        icon = aliases.get(self.icon, self.icon).casefold()
        if icon == "wifi":
            for radius in (5, 9, 13):
                self.create_arc(
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                    start=45,
                    extent=90,
                    style="arc",
                    outline=color,
                    width=2,
                )
            self.create_oval(x - 2, y + 8, x + 2, y + 12, fill=color, outline="")
        elif icon == "bluetooth":
            self.create_line(x, y - 12, x, y + 12, x + 8, y + 5, x - 7, y - 6,
                             fill=color, width=2, joinstyle="round")
            self.create_line(x, y - 12, x + 8, y - 5, x - 7, y + 6,
                             fill=color, width=2, joinstyle="round")
        elif icon == "display":
            self.create_rectangle(x - 12, y - 9, x + 12, y + 7, outline=color, width=2)
            self.create_line(x - 5, y + 11, x + 5, y + 11, x, y + 7, fill=color, width=2)
        elif icon == "keyboard":
            self.create_rectangle(x - 13, y - 9, x + 13, y + 9, outline=color, width=2)
            for row in (-4, 2):
                for column in (-8, -3, 2, 7):
                    self.create_rectangle(
                        x + column - 1,
                        y + row - 1,
                        x + column + 1,
                        y + row + 1,
                        fill=color,
                        outline="",
                    )
            self.create_line(x - 7, y + 6, x + 7, y + 6, fill=color, width=2)
        elif icon == "apps":
            for dx in (-7, 5):
                for dy in (-7, 5):
                    self.create_rectangle(x + dx - 4, y + dy - 4, x + dx + 4, y + dy + 4,
                                          outline=color, width=2)
        elif icon == "hardware":
            self.create_rectangle(x - 8, y - 8, x + 8, y + 8, outline=color, width=2)
            self.create_rectangle(x - 3, y - 3, x + 3, y + 3, fill=color, outline="")
            for offset in (-6, 0, 6):
                self.create_line(x + offset, y - 12, x + offset, y - 8, fill=color, width=2)
                self.create_line(x + offset, y + 8, x + offset, y + 12, fill=color, width=2)
        elif icon == "updates":
            self.create_arc(x - 11, y - 11, x + 11, y + 11, start=35, extent=285,
                            style="arc", outline=color, width=2)
            self.create_line(x + 8, y - 9, x + 12, y - 9, x + 11, y - 4,
                             fill=color, width=2)
        elif icon == "system":
            self.create_oval(x - 11, y - 11, x + 11, y + 11, outline=color, width=2)
            self.create_oval(x - 1, y - 7, x + 1, y - 5, fill=color, outline="")
            self.create_line(x, y - 1, x, y + 7, fill=color, width=2)
        elif icon == "roles":
            self.create_oval(x - 4, y - 11, x + 4, y - 3, outline=color, width=2)
            self.create_arc(x - 10, y - 1, x + 10, y + 14, start=0, extent=180,
                            style="arc", outline=color, width=2)
        elif icon == "appearance":
            self.create_oval(x - 11, y - 11, x + 11, y + 11, outline=color, width=2)
            for dx, dy in ((-5, -3), (1, -6), (5, 0), (-2, 5)):
                self.create_oval(x + dx - 2, y + dy - 2, x + dx + 2, y + dy + 2,
                                 fill=color, outline="")
        else:
            self.create_oval(x - 9, y - 9, x + 9, y + 9, outline=color, width=2)


class MaterialStatusCard(tk.Frame):
    """Compact responsive status summary shared by Settings sub-pages."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        title: tk.StringVar,
        body: tk.StringVar,
        compact: bool = False,
    ) -> None:
        super().__init__(
            parent,
            background=PANEL_ALT,
            highlightbackground=OUTLINE,
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        self.title_label = tk.Label(
            self,
            textvariable=title,
            background=PANEL_ALT,
            foreground=TEXT,
            anchor="w",
            justify="left",
            font=font_spec(self, 10 if compact else 11, "bold"),
        )
        self.title_label.pack(fill="x")
        self.body_label = tk.Label(
            self,
            textvariable=body,
            background=PANEL_ALT,
            foreground=MUTED,
            anchor="w",
            justify="left",
            wraplength=276 if compact else 650,
        )
        self.body_label.pack(fill="x", pady=(3, 0))
        self.body_label.bind(
            "<Configure>",
            lambda event: self.body_label.configure(
                wraplength=text_wrap_length(int(event.width), horizontal_padding=4)
            ),
        )

    def set_color(self, color: str) -> None:
        """Change only the card surface; text remains readable and stable."""

        self.configure(background=color)
        self.title_label.configure(background=color)
        self.body_label.configure(background=color)


class ScrollableSurface(tk.Frame):
    """Vertical surface that supports mouse wheels and direct touch drags."""

    def __init__(self, parent: tk.Misc, *, background: str) -> None:
        super().__init__(parent, background=background, borderwidth=0)
        self.canvas = tk.Canvas(
            self,
            background=background,
            borderwidth=0,
            highlightthickness=0,
        )
        self.scrollbar = tk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
            width=7,
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.content = tk.Frame(self.canvas, background=background, borderwidth=0)
        self._window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._sync_region)
        self.canvas.bind("<Configure>", self._sync_width)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda _event: self.scroll_pixels(-36))
        self.canvas.bind("<Button-5>", lambda _event: self.scroll_pixels(36))
        self.canvas.bind("<ButtonPress-1>", self._touch_start)
        self.canvas.bind("<B1-Motion>", self._touch_move)
        self._touch_y = 0
        self._bound_widgets: set[str] = set()

    def _sync_region(self, _event: tk.Event[tk.Misc]) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._bind_descendants(self.content)
        self.after_idle(self._sync_scrollbar)

    def _sync_width(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.itemconfigure(self._window, width=max(1, int(event.width)))
        self.after_idle(self._sync_scrollbar)

    def _sync_scrollbar(self) -> None:
        bounds = self.canvas.bbox("all")
        overflow = bounds is not None and needs_vertical_scroll(
            bounds[3] - bounds[1],
            self.canvas.winfo_height(),
        )
        managed = bool(self.scrollbar.winfo_manager())
        if overflow and not managed:
            self.scrollbar.pack(side="right", fill="y")
        elif not overflow and managed:
            self.scrollbar.pack_forget()

    def _bind_descendants(self, parent: tk.Misc) -> None:
        # A compact settings page must remain draggable even when a gesture
        # starts over a table or read-only detail surface. Tk Treeview/Text do
        # not provide phone-style drag scrolling themselves; additive bindings
        # preserve row selection and text behaviour for taps. Buttons, value
        # editors, toggles and scrollbars keep exclusive pointer handling so a
        # page swipe cannot submit or mutate a control accidentally.
        exclusive_pointer = {
            "Button", "TButton", "Entry", "TEntry", "TCombobox", "TSpinbox",
            "Checkbutton", "TCheckbutton", "Scrollbar", "TScrollbar",
        }
        for widget in parent.winfo_children():
            identity = str(widget)
            if identity not in self._bound_widgets:
                self._bound_widgets.add(identity)
                if (
                    widget.winfo_class() not in exclusive_pointer
                    and not isinstance(widget, MaterialCardButton)
                ):
                    widget.bind("<MouseWheel>", self._wheel, add="+")
                    widget.bind("<Button-4>", lambda _event: self.scroll_pixels(-36), add="+")
                    widget.bind("<Button-5>", lambda _event: self.scroll_pixels(36), add="+")
                    widget.bind("<ButtonPress-1>", self._touch_start, add="+")
                    widget.bind("<B1-Motion>", self._touch_move, add="+")
            self._bind_descendants(widget)

    def _wheel(self, event: tk.Event[tk.Misc]) -> None:
        self.scroll_pixels(-int(event.delta / 3))

    def _touch_start(self, event: tk.Event[tk.Misc]) -> None:
        self._touch_y = int(event.y_root)

    def _touch_move(self, event: tk.Event[tk.Misc]) -> None:
        current = int(event.y_root)
        self.scroll_pixels(self._touch_y - current)
        self._touch_y = current

    def scroll_pixels(self, delta: int) -> None:
        bounds = self.canvas.bbox("all")
        viewport = max(1, self.canvas.winfo_height())
        if bounds is None or bounds[3] <= viewport:
            return
        current = self.canvas.yview()[0]
        distance = max(1, bounds[3] - bounds[1])
        self.canvas.yview_moveto(max(0.0, min(1.0, current + delta / distance)))


__all__ = [
    "MaterialCardButton",
    "MaterialStatusCard",
    "ScrollableSurface",
    "rounded_rectangle",
]
