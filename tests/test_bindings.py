import json
import os
import unittest
import sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

D = os.path.join(os.path.dirname(__file__), "..", "frame", "input")


def outputs(f):
    b = json.load(open(os.path.join(D, f)))
    out = []
    for st in b["bindings"].values():
        for s in st.get("sources", []):
            for inp, o in s.get("inputs", {}).items():
                out.append((o["output"], s["path"], s.get("mode"), inp))
    return out


class Bindings(unittest.TestCase):
    """No default bindings at all: the user binds the actions in SteamVR's binding settings."""

    def test_no_default_bindings(self):
        a = json.load(open(os.path.join(D, "actions.json"), encoding="utf-8"))
        self.assertEqual(a.get("default_bindings", []), [])
        self.assertEqual([f for f in os.listdir(D) if f.startswith("bindings")], [])

    def test_no_system_button(self):
        text = open(os.path.join(D, "actions.json")).read().lower()
        self.assertNotIn("/input/system", text)


class Rebindable(unittest.TestCase):
    """Names SteamVR's binding settings show, and the app manifest that makes it list the app."""

    def test_every_action_and_set_named_in_ja_and_en(self):
        import json
        a = json.load(open(os.path.join(ROOT, "frame/input/actions.json"), encoding="utf-8"))
        names = [x["name"] for x in a["actions"]] + [x["name"] for x in a["action_sets"]]
        loc = {l["language_tag"]: l for l in a["localization"]}
        for tag in ("en_US", "ja_JP"):
            for n in names:
                self.assertIn(n, loc[tag], (tag, n))
        ja = loc["ja_JP"]
        self.assertEqual(ja["/actions/fvp/in/seek_back"], "シーク戻る")
        self.assertEqual(ja["/actions/fvp/in/seek_fwd"], "シーク進む")
        self.assertEqual(ja["/actions/fvp/in/play_pause"], "再生・一時停止")
        self.assertEqual(ja["/actions/fvp/in/scroll"], "スクロール")
        self.assertEqual(ja["/actions/fvp/in/turn"], "視点回転")

    def test_vrmanifest(self):
        import importlib.util  # by path: other tests put a stub fvp_openvr in sys.modules
        spec = importlib.util.spec_from_file_location("fvp_openvr_real", os.path.join(ROOT, "frame/fvp_openvr.py"))
        fvp_openvr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fvp_openvr)
        m = fvp_openvr.vrmanifest("cympfh.frame-video-player", "/x/input/actions.json", "/x/frame-video-player")
        app = m["applications"][0]
        self.assertEqual(app["app_key"], "cympfh.frame-video-player")
        self.assertEqual(app["action_manifest_path"], "/x/input/actions.json")
        self.assertTrue(app["is_dashboard_overlay"])
        self.assertEqual(app["binary_path_linux_arm"], "/x/frame-video-player")  # arm64 SteamVR skips the app without it
        self.assertEqual(app["strings"]["ja_jp"]["name"], "動画プレイヤー")

    def test_no_sticks_toggle(self):
        src = open(os.path.join(ROOT, "frame/fvp_app.py"), encoding="utf-8").read()
        self.assertNotIn('"sticks"', src)
        self.assertNotIn("スティック操作", src)
