import json
import os
import unittest

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
        self.assertEqual(got["/actions/fvp/in/right_stick"][0], "/user/hand/right/input/thumbstick")

    def test_every_bound_action_is_declared(self):
        a = {x["name"] for x in json.load(open(os.path.join(D, "actions.json")))["actions"]}
        for f in FILES:
            for o in outputs(f):
                self.assertIn(o[0], a)


if __name__ == "__main__":
    unittest.main()
