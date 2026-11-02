"""Unit tests for fvp_media (no headset needed). Run: python3 -m unittest discover -s tests"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "frame"))
import fvp_media as m  # noqa: E402


class Detect(unittest.TestCase):
    def proj(self, name):
        return m.detect_projection(name, {})

    def stereo(self, name, proj="flat"):
        return m.detect_stereo(name, {}, 1920, 1080, proj)

    def test_projection_by_name(self):
        self.assertEqual(self.proj("trip_360.mp4"), "360")
        self.assertEqual(self.proj("Trip 360° tour.mp4"), "360")
        self.assertEqual(self.proj("concert_180_LR.mp4"), "180")
        self.assertEqual(self.proj("VR180 live.mp4"), "180")
        self.assertEqual(self.proj("show ep180.mp4"), "flat")
        self.assertEqual(self.proj("xbox360 review.mp4"), "flat")
        self.assertEqual(self.proj("1360x768.mp4"), "flat")
        self.assertEqual(self.proj("movie.mp4"), "flat")

    def test_projection_by_metadata(self):
        info = {"streams": [{"side_data_list": [{"side_data_type": "Spherical Mapping",
                                                  "projection": "equirectangular"}]}]}
        self.assertEqual(m.detect_projection("a.mp4", info), "360")
        info["streams"][0]["side_data_list"][0]["bound_left"] = 1073741823
        self.assertEqual(m.detect_projection("a.mp4", info), "180")

    def test_stereo(self):
        self.assertEqual(self.stereo("movie_SBS.mkv"), "sbs")
        self.assertEqual(self.stereo("movie.hsbs.mkv"), "sbs")
        self.assertEqual(self.stereo("movie_OU.mkv"), "tb")
        self.assertEqual(self.stereo("clip_LR_final.mp4"), "mono")   # flat: LR alone is not enough
        self.assertEqual(self.stereo("concert_180_LR.mp4", "180"), "sbs")
        self.assertEqual(self.stereo("tour_360_TB.mp4", "360"), "tb")
        self.assertEqual(self.stereo("world.mp4"), "mono")


class Escape(unittest.TestCase):
    def test_strings(self):
        self.assertEqual(m.filter_path("/a/b.srt"), "/a/b.srt")
        self.assertEqual(m.filter_path("Ocean's Eleven.mkv"), "Ocean\\\\\\'s Eleven.mkv")
        self.assertEqual(m.filter_path("a:b"), "a\\\\:b")
        self.assertEqual(m.filter_path("a,b[c];d"), "a\\,b\\[c\\]\\;d")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_ffmpeg_accepts_awkward_names(self):
        d = tempfile.mkdtemp()
        try:
            for name in ("Ocean's Eleven", "a:b, [c]; d", "back\\slash"):
                base = os.path.join(d, name)
                with open(base + ".srt", "w") as f:
                    f.write("1\n00:00:00,000 --> 00:00:01,000\nhello\n")
                it = m.Item("frame", name, "k", base + ".mkv", subs=base + ".srt")
                it.width, it.height, it.has_audio = 320, 240, False
                vf, w, h = m.video_filter(it, "flat", True)
                r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.5",
                                    "-vf", vf, "-f", "null", "-"], capture_output=True)
                self.assertEqual(r.returncode, 0, (name, vf, r.stderr.decode()[-300:]))
        finally:
            shutil.rmtree(d)


class Urls(unittest.TestCase):
    def test_redact(self):
        s = "http://192.0.2.1:47652/v/" + "ab" * 24 + "/x.mp4"
        self.assertNotIn("ab" * 24, m.redact(s))
        self.assertIn("/v/***/x.mp4", m.redact(s))

    def test_pc_url(self):
        self.assertEqual(m.pc_url("http://192.0.2.1:47652", "t0k", "a b/c#1?.mp4"),
                         "http://192.0.2.1:47652/v/t0k/a%20b/c%231%3F.mp4")

    def test_youtube_url_after_double_dash(self):
        seen = {}

        class R:
            returncode = 0
            stdout = b"Title\nhttps://v.example/1\nhttps://a.example/2\n"
            stderr = b""

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return R()
        old_run, old_path = m.subprocess.run, m.yt_dlp_path
        m.subprocess.run, m.yt_dlp_path = fake_run, lambda: "/bin/yt-dlp"
        try:
            it = m.youtube_item("--exec=evil")
        finally:
            m.subprocess.run, m.yt_dlp_path = old_run, old_path
        self.assertEqual(seen["cmd"][-2:], ["--", "--exec=evil"])
        self.assertEqual((it.title, it.video, it.audio), ("Title", "https://v.example/1", "https://a.example/2"))



class HeavyVideo(unittest.TestCase):
    def test_too_heavy(self):
        it = m.Item("pc", "a", "k", "u")
        it.width, it.height = 7680, 3840
        self.assertTrue(m.too_heavy(it))
        it.width, it.height = 3840, 2160
        self.assertFalse(m.too_heavy(it))

    def test_clock_restart(self):
        t = [10.0]
        c = m.Clock(lambda: t[0])
        t[0] = 15.0
        c.restart()
        t[0] = 16.0
        self.assertAlmostEqual(c.now(), 1.0)
        c.pause()
        t[0] = 20.0
        c.restart()
        self.assertAlmostEqual(c.now(), 0.0)
        c.resume()
        t[0] = 21.0
        self.assertAlmostEqual(c.now(), 1.0)

    def test_audio_waits_for_first_frame(self):
        import threading
        pb = m.Playback.__new__(m.Playback)
        pb.lock, pb.running = threading.Lock(), threading.Event()
        pb.running.set()
        pb.stopped, pb.started, pb.aproc, pb.acmd = False, False, None, ["ffmpeg", "audio"]
        pb.start_pos, pb.t_open = 12.0, 0.0
        pb.clock = m.Clock()
        self.assertEqual(pb.position(), 12.0)
        started = []

        class P:
            pid, stderr = 1, []

            def poll(self):
                return None
        orig = m.subprocess.Popen
        m.subprocess.Popen = lambda cmd, **k: started.append(cmd) or P()
        try:
            pb._first_frame()
        finally:
            m.subprocess.Popen = orig
        self.assertEqual(started, [["ffmpeg", "audio"]])
        self.assertTrue(pb.started)
        pb2 = m.Playback.__new__(m.Playback)
        pb2.__dict__.update(pb.__dict__)
        pb2.stopped, pb2.aproc = True, None
        pb2._first_frame()
        self.assertIsNone(pb2.aproc)


if __name__ == "__main__":
    unittest.main()


class Examples(unittest.TestCase):
    def test_360_example(self):
        t, u = m.YOUTUBE_EXAMPLES[0]
        self.assertTrue(u.startswith("https://www.youtube.com/watch?v="))
        self.assertEqual(m.detect_projection(t, {}), "360")


class Broken(unittest.TestCase):
    def test_no_picture_is_not_playable(self):
        it = m.Item("pc", "HAWA.mp4", "k", "u")  # ffprobe: moov atom not found -> 0x0
        self.assertFalse(m.playable(it))
        it.width, it.height = 1920, 1080
        self.assertTrue(m.playable(it))
