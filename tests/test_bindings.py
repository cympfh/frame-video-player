import json
import os
import unittest
import sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

D = os.path.join(os.path.dirname(__file__), "..", "frame", "input")
FILES = ["bindings_frame_controller.json", "bindings_knuckles.json"]


def outputs(f):
    b = json.load(open(os.path.join(D, f)))
    out = []
    for st in b["bindings"].values():
        for s in st.get("sources", []):
            for inp, o in s.get("inputs", {}).items():
                out.append((o["output"], s["path"], s.get("mode"), inp))
    return out


class Bindings(unittest.TestCase):
    def test_no_system_button(self):
        for f in FILES + ["actions.json"]:
            text = open(os.path.join(D, f)).read().lower()
            self.assertNotIn("/input/system", text, f)
            self.assertNotIn("/input/steam", text, f)

    def test_no_left_joystick(self):
        for f in FILES:
            for o in outputs(f):
                self.assertFalse(o[1].startswith("/user/hand/left/input/thumbstick"), (f, o))

    def test_left_dpad_on_frame_controller(self):
        got = {o[0]: o[1:] for o in outputs("bindings_frame_controller.json")}
        self.assertEqual(got["/actions/fvp/in/seek_back"], ("/user/hand/left/input/dpad_left", "button", "click"))
        self.assertEqual(got["/actions/fvp/in/seek_fwd"], ("/user/hand/left/input/dpad_right", "button", "click"))
        self.assertEqual(got["/actions/fvp/in/play_pause"], ("/user/hand/left/input/dpad_down", "button", "click"))
        self.assertEqual(got["/actions/fvp/in/turn"][0], "/user/hand/right/input/thumbstick")
        self.assertEqual(got["/actions/fvp/in/scroll"][0], "/user/hand/right/input/thumbstick")

    def test_every_bound_action_is_declared(self):
        a = {x["name"] for x in json.load(open(os.path.join(D, "actions.json")))["actions"]}
        for f in FILES:
            for o in outputs(f):
                self.assertIn(o[0], a)


if __name__ == "__main__":
    unittest.main()


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
