"""All game content: biomes, monsters, items, classes and abilities."""

from depths import colors as C

MAX_DEPTH = 12

# --- Biomes -------------------------------------------------------------------

BIOMES = {
    "crypt": {
        "name": "The Forgotten Crypt", "style": "rooms",
        "wall": (150, 140, 162), "floor": (74, 68, 82), "floor_glyph": (150, 140, 165),
        "ambient": (0.40, 0.40, 0.48), "torch": (1.0, 0.78, 0.5),
    },
    "caverns": {
        "name": "The Flooded Caverns", "style": "caves",
        "wall": (100, 152, 160), "floor": (44, 70, 76), "floor_glyph": (100, 165, 170),
        "ambient": (0.32, 0.42, 0.50), "torch": (0.95, 0.85, 0.65),
    },
    "molten": {
        "name": "The Molten Depths", "style": "molten",
        "wall": (165, 100, 80), "floor": (80, 50, 40), "floor_glyph": (185, 115, 88),
        "ambient": (0.46, 0.28, 0.24), "torch": (1.0, 0.75, 0.5),
    },
    "abyss": {
        "name": "The Abyssal Halls", "style": "abyss",
        "wall": (125, 96, 175), "floor": (48, 36, 70), "floor_glyph": (130, 100, 185),
        "ambient": (0.34, 0.28, 0.48), "torch": (0.9, 0.8, 1.0),
    },
}


def biome_for(depth: int) -> str:
    if depth <= 3:
        return "crypt"
    if depth <= 6:
        return "caverns"
    if depth <= 9:
        return "molten"
    return "abyss"


# --- Monsters -----------------------------------------------------------------
# dmg is (dice, sides, bonus). speed 100 = normal. ai: melee, erratic, ranged,
# caster, blink, boss. Extra keys add special behaviour.

MONSTERS = {
    "rat": dict(name="giant rat", glyph="r", color=(170, 130, 100), hp=6, atk=1, df=0,
                dmg=(1, 3, 0), speed=110, xp=2, depth=(1, 3), weight=10, ai="melee", pack=3,
                desc="A bloated rat the size of a dog, with yellowed teeth."),
    "bat": dict(name="cave bat", glyph="b", color=(150, 120, 170), hp=5, atk=2, df=3,
                dmg=(1, 3, 0), speed=150, xp=3, depth=(1, 5), weight=7, ai="erratic",
                desc="It flits through the dark in jagged, unpredictable arcs."),
    "kobold": dict(name="kobold", glyph="k", color=(210, 150, 70), hp=10, atk=2, df=1,
                   dmg=(1, 4, 1), speed=100, xp=5, depth=(1, 4), weight=9, ai="melee", pack=2,
                   desc="A small, scaly scavenger clutching a rusted blade."),
    "archer": dict(name="goblin archer", glyph="g", color=(110, 200, 90), hp=9, atk=3, df=1,
                   dmg=(1, 4, 0), speed=100, xp=8, depth=(2, 6), weight=6, ai="ranged",
                   ranged=dict(range=7, dmg=(1, 6, 0), glyph="-", color=(200, 180, 120),
                               verb="shoots an arrow at"),
                   desc="It keeps its distance, nocking arrow after arrow."),
    "skeleton": dict(name="skeleton", glyph="s", color=(225, 225, 205), hp=18, atk=4, df=3,
                     dmg=(1, 6, 1), speed=100, xp=12, depth=(2, 7), weight=8, ai="melee",
                     desc="Bones held together by old and spiteful magic."),
    "zombie": dict(name="zombie", glyph="Z", color=(120, 160, 105), hp=28, atk=3, df=1,
                   dmg=(1, 8, 2), speed=60, xp=12, depth=(3, 7), weight=6, ai="melee",
                   desc="Slow, rotting and relentless."),
    "spider": dict(name="giant spider", glyph="S", color=(170, 70, 170), hp=16, atk=5, df=3,
                   dmg=(1, 6, 0), speed=120, xp=18, depth=(4, 8), weight=7, ai="melee",
                   poison=4, desc="Its fangs drip with a glistening venom."),
    "ooze": dict(name="acid ooze", glyph="o", color=(120, 235, 120), hp=22, atk=4, df=0,
                 dmg=(1, 6, 0), speed=70, xp=15, depth=(4, 9), weight=6, ai="melee",
                 splits=True, glow=((0.2, 0.6, 0.25), 2),
                 desc="A quivering mass of acid. Cutting it only makes more of it."),
    "troll": dict(name="cave troll", glyph="T", color=(100, 160, 100), hp=48, atk=6, df=4,
                  dmg=(2, 6, 2), speed=90, xp=40, depth=(5, 10), weight=5, ai="melee",
                  regen=2, desc="Its wounds knit closed as you watch."),
    "imp": dict(name="fire imp", glyph="i", color=(255, 130, 40), hp=14, atk=5, df=4,
                dmg=(1, 4, 0), speed=120, xp=22, depth=(6, 10), weight=6, ai="ranged",
                glow=((0.8, 0.35, 0.1), 3), fire_immune=True,
                ranged=dict(range=6, dmg=(1, 8, 0), glyph="*", color=(255, 120, 30),
                            verb="hurls fire at", burn=3),
                desc="A cackling spark of malice that throws fire."),
    "cultist": dict(name="dark cultist", glyph="c", color=(190, 70, 210), hp=24, atk=6, df=3,
                    dmg=(1, 6, 0), speed=100, xp=35, depth=(6, 11), weight=5, ai="caster",
                    ranged=dict(range=7, dmg=(2, 6, 0), glyph="•", color=(200, 80, 255),
                                verb="hurls a shadow bolt at"),
                    desc="It mends its allies and curses its foes."),
    "salamander": dict(name="salamander", glyph="l", color=(255, 95, 35), hp=32, atk=7, df=5,
                       dmg=(2, 5, 0), speed=100, xp=35, depth=(7, 11), weight=6, ai="melee",
                       burn=3, fire_immune=True, glow=((0.9, 0.3, 0.05), 3),
                       desc="A lizard wreathed in living flame."),
    "golem": dict(name="stone golem", glyph="G", color=(160, 160, 175), hp=75, atk=8, df=9,
                  dmg=(2, 8, 2), speed=70, xp=60, depth=(8, 12), weight=4, ai="melee",
                  desc="A slow mountain of carved rock. Hard to hurt, harder to stop."),
    "wraith": dict(name="wraith", glyph="W", color=(175, 205, 255), hp=36, atk=9, df=6,
                   dmg=(2, 6, 0), speed=110, xp=55, depth=(8, 12), weight=5, ai="melee",
                   drain=3, glow=((0.35, 0.45, 0.8), 2),
                   desc="A cold shape that feeds on the warmth of the living."),
    "shade": dict(name="shade", glyph="h", color=(120, 110, 160), hp=28, atk=10, df=8,
                  dmg=(2, 5, 0), speed=130, xp=50, depth=(9, 12), weight=5, ai="blink",
                  desc="It slips between shadows, never where you last saw it."),
    "drake": dict(name="ember drake", glyph="D", color=(230, 70, 40), hp=85, atk=11, df=8,
                  dmg=(2, 8, 3), speed=100, xp=120, depth=(10, 12), weight=3, ai="ranged",
                  fire_immune=True, glow=((0.8, 0.25, 0.05), 3),
                  ranged=dict(range=5, dmg=(3, 6, 0), glyph="≈", color=(255, 110, 20),
                              verb="breathes fire at", burn=4, radius=1, cooldown=5),
                  desc="A young dragon. Its breath could melt a portcullis."),
    "lich": dict(name="lich", glyph="L", color=(200, 255, 210), hp=62, atk=10, df=7,
                 dmg=(1, 8, 0), speed=100, xp=150, depth=(11, 12), weight=2, ai="caster",
                 summons="skeleton", glow=((0.4, 0.8, 0.5), 3),
                 ranged=dict(range=7, dmg=(3, 6, 0), glyph="•", color=(120, 255, 150),
                             verb="casts a necrotic bolt at"),
                 desc="A sorcerer who traded death for eternity, and regrets nothing."),
    "king": dict(name="the Hollow King", glyph="K", color=(255, 215, 60), hp=260, atk=14,
                 df=10, dmg=(3, 8, 4), speed=100, xp=1000, depth=(99, 99), weight=0, ai="boss",
                 glow=((0.9, 0.75, 0.3), 4),
                 ranged=dict(range=8, dmg=(3, 8, 0), glyph="*", color=(255, 220, 100),
                             verb="hurls a crown of light at"),
                 desc="The last king of the drowned realm, hollowed by a stolen heart. "
                      "End this, and the Depths are free."),
}

# --- Items --------------------------------------------------------------------

ITEMS = {
    # potions
    "heal": dict(name="potion of healing", glyph="!", color=(240, 70, 80), kind="potion",
                 depth=1, weight=14, desc="Restores a good portion of your health."),
    "greater_heal": dict(name="potion of greater healing", glyph="!", color=(255, 40, 120),
                         kind="potion", depth=5, weight=6, desc="Restores almost all health."),
    "mana": dict(name="potion of mana", glyph="!", color=(80, 140, 255), kind="potion",
                 depth=1, weight=9, desc="Restores your mana."),
    "haste": dict(name="potion of haste", glyph="!", color=(255, 240, 90), kind="potion",
                  depth=3, weight=4, desc="You move and strike twice as fast for a while."),
    "strength": dict(name="potion of strength", glyph="!", color=(255, 150, 40), kind="potion",
                     depth=2, weight=3, desc="Permanently increases your attack and damage."),
    "vitality": dict(name="potion of vitality", glyph="!", color=(120, 255, 140), kind="potion",
                     depth=2, weight=3, desc="Permanently increases your maximum health."),
    # scrolls
    "teleport": dict(name="scroll of teleportation", glyph="?", color=(170, 140, 255),
                     kind="scroll", depth=1, weight=6, desc="Whisks you to a random place."),
    "mapping": dict(name="scroll of magic mapping", glyph="?", color=(120, 220, 255),
                    kind="scroll", depth=1, weight=5, desc="Reveals the layout of this depth."),
    "fireball": dict(name="scroll of fireball", glyph="?", color=(255, 110, 50), kind="scroll",
                     depth=2, weight=6, target=True, desc="A roaring explosion at a target."),
    "lightning": dict(name="scroll of lightning", glyph="?", color=(200, 230, 255),
                      kind="scroll", depth=2, weight=6,
                      desc="Lightning strikes the nearest visible enemy."),
    "confusion": dict(name="scroll of confusion", glyph="?", color=(255, 140, 220),
                      kind="scroll", depth=1, weight=5, desc="Confuses every enemy in view."),
    "enchant_weapon": dict(name="scroll of enchant weapon", glyph="?", color=(255, 210, 90),
                           kind="scroll", depth=2, weight=4, desc="Improves your weapon."),
    "enchant_armor": dict(name="scroll of enchant armor", glyph="?", color=(140, 230, 210),
                          kind="scroll", depth=2, weight=4, desc="Improves your armor."),
    # wands
    "wand_fire": dict(name="wand of fire", glyph="/", color=(255, 100, 40), kind="wand",
                      depth=3, weight=3, target=True, charges=(3, 6),
                      desc="Fires a bolt of flame that sets its target alight."),
    "wand_frost": dict(name="wand of frost", glyph="/", color=(140, 220, 255), kind="wand",
                       depth=3, weight=3, target=True, charges=(3, 6),
                       desc="Fires a freezing bolt that roots its target in ice."),
    "wand_lightning": dict(name="wand of lightning", glyph="/", color=(230, 240, 255),
                           kind="wand", depth=5, weight=2, target=True, charges=(2, 5),
                           desc="Lightning that arcs between nearby enemies."),
    # weapons: dmg (dice, sides)
    "dagger": dict(name="dagger", glyph=")", color=(190, 200, 210), kind="weapon", depth=1,
                   weight=4, dmg=(1, 4), crit=10, desc="Light and quick. Better critical hits."),
    "short_sword": dict(name="short sword", glyph=")", color=(200, 205, 220), kind="weapon",
                        depth=1, weight=4, dmg=(1, 6), desc="A reliable, balanced blade."),
    "mace": dict(name="mace", glyph=")", color=(170, 170, 180), kind="weapon", depth=1,
                 weight=3, dmg=(1, 8), desc="A flanged iron head on an oak haft."),
    "longsword": dict(name="longsword", glyph=")", color=(215, 225, 245), kind="weapon",
                      depth=3, weight=3, dmg=(1, 10), desc="A knight's weapon."),
    "war_axe": dict(name="war axe", glyph=")", color=(200, 170, 150), kind="weapon", depth=5,
                    weight=2, dmg=(2, 6), desc="Heavy, brutal and very effective."),
    "runeblade": dict(name="runeblade", glyph=")", color=(120, 220, 255), kind="weapon",
                      depth=8, weight=1, dmg=(2, 8), crit=5,
                      desc="Runes along the fuller glow with a cold blue light."),
    # armor: ac
    "leather": dict(name="leather armor", glyph="[", color=(160, 110, 70), kind="armor",
                    depth=1, weight=4, ac=2, desc="Supple, quiet, modest protection."),
    "studded": dict(name="studded leather", glyph="[", color=(170, 130, 90), kind="armor",
                    depth=2, weight=3, ac=3, desc="Leather reinforced with iron studs."),
    "chain": dict(name="chain mail", glyph="[", color=(180, 185, 195), kind="armor", depth=3,
                  weight=3, ac=5, desc="Interlocking rings of steel."),
    "plate": dict(name="plate armor", glyph="[", color=(210, 215, 230), kind="armor", depth=6,
                  weight=2, ac=7, desc="Full plate. You feel like a walking fortress."),
    "dragonscale": dict(name="dragonscale armor", glyph="[", color=(230, 80, 60), kind="armor",
                        depth=9, weight=1, ac=9, fire_immune=True,
                        desc="Scales of a great wyrm. Fire cannot touch you."),
    # rings
    "ring_regen": dict(name="ring of regeneration", glyph="=", color=(120, 255, 140),
                       kind="ring", depth=3, weight=2, desc="Your wounds close quickly."),
    "ring_protection": dict(name="ring of protection", glyph="=", color=(140, 200, 255),
                            kind="ring", depth=2, weight=2, desc="+3 defense."),
    "ring_power": dict(name="ring of power", glyph="=", color=(255, 120, 80), kind="ring",
                       depth=4, weight=2, desc="+3 damage to every blow and spell."),
    "ring_wizardry": dict(name="ring of wizardry", glyph="=", color=(190, 130, 255),
                          kind="ring", depth=3, weight=2, desc="Mana returns much faster."),
    "gold": dict(name="gold", glyph="$", color=(255, 215, 60), kind="gold", depth=1, weight=0,
                 desc="Glittering coins."),
}

# --- Classes and abilities ------------------------------------------------------

ABILITIES = {
    "cleave": dict(name="Cleave", cost=4, target=None, color=(255, 200, 120),
                   desc="Strike every adjacent enemy."),
    "warcry": dict(name="War Cry", cost=6, target=None, color=(255, 120, 60),
                   desc="Enemies in view are stunned for 2 turns and you gain rage."),
    "second_wind": dict(name="Second Wind", cost=8, target=None, color=(120, 255, 140),
                        desc="Recover 35% of your health."),
    "firebolt": dict(name="Firebolt", cost=3, target="enemy", color=(255, 120, 40),
                     desc="A bolt of fire: 2d6 + level damage and burning."),
    "frost_nova": dict(name="Frost Nova", cost=6, target=None, color=(140, 220, 255),
                       desc="Freeze all enemies within 2 tiles for 3 turns, 2d4 damage."),
    "blink": dict(name="Blink", cost=5, target="cell", color=(190, 140, 255),
                  desc="Teleport to a visible tile up to 7 away."),
    "meteor": dict(name="Meteor", cost=14, target="enemy", color=(255, 80, 30), unlock=5,
                   desc="Call down a meteor: 5d6 + level in a radius of 2."),
    "knives": dict(name="Throw Knives", cost=4, target="enemy", color=(220, 225, 235),
                   desc="Throw three knives at a target, 1d6 each."),
    "shadowstep": dict(name="Shadowstep", cost=6, target="enemy", color=(150, 120, 200),
                       desc="Step behind an enemy. Your next strike is a guaranteed critical."),
    "smoke": dict(name="Smoke Bomb", cost=7, target=None, color=(170, 170, 190),
                  desc="Confuse every enemy within 3 tiles for 5 turns."),
    "earthshatter": dict(name="Earthshatter", cost=12, target=None, color=(200, 160, 100),
                         unlock=5, desc="Slam the ground: 3d8 to all enemies within 2, stun."),
    "assassinate": dict(name="Death Mark", cost=10, target="enemy", color=(255, 60, 90),
                        unlock=5, desc="Mark a foe; it takes double damage for 8 turns."),
}

CLASSES = {
    "warrior": dict(
        name="Warrior", color=(255, 150, 80), hp=42, mp=12, atk=4, df=2, crit=5,
        hp_per_level=9, mp_per_level=1, mp_regen=6, torch=7,
        start=["mace", "chain", "heal", "heal"],
        abilities=["cleave", "warcry", "second_wind", "earthshatter"],
        desc="A veteran of a hundred battles. Tough, armored, and happiest in the thick of it.",
        art=[
            "    ,^.    ",
            "   (o o)   ",
            "  __| |__  ",
            " /  |=|  \\ ",
            "|[] |=| []|",
            "    | |  ||",
            "   /   \\ ||",
            "  /_/ \\_\\||",
        ],
    ),
    "mage": dict(
        name="Mage", color=(150, 140, 255), hp=26, mp=34, atk=2, df=0, crit=5,
        hp_per_level=5, mp_per_level=4, mp_regen=2, torch=8,
        start=["dagger", "leather", "heal", "mana", "mana"],
        abilities=["firebolt", "frost_nova", "blink", "meteor"],
        desc="A scholar of the old fires. Fragile in a brawl, devastating at range.",
        art=[
            "     /\\    ",
            "    /**\\   ",
            "   /____\\  ",
            "   (o  o)  *",
            "  /|~~~~|\\/",
            " / |~~~~| |",
            "   |~~~~| |",
            "  /______\\|",
        ],
    ),
    "rogue": dict(
        name="Rogue", color=(120, 230, 150), hp=32, mp=18, atk=5, df=1, crit=18,
        hp_per_level=7, mp_per_level=2, mp_regen=4, torch=6, speed=110,
        start=["dagger", "studded", "heal", "teleport"],
        abilities=["knives", "shadowstep", "smoke", "assassinate"],
        desc="Quick, quiet and lethal. Strikes from the shadows for devastating criticals.",
        art=[
            "    ____   ",
            "   /    \\  ",
            "  | -  - | ",
            "   \\_~~_/  ",
            "  /|    |\\ ",
            " /-|    |-\\",
            "/  |____|  ",
            "   /    \\  ",
        ],
    ),
}

TRAPS = {
    "spike": dict(name="spike trap", color=(200, 200, 210)),
    "fire": dict(name="fire trap", color=(255, 110, 30)),
    "teleport": dict(name="teleport trap", color=(170, 130, 255)),
    "alarm": dict(name="alarm trap", color=(255, 230, 90)),
    "poison": dict(name="poison dart trap", color=(120, 230, 90)),
}


def xp_for_level(level: int) -> int:
    return int(18 * level ** 1.65)
