"""A headless OpenGL context (EGL, no window) and one RGBA texture, via ctypes.

Video frames are uploaded into the texture and handed to SteamVR with SetOverlayTexture.
SetOverlayRaw is not used for video: it blanks the overlay on every call (flicker).
"""
import ctypes

EGL_NONE = 0x3038
EGL_OPENGL_API = 0x30A2
EGL_RENDERABLE_TYPE = 0x3040
EGL_OPENGL_BIT = 0x0008
EGL_SURFACE_TYPE = 0x3033
EGL_PBUFFER_BIT = 0x0001
EGL_WIDTH = 0x3057
EGL_HEIGHT = 0x3056
EGL_PLATFORM_SURFACELESS_MESA = 0x31DD
GL_TEXTURE_2D = 0x0DE1
GL_RGBA = 0x1908
GL_RGBA8 = 0x8058
GL_UNSIGNED_BYTE = 0x1401
GL_LINEAR = 0x2601
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_TEXTURE_WRAP_S = 0x2802
GL_TEXTURE_WRAP_T = 0x2803
GL_CLAMP_TO_EDGE = 0x812F
GL_UNPACK_ALIGNMENT = 0x0CF5
GL_VENDOR = 0x1F00
GL_RENDERER = 0x1F01
GL_VERSION = 0x1F02

P = ctypes.c_void_p


class GLError(Exception):
    pass


class Context:
    def __init__(self):
        egl = ctypes.CDLL("libEGL.so.1")
        self.egl = egl
        egl.eglGetProcAddress.restype = P
        egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]
        egl.eglGetDisplay.restype = P
        egl.eglInitialize.argtypes = [P, P, P]
        egl.eglChooseConfig.argtypes = [P, P, ctypes.POINTER(P), ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        egl.eglCreateContext.restype = P
        egl.eglCreateContext.argtypes = [P, P, P, P]
        egl.eglCreatePbufferSurface.restype = P
        egl.eglCreatePbufferSurface.argtypes = [P, P, P]
        egl.eglMakeCurrent.argtypes = [P, P, P, P]
        egl.eglGetError.restype = ctypes.c_int
        self.how = ""
        dpy = None
        addr = egl.eglGetProcAddress(b"eglGetPlatformDisplayEXT")
        if addr:
            f = ctypes.CFUNCTYPE(P, ctypes.c_int, P, P)(addr)
            dpy = f(EGL_PLATFORM_SURFACELESS_MESA, None, None)
            self.how = "surfaceless"
        if not dpy or not egl.eglInitialize(dpy, None, None):
            dpy = egl.eglGetDisplay(None)
            self.how = "default"
            if not dpy or not egl.eglInitialize(dpy, None, None):
                raise GLError("eglInitialize failed: 0x%x" % egl.eglGetError())
        self.dpy = dpy
        if not egl.eglBindAPI(EGL_OPENGL_API):
            raise GLError("eglBindAPI(OpenGL) failed: 0x%x" % egl.eglGetError())
        cfg = P()
        n = ctypes.c_int(0)
        attrs = (ctypes.c_int * 5)(EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT, EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_NONE)
        if not egl.eglChooseConfig(dpy, attrs, ctypes.byref(cfg), 1, ctypes.byref(n)) or n.value < 1:
            attrs = (ctypes.c_int * 3)(EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT, EGL_NONE)
            if not egl.eglChooseConfig(dpy, attrs, ctypes.byref(cfg), 1, ctypes.byref(n)) or n.value < 1:
                raise GLError("eglChooseConfig failed: 0x%x" % egl.eglGetError())
        ctx = egl.eglCreateContext(dpy, cfg, None, (ctypes.c_int * 1)(EGL_NONE))
        if not ctx:
            raise GLError("eglCreateContext failed: 0x%x" % egl.eglGetError())
        surf = None
        if not egl.eglMakeCurrent(dpy, None, None, ctx):
            surf = egl.eglCreatePbufferSurface(dpy, cfg, (ctypes.c_int * 5)(EGL_WIDTH, 16, EGL_HEIGHT, 16, EGL_NONE))
            if not surf or not egl.eglMakeCurrent(dpy, surf, surf, ctx):
                raise GLError("eglMakeCurrent failed: 0x%x" % egl.eglGetError())
        self.ctx = ctx
        try:
            gl = ctypes.CDLL("libOpenGL.so.0")
        except OSError:
            gl = ctypes.CDLL("libGL.so.1")
        self.gl = gl
        gl.glGetString.restype = ctypes.c_char_p
        gl.glTexImage2D.argtypes = [ctypes.c_uint] + [ctypes.c_int] * 6 + [ctypes.c_uint, P]
        gl.glTexSubImage2D.argtypes = [ctypes.c_uint] + [ctypes.c_int] * 5 + [ctypes.c_uint, ctypes.c_uint, P]

    def info(self):
        g = self.gl.glGetString
        return "%s / %s / %s (%s)" % (g(GL_VENDOR), g(GL_RENDERER), g(GL_VERSION), self.how)

    def new_texture(self, w, h):
        gl = self.gl
        t = ctypes.c_uint(0)
        gl.glGenTextures(1, ctypes.byref(t))
        gl.glBindTexture(GL_TEXTURE_2D, t.value)
        for k, v in ((GL_TEXTURE_MIN_FILTER, GL_LINEAR), (GL_TEXTURE_MAG_FILTER, GL_LINEAR),
                     (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE), (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)):
            gl.glTexParameteri(GL_TEXTURE_2D, k, v)
        gl.glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
        return t.value

    def upload(self, tex, w, h, buf):
        """buf: bytearray of w*h*4 RGBA bytes."""
        gl = self.gl
        gl.glBindTexture(GL_TEXTURE_2D, tex)
        arr = (ctypes.c_char * len(buf)).from_buffer(buf)
        gl.glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, ctypes.cast(arr, P))
        gl.glFinish()
