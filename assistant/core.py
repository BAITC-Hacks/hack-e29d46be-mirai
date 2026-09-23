"""Public API; graph question tools are added by issue #12."""
import re
from assistant.cards import node_card, template_card, node_map


def ask(question: str, graph: dict) -> dict:
    nodes = node_map(graph)
    gids = [g for g in re.findall(r"(?<!\d)\d{1,20}(?!\d)", str(question)) if g in nodes]
    if gids:
        return {"answer": template_card(gids[0], graph), "cited_gids": [gids[0]], "source": "fallback"}
    return {"answer": "Уточните gid, роль или номер кластера.", "cited_gids": [], "source": "fallback"}
