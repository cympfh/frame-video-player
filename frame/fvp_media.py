"""Media side of frame-video-player: probing, sources (Frame / PC / YouTube), and the ffmpeg processes.

Video: ffmpeg decodes to raw RGBA on stdout (already scaled, and for 360/180 already converted to a
6-face cube with the v360 filter). Audio: a second ffmpeg plays to PipeWire (pulse output).
Pause and seek restart both processes at the new position.
"""
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.parse
import urllib.request

log = logging.getLogger("fvp")

HOME = os.path.expanduser("~")
OPT = os.path.join(HOME, ".local/opt/frame-video-player")
STATE = os.path.join(HOME, ".local/state/frame-video-player")
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".ts", ".m2ts", ".wmv", ".flv", ".mpg", ".mpeg")
SUB_EXTS = (".srt", ".ass", ".vtt")

FLAT_MAX = (1920, 1080)
CUBE_FACE = int(os.environ.get("FVP_CUBE_FACE", "720"))

_SECRET_RE = re.compile(r"(/(?:v|list)/)[0-9a-f]{16,}")


def redact(s):
    """Hide the PC streaming token in anything that goes to the log."""
    return _SECRET_RE.sub(r"\1***", str(s))


def yt_dlp_path():
    for p in (os.path.join(OPT, "bin/yt-dlp"), shutil.which("yt-dlp") or ""):
        if p and os.access(p, os.X_OK):
            return p
    return None


# ---------------------------------------------------------------- detection

def detect_projection(name, info):
    """'flat' / '360' / '180' from metadata (spherical side data, stereo3d) or the name."""
    for st in info.get("streams", []):
        for sd in st.get("side_data_list", []) or []:
            t = (sd.get("side_data_type") or "").lower()
            if "spherical" in t:
                proj = (sd.get("projection") or "").lower()
                if "equirect" in proj:
                    # 180: the bounds cut half of the sphere away
                    if int(sd.get("bound_left", 0) or 0) > 0 or int(sd.get("bound_right", 0) or 0) > 0:
                        return "180"
                    return "360"
    n = name.lower()
    if re.search(r"(^|[^0-9])180([^0-9]|$)|vr180|_180_|180x180", n):
        return "180"
    if re.search(r"(^|[^0-9])360([^0-9]|$)|equirect|_360_|360vr|360°", n):
        return "360"
    return "flat"


def detect_stereo(name, info, w, h):
    """'mono' / 'sbs' / 'tb' (stereo layout; only the left/top eye is shown)."""
    for st in info.get("streams", []):
        for sd in st.get("side_data_list", []) or []:
            if "stereo" in (sd.get("side_data_type") or "").lower():
                t = (sd.get("type") or "").lower()
                if "side" in t:
                    return "sbs"
                if "top" in t:
                    return "tb"
    n = name.lower()
    if re.search(r"(^|[^a-z])(sbs|lr|3dh)([^a-z]|$)", n):
        return "sbs"
    if re.search(r"(^|[^a-z])(tb|ou|3dv)([^a-z]|$)", n):
        return "tb"
    return "mono"


def ffprobe(src, headers=None):
    cmd = ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json"]
    if headers:
        cmd += ["-headers", headers]
    cmd.append(src)
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=30)
        if out.returncode != 0:
            log.warning("ffprobe failed: %s", redact(out.stderr.decode(errors="replace")))
        return json.loads(out.stdout or b"{}")
    except Exception as e:
        log.warning("ffprobe error: %s", redact(e))
        return {}


# ---------------------------------------------------------------- items

class Item:
    """One playable thing. key is stable (used for resume)."""

    def __init__(self, kind, title, key, video, audio=None, subs=None):
        self.kind, self.title, self.key = kind, title, key
        self.video, self.audio = video, audio or video
        self.subs = subs  # sidecar subtitle file (Frame files only)
        self.info = None
        self.duration = 0.0
        self.width = self.height = 0
        self.has_audio = True
        self.sub_streams = 0
        self.projection = "flat"
        self.stereo = "mono"

    def probe(self):
        self.info = ffprobe(self.video)
        fmt = self.info.get("format", {})
        try:
            self.duration = float(fmt.get("duration") or 0)
        except ValueError:
            self.duration = 0.0
        vs = [s for s in self.info.get("streams", []) if s.get("codec_type") == "video"]
        if vs:
            self.width, self.height = int(vs[0].get("width") or 0), int(vs[0].get("height") or 0)
        self.sub_streams = len([s for s in self.info.get("streams", []) if s.get("codec_type") == "subtitle"])
        if self.audio == self.video:
            self.has_audio = any(s.get("codec_type") == "audio" for s in self.info.get("streams", []))
        self.projection = detect_projection(self.title, self.info)
        self.stereo = detect_stereo(self.title, self.info, self.width, self.height)
        log.info("probe: %s %dx%d %.1fs proj=%s stereo=%s subs=%d audio=%s", self.title, self.width, self.height,
                 self.duration, self.projection, self.stereo, self.sub_streams, self.has_audio)


def local_root():
    d = os.path.join(HOME, "Videos")
    os.makedirs(d, exist_ok=True)
    return d


def list_local():
    root = local_root()
    out = []
    for dp, dns, fns in os.walk(root, followlinks=True):
        dns[:] = sorted(d for d in dns if not d.startswith("."))
        for f in sorted(fns, key=str.lower):
            if f.lower().endswith(VIDEO_EXTS):
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, root)
                base = os.path.splitext(full)[0]
                sub = next((base + e for e in SUB_EXTS if os.path.exists(base + e)), None)
                out.append(Item("frame", rel, "frame:" + rel, full, subs=sub))
        if len(out) > 5000:
            break
    return out


def _fsr_core():
    """Re-use frame-steamvr-remote's pairing (same PC, same secret)."""
    import sys
    d = os.path.join(HOME, ".local/opt/frame-steamvr-remote")
    if d not in sys.path:
        sys.path.append(d)
    import fsr_core  # noqa
    return fsr_core


def pc_video():
    """Ask the paired PC for a streaming token (and a URL the tray holds for us). Returns (base_url, token, url)."""
    core = _fsr_core()
    resp, pc = core.request_with_discovery("video", timeout=8)
    if resp.get("t") != "video":
        raise RuntimeError("PC のアプリが古いようです。PC の frame-steamvr-remote を新しくしてください")
    ip = pc.get("ip")
    return "http://%s:%d" % (ip, int(resp.get("port") or 47652)), resp.get("token", ""), resp.get("url")


def list_pc():
    base, token, url = pc_video()
    with urllib.request.urlopen("%s/list/%s" % (base, token), timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    items = []
    for f in data.get("files", []):
        p = f["path"]
        items.append(Item("pc", p, "pc:" + p, "%s/v/%s/%s" % (base, token, urllib.parse.quote(p))))
    log.info("PC video list: %d files", len(items))
    return items, url


def youtube_item(url):
    ytd = yt_dlp_path()
    if not ytd:
        raise RuntimeError("yt-dlp が入っていません")
    cmd = [ytd, "--no-playlist", "-f", "bv*[height<=1440][vcodec!*=av01]+ba/b", "--print", "%(title)s",
           "--print", "urls", url]
    log.info("yt-dlp: %s", url)
    r = subprocess.run(cmd, capture_output=True, timeout=90)
    err = r.stderr.decode(errors="replace")
    if err.strip():
        log.info("yt-dlp stderr: %s", err.strip())
    if r.returncode != 0:
        raise RuntimeError("YouTube の動画を開けません: " + (err.strip().splitlines() or ["?"])[-1][:120])
    lines = [x for x in r.stdout.decode(errors="replace").splitlines() if x.strip()]
    title, urls = lines[0], lines[1:]
    it = Item("youtube", title, "yt:" + url, urls[0], urls[1] if len(urls) > 1 else urls[0])
    it.page_url = url
    return it


# ---------------------------------------------------------------- playback

def frame_size(item, mode):
    if mode in ("360", "180"):
        return CUBE_FACE * 6, CUBE_FACE
    w, h = item.width or 1920, item.height or 1080
    if item.stereo == "sbs":
        w //= 2
    elif item.stereo == "tb":
        h //= 2
    s = min(FLAT_MAX[0] / float(w), FLAT_MAX[1] / float(h), 1.0)
    return max(2, int(w * s) // 2 * 2), max(2, int(h * s) // 2 * 2)


def _sub_filter(item, sub_on):
    if not sub_on or item.kind == "youtube":
        return None
    esc = lambda p: p.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")  # noqa
    if item.subs:
        return "subtitles='%s'" % esc(item.subs)
    if item.sub_streams and item.kind == "frame":
        return "subtitles='%s':si=0" % esc(item.video)
    return None


def video_filter(item, mode, sub_on):
    w, h = frame_size(item, mode)
    f = []
    if item.stereo == "sbs":
        f.append("crop=iw/2:ih:0:0")
    elif item.stereo == "tb":
        f.append("crop=iw:ih/2:0:0")
    if mode == "360":
        f.append("v360=input=e:output=c6x1:w=%d:h=%d" % (w, h))
    elif mode == "180":
        f.append("v360=input=hequirect:output=c6x1:w=%d:h=%d" % (w, h))
    else:
        sf = _sub_filter(item, sub_on)
        if sf:
            f.append(sf)
        f.append("scale=%d:%d:flags=bilinear" % (w, h))
    f.append("format=rgba")
    return ",".join(f), w, h


class Playback:
    """Two ffmpeg processes started at `start` seconds. Frames come from a reader thread."""

    def __init__(self, item, start, mode, volume, sub_on):
        self.item, self.start_pos, self.mode = item, max(0.0, start), mode
        vf, self.w, self.h = video_filter(item, mode, sub_on)
        self.frame_bytes = self.w * self.h * 4
        self.lock = threading.Lock()
        self.buf = bytearray(self.frame_bytes)
        self.ready = None   # bytearray of the newest whole frame
        self.frames = 0
        self.eof = False
        self.t0 = time.time()
        common = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning"]
        net = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"] \
            if item.video.startswith("http") else []
        vcmd = common + ["-threads", "0", "-ss", "%.3f" % self.start_pos, "-re"] + net + ["-i", item.video,
                                                                                         "-an", "-sn", "-vf", vf,
                                                                                         "-f", "rawvideo", "-"]
        log.info("video ffmpeg: %s", redact(" ".join(vcmd)))
        self.vproc = subprocess.Popen(vcmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        self.aproc = None
        if item.has_audio:
            anet = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"] \
                if item.audio.startswith("http") else []
            acmd = common + ["-ss", "%.3f" % self.start_pos, "-re"] + anet + ["-i", item.audio, "-vn", "-sn",
                                                                               "-af", "volume=%.2f" % volume,
                                                                               "-f", "pulse", "-name",
                                                                               "frame-video-player", "fvp"]
            log.info("audio ffmpeg: %s", redact(" ".join(acmd)))
            self.aproc = subprocess.Popen(acmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                          start_new_session=True)
        for name, p in (("video", self.vproc), ("audio", self.aproc)):
            if p:
                threading.Thread(target=self._stderr, args=(name, p), daemon=True).start()
        threading.Thread(target=self._read, daemon=True).start()

    def _stderr(self, name, p):
        for line in p.stderr:
            log.info("ffmpeg[%s]: %s", name, redact(line.decode(errors="replace").rstrip()))

    def _read(self):
        f = self.vproc.stdout
        while True:
            buf = bytearray(self.frame_bytes)
            mv = memoryview(buf)
            got = 0
            while got < self.frame_bytes:
                r = f.readinto(mv[got:])
                if not r:
                    break
                got += r
            if got < self.frame_bytes:
                break
            with self.lock:
                self.ready = buf
                self.frames += 1
        self.eof = True
        log.info("video stream ended after %d frames", self.frames)

    def take(self):
        with self.lock:
            b, self.ready = self.ready, None
        return b

    def position(self):
        return self.start_pos + (time.time() - self.t0)

    def stop(self):
        for p in (self.vproc, self.aproc):
            if p and p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except OSError:
                    pass
        for p in (self.vproc, self.aproc):
            if p:
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)


# ---------------------------------------------------------------- persistence

def _load(name, default):
    try:
        with open(os.path.join(STATE, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(name, data):
    os.makedirs(STATE, exist_ok=True)
    tmp = os.path.join(STATE, name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(STATE, name))


def load_resume():
    return _load("resume.json", {})


def save_resume(d):
    if len(d) > 500:
        for k in sorted(d, key=lambda k: d[k].get("at", 0))[:len(d) - 500]:
            d.pop(k)
    _save("resume.json", d)


def load_history():
    return _load("youtube-history.json", [])


def add_history(url, title):
    h = [x for x in load_history() if x.get("url") != url]
    h.insert(0, {"url": url, "title": title, "at": time.time()})
    _save("youtube-history.json", h[:100])


def load_settings():
    return _load("settings.json", {"volume": 1.0, "width": 3.0, "distance": 2.5, "subs": True, "flip": True})


def save_settings(s):
    _save("settings.json", s)
