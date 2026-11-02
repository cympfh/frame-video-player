import json
import os
import unittest

D = os.path.join(os.path.dirname(__file__), "..", "frame", "input")
FILES = ["bindings_frame_controller.json", "bindings_knuckles.json"]


def sources(f):
    b = json.load(open(os.path.join(D, f)))
    for st in b["bindings"].values():
        for kind in ("sources", "chords", "poses", "haptics", "skeleton"):
            for s in st.get(kind, []):
                yield s


class Bindings(unittest.TestCase):
    def test_no_system_button(self):
        for f in FILES + ["actions.json"]:
            text = open(os.path.join(D, f)).read().lower()
            self.assertNotIn("/input/system", text, f)
            self.assertNotIn("/input/steam", text, f)

    def test_play_pause_only_on_left_stick_click(self):
        for f in FILES:
            hits = []
            for s in sources(f):
                for inp, o in s.get("inputs", {}).items():
                    if o.get("output") == "/actions/fvp/in/left_click":
                        hits.append((s["path"], s.get("mode"), inp))
            self.assertEqual(hits, [("/user/hand/left/input/thumbstick", "joystick", "click")], f)


if __name__ == "__main__":
    unittest.main()
