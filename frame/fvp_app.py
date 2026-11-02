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
import fvp_openvr as vr
from fvp_controls import (TURN_STEP, resolve_tap, scroll_clamp, scroll_from_smooth,
                          wrap_deg)  # noqa: E402

log = logging.getLogger("fvp")
KEY = "cympfh.frame-video-player"
HERE = os.path.dirname(os.path.realpath(__file__))
OSD_W, OSD_H = 600, 100
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


def turn(f, r, yaw_deg):
    """Turn the floor-plane frame (forward, right) so that the content on the right comes to the front
    for positive yaw (what the user expects from ▶)."""
    a = math.radians(yaw_deg)
    c, s = math.cos(a), math.sin(a)
    f2 = [c * f[i] - s * r[i] for i in range(3)]
    r2 = [c * r[i] + s * f[i] for i in range(3)]
    return f2, r2


def cube_matrices(pose, yaw=0.0):
    """One matrix per cube face (FACES order). Each face looks back at the head. yaw turns the cube."""
    pos, f, r = head_frame(pose)
    f, r = turn(f, r, yaw)
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
        self.pc_dir = ""        # PC folder shown in the PC tab ('' = drives)
        self.pc_recent = []     # recent PC folders, newest first
        self.items = []
        self.scroll = 0.0  # in rows; fractional with smooth laser scrolling
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
        elif self.tab == "pc":
            btn("pc:top", 30, top, 200, 48, "ドライブ一覧", size=24)
            btn("pc:recent", 245, top, 200, 48, "最近のフォルダ", size=24)
            where = self.pc_dir or "ドライブとビデオフォルダ"
            while cv.text_width(where, 22) > 450 and len(where) > 4:
                where = "…" + where[2:]
            cv.text(where, 460, top + 32, 22, "#94a3b8")
            top += 56
            x = 30
            for i, p in enumerate(self.pc_recent[:4]):
                label = media.folder_name(p)
                while cv.text_width(label, 22) > 230 and len(label) > 3:
                    label = label[:-2] + "…"
                btn("pcrecent:%d" % i, x, top, 250, 48, label, on=p == self.pc_dir, size=22)
                x += 260
            top += 56
        else:
            btn("reload", 30, top, 220, 52, "一覧を読み直す", size=24)
            cv.text("Frame の ~/Videos", 270, top + 35, 22, "#94a3b8")
            top += 62
        rows = self.rows()
        rh = 46
        self.scroll = scroll_clamp(self.scroll, len(self.items), rows)
        first = int(self.scroll)
        off = (self.scroll - first) * (rh + 4)
        cv.save()
        cv.clip(30, top, 1040, rows * (rh + 4) - 4)
        for i, it in enumerate(self.items[first:first + rows + 1]):
            y = top + i * (rh + 4) - off
            key = "item:%d" % (first + i)
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
            y0c, y1c = max(y, top), min(y + rh, top + rows * (rh + 4) - 4)
            if y1c > y0c:
                self.buttons.append((key, 30, y0c, 1040, y1c - y0c))
        cv.restore()
        if not self.items:
            cv.text("ここに動画が出ます", 46, top + 40, 22, "#64748b")
        btn("up", 1084, top, 86, 140, "▲", enabled=self.scroll > 0)
        btn("down", 1084, top + rows * (rh + 4) - 144, 86, 140, "▼", enabled=self.scroll + rows < len(self.items))
        if len(self.items) > rows:  # scroll position bar
            span = rows * (rh + 4) - 4 - 2 * 144 - 16
            frac = self.scroll / float(len(self.items) - rows)
            cv.rrect(1121, top + 152 + frac * max(0, span - 20), 6, 20, 3, "#64748b")
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
        btn("seek:-30", 30, y1, 115, 64, "−30秒", enabled=on)
        btn("seek:-10", 155, y1, 115, 64, "−10秒", enabled=on)
        btn("pause", 280, y1, 190, 64, "再生" if app.paused else "一時停止", on=True, enabled=on)
        btn("seek:10", 480, y1, 115, 64, "+10秒", enabled=on)
        btn("seek:30", 605, y1, 115, 64, "+30秒", enabled=on)
        btn("next", 730, y1, 140, 64, "次の動画", enabled=on)
        btn("stop", 880, y1, 120, 64, "停止", enabled=on)
        st = it.stereo if it else "mono"
        btn("stereo", 1010, y1, 160, 64, {"mono": "3D: なし", "sbs": "3D: 左右", "tb": "3D: 上下"}[st],
            size=24, enabled=on)
        y2 = y1 + 80
        cv.text("音量 %d%%" % round(app.settings["volume"] * 100), 30, y2 + 40, 22, "#cbd5e1")
        btn("vol:-", 160, y2, 64, 60, "−")
        btn("vol:+", 230, y2, 64, 60, "+")
        mode_label = {"flat": "表示: 平面", "360": "表示: 360°", "180": "表示: 180°"}[app.mode]
        btn("mode", 304, y2, 166, 60, mode_label, size=22, enabled=on)
        btn("subs", 478, y2, 112, 60, "字幕: 入" if app.settings["subs"] else "字幕: 切", size=22)
        cv.text("大きさ", 598, y2 + 40, 22, "#cbd5e1")
        btn("size:-", 666, y2, 52, 60, "−")
        btn("size:+", 724, y2, 52, 60, "+")
        cv.text("距離", 786, y2 + 40, 22, "#cbd5e1")
        btn("dist:-", 834, y2, 52, 60, "−")
        btn("dist:+", 892, y2, 52, 60, "+")
        turnable = on and app.mode != "flat"  # 360 / 180: turn the view with the laser
        btn("turn:-", 954, y2, 56, 60, "◀", enabled=turnable)
        btn("recenter", 1016, y2, 94, 60, "正面へ", size=22)
        btn("turn:+", 1116, y2, 54, 60, "▶", enabled=turnable)
        cv.text(app.status[:80], 30, H - 22, 22, "#fbbf24" if app.status_warn else "#94a3b8")
        return cv

    def rows(self):
        return ROWS - 2 if self.tab == "pc" else ROWS - 1

    def scroll_by(self, rows):
        old = self.scroll
        self.scroll = scroll_clamp(self.scroll + rows, len(self.items), self.rows())
        return self.scroll != old

    def hit(self, x, y):
        for key, bx, by, bw, bh in reversed(self.buttons):
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return key, (x - bx) / float(bw)
        return None, 0


def panel_xy(x, y, flip=True):
    """OpenVR mouse coordinates (units of SetOverlayMouseScale = W x H) -> panel image coordinates (top-left origin).

    OpenVR reports the mouse in texture-bounds space with v growing from vMin to vMax. Our GL texture
    holds the image top row first, and with flip on we set bounds vMin=1, vMax=0 so the image shows
    upright; the same flip turns OpenVR's bottom-up y into top-down, so y is used as is. Without flip
    (raw bounds 0..1) the y has to be turned over, as frame-steamvr-remote does for SetOverlayRaw.
    """
    return x, (y if flip else H - y)


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
        self.held_url = None
        self.yaw = 0.0
        self.osd_until = 0.0
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
        self.osd = ov.create(KEY + ".osd", NAME + " OSD")
        ov.set_width(self.osd, 0.36)
        ov._f["SetOverlaySortOrder"](self.osd, 10)  # above the video
        self.otex = ctx.new_texture(OSD_W, OSD_H)
        for h in [self.screen] + self.faces + [self.osd]:
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
            # tell the caller (its done() resets whatever "…しています" text it showed)
            self.jobs.put((done, None, RuntimeError("ほかの処理が終わるまで待ってください")))
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
            self.panel.pc_recent = media.load_pc_folders()
            self.open_pc_dir(self.panel.pc_dir)
        else:
            hist = media.load_history()
            self.panel.items = [media.Item("ythist", h.get("title") or h["url"], "yt:" + h["url"], h["url"])
                                for h in hist]
            seen = {h["url"] for h in hist}
            self.panel.items += [media.Item("ythist", t, "yt:" + u, u) for t, u in media.YOUTUBE_EXAMPLES
                                 if u not in seen]
            self.say("YouTube の履歴: %d 件" % len(hist) if hist else
                     "PC で動画の URL をコピーして、トレイの「コピーした動画の URL を Frame で再生する」を選んでください")

    def open_pc_dir(self, path):
        self.say("PC のフォルダを読んでいます…")

        def done(r, e):
            if e:
                self.say("PC のフォルダを読めません: %s" % media.redact(e), True)
                return
            items, url, real = r
            if self.panel.tab == "pc":
                self.panel.items, self.panel.scroll, self.panel.pc_dir = items, 0, real
                if real:
                    self.panel.pc_recent = media.add_pc_folder(real)
                self.dirty = True
            n = len([x for x in items if x.kind == "pc"])
            self.say("%s: 動画 %d 件" % (real or "PC", n))
            if url:
                self.open_youtube(url)
        self.run_job(lambda: media.list_pc_dir(path), done)

    def show_pc_recent(self):
        self.panel.pc_recent = media.load_pc_folders()
        self.panel.items = [media.dir_item("[最近]  " + p, p) for p in self.panel.pc_recent]
        self.panel.scroll = 0
        self.dirty = True
        self.say("最近のフォルダ: %d 件" % len(self.panel.items) if self.panel.items else "まだフォルダを開いていません")

    def receive_url(self):
        self.say("PC に URL を聞いています…")

        def done(r, e):
            if e:
                if self.held_url:
                    url, self.held_url = self.held_url, None
                    self.open_youtube(url)
                    return
                self.say("PC につながりません: %s" % media.redact(e), True)
                return
            url = r[2] or self.held_url
            self.held_url = None
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
        if it.kind == "pcdir":
            self.open_pc_dir(it.path)
            return
        self.say("開いています: %s" % it.title)

        def done(r, e):
            if e:
                self.say("開けません: %s" % media.redact(e), True)
                return
            if not media.playable(it):
                self.say("開けません: 動画として読めないファイルです(壊れているか、途中までしかありません): %s" % it.title, True)
                return
            self.playlist = [x for x in self.panel.items if x.kind == it.kind]
            self.start(it)
        self.run_job(it.probe, done)

    # ---- playback
    def start(self, it, pos=None):
        self.stop_playback(save=True)
        self.item = it
        self.yaw = 0.0
        self.mode = it.projection
        if pos is None:
            r = self.resume.get(it.key, {}).get("pos", 0)
            pos = r if (r > 10 and (not it.duration or r < it.duration - 10)) else 0
        self.paused = False
        self.play_at(pos)
        self.place()
        self.say("再生中: %s%s" % (it.title, ("(%s から)" % fmt_time(pos)) if pos else ""))
        if media.too_heavy(it):
            self.say("%dx%d の動画は Frame には重すぎます。映像が出るまで時間がかかり、音より遅れます。4K 以下の動画を使ってください"
                     % (it.width, it.height), True)

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
            for i, (h, m) in enumerate(zip(self.faces, cube_matrices(self.pose, self.yaw))):
                if self.mode == "180" and FACES[i] == "back":
                    ov.hide(h)
                    continue
                ov.set_width(h, CUBE_R * 2)
                ov.set_transform_abs(h, m)
                self.bounds(h, i / 6.0, (i + 1) / 6.0)
                ov.show(h)
        log.info("placed: mode=%s pose=%s", self.mode, "ok" if self.pose else "none (default)")

    def turn_view(self, d):
        """Rotate the 360/180 cube by d degrees around the vertical axis (only the transforms change)."""
        self.yaw = wrap_deg(self.yaw + d)
        for i, (h, m) in enumerate(zip(self.faces, cube_matrices(self.pose, self.yaw))):
            if not (self.mode == "180" and FACES[i] == "back"):
                self.ov.set_transform_abs(h, m)

    def show_osd(self, text, secs=1.2):
        """A small label in front of the eyes (seek / pause feedback while the dashboard is closed)."""
        cv = cairo.Canvas(OSD_W, OSD_H)
        cv.rrect(0, 0, OSD_W, OSD_H, 24, "#0f141c", alpha=0.85)
        cv.text(text, OSD_W / 2.0, OSD_H / 2.0 + 15, 42, "#ffffff", align="center", bold=True)
        data = cv.rgba_bytes()
        cv.close()
        self.ctx.upload(self.otex, OSD_W, OSD_H, data)
        self.bounds(self.osd)
        self.ov.set_gl_texture(self.osd, self.otex)
        self.ov.set_transform_hmd(self.osd, [1, 0, 0, 0, 0, 1, 0, -0.18, 0, 0, 1, -1.0])
        self.ov.show(self.osd)
        self.osd_until = time.monotonic() + secs

    def pump_osd(self):
        if self.osd_until and time.monotonic() > self.osd_until:
            self.osd_until = 0.0
            self.ov.hide(self.osd)

    def visible_video_overlays(self):
        if self.item is None:
            return []
        if self.mode == "flat":
            return [self.screen]
        return [h for i, h in enumerate(self.faces) if not (self.mode == "180" and FACES[i] == "back")]

    def toggle_pause(self, src):
        """src: who asked (panel button / bound action / control socket), logged so a stray pause is traceable."""
        if self.item is None:
            return
        log.info("toggle_pause from %s (was %s)", src, "paused" if self.paused else "playing")
        if self.paused:
            self.paused = False
            if self.pb is not None:
                self.pb.resume()  # SIGCONT + reader continues: immediate
            else:
                self.play_at(self.paused_pos)
            self.say("再生")
        else:
            self.paused_pos = self.position()
            if self.pb is not None:
                self.pb.pause()   # reader waits + SIGSTOP on audio: immediate
            self.remember(self.paused_pos)
            self.paused = True  # toggle_pause only
            self.say("一時停止 %s" % fmt_time(self.paused_pos))

    def seek(self, pos):
        if self.item is None:
            return
        pos = max(0.0, pos)
        if self.paused:
            self.paused_pos = pos
            if self.pb is not None:
                self.play_at(pos)
                self.pb.pause()  # shows the new position as a still frame
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

    def refresh_pc_token(self, pos):
        """The PC forgets tokens nobody used for 12 hours (or after many newer ones): get a new one, retry once."""
        it = self.item
        self.stop_playback(save=False)
        it.refreshed = True
        self.say("PC につなぎ直しています…")

        def done(r, e):
            if self.item is not it:
                return  # the user switched to something else meanwhile
            if e:
                self.say("PC の動画を開けません: %s" % media.redact(e), True)
                return
            base, token, url = r
            if url:
                self.held_url = url  # the tray hands a URL out once: keep it for 「PC から URL を受け取る」
            if getattr(it, "path", None):
                it.video = it.audio = media.pc_file_url(base, token, it.path)
            else:
                it.video = it.audio = media.pc_url(base, token, it.title)
            self.play_at(pos)
            self.say("再生中: %s" % it.title)
        self.run_job(media.pc_video, done)

    def restart_same(self):
        if self.item is None:
            return
        if not self.paused:
            self.play_at(self.position())
        elif self.pb is not None:
            self.play_at(self.position())
            self.pb.pause()

    # ---- input
    def click(self, key, frac):
        s = self.settings
        if key.startswith("tab:"):
            self.load_tab(key[4:])
        elif key == "pc:top":
            self.open_pc_dir("")
        elif key == "pc:recent":
            self.show_pc_recent()
        elif key.startswith("pcrecent:"):
            i = int(key[9:])
            if i < len(self.panel.pc_recent):
                self.open_pc_dir(self.panel.pc_recent[i])
        elif key == "reload":
            self.load_tab(self.panel.tab)
        elif key == "yt:recv":
            self.receive_url()
        elif key.startswith("item:"):
            self.open_index(int(key[5:]))
        elif key == "up":
            self.panel.scroll_by(-(ROWS - 2))
        elif key == "down":
            self.panel.scroll_by(ROWS - 2)
        elif key == "seekbar" and self.item and self.item.duration:
            self.seek(frac * self.item.duration)
        elif key.startswith("seek:"):
            self.seek(self.position() + int(key[5:]))
        elif key == "pause":
            self.toggle_pause("panel click")
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
        elif key == "stereo" and self.item:
            # stereo videos show only the left (or top) eye; this lets the user fix a wrong guess
            self.item.stereo = {"mono": "sbs", "sbs": "tb", "tb": "mono"}[self.item.stereo]
            self.restart_same()
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
        elif key in ("turn:-", "turn:+"):
            if self.item is not None and self.mode != "flat":
                self.turn_view(TURN_STEP if key == "turn:+" else -TURN_STEP)
        elif key == "recenter":
            self.yaw = 0.0
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
            if self.item is not None and getattr(self.item, "refreshed", False):
                self.item.refreshed = False
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
                if pb.frames == 0 and self.item.kind == "pc" and not getattr(self.item, "refreshed", False):
                    self.refresh_pc_token(pb.position())
                    return
                self.say("再生が止まりました(ログを見てください)", True)
                self.paused_pos = pb.position()
                self.stop_playback(save=True)
                self.paused = True  # the video process died (warning logged above)
            else:
                self.remember(self.item.duration)
                self.next_item()
        now = time.time()
        if self.pb is not None and now - self.last_save > 5:
            self.last_save = now
            self.remember(self.pb.position())

    def draw_panel(self):
        t0 = time.monotonic()
        cv = self.panel.draw(self)
        data = cv.rgba_bytes()
        cv.close()
        self.ctx.upload(self.ptex, W, H, data)
        self.bounds(self.main)
        e = self.ov.set_gl_texture(self.main, self.ptex)
        if e:
            log.warning("panel SetOverlayTexture: %s", self.ov.err_name(e))
        self.dirty = False
        return (time.monotonic() - t0) * 1000

    def close(self):
        self.stop_playback(save=True)
        for h in [self.screen] + self.faces + [self.osd, self.main]:
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
        secs = 15.0
        if cmd == "test" and len(args) > 1:
            try:
                secs = float(args[-1])
                args = args[:-1]
            except ValueError:
                pass
        src = " ".join(args)  # paths may contain spaces
        if cmd == "test":
            test.update(until=time.time() + secs, frames=0, t0=time.time())
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
        app.toggle_pause("control socket")


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
    ov.set_flag(app.main, vr.FLAG_SEND_SMOOTH_SCROLL, True)  # laser scroll over the panel -> EV_SCROLL_SMOOTH
    down = None          # (key, x, y) at mouse down: taps survive a little pointer shake
    pending_click = None  # monotonic time of the last click, for the latency log
    stats = {"n": 0, "loop_max": 0.0, "draw_max": 0.0, "t": time.monotonic()}
    prev = time.monotonic()
    try:
        while not stop["flag"]:
            t_loop = time.monotonic()
            dt, prev = min(0.1, t_loop - prev), t_loop
            for ev in ov.poll(app.main):
                t = ev.eventType
                if t == vr.EV_QUIT:
                    # only 700 (Quit) is for us; 701 (ProcessQuit) is sent when *any* OpenVR process exits
                    log.info("quit event from SteamVR")
                    stop["flag"] = True
                elif t in (vr.EV_SCROLL_SMOOTH, vr.EV_SCROLL_DISCRETE):
                    # VREvent_Scroll_t xdelta/ydelta share the place of the mouse x/y
                    rows = scroll_from_smooth(ev.y) if t == vr.EV_SCROLL_SMOOTH else -ev.y * 2
                    if app.settings.get("scroll_invert"):
                        rows = -rows
                    if app.panel.scroll_by(rows):
                        app.dirty = True
                elif t in (vr.EV_MOUSE_MOVE, vr.EV_MOUSE_DOWN, vr.EV_MOUSE_UP):
                    x, y = panel_xy(ev.x, ev.y, app.settings.get("flip", True))
                    key, frac = app.panel.hit(x, y)
                    if t == vr.EV_MOUSE_MOVE:
                        if key != app.panel.hover:
                            app.panel.hover = key
                            app.dirty = True
                    elif t == vr.EV_MOUSE_DOWN and ev.button == 1:
                        down = (key, x, y)
                        if key and app.panel.hover != key:
                            app.panel.hover = key  # immediate visual feedback
                            app.dirty = True
                    elif t == vr.EV_MOUSE_UP and ev.button == 1:
                        key2 = resolve_tap(down, (key, x, y))
                        if key2 and key2 != key:
                            _k, frac = app.panel.hit(down[1], down[2])
                        down = None
                        if key2:
                            pending_click = time.monotonic()
                            try:
                                app.click(key2, frac)
                            except Exception:
                                log.exception("click failed")
                                app.say("エラーが起きました(ログを見てください)", True)
                            app.dirty = True
                            ms = app.draw_panel()  # redraw right away, before anything slow
                            log.info("click %s: handled+drawn in %.0f ms (draw %.0f ms)", key2,
                                     (time.monotonic() - pending_click) * 1000, ms)
                elif t == vr.EV_FOCUS_LEAVE:
                    down = None
                    if app.panel.hover:
                        app.panel.hover = None
                        app.dirty = True
            dash = ov.dashboard_visible()
            app.pump_osd()
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
                if app.item is not None and dash and not app.paused:
                    app.dirty = True  # time display
            if app.dirty:
                stats["draw_max"] = max(stats["draw_max"], app.draw_panel())
            el = (time.monotonic() - t_loop) * 1000
            stats["n"] += 1
            stats["loop_max"] = max(stats["loop_max"], el)
            if time.monotonic() - stats["t"] > 60 and app.item is not None:
                log.info("loop: %d iterations/60s, slowest %.0f ms, slowest panel draw %.0f ms",
                         stats["n"], stats["loop_max"], stats["draw_max"])
                stats.update(n=0, loop_max=0.0, draw_max=0.0, t=time.monotonic())
            time.sleep(0.005 if (app.pb or app.item is not None or dash) else 0.03)
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
