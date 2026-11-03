"""Flat screen placement (fvp_app.screen_matrix): level gaze keeps the old floor-plane behavior,
a steep gaze (lying down) puts the screen in front of the eyes, tilted to face the head."""
import math
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "frame"))
for name in ("fvp_openvr", "fvp_gl", "fvp_cairo"):
    sys.modules.setdefault(name, types.ModuleType(name))
import fvp_app as a  # noqa: E402


def pose(x, y, z, t=(1.0, 1.2, 0.5)):
    """3x4 row-major pose from the head's axis columns (x=right, y=up, z=back) and position t."""
    return [x[0], y[0], z[0], t[0],
            x[1], y[1], z[1], t[1],
            x[2], y[2], z[2], t[2]]


def cols(m):
    return (m[0], m[4], m[8]), (m[1], m[5], m[9]), (m[2], m[6], m[10]), (m[3], m[7], m[11])


def rot_x(deg, t=(1.0, 1.2, 0.5)):
    """Pose of a head pitched by deg (positive = looking up). Identity at 0, forward [0,0,-1]."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return pose((1, 0, 0), (0, c, s), (0, -s, c), t)


class LevelGaze(unittest.TestCase):
    def test_no_pose_is_vertical_ahead(self):
        x, y, z, t = cols(a.screen_matrix(None, 2.5))
        self.assertEqual(y, (0, 1, 0))
        self.assertEqual(z, (0, 0, 1))
        self.assertAlmostEqual(t[0], 0.0)
        self.assertAlmostEqual(t[1], 1.6)
        self.assertAlmostEqual(t[2], -2.5)

    def test_level_pose_matches_floor_plane(self):
        x, y, z, t = cols(a.screen_matrix(rot_x(0), 2.0))
        self.assertEqual(y, (0, 1, 0))  # the screen stands upright
        for got, want in zip(t, (1.0, 1.2, 0.5 - 2.0)):
            self.assertAlmostEqual(got, want)

    def test_slight_pitch_stays_floor_plane(self):
        # 20 degrees down is below GAZE_PITCH: same placement as level, still upright
        x, y, z, t = cols(a.screen_matrix(rot_x(-20), 2.0))
        self.assertEqual(y, (0, 1, 0))
        self.assertAlmostEqual(t[2], 0.5 - 2.0)


class SteepGaze(unittest.TestCase):
    def test_lying_on_back_screen_faces_down(self):
        # looking straight up: screen hangs above the head, picture top toward the head's up
        x, y, z, t = cols(a.screen_matrix(rot_x(90), 1.5))
        for got, want in zip(z, (0, -1, 0)):  # normal points down at the head
            self.assertAlmostEqual(got, want)
        for got, want in zip(x, (1, 0, 0)):  # not mirrored: screen right = head right
            self.assertAlmostEqual(got, want)
        for got, want in zip(y, (0, 0, 1)):
            self.assertAlmostEqual(got, want)
        for got, want in zip(t, (1.0, 1.2 + 1.5, 0.5)):
            self.assertAlmostEqual(got, want)

    def test_face_down_screen_faces_up(self):
        x, y, z, t = cols(a.screen_matrix(rot_x(-90), 1.0))
        for got, want in zip(z, (0, 1, 0)):
            self.assertAlmostEqual(got, want)
        for got, want in zip(t, (1.0, 1.2 - 1.0, 0.5)):
            self.assertAlmostEqual(got, want)

    def test_sixty_degrees_is_gaze_mode(self):
        x, y, z, t = cols(a.screen_matrix(rot_x(60), 2.0))
        f3 = (0, math.sin(math.radians(60)), -math.cos(math.radians(60)))
        for got, want in zip(z, (-f3[0], -f3[1], -f3[2])):
            self.assertAlmostEqual(got, want)
        for got, want in zip(t, (1.0, 1.2 + f3[1] * 2.0, 0.5 + f3[2] * 2.0)):
            self.assertAlmostEqual(got, want)
        self.assertAlmostEqual(math.sqrt(sum(c * c for c in y)), 1.0)  # still an orthonormal basis

    def test_head_up_parallel_to_gaze_falls_back(self):
        # head rolled so its up is parallel to the gaze: use the head's right instead, no crash
        p = pose((0, -1, 0), (0, 0, 1), (0, -1, 0))  # forward +y, up +z, right -y
        x, y, z, t = cols(a.screen_matrix(p, 1.0))
        self.assertAlmostEqual(math.sqrt(sum(c * c for c in x)), 1.0)
        self.assertAlmostEqual(math.sqrt(sum(c * c for c in y)), 1.0)
        self.assertAlmostEqual(sum(x[i] * y[i] for i in range(3)), 0.0)


if __name__ == "__main__":
    unittest.main()
