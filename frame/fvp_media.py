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
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("fvp")

HOME = os.path.expanduser("~")
OPT = os.path.join(HOME, ".local/opt/frame-video-player")
STATE = os.path.join(HOME, ".local/state/frame-video-player")
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".ts", ".m2ts", ".wmv", ".flv", ".mpg", ".mpeg")
SUB_EXTS = (".srt", ".ass", ".vtt")

FLAT_MAX = (1920, 1080)
AUDIO_BUFFER_MS = 100  # pulse buffer: small, so pause and volume feel immediate
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
    # "180" / "360" only as a word of its own (not "ep180", "x360", "1360")
    if re.search(r"(^|[^0-9a-z])(vr)?180(°|x180)?([^0-9a-z]|$)", n):
        return "180"
    if re.search(r"(^|[^0-9a-z])360(°|vr)?([^0-9a-z]|$)|equirect", n):
        return "360"
    return "flat"


def detect_stereo(name, info, w, h, projection="flat"):
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
    if re.search(r"(^|[^a-z0-9])(h?sbs|3dh)([^a-z0-9]|$)", n):
        return "sbs"
    if re.search(r"(^|[^a-z0-9])(h?ou|3dv)([^a-z0-9]|$)", n):
        return "tb"
    # Short tags like "LR" / "TB" are too common in ordinary names; trust them only on VR videos
    # (e.g. "_180_LR"). The panel has a manual 3D button for everything else.
    if projection != "flat":
        if re.search(r"(^|[^a-z0-9])lr([^a-z0-9]|$)", n):
            return "sbs"
        if re.search(r"(^|[^a-z0-9])tb([^a-z0-9]|$)", n):
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
        self.codec = ""
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
            self.codec = vs[0].get("codec_name") or ""
        self.sub_streams = len([s for s in self.info.get("streams", []) if s.get("codec_type") == "subtitle"])
        if self.audio == self.video:
            self.has_audio = any(s.get("codec_type") == "audio" for s in self.info.get("streams", []))
        self.projection = detect_projection(self.title, self.info)
        self.stereo = detect_stereo(self.title, self.info, self.width, self.height, self.projection)
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
        items.append(Item("pc", p, "pc:" + p, pc_url(base, token, p)))
    log.info("PC video list: %d files", len(items))
    return items, url


# ---------------------------------------------------------------- PC folders (any drive)

_pc = {"base": None, "token": None}


def _pc_get(kind, path=None, retry=True):
    """GET /<kind>/<token>[/<path>] from the tray as JSON. Gets a token first, and a new one on 403."""
    if not _pc["token"]:
        _pc["base"], _pc["token"], _url = pc_video()
        if _url:
            _pc["url"] = _url
    url = "%s/%s/%s" % (_pc["base"], kind, _pc["token"])
    if path is not None:
        url += "/" + urllib.parse.quote(path, safe="")
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403 and retry:
            _pc["token"] = None
            return _pc_get(kind, path, False)
        raise


def pc_file_url(base, token, path):
    return "%s/f/%s/%s" % (base, token, urllib.parse.quote(path, safe=""))


def folder_name(path):
    p = path.rstrip("/")
    return p.rsplit("/", 1)[-1] if "/" in p else (p + "/" if p.endswith(":") else p or "/")


def dir_item(title, path):
    it = Item("pcdir", title, "dir:" + path, None)
    it.path = path
    return it


def list_pc_dir(path):
    """Contents of a PC folder ('' = top: the Videos folder and the drives). Returns (items, url, path).

    Falls back to the old flat Videos list when the tray is too old for folders."""
    try:
        if not path:
            d = _pc_get("drives")
            items = []
            if d.get("videos"):
                items.append(dir_item("[ビデオ]  " + d["videos"], d["videos"]))
            items += [dir_item("[ドライブ]  " + x, x) for x in d.get("drives", [])]
        else:
            d = _pc_get("dir", path)
            path = d.get("path") or path
            items = [dir_item("↑ 上のフォルダへ", d.get("parent") or "")]
            items += [dir_item("[フォルダ]  " + n, path.rstrip("/") + "/" + n) for n in d.get("dirs", [])]
            for f in d.get("files", []):
                full = path.rstrip("/") + "/" + f["name"]
                it = Item("pc", f["name"], "pc:" + full, pc_file_url(_pc["base"], _pc["token"], full))
                it.path = full
                items.append(it)
    except urllib.error.HTTPError as e:
        if e.code != 404 or path:
            raise
        items, url = list_pc()
        return items, url, ""
    log.info("PC folder %r: %d entries", path, len(items))
    return items, _pc.pop("url", None), path


def load_pc_folders():
    return _load("pc-folders.json", [])


def add_pc_folder(path, keep=10):
    """Remember a PC folder for the quick-jump buttons: most recent first, at most `keep`."""
    h = [path] + [p for p in load_pc_folders() if p != path]
    _save("pc-folders.json", h[:keep])
    return h[:keep]


def pc_url(base, token, rel):
    return "%s/v/%s/%s" % (base, token, urllib.parse.quote(rel))


def youtube_item(url):
    ytd = yt_dlp_path()
    if not ytd:
        raise RuntimeError("yt-dlp が入っていません")
    cmd = [ytd, "--no-playlist", "-f", "bv*[height<=1440][vcodec!*=av01]+ba/b", "--print", "%(title)s",
           "--print", "urls", "--", url]
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
    if item.subs:
        return "subtitles=filename=%s" % filter_path(item.subs)
    if item.sub_streams and item.kind == "frame":
        return "subtitles=filename=%s:si=0" % filter_path(item.video)
    return None


def filter_path(p):
    """Escape a path for use as a filter option value inside a -vf filtergraph.

    ffmpeg unescapes twice: first the filtergraph (\\ ' [ ] , ; are special), then the option
    value (\\ ' : are special). See "Notes on filtergraph escaping" in ffmpeg-filters.
    """
    lvl1 = re.sub(r"([\\':])", r"\\\1", p)
    return re.sub(r"([\\'\[\],;])", r"\\\1", lvl1)


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


def stream_fps(info):
    """Frame rate of the first video stream (avg, then r_frame_rate), clamped to 10..60; 30 if unknown."""
    for st in (info or {}).get("streams", []):
        if st.get("codec_type") != "video":
            continue
        for k in ("avg_frame_rate", "r_frame_rate"):
            try:
                a, b = (st.get(k) or "0/0").split("/")
                if float(b) > 0 and float(a) > 0:
                    return min(60.0, max(10.0, float(a) / float(b)))
            except ValueError:
                pass
    return 30.0


# The Frame decodes video in software (no AV1/HEVC hardware path in ffmpeg there). Measured on the Frame:
# 8K (7680x3840) AV1 decodes at about 16-20 fps, with the 360 cube filter about 14 fps, so it can not keep
# up with 30 fps and a seek needs several seconds (keyframes every ~6 s) before the first picture.
HEAVY_PIXELS = 3840 * 2160 * 1.2


def playable(item):
    """False when ffprobe found no picture at all (broken or truncated file): don't start ffmpeg on it."""
    return item.width > 0 and item.height > 0


def too_heavy(item):
    """True when the Frame can not decode this video in real time (8K and up)."""
    return item.width * item.height > HEAVY_PIXELS


class Clock:
    """Wall clock that can be paused. now() = seconds played since start."""

    def __init__(self, t=time.monotonic):
        self.t = t
        self.t0 = t()
        self.paused_at = None
        self.paused_total = 0.0

    def now(self):
        end = self.paused_at if self.paused_at is not None else self.t()
        return end - self.t0 - self.paused_total

    def pause(self):
        if self.paused_at is None:
            self.paused_at = self.t()

    def resume(self):
        if self.paused_at is not None:
            self.paused_total += self.t() - self.paused_at
            self.paused_at = None

    def restart(self):
        """Back to 0, keeping the paused state."""
        now = self.t()
        self.t0, self.paused_total = now, 0.0
        if self.paused_at is not None:
            self.paused_at = now


class Playback:
    """Two ffmpeg processes started at `start` seconds.

    Video: ffmpeg writes constant-rate RGBA frames to a pipe as fast as it can; the reader thread paces
    them against a pausable Clock, so ffmpeg is held back by the full pipe (no -re, no catch-up burst
    after a pause). Audio: ffmpeg plays to pulse with a small buffer; pulse paces it. Pause = the reader
    waits + SIGSTOP on the audio ffmpeg; resume = SIGCONT. Nothing is restarted, so it is immediate.
    """

    def __init__(self, item, start, mode, volume, sub_on):
        self.item, self.start_pos, self.mode = item, max(0.0, start), mode
        vf, self.w, self.h = video_filter(item, mode, sub_on)
        self.fps = stream_fps(item.info)
        self.frame_bytes = self.w * self.h * 4
        self.lock = threading.Lock()
        self.ready = None   # bytearray of the newest whole frame
        self.frames = 0
        self.eof = False
        self.stopped = False
        self.clock = Clock()
        self.running = threading.Event()
        self.running.set()
        common = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning"]
        net = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"] \
            if item.video.startswith("http") else []
        vcmd = common + ["-threads", "0", "-ss", "%.3f" % self.start_pos] + net + [
            "-i", item.video, "-an", "-sn", "-vf", vf, "-r", "%.3f" % self.fps, "-f", "rawvideo", "-"]
        log.info("video ffmpeg: %s", redact(" ".join(vcmd)))
        self.vproc = subprocess.Popen(vcmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        self.aproc = None
        self.acmd = None
        self.started = False  # becomes True with the first video frame; audio starts only then
        if item.has_audio:
            anet = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"] \
                if item.audio.startswith("http") else []
            acmd = common + ["-ss", "%.3f" % self.start_pos] + anet + [
                "-i", item.audio, "-vn", "-sn", "-af", "volume=%.2f" % volume,
                "-f", "pulse", "-buffer_duration", str(AUDIO_BUFFER_MS), "-name", "frame-video-player", "fvp"]
            self.acmd = acmd
        threading.Thread(target=self._stderr, args=("video", self.vproc), daemon=True).start()
        self.t_open = time.monotonic()
        threading.Thread(target=self._read, daemon=True).start()

    def _first_frame(self):
        """Start the clock and the audio together with the first picture, so a slow video start (a heavy
        file, a far keyframe) never leaves the sound playing alone ahead of a black screen."""
        with self.lock:
            if self.stopped:
                return
            self.clock.restart()
            self.started = True
            log.info("first video frame after %.1f s", time.monotonic() - self.t_open)
            if self.acmd:
                log.info("audio ffmpeg: %s", redact(" ".join(self.acmd)))
                self.aproc = subprocess.Popen(self.acmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                              start_new_session=True)
                threading.Thread(target=self._stderr, args=("audio", self.aproc), daemon=True).start()
                if not self.running.is_set():
                    self._signal(signal.SIGSTOP)

    def _stderr(self, name, p):
        for line in p.stderr:
            log.info("ffmpeg[%s]: %s", name, redact(line.decode(errors="replace").rstrip()))

    def _read(self):
        f = self.vproc.stdout
        n = 0
        while not self.stopped:
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
            if n == 0:
                self._first_frame()
            # wait for this frame's time (and while paused)
            while not self.stopped:
                self.running.wait(0.2)
                if not self.running.is_set():
                    continue
                late = self.clock.now() - n / self.fps
                if late >= 0:
                    break
                time.sleep(min(-late, 0.05))
            n += 1
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
        if not self.started:
            return self.start_pos
        return self.start_pos + self.clock.now()

    def _signal(self, sig):
        if self.aproc and self.aproc.poll() is None:
            try:
                os.killpg(self.aproc.pid, sig)
            except OSError:
                pass

    def pause(self):
        self.running.clear()
        self.clock.pause()
        self._signal(signal.SIGSTOP)

    def resume(self):
        self._signal(signal.SIGCONT)
        self.clock.resume()
        self.running.set()

    def stop(self):
        """Kill both ffmpeg at once and reap them in the background (never blocks the UI)."""
        with self.lock:
            self.stopped = True
        self.running.set()
        procs = [p for p in (self.vproc, self.aproc) if p]
        for p in procs:
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGCONT)
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass

        def reap():
            for p in procs:
                try:
                    p.wait(timeout=5)
                except Exception:
                    pass
        threading.Thread(target=reap, daemon=True).start()


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


# Shown under the YouTube history so there is always something to try (checked with yt-dlp: 3840x1920 = 2:1
# equirectangular, tagged "360 video").
YOUTUBE_EXAMPLES = [
    ("例: Lions 360° | National Geographic", "https://www.youtube.com/watch?v=sPyAQQklc1s"),
]


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
