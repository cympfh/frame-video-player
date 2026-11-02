"""OpenVR のオーバーレイ API を ctypes で使うための最小の部品(標準ライブラリだけ)。

SteamOS(Frame)の SteamVR に入っている libopenvr_api.so を読み、C 用の関数表(FnTable)から
IVROverlay_028(無ければ 027)を使う。関数表の並びは openvr_capi.h の VR_IVROverlay_FnTable と同じ(版で並びが違うので、版ごとに持つ)。
"""
import ctypes
import glob
import os
import platform

OVERLAY_VERSIONS = ("IVROverlay_028", "IVROverlay_027")  # 新しい順に試す

# VR_IVROverlay_FnTable の並び(openvr_capi.h / IVROverlay_028)。ポインタは全部同じ大きさなので、並びだけ合っていればよい。
# IVROverlay_027(SteamVR 付属の openvr_capi.h と同じ並び。80 個)
FN_ORDER_027 = [
    "FindOverlay", "CreateOverlay", "DestroyOverlay", "GetOverlayKey", "GetOverlayName", "SetOverlayName",
    "GetOverlayImageData", "GetOverlayErrorNameFromEnum", "SetOverlayRenderingPid", "GetOverlayRenderingPid",
    "SetOverlayFlag", "GetOverlayFlag", "GetOverlayFlags", "SetOverlayColor", "GetOverlayColor", "SetOverlayAlpha",
    "GetOverlayAlpha", "SetOverlayTexelAspect", "GetOverlayTexelAspect", "SetOverlaySortOrder", "GetOverlaySortOrder",
    "SetOverlayWidthInMeters", "GetOverlayWidthInMeters", "SetOverlayCurvature", "GetOverlayCurvature",
    "SetOverlayPreCurvePitch", "GetOverlayPreCurvePitch", "SetOverlayTextureColorSpace", "GetOverlayTextureColorSpace",
    "SetOverlayTextureBounds", "GetOverlayTextureBounds", "GetOverlayTransformType", "SetOverlayTransformAbsolute",
    "GetOverlayTransformAbsolute", "SetOverlayTransformTrackedDeviceRelative", "GetOverlayTransformTrackedDeviceRelative",
    "SetOverlayTransformTrackedDeviceComponent", "GetOverlayTransformTrackedDeviceComponent", "SetOverlayTransformCursor",
    "GetOverlayTransformCursor", "SetOverlayTransformProjection", "ShowOverlay", "HideOverlay", "IsOverlayVisible",
    "GetTransformForOverlayCoordinates", "WaitFrameSync", "PollNextOverlayEvent", "GetOverlayInputMethod",
    "SetOverlayInputMethod", "GetOverlayMouseScale", "SetOverlayMouseScale", "ComputeOverlayIntersection",
    "IsHoverTargetOverlay", "SetOverlayIntersectionMask", "TriggerLaserMouseHapticVibration", "SetOverlayCursor",
    "SetOverlayCursorPositionOverride", "ClearOverlayCursorPositionOverride", "SetOverlayTexture", "ClearOverlayTexture",
    "SetOverlayRaw", "SetOverlayFromFile", "GetOverlayTexture", "ReleaseNativeOverlayHandle", "GetOverlayTextureSize",
    "CreateDashboardOverlay", "IsDashboardVisible", "IsActiveDashboardOverlay", "SetDashboardOverlaySceneProcess",
    "GetDashboardOverlaySceneProcess", "ShowDashboard", "GetPrimaryDashboardDevice", "ShowKeyboard",
    "ShowKeyboardForOverlay", "GetKeyboardText", "HideKeyboard", "SetKeyboardTransformAbsolute",
    "SetKeyboardPositionForOverlay", "ShowMessageOverlay", "CloseMessageOverlay",
]

# IVROverlay_028(OpenVR 公式の openvr_capi.h の並び。027 に CreateSubviewOverlay と SetSubviewPosition が増えた。82 個)
FN_ORDER_028 = [
    "FindOverlay", "CreateOverlay", "CreateSubviewOverlay", "DestroyOverlay", "GetOverlayKey", "GetOverlayName",
    "SetOverlayName", "GetOverlayImageData", "GetOverlayErrorNameFromEnum", "SetOverlayRenderingPid",
    "GetOverlayRenderingPid", "SetOverlayFlag", "GetOverlayFlag", "GetOverlayFlags", "SetOverlayColor",
    "GetOverlayColor", "SetOverlayAlpha", "GetOverlayAlpha", "SetOverlayTexelAspect", "GetOverlayTexelAspect",
    "SetOverlaySortOrder", "GetOverlaySortOrder", "SetOverlayWidthInMeters", "GetOverlayWidthInMeters",
    "SetOverlayCurvature", "GetOverlayCurvature", "SetOverlayPreCurvePitch", "GetOverlayPreCurvePitch",
    "SetOverlayTextureColorSpace", "GetOverlayTextureColorSpace", "SetOverlayTextureBounds",
    "GetOverlayTextureBounds", "GetOverlayTransformType", "SetOverlayTransformAbsolute",
    "GetOverlayTransformAbsolute", "SetOverlayTransformTrackedDeviceRelative",
    "GetOverlayTransformTrackedDeviceRelative", "SetOverlayTransformTrackedDeviceComponent",
    "GetOverlayTransformTrackedDeviceComponent", "SetOverlayTransformCursor", "GetOverlayTransformCursor",
    "SetOverlayTransformProjection", "SetSubviewPosition", "ShowOverlay", "HideOverlay", "IsOverlayVisible",
    "GetTransformForOverlayCoordinates", "WaitFrameSync", "PollNextOverlayEvent", "GetOverlayInputMethod",
    "SetOverlayInputMethod", "GetOverlayMouseScale", "SetOverlayMouseScale", "ComputeOverlayIntersection",
    "IsHoverTargetOverlay", "SetOverlayIntersectionMask", "TriggerLaserMouseHapticVibration", "SetOverlayCursor",
    "SetOverlayCursorPositionOverride", "ClearOverlayCursorPositionOverride", "SetOverlayTexture",
    "ClearOverlayTexture", "SetOverlayRaw", "SetOverlayFromFile", "GetOverlayTexture", "ReleaseNativeOverlayHandle",
    "GetOverlayTextureSize", "CreateDashboardOverlay", "IsDashboardVisible", "IsActiveDashboardOverlay",
    "SetDashboardOverlaySceneProcess", "GetDashboardOverlaySceneProcess", "ShowDashboard",
    "GetPrimaryDashboardDevice", "ShowKeyboard", "ShowKeyboardForOverlay", "GetKeyboardText", "HideKeyboard",
    "SetKeyboardTransformAbsolute", "SetKeyboardPositionForOverlay", "ShowMessageOverlay", "CloseMessageOverlay",
]

FN_ORDERS = {"IVROverlay_028": FN_ORDER_028, "IVROverlay_027": FN_ORDER_027}
FN_ORDER = FN_ORDER_028  # 互換用の別名

# イベントの種類(EVREventType)
EV_MOUSE_MOVE = 300
EV_MOUSE_DOWN = 301
EV_MOUSE_UP = 302
EV_FOCUS_ENTER = 303
EV_FOCUS_LEAVE = 304
EV_SCROLL_DISCRETE = 305  # data is VREvent_Scroll_t: xdelta, ydelta at the same place as mouse x, y
EV_SCROLL_SMOOTH = 309
EV_OVERLAY_SHOWN = 500
EV_OVERLAY_HIDDEN = 501
EV_DASHBOARD_ACTIVATED = 502
EV_DASHBOARD_DEACTIVATED = 503
EV_QUIT = 700
EV_PROCESS_QUIT = 701

# VR_Init が返すエラーのうち、SteamVR が起動していない・起動途中のときに出るもの(openvr.h の EVRInitError)
INIT_ERRORS = {
    1: "VRInitError_Unknown", 109: "VRInitError_Init_NotInitialized", 119: "VRInitError_Init_ShuttingDown",
    121: "VRInitError_Init_NoServerForBackgroundApp", 124: "VRInitError_Init_Internal",
    300: "VRInitError_IPC_ServerInitFailed", 301: "VRInitError_IPC_ConnectFailed",
    302: "VRInitError_IPC_SharedStateInitFailed", 303: "VRInitError_IPC_CompositorInitFailed",
    305: "VRInitError_IPC_Failed", 306: "VRInitError_IPC_CompositorConnectFailed",
    308: "VRInitError_IPC_ConnectFailedAfterMultipleAttempts", 309: "VRInitError_IPC_ConnectFailedAfterTargetExited",
    403: "VRInitError_Compositor_OverlayInitFailed",
}

APP_OVERLAY = 2          # VRApplication_Overlay
INPUT_MOUSE = 1          # VROverlayInputMethod_Mouse
FLAG_ENABLE_CLICK_STABILIZATION = 1 << 27
FLAG_SEND_DISCRETE_SCROLL = 1 << 6   # VROverlayFlags_SendVRDiscreteScrollEvents
FLAG_SEND_SMOOTH_SCROLL = 1 << 17    # VROverlayFlags_SendVRSmoothScrollEvents

EVENT_SIZE = 60          # sizeof(VREvent_t)(openvr_capi.h を gcc で測った値。pack(4))


class HmdVector2(ctypes.Structure):
    _fields_ = [("v0", ctypes.c_float), ("v1", ctypes.c_float)]


class VREvent(ctypes.Structure):
    """VREvent_t のうち必要な部分。data はマウスイベントの x, y, button だけ読む。pack(4)・全体 60 バイト。"""
    _pack_ = 4
    _fields_ = [("eventType", ctypes.c_uint32), ("trackedDeviceIndex", ctypes.c_uint32),
                ("eventAgeSeconds", ctypes.c_float),
                ("x", ctypes.c_float), ("y", ctypes.c_float), ("button", ctypes.c_uint32),
                ("_rest", ctypes.c_uint8 * (EVENT_SIZE - 24))]


assert ctypes.sizeof(VREvent) == EVENT_SIZE


class Texture(ctypes.Structure):
    """Texture_t: handle (GL texture name as a pointer), eType (1 = OpenGL), eColorSpace (0 = Auto)."""
    _fields_ = [("handle", ctypes.c_void_p), ("eType", ctypes.c_int), ("eColorSpace", ctypes.c_int)]


class TextureBounds(ctypes.Structure):
    _fields_ = [("uMin", ctypes.c_float), ("vMin", ctypes.c_float), ("uMax", ctypes.c_float), ("vMax", ctypes.c_float)]


class Matrix34(ctypes.Structure):
    _fields_ = [("m", ctypes.c_float * 12)]


TEXTURE_OPENGL = 1
ORIGIN_SEATED = 0
ORIGIN_STANDING = 1
HMD_INDEX = 0


class OpenVRError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def find_library():
    arch = "linuxarm64" if platform.machine() in ("aarch64", "arm64") else "linux64"
    cands = [os.environ.get("FVP_OPENVR_LIB", ""), "/opt/steamvr/bin/%s/libopenvr_api.so" % arch]
    cands += glob.glob(os.path.expanduser("~/.local/share/Steam/steamapps/common/SteamVR/bin/%s/libopenvr_api.so" % arch))
    for c in cands:
        if c and os.path.exists(c):
            return c
    raise OpenVRError("libopenvr_api.so が見つかりません")


class Overlay:
    """IVROverlay の FnTable。init() で SteamVR につなぐ(SteamVR が動いていなければ OpenVRError)。"""

    def __init__(self, lib_path=None):
        self.lib = ctypes.CDLL(lib_path or find_library())
        self.lib.VR_InitInternal.restype = ctypes.c_void_p
        self.lib.VR_InitInternal.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
        self.lib.VR_GetGenericInterface.restype = ctypes.c_void_p
        self.lib.VR_GetGenericInterface.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
        self.inited = False
        self.fn = None
        self.order = FN_ORDER
        self.version = None

    def _sym(self, err):
        """VR_Init のエラー番号を、読める名前にする。

        libopenvr_api の VR_GetVRInitErrorAsSymbol は、SteamVR が起動途中でつなぎに失敗した直後に呼ぶと、
        解放済みの文字列を指して SEGV することがある(0.2.1 までは SteamVR の起動直後にパネルが何度も落ちていた原因)。
        そのため呼ばずに、自分で持っている表だけで名前にする。
        """
        return INIT_ERRORS.get(err, "VRInitError %d" % err)

    def init(self):
        err = ctypes.c_int(0)
        self.lib.VR_InitInternal(ctypes.byref(err), APP_OVERLAY)
        if err.value != 0:
            raise OpenVRError("SteamVR につなげません: %s" % self._sym(err.value), err.value)
        self.inited = True
        last = None
        for ver in OVERLAY_VERSIONS:
            err = ctypes.c_int(0)
            p = self.lib.VR_GetGenericInterface(("FnTable:" + ver).encode(), ctypes.byref(err))
            if err.value != 0 or not p:
                last = "%s が取れません: %s" % (ver, self._sym(err.value))
                continue
            self.version = ver
            self.order = FN_ORDERS[ver]
            self.fn = (ctypes.c_void_p * len(self.order)).from_address(p)
            self._bind()
            if self._table_ok():
                return
            last = "%s の関数表の並びが想定と違います" % ver
            self.fn = None
        self.shutdown()
        raise OpenVRError("IVROverlay が使えません: %s" % last)

    def _table_ok(self):
        """関数表の並びが合っているかの確認: GetOverlayErrorNameFromEnum(0) が "VROverlayError_None" を返すか。"""
        try:
            ptr = self._f["GetOverlayErrorNameFromEnum"](0)
            return bool(ptr) and ptr > 4096 and ctypes.string_at(ptr) == b"VROverlayError_None"
        except Exception:
            return False

    def shutdown(self):
        if self.inited:
            try:
                self.lib.VR_ShutdownInternal()
            except Exception:
                pass
            self.inited = False
        self.fn = None

    def _bind(self):
        t = ctypes
        H = t.c_uint64
        E = t.c_int
        sigs = {
            "FindOverlay": (E, [t.c_char_p, t.POINTER(H)]),
            "CreateDashboardOverlay": (E, [t.c_char_p, t.c_char_p, t.POINTER(H), t.POINTER(H)]),
            "DestroyOverlay": (E, [H]),
            "SetOverlayWidthInMeters": (E, [H, t.c_float]),
            "SetOverlayFlag": (E, [H, t.c_int, t.c_bool]),
            "SetOverlayInputMethod": (E, [H, t.c_int]),
            "SetOverlayMouseScale": (E, [H, t.POINTER(HmdVector2)]),
            "SetOverlayRaw": (E, [H, t.c_void_p, t.c_uint32, t.c_uint32, t.c_uint32]),
            "SetOverlayFromFile": (E, [H, t.c_char_p]),
            "GetOverlayTextureSize": (E, [H, t.POINTER(t.c_uint32), t.POINTER(t.c_uint32)]),
            "PollNextOverlayEvent": (t.c_bool, [H, t.POINTER(VREvent), t.c_uint32]),
            "IsDashboardVisible": (t.c_bool, []),
            "IsOverlayVisible": (t.c_bool, [H]),
            "ShowDashboard": (None, [t.c_char_p]),
            "GetOverlayErrorNameFromEnum": (t.c_void_p, [E]),
        }
        # 無くても動く関数(IVROverlay_028 にだけある・古い SteamVR に無いかもしれないもの)
        optional = {
            "CreateSubviewOverlay": (E, [H, t.c_char_p, t.c_char_p, t.POINTER(H)]),
            "SetSubviewPosition": (E, [H, t.c_float, t.c_float]),
            "ShowOverlay": (E, [H]),
            "HideOverlay": (E, [H]),
            "SetOverlayAlpha": (E, [H, t.c_float]),
            "CreateOverlay": (E, [t.c_char_p, t.c_char_p, t.POINTER(H)]),
            "SetOverlayTexture": (E, [H, t.POINTER(Texture)]),
            "ClearOverlayTexture": (E, [H]),
            "SetOverlayTextureBounds": (E, [H, t.POINTER(TextureBounds)]),
            "SetOverlayTransformAbsolute": (E, [H, t.c_int, t.POINTER(Matrix34)]),
            "SetOverlayTransformTrackedDeviceRelative": (E, [H, t.c_uint32, t.POINTER(Matrix34)]),
            "SetOverlayCurvature": (E, [H, t.c_float]),
            "SetOverlaySortOrder": (E, [H, t.c_uint32]),
            "SetOverlayTexelAspect": (E, [H, t.c_float]),
        }
        self._f = {}
        for name, (res, args) in sigs.items():
            addr = self.fn[self.order.index(name)]
            if not addr:
                raise OpenVRError("IVROverlay の関数 %s がありません" % name)
            self._f[name] = t.CFUNCTYPE(res, *args)(addr)
        for name, (res, args) in optional.items():
            if name in self.order:
                addr = self.fn[self.order.index(name)]
                if addr:
                    self._f[name] = t.CFUNCTYPE(res, *args)(addr)

    def err_name(self, e):
        ptr = self._f["GetOverlayErrorNameFromEnum"](e)
        return ctypes.string_at(ptr).decode() if ptr and ptr > 4096 else str(e)

    def _check(self, what, e):
        if e != 0:
            raise OpenVRError("%s: %s" % (what, self.err_name(e)), e)

    def find(self, key):
        h = ctypes.c_uint64(0)
        e = self._f["FindOverlay"](key.encode(), ctypes.byref(h))
        return h.value if e == 0 else None

    def create_dashboard(self, key, name):
        main, thumb = ctypes.c_uint64(0), ctypes.c_uint64(0)
        e = self._f["CreateDashboardOverlay"](key.encode(), name.encode(), ctypes.byref(main), ctypes.byref(thumb))
        self._check("CreateDashboardOverlay", e)
        return main.value, thumb.value

    def destroy(self, handle):
        return self._f["DestroyOverlay"](handle)

    def set_width(self, handle, meters):
        self._check("SetOverlayWidthInMeters", self._f["SetOverlayWidthInMeters"](handle, meters))

    def set_flag(self, handle, flag, on):
        return self._f["SetOverlayFlag"](handle, flag, on)  # 古い SteamVR に無い旗でも続ける(戻り値は見ない)

    def set_mouse(self, handle, w, h):
        self._check("SetOverlayInputMethod", self._f["SetOverlayInputMethod"](handle, INPUT_MOUSE))
        sc = HmdVector2(float(w), float(h))
        self._check("SetOverlayMouseScale", self._f["SetOverlayMouseScale"](handle, ctypes.byref(sc)))

    def set_raw(self, handle, buf, w, h):
        """RGBA 8bit(上の行から)の画像を貼る。buf は w*h*4 バイトの bytes/bytearray。"""
        if len(buf) != w * h * 4:
            raise ValueError("画像のサイズが合いません")
        arr = (ctypes.c_char * len(buf)).from_buffer(buf) if isinstance(buf, bytearray) else ctypes.c_char_p(bytes(buf))
        self._check("SetOverlayRaw", self._f["SetOverlayRaw"](handle, ctypes.cast(arr, ctypes.c_void_p), w, h, 4))

    @property
    def has_subview(self):
        """「親のオーバーレイの上に小さな画像を重ねる」サブビューが使えるか(IVROverlay_028 以上)。"""
        return all(n in self._f for n in ("CreateSubviewOverlay", "SetSubviewPosition", "ShowOverlay", "HideOverlay"))

    @property
    def has_alpha(self):
        return "SetOverlayAlpha" in self._f

    def create_subview(self, parent, key, name):
        """親(同じプロセスのオーバーレイ)の上に重ねる小さな画像のオーバーレイを作る。座標は親の画像の px。"""
        if "CreateSubviewOverlay" not in self._f:
            raise OpenVRError("CreateSubviewOverlay が使えません(%s)" % self.version)
        h = ctypes.c_uint64(0)
        e = self._f["CreateSubviewOverlay"](parent, key.encode(), name.encode(), ctypes.byref(h))
        self._check("CreateSubviewOverlay", e)
        return h.value

    def set_subview_position(self, handle, x, y):
        self._check("SetSubviewPosition", self._f["SetSubviewPosition"](handle, float(x), float(y)))

    def show(self, handle):
        self._check("ShowOverlay", self._f["ShowOverlay"](handle))

    def hide(self, handle):
        self._check("HideOverlay", self._f["HideOverlay"](handle))

    def set_alpha(self, handle, a):
        self._check("SetOverlayAlpha", self._f["SetOverlayAlpha"](handle, float(a)))

    def set_from_file(self, handle, path):
        return self._f["SetOverlayFromFile"](handle, path.encode())

    def texture_size(self, handle):
        w, h = ctypes.c_uint32(0), ctypes.c_uint32(0)
        e = self._f["GetOverlayTextureSize"](handle, ctypes.byref(w), ctypes.byref(h))
        return e, w.value, h.value

    def poll(self, handle):
        """たまっているイベントを全部取り出す。VREvent のリスト(コピー)。"""
        out = []
        ev = VREvent()
        while self._f["PollNextOverlayEvent"](handle, ctypes.byref(ev), EVENT_SIZE):
            c = VREvent()
            ctypes.memmove(ctypes.byref(c), ctypes.byref(ev), EVENT_SIZE)
            out.append(c)
            if len(out) > 500:
                break
        return out

    def dashboard_visible(self):
        return bool(self._f["IsDashboardVisible"]())

    def show_dashboard(self, key):
        self._f["ShowDashboard"](key.encode())

    # --- added for frame-video-player ---
    def create(self, key, name):
        h = ctypes.c_uint64(0)
        self._check("CreateOverlay", self._f["CreateOverlay"](key.encode(), name.encode(), ctypes.byref(h)))
        return h.value

    def set_gl_texture(self, handle, tex_id):
        tx = Texture(ctypes.c_void_p(tex_id), TEXTURE_OPENGL, 0)
        return self._f["SetOverlayTexture"](handle, ctypes.byref(tx))

    def clear_texture(self, handle):
        return self._f["ClearOverlayTexture"](handle)

    def set_bounds(self, handle, u0, v0, u1, v1):
        b = TextureBounds(u0, v0, u1, v1)
        return self._f["SetOverlayTextureBounds"](handle, ctypes.byref(b))

    def set_transform_hmd(self, handle, mat12):
        m = Matrix34((ctypes.c_float * 12)(*mat12))
        return self._f["SetOverlayTransformTrackedDeviceRelative"](handle, HMD_INDEX, ctypes.byref(m))

    def set_transform_abs(self, handle, mat12, origin=ORIGIN_STANDING):
        m = Matrix34((ctypes.c_float * 12)(*mat12))
        return self._f["SetOverlayTransformAbsolute"](handle, origin, ctypes.byref(m))

    def set_curvature(self, handle, c):
        return self._f["SetOverlayCurvature"](handle, float(c))

    def set_sort(self, handle, n):
        return self._f["SetOverlaySortOrder"](handle, int(n))

    # --- head pose (IVRSystem) ---
    def hmd_pose(self, origin=ORIGIN_STANDING):
        """The headset's 3x4 pose matrix (12 floats, row-major) in the given tracking space, or None."""
        if not hasattr(self, "_pose_fn"):
            self._pose_fn = None
            err = ctypes.c_int(0)
            for ver in ("IVRSystem_023", "IVRSystem_022"):
                p = self.lib.VR_GetGenericInterface(("FnTable:" + ver).encode(), ctypes.byref(err))
                if p and err.value == 0:
                    tbl = (ctypes.c_void_p * 16).from_address(p)
                    # GetDeviceToAbsoluteTrackingPose is entry 11 in VR_IVRSystem_FnTable (openvr_capi.h)
                    self._pose_fn = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_float,
                                                     ctypes.POINTER(TrackedDevicePose), ctypes.c_uint32)(tbl[11])
                    break
        if not self._pose_fn:
            return None
        pose = TrackedDevicePose()
        self._pose_fn(origin, 0.0, ctypes.byref(pose), 1)
        if not pose.bPoseIsValid:
            return None
        return list(pose.m)


class TrackedDevicePose(ctypes.Structure):
    _fields_ = [("m", ctypes.c_float * 12), ("vel", ctypes.c_float * 3), ("angvel", ctypes.c_float * 3),
                ("result", ctypes.c_int), ("bPoseIsValid", ctypes.c_bool), ("bDeviceIsConnected", ctypes.c_bool)]
