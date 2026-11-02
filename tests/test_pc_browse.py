"""PC folder browsing: listing, recent folders, and the PC tab buttons (no PC or headset needed)."""
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "frame"))
for name in ("fvp_openvr", "fvp_gl", "fvp_cairo"):
    sys.modules.setdefault(name, types.ModuleType(name))
import fvp_app as a  # noqa: E402
import fvp_media as m  # noqa: E402


class FakeCanvas:
    def __init__(self, *args):
        pass

    def text_width(self, t, size):
        return len(t) * size * 0.6

    def __getattr__(self, name):
        return lambda *args, **kw: None


class Listing(unittest.TestCase):
    def setUp(self):
        m._pc.update(base="http://pc:47652", token="tok")

    def test_top_has_videos_and_drives(self):
        with mock.patch.object(m, "_pc_get", return_value={"drives": ["C:/", "F:/"], "videos": "C:/Users/u/Videos"}):
            items, url, path = m.list_pc_dir("")
        self.assertEqual(path, "")
        self.assertEqual([i.path for i in items], ["C:/Users/u/Videos", "C:/", "F:/"])
        self.assertTrue(all(i.kind == "pcdir" for i in items))

    def test_folder_has_parent_dirs_files(self):
        d = {"path": "F:/movies", "parent": "F:/", "dirs": ["a b"], "files": [{"name": "x #1.mp4", "size": 3}]}
        with mock.patch.object(m, "_pc_get", return_value=d):
            items, url, path = m.list_pc_dir("F:/movies")
        self.assertEqual([(i.kind, i.path) for i in items],
                         [("pcdir", "F:/"), ("pcdir", "F:/movies/a b"), ("pc", "F:/movies/x #1.mp4")])
        self.assertEqual(items[2].video, "http://pc:47652/f/tok/F%3A%2Fmovies%2Fx%20%231.mp4")

    def test_drive_root_parent_goes_to_top(self):
        with mock.patch.object(m, "_pc_get", return_value={"path": "F:/", "parent": None, "dirs": [], "files": []}):
            items, _u, _p = m.list_pc_dir("F:/")
        self.assertEqual(items[0].path, "")

    def test_folder_name(self):
        self.assertEqual(m.folder_name("F:/movies/anime"), "anime")
        self.assertEqual(m.folder_name("F:/"), "F:/")


class Recent(unittest.TestCase):
    def test_most_recent_first_and_capped(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(m, "STATE", d):
            for i in range(12):
                m.add_pc_folder("F:/%d" % i)
            m.add_pc_folder("F:/5")
            h = m.load_pc_folders()
        self.assertEqual(len(h), 10)
        self.assertEqual(h[:3], ["F:/5", "F:/11", "F:/10"])


class PanelButtons(unittest.TestCase):
    def test_pc_tab_buttons(self):
        a.cairo.Canvas = FakeCanvas
        p = a.Panel()
        p.tab, p.pc_dir = "pc", "F:/movies"
        p.pc_recent = ["F:/movies", "C:/Users/u/Videos", "F:/", "D:/x", "D:/y"]
        p.items = [m.dir_item("[フォルダ]  %d" % i, "F:/%d" % i) for i in range(20)]
        app = types.SimpleNamespace(settings={"volume": 1.0, "width": 3.0, "distance": 2.5, "subs": True}, item=None, resume={}, status="", status_warn=False, paused=False,
                                    mode="flat", position=lambda: 0)
        try:
            p.draw(app)
        except (AttributeError, KeyError, TypeError):
            pass  # the now-playing part needs more of the app; the list part is drawn before it
        keys = [b[0] for b in p.buttons]
        self.assertIn("pc:top", keys)
        self.assertIn("pc:recent", keys)
        self.assertEqual([k for k in keys if k.startswith("pcrecent:")], ["pcrecent:%d" % i for i in range(4)])
        rows = [b for b in p.buttons if b[0].startswith("item:")]
        self.assertEqual(len(rows), p.rows())
        self.assertTrue(all(b[4] >= 40 for b in rows))  # big enough to point at
        self.assertTrue(all(b[2] + b[4] <= 500 for b in rows))  # stays above the now-playing area
        self.assertTrue(p.scroll_by(3))  # right stick scroll works on the folder list


if __name__ == "__main__":
    unittest.main()
