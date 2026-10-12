"""Prerequisite graph utilities: cycle detection and topological ordering."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable, Iterable
from typing import TypeVar

N = TypeVar("N", bound=Hashable)


def would_create_cycle(edges: Iterable[tuple[N, N]], new_edge: tuple[N, N]) -> bool:
    """Edges are (prerequisite, concept). Adding (p, c) creates a cycle iff c reaches p."""
    p, c = new_edge
    if p == c:
        return True
    adj: dict[N, list[N]] = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
    stack, seen = [c], set()
    while stack:
        n = stack.pop()
        if n == p:
            return True
        if n in seen:
            continue
        seen.add(n)
        stack.extend(adj[n])
    return False


def is_acyclic(nodes: Iterable[N], edges: Iterable[tuple[N, N]]) -> bool:
    try:
        topological_order(nodes, edges)
        return True
    except ValueError:
        return False


def topological_order(nodes: Iterable[N], edges: Iterable[tuple[N, N]]) -> list[N]:
    nodes = list(nodes)
    indeg: dict[N, int] = {n: 0 for n in nodes}
    adj: dict[N, list[N]] = defaultdict(list)
    for a, b in edges:
        if a in indeg and b in indeg:
            adj[a].append(b)
            indeg[b] += 1
    order: list[N] = []
    ready = [n for n in nodes if indeg[n] == 0]
    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
    if len(order) != len(nodes):
        raise ValueError("prerequisite graph contains a cycle")
    return order


def ancestors(node: N, edges: Iterable[tuple[N, N]]) -> set[N]:
    rev: dict[N, list[N]] = defaultdict(list)
    for a, b in edges:
        rev[b].append(a)
    out: set[N] = set()
    stack = list(rev[node])
    while stack:
        n = stack.pop()
        if n not in out:
            out.add(n)
            stack.extend(rev[n])
    return out
