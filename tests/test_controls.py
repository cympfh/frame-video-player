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


class OverlapAlpha(unittest.TestCase):
    def test_translucent_only_while_menu_overlaps_video(self):
        self.assertEqual(c.overlap_alpha(True, True), c.MENU_ALPHA)
        self.assertEqual(c.overlap_alpha(True, False), 1.0)   # menu closed: full video
        self.assertEqual(c.overlap_alpha(False, True), 1.0)   # nothing playing: full menu
        self.assertEqual(c.overlap_alpha(False, False), 1.0)

    def test_menu_alpha_is_in_the_70_to_80_percent_range(self):
        self.assertGreaterEqual(c.MENU_ALPHA, 0.7)
        self.assertLessEqual(c.MENU_ALPHA, 0.8)


class Dpad(unittest.TestCase):
    def test_axis(self):
        self.assertEqual(c.dpad_axis(False, True), 1.0)
        self.assertEqual(c.dpad_axis(True, False), -1.0)
        self.assertEqual(c.dpad_axis(False, False), 0.0)

    def test_hold_repeats_seek(self):
        r = c.SeekRepeater()
        self.assertEqual(r.feed(c.dpad_axis(False, True), 0.0), r.STEP)
        self.assertNotEqual(r.feed(1.0, 5.0), 0)
        self.assertEqual(r.feed(0.0, 5.1), 0)


class Gate(unittest.TestCase):
    N = a.BUTTON_ACTIONS

    def run_seq(self, seq, action="play_pause"):
        g, e, hits = c.ButtonGate(self.N), c.Edge(), 0
        for st, dash, t in seq:
            hits += e.feed(g.feed(st, dash, t)[action])
        return hits

    def test_dashboard_close_with_everything_pressed_never_pauses(self):
        # the exact pattern from the Frame log: dash closes and all actions read pressed
        allp = {n: True for n in self.N}
        seq = [({}, True, 0.0), (allp, False, 1.0), (allp, False, 2.5), ({}, False, 3.0)]
        self.assertEqual(self.run_seq(seq), 0)

    def test_dashboard_open_close_never_changes_play_state(self):
        allp = {n: True for n in self.N}
        seq, t = [], 0.0
        for k in range(10):
            for st in ({}, {"play_pause": True}, allp):
                seq.append((st, k % 2 == 0, t)); t += 0.05
        self.assertEqual(self.run_seq(seq), 0)

    def test_press_held_through_close_needs_release(self):
        p = {"play_pause": True}
        seq = [(p, True, 0.0), (p, False, 0.1), (p, False, 2.0), ({}, False, 2.1), (p, False, 2.2)]
        self.assertEqual(self.run_seq(seq), 1)

    def test_real_press_after_settle(self):
        seq = [({}, False, 0.0), ({}, False, 1.0), ({"play_pause": True}, False, 1.1)]
        self.assertEqual(self.run_seq(seq), 1)

    def test_chord_ignored(self):
        seq = [({}, False, 0.0), ({}, False, 1.0),
               ({"play_pause": True, "seek_back": True}, False, 1.1), ({}, False, 1.2)]
        self.assertEqual(self.run_seq(seq), 0)


class Priority(unittest.TestCase):
    def test_global_only_while_loaded_and_dashboard_closed(self):
        G = 0x01000000
        self.assertEqual(c.input_priority(True, False, G), G)
        self.assertEqual(c.input_priority(True, True, G), 0)
        self.assertEqual(c.input_priority(False, False, G), 0)

    def test_states_frozen_at_close_then_real_press(self):
        """Frame log 16:29: back+play read pressed from dashboard close; a real press after release counts."""
        g, e = c.ButtonGate(a.BUTTON_ACTIONS), c.Edge()
        stuck = {"seek_back": True, "play_pause": True}
        hits = 0
        for st, dash, t in [({}, True, 0.0), (stuck, False, 0.1), (stuck, False, 3.0), ({}, False, 3.1),
                            ({"play_pause": True}, False, 3.2)]:
            hits += e.feed(g.feed(st, dash, t)["play_pause"])
        self.assertEqual(hits, 1)


class PauseOrigin(unittest.TestCase):
    def test_no_event_or_dashboard_path_toggles_pause(self):
        """Only the panel button, the bound action (through ButtonGate) and the control socket may pause."""
        import re
        src = open(os.path.join(os.path.dirname(__file__), "..", "frame", "fvp_app.py"), encoding="utf-8").read()
        callers = re.findall(r'toggle_pause\("([^"]+)"\)', src)
        self.assertEqual(sorted(callers), ["action play_pause", "control socket", "panel click"])
        self.assertNotRegex(src, r"self\.paused = True(?![^\n]*#)")  # only toggle_pause / stop paths set it

    def test_panel_rotation_buttons(self):
        s = open(os.path.join(os.path.dirname(__file__), "..", "frame", "fvp_app.py"), encoding="utf-8").read()
        for k in ('"turn:-"', '"turn:+"', '"recenter"'):
            self.assertIn(k, s)
        self.assertEqual(c.TURN_STEP, 30.0)


if __name__ == "__main__":
    unittest.main()
