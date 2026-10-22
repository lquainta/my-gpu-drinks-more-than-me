"""Title, class selection, death, victory, high-score and help screens."""

import json
import math
import os
import random
import time

from depths import colors as C
from depths import data

DATA_DIR = os.path.expanduser("~/.depths")
SAVE_PATH = os.path.join(DATA_DIR, "save.pkl")
SCORES_PATH = os.path.join(DATA_DIR, "scores.json")

LOGO = [
    "██████╗ ███████╗██████╗ ████████╗██╗  ██╗███████╗",
    "██╔══██╗██╔════╝██╔══██╗╚══██╔══╝██║  ██║██╔════╝",
    "██║  ██║█████╗  ██████╔╝   ██║   ███████║███████╗",
    "██║  ██║██╔══╝  ██╔═══╝    ██║   ██╔══██║╚════██║",
    "██████╔╝███████╗██║        ██║   ██║  ██║███████║",
    "╚═════╝ ╚══════╝╚═╝        ╚═╝   ╚═╝  ╚═╝╚══════╝",
]

STAIRS = [
    "        ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄        ",
    "      ▄█▀              ▀█▄      ",
    "     █▀    ▄▄▄▄▄▄▄▄▄▄    ▀█     ",
    "    █▌   ▄█▀        ▀█▄   ▐█    ",
    "    █   █▀   ▄▄▄▄▄▄   ▀█   █    ",
    "    █   █   █▀    ▀█   █   █    ",
    "    █   █   █  ▄▄  █   █   █    ",
]

TOMBSTONE = [
    "        _.---------._        ",
    "     .-'             '-.     ",
    "    /                   \\    ",
    "   |      R . I . P .    |   ",
    "   |                     |   ",
    "   |                     |   ",
    "   |                     |   ",
    "   |                     |   ",
    "   |                     |   ",
    "   |                     |   ",
    " __|_____________________|__ ",
    "/___________________________\\",
]

CROWN = [
    "    *       *       *    ",
    "   /█\\     /█\\     /█\\   ",
    "  /███\\___/███\\___/███\\  ",
    "  █████████████████████  ",
    "  █ ◆ ███ ◆ ███ ◆ ███ █  ",
    "  █████████████████████  ",
]

HELP_KEYS = [
    ("Arrows / hjkl yubn", "Move or attack (yubn = diagonals)"),
    (".", "Wait a turn"),
    ("g  or  ,", "Pick up items"),
    ("i", "Inventory: use, equip, drop"),
    ("1 2 3 4", "Use class abilities"),
    ("o", "Auto-explore"),
    (">", "Descend stairs / travel to known stairs"),
    ("r", "Rest until healed"),
    ("x", "Look around"),
    ("c", "Character sheet"),
    ("m", "Message history"),
    ("Esc", "Menu: save & quit"),
    ("In targeting", "Move cursor, Tab cycles foes, Enter fires"),
]

LEGEND = [
    ("@", (255, 248, 225), "You"),
    ("·", (90, 86, 100), "Floor"),
    ("+", (190, 130, 70), "Door"),
    (">", (200, 210, 255), "Stairs down"),
    ("~", (120, 180, 245), "Water"),
    ("≈", (255, 140, 40), "Lava"),
    ("*", (255, 170, 60), "Brazier"),
    ("♦", (190, 120, 255), "Crystal"),
    ("■", (230, 180, 70), "Chest"),
    ("{", (120, 200, 255), "Fountain"),
    ("^", (230, 80, 80), "Trap"),
    ("!", (240, 70, 80), "Potion"),
    ("?", (170, 140, 255), "Scroll"),
    ("/", (255, 100, 40), "Wand"),
    (")", (200, 205, 220), "Weapon"),
    ("[", (180, 185, 195), "Armor"),
    ("=", (140, 200, 255), "Ring"),
    ("$", (255, 215, 60), "Gold"),
]


# --- storage ------------------------------------------------------------------------

def load_scores() -> list[dict]:
    try:
        with open(SCORES_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def record_score(game) -> int:
    """Save a finished run. Returns its 1-based rank."""
    p = game.player
    entry = dict(score=game.score(), cls=p.cls, depth=p.deepest, level=p.level, turns=p.turns,
                 kills=p.kills, gold=p.gold, won=game.won,
                 killed_by="" if game.won else p.killed_by, date=time.strftime("%Y-%m-%d"))
    scores = load_scores() + [entry]
    scores.sort(key=lambda e: -e["score"])
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(SCORES_PATH, "w") as f:
            json.dump(scores[:50], f, indent=1)
    except OSError:
        pass
    return scores.index(entry) + 1


def delete_save() -> None:
    try:
        os.remove(SAVE_PATH)
    except OSError:
        pass


# --- shared backdrop -----------------------------------------------------------------

class Embers:
    """Rising embers for menu backgrounds."""

    def __init__(self, color=(255, 140, 40), rate: float = 30, fall: bool = False):
        self.p = []
        self.rng = random.Random()
        self.color = color
        self.rate = rate
        self.fall = fall

    def update(self, dt, w, h):
        r = self.rng
        for _ in range(int(self.rate * dt) + (r.random() < (self.rate * dt) % 1)):
            if self.fall:
                self.p.append([r.uniform(0, w), -1.0, r.uniform(-0.5, 0.5), r.uniform(1, 3),
                               r.uniform(4, 9), r.choice("·.'")])
            else:
                self.p.append([r.uniform(0, w), h + 0.0, r.uniform(-1, 1), -r.uniform(2, 7),
                               r.uniform(2, 6), r.choice("·.'*")])
        for e in self.p:
            e[0] += (e[2] + math.sin(e[1] * 0.3) * 0.6) * dt
            e[1] += e[3] * dt
            e[4] -= dt
        self.p = [e for e in self.p if e[4] > 0 and -2 < e[1] < h + 1][-400:]

    def draw(self, cv):
        for x, y, _vx, _vy, life, g in self.p:
            k = min(1.0, life / 2)
            xi, yi = int(x), int(y)
            if 0 <= xi < cv.w and 0 <= yi < cv.h:
                cv.put(xi, yi, g, C.mix(cv.get_bg(xi, yi), self.color, k))


def backdrop(cv, now, tint=(18, 8, 6)):
    """A dark radial vignette with a slow breathing glow."""
    cx, cy = cv.w / 2, cv.h * 0.55
    breathe = 0.85 + 0.15 * math.sin(now * 0.8)
    for y in range(cv.h):
        row = y * cv.w
        dy = (y - cy) / (cv.h * 0.7)
        for x in range(cv.w):
            dx = (x - cx) / (cv.w * 0.7)
            k = max(0.0, 1 - math.sqrt(dx * dx + dy * dy * 3)) * breathe
            cv.bg[row + x] = (int(3 + tint[0] * k), int(3 + tint[1] * k), int(6 + tint[2] * k))


# --- screens -------------------------------------------------------------------------

class Screen:
    def __init__(self, app):
        self.app = app

    def accepts_input(self) -> bool:
        return True

    def handle(self, key: str) -> None:
        pass

    def update(self, dt: float, now: float) -> None:
        pass

    def draw(self, cv, now: float) -> None:
        pass


class TitleScreen(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.embers = Embers()
        self.sel = 0
        self.start = time.monotonic()

    def options(self):
        opts = ["New Game"]
        if os.path.exists(SAVE_PATH):
            opts.insert(0, "Continue")
        return opts + ["High Scores", "How to Play", "Quit"]

    def handle(self, key):
        opts = self.options()
        if key in ("up", "k"):
            self.sel = (self.sel - 1) % len(opts)
        elif key in ("down", "j"):
            self.sel = (self.sel + 1) % len(opts)
        elif key in ("enter", "space"):
            choice = opts[self.sel]
            if choice == "Continue":
                self.app.continue_game()
            elif choice == "New Game":
                self.app.set_screen(ClassSelectScreen(self.app))
            elif choice == "High Scores":
                self.app.set_screen(ScoresScreen(self.app))
            elif choice == "How to Play":
                self.app.set_screen(HelpScreen(self.app))
            else:
                self.app.running = False
        elif key in ("q", "esc"):
            self.app.running = False

    def update(self, dt, now):
        self.embers.update(dt, self.app.width, self.app.height)

    def draw(self, cv, now):
        backdrop(cv, now)
        self.embers.draw(cv)
        age = now - self.start
        top = max(1, cv.h // 2 - 12)
        lw = len(LOGO[0])
        x0 = (cv.w - lw) // 2
        for row, line in enumerate(LOGO):
            for i, ch in enumerate(line):
                if ch == " ":
                    continue
                reveal = min(1.0, max(0.0, age * 1.6 - (row * 0.08 + i * 0.006)))
                if reveal <= 0:
                    continue
                heat = 0.5 + 0.5 * math.sin(now * 2.2 - i * 0.18 + row * 0.5)
                base = C.gradient([(255, 236, 160), (255, 150, 40), (200, 50, 20)], row / 5)
                col = C.mix(base, (255, 245, 210), heat * 0.35) if ch == "█" else \
                    C.scale(base, 0.45)
                cv.put(x0 + i, top + row, ch, C.mix(cv.get_bg(x0 + i, top + row), col, reveal))
        sub = "A   D E S C E N T   I N T O   T H E   H O L L O W   K I N G D O M"
        if len(sub) > cv.w - 2:
            sub = "A DESCENT INTO THE HOLLOW KINGDOM"
        cv.center(top + 7, sub, C.mix((10, 8, 10), (190, 160, 130), min(1, max(0, age - 0.8))))
        sy = top + 9
        sx = (cv.w - len(STAIRS[0])) // 2
        for r, line in enumerate(STAIRS):
            depth = r / len(STAIRS)
            for i, ch in enumerate(line):
                if ch != " ":
                    cv.put(sx + i, sy + r, ch, C.mix((90, 70, 60), (20, 14, 16), depth))
        # flickering torches on either side of the stairway
        for tx in (sx - 4, sx + len(STAIRS[0]) + 3):
            f = 0.5 + 0.5 * math.sin(now * 13 + tx) * math.sin(now * 7.1)
            cv.put(tx, sy + 1, "*" if f > 0.3 else "+", C.mix((255, 110, 20), (255, 240, 160), f))
            cv.put(tx, sy + 2, "║", (110, 80, 50))
            cv.put(tx, sy + 3, "║", (90, 60, 40))
        opts = self.options()
        my = sy + len(STAIRS) + 2
        for i, o in enumerate(opts):
            sel = i == self.sel
            label = f"  {o}  "
            if sel:
                glow = 0.5 + 0.5 * math.sin(now * 5)
                label = f"› {o} ‹"
                cv.center(my + i * 2, label, C.mix(C.GOLD, C.WHITE, glow * 0.6), (40, 22, 14))
            else:
                cv.center(my + i * 2, label, (150, 130, 120))
        cv.center(cv.h - 1, "↑↓ choose   Enter select", (90, 80, 80))


class ClassSelectScreen(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.sel = 0
        self.keys = list(data.CLASSES)
        self.embers = Embers(rate=12)

    def handle(self, key):
        if key in ("left", "h"):
            self.sel = (self.sel - 1) % 3
        elif key in ("right", "l", "tab"):
            self.sel = (self.sel + 1) % 3
        elif key in ("1", "2", "3"):
            self.sel = int(key) - 1
        elif key in ("enter", "space"):
            self.app.new_game(self.keys[self.sel])
        elif key in ("esc", "q"):
            self.app.set_screen(TitleScreen(self.app))

    def update(self, dt, now):
        self.embers.update(dt, self.app.width, self.app.height)

    def draw(self, cv, now):
        backdrop(cv, now, (10, 8, 16))
        self.embers.draw(cv)
        cv.center(1, "C H O O S E   Y O U R   P A T H", C.GOLD)
        card_w = min(40, (cv.w - 8) // 3)
        card_h = min(cv.h - 5, 34)
        gap = 2
        total = card_w * 3 + gap * 2
        x0 = (cv.w - total) // 2
        for i, key in enumerate(self.keys):
            d = data.CLASSES[key]
            x = x0 + i * (card_w + gap)
            y = 3
            sel = i == self.sel
            border = C.mix(d["color"], C.WHITE, 0.3 + 0.2 * math.sin(now * 4)) if sel \
                else C.scale(d["color"], 0.35)
            cv.box(x, y, card_w, card_h, border, (16, 14, 24) if sel else (10, 10, 16),
                   heavy=sel, shadow=sel)
            cv.center(y + 1, d["name"].upper(), d["color"] if sel else C.scale(d["color"], 0.6),
                      x0=x, w=card_w)
            for r, line in enumerate(d["art"]):
                bob = 0 if not sel else round(0.5 + 0.5 * math.sin(now * 3))
                cv.center(y + 3 + r - bob + 1, line, C.scale(d["color"], 1.0 if sel else 0.5),
                          x0=x, w=card_w)
            yy = y + 13
            used = cv.wrap(x + 2, yy, card_w - 4, d["desc"], C.UI_TEXT if sel else C.UI_DIM, 4)
            yy += used + 1
            stats = [("HP", d["hp"], 45, (220, 70, 70)), ("MP", d["mp"], 36, (80, 130, 255)),
                     ("ATK", d["atk"], 6, (255, 170, 60)), ("DEF", d["df"], 4, (140, 200, 255)),
                     ("CRIT", d["crit"], 20, (255, 230, 90))]
            for name, v, mx, col in stats:
                cv.text(x + 2, yy, f"{name:<5}", C.UI_DIM)
                cv.bar(x + 8, yy, card_w - 15, v / mx, col if sel else C.scale(col, 0.5), (24, 24, 34))
                cv.text(x + card_w - 6, yy, f"{v:>3}", C.UI_TEXT)
                yy += 1
            yy += 1
            cv.text(x + 2, yy, "Abilities", C.UI_TITLE if sel else C.UI_DIM)
            yy += 1
            for a in d["abilities"]:
                ab = data.ABILITIES[a]
                label = ab["name"] + (f" (Lv {ab['unlock']})" if ab.get("unlock") else "")
                cv.text(x + 3, yy, "• " + label, ab["color"] if sel else C.scale(ab["color"], 0.5),
                        maxw=card_w - 5)
                yy += 1
        cv.center(cv.h - 1, "←→ choose   Enter begin   Esc back", (110, 100, 110))


class ScoresScreen(Screen):
    def handle(self, key):
        self.app.set_screen(TitleScreen(self.app))

    def draw(self, cv, now):
        backdrop(cv, now, (14, 12, 4))
        cv.center(2, "H A L L   O F   L E G E N D S", C.GOLD)
        scores = load_scores()[:15]
        w = min(cv.w - 4, 96)
        x = (cv.w - w) // 2
        cv.box(x, 4, w, len(scores) + 5 if scores else 6, (110, 90, 40), (14, 12, 8))
        header = f"{'#':>3}  {'SCORE':>7}  {'CLASS':<8} {'DEPTH':>5} {'LVL':>4}  FATE"
        cv.text(x + 2, 5, header, C.UI_TITLE)
        if not scores:
            cv.text(x + 2, 7, "No legends yet. The Depths await.", C.UI_DIM)
        for i, s in enumerate(scores):
            fate = "slew the Hollow King" if s["won"] else f"killed by {s['killed_by']}"
            col = C.GOLD if s["won"] else C.gradient([C.WHITE, C.UI_DIM], i / 15)
            line = f"{i + 1:>3}  {s['score']:>7}  {s['cls']:<8} {s['depth']:>5} {s['level']:>4}  {fate}"
            cv.text(x + 2, 7 + i, line, col, maxw=w - 4)
        cv.center(cv.h - 1, "Press any key", (110, 100, 90))


def draw_help(cv, x, y, w, h):
    cv.box(x, y, w, h, C.UI_BORDER, C.UI_PANEL, title="HOW TO PLAY", heavy=True, shadow=True)
    yy = y + 2
    cv.wrap(x + 3, yy, w - 6, "Descend through twelve depths and destroy the Hollow King. "
            "Bump into monsters to attack. Sleeping monsters take a sneak attack.", C.UI_TEXT)
    yy += 3
    col2 = x + 3 + 22
    for k, desc in HELP_KEYS:
        if yy >= y + h - 2:
            break
        cv.text(x + 3, yy, k, C.GOLD)
        cv.text(col2, yy, desc, C.UI_TEXT, maxw=w - 26 - 30)
        yy += 1
    lx = x + w - 28
    ly = y + 5
    cv.text(lx, ly - 1, "LEGEND", C.UI_TITLE)
    for i, (g, col, name) in enumerate(LEGEND):
        if ly + i >= y + h - 1:
            break
        cv.text(lx, ly + i, g, col)
        cv.text(lx + 2, ly + i, name, C.UI_DIM)


class HelpScreen(Screen):
    def handle(self, key):
        self.app.set_screen(TitleScreen(self.app))

    def draw(self, cv, now):
        backdrop(cv, now, (6, 8, 14))
        w, h = min(cv.w - 4, 100), min(cv.h - 2, 28)
        draw_help(cv, (cv.w - w) // 2, (cv.h - h) // 2, w, h)
        cv.center(cv.h - 1, "Press any key", C.UI_DIM)


class DeathScreen(Screen):
    def __init__(self, app, game, rank):
        super().__init__(app)
        self.game = game
        self.rank = rank
        self.ash = Embers((150, 150, 160), rate=18, fall=True)
        self.start = time.monotonic()

    def handle(self, key):
        if time.monotonic() - self.start > 1.0:
            self.app.set_screen(TitleScreen(self.app))

    def update(self, dt, now):
        self.ash.update(dt, self.app.width, self.app.height)

    def draw(self, cv, now):
        backdrop(cv, now, (20, 4, 4))
        self.ash.draw(cv)
        g, p = self.game, self.game.player
        top = max(1, cv.h // 2 - 12)
        x0 = (cv.w - len(TOMBSTONE[0])) // 2
        for r, line in enumerate(TOMBSTONE):
            cv.text(x0, top + r, line, (150, 150, 160))
        inner = [p.cdata["name"], "", f"slain by {p.killed_by}", f"on depth {p.deepest}",
                 f"turn {p.turns}"]
        for i, line in enumerate(inner):
            cv.center(top + 4 + i, line, (210, 205, 200) if i else p.cdata["color"])
        cv.center(top + 14, "Y O U   H A V E   D I E D", C.mix((90, 10, 10), (230, 40, 40),
                                                               0.5 + 0.5 * math.sin(now * 2)))
        stats = f"Level {p.level}   ·   {p.kills} kills   ·   {p.gold} gold   ·   Score {g.score()}"
        cv.center(top + 16, stats, C.UI_TEXT)
        cv.center(top + 18, f"Rank #{self.rank} in the Hall of Legends", C.GOLD)
        cv.center(cv.h - 1, "Press any key", (110, 100, 100))


class VictoryScreen(Screen):
    def __init__(self, app, game, rank):
        super().__init__(app)
        self.game = game
        self.rank = rank
        self.sparks = []
        self.rng = random.Random()
        self.start = time.monotonic()

    def handle(self, key):
        if time.monotonic() - self.start > 1.5:
            self.app.set_screen(TitleScreen(self.app))

    def update(self, dt, now):
        r = self.rng
        if r.random() < dt * 3:
            cx, cy = r.uniform(5, self.app.width - 5), r.uniform(2, self.app.height * 0.5)
            col = r.choice([C.GOLD, C.ORANGE, C.CYAN, C.PINK, C.GREEN, C.WHITE])
            for _ in range(40):
                a = r.uniform(0, math.tau)
                s = r.uniform(4, 16)
                self.sparks.append([cx, cy, math.cos(a) * s, math.sin(a) * s * 0.5,
                                    r.uniform(0.8, 1.6), col])
        for s in self.sparks:
            s[0] += s[2] * dt
            s[1] += s[3] * dt
            s[3] += 6 * dt
            s[2] *= 1 - dt
            s[4] -= dt
        self.sparks = [s for s in self.sparks if s[4] > 0]

    def draw(self, cv, now):
        backdrop(cv, now, (22, 18, 4))
        for x, y, _vx, _vy, life, col in self.sparks:
            cv.put(int(x), int(y), "*" if life > 0.8 else "·", C.mix(cv.get_bg(int(x), int(y)), col,
                                                                      min(1, life)))
        g, p = self.game, self.game.player
        top = max(1, cv.h // 2 - 10)
        x0 = (cv.w - len(CROWN[0])) // 2
        for r, line in enumerate(CROWN):
            for i, ch in enumerate(line):
                if ch != " ":
                    glow = 0.5 + 0.5 * math.sin(now * 3 - i * 0.3)
                    col = (120, 200, 255) if ch == "◆" else C.mix(C.GOLD, (255, 250, 220), glow * 0.6)
                    cv.put(x0 + i, top + r, ch, col)
        cv.center(top + 8, "V I C T O R Y", C.mix(C.GOLD, C.WHITE, 0.5 + 0.5 * math.sin(now * 4)))
        cv.center(top + 10, "The Hollow King is no more. Light returns to the Depths.", C.UI_TEXT)
        cv.center(top + 12, f"The {p.cdata['name']}  ·  Level {p.level}  ·  {p.kills} kills  ·  "
                            f"{p.gold} gold  ·  {p.turns} turns", C.UI_TITLE)
        cv.center(top + 14, f"Score {g.score()}   ·   Rank #{self.rank}", C.GOLD)
        cv.center(cv.h - 1, "Press any key", (120, 110, 90))
