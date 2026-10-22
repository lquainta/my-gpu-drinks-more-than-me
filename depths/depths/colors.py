"""Color helpers. Colors are (r, g, b) tuples of ints 0-255."""

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREY = (140, 140, 150)
DARK = (8, 8, 14)
RED = (230, 60, 50)
DARK_RED = (120, 20, 20)
ORANGE = (255, 140, 40)
YELLOW = (255, 220, 90)
GOLD = (255, 200, 60)
GREEN = (90, 220, 110)
TEAL = (60, 220, 200)
CYAN = (90, 210, 255)
BLUE = (80, 130, 255)
PURPLE = (180, 100, 255)
PINK = (255, 120, 200)
BROWN = (150, 100, 60)

UI_BORDER = (70, 90, 120)
UI_TITLE = (170, 200, 255)
UI_TEXT = (200, 205, 215)
UI_DIM = (110, 115, 130)
UI_BG = (10, 12, 20)
UI_PANEL = (14, 17, 28)
UI_HIGHLIGHT = (40, 55, 90)


def clamp(v: float, lo: float = 0, hi: float = 255) -> int:
    return int(lo if v < lo else hi if v > hi else v)


def mix(a, b, t: float):
    if t <= 0:
        return a
    if t >= 1:
        return b
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def scale(c, k: float):
    return (clamp(c[0] * k), clamp(c[1] * k), clamp(c[2] * k))


def light(c, l):
    """Multiply a color by an (r, g, b) light level where 1.0 is full brightness."""
    return (clamp(c[0] * l[0]), clamp(c[1] * l[1]), clamp(c[2] * l[2]))


def add(a, b):
    return (clamp(a[0] + b[0]), clamp(a[1] + b[1]), clamp(a[2] + b[2]))


def gradient(stops, t: float):
    """Interpolate along a list of colors, t in 0..1."""
    if t <= 0:
        return stops[0]
    if t >= 1:
        return stops[-1]
    pos = t * (len(stops) - 1)
    i = int(pos)
    return mix(stops[i], stops[i + 1], pos - i)


def grey(c):
    v = (c[0] * 30 + c[1] * 59 + c[2] * 11) // 100
    return (v, v, v)
