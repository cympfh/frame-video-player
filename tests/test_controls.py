"""Rotation, scroll and tap logic (pure functions in fvp_controls, plus the cube turn in fvp_app)."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "frame"))
for name in ("fvp_openvr", "fvp_gl", "fvp_cairo"):
    sys.modules.setdefault(name, types.ModuleType(name))
import fvp_app as a  # noqa: E402
import fvp_controls as c  # noqa: E402


class Rotation(unittest.TestCase):
    def test_wrap(self):
        self.assertAlmostEqual(c.wrap_deg(190), -170)
        self.assertAlmostEqual(c.wrap_deg(-190), 170)

    def test_turn_right_brings_right_side_to_front(self):
        f, r = [0, 0, -1], [1, 0, 0]
        f2, r2 = a.turn(f, r, 90)
        # the front face moves to the left, the right face is now straight ahead
        for got, want in zip(f2, [-1, 0, 0]):
            self.assertAlmostEqual(got, want)
        for got, want in zip(r2, f):
            self.assertAlmostEqual(got, want)

    def test_cube_follows_yaw(self):
        m0 = a.cube_matrices(None, 0)
        m90 = a.cube_matrices(None, 90)
        i_front, i_right = a.FACES.index("front"), a.FACES.index("right")
        t = lambda m: (m[3], m[7], m[11])  # noqa: E731
        for x, y in zip(t(m90[i_right]), t(m0[i_front])):
            self.assertAlmostEqual(x, y, places=4)


class Scroll(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(c.scroll_clamp(-3, 20, 7), 0)
        self.assertEqual(c.scroll_clamp(50, 20, 7), 13)
        self.assertEqual(c.scroll_clamp(5, 3, 7), 0)
        self.assertAlmostEqual(c.scroll_clamp(2.5, 20, 7), 2.5)

    def test_scroll_up_moves_toward_top(self):
        self.assertLess(c.scroll_from_smooth(0.5), 0)

    def test_panel_scroll_by(self):
        p = a.Panel()
        p.items = list(range(20))
        self.assertTrue(p.scroll_by(1.5))
        self.assertAlmostEqual(p.scroll, 1.5)
        self.assertFalse(p.scroll_by(-10) and p.scroll_by(-1))
        self.assertEqual(p.scroll, 0)


class Taps(unittest.TestCase):
    def test_same_key(self):
        self.assertEqual(c.resolve_tap(("pause", 10, 10), ("pause", 50, 10)), "pause")

    def test_small_slip_keeps_the_pressed_key(self):
        self.assertEqual(c.resolve_tap(("pause", 10, 10), ("seek:10", 30, 15)), "pause")
        self.assertEqual(c.resolve_tap(("pause", 10, 10), (None, 20, 20)), "pause")

    def test_drag_away_cancels(self):
        self.assertIsNone(c.resolve_tap(("pause", 10, 10), ("seek:10", 200, 10)))

    def test_no_down_seen(self):
        self.assertEqual(c.resolve_tap(None, ("pause", 1, 1)), "pause")


class OverlapAlpha(unittest.TestCase):
    def test_translucent_only_while_menu_overlaps_video(self):
        self.assertEqual(c.overlap_alpha(True, True), c.MENU_ALPHA)
        self.assertEqual(c.overlap_alpha(True, False), 1.0)   # menu closed: full video
        self.assertEqual(c.overlap_alpha(False, True), 1.0)   # nothing playing: full menu
        self.assertEqual(c.overlap_alpha(False, False), 1.0)

    def test_menu_alpha_is_in_the_70_to_80_percent_range(self):
        self.assertGreaterEqual(c.MENU_ALPHA, 0.7)
        self.assertLessEqual(c.MENU_ALPHA, 0.8)



class LaserOnly(unittest.TestCase):
    SRC = os.path.join(os.path.dirname(__file__), "..", "frame")

    def src(self, f):
        return open(os.path.join(self.SRC, f), encoding="utf-8").read()

    def test_only_panel_and_socket_toggle_pause(self):
        import re
        callers = re.findall(r'toggle_pause\("([^"]+)"\)', self.src("fvp_app.py"))
        self.assertEqual(sorted(callers), ["control socket", "panel click"])
        self.assertNotRegex(self.src("fvp_app.py"), r"self\.paused = True(?![^\n]*#)")

    def test_no_steamvr_input_code(self):
        for f in ("fvp_app.py", "fvp_openvr.py", "fvp_controls.py"):
            s = self.src(f)
            for word in ("IVRInput", "IVRApplications", "actions.json", "vrmanifest", "ActionSet", "dpad",
                         "GLOBAL_PRIORITY"):
                self.assertNotIn(word, s, (f, word))
        self.assertFalse(os.path.exists(os.path.join(self.SRC, "input")))

    def test_panel_rotation_buttons(self):
        s = self.src("fvp_app.py")
        for k in ('"turn:-"', '"turn:+"', '"recenter"'):
            self.assertIn(k, s)
        self.assertEqual(c.TURN_STEP, 30.0)


if __name__ == "__main__":
    unittest.main()
