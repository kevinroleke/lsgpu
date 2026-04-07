"""EntitySpec, Entity, and helper functions for entity authors."""

import random
from dataclasses import dataclass, field

from ansi import RESET


@dataclass
class EntitySpec:
    """
    Static definition of an entity type.

    To add a new entity:
      1. Create entities/<yourname>.py
      2. Build an EntitySpec with your ASCII art frames and colour
      3. Set module-level  SPEC = EntitySpec(...)
      4. Done — it's auto-discovered on next run.
    """
    name:   str
    frames: list[list[str]]
    color:  str

    @property
    def width(self) -> int:
        return max(len(line) for frame in self.frames for line in frame)

    @property
    def height(self) -> int:
        return max(len(frame) for frame in self.frames)


@dataclass
class Entity:
    """Live instance of an EntitySpec bouncing around the screen."""
    spec:  EntitySpec
    x:     float
    y:     float
    dx:    float
    dy:    float
    phase: int = 0   # per-instance frame offset so clones animate out of sync

    def current_frame(self, tick: int) -> list[str]:
        idx = (tick // 4 + self.phase) % len(self.spec.frames)
        return self.spec.frames[idx]

    def tick(self, cols: int, rows: int) -> None:
        max_x = max(0, cols - self.spec.width  - 1)
        max_y = max(0, rows - self.spec.height - 3)
        self.x += self.dx
        self.y += self.dy
        if self.x <= 0:        self.x = 0.0;          self.dx =  abs(self.dx)
        elif self.x >= max_x:  self.x = float(max_x); self.dx = -abs(self.dx)
        if self.y <= 0:        self.y = 0.0;          self.dy =  abs(self.dy)
        elif self.y >= max_y:  self.y = float(max_y); self.dy = -abs(self.dy)


def spawn(spec: EntitySpec, cols: int, rows: int, phase: int = 0) -> Entity:
    """Spawn an entity at a random position with a random velocity."""
    max_x = max(1, cols - spec.width  - 1)
    max_y = max(1, rows - spec.height - 3)
    return Entity(
        spec=spec,
        x=float(random.randint(0, max_x)),
        y=float(random.randint(0, max_y)),
        dx=random.uniform(0.25, 0.55) * random.choice([-1, 1]),
        dy=random.uniform(0.15, 0.40) * random.choice([-1, 1]),
        phase=phase,
    )


def overlay(entities: list[Entity], tick: int) -> str:
    """Build cursor-positioning escape sequences to stamp all entities on screen."""
    buf: list[str] = []
    for e in entities:
        for i, line in enumerate(e.current_frame(tick)):
            row = int(e.y) + i + 1
            col = int(e.x) + 1
            buf.append(f"\033[{row};{col}H{e.spec.color}{line}{RESET}")
    return "".join(buf)
