"""The player and monsters."""

import itertools

from depths import data

_ids = itertools.count(1)


class Actor:
    def __init__(self, name: str, glyph: str, color, x: int, y: int, hp: int, atk: int,
                 df: int, dmg, speed: int = 100):
        self.id = next(_ids)
        self.name = name
        self.glyph = glyph
        self.color = color
        self.x, self.y = x, y
        self.hp = self.max_hp = hp
        self.base_atk = atk
        self.base_df = df
        self.base_dmg = dmg  # (dice, sides, bonus)
        self.base_speed = speed
        self.energy = 0
        self.statuses: dict[str, int] = {}
        self.is_player = False

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def speed(self) -> int:
        s = self.base_speed
        if "haste" in self.statuses:
            s *= 2
        if "slow" in self.statuses:
            s //= 2
        return s

    def has(self, status: str) -> bool:
        return self.statuses.get(status, 0) > 0

    def add_status(self, status: str, turns: int) -> None:
        self.statuses[status] = max(self.statuses.get(status, 0), turns)


class Monster(Actor):
    def __init__(self, key: str, x: int, y: int):
        d = data.MONSTERS[key]
        super().__init__(d["name"], d["glyph"], d["color"], x, y, d["hp"], d["atk"], d["df"],
                         d["dmg"], d["speed"])
        self.key = key
        self.ai = d["ai"]
        self.asleep = False
        self.hunting = False
        self.last_seen: tuple[int, int] | None = None
        self.lost_turns = 0
        self.cooldown = 0
        self.summon_cooldown = 0
        self.phase = 1

    @property
    def d(self):
        return data.MONSTERS[self.key]

    @property
    def atk(self) -> int:
        return self.base_atk

    @property
    def defense(self) -> int:
        return self.base_df

    @property
    def armor(self) -> int:
        return self.base_df // 3


def make_monster(key: str, x: int, y: int) -> Monster:
    return Monster(key, x, y)


class Player(Actor):
    def __init__(self, cls: str):
        d = data.CLASSES[cls]
        super().__init__("you", "@", (255, 255, 255), 0, 0, d["hp"], d["atk"], d["df"],
                         (1, 2, 0), d.get("speed", 100))
        self.is_player = True
        self.cls = cls
        self.mp = self.max_mp = d["mp"]
        self.level = 1
        self.xp = 0
        self.gold = 0
        self.inventory: list = []
        self.equipment: dict = {"weapon": None, "armor": None, "ring": None}
        self.kills = 0
        self.bonus_atk = 0
        self.bonus_dmg = 0
        self.regen_clock = 0
        self.mana_clock = 0
        self.deepest = 1
        self.killed_by = ""
        self.turns = 0

    @property
    def cdata(self):
        return data.CLASSES[self.cls]

    @property
    def abilities(self) -> list[str]:
        return [a for a in self.cdata["abilities"]
                if data.ABILITIES[a].get("unlock", 1) <= self.level]

    @property
    def all_abilities(self) -> list[str]:
        return self.cdata["abilities"]

    def ring(self, key: str) -> bool:
        r = self.equipment["ring"]
        return r is not None and r.key == key

    @property
    def atk(self) -> int:
        w = self.equipment["weapon"]
        bonus = w.enchant if w else 0
        return self.base_atk + self.bonus_atk + bonus + ("rage" in self.statuses) * 3

    @property
    def armor(self) -> int:
        a = self.equipment["armor"]
        return (a.d["ac"] + a.enchant) if a else 0

    @property
    def defense(self) -> int:
        return self.base_df + self.armor + (3 if self.ring("ring_protection") else 0)

    @property
    def dmg(self):
        w = self.equipment["weapon"]
        if w:
            n, s = w.d["dmg"]
            bonus = w.enchant
        else:
            n, s, bonus = 1, 3, 0
        bonus += self.bonus_dmg + (3 if self.ring("ring_power") else 0)
        bonus += ("rage" in self.statuses) * 2
        return n, s, bonus

    @property
    def crit(self) -> int:
        w = self.equipment["weapon"]
        return self.cdata["crit"] + (w.d.get("crit", 0) if w else 0)

    @property
    def spell_power(self) -> int:
        return self.level + (3 if self.ring("ring_power") else 0)

    @property
    def fire_immune(self) -> bool:
        a = self.equipment["armor"]
        return bool(a and a.d.get("fire_immune"))

    @property
    def torch(self) -> int:
        return self.cdata["torch"]

    @property
    def xp_next(self) -> int:
        return data.xp_for_level(self.level)
