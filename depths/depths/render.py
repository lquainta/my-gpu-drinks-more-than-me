"""Draws the game: the lit map, creatures, effects, sidebar, minimap and message log."""

import math

from depths import colors as C
from depths import data
from depths.fov import chebyshev
from depths.mapgen import (BRAZIER, CRYSTAL, DEEP_WATER, FLOOR, FOUNTAIN, LAVA, MUSHROOM,
                           STAIRS_DOWN, THRONE, TILES, WALL, WATER)

SIDEBAR_W = 32
LOG_H = 7
UNSEEN = (4, 4, 8)

# Cell kinds in the cached base layer
K_VOID, K_WALL, K_FLAT, K_GLOW, K_WATER, K_DEEP, K_LAVA = range(7)


class Layout:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.map_x, self.map_y = 0, 1
        self.map_w = w - SIDEBAR_W
        self.map_h = h - LOG_H - 1
        self.side_x = w - SIDEBAR_W
        self.log_y = h - LOG_H

    @property
    def too_small(self) -> bool:
        return self.w < 96 or self.h < 30


class GameView:
    def __init__(self):
        self._base_key = None
        self._light_key = None
        self.light = {}
        self.cam = (0, 0)
        self.layout = Layout(120, 40)

    # --- caches ---------------------------------------------------------------------

    def _build_base(self, lv) -> None:
        b = data.BIOMES[lv.biome]
        wall, floor, fglyph = b["wall"], b["floor"], b["floor_glyph"]
        W, H = lv.w, lv.h
        kind = [[K_VOID] * W for _ in range(H)]
        glyph = [[" "] * W for _ in range(H)]
        fg = [[C.BLACK] * W for _ in range(H)]
        bg = [[UNSEEN] * W for _ in range(H)]
        mglyph = [[" "] * W for _ in range(H)]
        mfg = [[UNSEEN] * W for _ in range(H)]
        mbg = [[UNSEEN] * W for _ in range(H)]
        tiles = lv.tiles
        for y in range(H):
            for x in range(W):
                t = tiles[y][x]
                n = lv.noise[y][x]
                floor_bg = C.scale(floor, 0.7 + 0.6 * n)
                mem_floor = C.scale((9, 10, 16), 0.85 + 0.3 * n)
                if t == WALL:
                    face = any(0 <= x + dx < W and 0 <= y + dy < H and tiles[y + dy][x + dx] != WALL
                               for dx in (-1, 0, 1) for dy in (-1, 0, 1))
                    if not face:
                        continue
                    kind[y][x] = K_WALL
                    base = C.scale(wall, 0.72 + 0.55 * n)
                    bg[y][x] = base
                    if n > 0.74:
                        glyph[y][x] = "░"
                        fg[y][x] = C.scale(base, 0.72)
                    mbg[y][x] = C.scale((26, 28, 40), 0.8 + 0.4 * n)
                    continue
                mbg[y][x] = mem_floor
                if t == FLOOR:
                    kind[y][x] = K_FLAT
                    bg[y][x] = floor_bg
                    if n > 0.52:
                        glyph[y][x] = "·"
                        fg[y][x] = C.scale(fglyph, 0.6 + 0.6 * n)
                        mglyph[y][x] = "·"
                        mfg[y][x] = (30, 34, 48)
                    continue
                name, g, tfg, _walk, _tr, light = TILES[t]
                glyph[y][x] = g
                fg[y][x] = tfg or fglyph
                bg[y][x] = floor_bg
                mglyph[y][x] = g
                mfg[y][x] = C.scale(C.mix(C.grey(tfg or fglyph), (80, 90, 130), 0.4), 0.5)
                if t == WATER:
                    kind[y][x] = K_WATER
                elif t == DEEP_WATER:
                    kind[y][x] = K_DEEP
                elif t == LAVA:
                    kind[y][x] = K_LAVA
                    mfg[y][x] = (90, 40, 20)
                elif light:
                    kind[y][x] = K_GLOW
                else:
                    kind[y][x] = K_FLAT
        self.kind, self.glyph, self.fg, self.bg = kind, glyph, fg, bg
        self.mglyph, self.mfg, self.mbg = mglyph, mfg, mbg
        self._base_key = (id(lv), lv.version)

    def _build_light(self, game) -> None:
        lv, p = game.level, game.player
        b = data.BIOMES[lv.biome]
        ar, ag, ab = b["ambient"]
        tr, tg, tb = b["torch"]
        radius = p.torch + 0.5
        static = lv.static_light
        px, py = p.x, p.y
        light = {}
        for x, y in game.visible:
            s = static[y][x]
            d = math.sqrt((x - px) ** 2 + (y - py) ** 2)
            k = 1 - d / radius
            k = k * k * 1.35 if k > 0 else 0.0
            light[(x, y)] = (ar + s[0] + tr * k, ag + s[1] + tg * k, ab + s[2] + tb * k)
        # Glowing and burning creatures light their surroundings.
        sources = []
        for m in lv.monsters:
            if (m.x, m.y) not in game.visible and chebyshev(m.x, m.y, px, py) > 14:
                continue
            g = m.d.get("glow")
            if g:
                sources.append((m.x, m.y, g[0], g[1]))
            if m.has("burning"):
                sources.append((m.x, m.y, (0.9, 0.4, 0.1), 3))
        if p.has("burning"):
            sources.append((px, py, (0.9, 0.4, 0.1), 3))
        for sx, sy, (r, g, bl), rad in sources:
            for y in range(sy - rad, sy + rad + 1):
                for x in range(sx - rad, sx + rad + 1):
                    cur = light.get((x, y))
                    if cur is None:
                        continue
                    d = math.sqrt((x - sx) ** 2 + (y - sy) ** 2)
                    if d > rad:
                        continue
                    k = (1 - d / (rad + 0.5)) ** 1.5
                    light[(x, y)] = (cur[0] + r * k, cur[1] + g * k, cur[2] + bl * k)
        self.light = light
        self._light_key = (id(lv), lv.version, p.turns, px, py, len(lv.monsters))

    # --- main entry -----------------------------------------------------------------

    def draw(self, cv, game, fx, now: float, overlay: dict | None = None) -> None:
        L = self.layout = Layout(cv.w, cv.h)
        lv, p = game.level, game.player
        if self._base_key != (id(lv), lv.version):
            self._build_base(lv)
        if self._light_key != (id(lv), lv.version, p.turns, p.x, p.y, len(lv.monsters)):
            self._build_light(game)
        vw, vh = L.map_w, L.map_h
        cx = p.x - vw // 2
        cy = p.y - vh // 2
        if lv.w <= vw:
            cx = (lv.w - vw) // 2
        else:
            cx = max(0, min(lv.w - vw, cx))
        if lv.h <= vh:
            cy = (lv.h - vh) // 2
        else:
            cy = max(0, min(lv.h - vh, cy))
        sx, sy = fx.shake_offset(now)
        cx += sx
        cy += sy
        self.cam = (cx, cy)
        self._draw_map(cv, game, fx, now, cx, cy)
        self._draw_entities(cv, game, fx, now, cx, cy)
        self._draw_effects(cv, game, fx, now, cx, cy)
        if overlay:
            self._draw_overlay(cv, game, overlay, now, cx, cy)
        self._draw_banner(cv, fx, now)
        self._draw_topbar(cv, game, now)
        self._draw_sidebar(cv, game, now)
        self._draw_log(cv, game)

    # --- map --------------------------------------------------------------------------

    def _draw_map(self, cv, game, fx, now, cx, cy) -> None:
        L = self.layout
        lv = game.level
        W = cv.w
        vis = game.visible
        light = self.light
        explored = lv.explored
        kind, glyph, fgs, bgs = self.kind, self.glyph, self.fg, self.bg
        mglyph, mfg, mbg = self.mglyph, self.mfg, self.mbg
        flick = 0.94 + 0.04 * math.sin(now * 11.0) + 0.03 * math.sin(now * 17.3 + 1.7)
        dyn = {}
        for x0, y0, (r, g, b), rad in fx.lights(now):
            for y in range(y0 - rad, y0 + rad + 1):
                for x in range(x0 - rad, x0 + rad + 1):
                    d = math.sqrt((x - x0) ** 2 + (y - y0) ** 2)
                    if d <= rad and (x, y) in vis:
                        k = (1 - d / (rad + 0.5)) ** 1.5
                        o = dyn.get((x, y), (0, 0, 0))
                        dyn[(x, y)] = (o[0] + r * k, o[1] + g * k, o[2] + b * k)
        ch_out, fg_out, bg_out = cv.ch, cv.fg, cv.bg
        mw, mh = lv.w, lv.h
        rng_r = fx.rng.random
        dt_rate = 1 / 20
        for vy in range(L.map_h):
            my = cy + vy
            row = (L.map_y + vy) * W + L.map_x
            if not 0 <= my < mh:
                for vx in range(L.map_w):
                    ch_out[row + vx] = " "
                    bg_out[row + vx] = UNSEEN
                continue
            krow, grow, frow, brow = kind[my], glyph[my], fgs[my], bgs[my]
            erow = explored[my]
            for vx in range(L.map_w):
                mx = cx + vx
                i = row + vx
                if not 0 <= mx < mw:
                    ch_out[i] = " "
                    bg_out[i] = UNSEEN
                    continue
                if (mx, my) in vis:
                    l0, l1, l2 = light.get((mx, my), (0.1, 0.1, 0.1))
                    l0 *= flick
                    l1 *= flick
                    l2 *= flick
                    d = dyn.get((mx, my)) if dyn else None
                    if d:
                        l0 += d[0]
                        l1 += d[1]
                        l2 += d[2]
                    k = krow[mx]
                    if k == K_WALL or k == K_FLAT:
                        b = brow[mx]
                        f = frow[mx]
                        bg_out[i] = (min(255, int(b[0] * l0)), min(255, int(b[1] * l1)),
                                     min(255, int(b[2] * l2)))
                        ch_out[i] = grow[mx]
                        fg_out[i] = (min(255, int(f[0] * (l0 + 0.15))),
                                     min(255, int(f[1] * (l1 + 0.15))),
                                     min(255, int(f[2] * (l2 + 0.15))))
                    elif k == K_GLOW:
                        b = brow[mx]
                        f = frow[mx]
                        t = lv.tiles[my][mx]
                        pulse = 0.5 + 0.5 * math.sin(now * 3 + mx * 1.3 + my)
                        if t == BRAZIER:
                            f = C.mix((255, 120, 30), (255, 230, 140), pulse)
                            ch_out[i] = "*" if pulse > 0.25 else "+"
                            if rng_r() < dt_rate * 0.8:
                                fx.emit_ambient(mx, my, "spark")
                        elif t == MUSHROOM:
                            f = C.mix(f, (200, 255, 240), pulse * 0.4)
                            ch_out[i] = grow[mx]
                            if rng_r() < dt_rate * 0.08:
                                fx.emit_ambient(mx, my, "spore")
                        elif t == CRYSTAL:
                            f = C.mix(f, (240, 210, 255), pulse * 0.5)
                            ch_out[i] = grow[mx]
                            if rng_r() < dt_rate * 0.1:
                                fx.emit_ambient(mx, my, "mote")
                        elif t == STAIRS_DOWN:
                            f = C.mix((150, 170, 255), (255, 255, 255), pulse)
                            ch_out[i] = ">"
                        elif t == FOUNTAIN:
                            ch_out[i] = grow[mx]
                            if rng_r() < dt_rate * 0.3:
                                fx.emit_ambient(mx, my, "drip")
                        else:
                            ch_out[i] = grow[mx]
                        fg_out[i] = f
                        bg_out[i] = (min(255, int(b[0] * l0)), min(255, int(b[1] * l1)),
                                     min(255, int(b[2] * l2)))
                    elif k == K_LAVA:
                        w = 0.5 + 0.35 * math.sin(now * 1.7 + mx * 0.55 + my * 0.8) + \
                            0.15 * math.sin(now * 3.1 - mx * 0.9 + my * 0.3)
                        bg_out[i] = (int(140 + 90 * w), int(28 + 50 * w), int(6 + 10 * w))
                        ch_out[i] = "≈" if w > 0.68 else "~" if w > 0.42 else " "
                        fg_out[i] = (255, int(170 + 70 * w), int(60 + 60 * w))
                        if rng_r() < dt_rate * 0.03:
                            fx.emit_ambient(mx, my, "ember")
                    else:
                        w = math.sin(now * 2.0 + mx * 0.7 + my * 0.45)
                        if k == K_WATER:
                            base = (20 + 6 * w, 48 + 10 * w, 92 + 16 * w)
                            ch_out[i] = "~" if w > 0.35 else " "
                            fcol = (120, 180, 245)
                        else:
                            base = (10 + 4 * w, 24 + 8 * w, 66 + 14 * w)
                            ch_out[i] = "≈" if w > 0.6 else " "
                            fcol = (80, 130, 230)
                        lw0, lw1, lw2 = l0 + 0.25, l1 + 0.25, l2 + 0.25
                        bg_out[i] = (min(255, int(base[0] * lw0)), min(255, int(base[1] * lw1)),
                                     min(255, int(base[2] * lw2)))
                        fg_out[i] = (min(255, int(fcol[0] * lw0)), min(255, int(fcol[1] * lw1)),
                                     min(255, int(fcol[2] * lw2)))
                elif erow[mx]:
                    ch_out[i] = mglyph[my][mx]
                    fg_out[i] = mfg[my][mx]
                    bg_out[i] = mbg[my][mx]
                else:
                    ch_out[i] = " "
                    bg_out[i] = UNSEEN

    def to_screen(self, x, y):
        L = self.layout
        sx = round(x) - self.cam[0]
        sy = round(y) - self.cam[1]
        if 0 <= sx < L.map_w and 0 <= sy < L.map_h:
            return L.map_x + sx, L.map_y + sy
        return None

    def _draw_entities(self, cv, game, fx, now, cx, cy) -> None:
        lv, p = game.level, game.player
        vis = game.visible
        for item in lv.items:
            if (item.x, item.y) in vis:
                s = self.to_screen(item.x, item.y)
                if s:
                    c = item.d["color"]
                    if item.d["kind"] in ("ring", "wand", "gold"):
                        c = C.mix(c, C.WHITE, 0.25 + 0.25 * math.sin(now * 4 + item.x))
                    cv.put(s[0], s[1], item.d["glyph"], c)
        for m in lv.monsters:
            if (m.x, m.y) not in vis or not m.alive:
                continue
            s = self.to_screen(m.x, m.y)
            if not s:
                continue
            color = m.color
            bg = None
            if m.asleep:
                color = C.scale(color, 0.6)
                if fx.rng.random() < 0.015:
                    fx.emit_ambient(m.x, m.y, "sleep")
            if m.has("frozen"):
                bg = (50, 110, 170)
            elif m.has("burning"):
                bg = C.mix((150, 40, 0), (230, 110, 20), 0.5 + 0.5 * math.sin(now * 14))
            elif m.has("marked"):
                bg = C.mix((70, 0, 10), (150, 10, 30), 0.5 + 0.5 * math.sin(now * 6))
            elif m.has("stunned") or m.has("confused"):
                color = C.mix(color, C.PINK, 0.5 + 0.5 * math.sin(now * 8))
            if m.key == "king":
                color = C.mix(color, C.WHITE, 0.3 + 0.3 * math.sin(now * 3))
            if fx.hit_until.get(m.id, 0) > now:
                bg = (220, 50, 40)
                color = C.WHITE
            cv.put(s[0], s[1], m.glyph, color, bg)
        s = self.to_screen(p.x, p.y)
        if s:
            color = (255, 248, 225)
            bg = None
            if fx.hit_until.get(p.id, 0) > now:
                bg, color = (200, 30, 30), C.WHITE
            elif p.has("frozen"):
                bg = (50, 110, 170)
            elif p.has("burning"):
                bg = C.mix((150, 40, 0), (230, 110, 20), 0.5 + 0.5 * math.sin(now * 14))
            elif p.has("haste"):
                color = C.mix(color, C.YELLOW, 0.5 + 0.5 * math.sin(now * 10))
            elif p.has("rage"):
                color = C.mix(color, C.RED, 0.5 + 0.5 * math.sin(now * 7))
            cv.put(s[0], s[1], "@", color, bg)

    def _draw_effects(self, cv, game, fx, now, cx, cy) -> None:
        vis = game.visible
        for p in fx.particles:
            cell = (round(p.x), round(p.y))
            if cell not in vis:
                continue
            s = self.to_screen(*cell)
            if s:
                t = p.life / p.max_life
                cv.put(s[0], s[1], p.glyph, C.mix(p.end, p.color, t))
        for b in fx.blasts:
            age = now - b["start"]
            k = 1 - age / b["life"]
            r = b["radius"]
            rr = (r + 0.5) * min(1.0, age / (b["life"] * 0.45))
            for y in range(b["y"] - r - 1, b["y"] + r + 2):
                for x in range(b["x"] - r - 1, b["x"] + r + 2):
                    if (x, y) not in vis:
                        continue
                    d = math.sqrt((x - b["x"]) ** 2 + (y - b["y"]) ** 2)
                    s = self.to_screen(x, y)
                    if not s:
                        continue
                    if b["ring"]:
                        if abs(d - rr) < 0.7:
                            cv.put(s[0], s[1], "o" if d > 0.5 else "*",
                                   C.mix(b["color"], C.WHITE, 0.4 * k),
                                   C.mix(cv.get_bg(*s), C.scale(b["color"], 0.6), k * 0.7))
                    elif d <= rr:
                        heat = (1 - d / (r + 1)) * k
                        col = C.gradient([C.scale(b["color"], 0.3), b["color"], (255, 250, 220)], heat)
                        cv.put(s[0], s[1], "*" if heat > 0.55 else "·" if heat > 0.25 else " ",
                               C.mix(col, C.WHITE, 0.3), C.mix(cv.get_bg(*s), col, min(1, heat * 1.3)))
        for b in fx.beams:
            k = 1 - (now - b["start"]) / b["life"]
            for x, y in b["path"]:
                s = self.to_screen(x, y)
                if s and (x, y) in vis:
                    cv.put(s[0], s[1], fx.rng.choice("~-*≈"), C.mix(b["color"], C.WHITE, 0.5),
                           C.mix(cv.get_bg(*s), C.scale(b["color"], 0.7), k))
        for b in fx.bolts:
            i = int((now - b["start"]) * b["speed"])
            path = b["path"]
            for j in range(max(0, i - 3), min(i + 1, len(path))):
                x, y = path[j]
                s = self.to_screen(x, y)
                if not s:
                    continue
                fade = (j - i + 4) / 4
                glyph = b["glyph"] if j == i else "·"
                cv.put(s[0], s[1], glyph, C.mix(C.scale(b["color"], 0.3), C.mix(b["color"], C.WHITE, 0.3), fade))
        for x, y, text, color, age, life in fx.texts:
            s = self.to_screen(x, y - age * 1.8)
            if s:
                k = 1 - max(0.0, age - life * 0.6) / (life * 0.4)
                c = C.mix(C.scale(color, 0.2), color, k)
                cv.text(s[0] - len(text) // 2, s[1], text, c)
        if fx.flash_color and now < fx.flash_until:
            k = (fx.flash_until - now) / 0.35 * 0.45
            L = self.layout
            for y in range(L.map_y, L.map_y + L.map_h):
                row = y * cv.w
                for x in range(L.map_x, L.map_x + L.map_w):
                    i = row + x
                    cv.bg[i] = C.mix(cv.bg[i], fx.flash_color, k)

    def _draw_overlay(self, cv, game, ov, now, cx, cy) -> None:
        cursor = ov.get("cursor")
        if not cursor:
            return
        pulse = 0.5 + 0.5 * math.sin(now * 8)
        for x, y in ov.get("path", []):
            s = self.to_screen(x, y)
            if s:
                cv.put(s[0], s[1], cv.ch[s[1] * cv.w + s[0]], None,
                       C.mix(cv.get_bg(*s), ov.get("path_color", (70, 90, 160)), 0.55))
        radius = ov.get("radius", 0)
        if radius:
            for y in range(cursor[1] - radius, cursor[1] + radius + 1):
                for x in range(cursor[0] - radius, cursor[0] + radius + 1):
                    s = self.to_screen(x, y)
                    if s:
                        cv.put(s[0], s[1], cv.ch[s[1] * cv.w + s[0]], None,
                               C.mix(cv.get_bg(*s), (160, 70, 30), 0.35))
        s = self.to_screen(*cursor)
        if s:
            ok = ov.get("valid", True)
            col = (230, 220, 90) if ok else (220, 60, 60)
            cv.put(s[0], s[1], cv.ch[s[1] * cv.w + s[0]], C.BLACK,
                   C.mix(C.scale(col, 0.5), col, pulse))

    def _draw_banner(self, cv, fx, now) -> None:
        if not fx.banner:
            return
        title, sub, start = fx.banner
        age = now - start
        k = min(1.0, age / 0.5) * min(1.0, (3.2 - age) / 0.8)
        if k <= 0:
            return
        L = self.layout
        y = L.map_y + L.map_h // 4
        spaced = "  ".join(title)
        w = max(len(spaced), len(sub)) + 12
        x0 = L.map_x + (L.map_w - w) // 2
        for yy in range(y - 1, y + 4):
            for xx in range(x0, x0 + w):
                if 0 <= xx < cv.w and 0 <= yy < cv.h:
                    i = yy * cv.w + xx
                    edge = min(xx - x0, x0 + w - 1 - xx) / 6
                    cv.bg[i] = C.mix(cv.bg[i], (0, 0, 0), 0.75 * k * min(1, edge))
                    cv.fg[i] = C.mix(cv.fg[i], (0, 0, 0), 0.75 * k * min(1, edge))
        shimmer = (age * 14) % (len(spaced) + 10)
        for i, ch in enumerate(spaced):
            glow = max(0.0, 1 - abs(i - shimmer) / 3)
            c = C.mix(C.GOLD, C.WHITE, glow)
            cv.put(L.map_x + (L.map_w - len(spaced)) // 2 + i, y, ch, C.mix(UNSEEN, c, k))
        line = "─" * (len(sub) + 4)
        cv.center(y + 1, line, C.mix(UNSEEN, (120, 100, 60), k), x0=L.map_x, w=L.map_w)
        cv.center(y + 2, sub, C.mix(UNSEEN, C.UI_TITLE, k), x0=L.map_x, w=L.map_w)

    # --- chrome -----------------------------------------------------------------------

    def _draw_topbar(self, cv, game, now) -> None:
        cv.fill(0, 0, cv.w, 1, " ", None, (12, 14, 24))
        title = "D E P T H S"
        for i, ch in enumerate(title):
            glow = 0.5 + 0.5 * math.sin(now * 2 - i * 0.4)
            cv.put(2 + i, 0, ch, C.mix((200, 90, 30), (255, 210, 120), glow))
        b = data.BIOMES[game.level.biome]
        info = f"Depth {game.depth}/{data.MAX_DEPTH}  ·  {b['name']}"
        cv.text(17, 0, info, C.UI_TITLE)
        right = f"Turn {game.player.turns}   ?: help   Esc: menu"
        cv.text(cv.w - len(right) - 2, 0, right, C.UI_DIM)

    def _draw_sidebar(self, cv, game, now) -> None:
        L = self.layout
        p = game.player
        x0, w = L.side_x, SIDEBAR_W
        cv.box(x0, 1, w, cv.h - 1, C.UI_BORDER, C.UI_PANEL, title=None)
        x = x0 + 2
        iw = w - 4
        y = 2
        cd = p.cdata
        cv.text(x, y, cd["name"].upper(), cd["color"])
        lvl = f"Level {p.level}"
        cv.text(x0 + w - 2 - len(lvl), y, lvl, C.GOLD)
        y += 2
        hp_frac = p.hp / p.max_hp
        hp_col = C.gradient([(200, 30, 30), (230, 160, 40), (60, 200, 80)], hp_frac)
        if hp_frac < 0.3:
            hp_col = C.mix(hp_col, C.WHITE, 0.3 + 0.3 * math.sin(now * 8))
        cv.text(x, y, "HP", C.UI_DIM)
        cv.bar(x + 3, y, iw - 3, hp_frac, hp_col, (40, 16, 18), f"{max(0, p.hp)}/{p.max_hp}")
        y += 1
        cv.text(x, y, "MP", C.UI_DIM)
        cv.bar(x + 3, y, iw - 3, p.mp / max(1, p.max_mp), (60, 110, 230), (16, 20, 44),
               f"{p.mp}/{p.max_mp}")
        y += 1
        cv.text(x, y, "XP", C.UI_DIM)
        cv.bar(x + 3, y, iw - 3, p.xp / p.xp_next, (210, 170, 50), (36, 30, 14),
               f"{p.xp}/{p.xp_next}")
        y += 2
        n, s, b = p.dmg
        cv.text(x, y, "ATK", C.UI_DIM)
        cv.text(x + 4, y, str(p.atk), C.WHITE)
        cv.text(x + 9, y, "DEF", C.UI_DIM)
        cv.text(x + 13, y, str(p.defense), C.WHITE)
        cv.text(x + 18, y, "DMG", C.UI_DIM)
        cv.text(x + 22, y, f"{n}d{s}+{b}", C.WHITE)
        y += 1
        cv.text(x, y, "Gold", C.UI_DIM)
        cv.text(x + 5, y, str(p.gold), C.GOLD)
        cv.text(x + 14, y, "Kills", C.UI_DIM)
        cv.text(x + 20, y, str(p.kills), C.WHITE)
        y += 2
        y = self._section(cv, x0, y, w, "EQUIPMENT")
        for slot, glyph in (("weapon", ")"), ("armor", "["), ("ring", "=")):
            item = p.equipment[slot]
            if item:
                cv.text(x, y, glyph, item.d["color"])
                cv.text(x + 2, y, item.name, C.UI_TEXT, maxw=iw - 2)
            else:
                cv.text(x, y, glyph, C.UI_DIM)
                cv.text(x + 2, y, f"no {slot}", C.UI_DIM)
            y += 1
        y += 1
        y = self._section(cv, x0, y, w, "ABILITIES")
        for i, key in enumerate(p.all_abilities):
            a = data.ABILITIES[key]
            unlocked = key in p.abilities
            can = unlocked and p.mp >= a["cost"]
            cv.text(x, y, str(i + 1), C.GOLD if can else C.UI_DIM)
            if unlocked:
                cv.text(x + 2, y, a["name"], a["color"] if can else C.scale(a["color"], 0.45))
                cost = f"{a['cost']} MP"
                cv.text(x0 + w - 2 - len(cost), y, cost, C.BLUE if can else C.UI_DIM)
            else:
                cv.text(x + 2, y, f"{a['name']} (Lv {a['unlock']})", C.scale(C.UI_DIM, 0.7))
            y += 1
        if p.statuses:
            y += 1
            y = self._section(cv, x0, y, w, "STATUS")
            colors = {"poison": C.GREEN, "burning": C.ORANGE, "haste": C.YELLOW, "rage": C.RED,
                      "confused": C.PINK, "frozen": C.CYAN, "stunned": C.PINK,
                      "empowered": C.PURPLE}
            line_x = x
            for k, v in p.statuses.items():
                label = f"{k.capitalize()} {v}"
                if line_x + len(label) > x0 + w - 2:
                    y += 1
                    line_x = x
                cv.text(line_x, y, label, colors.get(k, C.UI_TEXT))
                line_x += len(label) + 2
            y += 1
        y += 1
        mm_rows = 8
        mm_y = cv.h - mm_rows - 3
        y = self._section(cv, x0, y, w, "IN SIGHT")
        seen = game.visible_monsters()
        room = mm_y - y - 2
        if not seen:
            cv.text(x, y, "Nothing stirs.", C.UI_DIM)
        for m in seen[:max(0, room)]:
            cv.text(x, y, m.glyph, m.color)
            name = m.name + (" (asleep)" if m.asleep else "")
            cv.text(x + 2, y, name, C.UI_TEXT if not m.asleep else C.UI_DIM, maxw=iw - 9)
            frac = m.hp / m.max_hp
            cv.bar(x0 + w - 8, y, 6, frac, C.gradient([(200, 40, 40), (220, 180, 40), (80, 200, 90)], frac),
                   (40, 18, 20))
            y += 1
        if len(seen) > room > 0:
            cv.text(x, y, f"... and {len(seen) - room} more", C.UI_DIM)
        self._section(cv, x0, mm_y - 1, w, "MAP")
        self._draw_minimap(cv, game, x, mm_y, iw, mm_rows, now)

    def _section(self, cv, x0, y, w, title) -> int:
        cv.text(x0 + 1, y, "─" * (w - 2), (40, 50, 70))
        cv.text(x0 + 3, y, f" {title} ", C.UI_TITLE)
        return y + 1

    def _draw_minimap(self, cv, game, x0, y0, w, rows, now) -> None:
        lv, p = game.level, game.player
        sx = lv.w / w
        sy = lv.h / (rows * 2)
        monsters = {(m.x, m.y) for m in game.visible_monsters()}

        def pixel(px, py):
            x0c, x1c = int(px * sx), int((px + 1) * sx)
            y0c, y1c = int(py * sy), int((py + 1) * sy)
            best = None
            for yy in range(y0c, max(y0c + 1, y1c)):
                for xx in range(x0c, max(x0c + 1, x1c)):
                    if (xx, yy) == (p.x, p.y):
                        return C.WHITE if int(now * 3) % 2 else C.GOLD
                    if (xx, yy) in monsters:
                        best = (230, 60, 60)
                    if best is not None or not lv.inside(xx, yy) or not lv.explored[yy][xx]:
                        continue
                    t = lv.tiles[yy][xx]
                    if t == STAIRS_DOWN or t == THRONE:
                        best = (120, 200, 255)
            if best:
                return best
            cx, cy = int((px + 0.5) * sx), int((py + 0.5) * sy)
            if not lv.inside(cx, cy) or not lv.explored[cy][cx]:
                return (8, 9, 14)
            t = lv.tiles[cy][cx]
            if t == WALL:
                return (60, 62, 80) if self.kind[cy][cx] == K_WALL else (8, 9, 14)
            if t == LAVA:
                return (200, 70, 20)
            if t in (WATER, DEEP_WATER):
                return (40, 80, 160)
            return (34, 36, 50) if (cx, cy) not in game.visible else (80, 80, 96)

        for r in range(rows):
            for c in range(w):
                top = pixel(c, r * 2)
                bot = pixel(c, r * 2 + 1)
                cv.put(x0 + c, y0 + r, "▀", top, bot)

    def _draw_log(self, cv, game) -> None:
        L = self.layout
        w = L.map_w
        cv.box(0, L.log_y, w, LOG_H, C.UI_BORDER, (9, 10, 17))
        cv.text(2, L.log_y, " MESSAGES ", C.UI_TITLE)
        lines = LOG_H - 2
        msgs = game.messages[-lines:]
        turn = game.player.turns
        for i, (text, color, t) in enumerate(msgs):
            age = len(msgs) - 1 - i
            fade = 1.0 if t >= turn - 1 else max(0.35, 0.8 - age * 0.12)
            cv.text(2, L.log_y + 1 + i, text, C.mix((9, 10, 17), color, fade), maxw=w - 4)
