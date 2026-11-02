"""Mouse mapping and hit testing of the panel (fvp_app imports GL/OpenVR wrappers lazily, so stub them)."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "frame"))
for name in ("fvp_openvr", "fvp_gl", "fvp_cairo"):
    sys.modules.setdefault(name, types.ModuleType(name))
import fvp_app as a  # noqa: E402


class Mapping(unittest.TestCase):
    def test_flip_bounds_keep_y(self):
        self.assertEqual(a.panel_xy(10, 20, True), (10, 20))

    def test_raw_bounds_turn_y_over(self):
        self.assertEqual(a.panel_xy(10, 20, False), (10, a.H - 20))

    def test_hit_matches_drawn_buttons(self):
        p = types.SimpleNamespace(buttons=[("top", 0, 0, 100, 50), ("bottom", 0, a.H - 50, 100, 50)])
        hit = lambda x, y: a.Panel.hit(p, *a.panel_xy(x, y, True))[0]  # noqa: E731
        self.assertEqual(hit(10, 10), "top")
        self.assertEqual(hit(10, a.H - 10), "bottom")


if __name__ == "__main__":
    unittest.main()
