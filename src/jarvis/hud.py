"""A full-screen holographic HUD for the terminal, drawn with raw ANSI truecolor.

A render thread redraws the whole screen ~15 times a second from shared state; a key
thread reads single keypresses. The main loop talks to it through the same methods as
PlainUI.
"""

import _thread
import math
import os
import queue
import random
import select
import subprocess
import sys
import termios
import textwrap
import threading
import time
import tty
from collections import deque

import numpy as np

FPS = 15

# Palette
BG = (2, 7, 15)
BG_SCAN = (4, 12, 23)
SWEEP = (0, 70, 100)
GRID = (12, 38, 52)
CYAN = (0, 200, 255)
CYAN_DIM = (0, 85, 115)
ICE = (190, 240, 255)
WHITE = (240, 252, 255)
GOLD = (255, 186, 64)
RED = (255, 64, 72)
GLITCH = (255, 40, 200)

STATE_COLORS = {
    "booting": CYAN, "standby": CYAN, "listening": (90, 255, 230), "transcribing": ICE,
    "thinking": GOLD, "speaking": CYAN, "error": RED,
}
STATE_SPIN = {
    "booting": 1.5, "standby": 0.25, "listening": 0.7, "transcribing": 1.2,
    "thinking": 2.4, "speaking": 0.8, "error": 0.1,
}
SPINNER = "◐◓◑◒"
BARS = " ▁▂▃▄▅▆▇█"


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


class Canvas:
    """A grid of characters with a foreground color per cell and a background per row."""

    def __init__(self, w: int, h: int, t: float):
        self.w, self.h = w, h
        self.ch = [[" "] * w for _ in range(h)]
        self.fg = [[CYAN] * w for _ in range(h)]
        sweep = (t * 7) % (h + 24) - 12
        self.row_bg = []
        for y in range(h):
            bg = BG_SCAN if y % 2 else BG
            distance = abs(y - sweep)
            if distance < 4:
                bg = mix(bg, SWEEP, 0.28 * (1 - distance / 4))
            self.row_bg.append(bg)
        for y in range(1, h, 3):
            row_ch, row_fg = self.ch[y], self.fg[y]
            for x in range((y // 3) % 2 * 3 + 2, w, 6):
                row_ch[x], row_fg[x] = "·", GRID

    def put(self, x: int, y: int, text: str, fg=CYAN) -> None:
        if not 0 <= y < self.h:
            return
        row_ch, row_fg = self.ch[y], self.fg[y]
        for i, c in enumerate(text):
            if 0 <= x + i < self.w:
                row_ch[x + i], row_fg[x + i] = c, fg

    def clear(self, x: int, y: int, w: int, h: int) -> None:
        for row in range(y, y + h):
            self.put(x, row, " " * w)

    def box(self, x: int, y: int, w: int, h: int, title: str = "", color=CYAN) -> None:
        dim = mix(BG, color, 0.45)
        self.clear(x, y, w, h)
        self.put(x, y, "┏" + "─" * (w - 2) + "┓", dim)
        for row in range(y + 1, y + h - 1):
            self.put(x, row, "│", dim)
            self.put(x + w - 1, row, "│", dim)
        self.put(x, y + h - 1, "┗" + "─" * (w - 2) + "┛", dim)
        for cx, cy, c in ((x, y, "┏━"), (x + w - 2, y, "━┓"),
                          (x, y + h - 1, "┗━"), (x + w - 2, y + h - 1, "━┛")):
            self.put(cx, cy, c, color)
        if title:
            self.put(x + 3, y, f"╸ {title} ╺", color)

    def glitch(self) -> None:
        y = random.randrange(self.h)
        shift = random.choice((-3, -2, 2, 3))
        self.ch[y] = self.ch[y][-shift:] + self.ch[y][:-shift]
        self.fg[y] = [mix(c, GLITCH, 0.35) for c in self.fg[y][-shift:] + self.fg[y][:-shift]]

    def render(self, brightness: float) -> list[str]:
        """One escape-coded string per row, each starting with a cursor move."""
        cache: dict = {}

        def fg_code(c):
            code = cache.get(c)
            if code is None:
                code = cache[c] = "\x1b[38;2;%d;%d;%dm" % tuple(
                    min(255, int(v * brightness)) for v in c)
            return code

        out = []
        for y in range(self.h):
            bg = self.row_bg[y]
            parts = [f"\x1b[{y + 1};1H\x1b[48;2;{bg[0]};{bg[1]};{bg[2]}m"]
            current = None
            row_ch, row_fg = self.ch[y], self.fg[y]
            # Never touch the bottom-right cell; writing it can scroll the screen.
            width = self.w - 1 if y == self.h - 1 else self.w
            for x in range(width):
                if row_fg[x] is not current:
                    current = row_fg[x]
                    parts.append(fg_code(current))
                parts.append(row_ch[x])
            out.append("".join(parts))
        return out


def arc_reactor(rows: int, cols: int, t: float, spin: float, level: float, power: float):
    """Intensity field (0..~1.2) for a rotating arc-reactor style emblem."""
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float32)
    u = (x - (cols - 1) / 2) / (cols / 2)
    v = (y - (rows - 1) / 2) / (rows / 2)
    r = np.sqrt(u * u + v * v)
    turn = (np.arctan2(v, u) / (2 * math.pi)) % 1.0

    # Rings must be at least about a cell thick or they break up into dotted noise.
    cell = 2.0 / rows

    def ring(radius, width):
        return np.exp(-(((r - radius) / max(width, 0.5 * cell)) ** 2))

    phase = t * spin
    outer = ring(0.92, 0.06) * (((turn * 12 + phase * 0.12) % 1) < 0.8) * 0.95
    ticks = ring(0.78, 0.03) * (((turn * 36 - phase * 0.35) % 1) < 0.5) * 0.55
    middle = ring(0.62 + 0.05 * level, 0.05) * (0.45 + 0.55 * np.cos(
        2 * math.pi * (turn * 3 - phase * 0.25)) ** 2)
    inner = ring(0.42, 0.07) * (((turn * 3 + phase * 0.5) % 1) < 0.7) * 0.95
    core = np.clip(1 - r / (0.3 + 0.08 * level), 0, 1) ** 0.9 * (
        0.75 + 0.5 * level + 0.08 * math.sin(t * 3))
    halo = 0.18 * np.exp(-(((r - 0.93) / 0.18) ** 2))
    field = np.maximum.reduce([outer, ticks, middle, inner, core, halo])
    return field * power


class HudUI:
    def __init__(self, info: dict | None = None):
        self.on_interrupt = None
        self.level_source = None  # callable giving the speaker's current loudness
        self.speaking_source = None  # callable: is audio playing right now?
        self._lock = threading.Lock()
        self._t0 = time.monotonic()
        self._state = "booting"
        self._state_since = 0.0
        self._entries: list[dict] = []  # {"who", "text", "shown"}
        self._activity: deque[tuple[str, str]] = deque(maxlen=50)
        self._levels: deque[float] = deque([0.0] * 200, maxlen=200)
        self._mic = 0.0
        self._info = {"turns": 0, "cost": 0.0, **(info or {})}
        self._input_mode = "none"  # none | text | talk_wait | talk_rec
        self._buffer = ""
        self._lines: queue.Queue[str] = queue.Queue()
        self._talk_start = threading.Event()
        self._talk_stop = threading.Event()
        self._running = False
        self._power = "--"
        self._saved_tty = None
        self._saved_stderr = None
        self._prev_rows: list[str] = []
        self._brightness = 1.0

    # --- lifecycle -------------------------------------------------------------

    def start(self) -> None:
        # Library warnings written to stderr would scribble over the HUD.
        log = os.path.expanduser("~/.cache/jarvis/jarvis.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        self._saved_stderr = os.dup(2)
        log_fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        os.dup2(log_fd, 2)
        os.close(log_fd)

        fd = sys.stdin.fileno()
        self._saved_tty = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[2J")  # alt screen, hide cursor
        sys.stdout.flush()
        self._running = True
        for target in (self._render_loop, self._key_loop, self._power_loop):
            threading.Thread(target=target, daemon=True).start()

    def stop(self) -> None:
        if not self._running:
            return
        time.sleep(0.4)  # let the final line finish typing out
        self._running = False
        time.sleep(1.5 / FPS)
        sys.stdout.write("\x1b[0m\x1b[2J\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._saved_tty)
        os.dup2(self._saved_stderr, 2)
        os.close(self._saved_stderr)

    # --- the interface shared with PlainUI ------------------------------------

    def state(self, name: str) -> None:
        with self._lock:
            if name != self._state:
                self._state, self._state_since = name, self._now()

    def info(self, **values) -> None:
        with self._lock:
            self._info.update(values)

    def mic_level(self, rms: float) -> None:
        self._mic = rms

    def system(self, text: str) -> None:
        self._add("system", text)

    def jarvis(self, text: str) -> None:
        self._add("jarvis", text)

    def user(self, text: str) -> None:
        self._add("user", text)

    def reply_begin(self) -> None:
        self._add("jarvis", "")

    def reply_delta(self, text: str) -> None:
        with self._lock:
            self._entries[-1]["text"] += text

    def reply_end(self) -> None:
        with self._lock:
            self._entries[-1]["text"] = self._entries[-1]["text"].strip()

    def tool(self, name: str) -> None:
        with self._lock:
            self._activity.append((time.strftime("%H:%M:%S"), name))

    def error(self, text: str) -> None:
        self._add("error", text)
        self.state("error")

    def notice(self, text: str) -> None:
        self._add("system", text.upper())

    def read_text(self) -> str:
        self._buffer = ""
        self._input_mode = "text"
        try:
            while True:
                try:
                    return self._lines.get(timeout=0.1)
                except queue.Empty:
                    pass
        finally:
            self._input_mode = "none"

    def wait_to_talk(self) -> None:
        self._talk_start.clear()
        self._input_mode = "talk_wait"
        while not self._talk_start.wait(0.1):
            pass

    def talk_finished(self) -> threading.Event:
        self._talk_stop.clear()
        self._input_mode = "talk_rec"
        return self._talk_stop

    # --- internals ---------------------------------------------------------------

    def _now(self) -> float:
        return time.monotonic() - self._t0

    def _add(self, who: str, text: str) -> None:
        with self._lock:
            self._entries.append({"who": who, "text": text, "shown": 0})
            del self._entries[:-200]

    def _key_loop(self) -> None:
        fd = sys.stdin.fileno()
        while self._running:
            if not select.select([fd], [], [], 0.1)[0]:
                continue
            key = os.read(fd, 1).decode(errors="ignore")
            if key == "\x1b":
                # Arrow keys etc. arrive as escape sequences; a lone ESC is a real press.
                if select.select([fd], [], [], 0.03)[0]:
                    os.read(fd, 8)
                    continue
                if self.on_interrupt and self._state in ("thinking", "speaking"):
                    self.on_interrupt()
                continue
            mode = self._input_mode
            if mode == "text":
                if key in ("\r", "\n"):
                    if self._buffer.strip():
                        self._lines.put(self._buffer.strip())
                        self._buffer = ""
                elif key in ("\x7f", "\b"):
                    self._buffer = self._buffer[:-1]
                elif key == "\x04":
                    _thread.interrupt_main()
                elif key.isprintable():
                    self._buffer += key
            elif mode == "talk_wait" and key in (" ", "\r", "\n"):
                self._input_mode = "none"
                self._talk_start.set()
            elif mode == "talk_rec" and key in (" ", "\r", "\n"):
                self._input_mode = "none"
                self._talk_stop.set()
            elif key in ("q", "Q") and mode != "text":
                _thread.interrupt_main()

    def _power_loop(self) -> None:
        while self._running:
            try:
                out = subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                                     text=True, timeout=5).stdout
                pct = next(w for w in out.split() if w.endswith("%;")).rstrip(";")
                self._power = pct + (" AC" if "AC Power" in out else "")
            except (StopIteration, OSError, subprocess.SubprocessError):
                self._power = "N/A"
            for _ in range(300):
                if not self._running:
                    return
                time.sleep(0.1)

    def _render_loop(self) -> None:
        while self._running:
            started = time.monotonic()
            try:
                rows = self._frame()
                if len(rows) != len(self._prev_rows):
                    self._prev_rows = [""] * len(rows)  # resized: redraw everything
                changed = [row for row, prev in zip(rows, self._prev_rows) if row != prev]
                self._prev_rows = rows
                # Synchronized output (?2026) stops terminals that support it from tearing.
                sys.stdout.write("\x1b[?2026h" + "".join(changed) + "\x1b[0m\x1b[?2026l")
                sys.stdout.flush()
            except Exception as exc:  # never let a drawing bug kill the session
                print(f"HUD render error: {exc!r}", file=sys.stderr)
            time.sleep(max(0.0, 1 / FPS - (time.monotonic() - started)))

    def _display_state(self) -> str:
        if self.speaking_source and self.speaking_source():
            return "speaking"
        return self._state

    def _current_level(self, state: str) -> float:
        if state == "speaking" and self.level_source:
            raw = self.level_source() * 5
        elif state == "listening":
            raw = self._mic * 12
        else:
            raw = 0.0
        return min(1.0, raw) ** 0.7

    # --- drawing ----------------------------------------------------------------

    def _frame(self) -> list[str]:
        w, h = os.get_terminal_size()
        t = self._now()
        canvas = Canvas(w, h, t)
        if w < 80 or h < 24:
            message = "ENLARGE DISPLAY, SIR  (80 x 24 MINIMUM)"
            canvas.put(max(0, (w - len(message)) // 2), h // 2, message, CYAN)
            return canvas.render(1.0)

        with self._lock:
            state = self._display_state()
            level = self._current_level(state)
            self._levels.append(level)
            color = STATE_COLORS.get(state, CYAN)

            self._draw_header(canvas, t, color)
            left_w = max(34, min(56, w * 2 // 5))
            self._draw_left(canvas, t, state, level, color, left_w)
            self._draw_right(canvas, t, state, left_w + 2)
            self._draw_footer(canvas, t, state)

        if random.random() < 0.035:
            canvas.glitch()
        # An occasional brief dip in brightness reads as holographic flicker.
        self._brightness = 0.82 + 0.1 * random.random() if random.random() < 0.06 else 1.0
        return canvas.render(self._brightness)

    def _draw_header(self, c: Canvas, t: float, color) -> None:
        title = "J . A . R . V . I . S ."
        shimmer = (t * 14) % (len(title) + 40) - 5
        c.put(2, 0, "◢◤", color)
        for i, ch in enumerate(title):
            glow = max(0.0, 1 - abs(i - shimmer) / 4)
            c.put(5 + i, 0, ch, mix(CYAN, WHITE, glow))
        c.put(6 + len(title), 0, "◥◣", color)
        clock = time.strftime("%a %d %b %Y  ·  %H:%M:%S").upper()
        right = f"MARK VII INTERFACE  ┃  {clock}"
        subtitle = "JUST A RATHER VERY INTELLIGENT SYSTEM"
        if 12 + len(title) + len(subtitle) < c.w - len(right) - 2:
            c.put(10 + len(title), 0, subtitle, CYAN_DIM)
        c.put(c.w - len(right) - 2, 0, right, CYAN_DIM)
        c.put(c.w - len(clock) - 2, 0, clock, ICE)

        pulse = (t * 40) % (c.w + 60) - 30
        for x in range(c.w):
            glow = max(0.0, 1 - abs(x - pulse) / 18)
            c.put(x, 1, "━", mix(mix(BG, CYAN, 0.35), WHITE, glow))

    def _draw_left(self, c: Canvas, t, state, level, color, width) -> None:
        x0, top = 1, 3
        wave_h = 3
        diag_h = 11 if c.h >= 40 else 8
        reactor_h = max(8, c.h - top - wave_h - diag_h - 5)
        c.box(x0, top, width, reactor_h, "ARC CORE", color)

        rows = reactor_h - 2
        cols = min(width - 4, rows * 2 + 1)
        rows = min(rows, cols // 2 + 1)
        boot = min(1.0, (t - 0.2) / 1.8) if t < 2 else 1.0
        field = arc_reactor(rows, cols, t, STATE_SPIN.get(state, 0.5), level, max(0.0, boot))
        rx = x0 + (width - cols) // 2
        ry = top + 1 + (reactor_h - 2 - rows) // 2
        for y in range(rows):
            for x in range(cols):
                v = round(float(field[y, x]) * 12) / 12
                if v < 0.17:
                    continue
                ch = "·" if v < 0.3 else "░" if v < 0.45 else "▒" if v < 0.65 else \
                    "▓" if v < 0.85 else "█"
                fg = mix(BG, color, v / 0.8) if v <= 0.8 else mix(color, WHITE, (v - 0.8) / 0.4)
                c.put(rx + x, ry + y, ch, fg)

        # State label
        y = top + reactor_h
        blink = "◉" if int(t * 2.5) % 2 else "○"
        label = f"{blink}  {state.upper()}"
        if state == "thinking":
            label += "  " + SPINNER[int(t * 8) % 4]
        c.put(x0 + (width - len(label)) // 2, y, label, mix(color, WHITE, 0.25))

        # Waveform
        wave_w = width - 2
        history = list(self._levels)[-wave_w:]
        for i, v in enumerate(history):
            for row in range(wave_h):
                fill = max(0.0, min(1.0, v * wave_h - (wave_h - 1 - row)))
                if fill > 0:
                    ch = BARS[max(1, int(fill * 8))]
                    c.put(x0 + 1 + i, y + 1 + row, ch, mix(CYAN_DIM, mix(color, WHITE, v), 0.4 + v))
                elif row == wave_h - 1:
                    c.put(x0 + 1 + i, y + 1 + row, "▁", mix(BG, CYAN_DIM, 0.6))

        # Diagnostics
        dy = y + wave_h + 2
        c.box(x0, dy, width, c.h - dy - 2, "DIAGNOSTICS", CYAN)
        load = os.getloadavg()[0] / (os.cpu_count() or 1)
        info = self._info
        uptime = int(t)
        lines = [
            ("CORE LOAD", self._meter(load, 10) + f" {min(load, 9.99) * 100:3.0f}%"),
            ("POWER", self._power),
            ("UPLINK", "CLAUDE CODE · " + str(info.get("model") or "DEFAULT").upper()),
            ("VOICE", str(info.get("voice", "-")).upper()),
            ("SESSION", (info.get("session") or "NEW")[:8].upper()),
            ("EXCHANGES", f"{info['turns']}   COST ${info['cost']:.2f}"),
            ("UPTIME", f"{uptime // 3600:02d}:{uptime // 60 % 60:02d}:{uptime % 60:02d}"),
            ("AUDIO IN", self._meter(min(1.0, self._mic * 12) if state == "listening" else 0, 10)),
            ("DIRECTORY", str(info.get("cwd", "")).upper()),
        ]
        for i, (key, value) in enumerate(lines[: c.h - dy - 4]):
            c.put(x0 + 2, dy + 1 + i, f"{key:<10}", CYAN_DIM)
            c.put(x0 + 13, dy + 1 + i, value[: width - 15], ICE)

    @staticmethod
    def _meter(fraction: float, cells: int) -> str:
        filled = round(max(0.0, min(1.0, fraction)) * cells)
        return "▰" * filled + "▱" * (cells - filled)

    def _draw_right(self, c: Canvas, t, state, x0) -> None:
        width = c.w - x0 - 1
        activity_h = 8
        comms_h = c.h - 3 - activity_h - 2
        c.box(x0, 3, width, comms_h, "COMMS", CYAN)
        self._draw_comms(c, t, state, x0 + 2, 4, width - 4, comms_h - 2)

        ay = 3 + comms_h
        c.box(x0, ay, width, activity_h, "SUBSYSTEM ACTIVITY", CYAN)
        recent = list(self._activity)[-(activity_h - 2):]
        if not recent:
            c.put(x0 + 2, ay + 1, "NO ACTIVE OPERATIONS", CYAN_DIM)
        for i, (stamp, name) in enumerate(recent):
            last = i == len(recent) - 1 and state == "thinking"
            marker = SPINNER[int(t * 8) % 4] if last else "▸"
            c.put(x0 + 2, ay + 1 + i, stamp, CYAN_DIM)
            c.put(x0 + 12, ay + 1 + i, f"{marker} {name.upper()}"[: width - 14],
                  GOLD if last else ICE)

    def _draw_comms(self, c: Canvas, t, state, x, y, width, height) -> None:
        labels = {"user": ("YOU", GOLD, WHITE), "jarvis": ("JARVIS", CYAN, ICE),
                  "system": ("»", CYAN_DIM, mix(CYAN_DIM, CYAN, 0.5)),
                  "error": ("!!", RED, RED)}
        lines: list[tuple[str, tuple, str, tuple, int]] = []
        for entry in self._entries:
            # Typewriter effect: reveal a few characters per frame.
            remaining = len(entry["text"]) - entry["shown"]
            if remaining > 0:
                entry["shown"] += max(2, remaining // 6)
            label, label_color, text_color = labels[entry["who"]]
            text = entry["text"][: entry["shown"]]
            if entry["who"] == "jarvis" and not text and state == "thinking":
                text = "processing " + SPINNER[int(t * 8) % 4]
            indent = 2 if entry["who"] == "system" else 9
            wrapped = []
            for para in text.split("\n"):
                wrapped += textwrap.wrap(para, max(10, width - indent)) or [""]
            while len(wrapped) > 1 and not wrapped[-1]:
                wrapped.pop()
            for i, line in enumerate(wrapped):
                lines.append((label if i == 0 else "", label_color, line, text_color, indent))
            if entry["who"] != "system":
                lines.append(("", CYAN, "", CYAN, 0))
        while lines and not lines[-1][2] and not lines[-1][0]:
            lines.pop()
        for row, (label, label_color, line, text_color, indent) in enumerate(lines[-height:]):
            if label:
                c.put(x, y + row, label, label_color)
            c.put(x + indent, y + row, line, text_color)

    def _draw_footer(self, c: Canvas, t, state) -> None:
        y = c.h - 1
        mode = self._input_mode
        cursor = "█" if int(t * 2) % 2 else " "
        if mode == "text":
            prompt = "▶ " + self._buffer[-(c.w - 30):] + cursor
            c.put(2, y, prompt, WHITE)
            hint = "[ENTER] TRANSMIT  [ESC] INTERRUPT"
        elif mode == "talk_wait":
            c.put(2, y, "[SPACE] TALK   [Q] SHUT DOWN", ICE)
            hint = "STANDING BY"
        elif mode == "talk_rec":
            dot = "●" if int(t * 3) % 2 else " "
            c.put(2, y, f"{dot} RECORDING   [SPACE] SEND", RED)
            hint = "CHANNEL OPEN"
        else:
            hint = "[ESC] INTERRUPT" if state in ("thinking", "speaking") else ""
        c.put(c.w - len(hint) - 2, y, hint, CYAN_DIM)
