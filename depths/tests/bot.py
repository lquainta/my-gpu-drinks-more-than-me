"""A simple bot that plays DEPTHS headlessly. Used to shake out crashes.

Run directly for a quick report:  python3 tests/bot.py [games] [max_turns]
"""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from depths import data  # noqa: E402
from depths.fov import INF, NEIGHBORS, chebyshev, distance_map  # noqa: E402
from depths.game import Game  # noqa: E402


def bot_turn(g: Game, rng: random.Random) -> None:
    p = g.player
    lv = g.level
    # Heal when hurt.
    if p.hp < p.max_hp * 0.4:
        for item in p.inventory:
            if item.key in ("heal", "greater_heal"):
                g.use_item(item)
                return
    # Equip anything better.
    for item in list(p.inventory):
        kind = item.d["kind"]
        if kind == "weapon":
            cur = p.equipment["weapon"]
            if not cur or item.d["dmg"][0] * item.d["dmg"][1] > cur.d["dmg"][0] * cur.d["dmg"][1]:
                g.equip(item)
                return
        if kind == "armor":
            cur = p.equipment["armor"]
            if not cur or item.d["ac"] > cur.d["ac"]:
                g.equip(item)
                return
        if kind == "ring" and not p.equipment["ring"]:
            g.equip(item)
            return
    enemies = g.threats()
    if enemies:
        m = enemies[0]
        d = chebyshev(p.x, p.y, m.x, m.y)
        # Try an ability or a random usable item sometimes.
        if rng.random() < 0.3 and p.abilities:
            key = rng.choice(p.abilities)
            target = (m.x, m.y)
            if data.ABILITIES[key]["target"] == "cell":
                target = (p.x + rng.randint(-3, 3), p.y + rng.randint(-3, 3))
            if g.use_ability(key, target):
                return
        if rng.random() < 0.1:
            usable = [i for i in p.inventory if i.d["kind"] in ("scroll", "wand", "potion")]
            if usable:
                if g.use_item(rng.choice(usable), (m.x, m.y)):
                    return
        if d == 1:
            g.move(m.x - p.x, m.y - p.y)
            return
        towards = distance_map(lv.w, lv.h, [(m.x, m.y)], lv.passable_for_path, limit=40)
        best = min(NEIGHBORS, key=lambda o: towards[p.y + o[1]][p.x + o[0]])
        if towards[p.y + best[1]][p.x + best[0]] >= INF or not g.move(*best):
            g.wait()
        return
    if lv.tiles[p.y][p.x] == 4 and (rng.random() < 0.5 or g.explore_step()):
        g.descend()
        return
    reason = g.explore_step()
    if reason is None:
        return
    if g.depth < data.MAX_DEPTH:
        r = g.travel_step(lv.down)
        if r == "arrived":
            g.descend()
            return
        if r is None:
            return
    if p.hp < p.max_hp and g.rest_step() is None:
        return
    # Wander a bit if stuck.
    dx, dy = rng.choice(NEIGHBORS)
    if not g.move(dx, dy):
        g.wait()


def play(seed: int, cls: str, max_turns: int, god: bool = False) -> Game:
    rng = random.Random(seed)
    g = Game(cls, seed=seed)
    while not g.dead and not g.won and g.player.turns < max_turns:
        if god:
            g.player.hp = max(g.player.hp, g.player.max_hp // 2)
            g.player.mp = g.player.max_mp
        bot_turn(g, rng)
        g.fx.clear()
    return g


if __name__ == "__main__":
    games = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    turns = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    for i in range(games):
        cls = list(data.CLASSES)[i % 3]
        g = play(1000 + i, cls, turns, god="--god" in sys.argv)
        p = g.player
        result = "WON" if g.won else f"died to {p.killed_by}" if g.dead else "timeout"
        print(f"{cls:8} seed {1000 + i}: depth {g.depth:2} lvl {p.level:2} turns {p.turns:5} "
              f"kills {p.kills:3} gold {p.gold:5} -> {result}")
