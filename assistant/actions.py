"""Validate map actions built from graph query results, never from model prose."""
from __future__ import annotations

import re

from assistant.cards import edge_ends, node_map, records


def validated_actions(value, graph, cited_gids):
    if not isinstance(value, list):
        return []
    nodes = node_map(graph)
    cited = set(cited_gids)
    edges = {edge_ends(edge) for edge in records(graph.get('edges'))} if isinstance(graph, dict) else set()
    accepted, seen = [], set()
    for action in value[:24]:
        if not isinstance(action, dict):
            continue
        kind, label, gids = action.get('kind'), action.get('label'), action.get('gids')
        if kind not in ('path', 'nodes') or not isinstance(label, str) or not 1 <= len(label.strip()) <= 120:
            continue
        if not isinstance(gids, list) or not 1 <= len(gids) <= 500:
            continue
        if any(not isinstance(gid, str) or not re.fullmatch(r'[0-9]{1,20}', gid)
               or gid not in nodes or gid not in cited for gid in gids):
            continue
        if kind == 'path':
            if len(gids) < 2 or len(set(gids)) != len(gids):
                continue
            if any((a, b) not in edges for a, b in zip(gids, gids[1:])):
                continue
        else:
            gids = list(dict.fromkeys(gids))
        key = (kind, tuple(gids))
        if key not in seen:
            accepted.append({'kind': kind, 'label': label.strip(), 'gids': list(gids)})
            seen.add(key)
        if len(accepted) == 6:
            break
    return accepted
