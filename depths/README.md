# DEPTHS

*A descent into the Hollow Kingdom.*

DEPTHS is a roguelike that runs entirely in your terminal, drawn in 24-bit color with real-time
lighting, particles and animation. It is pure Python standard library: nothing to install, no
network, no assets.

```sh
python3 depths/play.py
```

Needs Python 3.10+ and a terminal at least **96 × 30** with truecolor support (Apple Terminal,
iTerm2, Ghostty, Kitty, WezTerm, Windows Terminal, most Linux terminals). Bigger is better.

## The game

Twelve procedurally generated depths across four biomes stand between you and the Hollow King:

| Depths | Biome | |
| --- | --- | --- |
| 1–3 | **The Forgotten Crypt** | Rooms and corridors, braziers, pillared halls, flooded chambers |
| 4–6 | **The Flooded Caverns** | Organic caves, deep pools, moss and glowing fungus |
| 7–9 | **The Molten Depths** | Rivers of lava with rubble bridges, embers drifting upward |
| 10–12 | **The Abyssal Halls** | Crystal-lit ruins, and the Hollow Throne at the bottom |

Pick a class:

- **Warrior**: tough and armored. *Cleave*, *War Cry*, *Second Wind*, and *Earthshatter* at level 5.
- **Mage**: fragile but devastating. *Firebolt*, *Frost Nova*, *Blink*, and *Meteor* at level 5.
- **Rogue**: fast and deadly crits. *Throw Knives*, *Shadowstep*, *Smoke Bomb*, and *Death Mark* at level 5.

There are 18 monsters with their own behaviour. Archers keep their distance, bats flit
erratically, oozes split when struck, trolls regenerate, cultists heal their allies, shades
blink through shadows, drakes breathe fire, liches raise the dead, and the Hollow King fights
in three phases. You'll find potions, scrolls, wands, weapons, armor and rings, plus chests,
fountains, hidden traps, and status effects (poison, burning, frozen, stunned, confused,
haste, rage).

## Controls

| Key | Action |
| --- | --- |
| Arrows / `h j k l` / `y u b n` | Move or attack (`yubn` are diagonals) |
| `.` | Wait a turn |
| `g` or `,` | Pick up |
| `i` | Inventory (`a`–`z` select, `Enter` use/equip, `D` drop) |
| `1` `2` `3` `4` | Class abilities |
| `o` | Auto-explore |
| `>` | Descend, or travel to the known stairs |
| `r` | Rest until healed |
| `x` | Look around |
| `c` | Character sheet |
| `m` | Message history |
| `Esc` | Menu (save & quit, abandon) |

In targeting mode, move the cursor, press `Tab` to cycle through enemies, and press `Enter` to
fire. Any key interrupts auto-explore, travel and rest.

Saves and the high-score table live in `~/.depths/`. Ctrl-C saves your run before exiting.

## Under the hood

```
depths/
  play.py            launcher
  depths/
    term.py          raw terminal input and a diffing truecolor renderer
    canvas.py        off-screen cell buffer with boxes, bars and text
    fov.py           recursive shadowcasting, Bresenham lines, distance maps
    mapgen.py        BSP rooms, cellular-automata caves, lava rivers, population, baked light
    actors.py        player and monsters
    game.py          turns and energy, combat, AI, abilities, items, traps, auto-explore
    particles.py     particles, projectiles, explosions, floating text, shake and flash
    render.py        lit map, entities, effects, sidebar, minimap, message log
    screens.py       title, class select, death, victory, high scores, help
    app.py           main loop and in-game input, targeting, inventory, menus
  tests/
    test_depths.py   unit tests
    bot.py           a bot that plays the game headlessly to catch crashes
```

- **Rendering**: each frame is drawn into an off-screen canvas, then only the cells that changed
  are sent to the terminal, inside synchronized-output markers so frames never tear.
- **Lighting**: static light (braziers, lava, crystals, fungus) is baked per level with line of
  sight. Your torch, glowing monsters and spell effects are layered on top every frame with a
  subtle flicker. Remembered areas fade to a cold blue.
- **Turns**: an energy system lets hasted, slowed and fast creatures act at different rates.
  Monsters path with a shared distance map from the player.

## Tests

```sh
cd depths
python3 -m unittest discover tests        # unit tests
python3 tests/bot.py 6 3000               # bot plays 6 games
python3 tests/bot.py 3 15000 --god        # invulnerable bot plays all the way to the Hollow King
```
