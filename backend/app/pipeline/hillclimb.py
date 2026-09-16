"""Generic steepest-ascent hill climbing with random restarts.

Both optimisation passes (field grouping and junk pruning) plug their own
state / cost / neighbour functions into this module.  No model calls happen
here — this is pure CPU local search.
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Callable, Generic, Iterable, TypeVar

S = TypeVar("S")

# On hosts with a fractional CPU quota (e.g. 0.1 vCPU) a tight loop starves every other process in
# the container. Sleeping briefly every N evaluations hands the quota back so health checks and
# other requests still get served. 0 disables it.
CPU_YIELD_MS = float(os.environ.get("FORM_CPU_YIELD_MS", "0"))
CPU_YIELD_EVERY = 200


def _maybe_yield(evals: int) -> None:
    if CPU_YIELD_MS and evals % CPU_YIELD_EVERY == 0:
        time.sleep(CPU_YIELD_MS / 1000.0)


@dataclass
class ClimbResult(Generic[S]):
    state: S
    cost: float
    iterations: int
    restarts: int
    evaluations: int
    initial_cost: float = 0.0  # cost of the starting state of the best run


def hill_climb(initial: S, cost_fn: Callable[[S], float],
               neighbors_fn: Callable[[S], Iterable[S]], max_iterations: int = 200) -> ClimbResult[S]:
    """Steepest-ascent: move to the best neighbour while it improves the cost."""
    current = initial
    current_cost = cost_fn(current)
    initial_cost = current_cost
    evals = 1
    it = 0
    while it < max_iterations:
        it += 1
        best, best_cost = None, current_cost
        for n in neighbors_fn(current):
            c = cost_fn(n)
            evals += 1
            _maybe_yield(evals)
            if c < best_cost - 1e-9:
                best, best_cost = n, c
        if best is None:
            break  # local optimum reached
        current, current_cost = best, best_cost
    return ClimbResult(current, current_cost, it, 1, evals, initial_cost)


def random_restart_hill_climb(make_initial: Callable[[random.Random], S], cost_fn: Callable[[S], float],
                              neighbors_fn: Callable[[S], Iterable[S]], restarts: int = 6,
                              max_iterations: int = 200, seed: int = 0) -> ClimbResult[S]:
    """Run ``restarts`` climbs from different initial states and keep the best."""
    rng = random.Random(seed)
    best: ClimbResult[S] | None = None
    total_evals = 0
    total_iters = 0
    for _ in range(max(1, restarts)):
        res = hill_climb(make_initial(rng), cost_fn, neighbors_fn, max_iterations)
        total_evals += res.evaluations
        total_iters += res.iterations
        if best is None or res.cost < best.cost - 1e-9:
            best = res
    assert best is not None
    best.restarts = max(1, restarts)
    best.evaluations = total_evals
    best.iterations = total_iters
    return best
