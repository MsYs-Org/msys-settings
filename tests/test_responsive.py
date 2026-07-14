from __future__ import annotations

import unittest

from msys_settings.responsive import (
    layout_metrics,
    needs_vertical_scroll,
    text_wrap_length,
)


class ResponsiveLayoutTests(unittest.TestCase):
    def test_phone_portrait_and_landscape_stay_compact(self) -> None:
        self.assertEqual(layout_metrics(320).mode, "compact")
        self.assertEqual(layout_metrics(480).mode, "compact")
        self.assertEqual(layout_metrics(600).mode, "desktop")

    def test_wrap_length_follows_width_and_remains_bounded(self) -> None:
        self.assertEqual(text_wrap_length(320, horizontal_padding=24), 296)
        self.assertEqual(text_wrap_length(480, horizontal_padding=24), 456)
        self.assertEqual(text_wrap_length(80, horizontal_padding=24), 120)
        self.assertEqual(text_wrap_length(1200, horizontal_padding=24), 720)

    def test_outer_scrollbar_only_appears_for_real_overflow(self) -> None:
        self.assertFalse(needs_vertical_scroll(478, 480))
        self.assertFalse(needs_vertical_scroll(481, 480))
        self.assertTrue(needs_vertical_scroll(482, 480))
        self.assertTrue(needs_vertical_scroll(500, 320))


if __name__ == "__main__":
    unittest.main()
