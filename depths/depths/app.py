"""The application loop and the in-game screen (input, targeting, inventory, menus)."""

import math
import os
import time

from depths import colors as C
from depths import data
from depths import game as G
from depths import screens as S
from depths.canvas import Canvas
from depths.fov import chebyshev, line
from depths.particles import Effects
from depths.render import SIDEBAR_W, GameView, Layout

FPS = 30

MOVES = {
    "up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0),
    "k": (0, -1), "j": (0, 1), "h": (-1, 0), "l": (1, 0),
    "y": (-1, -1), "u": (1, -1), "b": (-1, 1), "n": (1, 1),
    "home": (-1, -1), "pgup": (1, -1), "end": (-1, 1), "pgdn": (1, 1),
}


class App:
    def __init__(self, term=None):
        self.term = term
        self.running = True
        self.width, self.height = term.size() if term else (120, 40)
        self.screen = S.TitleScreen(self)

    def set_screen(self, screen) -> None:
        self.screen = screen

    def new_game(self, cls: str) -> None:
        S.delete_save()
        self.screen = GameScreen(self, G.Game(cls))

    def continue_game(self) -> None:
        try:
            g = G.load(S.SAVE_PATH)
        except Exception:
            S.delete_save()
            self.screen = S.TitleScreen(self)
            return
        g.msg("Welcome back.", C.UI_TITLE)
        self.screen = GameScreen(self, g)

    def save_and_quit(self, game) -> None:
        os.makedirs(S.DATA_DIR, exist_ok=True)
        G.save(game, S.SAVE_PATH)
        self.screen = S.TitleScreen(self)

    def loop(self) -> None:
        from depths.term import Renderer

        renderer = Renderer(self.term)
        last = time.monotonic()
        while self.running:
            frame_start = time.monotonic()
            dt = min(0.1, frame_start - last)
            last = frame_start
            self.width, self.height = self.term.size()
            if self.screen.accepts_input():
                key = self.term.read_key(0.001)
                while key is not None:
                    self.screen.handle(key)
                    if not self.screen.accepts_input():
                        break
                    key = self.term.read_key(0)
            self.screen.update(dt, frame_start)
            cv = Canvas(self.width, self.height)
            self.screen.draw(cv, frame_start)
            renderer.flush(cv)
            spare = 1 / FPS - (time.monotonic() - frame_start)
            if spare > 0:
                time.sleep(spare)


class GameScreen(S.Screen):
    def __init__(self, app, game: G.Game):
        super().__init__(app)
        self.game = game
        self.view = GameView()
        self.fx = Effects()
        self.mode = "play"
        self.auto = None
        self.auto_next = 0.0
        self.cursor = (0, 0)
        self.pending = None
        self.inv_sel = 0
        self.menu_sel = 0
        self.log_scroll = 0
        self.end_at = None
        self.now = time.monotonic()
        self._absorb()

    # --- plumbing -----------------------------------------------------------------

    def _absorb(self) -> None:
        if self.game.fx:
            self.fx.consume(self.game.fx, self.now, self.game.level.name)
            self.game.fx.clear()

    def accepts_input(self) -> bool:
        # Hold input while a projectile is flying so the player sees it land.
        return not self.fx.busy() and self.end_at is None

    def act(self, fn, *args) -> bool:
        used = fn(*args)
        self._absorb()
        if self.game.dead or self.game.won:
            self.auto = None
            if self.end_at is None:
                self.end_at = self.now + (1.8 if self.game.dead else 3.0)
        return used

    # --- input ----------------------------------------------------------------------

    def handle(self, key: str) -> None:
        if self.auto:
            self.auto = None
            self.game.msg("Stopped.", C.UI_DIM)
            return
        handler = getattr(self, f"_key_{self.mode}")
        handler(key)

    def _key_play(self, key: str) -> None:
        g = self.game
        if key in MOVES:
            self.act(g.move, *MOVES[key])
        elif key in (".", "5", "s"):
            self.act(g.wait)
        elif key in ("g", ","):
            self.act(g.pickup)
        elif key == "i":
            self.mode = "inventory"
            self.inv_sel = 0
        elif key == "c":
            self.mode = "char"
        elif key == "m":
            self.mode = "log"
            self.log_scroll = 0
        elif key == "?":
            self.mode = "help"
        elif key == "esc":
            self.mode = "menu"
            self.menu_sel = 0
        elif key == "x":
            self.mode = "look"
            self.cursor = (g.player.x, g.player.y)
        elif key == ">":
            if g.level.tiles[g.player.y][g.player.x] == 4:
                self.act(g.descend)
            elif g.depth < data.MAX_DEPTH:
                self.auto = ("travel", g.level.down)
        elif key in ("o", "z"):
            self.auto = ("explore",)
        elif key == "r":
            self.auto = ("rest",)
        elif key in ("1", "2", "3", "4"):
            idx = int(key) - 1
            abilities = g.player.all_abilities
            if idx < len(abilities):
                self._start_ability(abilities[idx])
        elif key == "S":
            self.app.save_and_quit(g)

    def _start_ability(self, key: str) -> None:
        g, p = self.game, self.game.player
        a = data.ABILITIES[key]
        if key not in p.abilities:
            g.msg(f"{a['name']} unlocks at level {a.get('unlock')}.", C.UI_DIM)
            return
        if p.mp < a["cost"]:
            g.msg(f"Not enough mana for {a['name']} ({a['cost']} MP).", C.BLUE)
            return
        if a["target"] is None:
            self.act(g.use_ability, key, None)
            return
        radius = 2 if key == "meteor" else 0
        self._begin_target(dict(kind="ability", key=key, radius=radius,
                                range=7 if key == "blink" else None, color=a["color"],
                                want="cell" if a["target"] == "cell" else "enemy"))

    def _begin_target(self, pending: dict) -> None:
        g = self.game
        self.pending = pending
        self.mode = "target"
        foes = g.visible_monsters()
        if pending["want"] == "enemy" and foes:
            self.cursor = (foes[0].x, foes[0].y)
        else:
            self.cursor = (g.player.x, g.player.y)

    def _key_target(self, key: str) -> None:
        g = self.game
        if key in MOVES:
            dx, dy = MOVES[key]
            self.cursor = (self.cursor[0] + dx, self.cursor[1] + dy)
        elif key == "tab":
            foes = g.visible_monsters()
            if foes:
                spots = [(m.x, m.y) for m in foes]
                i = spots.index(self.cursor) + 1 if self.cursor in spots else 0
                self.cursor = spots[i % len(spots)]
        elif key in ("enter", "f", "space", "t"):
            if not self._target_valid():
                g.msg("You can't target that.", C.UI_DIM)
                return
            pend = self.pending
            self.mode = "play"
            self.pending = None
            if pend["kind"] == "ability":
                self.act(g.use_ability, pend["key"], self.cursor)
            else:
                self.act(g.use_item, pend["item"], self.cursor)
        elif key in ("esc", "q"):
            self.mode = "play"
            self.pending = None

    def _target_valid(self) -> bool:
        g, p = self.game, self.game.player
        c = self.cursor
        if c not in g.visible or c == (p.x, p.y):
            return False
        rng = self.pending.get("range")
        return rng is None or chebyshev(p.x, p.y, *c) <= rng

    def _key_look(self, key: str) -> None:
        if key in MOVES:
            dx, dy = MOVES[key]
            self.cursor = (self.cursor[0] + dx, self.cursor[1] + dy)
        elif key == "tab":
            foes = self.game.visible_monsters()
            if foes:
                spots = [(m.x, m.y) for m in foes]
                i = spots.index(self.cursor) + 1 if self.cursor in spots else 0
                self.cursor = spots[i % len(spots)]
        else:
            self.mode = "play"

    def _inv_entries(self):
        p = self.game.player
        eq = [(i, True) for i in p.equipment.values() if i]
        return eq + [(i, False) for i in p.inventory]

    def _key_inventory(self, key: str) -> None:
        g = self.game
        entries = self._inv_entries()
        if key in ("esc", "I"):
            self.mode = "play"
            return
        if not entries:
            return
        self.inv_sel = min(self.inv_sel, len(entries) - 1)
        if key == "up":
            self.inv_sel = (self.inv_sel - 1) % len(entries)
        elif key == "down":
            self.inv_sel = (self.inv_sel + 1) % len(entries)
        elif len(key) == 1 and "a" <= key <= "z":
            idx = ord(key) - ord("a")
            if idx < len(entries):
                self.inv_sel = idx
        elif key == "enter":
            item, _ = entries[self.inv_sel]
            if item.d.get("target"):
                self._begin_target(dict(kind="item", item=item, radius=2 if item.key == "fireball" else 0,
                                        range=None, color=item.d["color"], want="enemy"))
                return
            self.mode = "play"
            self.act(g.use_item, item, None)
        elif key == "D":
            item, _ = entries[self.inv_sel]
            self.mode = "play"
            self.act(g.drop, item)

    def _key_char(self, key: str) -> None:
        self.mode = "play"

    def _key_help(self, key: str) -> None:
        self.mode = "play"

    def _key_log(self, key: str) -> None:
        if key in ("up", "k"):
            self.log_scroll += 1
        elif key in ("down", "j"):
            self.log_scroll = max(0, self.log_scroll - 1)
        else:
            self.mode = "play"

    MENU = ["Resume", "How to Play", "Save & Quit", "Abandon Run"]

    def _key_menu(self, key: str) -> None:
        if key in ("up", "k"):
            self.menu_sel = (self.menu_sel - 1) % len(self.MENU)
        elif key in ("down", "j"):
            self.menu_sel = (self.menu_sel + 1) % len(self.MENU)
        elif key == "esc":
            self.mode = "play"
        elif key in ("enter", "space"):
            choice = self.MENU[self.menu_sel]
            if choice == "Resume":
                self.mode = "play"
            elif choice == "How to Play":
                self.mode = "help"
            elif choice == "Save & Quit":
                self.app.save_and_quit(self.game)
            else:
                self.mode = "confirm"

    def _key_confirm(self, key: str) -> None:
        if key in ("y", "Y"):
            g = self.game
            g.player.killed_by = "giving up"
            g.dead = True
            S.delete_save()
            rank = S.record_score(g)
            self.app.set_screen(S.DeathScreen(self.app, g, rank))
        else:
            self.mode = "menu"

    # --- update -----------------------------------------------------------------------

    def update(self, dt: float, now: float) -> None:
        self.now = now
        self.fx.update(dt, now)
        g = self.game
        if self.end_at is not None and now >= self.end_at:
            S.delete_save()
            rank = S.record_score(g)
            if g.won:
                self.app.set_screen(S.VictoryScreen(self.app, g, rank))
            else:
                self.app.set_screen(S.DeathScreen(self.app, g, rank))
            return
        if self.auto and now >= self.auto_next and not self.fx.busy() and self.mode == "play":
            hp_before = g.player.hp
            kind = self.auto[0]
            if kind == "explore":
                reason = g.explore_step()
            elif kind == "travel":
                reason = g.travel_step(self.auto[1])
                if reason == "arrived":
                    reason = None
                    self.auto = None
                    g.msg("You reach the stairs. Press > to descend.", C.CYAN)
            else:
                reason = g.rest_step()
            self._absorb()
            if reason:
                g.msg(reason, C.UI_DIM)
                self.auto = None
            elif g.player.hp < hp_before:
                self.auto = None
            if g.dead or g.won:
                self.act(lambda: None)
            self.auto_next = now + (0.03 if kind != "rest" else 0.005)

    # --- drawing ----------------------------------------------------------------------

    def draw(self, cv, now: float) -> None:
        L = Layout(cv.w, cv.h)
        if L.too_small:
            S.backdrop(cv, now, (6, 8, 14))
            cv.center(cv.h // 2 - 2, "The Depths need more room.", C.GOLD)
            cv.center(cv.h // 2, "Please enlarge your terminal", C.UI_TEXT)
            cv.center(cv.h // 2 + 1, "to at least 96 x 30.", C.UI_TEXT)
            cv.center(cv.h // 2 + 3, f"(currently {cv.w} x {cv.h})", C.UI_DIM)
            return
        overlay = None
        if self.mode in ("target", "look"):
            overlay = self._overlay()
        self.view.draw(cv, self.game, self.fx, now, overlay)
        L = self.view.layout
        if self.mode == "inventory":
            self._draw_inventory(cv, L, now)
        elif self.mode == "char":
            self._draw_char(cv, L)
        elif self.mode == "help":
            w, h = min(L.map_w - 4, 96), min(L.map_h + 4, 28)
            S.draw_help(cv, (L.map_w - w) // 2, 2, w, h)
        elif self.mode == "log":
            self._draw_log(cv, L)
        elif self.mode in ("menu", "confirm"):
            self._draw_menu(cv, L, now)
        elif self.mode in ("target", "look"):
            self._draw_target_info(cv, L)
        if self.auto:
            label = {"explore": "EXPLORING", "travel": "TRAVELLING", "rest": "RESTING"}[self.auto[0]]
            label = f" {label} · any key to stop "
            cv.text(L.map_x + (L.map_w - len(label)) // 2, L.map_y, label, C.BLACK,
                    C.mix(C.GOLD, C.WHITE, 0.3 + 0.2 * math.sin(now * 5)))

    def _overlay(self) -> dict:
        g, p = self.game, self.game.player
        ov = {"cursor": self.cursor}
        if self.mode == "target":
            ov["path"] = line(p.x, p.y, *self.cursor)[1:-1]
            ov["radius"] = self.pending.get("radius", 0)
            ov["valid"] = self._target_valid()
            ov["path_color"] = C.scale(self.pending.get("color", (90, 110, 180)), 0.6)
        return ov

    def _describe(self, x: int, y: int) -> list[tuple[str, tuple]]:
        g = self.game
        lv = g.level
        out = []
        if not lv.inside(x, y) or not lv.explored[y][x]:
            return [("Unexplored darkness.", C.UI_DIM)]
        if (x, y) == (g.player.x, g.player.y):
            out.append(("You.", C.WHITE))
        m = g.monster_at(x, y)
        if m and (x, y) in g.visible:
            out.append((f"{m.name.capitalize()}  ({m.hp}/{m.max_hp} HP)", m.color))
            out.append((m.d["desc"], C.UI_TEXT))
            st = ", ".join(s for s in m.statuses) or ("asleep" if m.asleep else "")
            if m.asleep and st != "asleep":
                st = "asleep, " + st
            if st:
                out.append((f"Status: {st}", C.UI_DIM))
            n, s, b = m.base_dmg
            out.append((f"Attack {m.atk}  Defense {m.defense}  Damage {n}d{s}+{b}", C.UI_DIM))
        for item in lv.items_at(x, y):
            if (x, y) in g.visible:
                out.append((item.name.capitalize(), item.d["color"]))
        from depths.mapgen import TILES
        tile = TILES[lv.tiles[y][x]][0]
        out.append((f"Terrain: {tile}" + ("" if (x, y) in g.visible else " (remembered)"), C.UI_DIM))
        return out

    def _draw_target_info(self, cv, L) -> None:
        lines = self._describe(*self.cursor)
        if self.mode == "target":
            pend = self.pending
            name = data.ABILITIES[pend["key"]]["name"] if pend["kind"] == "ability" \
                else pend["item"].d["name"]
            head = (f"Targeting: {name}   Enter fire · Tab next foe · Esc cancel", C.GOLD)
        else:
            head = ("Looking   Arrows move · Tab next foe · any other key closes", C.GOLD)
        lines = [head] + lines
        w = min(L.map_w - 4, 74)
        h = 0
        import textwrap
        wrapped = []
        for text, col in lines:
            for part in textwrap.wrap(text, w - 4) or [""]:
                wrapped.append((part, col))
        h = len(wrapped) + 2
        y = L.map_y + L.map_h - h
        cv.box(2, y, w, h, C.UI_BORDER, (12, 14, 24))
        for i, (t, col) in enumerate(wrapped):
            cv.text(4, y + 1 + i, t, col)

    def _draw_inventory(self, cv, L, now) -> None:
        g, p = self.game, self.game.player
        entries = self._inv_entries()
        w = min(L.map_w - 4, 92)
        h = min(L.map_h + 4, max(14, len(entries) + 6))
        x0 = (L.map_w - w) // 2
        y0 = 2
        cv.box(x0, y0, w, h, (110, 90, 50), (16, 14, 12), title="INVENTORY", title_fg=C.GOLD,
               heavy=True, shadow=True)
        list_w = w // 2
        cv.text(x0 + 2, y0 + 1, f"{len(p.inventory)}/{G.INVENTORY_LIMIT} carried   {p.gold} gold",
                C.UI_DIM)
        if not entries:
            cv.text(x0 + 3, y0 + 3, "Your pack is empty.", C.UI_DIM)
        self.inv_sel = min(self.inv_sel, max(0, len(entries) - 1))
        visible_rows = h - 5
        first = max(0, self.inv_sel - visible_rows + 1)
        for row, idx in enumerate(range(first, min(len(entries), first + visible_rows))):
            item, equipped = entries[idx]
            y = y0 + 3 + row
            sel = idx == self.inv_sel
            if sel:
                cv.fill(x0 + 1, y, list_w, 1, " ", None, C.mix((40, 34, 24), (70, 60, 30),
                                                              0.5 + 0.5 * math.sin(now * 4)))
            letter = chr(ord("a") + idx) if idx < 26 else " "
            cv.text(x0 + 2, y, letter, C.GOLD if sel else C.UI_DIM)
            cv.text(x0 + 4, y, item.d["glyph"], item.d["color"])
            label = item.name + (" (equipped)" if equipped else "")
            cv.text(x0 + 6, y, label, C.WHITE if sel else C.UI_TEXT, maxw=list_w - 7)
        # Details pane
        dx = x0 + list_w + 2
        dw = w - list_w - 4
        for yy in range(y0 + 2, y0 + h - 2):
            cv.put(dx - 1, yy, "│", (60, 50, 34))
        if entries:
            item, equipped = entries[self.inv_sel]
            d = item.d
            cv.text(dx + 1, y0 + 3, item.name.upper(), d["color"], maxw=dw - 2)
            yy = y0 + 5
            yy += cv.wrap(dx + 1, yy, dw - 2, d["desc"], C.UI_TEXT, 4) + 1
            if d["kind"] == "weapon":
                n, s = d["dmg"]
                cv.text(dx + 1, yy, f"Damage {n}d{s}{'+' + str(item.enchant) if item.enchant else ''}",
                        C.WHITE)
                cur = p.equipment["weapon"]
                if cur and cur is not item:
                    avg_new = n * (s + 1) / 2 + item.enchant
                    cn, cs = cur.d["dmg"]
                    avg_old = cn * (cs + 1) / 2 + cur.enchant
                    diff = avg_new - avg_old
                    cv.text(dx + 1, yy + 1, f"{'+' if diff >= 0 else ''}{diff:.1f} avg vs current",
                            C.GREEN if diff > 0 else C.RED if diff < 0 else C.UI_DIM)
            elif d["kind"] == "armor":
                cv.text(dx + 1, yy, f"Armor {d['ac'] + item.enchant}", C.WHITE)
                cur = p.equipment["armor"]
                if cur and cur is not item:
                    diff = d["ac"] + item.enchant - cur.d["ac"] - cur.enchant
                    cv.text(dx + 1, yy + 1, f"{'+' if diff >= 0 else ''}{diff} vs current",
                            C.GREEN if diff > 0 else C.RED if diff < 0 else C.UI_DIM)
            elif d["kind"] == "wand":
                cv.text(dx + 1, yy, f"{item.charges} charges", C.WHITE)
            elif item.count > 1:
                cv.text(dx + 1, yy, f"You carry {item.count}.", C.WHITE)
            verb = {"weapon": "wield", "armor": "wear", "ring": "wear", "potion": "drink",
                    "scroll": "read", "wand": "zap"}[d["kind"]]
            if equipped:
                verb = "remove"
            cv.text(dx + 1, y0 + h - 3, f"a-z select  Enter {verb}  D drop  Esc close", C.UI_DIM,
                    maxw=dw - 1)

    def _draw_char(self, cv, L) -> None:
        g, p = self.game, self.game.player
        w, h = min(L.map_w - 4, 70), 22
        x0, y0 = (L.map_w - w) // 2, 2
        cd = p.cdata
        cv.box(x0, y0, w, h, cd["color"], (14, 14, 22), title="CHARACTER", title_fg=cd["color"],
               heavy=True, shadow=True)
        for r, art in enumerate(cd["art"]):
            cv.text(x0 + 3, y0 + 2 + r, art, C.scale(cd["color"], 0.8))
        x = x0 + 18
        n, s, b = p.dmg
        rows = [
            ("Class", cd["name"]), ("Level", f"{p.level}  ({p.xp}/{p.xp_next} XP)"),
            ("Health", f"{p.hp}/{p.max_hp}"), ("Mana", f"{p.mp}/{p.max_mp}"),
            ("Attack", str(p.atk)), ("Defense", f"{p.defense}  (armor {p.armor})"),
            ("Damage", f"{n}d{s}+{b}"), ("Critical", f"{p.crit}%"),
            ("Speed", str(p.speed)), ("Torch", f"{p.torch} tiles"),
            ("Deepest", f"depth {p.deepest}"), ("Kills", str(p.kills)), ("Gold", str(p.gold)),
            ("Turns", str(p.turns)), ("Score", str(g.score())),
        ]
        for i, (k, v) in enumerate(rows):
            cv.text(x, y0 + 2 + i, k, C.UI_DIM)
            cv.text(x + 12, y0 + 2 + i, v, C.WHITE)
        cv.center(y0 + h - 2, "Press any key", C.UI_DIM, x0=x0, w=w)

    def _draw_log(self, cv, L) -> None:
        g = self.game
        w, h = min(L.map_w - 4, 100), L.map_h + 3
        x0, y0 = (L.map_w - w) // 2, 1
        cv.box(x0, y0, w, h, C.UI_BORDER, (10, 11, 18), title="MESSAGE HISTORY", heavy=True,
               shadow=True)
        rows = h - 3
        msgs = g.messages
        end = len(msgs) - self.log_scroll
        self.log_scroll = min(self.log_scroll, max(0, len(msgs) - rows))
        for i, (text, col, turn) in enumerate(msgs[max(0, end - rows):end]):
            cv.text(x0 + 2, y0 + 1 + i, f"{turn:>5}", C.UI_DIM)
            cv.text(x0 + 9, y0 + 1 + i, text, col, maxw=w - 11)
        cv.center(y0 + h - 1, " ↑↓ scroll · any other key closes ", C.UI_DIM, x0=x0, w=w)

    def _draw_menu(self, cv, L, now) -> None:
        w, h = 34, len(self.MENU) * 2 + 4
        x0, y0 = (L.map_w - w) // 2, max(2, L.map_h // 2 - h // 2)
        cv.darken(L.map_x, L.map_y, L.map_w, L.map_h, 0.5)
        cv.box(x0, y0, w, h, C.UI_BORDER, (12, 14, 24), title="PAUSED", heavy=True, shadow=True)
        if self.mode == "confirm":
            cv.center(y0 + 2, "Abandon this run?", C.RED, x0=x0, w=w)
            cv.center(y0 + 4, "It will be lost forever.", C.UI_TEXT, x0=x0, w=w)
            cv.center(y0 + 6, "y  yes      any key  no", C.UI_DIM, x0=x0, w=w)
            return
        for i, opt in enumerate(self.MENU):
            sel = i == self.menu_sel
            label = f"› {opt} ‹" if sel else opt
            col = C.mix(C.GOLD, C.WHITE, 0.3 + 0.3 * math.sin(now * 5)) if sel else C.UI_TEXT
            cv.center(y0 + 2 + i * 2, label, col, x0=x0, w=w)


def main() -> None:
    import sys

    from depths.term import Terminal

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("DEPTHS needs an interactive terminal.")
        return
    with Terminal() as term:
        app = App(term)
        try:
            app.loop()
        except KeyboardInterrupt:
            if isinstance(app.screen, GameScreen) and not app.screen.game.dead:
                G.save(app.screen.game, S.SAVE_PATH)
    print("Thanks for playing DEPTHS.")
