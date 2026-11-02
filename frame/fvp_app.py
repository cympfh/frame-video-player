"""frame-video-player: a SteamVR dashboard panel 「動画プレイヤー」 plus the video screen / 360° cube overlays.

Runs as the systemd user unit frame-video-player.service, under its own executable name
(frame-video-player, a small program that embeds Python), so SteamVR does not lump it together with
other python3 OpenVR apps. Everything is drawn into OpenGL textures and handed to SteamVR with
SetOverlayTexture (SetOverlayRaw blanks the overlay on every call = flicker).
"""
import fcntl
import logging
import logging.handlers
import math
import os
import queue
import signal
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import fvp_cairo as cairo  # noqa: E402
import fvp_gl  # noqa: E402
import fvp_media as media  # noqa: E402
import fvp_openvr as vr  # noqa: E402

log = logging.getLogger("fvp")
KEY = "cympfh.frame-video-player"
NAME = "動画プレイヤー"
W, H = 1200, 800
PANEL_M = 1.6
LOGO = os.path.join(os.path.dirname(os.path.realpath(__file__)), "assets/logo.png")
TABS = (("frame", "Frame の動画"), ("pc", "PC の動画"), ("youtube", "YouTube"))
ROWS = 8
FACES = ("right", "left", "up", "down", "front", "back")  # ffmpeg v360 c6x1 default order "rludfb"
CUBE_R = 30.0


def setup_logging():
    os.makedirs(media.STATE, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(os.path.join(media.STATE, "frame-video-player.log"),
                                             maxBytes=20 * 1024 * 1024, backupCount=5, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    s = logging.StreamHandler()
    s.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(s)
    log.setLevel(logging.INFO)


def fmt_time(t):
    t = int(max(0, t))
    return "%d:%02d:%02d" % (t // 3600, t // 60 % 60, t % 60) if t >= 3600 else "%d:%02d" % (t // 60, t % 60)


# ------------------------------------------------------------------ geometry

def _norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _mat(x, y, z, t):
    return [x[0], y[0], z[0], t[0], x[1], y[1], z[1], t[1], x[2], y[2], z[2], t[2]]


def head_frame(pose):
    """(head position, forward, right) with forward flattened to the floor plane."""
    if pose is None:
        return [0.0, 1.6, 0.0], [0.0, 0.0, -1.0], [1.0, 0.0, 0.0]
    pos = [pose[3], pose[7], pose[11]]
    f = _norm([-pose[2], 0.0, -pose[10]])
    r = [-f[2], 0.0, f[0]]
    return pos, f, r


def screen_matrix(pose, distance):
    pos, f, r = head_frame(pose)
    t = [pos[i] + f[i] * distance for i in range(3)]
    return _mat(r, [0, 1, 0], [-f[0], -f[1], -f[2]], t)


def cube_matrices(pose):
    """One matrix per cube face (FACES order). Each face looks back at the head."""
    pos, f, r = head_frame(pose)
    u = [0.0, 1.0, 0.0]
    neg = lambda v: [-v[0], -v[1], -v[2]]  # noqa: E731
    faces = {
        "front": (r, u, neg(f), f),
        "back": (neg(r), u, f, neg(f)),
        "right": (neg(f), u, neg(r), r),
        "left": (f, u, r, neg(r)),
        "up": (r, neg(f), neg(u), u),
        "down": (r, f, u, neg(u)),
    }
    out = []
    for name in FACES:
        x, y, z, d = faces[name]
        out.append(_mat(x, y, z, [pos[i] + d[i] * CUBE_R for i in range(3)]))
    return out


# ------------------------------------------------------------------ panel drawing

class Panel:
    def __init__(self):
        self.tab = "frame"
        self.items = []
        self.scroll = 0
        self.status = ""
        self.hover = None
        self.buttons = []

    def draw(self, app):
        cv = cairo.Canvas(W, H)
        cv.rect_gradient(0, 0, W, H, "#1b2230", "#0f141c")
        self.buttons = []

        def btn(key, x, y, w, h, label, on=False, size=26, enabled=True):
            col = "#3b82f6" if on else ("#334155" if enabled else "#1f2937")
            if self.hover == key and enabled:
                col = "#60a5fa" if on else "#475569"
            cv.rrect(x, y, w, h, 12, col)
            cv.text(label, x + w / 2.0, y + h / 2.0 + size * 0.36, size, "#ffffff" if enabled else "#6b7280",
                    align="center", bold=on)
            if enabled:
                self.buttons.append((key, x, y, w, h))

        cv.text(NAME, 30, 52, 34, "#e2e8f0", bold=True)
        x = 330
        for k, label in TABS:
            btn("tab:" + k, x, 14, 230, 56, label, on=self.tab == k)
            x += 245
        # list
        top = 88
        if self.tab == "youtube":
            btn("yt:recv", 30, top, 400, 52, "PC から URL を受け取る", size=24)
            btn("reload", 445, top, 200, 52, "履歴を見る", size=24)
            top += 62
        else:
            btn("reload", 30, top, 220, 52, "一覧を読み直す", size=24)
            where = {"frame": "Frame の ~/Videos", "pc": "PC の「ビデオ」フォルダ"}[self.tab]
            cv.text(where, 270, top + 35, 22, "#94a3b8")
            top += 62
        rows = ROWS - (1 if self.tab == "youtube" else 1)
        rh = 46
        vis = self.items[self.scroll:self.scroll + rows]
        for i, it in enumerate(vis):
            y = top + i * (rh + 4)
            key = "item:%d" % (self.scroll + i)
            cur = app.item is not None and app.item.key == it.key
            col = "#1e3a5f" if cur else ("#273449" if self.hover == key else "#1a2332")
            cv.rrect(30, y, 1040, rh, 8, col)
            mark = ""
            pos = app.resume.get(it.key, {}).get("pos", 0)
            if pos > 10:
                mark = "続きから " + fmt_time(pos)
            label = it.title
            while cv.text_width(label, 22) > 1040 - 220 and len(label) > 4:
                label = label[:-2]
            if label != it.title:
                label = label[:-1] + "…"
            cv.text(label, 46, y + 31, 22, "#f1f5f9")
            cv.text(mark, 1056, y + 31, 18, "#93c5fd", align="right")
            self.buttons.append((key, 30, y, 1040, rh))
        if not self.items:
            cv.text("ここに動画が出ます", 46, top + 40, 22, "#64748b")
        btn("up", 1084, top, 86, 140, "▲", enabled=self.scroll > 0)
        btn("down", 1084, top + rows * (rh + 4) - 144, 86, 140, "▼", enabled=self.scroll + rows < len(self.items))
        # now playing
        y0 = 500
        it = app.item
        title = it.title if it else "再生していません"
        while cv.text_width(title, 24) > 1140 and len(title) > 4:
            title = title[:-2]
        cv.text(title, 30, y0 + 24, 24, "#e2e8f0", bold=True)
        pos, dur = app.position(), (it.duration if it else 0)
        cv.rrect(30, y0 + 40, 1000, 26, 13, "#334155")
        if dur > 0:
            cv.rrect(30, y0 + 40, max(26, 1000 * min(1.0, pos / dur)), 26, 13, "#3b82f6")
            self.buttons.append(("seekbar", 30, y0 + 34, 1000, 38))
        cv.text("%s / %s" % (fmt_time(pos), fmt_time(dur) if dur else "--:--"), 1170, y0 + 61, 22, "#cbd5e1",
                align="right")
        y1 = y0 + 86
        on = it is not None
        btn("seek:-30", 30, y1, 130, 64, "−30秒", enabled=on)
        btn("seek:-10", 170, y1, 130, 64, "−10秒", enabled=on)
        btn("pause", 310, y1, 220, 64, "再生" if app.paused else "一時停止", on=True, enabled=on)
        btn("seek:10", 540, y1, 130, 64, "+10秒", enabled=on)
        btn("seek:30", 680, y1, 130, 64, "+30秒", enabled=on)
        btn("next", 820, y1, 160, 64, "次の動画", enabled=on)
        btn("stop", 990, y1, 180, 64, "停止", enabled=on)
        y2 = y1 + 80
        cv.text("音量 %d%%" % round(app.settings["volume"] * 100), 30, y2 + 40, 22, "#cbd5e1")
        btn("vol:-", 160, y2, 64, 60, "−")
        btn("vol:+", 230, y2, 64, 60, "+")
        mode_label = {"flat": "表示: 平面", "360": "表示: 360°", "180": "表示: 180°"}[app.mode]
        btn("mode", 310, y2, 200, 60, mode_label, size=24, enabled=on)
        btn("subs", 520, y2, 150, 60, "字幕: 入" if app.settings["subs"] else "字幕: 切", size=24)
        cv.text("大きさ", 690, y2 + 40, 22, "#cbd5e1")
        btn("size:-", 760, y2, 56, 60, "−")
        btn("size:+", 820, y2, 56, 60, "+")
        cv.text("距離", 890, y2 + 40, 22, "#cbd5e1")
        btn("dist:-", 940, y2, 56, 60, "−")
        btn("dist:+", 1000, y2, 56, 60, "+")
        btn("recenter", 1066, y2, 104, 60, "正面へ", size=22)
        cv.text(app.status[:80], 30, H - 22, 22, "#fbbf24" if app.status_warn else "#94a3b8")
        return cv

    def hit(self, x, y):
        for key, bx, by, bw, bh in reversed(self.buttons):
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return key, (x - bx) / float(bw)
        return None, 0


# ------------------------------------------------------------------ app

class App:
    def __init__(self, ov, ctx):
        self.ov, self.ctx = ov, ctx
        self.settings = media.load_settings()
        self.resume = media.load_resume()
        self.panel = Panel()
        self.item = None
        self.playlist = []
        self.pb = None
        self.paused = False
        self.paused_pos = 0.0
        self.mode = "flat"
        self.status, self.status_warn = "", False
        self.jobs = queue.Queue()
        self.dirty = True
        self.pose = None
        self.vtex = None
        self.vsize = (0, 0)
        self.last_save = 0.0
        self.busy = False
        self.settings_override = {}
        self.main, self.thumb = ov.create_dashboard(KEY, NAME)
        ov.set_width(self.main, PANEL_M)
        ov.set_mouse(self.main, W, H)
        ov.set_flag(self.main, vr.FLAG_ENABLE_CLICK_STABILIZATION, True)
        if os.path.exists(LOGO):
            ov.set_from_file(self.thumb, LOGO)
        self.ptex = ctx.new_texture(W, H)
        self.screen = ov.create(KEY + ".screen", NAME + " 画面")
        self.faces = [ov.create(KEY + ".cube." + n, NAME + " 360 " + n) for n in FACES]
        for h in [self.screen] + self.faces:
            ov.hide(h)
        self.load_tab("frame")

    # ---- helpers
    def say(self, text, warn=False):
        self.status, self.status_warn = text, warn
        (log.warning if warn else log.info)("status: %s", text)
        self.dirty = True

    def bounds(self, h, u0=0.0, u1=1.0):
        if self.settings.get("flip", True):
            self.ov.set_bounds(h, u0, 1.0, u1, 0.0)
        else:
            self.ov.set_bounds(h, u0, 0.0, u1, 1.0)

    def run_job(self, fn, done):
        if self.busy:
            self.say("ほかの処理が終わるまで待ってください")
            return
        self.busy = True

        def work():
            try:
                r = fn()
                self.jobs.put((done, r, None))
            except Exception as e:
                log.warning("job failed: %s", media.redact(traceback.format_exc()))
                self.jobs.put((done, None, e))
        threading.Thread(target=work, daemon=True).start()

    def position(self):
        if self.pb is not None:
            return self.pb.position()
        return self.paused_pos

    # ---- lists
    def load_tab(self, tab):
        self.panel.tab, self.panel.scroll = tab, 0
        self.panel.items = []
        self.dirty = True
        if tab == "frame":
            self.panel.items = media.list_local()
            self.say("Frame の動画: %d 件" % len(self.panel.items))
        elif tab == "pc":
            self.say("PC の一覧を読んでいます…")

            def done(r, e):
                if e:
                    self.say("PC の一覧を読めません: %s" % media.redact(e), True)
                    return
                items, url = r
                if self.panel.tab == "pc":
                    self.panel.items = items
                self.say("PC の動画: %d 件" % len(items))
                if url:
                    self.open_youtube(url)
            self.run_job(media.list_pc, done)
        else:
            hist = media.load_history()
            self.panel.items = [media.Item("ythist", h.get("title") or h["url"], "yt:" + h["url"], h["url"])
                                for h in hist]
            self.say("YouTube の履歴: %d 件" % len(hist) if hist else
                     "PC で動画の URL をコピーして、トレイの「コピーした動画の URL を Frame で再生する」を選んでください")

    def receive_url(self):
        self.say("PC に URL を聞いています…")

        def done(r, e):
            if e:
                self.say("PC につながりません: %s" % media.redact(e), True)
                return
            url = r[2]
            if not url:
                self.say("PC に URL がありません。トレイの「コピーした動画の URL を Frame で再生する」を先に選んでください", True)
                return
            self.open_youtube(url)
        self.run_job(media.pc_video, done)

    def open_youtube(self, url):
        self.say("YouTube の動画を開いています…")

        def fn():
            it = media.youtube_item(url)
            it.probe()
            return it

        def done(it, e):
            if e:
                self.say(str(e), True)
                return
            media.add_history(url, it.title)
            self.playlist = [it]
            self.start(it)
        self.busy = False
        self.run_job(fn, done)

    def open_index(self, i):
        it = self.panel.items[i]
        if it.kind == "ythist":
            self.open_youtube(it.video)
            return
        self.say("開いています: %s" % it.title)

        def done(r, e):
            if e:
                self.say("開けません: %s" % media.redact(e), True)
                return
            self.playlist = [x for x in self.panel.items if x.kind == it.kind]
            self.start(it)
        self.run_job(it.probe, done)

    # ---- playback
    def start(self, it, pos=None):
        self.stop_playback(save=True)
        self.item = it
        self.mode = it.projection
        if pos is None:
            r = self.resume.get(it.key, {}).get("pos", 0)
            pos = r if (r > 10 and (not it.duration or r < it.duration - 10)) else 0
        self.paused = False
        self.play_at(pos)
        self.place()
        self.say("再生中: %s%s" % (it.title, ("(%s から)" % fmt_time(pos)) if pos else ""))

    def play_at(self, pos):
        if self.pb:
            self.pb.stop()
        if self.item.duration:
            pos = min(pos, max(0.0, self.item.duration - 1))
        vol = self.settings_override.get("volume", self.settings["volume"])
        self.pb = media.Playback(self.item, pos, self.mode, vol, self.settings["subs"])
        if (self.pb.w, self.pb.h) != self.vsize:
            self.vtex = self.ctx.new_texture(self.pb.w, self.pb.h)
            self.vsize = (self.pb.w, self.pb.h)
        self.dirty = True

    def stop_playback(self, save=True):
        if self.item is not None and save:
            self.remember(self.position())
        if self.pb:
            self.pb.stop()
            self.pb = None

    def remember(self, pos):
        it = self.item
        if it is None or self.settings_override.get("hidden"):
            return  # test runs do not touch the resume positions
        if it.duration and pos > it.duration - 15:
            self.resume.pop(it.key, None)
        else:
            self.resume[it.key] = {"pos": round(pos, 1), "at": time.time()}
        media.save_resume(self.resume)

    def place(self):
        """Put the screen (or the 360 cube) in front of where the head looks now."""
        self.pose = self.ov.hmd_pose()
        ov = self.ov
        if self.item is None or self.settings_override.get("hidden"):
            for h in [self.screen] + self.faces:
                ov.hide(h)
            return
        if self.mode == "flat":
            for h in self.faces:
                ov.hide(h)
            ov.set_width(self.screen, self.settings["width"])
            ov.set_transform_abs(self.screen, screen_matrix(self.pose, self.settings["distance"]))
            self.bounds(self.screen)
            ov.show(self.screen)
        else:
            ov.hide(self.screen)
            for i, (h, m) in enumerate(zip(self.faces, cube_matrices(self.pose))):
                if self.mode == "180" and FACES[i] == "back":
                    ov.hide(h)
                    continue
                ov.set_width(h, CUBE_R * 2)
                ov.set_transform_abs(h, m)
                self.bounds(h, i / 6.0, (i + 1) / 6.0)
                ov.show(h)
        log.info("placed: mode=%s pose=%s", self.mode, "ok" if self.pose else "none (default)")

    def visible_video_overlays(self):
        if self.item is None:
            return []
        if self.mode == "flat":
            return [self.screen]
        return [h for i, h in enumerate(self.faces) if not (self.mode == "180" and FACES[i] == "back")]

    def toggle_pause(self):
        if self.item is None:
            return
        if self.paused:
            self.paused = False
            self.play_at(self.paused_pos)
            self.say("再生")
        else:
            self.paused_pos = self.position()
            self.stop_playback(save=True)
            self.paused = True
            self.say("一時停止 %s" % fmt_time(self.paused_pos))

    def seek(self, pos):
        if self.item is None:
            return
        pos = max(0.0, pos)
        if self.paused:
            self.paused_pos = pos
            self.dirty = True
        else:
            self.play_at(pos)

    def next_item(self):
        if self.item is None or not self.playlist:
            return
        keys = [x.key for x in self.playlist]
        i = keys.index(self.item.key) + 1 if self.item.key in keys else len(keys)
        if i >= len(self.playlist):
            self.say("プレイリストの最後です")
            self.stop_all()
            return
        nxt = self.playlist[i]

        def done(r, e):
            if e:
                self.say("開けません: %s" % media.redact(e), True)
                return
            self.start(nxt, pos=0)
        self.busy = False
        self.run_job(nxt.probe, done)

    def stop_all(self):
        self.stop_playback(save=True)
        self.item = None
        self.paused = False
        self.place()
        self.dirty = True

    def restart_same(self):
        if self.item is not None and not self.paused:
            self.play_at(self.position())

    # ---- input
    def click(self, key, frac):
        s = self.settings
        if key.startswith("tab:"):
            self.load_tab(key[4:])
        elif key == "reload":
            self.load_tab(self.panel.tab)
        elif key == "yt:recv":
            self.receive_url()
        elif key.startswith("item:"):
            self.open_index(int(key[5:]))
        elif key == "up":
            self.panel.scroll = max(0, self.panel.scroll - (ROWS - 2))
        elif key == "down":
            self.panel.scroll = min(max(0, len(self.panel.items) - 1), self.panel.scroll + (ROWS - 2))
        elif key == "seekbar" and self.item and self.item.duration:
            self.seek(frac * self.item.duration)
        elif key.startswith("seek:"):
            self.seek(self.position() + int(key[5:]))
        elif key == "pause":
            self.toggle_pause()
        elif key == "next":
            self.next_item()
        elif key == "stop":
            self.stop_all()
            self.say("停止しました")
        elif key in ("vol:-", "vol:+"):
            s["volume"] = round(min(2.0, max(0.0, s["volume"] + (0.1 if key == "vol:+" else -0.1))), 2)
            self.restart_same()
        elif key == "mode" and self.item:
            self.mode = {"flat": "360", "360": "180", "180": "flat"}[self.mode]
            self.restart_same()
            self.place()
        elif key == "subs":
            s["subs"] = not s["subs"]
            if self.mode == "flat":
                self.restart_same()
        elif key in ("size:-", "size:+"):
            s["width"] = round(min(12.0, max(0.5, s["width"] * (1.2 if key == "size:+" else 1 / 1.2))), 2)
            self.place()
        elif key in ("dist:-", "dist:+"):
            s["distance"] = round(min(15.0, max(0.6, s["distance"] + (0.5 if key == "dist:+" else -0.5))), 2)
            self.place()
        elif key == "recenter":
            self.place()
        media.save_settings(s)
        self.dirty = True

    # ---- loop pieces
    def pump_jobs(self):
        while True:
            try:
                done, r, e = self.jobs.get_nowait()
            except queue.Empty:
                return
            self.busy = False
            done(r, e)
            self.dirty = True

    def pump_video(self):
        pb = self.pb
        if pb is None:
            return
        buf = pb.take()
        if buf is not None:
            self.ctx.upload(self.vtex, pb.w, pb.h, buf)
            for h in self.visible_video_overlays():
                e = self.ov.set_gl_texture(h, self.vtex)
                if e:
                    log.warning("SetOverlayTexture: %s", self.ov.err_name(e))
        elif pb.eof and pb.ready is None and pb.vproc.poll() is not None:
            ended = self.item.duration and pb.position() > self.item.duration - 5
            if pb.frames == 0 or not ended:
                rc = pb.vproc.returncode
                log.warning("video stopped early (exit %s, %d frames)", rc, pb.frames)
                self.say("再生が止まりました(ログを見てください)", True)
                self.paused_pos = pb.position()
                self.stop_playback(save=True)
                self.paused = True
            else:
                self.remember(self.item.duration)
                self.next_item()
        now = time.time()
        if self.pb is not None and now - self.last_save > 5:
            self.last_save = now
            self.remember(self.pb.position())

    def draw_panel(self):
        cv = self.panel.draw(self)
        data = cv.rgba_bytes()
        cv.close()
        self.ctx.upload(self.ptex, W, H, data)
        self.bounds(self.main)
        e = self.ov.set_gl_texture(self.main, self.ptex)
        if e:
            log.warning("panel SetOverlayTexture: %s", self.ov.err_name(e))
        self.dirty = False

    def close(self):
        self.stop_playback(save=True)
        for h in [self.screen] + self.faces + [self.main]:
            try:
                self.ov.destroy(h)
            except Exception:
                pass


class Control:
    """A local command socket (for the CLI and for tests): play <path|url> / test <path|url> <seconds> / stop / pause."""

    def __init__(self):
        import socket
        self.path = os.path.join(media.STATE, "control.sock")
        if os.path.exists(self.path):
            os.unlink(self.path)
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.s.bind(self.path)
        os.chmod(self.path, 0o600)
        self.s.setblocking(False)

    def poll(self):
        out = []
        while True:
            try:
                out.append(self.s.recv(4096).decode("utf-8", "replace").strip())
            except BlockingIOError:
                return out


def handle_command(app, line, test):
    log.info("command: %s", media.redact(line))
    parts = line.split(" ")
    cmd, args = parts[0], parts[1:]
    if cmd in ("play", "test") and args:
        src = args[0]
        if cmd == "test":
            test.update(until=time.time() + float(args[1] if len(args) > 1 else 15), frames=0, t0=time.time())
            app.settings_override = {"volume": 0.0, "hidden": True}
        else:
            app.settings_override = {}
        if src.startswith("http") and "/v/" not in src:
            app.busy = False
            app.open_youtube(src)
        elif src.startswith("pc:"):
            rel = src[3:]

            def fn():
                items, _url = media.list_pc()
                it = next(x for x in items if x.title == rel)
                it.probe()
                return it

            def done(it, e):
                if e:
                    app.say("PC の動画を開けません: %s" % media.redact(e), True)
                    return
                app.playlist = [it]
                app.start(it)
            app.busy = False
            app.run_job(fn, done)
        else:
            it = media.Item("frame", os.path.basename(src), "cli:" + src, src)
            app.busy = False

            def done(r, e):
                if e:
                    app.say("開けません: %s" % e, True)
                    return
                app.playlist = [it]
                app.start(it)
            app.run_job(it.probe, done)
    elif cmd == "mode" and args and app.item:
        app.mode = args[0]
        app.restart_same()
        app.place()
    elif cmd == "stop":
        app.stop_all()
    elif cmd == "pause":
        app.toggle_pause()


def _lock():
    os.makedirs(media.STATE, exist_ok=True)
    fd = os.open(os.path.join(media.STATE, "lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return fd


def main():
    setup_logging()
    log.info("start pid=%d exe=%s", os.getpid(), sys.executable)
    if _lock() is None:
        log.info("already running")
        return 3
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(flag=True))
    ctx = fvp_gl.Context()
    log.info("GL: %s", ctx.info())
    ov = vr.Overlay()
    for i in range(60):
        try:
            ov.init()
            break
        except vr.OpenVRError as e:
            if stop["flag"]:
                return 0
            log.info("waiting for SteamVR: %s", e)
            time.sleep(5)
    else:
        return 1
    log.info("OpenVR: %s", ov.version)
    app = App(ov, ctx)
    ctl = Control()
    test = {"until": 0}
    code = 0
    last_tick = 0.0
    try:
        while not stop["flag"]:
            for ev in ov.poll(app.main):
                t = ev.eventType
                if t == vr.EV_QUIT:
                    # only 700 (Quit) is for us; 701 (ProcessQuit) is sent when *any* OpenVR process exits
                    log.info("quit event from SteamVR")
                    stop["flag"] = True
                elif t in (vr.EV_MOUSE_MOVE, vr.EV_MOUSE_DOWN, vr.EV_MOUSE_UP):
                    x, y = ev.x, H - ev.y
                    key, frac = app.panel.hit(x, y)
                    if t == vr.EV_MOUSE_MOVE:
                        if key != app.panel.hover:
                            app.panel.hover = key
                            app.dirty = True
                    elif t == vr.EV_MOUSE_UP and ev.button == 1 and key:
                        log.info("click %s", key)
                        try:
                            app.click(key, frac)
                        except Exception:
                            log.exception("click failed")
                            app.say("エラーが起きました(ログを見てください)", True)
                elif t == vr.EV_FOCUS_LEAVE:
                    if app.panel.hover:
                        app.panel.hover = None
                        app.dirty = True
            for line in ctl.poll():
                try:
                    handle_command(app, line, test)
                except Exception:
                    log.exception("command failed")
            app.pump_jobs()
            app.pump_video()
            if test["until"]:
                if app.pb:
                    test["frames"] = app.pb.frames
                if time.time() > test["until"]:
                    el = time.time() - test["t0"]
                    log.info("test result: %d frames in %.1fs (%.1f fps incl. startup) size=%s mode=%s",
                             test["frames"], el, test["frames"] / el, app.vsize, app.mode)
                    test["until"] = 0
                    app.stop_all()
                    app.settings_override = {}
            now = time.time()
            if now - last_tick > 1.0:
                last_tick = now
                if app.item is not None and ov.dashboard_visible():
                    app.dirty = True  # time display
            if app.dirty:
                app.draw_panel()
            time.sleep(0.005 if app.pb else 0.03)
    except Exception:
        log.exception("unexpected error")
        code = 1
    finally:
        app.close()
        ov.shutdown()
        log.info("stopped")
    return code


def send(args):
    """frame-video-player play <file|url> / stop / pause : tell the running panel (no OpenVR here)."""
    import socket
    if args and args[0] == "play" and len(args) > 1 and not args[1].startswith("http"):
        args[1] = os.path.abspath(args[1])
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        s.sendto(" ".join(args).encode(), os.path.join(media.STATE, "control.sock"))
    except OSError:
        print("動画プレイヤーが動いていません(SteamVR を起動すると動きます)")
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(send(sys.argv[1:]))
    sys.exit(main())
