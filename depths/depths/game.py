"""Game rules: turns, combat, monster AI, abilities, items, traps and exploration."""

import pickle
import random

from depths import colors as C
from depths import data
from depths.actors import Monster, Player, make_monster
from depths.fov import INF, NEIGHBORS, chebyshev, compute_fov, distance_map, line
from depths.mapgen import (BONES, CHEST, DEEP_WATER, DOOR, FLOOR, FOUNTAIN, LAVA, OPEN_CHEST,
                           OPEN_DOOR, STAIRS_DOWN, TILES, TRAP, WALL, Item, Level, generate)

FOV_RADIUS = 11
INVENTORY_LIMIT = 22


class Game:
    def __init__(self, cls: str, seed: int | None = None):
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.rng = random.Random(self.seed)
        self.player = Player(cls)
        self.depth = 0
        self.level: Level | None = None
        self.messages: list[tuple[str, tuple, int]] = []
        self.fx: list[dict] = []
        self.visible: set = set()
        self.dmap = None
        self.dead = False
        self.won = False
        self.total_xp = 0
        self.used_fountains: set = set()
        for key in self.player.cdata["start"]:
            item = Item(key, rng=self.rng)
            kind = item.d["kind"]
            if kind in ("weapon", "armor", "ring") and self.player.equipment[kind] is None:
                self.player.equipment[kind] = item
            else:
                self._add_to_inventory(item)
        self.enter_level(1)
        self.msg(f"You descend into the Depths as a {self.player.cdata['name'].lower()}. "
                 "Press ? for help.", C.UI_TITLE)

    # --- helpers --------------------------------------------------------------------

    def msg(self, text: str, color=C.UI_TEXT) -> None:
        self.messages.append((text, color, self.player.turns))
        del self.messages[:-300]

    def emit(self, kind: str, **kw) -> None:
        kw["type"] = kind
        self.fx.append(kw)

    def roll(self, n: int, s: int, b: int = 0) -> int:
        return sum(self.rng.randint(1, s) for _ in range(n)) + b

    def monster_at(self, x: int, y: int) -> Monster | None:
        for m in self.level.monsters:
            if m.x == x and m.y == y and m.alive:
                return m
        return None

    def occupied(self, x: int, y: int) -> bool:
        return (self.player.x, self.player.y) == (x, y) or self.monster_at(x, y) is not None

    def visible_monsters(self) -> list[Monster]:
        p = self.player
        ms = [m for m in self.level.monsters if m.alive and (m.x, m.y) in self.visible]
        ms.sort(key=lambda m: chebyshev(p.x, p.y, m.x, m.y))
        return ms

    def the(self, a) -> str:
        if a.is_player:
            return "you"
        return a.name if a.name.startswith("the ") else f"the {a.name}"

    def can_see(self, a) -> bool:
        return a.is_player or (a.x, a.y) in self.visible

    def score(self) -> int:
        p = self.player
        return (p.gold + self.total_xp * 2 + (p.deepest - 1) * 500 + p.kills * 10
                + (25000 if self.won else 0))

    # --- levels ---------------------------------------------------------------------

    def enter_level(self, depth: int) -> None:
        self.depth = depth
        self.level = generate(depth, self.seed + depth * 1013)
        p = self.player
        p.x, p.y = self.level.up
        p.deepest = max(p.deepest, depth)
        p.energy = 100
        self.update_fov()
        self.update_dmap()
        self.emit("enter", depth=depth)
        self.msg(f"Depth {depth}: {self.level.name}.", C.GOLD)
        if depth == data.MAX_DEPTH:
            self.msg("A cold voice echoes through the halls: \"WHO DARES DESCEND SO FAR?\"",
                     C.YELLOW)

    def update_fov(self) -> None:
        lv, p = self.level, self.player
        self.visible = compute_fov(lv.opaque, lv.w, lv.h, p.x, p.y, FOV_RADIUS)
        for x, y in self.visible:
            lv.explored[y][x] = True
        # Spot hidden traps nearby.
        chance, reach = (0.35, 2) if p.cls == "rogue" else (0.08, 1)
        for (tx, ty), kind in list(lv.traps.items()):
            if lv.tiles[ty][tx] != TRAP and chebyshev(p.x, p.y, tx, ty) <= reach \
                    and (tx, ty) in self.visible and self.rng.random() < chance:
                lv.set(tx, ty, TRAP)
                self.msg(f"You spot a {data.TRAPS[kind]['name']}.", C.ORANGE)

    def update_dmap(self) -> None:
        lv, p = self.level, self.player
        self.dmap = distance_map(lv.w, lv.h, [(p.x, p.y)], lv.passable_for_path, limit=60)

    # --- turn structure -------------------------------------------------------------

    def end_turn(self) -> None:
        """The player has spent an action; let the world catch up."""
        p = self.player
        p.energy -= 100
        p.turns += 1
        self.update_dmap()
        while not self.dead:
            while p.energy < 100 and not self.dead:
                self._tick()
            if self.dead or not (p.has("frozen") or p.has("stunned")):
                break
            self.msg("You cannot move!", C.CYAN)
            p.energy -= 100
        self.update_fov()

    def _tick(self) -> None:
        p = self.player
        p.energy += p.speed
        for m in list(self.level.monsters):
            if not m.alive:
                continue
            m.energy += m.speed
            while m.energy >= 100 and m.alive and not self.dead:
                m.energy -= 100
                self._monster_act(m)
        if self.dead:
            return
        self._tick_statuses(p)
        for m in list(self.level.monsters):
            if m.alive:
                self._tick_statuses(m)
        self._regenerate()
        self.level.monsters = [m for m in self.level.monsters if m.alive]

    def _tick_statuses(self, a) -> None:
        if a.has("poison"):
            self.damage(a, 1 + self.depth // 4, None, cause="poison", quiet=True)
        if a.alive and a.has("burning"):
            immune = a.fire_immune if a.is_player else a.d.get("fire_immune")
            if not immune:
                self.damage(a, 2 + self.depth // 3, None, cause="flames", quiet=True)
                self.emit("burst", x=a.x, y=a.y, color=C.ORANGE, n=3, speed=4, glyphs="'.*")
            else:
                a.statuses.pop("burning", None)
        for k in list(a.statuses):
            a.statuses[k] -= 1
            if a.statuses[k] <= 0:
                del a.statuses[k]
                if a.is_player:
                    ended = {"haste": "You slow down.", "rage": "Your rage subsides.",
                             "poison": "The poison wears off.", "burning": "The flames die out.",
                             "confused": "Your head clears.", "frozen": "The ice cracks free."}
                    if k in ended:
                        self.msg(ended[k], C.UI_DIM)

    def _regenerate(self) -> None:
        p = self.player
        p.regen_clock += 1
        every = 2 if p.ring("ring_regen") else max(3, 9 - p.level // 2)
        if p.regen_clock >= every:
            p.regen_clock = 0
            if p.hp < p.max_hp and not p.has("poison"):
                p.hp += 1
        p.mana_clock += 1
        every = p.cdata["mp_regen"]
        if p.ring("ring_wizardry"):
            every = max(1, every // 2)
        if p.mana_clock >= every:
            p.mana_clock = 0
            p.mp = min(p.max_mp, p.mp + 1)
        for m in self.level.monsters:
            if m.d.get("regen") and m.hp < m.max_hp:
                m.hp = min(m.max_hp, m.hp + m.d["regen"])

    # --- combat ---------------------------------------------------------------------

    def attack(self, a, d, mult: float = 1.0, force_crit: bool = False,
               sure_hit: bool = False) -> bool:
        """Melee attack. Returns True on a hit."""
        sneak = a.is_player and isinstance(d, Monster) and d.asleep
        chance = max(10, min(97, 72 + 4 * (a.atk - d.defense)))
        if d.has("frozen") or d.has("stunned"):
            chance = 100
        if not (sneak or sure_hit or self.rng.randint(1, 100) <= chance):
            self.emit("text", x=d.x, y=d.y, text="miss", color=C.UI_DIM)
            if self.can_see(a) or self.can_see(d):
                verb = "miss" if a.is_player else "misses"
                self.msg(f"{self.the(a).capitalize()} {verb} {self.the(d)}.", C.UI_DIM)
            self._wake(d)
            return False
        n, s, b = a.dmg if a.is_player else a.base_dmg
        dmg = self.roll(n, s, b)
        crit_chance = a.crit if a.is_player else 5
        if a.is_player and a.has("empowered"):
            force_crit = True
            a.statuses.pop("empowered", None)
        crit = force_crit or sneak or self.rng.randint(1, 100) <= crit_chance
        if crit:
            dmg = int(dmg * (2.6 if a.is_player and a.cls == "rogue" else 2.0))
        dmg = max(1, int((dmg - self.rng.randint(0, d.armor)) * mult))
        if a.is_player and sneak:
            self.msg(f"You strike the sleeping {d.name}!", C.YELLOW)
        self.damage(d, dmg, a, crit=crit)
        if a.alive and d.alive and not a.is_player:
            md = a.d
            if md.get("poison") and not d.has("poison"):
                d.add_status("poison", md["poison"] + self.depth // 2)
                self.msg("You are poisoned!", C.GREEN)
            if md.get("burn") and not d.fire_immune:
                d.add_status("burning", md["burn"])
                self.msg("You catch fire!", C.ORANGE)
            if md.get("drain") and d.mp > 0:
                d.mp = max(0, d.mp - md["drain"])
                a.hp = min(a.max_hp, a.hp + md["drain"])
                self.msg(f"The {a.name} drains your energy.", C.PURPLE)
        return True

    def damage(self, t, amount: int, source, crit: bool = False, cause: str = "",
               quiet: bool = False, color=None) -> None:
        if not t.alive:
            return
        if not t.is_player and t.has("marked"):
            amount *= 2
        t.hp -= amount
        self.emit("hit", id=t.id, x=t.x, y=t.y)
        num_color = color or (C.RED if t.is_player else C.YELLOW if crit else C.WHITE)
        self.emit("text", x=t.x, y=t.y, text=str(amount) + ("!" if crit else ""), color=num_color)
        self.emit("burst", x=t.x, y=t.y, color=(200, 30, 30) if t.is_player else
                  C.scale(t.color, 0.9), n=4 + min(10, amount // 2), speed=6, glyphs="·.,'")
        if crit or amount >= 12:
            self.emit("shake", power=2 if crit else 1)
        if not quiet and (self.can_see(t) or (source and self.can_see(source))):
            if source is None:
                pass
            elif source.is_player:
                word = "CRITICALLY hit" if crit else "hit"
                self.msg(f"You {word} {self.the(t)} for {amount}.", C.YELLOW if crit else C.UI_TEXT)
            elif t.is_player:
                word = "critically hits" if crit else "hits"
                self.msg(f"{self.the(source).capitalize()} {word} you for {amount}.", C.RED)
            else:
                self.msg(f"{self.the(source).capitalize()} hits {self.the(t)}.", C.UI_DIM)
        if t.hp <= 0:
            self._kill(t, source, cause)
            return
        if not t.is_player:
            self._wake(t)
            t.hunting = True
            if t.d.get("splits") and t.hp >= 4:
                self._split(t)
            if t.ai == "blink" and self.rng.random() < 0.5:
                self._blink_near_player(t)

    def _kill(self, t, source, cause: str) -> None:
        if t.is_player:
            t.hp = 0
            self.dead = True
            if cause:
                t.killed_by = cause
            elif source is None:
                t.killed_by = "misfortune"
            elif source.name.startswith("the "):
                t.killed_by = source.name
            else:
                t.killed_by = f"a {source.name}"
            self.msg("You die...", C.RED)
            self.emit("death")
            return
        p = self.player
        self.emit("burst", x=t.x, y=t.y, color=t.color, n=18, speed=9, glyphs="*·+x")
        if self.can_see(t):
            self.msg(f"{self.the(t).capitalize()} dies.", C.ORANGE)
        p.kills += 1
        self.gain_xp(t.d["xp"])
        lv = self.level
        if lv.tiles[t.y][t.x] == FLOOR and self.rng.random() < 0.3:
            lv.set(t.x, t.y, BONES)
        if self.rng.random() < 0.12 + (0.5 if t.d["xp"] >= 60 else 0):
            keys = [k for k, d in data.ITEMS.items()
                    if d["kind"] != "gold" and d["depth"] <= self.depth + 1]
            lv.items.append(Item(self.rng.choice(keys), t.x, t.y, rng=self.rng))
        elif self.rng.random() < 0.25:
            lv.items.append(Item("gold", t.x, t.y, count=self.rng.randint(3, 10) * self.depth))
        if t.key == "king":
            self.won = True
            self.emit("victory")
            self.msg("The Hollow King crumbles to dust. The Depths fall silent.", C.GOLD)

    def _split(self, m: Monster) -> None:
        if sum(1 for o in self.level.monsters if o.key == m.key) >= 8:
            return
        for dx, dy in self.rng.sample(NEIGHBORS, len(NEIGHBORS)):
            x, y = m.x + dx, m.y + dy
            if self.level.walkable(x, y) and not self.occupied(x, y):
                child = make_monster(m.key, x, y)
                child.hp = child.max_hp = m.hp // 2
                m.hp -= child.hp
                child.hunting = True
                self.level.monsters.append(child)
                if self.can_see(m):
                    self.msg(f"The {m.name} splits in two!", C.GREEN)
                return

    def _blink_near_player(self, m: Monster) -> None:
        p = self.player
        spots = [(p.x + dx, p.y + dy) for dx in range(-4, 5) for dy in range(-4, 5)
                 if 2 <= max(abs(dx), abs(dy))]
        spots = [s for s in spots if self.level.walkable(*s) and not self.occupied(*s)
                 and s in self.visible]
        if spots:
            self.emit("burst", x=m.x, y=m.y, color=C.PURPLE, n=8, speed=5, glyphs="·:")
            m.x, m.y = self.rng.choice(spots)
            self.emit("burst", x=m.x, y=m.y, color=C.PURPLE, n=8, speed=5, glyphs="·:")
            if self.can_see(m):
                self.msg(f"The {m.name} flickers through the shadows.", C.PURPLE)

    def _wake(self, m) -> None:
        if isinstance(m, Monster) and m.asleep:
            m.asleep = False
            m.hunting = True

    def gain_xp(self, amount: int) -> None:
        p = self.player
        p.xp += amount
        self.total_xp += amount
        while p.xp >= p.xp_next:
            p.xp -= p.xp_next
            p.level += 1
            cd = p.cdata
            p.max_hp += cd["hp_per_level"]
            p.hp = min(p.max_hp, p.hp + cd["hp_per_level"] + p.max_hp // 4)
            p.max_mp += cd["mp_per_level"]
            p.mp = min(p.max_mp, p.mp + cd["mp_per_level"] + 4)
            p.base_atk += 1
            if p.level % 2 == 0:
                p.base_df += 1
            self.msg(f"You reach level {p.level}!", C.GOLD)
            self.emit("levelup", x=p.x, y=p.y)
            for a in p.all_abilities:
                if data.ABILITIES[a].get("unlock") == p.level:
                    self.msg(f"New ability unlocked: {data.ABILITIES[a]['name']}!", C.GOLD)

    # --- monster AI -----------------------------------------------------------------

    def _monster_act(self, m: Monster) -> None:
        p = self.player
        if m.has("frozen") or m.has("stunned"):
            return
        dist = chebyshev(m.x, m.y, p.x, p.y)
        sees = (m.x, m.y) in self.visible and dist <= FOV_RADIUS
        if m.asleep:
            if sees and dist <= 8:
                chance = (0.1 if p.cls == "rogue" else 0.28) * (2 if dist <= 2 else 1)
                if self.rng.random() < chance:
                    m.asleep = False
                    m.hunting = True
                    self.msg(f"The {m.name} notices you!", C.ORANGE)
                    self.emit("text", x=m.x, y=m.y, text="!", color=C.ORANGE)
            return
        if m.cooldown > 0:
            m.cooldown -= 1
        if m.summon_cooldown > 0:
            m.summon_cooldown -= 1
        if sees:
            m.hunting = True
            m.last_seen = (p.x, p.y)
            m.lost_turns = 0
        elif m.hunting:
            m.lost_turns += 1
            if m.lost_turns > 20:
                m.hunting = False
        if m.has("confused"):
            self._random_step(m)
            return
        if m.has("fear"):
            self._step(m, flee=True)
            return
        if not m.hunting:
            if self.rng.random() < 0.25:
                self._random_step(m)
            return
        if m.ai == "erratic" and self.rng.random() < 0.5:
            self._random_step(m)
            return
        if m.ai == "boss" and self._boss_act(m, dist, sees):
            return
        if m.ai == "caster" and sees and self._caster_act(m):
            return
        r = m.d.get("ranged")
        if r and sees and dist <= r["range"] and m.cooldown == 0 and self._clear_shot(m, p):
            if dist > 1 or (m.ai != "ranged" and self.rng.random() < 0.35):
                if m.ai != "ranged" or dist > 1:
                    self._monster_shoot(m)
                    return
        if m.ai == "ranged" and r and dist <= 2 and sees and self.rng.random() < 0.5:
            if self._step(m, flee=True):
                return
        if dist == 1:
            self.attack(m, p)
            return
        self._step(m)

    def _clear_shot(self, a, b) -> bool:
        for x, y in line(a.x, a.y, b.x, b.y)[1:-1]:
            if self.level.opaque[y][x] or self.monster_at(x, y):
                return False
        return True

    def _monster_shoot(self, m: Monster) -> None:
        p, r = self.player, m.d["ranged"]
        path = line(m.x, m.y, p.x, p.y)[1:]
        self.emit("bolt", path=path, glyph=r["glyph"], color=r["color"])
        if self.can_see(m):
            self.msg(f"The {m.name} {r['verb']} you.", C.ORANGE)
        m.cooldown = r.get("cooldown", 0)
        if r.get("radius"):
            self.emit("explode", x=p.x, y=p.y, radius=r["radius"], color=r["color"])
            self._hurt_player_spell(self.roll(*r["dmg"]) + self.depth // 2, m, r)
            return
        chance = max(15, min(95, 70 + 4 * (m.atk - p.defense)))
        if self.rng.randint(1, 100) > chance:
            self.emit("text", x=p.x, y=p.y, text="miss", color=C.UI_DIM)
            self.msg("It misses.", C.UI_DIM)
            return
        self._hurt_player_spell(self.roll(*r["dmg"]) + self.depth // 3, m, r)

    def _hurt_player_spell(self, dmg: int, src, r: dict) -> None:
        p = self.player
        if r.get("burn") and p.fire_immune:
            dmg //= 3
            self.msg("Your dragonscale shrugs off the flames.", C.ORANGE)
        self.damage(p, max(1, dmg - self.rng.randint(0, p.armor // 2)), src)
        if p.alive and r.get("burn") and not p.fire_immune:
            p.add_status("burning", r["burn"])

    def _caster_act(self, m: Monster) -> bool:
        if m.cooldown == 0:
            for o in self.level.monsters:
                if o is not m and o.alive and o.hp < o.max_hp * 0.6 and \
                        chebyshev(m.x, m.y, o.x, o.y) <= 6:
                    heal = 8 + self.depth * 2
                    o.hp = min(o.max_hp, o.hp + heal)
                    m.cooldown = 4
                    self.emit("burst", x=o.x, y=o.y, color=C.GREEN, n=10, speed=3, glyphs="+·")
                    if self.can_see(m):
                        self.msg(f"The {m.name} mends the {o.name}'s wounds.", C.PURPLE)
                    return True
        if m.d.get("summons") and m.summon_cooldown == 0:
            self._summon(m, m.d["summons"], 2)
            m.summon_cooldown = 12
            return True
        return False

    def _summon(self, m: Monster, key: str, count: int) -> None:
        made = 0
        for dx, dy in self.rng.sample(NEIGHBORS, len(NEIGHBORS)):
            x, y = m.x + dx, m.y + dy
            if made < count and self.level.walkable(x, y) and not self.occupied(x, y):
                s = make_monster(key, x, y)
                s.hunting = True
                self.level.monsters.append(s)
                self.emit("burst", x=x, y=y, color=s.color, n=10, speed=4, glyphs="·*")
                made += 1
        if made and self.can_see(m):
            self.msg(f"The {m.name.removeprefix('the ')} summons {made} "
                     f"{data.MONSTERS[key]['name']}{'s' if made > 1 else ''}!", C.PURPLE)

    def _boss_act(self, m: Monster, dist: int, sees: bool) -> bool:
        p = self.player
        if m.phase == 1 and m.hp <= m.max_hp * 0.6:
            m.phase = 2
            self.msg("The Hollow King roars: \"KNEEL!\" Shadows pour from the walls.", C.YELLOW)
            self.emit("shake", power=3)
            self._summon(m, "wraith", 2)
            m.summon_cooldown = 14
            return True
        if m.phase == 2 and m.hp <= m.max_hp * 0.3:
            m.phase = 3
            m.base_speed = 135
            self.msg("The Hollow King's crown blazes. He moves with terrible speed!", C.YELLOW)
            self.emit("shake", power=3)
            self.emit("explode", x=m.x, y=m.y, radius=3, color=C.GOLD)
            return True
        if dist <= 1 and m.cooldown == 0 and self.rng.random() < 0.45:
            m.cooldown = 5
            self.msg("The Hollow King slams the ground! A shockwave tears outward.", C.GOLD)
            self.emit("explode", x=m.x, y=m.y, radius=2, color=C.GOLD)
            self.emit("shake", power=3)
            self.damage(p, self.roll(2, 8, 4), m)
            if p.alive:
                p.add_status("stunned", 1)
            return True
        if m.phase >= 2 and m.summon_cooldown == 0 and sees:
            self._summon(m, self.rng.choice(("wraith", "shade")), 2)
            m.summon_cooldown = 16
            return True
        if m.phase == 3 and dist > 2 and self.rng.random() < 0.25:
            for dx, dy in self.rng.sample(NEIGHBORS, 8):
                x, y = p.x + dx, p.y + dy
                if self.level.walkable(x, y) and not self.occupied(x, y):
                    self.emit("burst", x=m.x, y=m.y, color=C.GOLD, n=12, speed=6, glyphs="*·")
                    m.x, m.y = x, y
                    self.msg("The Hollow King steps through the air beside you!", C.YELLOW)
                    return True
        return False

    def _random_step(self, m: Monster) -> None:
        dx, dy = self.rng.choice(NEIGHBORS)
        x, y = m.x + dx, m.y + dy
        if self.level.walkable(x, y) and not self.occupied(x, y):
            m.x, m.y = x, y

    def _step(self, m: Monster, flee: bool = False) -> bool:
        dm = self.dmap
        here = dm[m.y][m.x]
        best, best_val = None, None
        options = list(NEIGHBORS)
        self.rng.shuffle(options)
        for dx, dy in options:
            x, y = m.x + dx, m.y + dy
            if not self.level.passable_for_path(x, y) or self.occupied(x, y):
                continue
            v = dm[y][x]
            if v >= INF:
                continue
            score = -v if flee else v
            if best_val is None or score < best_val:
                best, best_val = (x, y), score
        if best is None:
            return False
        if not flee and here < INF and best_val >= here:
            return False
        if flee and here < INF and -best_val <= here:
            return False
        x, y = best
        if self.level.tiles[y][x] == DOOR:
            self.level.set(x, y, OPEN_DOOR)
            return True
        m.x, m.y = x, y
        return True

    # --- player actions -------------------------------------------------------------
    # Each returns True if it used the player's turn.

    def move(self, dx: int, dy: int) -> bool:
        p, lv = self.player, self.level
        if p.has("confused") and self.rng.random() < 0.5:
            dx, dy = self.rng.choice(NEIGHBORS)
            self.msg("You stumble in confusion.", C.PINK)
        x, y = p.x + dx, p.y + dy
        m = self.monster_at(x, y)
        if m:
            self.attack(p, m)
            self._noise(x, y)
            self.end_turn()
            return True
        t = lv.tile(x, y)
        if t == DOOR:
            lv.set(x, y, OPEN_DOOR)
            self.msg("You open the door.", C.UI_DIM)
            self.end_turn()
            return True
        if t == CHEST:
            self._open_chest(x, y)
            self.end_turn()
            return True
        if t == FOUNTAIN:
            self._drink_fountain(x, y)
            return True
        if t in (LAVA, DEEP_WATER):
            self.msg(f"You can't walk into the {TILES[t][0]}.", C.UI_DIM)
            return False
        if not lv.walkable(x, y):
            return False
        p.x, p.y = x, y
        self._arrive()
        self.end_turn()
        return True

    def _arrive(self) -> None:
        p, lv = self.player, self.level
        gold = [i for i in lv.items_at(p.x, p.y) if i.key == "gold"]
        for g in gold:
            p.gold += g.count
            lv.items.remove(g)
            self.msg(f"You pick up {g.count} gold.", C.GOLD)
            self.emit("text", x=p.x, y=p.y, text=f"+{g.count}", color=C.GOLD)
        here = lv.items_at(p.x, p.y)
        if len(here) == 1:
            self.msg(f"You see {here[0].name} here. (g to pick up)", C.UI_TEXT)
        elif here:
            self.msg(f"You see {len(here)} items here. (g to pick up)", C.UI_TEXT)
        if lv.tiles[p.y][p.x] == STAIRS_DOWN:
            self.msg("There are stairs leading down here. (> to descend)", C.CYAN)
        trap = lv.traps.get((p.x, p.y))
        if trap:
            self._trigger_trap(trap)

    def _trigger_trap(self, kind: str) -> None:
        p, lv = self.player, self.level
        del lv.traps[(p.x, p.y)]
        lv.set(p.x, p.y, TRAP)
        name = data.TRAPS[kind]["name"]
        self.msg(f"You trigger a {name}!", C.ORANGE)
        if kind == "spike":
            self.emit("burst", x=p.x, y=p.y, color=C.GREY, n=10, speed=5, glyphs="^|")
            self.damage(p, self.roll(2, 5, self.depth), None, cause=f"a {name}")
        elif kind == "fire":
            self.emit("explode", x=p.x, y=p.y, radius=1, color=C.ORANGE)
            self.damage(p, self.roll(1, 6, self.depth // 2), None, cause=f"a {name}")
            if p.alive and not p.fire_immune:
                p.add_status("burning", 4)
        elif kind == "poison":
            p.add_status("poison", 6 + self.depth)
            self.msg("A dart pricks you. You feel sick.", C.GREEN)
        elif kind == "teleport":
            self._teleport_player()
        elif kind == "alarm":
            self.msg("A deafening shriek echoes through the halls!", C.YELLOW)
            self.emit("shake", power=1)
            for m in self.level.monsters:
                if chebyshev(m.x, m.y, p.x, p.y) <= 25:
                    m.asleep = False
                    m.hunting = True

    def _noise(self, x: int, y: int) -> None:
        for m in self.level.monsters:
            if m.asleep and chebyshev(m.x, m.y, x, y) <= 5 and self.rng.random() < 0.25:
                m.asleep = False
                m.hunting = True

    def _open_chest(self, x: int, y: int) -> None:
        lv = self.level
        lv.set(x, y, OPEN_CHEST)
        contents = lv.chests.pop((x, y), [])
        for item in contents:
            item.x, item.y = x, y
            lv.items.append(item)
        self.emit("burst", x=x, y=y, color=C.GOLD, n=20, speed=6, glyphs="*·$")
        self.msg("You pry open the chest. Treasure spills out!", C.GOLD)

    def _drink_fountain(self, x: int, y: int) -> None:
        p = self.player
        key = (self.depth, x, y)
        if key in self.used_fountains:
            self.msg("The fountain has run dry.", C.UI_DIM)
            return
        self.used_fountains.add(key)
        p.hp, p.mp = p.max_hp, p.max_mp
        p.statuses.pop("poison", None)
        p.statuses.pop("burning", None)
        self.emit("burst", x=p.x, y=p.y, color=C.CYAN, n=24, speed=4, glyphs="~·*")
        self.msg("You drink from the fountain. You feel completely restored.", C.CYAN)
        self.end_turn()

    def wait(self) -> bool:
        self.end_turn()
        return True

    def pickup(self) -> bool:
        p, lv = self.player, self.level
        here = [i for i in lv.items_at(p.x, p.y) if i.key != "gold"]
        if not here:
            self.msg("There is nothing here to pick up.", C.UI_DIM)
            return False
        for item in here:
            if not self._add_to_inventory(item):
                self.msg("Your pack is full.", C.RED)
                break
            lv.items.remove(item)
            self.msg(f"You pick up {item.name}.", item.d["color"])
        self.end_turn()
        return True

    def _add_to_inventory(self, item: Item) -> bool:
        p = self.player
        for other in p.inventory:
            if other.stacks_with(item):
                other.count += item.count
                return True
        if len(p.inventory) >= INVENTORY_LIMIT:
            return False
        p.inventory.append(item)
        return True

    def drop(self, item: Item) -> bool:
        p = self.player
        if item in p.inventory:
            p.inventory.remove(item)
        else:
            for slot, e in p.equipment.items():
                if e is item:
                    p.equipment[slot] = None
        item.x, item.y = p.x, p.y
        self.level.items.append(item)
        self.msg(f"You drop {item.name}.", C.UI_DIM)
        self.end_turn()
        return True

    def descend(self) -> bool:
        p = self.player
        if self.level.tiles[p.y][p.x] != STAIRS_DOWN:
            self.msg("There are no stairs down here.", C.UI_DIM)
            return False
        self.enter_level(self.depth + 1)
        return True

    def _teleport_player(self) -> None:
        p, lv = self.player, self.level
        spots = [(x, y) for y in range(lv.h) for x in range(lv.w)
                 if lv.tiles[y][x] == FLOOR and not self.occupied(x, y)
                 and chebyshev(x, y, p.x, p.y) > 12 and (x, y) not in lv.traps]
        if not spots:
            return
        self.emit("burst", x=p.x, y=p.y, color=C.PURPLE, n=16, speed=6, glyphs="·*")
        p.x, p.y = self.rng.choice(spots)
        self.emit("burst", x=p.x, y=p.y, color=C.PURPLE, n=16, speed=6, glyphs="·*")
        self.msg("Space folds around you.", C.PURPLE)
        self.update_fov()

    # --- equipment and items -----------------------------------------------------

    def equip(self, item: Item) -> bool:
        p = self.player
        slot = item.d["kind"]
        if p.equipment.get(slot) is item:
            if not self._add_to_inventory(item):
                self.msg("Your pack is full.", C.RED)
                return False
            p.equipment[slot] = None
            self.msg(f"You remove {item.name}.", C.UI_TEXT)
            self.end_turn()
            return True
        old = p.equipment[slot]
        p.inventory.remove(item)
        p.equipment[slot] = item
        if old:
            p.inventory.append(old)
        verb = {"weapon": "wield", "armor": "put on", "ring": "slip on"}[slot]
        self.msg(f"You {verb} {item.name}.", item.d["color"])
        self.end_turn()
        return True

    def use_item(self, item: Item, target: tuple[int, int] | None = None) -> bool:
        d = item.d
        kind = d["kind"]
        if kind in ("weapon", "armor", "ring"):
            return self.equip(item)
        p = self.player
        used = getattr(self, f"_use_{item.key}")(item, target)
        if not used:
            return False
        if kind == "wand":
            item.charges -= 1
            if item.charges <= 0:
                p.inventory.remove(item)
                self.msg(f"The {d['name']} crumbles to dust.", C.UI_DIM)
        else:
            item.count -= 1
            if item.count <= 0:
                p.inventory.remove(item)
        if not self.dead:
            self.end_turn()
        return True

    def _heal(self, amount: int) -> None:
        p = self.player
        amount = min(amount, p.max_hp - p.hp)
        p.hp += amount
        self.emit("burst", x=p.x, y=p.y, color=C.GREEN, n=14, speed=3, glyphs="+·")
        if amount:
            self.emit("text", x=p.x, y=p.y, text=f"+{amount}", color=C.GREEN)

    def _use_heal(self, item, target):
        self._heal(max(15, int(self.player.max_hp * 0.45)))
        self.player.statuses.pop("poison", None)
        self.msg("You feel much better.", C.GREEN)
        return True

    def _use_greater_heal(self, item, target):
        self._heal(int(self.player.max_hp * 0.9))
        self.player.statuses.pop("poison", None)
        self.player.statuses.pop("burning", None)
        self.msg("Warmth floods through you. Your wounds vanish.", C.GREEN)
        return True

    def _use_mana(self, item, target):
        p = self.player
        p.mp = min(p.max_mp, p.mp + max(12, int(p.max_mp * 0.7)))
        self.emit("burst", x=p.x, y=p.y, color=C.BLUE, n=14, speed=3, glyphs="*·")
        self.msg("Your mind sharpens. Mana surges back.", C.BLUE)
        return True

    def _use_haste(self, item, target):
        self.player.add_status("haste", 20)
        self.msg("The world slows around you.", C.YELLOW)
        return True

    def _use_strength(self, item, target):
        p = self.player
        p.bonus_atk += 1
        p.bonus_dmg += 1
        self.emit("levelup", x=p.x, y=p.y)
        self.msg("Strength courses through your limbs.", C.ORANGE)
        return True

    def _use_vitality(self, item, target):
        p = self.player
        p.max_hp += 10
        p.hp += 10
        self._heal(0)
        self.msg("You feel more resilient.", C.GREEN)
        return True

    def _use_teleport(self, item, target):
        self._teleport_player()
        return True

    def _use_mapping(self, item, target):
        lv = self.level
        for y in range(lv.h):
            for x in range(lv.w):
                if lv.tiles[y][x] != WALL or any(lv.walkable(x + dx, y + dy) for dx, dy in NEIGHBORS):
                    lv.explored[y][x] = True
        self.emit("flash", color=C.CYAN)
        self.msg("The layout of this depth blooms in your mind.", C.CYAN)
        return True

    def _use_fireball(self, item, target):
        if not target:
            return False
        self._explosion(target, 2, self.roll(4, 6, self.depth), C.ORANGE, burn=3)
        self.msg("A fireball roars into the darkness!", C.ORANGE)
        return True

    def _use_lightning(self, item, target):
        ms = self.visible_monsters()
        if not ms:
            self.msg("There are no enemies in sight.", C.UI_DIM)
            return False
        m = ms[0]
        p = self.player
        self.emit("beam", path=line(p.x, p.y, m.x, m.y)[1:], color=(220, 235, 255))
        self.emit("flash", color=(200, 220, 255))
        self.msg(f"Lightning strikes the {m.name}!", (220, 235, 255))
        self.damage(m, self.roll(5, 6, self.depth), p, color=(200, 230, 255))
        return True

    def _use_confusion(self, item, target):
        ms = self.visible_monsters()
        for m in ms:
            m.add_status("confused", 8)
            self._wake(m)
            self.emit("text", x=m.x, y=m.y, text="?", color=C.PINK)
        self.msg("Your foes reel in confusion." if ms else "The scroll's light fades harmlessly.",
                 C.PINK)
        return True

    def _use_enchant_weapon(self, item, target):
        w = self.player.equipment["weapon"]
        if not w:
            self.msg("Your hands glow briefly, then fade.", C.UI_DIM)
            return True
        w.enchant += 1
        self.msg(f"Your {w.d['name']} glows bright gold.", C.GOLD)
        self.emit("burst", x=self.player.x, y=self.player.y, color=C.GOLD, n=16, speed=4, glyphs="*·")
        return True

    def _use_enchant_armor(self, item, target):
        a = self.player.equipment["armor"]
        if not a:
            self.msg("Your skin tingles briefly.", C.UI_DIM)
            return True
        a.enchant += 1
        self.msg(f"Your {a.d['name']} gleams with new strength.", C.TEAL)
        self.emit("burst", x=self.player.x, y=self.player.y, color=C.TEAL, n=16, speed=4, glyphs="*·")
        return True

    def _use_wand_fire(self, item, target):
        m = self._bolt(target, "*", C.ORANGE)
        if m:
            self.damage(m, self.roll(3, 6, self.depth // 2), self.player, color=C.ORANGE)
            if m.alive and not m.d.get("fire_immune"):
                m.add_status("burning", 4)
        return target is not None

    def _use_wand_frost(self, item, target):
        m = self._bolt(target, "*", C.CYAN)
        if m:
            self.damage(m, self.roll(2, 6, self.depth // 2), self.player, color=C.CYAN)
            if m.alive:
                m.add_status("frozen", 4)
                self.msg(f"The {m.name} is frozen solid!", C.CYAN)
        return target is not None

    def _use_wand_lightning(self, item, target):
        if not target:
            return False
        p = self.player
        m = self._bolt(target, None, None)
        if not m:
            return True
        hit = {m.id}
        src, dmg = (p.x, p.y), self.roll(4, 6, self.depth // 2)
        cur = m
        for _ in range(4):
            self.emit("beam", path=line(src[0], src[1], cur.x, cur.y)[1:], color=(220, 235, 255))
            self.damage(cur, dmg, p, color=(200, 230, 255))
            src = (cur.x, cur.y)
            nxt = [o for o in self.visible_monsters() if o.id not in hit and
                   chebyshev(o.x, o.y, src[0], src[1]) <= 4]
            if not nxt:
                break
            cur = nxt[0]
            hit.add(cur.id)
            dmg = max(1, dmg * 3 // 4)
        self.emit("flash", color=(200, 220, 255))
        self.msg("Lightning arcs between your foes!", (220, 235, 255))
        return True

    def _bolt(self, target, glyph, color):
        """Fire a projectile at a target cell; returns the monster it hits, if any."""
        if not target:
            return None
        p, lv = self.player, self.level
        path = []
        for x, y in line(p.x, p.y, target[0], target[1])[1:]:
            if lv.opaque[y][x] or not (lv.walkable(x, y) or lv.tiles[y][x] in (LAVA, DEEP_WATER)):
                break
            path.append((x, y))
            m = self.monster_at(x, y)
            if m:
                if glyph:
                    self.emit("bolt", path=path, glyph=glyph, color=color)
                self._wake(m)
                return m
        if glyph and path:
            self.emit("bolt", path=path, glyph=glyph, color=color)
        return None

    def _explosion(self, center, radius: int, dmg: int, color, burn: int = 0,
                   freeze: int = 0, stun: int = 0, hurts_player: bool = False) -> None:
        cx, cy = center
        self.emit("explode", x=cx, y=cy, radius=radius, color=color)
        self.emit("shake", power=2 + radius // 2)
        p = self.player
        for m in list(self.level.monsters):
            if m.alive and chebyshev(m.x, m.y, cx, cy) <= radius:
                self.damage(m, dmg, p, color=color)
                if m.alive:
                    if burn and not m.d.get("fire_immune"):
                        m.add_status("burning", burn)
                    if freeze:
                        m.add_status("frozen", freeze)
                    if stun:
                        m.add_status("stunned", stun)
        if hurts_player and chebyshev(p.x, p.y, cx, cy) <= radius:
            self.damage(p, dmg // 2, None, cause="your own spell")

    # --- abilities ----------------------------------------------------------------

    def use_ability(self, key: str, target: tuple[int, int] | None = None) -> bool:
        p = self.player
        a = data.ABILITIES[key]
        if key not in p.abilities:
            self.msg(f"{a['name']} unlocks at level {a.get('unlock', 1)}.", C.UI_DIM)
            return False
        if p.mp < a["cost"]:
            self.msg(f"Not enough mana for {a['name']} ({a['cost']} MP).", C.BLUE)
            return False
        if not getattr(self, f"_ab_{key}")(target):
            return False
        p.mp -= a["cost"]
        self.end_turn()
        return True

    def _adjacent_monsters(self, radius: int = 1):
        p = self.player
        return [m for m in self.level.monsters
                if m.alive and chebyshev(m.x, m.y, p.x, p.y) <= radius
                and (m.x, m.y) in self.visible]

    def _ab_cleave(self, target):
        ms = self._adjacent_monsters()
        if not ms:
            self.msg("There is nothing next to you to cleave.", C.UI_DIM)
            return False
        p = self.player
        self.emit("ring", x=p.x, y=p.y, radius=1, color=(255, 210, 140))
        self.msg("You sweep your weapon in a wide arc!", (255, 210, 140))
        for m in ms:
            self.attack(p, m, mult=1.1)
        return True

    def _ab_warcry(self, target):
        p = self.player
        self.emit("ring", x=p.x, y=p.y, radius=6, color=C.ORANGE)
        self.emit("shake", power=2)
        p.add_status("rage", 10)
        for m in self.visible_monsters():
            if chebyshev(m.x, m.y, p.x, p.y) <= 8:
                m.add_status("stunned", 2)
                self._wake(m)
        self.msg("You let out a thunderous war cry!", C.ORANGE)
        return True

    def _ab_second_wind(self, target):
        p = self.player
        if p.hp >= p.max_hp:
            self.msg("You are already at full health.", C.UI_DIM)
            return False
        self._heal(int(p.max_hp * 0.35))
        self.msg("You catch your second wind.", C.GREEN)
        return True

    def _ab_firebolt(self, target):
        m = self._bolt(target, "*", C.ORANGE)
        if target is None:
            return False
        if m:
            self.damage(m, self.roll(2, 6, self.player.spell_power), self.player, color=C.ORANGE)
            if m.alive and not m.d.get("fire_immune"):
                m.add_status("burning", 3)
        return True

    def _ab_frost_nova(self, target):
        p = self.player
        self.emit("ring", x=p.x, y=p.y, radius=2, color=C.CYAN)
        ms = self._adjacent_monsters(2)
        for m in ms:
            self.damage(m, self.roll(2, 4, p.spell_power // 2), p, color=C.CYAN)
            if m.alive:
                m.add_status("frozen", 3)
        self.msg("A ring of frost bursts from your hands!", C.CYAN)
        return True

    def _ab_blink(self, target):
        p, lv = self.player, self.level
        if not target or target not in self.visible or not lv.walkable(*target) \
                or self.occupied(*target) or chebyshev(p.x, p.y, *target) > 7:
            self.msg("You can't blink there.", C.UI_DIM)
            return False
        self.emit("burst", x=p.x, y=p.y, color=C.PURPLE, n=14, speed=6, glyphs="·*")
        self.emit("beam", path=line(p.x, p.y, *target)[1:], color=(190, 140, 255))
        p.x, p.y = target
        self.emit("burst", x=p.x, y=p.y, color=C.PURPLE, n=14, speed=6, glyphs="·*")
        self.msg("You blink across the gap.", C.PURPLE)
        self._arrive()
        self.update_fov()
        return True

    def _ab_meteor(self, target):
        if not target or target not in self.visible:
            return False
        self.msg("A meteor screams down from the dark!", (255, 120, 50))
        self._explosion(target, 2, self.roll(5, 6, self.player.spell_power), (255, 90, 30),
                        burn=4)
        return True

    def _ab_knives(self, target):
        if target is None:
            return False
        p = self.player
        for _ in range(3):
            m = self._bolt(target, "-", (220, 225, 235))
            if m and m.alive:
                if self.rng.randint(1, 100) <= max(20, min(97, 75 + 4 * (p.atk - m.defense))):
                    crit = self.rng.randint(1, 100) <= p.crit
                    dmg = self.roll(1, 6, p.dmg[2] // 2) * (2 if crit else 1)
                    self.damage(m, dmg, p, crit=crit)
                else:
                    self.emit("text", x=m.x, y=m.y, text="miss", color=C.UI_DIM)
        return True

    def _ab_shadowstep(self, target):
        p = self.player
        m = self.monster_at(*target) if target else None
        if not m or (m.x, m.y) not in self.visible:
            self.msg("Choose a visible enemy to step behind.", C.UI_DIM)
            return False
        dx = (m.x > p.x) - (m.x < p.x)
        dy = (m.y > p.y) - (m.y < p.y)
        spots = [(m.x + dx, m.y + dy)] + [(m.x + a, m.y + b) for a, b in NEIGHBORS]
        for x, y in spots:
            if self.level.walkable(x, y) and not self.occupied(x, y):
                self.emit("burst", x=p.x, y=p.y, color=(150, 120, 200), n=12, speed=5, glyphs="·:")
                p.x, p.y = x, y
                self.emit("burst", x=p.x, y=p.y, color=(150, 120, 200), n=12, speed=5, glyphs="·:")
                p.add_status("empowered", 4)
                self.msg(f"You melt into the shadows behind the {m.name}.", (170, 140, 220))
                self.update_fov()
                return True
        self.msg("There is no room behind it.", C.UI_DIM)
        return False

    def _ab_smoke(self, target):
        p = self.player
        self.emit("explode", x=p.x, y=p.y, radius=3, color=(150, 150, 165))
        ms = self._adjacent_monsters(3)
        for m in ms:
            m.add_status("confused", 5)
            self.emit("text", x=m.x, y=m.y, text="?", color=C.PINK)
        self.msg("You vanish in a cloud of choking smoke!", (190, 190, 205))
        return True

    def _ab_earthshatter(self, target):
        p = self.player
        self.emit("ring", x=p.x, y=p.y, radius=2, color=(200, 160, 100))
        self.emit("shake", power=4)
        for m in self._adjacent_monsters(2):
            self.damage(m, self.roll(3, 8, p.spell_power), p, color=(220, 180, 120))
            if m.alive:
                m.add_status("stunned", 2)
        self.msg("You shatter the earth beneath your foes!", (220, 180, 120))
        return True

    def _ab_assassinate(self, target):
        m = self.monster_at(*target) if target else None
        if not m or (m.x, m.y) not in self.visible:
            self.msg("Choose a visible enemy to mark.", C.UI_DIM)
            return False
        m.add_status("marked", 8)
        self.emit("text", x=m.x, y=m.y, text="MARKED", color=C.RED)
        self.msg(f"You mark the {m.name} for death. It takes double damage.", C.RED)
        return True

    # --- automation ----------------------------------------------------------------

    def threats(self) -> list[Monster]:
        """Visible enemies that can actually get at you (not stranded across lava)."""
        p = self.player
        out = []
        for m in self.visible_monsters():
            d = chebyshev(m.x, m.y, p.x, p.y)
            if m.asleep and d > 3:
                continue
            reachable = self.dmap is not None and self.dmap[m.y][m.x] < INF
            shooter = "ranged" in m.d and d <= m.d["ranged"]["range"] and self._clear_shot(m, p)
            if reachable or shooter or d <= 1:
                out.append(m)
        return out

    def danger(self) -> bool:
        return bool(self.threats())

    def _safe(self, x: int, y: int) -> bool:
        lv = self.level
        t = lv.tile(x, y)
        return lv.explored[y][x] and t != TRAP and (lv.walkable(x, y) or t == DOOR)

    def _step_downhill(self, dist) -> bool:
        p = self.player
        best, best_v = None, dist[p.y][p.x]
        for dx, dy in NEIGHBORS:
            x, y = p.x + dx, p.y + dy
            if self.level.inside(x, y) and dist[y][x] < best_v and not self.monster_at(x, y):
                best, best_v = (dx, dy), dist[y][x]
        if best is None:
            return False
        return self.move(*best)

    def explore_step(self) -> str | None:
        """Take one auto-explore step. Returns a reason to stop, or None to continue."""
        if self.danger():
            return "You see an enemy."
        lv, p = self.level, self.player
        here = [i for i in lv.items_at(p.x, p.y) if i.key != "gold"]
        if here and len(p.inventory) < INVENTORY_LIMIT:
            self.pickup()
            return None
        targets = []
        for y in range(lv.h):
            for x in range(lv.w):
                if not self._safe(x, y):
                    continue
                if any(lv.inside(x + dx, y + dy) and not lv.explored[y + dy][x + dx]
                       for dx, dy in NEIGHBORS):
                    targets.append((x, y))
        if len(p.inventory) < INVENTORY_LIMIT:
            targets += [(i.x, i.y) for i in lv.items if lv.explored[i.y][i.x]
                        and (i.x, i.y) != (p.x, p.y) and self._safe(i.x, i.y)]
        targets += [c for c in lv.chests if lv.explored[c[1]][c[0]]]
        if not targets:
            return "There is nothing left to explore here."
        chest_spots = set(lv.chests)
        dist = distance_map(lv.w, lv.h, targets,
                            lambda x, y: self._safe(x, y) and (x, y) not in chest_spots)
        for c in chest_spots:
            if chebyshev(p.x, p.y, *c) == 1:
                self.move(c[0] - p.x, c[1] - p.y)
                return None
        if dist[p.y][p.x] >= INF:
            return "There is nothing more you can reach."
        if not self._step_downhill(dist):
            return "Exploration interrupted."
        return None

    def travel_step(self, goal: tuple[int, int]) -> str | None:
        if self.danger():
            return "You see an enemy."
        p, lv = self.player, self.level
        if (p.x, p.y) == goal:
            return "arrived"
        if not lv.explored[goal[1]][goal[0]]:
            return "You haven't found the way down yet."
        dist = distance_map(lv.w, lv.h, [goal], self._safe)
        if dist[p.y][p.x] >= INF or not self._step_downhill(dist):
            return "You can't find a path there."
        return None

    def rest_step(self) -> str | None:
        p = self.player
        if self.danger():
            return "You see an enemy."
        if p.hp >= p.max_hp and p.mp >= p.max_mp:
            return "You feel rested."
        self.wait()
        return None


def save(game: Game, path: str) -> None:
    import os

    game.fx.clear()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(game, f)


def load(path: str) -> Game:
    with open(path, "rb") as f:
        return pickle.load(f)
