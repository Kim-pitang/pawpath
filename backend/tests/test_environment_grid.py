"""환경 측정의 격자 색인은 전부 훑는 방식과 같은 결과를 내야 한다(속도만 다르다)."""
import random

from app.services import environment_service as env


def brute_nearest(point, ways, limit):
    return env.nearest_way(point, ways, limit)


def random_ways(rng, count):
    ways = []
    for index in range(count):
        x, y = rng.uniform(0, 400), rng.uniform(0, 400)
        points = [(x, y)]
        for _ in range(rng.randint(1, 4)):
            x, y = x + rng.uniform(-60, 60), y + rng.uniform(-60, 60)
            points.append((x, y))
        ways.append(({"highway": "footway", "id": index}, points))
    return ways


def test_grid_nearest_way_matches_scanning_every_segment():
    rng = random.Random(7)
    ways = random_ways(rng, 120)
    grid = env.way_grid(ways)
    for _ in range(600):
        point = (rng.uniform(-20, 420), rng.uniform(-20, 420))
        assert grid.nearest(point) is brute_nearest(point, ways, env.WAY_MATCH_M)


def test_grid_keeps_the_later_way_when_distances_tie():
    # 같은 선분이 두 길에 있으면 기존 규칙대로 나중 길이 이긴다
    ways = [({"highway": "residential"}, [(0.0, 0.0), (10.0, 0.0)]), ({"highway": "footway"}, [(0.0, 0.0), (10.0, 0.0)])]
    assert env.way_grid(ways).nearest((5.0, 3.0)) == {"highway": "footway"}


def test_a_point_beyond_the_limit_matches_nothing_even_in_a_neighbouring_cell():
    ways = [({"highway": "footway"}, [(0.0, 0.0), (100.0, 0.0)])]
    grid = env.way_grid(ways)
    assert grid.nearest((50.0, env.WAY_MATCH_M + 1)) is None
    assert grid.nearest((50.0, env.WAY_MATCH_M - 1)) is not None
