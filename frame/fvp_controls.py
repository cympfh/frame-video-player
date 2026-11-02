"""Pure input logic (no OpenVR here, so it is unit-tested): sticks, seeking, rotation, scrolling, taps."""
import math

DEADZONE = 0.25


def deadzone(v, dz=DEADZONE):
    """Map |v| in [dz, 1] to [0, 1] keeping the sign; smaller is 0."""
    a = abs(v)
    if a <= dz:
        return 0.0
    return math.copysign(min(1.0, (a - dz) / (1.0 - dz)), v)


def yaw_step(stick_x, dt, max_deg_per_s=90.0):
    """Yaw change in degrees for this frame. Right stick right = turn the view right (scene rotates left)."""
    return _curve(deadzone(stick_x)) * max_deg_per_s * dt


def _curve(v):
    # gentle near the centre, full speed at the edge
    return math.copysign(v * v, v)


def wrap_deg(a):
    return (a + 180.0) % 360.0 - 180.0


class SeekRepeater:
    """Left stick left/right: one step at once, then repeats while held, faster when pushed further.

    feed(x, now) returns the seconds to seek now (0 when nothing to do).
    """
    STEP = 10.0
    FIRST_DELAY = 0.45
    PRESS = 0.6     # |x| to count as pushed
    RELEASE = 0.35  # |x| to count as released (hysteresis)

    def __init__(self):
        self.dir = 0
        self.next_at = 0.0
        self.count = 0

    def feed(self, x, now):
        if self.dir and abs(x) < self.RELEASE:
            self.dir = 0
            return 0.0
        d = 1 if x >= self.PRESS else (-1 if x <= -self.PRESS else 0)
        if d == 0:
            return 0.0
        if d != self.dir:
            self.dir, self.count = d, 1
            self.next_at = now + self.FIRST_DELAY
            return d * self.STEP
        if now >= self.next_at:
            self.count += 1
            # full deflection repeats every 0.15 s, light push every 0.35 s; long holds jump 30 s
            gap = 0.35 - 0.2 * deadzone(abs(x), self.PRESS)
            self.next_at = now + gap
            return d * (30.0 if self.count > 8 else self.STEP)
        return 0.0


class Edge:
    """Rising edge of a button (bool state)."""

    def __init__(self):
        self.prev = False

    def feed(self, state):
        hit = state and not self.prev
        self.prev = bool(state)
        return hit


def scroll_clamp(scroll, n_items, rows):
    return min(max(0.0, float(n_items - rows)), max(0.0, scroll))


def scroll_from_smooth(ydelta, rows_per_unit=6.0):
    """VREvent_ScrollSmooth ydelta (positive = stick up) -> rows to move the list (negative = toward the top)."""
    return -ydelta * rows_per_unit


def scroll_from_stick(stick_y, dt, rows_per_s=12.0):
    """Right stick up/down held while the panel is open: rows to move this frame."""
    return -_curve(deadzone(stick_y)) * rows_per_s * dt


def resolve_tap(down, up, tol=28.0):
    """down/up = (key, x, y). Taps keep the key pressed down if the pointer moved only a little."""
    if down is None:
        return up[0]
    dk, dx, dy = down
    uk, ux, uy = up
    if uk == dk:
        return uk
    if dk is not None and math.hypot(ux - dx, uy - dy) <= tol:
        return dk
    return None



def dpad_axis(back, fwd):
    """Two D-pad buttons -> -1 / 0 / +1 for SeekRepeater."""
    return (1.0 if fwd else 0.0) - (1.0 if back else 0.0)


class ButtonGate:
    """Filters the boolean actions (seek_back, seek_fwd, play_pause) before they can seek or pause.

    Seen on the Frame (log 16:20:50 / 16:20:53 / 16:20:55): when the Steam button closes the dashboard,
    SteamVR reports EVERY boolean action as active+pressed in the same frame, which looked like a
    play/pause press. So:
      - nothing passes while the dashboard is open, or within SETTLE s of it opening/closing;
      - anything already held when the gate opens counts as held (needs release + a new press);
      - two or more actions pressed at once is not a real press: everything is ignored until all released.
    feed(states, dash_visible, now) -> dict of states that may be used now (all False when blocked).
    """
    SETTLE = 0.6

    def __init__(self, names):
        self.names = tuple(names)
        self.dash = None
        self.since = -1e9
        self.latched = set()   # held when the gate opened (or chorded); ignored until released

    def feed(self, states, dash_visible, now):
        pressed = {n for n in self.names if states.get(n)}
        self.latched &= pressed
        if dash_visible != self.dash:
            self.dash, self.since = dash_visible, now
        if dash_visible or now - self.since < self.SETTLE or len(pressed - self.latched) > 1:
            self.latched |= pressed
            return {n: False for n in self.names}
        return {n: (n in pressed and n not in self.latched) for n in self.names}
