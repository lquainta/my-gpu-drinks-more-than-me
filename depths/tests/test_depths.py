"""Tests for DEPTHS. Run from the depths/ directory:  python3 -m unittest discover tests"""

import os
import random
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from depths import data, mapgen  # noqa: E402
from depths import game as G  # noqa: E402
from depths.actors import make_monster  # noqa: E402
from depths.canvas import Canvas  # noqa: E402
from depths.fov import INF, compute_fov, distance_map, line  # noqa: E402
from depths.mapgen import Item  # noqa: E402


class FovTests(unittest.TestCase):
    def test_open_room_sees_everything_in_radius(self):
        opaque = [[False] * 21 for _ in range(21)]
        vis = compute_fov(opaque, 21, 21, 10, 10, 5)
        self.assertIn((10, 5), vis)
        self.assertIn((14, 13), vis)
        self.assertNotIn((10, 4), vis)

    def test_wall_blocks_sight(self):
        opaque = [[False] * 21 for _ in range(21)]
        for y in range(21):
            opaque[y][12] = True
        vis = compute_fov(opaque, 21, 21, 10, 10, 8)
        self.assertIn((12, 10), vis)  # the wall itself is seen
        self.assertNotIn((14, 10), vis)

    def test_line_endpoints(self):
        pts = line(0, 0, 5, 3)
        self.assertEqual(pts[0], (0, 0))
        self.assertEqual(pts[-1], (5, 3))
        self.assertEqual(len(pts), 6)


class MapgenTests(unittest.TestCase):
    def test_every_depth_is_connected(self):
        for depth in range(1, data.MAX_DEPTH + 1):
            for seed in (1, 2):
                lv = mapgen.generate(depth, seed * 97 + depth)
                dist = distance_map(lv.w, lv.h, [lv.up], lv.passable_for_path)
                self.assertLess(dist[lv.down[1]][lv.down[0]], INF, f"depth {depth}")
                for m in lv.monsters:
                    self.assertTrue(lv.walkable(m.x, m.y), f"monster in wall on depth {depth}")
                    self.assertLess(dist[m.y][m.x], INF)
                for item in lv.items:
                    self.assertLess(dist[item.y][item.x], INF)

    def test_generation_is_deterministic(self):
        a = mapgen.generate(4, 1234)
        b = mapgen.generate(4, 1234)
        self.assertEqual(a.tiles, b.tiles)

    def test_final_depth_has_the_king(self):
        lv = mapgen.generate(data.MAX_DEPTH, 5)
        self.assertTrue(any(m.key == "king" for m in lv.monsters))
        self.assertTrue(any(mapgen.THRONE in row for row in lv.tiles))


def fresh_game(cls="warrior", seed=7) -> G.Game:
    g = G.Game(cls, seed=seed)
    g.level.monsters.clear()
    return g


def place_monster(g: G.Game, key: str, dx: int = 1, dy: int = 0):
    p = g.player
    for ddx, ddy in [(dx, dy), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)]:
        x, y = p.x + ddx, p.y + ddy
        if g.level.walkable(x, y) and not g.occupied(x, y):
            m = make_monster(key, x, y)
            g.level.monsters.append(m)
            g.update_fov()
            g.update_dmap()
            return m
    raise RuntimeError("no room")


class CombatTests(unittest.TestCase):
    def test_killing_grants_xp_and_kill(self):
        g = fresh_game()
        m = place_monster(g, "rat")
        m.hp = 1
        m.asleep = True  # sneak attacks always hit
        g.move(m.x - g.player.x, m.y - g.player.y)
        self.assertFalse(m.alive)
        self.assertEqual(g.player.kills, 1)
        self.assertGreater(g.total_xp, 0)

    def test_player_can_die(self):
        g = fresh_game()
        g.player.hp = 1
        g.damage(g.player, 5, None, cause="a test")
        self.assertTrue(g.dead)
        self.assertEqual(g.player.killed_by, "a test")

    def test_level_up(self):
        g = fresh_game()
        hp = g.player.max_hp
        g.gain_xp(g.player.xp_next)
        self.assertEqual(g.player.level, 2)
        self.assertGreater(g.player.max_hp, hp)

    def test_monsters_approach_and_attack(self):
        g = fresh_game()
        m = place_monster(g, "skeleton")
        m.asleep = False
        m.hunting = True
        hp = g.player.hp
        for _ in range(30):
            g.wait()
        self.assertLess(g.player.hp, hp)

    def test_ooze_splits(self):
        g = fresh_game()
        m = place_monster(g, "ooze")
        g.damage(m, 2, g.player)
        self.assertGreaterEqual(sum(1 for o in g.level.monsters if o.key == "ooze"), 2)

    def test_every_monster_can_act(self):
        for key in data.MONSTERS:
            g = fresh_game(seed=11)
            m = place_monster(g, key, 3, 0)
            m.asleep = False
            m.hunting = True
            for _ in range(6):
                if g.dead:
                    break
                g.player.hp = g.player.max_hp
                g.wait()


class ItemTests(unittest.TestCase):
    def test_every_item_can_be_used(self):
        for key, d in data.ITEMS.items():
            if d["kind"] == "gold":
                continue
            g = fresh_game(seed=3)
            m = place_monster(g, "troll", 2, 0)
            item = Item(key)
            g.player.inventory.append(item)
            target = (m.x, m.y) if d.get("target") else None
            used = g.use_item(item, target)
            if key != "lightning" or g.visible_monsters():
                self.assertTrue(used, key)

    def test_stacking_and_pickup(self):
        g = fresh_game()
        p = g.player
        before = sum(i.count for i in p.inventory if i.key == "heal")
        g.level.items.append(Item("heal", p.x, p.y))
        g.pickup()
        after = sum(i.count for i in p.inventory if i.key == "heal")
        self.assertEqual(after, before + 1)

    def test_equip_swaps(self):
        g = fresh_game()
        sword = Item("longsword")
        g.player.inventory.append(sword)
        old = g.player.equipment["weapon"]
        g.equip(sword)
        self.assertIs(g.player.equipment["weapon"], sword)
        self.assertIn(old, g.player.inventory)

    def test_gold_is_auto_collected(self):
        g = fresh_game()
        p = g.player
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            if g.level.walkable(p.x + dx, p.y + dy):
                g.level.items.append(Item("gold", p.x + dx, p.y + dy, count=50))
                g.move(dx, dy)
                break
        self.assertEqual(p.gold, 50)


class AbilityTests(unittest.TestCase):
    def test_every_ability(self):
        for cls, cd in data.CLASSES.items():
            for key in cd["abilities"]:
                g = fresh_game(cls, seed=5)
                p = g.player
                p.level = 9
                p.mp = p.max_mp = 99
                p.hp = p.max_hp - 10
                m = place_monster(g, "golem", 1, 0)
                t = data.ABILITIES[key]["target"]
                target = None
                if t == "enemy":
                    target = (m.x, m.y)
                elif t == "cell":
                    target = next(c for c in sorted(g.visible, key=lambda c: abs(c[0] - p.x) + abs(c[1] - p.y))
                                  if g.level.walkable(*c) and not g.occupied(*c)
                                  and 2 <= max(abs(c[0] - p.x), abs(c[1] - p.y)) <= 5)
                self.assertTrue(g.use_ability(key, target), f"{cls}:{key}")
                self.assertLess(p.mp, 99)

    def test_locked_ability(self):
        g = fresh_game("mage")
        self.assertFalse(g.use_ability("meteor", (g.player.x + 1, g.player.y)))


class PersistenceTests(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        g = G.Game("rogue", seed=99)
        for _ in range(5):
            g.wait()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "save.pkl")
            G.save(g, path)
            g2 = G.load(path)
        self.assertEqual(g2.player.turns, g.player.turns)
        self.assertEqual(g2.level.tiles, g.level.tiles)
        g2.wait()  # still playable

    def test_score_increases(self):
        g = fresh_game()
        s = g.score()
        g.player.gold += 100
        self.assertGreater(g.score(), s)


class RenderTests(unittest.TestCase):
    def test_every_screen_and_mode_draws(self):
        from depths import app as A
        from depths import screens as S

        class FakeTerm:
            def size(self):
                return (140, 42)

        app = A.App(FakeTerm())
        now = time.monotonic()
        for screen in (S.TitleScreen(app), S.ClassSelectScreen(app), S.ScoresScreen(app),
                       S.HelpScreen(app)):
            screen.update(0.03, now)
            screen.draw(Canvas(140, 42), now)
        g = G.Game("mage", seed=21)
        gs = A.GameScreen(app, g)
        for mode in ("play", "inventory", "char", "help", "log", "menu", "confirm", "look"):
            gs.mode = mode
            gs.cursor = (g.player.x, g.player.y)
            gs.update(0.03, now)
            gs.draw(Canvas(140, 42), now + 1)
        gs.mode = "play"
        gs._start_ability("firebolt")
        gs.draw(Canvas(140, 42), now + 2)
        gs.mode = "play"
        g._explosion((g.player.x + 2, g.player.y), 2, 3, (255, 100, 30))
        gs._absorb()
        for k in range(5):
            gs.update(0.05, now + k * 0.05)
            gs.draw(Canvas(140, 42), now + k * 0.05)
        gs.draw(Canvas(60, 20), now)  # too-small terminal message
        g.player.killed_by = "a test"
        S.DeathScreen(app, g, 1).draw(Canvas(140, 42), now)
        S.VictoryScreen(app, g, 1).draw(Canvas(140, 42), now)


class BotTests(unittest.TestCase):
    def test_bot_plays_each_class_without_crashing(self):
        from bot import play

        for i, cls in enumerate(data.CLASSES):
            g = play(500 + i, cls, 600)
            self.assertGreater(g.player.turns, 100)


if __name__ == "__main__":
    unittest.main()
