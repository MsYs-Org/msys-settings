"""Pure viewport policy for the dependency-free Settings frontend."""

from __future__ import annotations


COMPACT_WIDTH = 600
MAX_WINDOW_WIDTH = 1000
MAX_WINDOW_HEIGHT = 720


def is_compact(screen_width: int) -> bool:
    return max(int(screen_width), 1) < COMPACT_WIDTH


def window_size(screen_width: int, screen_height: int) -> tuple[int, int]:
    """Keep small displays exact while bounding oversized desktop windows."""

    return (
        min(max(int(screen_width), 1), MAX_WINDOW_WIDTH),
        min(max(int(screen_height), 1), MAX_WINDOW_HEIGHT),
    )


__all__ = ["is_compact", "window_size"]
