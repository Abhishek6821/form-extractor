"""Generic steepest-ascent hill climbing with random restarts.

Both optimisation passes (field grouping and junk pruning) plug their own
state / cost / neighbour functions into this module.  No model calls happen
here — this is pure CPU local search.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Generic, Iterable, TypeVar

S = TypeVar("S")


@dataclass
class ClimbResult(Generic[S]):
    state: S
    cost: float
    iterations: int
    restarts: int
    evaluations: int


def hill_climb(initial: S, cost_fn: Callable[[S], float],
               neighbors_fn: Callable[[S], Iterable[S]], max_iterations: int = 200) -> ClimbResult[S]:
    """Steepest-ascent: move to the best neighbour while it improves the cost."""
    current = initial
    current_cost = cost_fn(current)
    evals = 1
    it = 0
    while it < max_iterations:
        it += 1
        best, best_cost = None, current_cost
        for n in neighbors_fn(current):
            c = cost_fn(n)
            evals += 1
            if c < best_cost - 1e-9:
                best, best_cost = n, c
        if best is None:
            break  # local optimum reached
        current, current_cost = best, best_cost
    return ClimbResult(current, current_cost, it, 1, evals)


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
