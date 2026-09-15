import random

from app.pipeline.hillclimb import hill_climb, random_restart_hill_climb


def test_hill_climb_finds_local_minimum():
    # f(x) = (x - 3)^2 on integers, neighbours x±1
    res = hill_climb(10, lambda x: (x - 3) ** 2, lambda x: [x - 1, x + 1])
    assert res.state == 3 and res.cost == 0


def test_random_restart_escapes_local_optimum():
    # two basins: x=0 (cost 1) and x=20 (cost 0); start points are random
    def cost(x):
        return min((x - 0) ** 2 + 1, (x - 20) ** 2)

    res = random_restart_hill_climb(lambda rng: rng.randint(-5, 25), cost, lambda x: [x - 1, x + 1], restarts=8, seed=1)
    assert res.state == 20 and res.cost == 0
    assert res.restarts == 8 and res.evaluations > 0
