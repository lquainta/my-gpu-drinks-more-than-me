"""Field of view (recursive shadowcasting), lines, and distance maps."""

from collections import deque

_MULT = (
    (1, 0, 0, -1, -1, 0, 0, 1),
    (0, 1, -1, 0, 0, -1, 1, 0),
    (0, 1, 1, 0, 0, -1, -1, 0),
    (1, 0, 0, 1, -1, 0, 0, -1),
)

INF = 1 << 30
NEIGHBORS = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))


def compute_fov(opaque, w: int, h: int, ox: int, oy: int, radius: int) -> set:
    """Cells visible from (ox, oy). `opaque[y][x]` is True where sight is blocked."""
    visible = {(ox, oy)}
    r2 = radius * radius

    def cast(row, start, end, xx, xy, yx, yy):
        if start < end:
            return
        new_start = 0.0
        for j in range(row, radius + 1):
            dx, dy = -j - 1, -j
            blocked = False
            while dx <= 0:
                dx += 1
                x = ox + dx * xx + dy * xy
                y = oy + dx * yx + dy * yy
                l_slope = (dx - 0.5) / (dy + 0.5)
                r_slope = (dx + 0.5) / (dy - 0.5)
                if start < r_slope:
                    continue
                if end > l_slope:
                    break
                inside = 0 <= x < w and 0 <= y < h
                if inside and dx * dx + dy * dy <= r2:
                    visible.add((x, y))
                is_opaque = not inside or opaque[y][x]
                if blocked:
                    if is_opaque:
                        new_start = r_slope
                    else:
                        blocked = False
                        start = new_start
                elif is_opaque and j < radius:
                    blocked = True
                    cast(j + 1, start, l_slope, xx, xy, yx, yy)
                    new_start = r_slope
            if blocked:
                break

    for o in range(8):
        cast(1, 1.0, 0.0, _MULT[0][o], _MULT[1][o], _MULT[2][o], _MULT[3][o])
    return visible


def line(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Bresenham line from (x0, y0) to (x1, y1), inclusive of both ends."""
    points = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            return points
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def distance_map(w: int, h: int, sources, passable, limit: int = 200) -> list[list[int]]:
    """Breadth-first step counts (8-directional) from any source to every passable cell."""
    dist = [[INF] * w for _ in range(h)]
    q = deque()
    for x, y in sources:
        if 0 <= x < w and 0 <= y < h:
            dist[y][x] = 0
            q.append((x, y))
    while q:
        x, y = q.popleft()
        d = dist[y][x] + 1
        if d > limit:
            continue
        for dx, dy in NEIGHBORS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and dist[ny][nx] > d and passable(nx, ny):
                dist[ny][nx] = d
                q.append((nx, ny))
    return dist


def chebyshev(x0: int, y0: int, x1: int, y1: int) -> int:
    return max(abs(x0 - x1), abs(y0 - y1))
