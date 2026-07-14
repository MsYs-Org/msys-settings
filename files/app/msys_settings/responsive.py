"""Pure responsive layout decisions shared by the Tk UI and tests."""

from __future__ import annotations

from dataclasses import dataclass


COMPACT_BREAKPOINT = 600


@dataclass(frozen=True)
class LayoutMetrics:
    mode: str
    outer_padding: int
    card_gap: int
    quick_columns: int
    navigation_width: int
    content_max_width: int


def layout_metrics(width: int) -> LayoutMetrics:
    safe_width = max(1, int(width))
    if safe_width < COMPACT_BREAKPOINT:
        return LayoutMetrics("compact", 10, 8, 2, 0, safe_width)
    return LayoutMetrics("desktop", 20, 12, 3, 248, min(820, safe_width - 248))


def text_wrap_length(
    width: int,
    *,
    horizontal_padding: int = 24,
    minimum: int = 120,
    maximum: int = 720,
) -> int:
    """Return a bounded Tk ``wraplength`` for the actual widget width.

    Keeping this calculation pure makes compact and rotated layouts behave
    consistently without adding a geometry manager or a third-party widget.
    """

    available = max(1, int(width)) - max(0, int(horizontal_padding))
    lower = max(1, int(minimum))
    upper = max(lower, int(maximum))
    return max(lower, min(upper, available))


def needs_vertical_scroll(content_height: int, viewport_height: int) -> bool:
    """Whether a page needs its thin outer scrollbar."""

    return max(0, int(content_height)) > max(0, int(viewport_height)) + 1


def filter_navigation(
    query: str,
    entries: tuple[tuple[str, str], ...] | list[tuple[str, str]],
) -> tuple[str, ...]:
    needle = " ".join(str(query).casefold().split())
    if not needle:
        return tuple(key for key, _label in entries)
    return tuple(
        key
        for key, label in entries
        if needle in (key + " " + label).casefold()
    )


__all__ = [
    "COMPACT_BREAKPOINT",
    "LayoutMetrics",
    "filter_navigation",
    "layout_metrics",
    "needs_vertical_scroll",
    "text_wrap_length",
]
