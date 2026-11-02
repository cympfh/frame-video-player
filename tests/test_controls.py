"""Stick, seek, rotation, scroll and tap logic (pure functions in fvp_controls, plus the cube turn in fvp_app)."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "frame"))
for name in ("fvp_openvr", "fvp_gl", "fvp_cairo"):
    sys.modules.setdefault(name, types.ModuleType(name))
import fvp_app as a  # noqa: E402
import fvp_controls as c  # noqa: E402


class Deadzone(unittest.TestCase):
    def test_inside_is_zero(self):
        for v in (0, 0.1, -0.25):
            self.assertEqual(c.deadzone(v), 0.0)

    def test_edges_and_sign(self):
        self.assertAlmostEqual(c.deadzone(1.0), 1.0)
        self.assertAlmostEqual(c.deadzone(-1.0), -1.0)
        self.assertAlmostEqual(c.deadzone(1.5), 1.0)
        self.assertGreater(c.deadzone(0.6), 0)


class Rotation(unittest.TestCase):
    def test_proportional_and_signed(self):
        full = c.yaw_step(1.0, 0.1, 90)
        self.assertAlmostEqual(full, 9.0)
        self.assertAlmostEqual(c.yaw_step(-1.0, 0.1, 90), -9.0)
        half = c.yaw_step(0.6, 0.1, 90)
        self.assertTrue(0 < half < full)
        self.assertEqual(c.yaw_step(0.2, 0.1, 90), 0.0)

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


class Seek(unittest.TestCase):
    def test_single_step_then_repeat(self):
        s = c.SeekRepeater()
        self.assertEqual(s.feed(0.9, 0.0), 10.0)
        self.assertEqual(s.feed(0.9, 0.2), 0.0)      # waits before repeating
        self.assertEqual(s.feed(0.9, 0.5), 10.0)     # repeat
        self.assertEqual(s.feed(0.0, 0.6), 0.0)      # released
        self.assertEqual(s.feed(-0.9, 0.7), -10.0)   # other way, at once

    def test_small_push_and_hysteresis(self):
        s = c.SeekRepeater()
        self.assertEqual(s.feed(0.5, 0.0), 0.0)
        self.assertEqual(s.feed(0.7, 0.1), 10.0)
        self.assertEqual(s.feed(0.45, 0.2), 0.0)     # still held (above release)
        self.assertEqual(s.dir, 1)

    def test_harder_push_repeats_faster(self):
        def count(x):
            s, n, t = c.SeekRepeater(), 0, 0.0
            while t < 3.0:
                n += s.feed(x, t) != 0
                t += 0.01
            return n
        self.assertGreater(count(1.0), count(0.65))

    def test_long_hold_takes_bigger_steps(self):
        s, t, steps = c.SeekRepeater(), 0.0, []
        while t < 4.0:
            v = s.feed(1.0, t)
            if v:
                steps.append(v)
            t += 0.01
        self.assertEqual(steps[0], 10.0)
        self.assertEqual(steps[-1], 30.0)

    def test_click_edge(self):
        e = c.Edge()
        self.assertEqual([e.feed(x) for x in (False, True, True, False, True)], [False, True, False, False, True])


class Scroll(unittest.TestCase):
    def test_clamp(self):
        self.assertEqual(c.scroll_clamp(-3, 20, 7), 0)
        self.assertEqual(c.scroll_clamp(50, 20, 7), 13)
        self.assertEqual(c.scroll_clamp(5, 3, 7), 0)
        self.assertAlmostEqual(c.scroll_clamp(2.5, 20, 7), 2.5)

    def test_stick_up_moves_toward_top(self):
        self.assertLess(c.scroll_from_smooth(0.5), 0)
        self.assertLess(c.scroll_from_stick(1.0, 0.1), 0)
        self.assertEqual(c.scroll_from_stick(0.1, 0.1), 0)

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



class SystemGuard(unittest.TestCase):
    def test_origin(self):
        self.assertTrue(c.is_system_origin("Left Hand Frame Controller System"))
        self.assertTrue(c.is_system_origin("左手 Steam ボタン"))
        self.assertFalse(c.is_system_origin("Left Hand Frame Controller Thumbstick"))
        self.assertFalse(c.is_system_origin(""))

    def test_dash_guard(self):
        g = c.DashGuard()
        self.assertFalse(g.feed(False, 10.0))
        self.assertTrue(g.feed(True, 10.1))
        self.assertTrue(g.feed(True, 10.5))
        self.assertFalse(g.feed(True, 11.0))


if __name__ == "__main__":
    unittest.main()
