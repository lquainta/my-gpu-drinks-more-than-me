"""Procedural level generation: rooms, caves, lava flows, and everything in them."""

import random
from collections import deque

from depths import data
from depths.fov import NEIGHBORS, compute_fov, distance_map, INF

MAP_W, MAP_H = 96, 48

# Tile ids
FLOOR, WALL, DOOR, OPEN_DOOR, STAIRS_DOWN, STAIRS_UP, WATER, DEEP_WATER, LAVA, GRASS, \
    BRAZIER, CRYSTAL, PILLAR, FOUNTAIN, RUBBLE, MUSHROOM, BONES, THRONE, CHEST, \
    OPEN_CHEST, TRAP = range(21)

# name, glyph, fg, walkable, transparent, light (rgb, radius) or None
TILES = {
    FLOOR: ("floor", "·", None, True, True, None),
    WALL: ("wall", " ", None, False, False, None),
    DOOR: ("door", "+", (190, 130, 70), False, False, None),
    OPEN_DOOR: ("open door", "'", (170, 115, 60), True, True, None),
    STAIRS_DOWN: ("stairs down", ">", (255, 240, 180), True, True, ((0.5, 0.55, 0.8), 3)),
    STAIRS_UP: ("stairs up", "<", (180, 180, 200), True, True, None),
    WATER: ("shallow water", "~", (90, 160, 230), True, True, None),
    DEEP_WATER: ("deep water", "≈", (60, 110, 220), False, True, None),
    LAVA: ("lava", "≈", (255, 120, 30), False, True, ((1.0, 0.42, 0.1), 3)),
    GRASS: ("cave moss", '"', (90, 170, 90), True, True, None),
    BRAZIER: ("brazier", "*", (255, 170, 60), False, True, ((1.0, 0.62, 0.28), 7)),
    CRYSTAL: ("glowing crystal", "♦", (190, 120, 255), False, False, ((0.55, 0.3, 1.0), 5)),
    PILLAR: ("pillar", "○", (150, 145, 160), False, False, None),
    FOUNTAIN: ("fountain", "{", (120, 200, 255), False, True, ((0.3, 0.6, 1.0), 4)),
    RUBBLE: ("rubble", ",", (120, 110, 100), True, True, None),
    MUSHROOM: ("glowing fungus", "♠", (80, 240, 210), True, True, ((0.15, 0.7, 0.6), 3)),
    BONES: ("bones", "%", (200, 195, 170), True, True, None),
    THRONE: ("the Hollow Throne", "Π", (255, 215, 80), False, True, ((1.0, 0.8, 0.35), 7)),
    CHEST: ("chest", "■", (230, 180, 70), False, True, None),
    OPEN_CHEST: ("open chest", "□", (150, 120, 60), True, True, None),
    TRAP: ("trap", "^", (230, 80, 80), True, True, None),
}


def walkable(t: int) -> bool:
    return TILES[t][3]


def transparent(t: int) -> bool:
    return TILES[t][4]


class Item:
    def __init__(self, key: str, x: int = 0, y: int = 0, count: int = 1, rng=random):
        self.key = key
        self.x, self.y = x, y
        self.count = count
        self.enchant = 0
        d = data.ITEMS[key]
        self.charges = rng.randint(*d["charges"]) if "charges" in d else 0

    @property
    def d(self):
        return data.ITEMS[self.key]

    @property
    def name(self) -> str:
        d = self.d
        if d["kind"] == "gold":
            return f"{self.count} gold"
        n = d["name"]
        if self.enchant:
            n = f"{'+' if self.enchant > 0 else ''}{self.enchant} {n}"
        if d["kind"] == "wand":
            n += f" ({self.charges})"
        if self.count > 1:
            n = f"{self.count} x {n}"
        return n

    def stacks_with(self, other: "Item") -> bool:
        return self.key == other.key and self.d["kind"] in ("potion", "scroll")


class Level:
    def __init__(self, depth: int, seed: int):
        self.depth = depth
        self.seed = seed
        self.biome = data.biome_for(depth)
        self.w, self.h = MAP_W, MAP_H
        self.tiles = [[WALL] * self.w for _ in range(self.h)]
        self.explored = [[False] * self.w for _ in range(self.h)]
        self.opaque = [[True] * self.w for _ in range(self.h)]
        self.noise: list[list[float]] = []
        self.static_light: list[list[tuple]] = []
        self.items: list[Item] = []
        self.monsters: list = []
        self.traps: dict[tuple[int, int], str] = {}
        self.chests: dict[tuple[int, int], list[Item]] = {}
        self.up = (0, 0)
        self.down = (0, 0)
        self.rooms: list[tuple[int, int, int, int]] = []
        self.version = 0  # bumped whenever a tile changes, so renderers can re-cache

    @property
    def name(self) -> str:
        return data.BIOMES[self.biome]["name"]

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def tile(self, x: int, y: int) -> int:
        return self.tiles[y][x] if self.inside(x, y) else WALL

    def set(self, x: int, y: int, t: int) -> None:
        self.tiles[y][x] = t
        self.opaque[y][x] = not transparent(t)
        self.version += 1

    def walkable(self, x: int, y: int) -> bool:
        return self.inside(x, y) and walkable(self.tiles[y][x])

    def passable_for_path(self, x: int, y: int) -> bool:
        """Walkable or a closed door (which a walker can open)."""
        t = self.tile(x, y)
        return walkable(t) or t == DOOR

    def floor_cells(self) -> list[tuple[int, int]]:
        return [(x, y) for y in range(self.h) for x in range(self.w)
                if self.tiles[y][x] == FLOOR]

    def items_at(self, x: int, y: int) -> list[Item]:
        return [i for i in self.items if i.x == x and i.y == y]

    def rebuild_opaque(self) -> None:
        for y in range(self.h):
            for x in range(self.w):
                self.opaque[y][x] = not transparent(self.tiles[y][x])


# --- generation ---------------------------------------------------------------

def generate(depth: int, seed: int) -> Level:
    """Generate a level. Retries with a new seed in the rare event of a bad layout."""
    for attempt in range(20):
        rng = random.Random(seed * 7919 + attempt)
        lv = Level(depth, seed)
        style = data.BIOMES[lv.biome]["style"]
        if style == "rooms":
            _rooms(lv, rng, crypt=True)
        elif style == "caves":
            _caves(lv, rng)
        elif style == "molten":
            _molten(lv, rng)
        else:
            _abyss(lv, rng)
        if _finish(lv, rng):
            return lv
    raise RuntimeError("could not generate a level")


def _carve(lv: Level, x: int, y: int, t: int = FLOOR) -> None:
    if 1 <= x < lv.w - 1 and 1 <= y < lv.h - 1:
        lv.tiles[y][x] = t


def _rooms(lv: Level, rng: random.Random, crypt: bool) -> None:
    leaves = []

    def split(x, y, w, h, d):
        if d >= 5 or (w < 22 and h < 14) or (d >= 3 and rng.random() < 0.25):
            leaves.append((x, y, w, h))
            return
        if w > h * 1.6 or (w >= 22 and (h < 14 or rng.random() < 0.5)):
            cut = rng.randint(w // 3, w - w // 3)
            split(x, y, cut, h, d + 1)
            split(x + cut, y, w - cut, h, d + 1)
        else:
            cut = rng.randint(h // 3, h - h // 3)
            split(x, y, w, cut, d + 1)
            split(x, y + cut, w, h - cut, d + 1)

    split(1, 1, lv.w - 2, lv.h - 2, 0)
    rooms = []
    for x, y, w, h in leaves:
        if w < 7 or h < 6:
            continue
        rw = rng.randint(4, min(16, w - 3))
        rh = rng.randint(3, min(10, h - 3))
        rx = rng.randint(x + 1, x + w - rw - 1)
        ry = rng.randint(y + 1, y + h - rh - 1)
        rooms.append((rx, ry, rw, rh))
        for yy in range(ry, ry + rh):
            for xx in range(rx, rx + rw):
                _carve(lv, xx, yy)
    lv.rooms = rooms

    def center(r):
        return r[0] + r[2] // 2, r[1] + r[3] // 2

    def corridor(a, b):
        (x0, y0), (x1, y1) = center(a), center(b)
        if rng.random() < 0.5:
            for x in range(min(x0, x1), max(x0, x1) + 1):
                _carve(lv, x, y0)
            for y in range(min(y0, y1), max(y0, y1) + 1):
                _carve(lv, x1, y)
        else:
            for y in range(min(y0, y1), max(y0, y1) + 1):
                _carve(lv, x0, y)
            for x in range(min(x0, x1), max(x0, x1) + 1):
                _carve(lv, x, y1)

    for a, b in zip(rooms, rooms[1:]):
        corridor(a, b)
    for _ in range(max(1, len(rooms) // 4)):
        corridor(rng.choice(rooms), rng.choice(rooms))

    # Doors where corridors meet rooms, at chokepoints.
    for rx, ry, rw, rh in rooms:
        edges = [(x, ry - 1) for x in range(rx, rx + rw)] + \
                [(x, ry + rh) for x in range(rx, rx + rw)] + \
                [(rx - 1, y) for y in range(ry, ry + rh)] + \
                [(rx + rw, y) for y in range(ry, ry + rh)]
        for x, y in edges:
            if lv.tile(x, y) != FLOOR:
                continue
            horiz = lv.tile(x - 1, y) == WALL and lv.tile(x + 1, y) == WALL
            vert = lv.tile(x, y - 1) == WALL and lv.tile(x, y + 1) == WALL
            if (horiz or vert) and rng.random() < 0.55:
                lv.tiles[y][x] = DOOR

    # Room dressing
    for rx, ry, rw, rh in rooms:
        roll = rng.random()
        if crypt and rw >= 7 and rh >= 5 and roll < 0.3:
            for x, y in ((rx + 1, ry + 1), (rx + rw - 2, ry + 1), (rx + 1, ry + rh - 2),
                         (rx + rw - 2, ry + rh - 2)):
                lv.tiles[y][x] = BRAZIER
        elif rw >= 9 and rh >= 6 and roll < 0.5:
            for x in range(rx + 2, rx + rw - 2, 3):
                lv.tiles[ry + 1][x] = PILLAR
                lv.tiles[ry + rh - 2][x] = PILLAR
        elif roll < 0.6 and rw >= 5 and rh >= 4:
            lv.tiles[ry + rh // 2][rx + rw // 2] = BRAZIER if crypt else CRYSTAL
        elif roll < 0.68:
            cx, cy = rx + rw // 2, ry + rh // 2
            for yy in range(ry, ry + rh):
                for xx in range(rx, rx + rw):
                    if (xx - cx) ** 2 / max(1, rw / 2) ** 2 + (yy - cy) ** 2 / max(1, rh / 2) ** 2 < 0.6:
                        lv.tiles[yy][xx] = WATER
        for _ in range(rng.randint(0, 3)):
            x, y = rng.randint(rx, rx + rw - 1), rng.randint(ry, ry + rh - 1)
            if lv.tiles[y][x] == FLOOR:
                lv.tiles[y][x] = rng.choice((RUBBLE, BONES, RUBBLE))


def _cellular(w: int, h: int, rng: random.Random, fill: float, steps: int) -> list[list[bool]]:
    """True = solid."""
    g = [[(x in (0, w - 1) or y in (0, h - 1) or rng.random() < fill) for x in range(w)]
         for y in range(h)]
    for step in range(steps):
        n = [[False] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                if x in (0, w - 1) or y in (0, h - 1):
                    n[y][x] = True
                    continue
                c = sum(g[y + dy][x + dx] for dx, dy in NEIGHBORS)
                if step < steps - 2:
                    c2 = 0
                    for dy in range(-2, 3):
                        for dx in range(-2, 3):
                            xx, yy = x + dx, y + dy
                            if not (0 <= xx < w and 0 <= yy < h) or g[yy][xx]:
                                c2 += 1
                    n[y][x] = c >= 5 or c2 <= 2
                else:
                    n[y][x] = c >= 5
        g = n
    return g


def _caves(lv: Level, rng: random.Random) -> None:
    g = _cellular(lv.w, lv.h, rng, 0.45, 6)
    for y in range(lv.h):
        for x in range(lv.w):
            if not g[y][x]:
                lv.tiles[y][x] = FLOOR
    water = _cellular(lv.w, lv.h, rng, 0.64, 5)
    for y in range(lv.h):
        for x in range(lv.w):
            if lv.tiles[y][x] == FLOOR and not water[y][x]:
                deep = all(lv.tile(x + dx, y + dy) != WALL and not water[y + dy][x + dx]
                           for dx, dy in NEIGHBORS if lv.inside(x + dx, y + dy))
                lv.tiles[y][x] = DEEP_WATER if deep and rng.random() < 0.8 else WATER
    for y in range(lv.h):
        for x in range(lv.w):
            if lv.tiles[y][x] == FLOOR:
                r = rng.random()
                if r < 0.025:
                    lv.tiles[y][x] = MUSHROOM
                elif r < 0.09:
                    lv.tiles[y][x] = GRASS


def _molten(lv: Level, rng: random.Random) -> None:
    g = _cellular(lv.w, lv.h, rng, 0.44, 6)
    for y in range(lv.h):
        for x in range(lv.w):
            if not g[y][x]:
                lv.tiles[y][x] = FLOOR
    # Lava rivers: wandering walks across the map.
    for _ in range(rng.randint(2, 3)):
        x, y = rng.randint(5, lv.w - 6), 1
        if rng.random() < 0.5:
            x, y = 1, rng.randint(5, lv.h - 6)
            horizontal = True
        else:
            horizontal = False
        width = rng.randint(1, 2)
        while 0 < x < lv.w - 1 and 0 < y < lv.h - 1:
            for dy in range(-width, width + 1):
                for dx in range(-width, width + 1):
                    if lv.tile(x + dx, y + dy) == FLOOR and abs(dx) + abs(dy) <= width:
                        lv.tiles[y + dy][x + dx] = LAVA
            if horizontal:
                x += 1
                y += rng.choice((-1, 0, 0, 1))
            else:
                y += 1
                x += rng.choice((-1, 0, 0, 1))
    # Bridges: re-open some lava so rivers are crossable.
    for y in range(1, lv.h - 1):
        for x in range(1, lv.w - 1):
            if lv.tiles[y][x] == LAVA and rng.random() < 0.05:
                for k in range(-3, 4):
                    if lv.tile(x + k, y) == LAVA:
                        lv.tiles[y][x + k] = RUBBLE
    for y in range(lv.h):
        for x in range(lv.w):
            if lv.tiles[y][x] == FLOOR and rng.random() < 0.04:
                lv.tiles[y][x] = RUBBLE


def _abyss(lv: Level, rng: random.Random) -> None:
    _rooms(lv, rng, crypt=False)
    g = _cellular(lv.w, lv.h, rng, 0.5, 5)
    for y in range(1, lv.h - 1):
        for x in range(1, lv.w - 1):
            if not g[y][x] and lv.tiles[y][x] == WALL and rng.random() < 0.9:
                lv.tiles[y][x] = FLOOR
    for y in range(1, lv.h - 1):
        for x in range(1, lv.w - 1):
            if lv.tiles[y][x] == WALL and rng.random() < 0.03 and any(
                    lv.tile(x + dx, y + dy) == FLOOR for dx, dy in NEIGHBORS):
                lv.tiles[y][x] = CRYSTAL


def _regions(lv: Level) -> list[set]:
    seen = [[False] * lv.w for _ in range(lv.h)]
    regions = []
    for y in range(lv.h):
        for x in range(lv.w):
            if seen[y][x] or not lv.passable_for_path(x, y):
                continue
            region = set()
            q = deque([(x, y)])
            seen[y][x] = True
            while q:
                cx, cy = q.popleft()
                region.add((cx, cy))
                for dx, dy in NEIGHBORS:
                    nx, ny = cx + dx, cy + dy
                    if lv.inside(nx, ny) and not seen[ny][nx] and lv.passable_for_path(nx, ny):
                        seen[ny][nx] = True
                        q.append((nx, ny))
            regions.append(region)
    return regions


def _finish(lv: Level, rng: random.Random) -> bool:
    regions = _regions(lv)
    if not regions:
        return False
    main = max(regions, key=len)
    if len(main) < 350:
        return False
    for region in regions:
        if region is not main:
            for x, y in region:
                lv.tiles[y][x] = LAVA if lv.biome == "molten" else WALL
    lv.rebuild_opaque()

    floors = [c for c in main if lv.tiles[c[1]][c[0]] == FLOOR]
    if len(floors) < 120:
        return False
    start = rng.choice(floors)
    dist = distance_map(lv.w, lv.h, [start], lv.passable_for_path)
    far = max(floors, key=lambda c: dist[c[1]][c[0]] if dist[c[1]][c[0]] < INF else -1)
    if dist[far[1]][far[0]] < 25:
        return False
    lv.up = start
    lv.set(*start, STAIRS_UP)
    if lv.depth < data.MAX_DEPTH:
        lv.down = far
        lv.set(*far, STAIRS_DOWN)
    else:
        _throne_room(lv, far)

    _populate(lv, rng, dist)
    _compute_noise(lv, rng)
    compute_static_light(lv)
    return True


def _throne_room(lv: Level, at: tuple[int, int]) -> None:
    # Clamp the centre so the hall fits; it still contains `at`, so it stays connected.
    x0 = max(7, min(lv.w - 8, at[0]))
    y0 = max(5, min(lv.h - 6, at[1]))
    for dy in range(-4, 5):
        for dx in range(-6, 7):
            lv.tiles[y0 + dy][x0 + dx] = FLOOR
    for dx in (-5, 5):
        for dy in (-3, 3):
            lv.tiles[y0 + dy][x0 + dx] = BRAZIER
    lv.tiles[y0 - 3][x0] = THRONE
    lv.down = (x0, y0)
    lv.rebuild_opaque()


def _weighted(rng: random.Random, table: dict, depth: int, key_depth) -> str | None:
    options = [(k, d["weight"]) for k, d in table.items() if d["weight"] and key_depth(d, depth)]
    total = sum(w for _, w in options)
    if not total:
        return None
    r = rng.uniform(0, total)
    for k, w in options:
        r -= w
        if r <= 0:
            return k
    return options[-1][0]


def _populate(lv: Level, rng: random.Random, dist) -> None:
    from depths.actors import make_monster

    depth = lv.depth
    free = [(x, y) for y in range(lv.h) for x in range(lv.w)
            if lv.tiles[y][x] in (FLOOR, GRASS, RUBBLE, MUSHROOM, WATER)
            and dist[y][x] < INF and (x, y) != lv.up]
    rng.shuffle(free)
    taken = {lv.up, lv.down}

    def take(min_dist=0):
        while free:
            c = free.pop()
            if c not in taken and dist[c[1]][c[0]] >= min_dist:
                taken.add(c)
                return c
        return None

    # Monsters
    count = 7 + int(depth * 1.6) + rng.randint(0, 3)
    placed = 0
    while placed < count:
        key = _weighted(rng, data.MONSTERS, depth,
                        lambda d, dep: d["depth"][0] <= dep <= d["depth"][1])
        spot = take(min_dist=9)
        if not key or not spot:
            break
        group = [spot]
        for _ in range(data.MONSTERS[key].get("pack", 1) - 1):
            if rng.random() < 0.6:
                for dx, dy in NEIGHBORS:
                    c = (spot[0] + dx, spot[1] + dy)
                    if lv.walkable(*c) and c not in taken:
                        taken.add(c)
                        group.append(c)
                        break
        for x, y in group:
            m = make_monster(key, x, y)
            m.asleep = rng.random() < 0.55
            lv.monsters.append(m)
            placed += 1

    if depth == data.MAX_DEPTH:
        kx, ky = lv.down
        king = make_monster("king", kx, ky)
        king.asleep = True
        lv.monsters = [m for m in lv.monsters if (m.x, m.y) != (kx, ky)]
        lv.monsters.append(king)

    # Items
    def random_item(x, y):
        key = _weighted(rng, {k: v for k, v in data.ITEMS.items() if v["kind"] != "gold"},
                        depth, lambda d, dep: d["depth"] <= dep + 1)
        item = Item(key, x, y, rng=rng)
        if item.d["kind"] in ("weapon", "armor") and rng.random() < 0.25 + depth * 0.03:
            item.enchant = rng.randint(1, 1 + depth // 4)
        return item

    for _ in range(5 + rng.randint(0, 3) + depth // 3):
        spot = take()
        if spot:
            lv.items.append(random_item(*spot))
    for _ in range(4 + rng.randint(0, 4)):
        spot = take()
        if spot:
            lv.items.append(Item("gold", *spot, count=rng.randint(5, 15) * depth + rng.randint(0, 20)))

    # Chests (in dead ends / room corners are nice, but anywhere walkable is fine)
    for _ in range(rng.randint(1, 2)):
        spot = take(min_dist=6)
        if spot:
            lv.set(*spot, CHEST)
            contents = [random_item(*spot) for _ in range(rng.randint(2, 3))]
            contents.append(Item("gold", *spot, count=rng.randint(20, 40) * depth))
            lv.chests[spot] = contents

    # Fountain
    if rng.random() < 0.35:
        spot = take(min_dist=5)
        if spot and all(lv.walkable(spot[0] + dx, spot[1] + dy) for dx, dy in NEIGHBORS):
            lv.set(*spot, FOUNTAIN)

    # Hidden traps
    if depth >= 2:
        for _ in range(rng.randint(2, 4 + depth // 2)):
            spot = take(min_dist=5)
            if spot and lv.tiles[spot[1]][spot[0]] == FLOOR:
                lv.traps[spot] = rng.choice(list(data.TRAPS))


def _compute_noise(lv: Level, rng: random.Random) -> None:
    raw = [[rng.random() for _ in range(lv.w)] for _ in range(lv.h)]
    lv.noise = [[0.0] * lv.w for _ in range(lv.h)]
    for y in range(lv.h):
        for x in range(lv.w):
            s, n = 0.0, 0
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if lv.inside(x + dx, y + dy):
                        s += raw[y + dy][x + dx]
                        n += 1
            lv.noise[y][x] = 0.55 * (s / n) + 0.45 * raw[y][x]


def compute_static_light(lv: Level) -> None:
    """Pre-bake the light from fixed sources (braziers, lava, crystals...)."""
    light = [[[0.0, 0.0, 0.0] for _ in range(lv.w)] for _ in range(lv.h)]
    for y in range(lv.h):
        for x in range(lv.w):
            src = TILES[lv.tiles[y][x]][5]
            if not src:
                continue
            (r, g, b), radius = src
            if lv.tiles[y][x] in (LAVA, MUSHROOM):
                # Many small sources: skip line of sight for speed.
                cells = ((x + dx, y + dy) for dy in range(-radius, radius + 1)
                         for dx in range(-radius, radius + 1))
                strength = 0.35
            else:
                cells = compute_fov(lv.opaque, lv.w, lv.h, x, y, radius)
                strength = 1.0
            for cx, cy in cells:
                if not lv.inside(cx, cy):
                    continue
                d = ((cx - x) ** 2 + (cy - y) ** 2) ** 0.5
                if d > radius:
                    continue
                k = strength * (1 - d / (radius + 0.5)) ** 1.5
                cell = light[cy][cx]
                cell[0] += r * k
                cell[1] += g * k
                cell[2] += b * k
    lv.static_light = [[(min(c[0], 1.6), min(c[1], 1.6), min(c[2], 1.6)) for c in row]
                       for row in light]
