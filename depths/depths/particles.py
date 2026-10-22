"""Visual effects: particles, projectiles, explosions, floating text, shake and flashes.

The game emits plain event dicts; this module turns them into short-lived animations.
Coordinates are in map cells (floats).
"""

import math
import random

from depths import colors as C

MAX_PARTICLES = 500


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "glyph", "color", "end", "gravity",
                 "drag")

    def __init__(self, x, y, vx, vy, life, glyph, color, end=None, gravity=0.0, drag=0.0):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.life = self.max_life = life
        self.glyph = glyph
        self.color = color
        self.end = end if end is not None else C.scale(color, 0.15)
        self.gravity = gravity
        self.drag = drag


class Effects:
    def __init__(self):
        self.rng = random.Random()
        self.particles: list[Particle] = []
        self.texts: list[list] = []  # [x, y, text, color, age, life]
        self.bolts: list[dict] = []
        self.beams: list[dict] = []
        self.blasts: list[dict] = []  # explosions and rings
        self.hit_until: dict[int, float] = {}
        self.shake_until = 0.0
        self.shake_power = 0
        self.flash_color = None
        self.flash_until = 0.0
        self.banner = None  # (title, subtitle, start)
        self.now = 0.0

    # --- events -----------------------------------------------------------------

    def consume(self, events: list[dict], now: float, level_name: str = "") -> None:
        for e in events:
            kind = e["type"]
            if kind == "burst":
                self.burst(e["x"], e["y"], e["color"], e.get("n", 8), e.get("speed", 5),
                           e.get("glyphs", "·*"))
            elif kind == "text":
                jitter = self.rng.uniform(-0.3, 0.3)
                self.texts.append([e["x"] + jitter, e["y"], e["text"], e["color"], 0.0, 1.0])
            elif kind == "hit":
                self.hit_until[e["id"]] = now + 0.14
            elif kind == "shake":
                self.shake_until = now + 0.12 + 0.06 * e["power"]
                self.shake_power = max(self.shake_power if now < self.shake_until else 0,
                                       min(2, e["power"]))
            elif kind == "bolt":
                if e["path"]:
                    self.bolts.append(dict(path=e["path"], glyph=e["glyph"], color=e["color"],
                                           start=now, speed=45.0))
            elif kind == "beam":
                self.beams.append(dict(path=e["path"], color=e["color"], start=now, life=0.3))
            elif kind == "explode":
                self.blasts.append(dict(x=e["x"], y=e["y"], radius=e["radius"], color=e["color"],
                                        start=now, life=0.45, ring=False))
                self.burst(e["x"], e["y"], e["color"], 12 + 8 * e["radius"], 4 + 3 * e["radius"],
                           "*·+'")
            elif kind == "ring":
                self.blasts.append(dict(x=e["x"], y=e["y"], radius=e["radius"], color=e["color"],
                                        start=now, life=0.35, ring=True))
            elif kind == "flash":
                self.flash_color = e["color"]
                self.flash_until = now + 0.35
            elif kind == "levelup":
                self.blasts.append(dict(x=e["x"], y=e["y"], radius=3, color=C.GOLD, start=now,
                                        life=0.6, ring=True))
                for _ in range(30):
                    self.particles.append(Particle(
                        e["x"] + self.rng.uniform(-1.5, 1.5), e["y"] + self.rng.uniform(-0.5, 0.5),
                        self.rng.uniform(-0.6, 0.6), -self.rng.uniform(2, 6), self.rng.uniform(0.6, 1.2),
                        self.rng.choice("*+·'"), C.GOLD, (120, 60, 0)))
                self.texts.append([e["x"], e["y"] - 1, "LEVEL UP!", C.GOLD, 0.0, 1.6])
            elif kind == "enter":
                self.banner = (f"DEPTH {e['depth']}", level_name.upper(), now)
                self.particles.clear()

    def burst(self, x, y, color, n, speed, glyphs) -> None:
        r = self.rng
        for _ in range(n):
            a = r.uniform(0, math.tau)
            s = r.uniform(0.3, 1.0) * speed
            self.particles.append(Particle(
                x, y, math.cos(a) * s, math.sin(a) * s * 0.6, r.uniform(0.25, 0.6),
                r.choice(glyphs), C.mix(color, C.WHITE, r.uniform(0, 0.35)), drag=3.0))

    def emit_ambient(self, x, y, kind: str) -> None:
        r = self.rng
        if len(self.particles) > MAX_PARTICLES:
            return
        if kind == "ember":
            self.particles.append(Particle(x + r.uniform(-0.4, 0.4), y, r.uniform(-0.4, 0.4),
                                           -r.uniform(1.0, 2.5), r.uniform(0.8, 1.8),
                                           r.choice("'·."), (255, r.randint(120, 200), 40),
                                           (90, 20, 0)))
        elif kind == "spark":
            self.particles.append(Particle(x + r.uniform(-0.3, 0.3), y - 0.3, r.uniform(-0.5, 0.5),
                                           -r.uniform(1.5, 3.0), r.uniform(0.3, 0.7), "'",
                                           (255, 210, 120), (120, 40, 0)))
        elif kind == "spore":
            self.particles.append(Particle(x + r.uniform(-0.5, 0.5), y, r.uniform(-0.3, 0.3),
                                           -r.uniform(0.2, 0.6), r.uniform(1.5, 3.0), "·",
                                           (90, 255, 220), (10, 60, 50)))
        elif kind == "mote":
            self.particles.append(Particle(x + r.uniform(-0.5, 0.5), y, r.uniform(-0.2, 0.2),
                                           -r.uniform(0.2, 0.5), r.uniform(1.5, 3.0), "·",
                                           (200, 150, 255), (30, 10, 60)))
        elif kind == "sleep":
            self.particles.append(Particle(x + 0.4, y - 0.4, 0.4, -0.7, 1.2, "z",
                                           (170, 180, 255), (30, 30, 60)))
        elif kind == "drip":
            self.particles.append(Particle(x + r.uniform(-0.3, 0.3), y - 0.5, 0, 1.5, 0.5, "'",
                                           (140, 200, 255), (20, 40, 80), gravity=6))

    # --- simulation -----------------------------------------------------------------

    def update(self, dt: float, now: float) -> None:
        self.now = now
        alive = []
        for p in self.particles:
            p.life -= dt
            if p.life <= 0:
                continue
            if p.drag:
                k = max(0.0, 1 - p.drag * dt)
                p.vx *= k
                p.vy *= k
            p.vy += p.gravity * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            alive.append(p)
        self.particles = alive[-MAX_PARTICLES:]
        for t in self.texts:
            t[4] += dt
        self.texts = [t for t in self.texts if t[4] < t[5]]
        self.bolts = [b for b in self.bolts
                      if (now - b["start"]) * b["speed"] < len(b["path"]) + 3]
        self.beams = [b for b in self.beams if now - b["start"] < b["life"]]
        self.blasts = [b for b in self.blasts if now - b["start"] < b["life"]]
        if self.banner and now - self.banner[2] > 3.2:
            self.banner = None

    def busy(self) -> bool:
        """True while a projectile is in flight (input waits briefly so it's visible)."""
        return bool(self.bolts)

    def shake_offset(self, now: float) -> tuple[int, int]:
        if now >= self.shake_until:
            return 0, 0
        p = self.shake_power
        return self.rng.randint(-p, p), self.rng.randint(-1, 1) if p > 1 else 0

    def lights(self, now: float):
        """Dynamic light sources from effects: (x, y, (r, g, b), radius)."""
        out = []
        for b in self.bolts:
            i = int((now - b["start"]) * b["speed"])
            if i < len(b["path"]):
                x, y = b["path"][i]
                c = b["color"]
                out.append((x, y, (c[0] / 255, c[1] / 255, c[2] / 255), 3))
        for b in self.blasts:
            k = 1 - (now - b["start"]) / b["life"]
            c = b["color"]
            out.append((b["x"], b["y"], (c[0] / 255 * 1.6 * k, c[1] / 255 * 1.6 * k,
                                         c[2] / 255 * 1.6 * k), b["radius"] + 3))
        for b in self.beams:
            k = 1 - (now - b["start"]) / b["life"]
            for x, y in b["path"][::3]:
                out.append((x, y, (0.6 * k, 0.7 * k, 1.0 * k), 2))
        return out
