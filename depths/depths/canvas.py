"""An off-screen grid of colored characters that screens draw into."""

from depths import colors as C


class Canvas:
    __slots__ = ("w", "h", "ch", "fg", "bg")

    def __init__(self, w: int, h: int, bg=C.DARK):
        self.w, self.h = w, h
        n = w * h
        self.ch = [" "] * n
        self.fg = [C.UI_TEXT] * n
        self.bg = [bg] * n

    def copy(self) -> "Canvas":
        c = Canvas.__new__(Canvas)
        c.w, c.h = self.w, self.h
        c.ch, c.fg, c.bg = self.ch[:], self.fg[:], self.bg[:]
        return c

    def put(self, x: int, y: int, ch: str, fg=None, bg=None) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            i = y * self.w + x
            self.ch[i] = ch
            if fg is not None:
                self.fg[i] = fg
            if bg is not None:
                self.bg[i] = bg

    def get_bg(self, x: int, y: int):
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.bg[y * self.w + x]
        return C.BLACK

    def text(self, x: int, y: int, s: str, fg=C.UI_TEXT, bg=None, maxw: int | None = None) -> int:
        """Draw a string; returns the x just past the end."""
        if maxw is not None and len(s) > maxw:
            s = s[: max(0, maxw - 1)] + "…" if maxw > 0 else ""
        if not 0 <= y < self.h:
            return x + len(s)
        row = y * self.w
        for i, c in enumerate(s):
            xx = x + i
            if 0 <= xx < self.w:
                j = row + xx
                self.ch[j] = c
                self.fg[j] = fg
                if bg is not None:
                    self.bg[j] = bg
        return x + len(s)

    def center(self, y: int, s: str, fg=C.UI_TEXT, bg=None, x0: int = 0, w: int | None = None) -> None:
        w = self.w if w is None else w
        self.text(x0 + (w - len(s)) // 2, y, s, fg, bg)

    def fill(self, x: int, y: int, w: int, h: int, ch: str = " ", fg=None, bg=None) -> None:
        for yy in range(max(0, y), min(self.h, y + h)):
            row = yy * self.w
            for xx in range(max(0, x), min(self.w, x + w)):
                j = row + xx
                self.ch[j] = ch
                if fg is not None:
                    self.fg[j] = fg
                if bg is not None:
                    self.bg[j] = bg

    def darken(self, x: int, y: int, w: int, h: int, k: float) -> None:
        for yy in range(max(0, y), min(self.h, y + h)):
            row = yy * self.w
            for xx in range(max(0, x), min(self.w, x + w)):
                j = row + xx
                self.fg[j] = C.scale(self.fg[j], k)
                self.bg[j] = C.scale(self.bg[j], k)

    def box(self, x: int, y: int, w: int, h: int, fg=C.UI_BORDER, bg=C.UI_PANEL,
            title: str | None = None, title_fg=C.UI_TITLE, heavy: bool = False,
            shadow: bool = False) -> None:
        if shadow:
            self.darken(x + 2, y + 1, w, h, 0.45)
        self.fill(x, y, w, h, " ", fg, bg)
        tl, tr, bl, br, hz, vt = ("╔", "╗", "╚", "╝", "═", "║") if heavy else \
            ("╭", "╮", "╰", "╯", "─", "│")
        self.text(x, y, tl + hz * (w - 2) + tr, fg, bg)
        self.text(x, y + h - 1, bl + hz * (w - 2) + br, fg, bg)
        for yy in range(y + 1, y + h - 1):
            self.put(x, yy, vt, fg, bg)
            self.put(x + w - 1, yy, vt, fg, bg)
        if title:
            t = f" {title} "
            self.text(x + 2, y, t, title_fg, bg)

    def bar(self, x: int, y: int, w: int, frac: float, full, empty, label: str = "",
            label_fg=C.WHITE) -> None:
        """A smooth horizontal bar using eighth-blocks, with a centered label."""
        frac = max(0.0, min(1.0, frac))
        eighths = int(round(frac * w * 8))
        blocks = " ▏▎▍▌▋▊▉█"
        for i in range(w):
            fill = max(0, min(8, eighths - i * 8))
            shade = C.mix(full, C.WHITE, 0.15) if i == 0 else full
            if fill == 8:
                self.put(x + i, y, " ", None, C.mix(shade, C.scale(full, 0.6), i / max(1, w)))
            elif fill == 0:
                self.put(x + i, y, " ", None, empty)
            else:
                self.put(x + i, y, blocks[fill], C.mix(full, C.scale(full, 0.6), i / max(1, w)),
                         empty)
        if label:
            lx = x + (w - len(label)) // 2
            for i, c in enumerate(label):
                if 0 <= lx + i - x < w:
                    self.put(lx + i, y, c, label_fg)

    def wrap(self, x: int, y: int, w: int, text: str, fg=C.UI_TEXT, max_lines: int = 99) -> int:
        """Word-wrap text into a column; returns the number of lines used."""
        import textwrap

        lines = []
        for para in text.split("\n"):
            lines += textwrap.wrap(para, w) or [""]
        for i, line in enumerate(lines[:max_lines]):
            self.text(x, y + i, line, fg)
        return min(len(lines), max_lines)
