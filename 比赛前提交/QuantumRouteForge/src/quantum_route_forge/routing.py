from __future__ import annotations

from typing import Iterable, List

from .geometry import cycle_distance, euclidean
from .models import Customer, Point, RoutePlan


def nearest_neighbor(depot: Point, customers: Iterable[Customer]) -> List[Customer]:
    remaining = list(customers)
    if not remaining:
        return []

    ordered: list[Customer] = []
    current = depot
    while remaining:
        nxt = min(remaining, key=lambda c: euclidean(current, c.point))
        ordered.append(nxt)
        remaining.remove(nxt)
        current = nxt.point
    return ordered


def two_opt_pass(depot: Point, route: List[Customer]) -> List[Customer]:
    best = route[:]
    best_cost = cycle_distance([c.point for c in best], depot=depot)
    n = len(best)

    for i in range(0, n - 2):
        for j in range(i + 2, n):
            candidate = best[:]
            candidate[i : j + 1] = reversed(candidate[i : j + 1])
            cand_cost = cycle_distance([c.point for c in candidate], depot=depot)
            if cand_cost + 1e-9 < best_cost:
                best = candidate
                best_cost = cand_cost
    return best


def build_route_plans(
    assignments: dict[int, list[Customer]],
    depot: Point,
    two_opt_rounds: int = 2,
) -> list[RoutePlan]:
    plans: list[RoutePlan] = []
    for vehicle_id, customers in sorted(assignments.items(), key=lambda kv: kv[0]):
        ordered = nearest_neighbor(depot, customers)
        for _ in range(max(0, two_opt_rounds)):
            ordered = two_opt_pass(depot, ordered)

        plans.append(
            RoutePlan(
                vehicle_id=vehicle_id + 1,
                customers=ordered,
                load=sum(c.demand for c in ordered),
                distance=cycle_distance([c.point for c in ordered], depot=depot),
            )
        )
    return plans
