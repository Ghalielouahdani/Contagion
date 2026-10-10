"""Bounded breadth-first exploration over adapters.

Seeds come from the portfolio (one market or token per position). Each adapter returns the
entities it found; the explorer follows them until nothing new appears or a limit is hit.
A limit, a missing adapter or a failing source becomes an `unresolved` entry, never a
silent gap.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from backend.adapters.base import Ctx, Entity
from backend.adapters.sources import ReplayMiss, SourceError


@dataclass(frozen=True)
class Limits:
    max_depth: int = 10
    max_entities: int = 200
    time_budget_s: float = 600.0


class Explorer:
    def __init__(self, ctx: Ctx, adapters: list, limits: Limits | None = None):
        self.ctx, self.adapters, self.limits = ctx, adapters, limits or Limits()
        self.visited: set[Entity] = set()
        self.trace: list[dict] = []

    def run(self, seeds: list[Entity]) -> None:
        queue = deque((seed, 0) for seed in seeds)
        started = time.monotonic()
        while queue:
            entity, depth = queue.popleft()
            if entity in self.visited:
                continue
            self.visited.add(entity)
            subject = f"{entity.kind}:{entity.key}"
            if depth > self.limits.max_depth:
                self.ctx.unresolve(subject, f"not explored: depth limit {self.limits.max_depth}")
                continue
            if len(self.visited) > self.limits.max_entities:
                self.ctx.unresolve(subject, f"not explored: entity limit {self.limits.max_entities}")
                continue
            if time.monotonic() - started > self.limits.time_budget_s:
                self.ctx.unresolve(subject, f"not explored: time budget {self.limits.time_budget_s:.0f}s")
                continue
            adapter = None
            try:
                adapter = next((a for a in self.adapters if a.accepts(entity, self.ctx)), None)
                if adapter is None:
                    self.ctx.unresolve(subject, "no adapter recognises this entity")
                    continue
                found = adapter.discover(entity, self.ctx)
            except ReplayMiss:
                raise
            except (SourceError, ValueError, KeyError) as exc:
                name = adapter.name if adapter else "dispatch"
                self.ctx.unresolve(subject, f"{name} failed: {exc}")
                self.ctx.warnings.append(f"{name} could not explore {subject}: {exc}")
                continue
            # every asset an adapter touched (e.g. a token an oracle reads) is explored too
            found = found + [Entity("token", a) for a in self.ctx.pending_tokens]
            self.ctx.pending_tokens.clear()
            self.trace.append(
                {
                    "entity": subject,
                    "adapter": adapter.name,
                    "depth": depth,
                    "found": sorted({f"{f.kind}:{f.key}" for f in found}),
                }
            )
            queue.extend((f, depth + 1) for f in dict.fromkeys(found) if f not in self.visited)
