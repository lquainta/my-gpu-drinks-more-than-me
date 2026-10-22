"""Raw terminal handling: alternate screen, key reading, and diffed truecolor output."""

import os
import select
import shutil
import sys
import termios
import tty

from depths.canvas import Canvas

_SEQUENCES = {
    "A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end",
    "1~": "home", "7~": "home", "4~": "end", "8~": "end", "5~": "pgup", "6~": "pgdn",
    "Z": "shift-tab", "3~": "delete",
}
_SIMPLE = {"\r": "enter", "\n": "enter", "\x7f": "backspace", "\x08": "backspace",
           "\t": "tab", " ": "space"}


class Terminal:
    """Context manager that puts the terminal into a full-screen, unbuffered mode."""

    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.out = sys.stdout
        self._pending = b""
        self._saved = None

    def __enter__(self):
        self._saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        # Alternate screen, hide cursor, disable line wrap (so the last cell is safe).
        self.write("\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[2J")
        return self

    def __exit__(self, *exc):
        self.write("\x1b[0m\x1b[2J\x1b[?7h\x1b[?25h\x1b[?1049l")
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)
        return False

    def write(self, s: str) -> None:
        self.out.write(s)
        self.out.flush()

    def size(self) -> tuple[int, int]:
        size = shutil.get_terminal_size((120, 40))
        return size.columns, size.lines

    def read_key(self, timeout: float) -> str | None:
        """Return the next key name, or None if nothing arrives within `timeout`."""
        if not self._pending:
            if not select.select([self.fd], [], [], timeout)[0]:
                return None
            self._pending += os.read(self.fd, 256)
        return self._parse()

    def _parse(self) -> str | None:
        b = self._pending
        if b[:1] == b"\x1b":
            if len(b) == 1 and select.select([self.fd], [], [], 0.02)[0]:
                self._pending += os.read(self.fd, 256)
                b = self._pending
            if len(b) == 1:
                self._pending = b""
                return "esc"
            if b[1:2] in (b"[", b"O"):
                j = 2
                while j < len(b) and not 0x40 <= b[j] <= 0x7E:
                    j += 1
                if j >= len(b):
                    self._pending = b""
                    return None
                seq = b[2:j + 1].decode(errors="ignore")
                self._pending = b[j + 1:]
                return _SEQUENCES.get(seq)
            self._pending = b[1:]
            return "esc"
        for n in range(1, 5):
            try:
                ch = b[:n].decode()
            except UnicodeDecodeError:
                continue
            self._pending = b[n:]
            return _SIMPLE.get(ch, ch)
        self._pending = b[1:]
        return None


class Renderer:
    """Writes a Canvas to the terminal, sending only cells that changed."""

    def __init__(self, terminal: Terminal):
        self.term = terminal
        self.prev: Canvas | None = None
        self._fg_cache: dict = {}
        self._bg_cache: dict = {}

    def invalidate(self) -> None:
        self.prev = None

    def _fg(self, c):
        s = self._fg_cache.get(c)
        if s is None:
            s = self._fg_cache[c] = "\x1b[38;2;%d;%d;%dm" % c
        return s

    def _bg(self, c):
        s = self._bg_cache.get(c)
        if s is None:
            s = self._bg_cache[c] = "\x1b[48;2;%d;%d;%dm" % c
        return s

    def flush(self, cv: Canvas) -> None:
        prev = self.prev
        full = prev is None or prev.w != cv.w or prev.h != cv.h
        parts = ["\x1b[?2026h"]
        if full:
            parts.append("\x1b[0m\x1b[2J")
        w = cv.w
        ch, fg, bg = cv.ch, cv.fg, cv.bg
        if not full:
            pch, pfg, pbg = prev.ch, prev.fg, prev.bg
        cur_fg = cur_bg = None
        cursor = -1
        for i in range(w * cv.h):
            c = ch[i]
            f = fg[i]
            b = bg[i]
            if not full and c == pch[i] and b == pbg[i] and (f == pfg[i] or c == " "):
                continue
            if cursor != i:
                parts.append("\x1b[%d;%dH" % (i // w + 1, i % w + 1))
            if b != cur_bg:
                parts.append(self._bg(b))
                cur_bg = b
            if c != " " and f != cur_fg:
                parts.append(self._fg(f))
                cur_fg = f
            parts.append(c)
            cursor = i + 1 if (i + 1) % w else -1
        parts.append("\x1b[?2026l")
        self.term.write("".join(parts))
        self.prev = cv.copy()
