"""Pure panel logic (no OpenVR here, so it is unit-tested): rotation, scrolling, taps. Laser pointer only."""
import math

TURN_STEP = 30.0  # degrees per ◀ / ▶ press on the panel (360 / 180 view)


def wrap_deg(a):
    return (a + 180.0) % 360.0 - 180.0


def scroll_clamp(scroll, n_items, rows):
    return min(max(0.0, float(n_items - rows)), max(0.0, scroll))


def scroll_from_smooth(ydelta, rows_per_unit=6.0):
    """VREvent_ScrollSmooth ydelta (positive = up) -> rows to move the list (negative = toward the top)."""
    return -ydelta * rows_per_unit


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
