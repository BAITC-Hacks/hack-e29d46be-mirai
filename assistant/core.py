"""Graph grounded response helpers for the analyst assistant."""
from __future__ import annotations

from typing import Any

try:
    from assistant.llm import call_model
except Exception:  # keep imports usable before optional dependencies are installed
    call_model = None

_ROLE_RU = {
    "consolidator": "сборщик",
    "transit": "транзитный узел",
    "distributor": "распределитель",
    "terminal": "наблюдаемый конечный узел",
    "coordinator": "возможный координирующий узел",
    "peripheral": "периферийный узел",
}


def _nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    raw = graph.get("nodes", [])
    if isinstance(raw, dict):
        values = list(raw.values())
    elif isinstance(raw, list):
        values = raw
    else:
        return []
    return [item for item in values if isinstance(item, dict)]


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("id", node.get("gid", "")))


def _edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    raw = graph.get("edges", [])
    return [edge for edge in raw if isinstance(edge, dict)] if isinstance(raw, list) else []


def _find_node(gid: str, graph: dict[str, Any]) -> dict[str, Any] | None:
    target = str(gid)
    return next((node for node in _nodes(graph) if _node_id(node) == target), None)


def _amount(value: Any) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return "не указано"
    if abs(amount) >= 1_000_000:
        return f"{amount / 1_000_000:.2f} млн ₸"
    if abs(amount) >= 1_000:
        return f"{amount / 1_000:.0f} тыс. ₸"
    return f"{amount:.0f} ₸"


def _neighbor_lines(gid: str, graph: dict[str, Any], direction: str, limit: int = 5) -> list[str]:
    matches = []
    for edge in _edges(graph):
        source = str(edge.get("source", edge.get("src", "")))
        target = str(edge.get("target", edge.get("dst", "")))
        other = target if direction == "out" and source == gid else source if direction == "in" and target == gid else ""
        if other:
            matches.append((other, edge.get("sum_kzt", 0)))
    matches.sort(key=lambda item: (-(float(item[1] or 0) if isinstance(item[1], (int, float)) else 0), item[0]))
    return [f"{other} ({_amount(amount)})" for other, amount in matches[:limit]]


def _card_facts(gid: str, node: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    metrics = node.get("metrics") if isinstance(node.get("metrics"), dict) else {}
    role = str(node.get("role") or "не определена")
    depth = node.get("depth", "не указано")
    flags = node.get("flags") if isinstance(node.get("flags"), list) else []
    return {
        "gid": gid,
        "role": role,
        "role_ru": _ROLE_RU.get(role, role),
        "role_score": node.get("role_score"),
        "priority_score": node.get("priority_score"),
        "cluster_id": node.get("cluster_id"),
        "depth": depth,
        "is_seed": bool(node.get("is_seed")),
        "evidence": str(node.get("evidence") or ""),
        "flags": [str(flag) for flag in flags],
        "metrics": {
            key: metrics.get(key)
            for key in ("in_deg", "out_deg", "in_kzt", "out_kzt", "in_tx", "out_tx", "pass_through", "fast_forward_share", "betweenness", "pagerank")
            if key in metrics
        },
        "incoming": _neighbor_lines(gid, graph, "in"),
        "outgoing": _neighbor_lines(gid, graph, "out"),
    }


def _template_card(facts: dict[str, Any]) -> str:
    if facts["role"] == "не определена":
        return f"Узел {facts['gid']} не найден в графе."
    metrics = facts["metrics"]
    parts = [
        f"Узел {facts['gid']} — {facts['role_ru']} (роль: {facts['role']}, оценка {facts['role_score'] if facts['role_score'] is not None else 'н/д'}).",
        f"Приоритет: {facts['priority_score'] if facts['priority_score'] is not None else 'н/д'}; кластер: {facts['cluster_id'] if facts['cluster_id'] is not None else 'н/д'}; колено: {facts['depth']}.",
    ]
    if facts["evidence"]:
        parts.append(f"Основание в данных: {facts['evidence']}")
    if "in_deg" in metrics or "in_kzt" in metrics:
        parts.append(f"Входящие: {metrics.get('in_deg', 'н/д')} отправителей, {_amount(metrics.get('in_kzt'))}; исходящие: {metrics.get('out_deg', 'н/д')} получателей, {_amount(metrics.get('out_kzt'))}.")
    if facts["flags"]:
        parts.append("Флаги: " + ", ".join(facts["flags"]) + ".")
    elif int(facts["depth"]) == 4 if str(facts["depth"]).isdigit() else False:
        parts.append("Обход остановился на 4-м колене: отсутствие исходящих в этой выгрузке не доказывает, что деньги остались на счёте.")
    if facts["incoming"]:
        parts.append("Крупнейшие входящие связи: " + "; ".join(facts["incoming"]) + ".")
    if facts["outgoing"]:
        parts.append("Крупнейшие исходящие связи: " + "; ".join(facts["outgoing"]) + ".")
    parts.append("Это описание признаков в доступном графе, а не вывод о личности или незаконной деятельности.")
    return " ".join(parts)


def node_card(gid: str, graph: dict) -> dict:
    """Return a safe template card, optionally improved by the configured LLM."""
    node = _find_node(str(gid), graph)
    if node is None:
        return {"text": f"Узел {gid} не найден в графе.", "source": "template"}
    facts = _card_facts(str(gid), node, graph)
    template = _template_card(facts)
    if call_model is None:
        return {"text": template, "source": "template"}
    response = call_model([
        {"role": "system", "content": "Ты помощник AML-аналитика. Перефразируй предоставленные факты по-русски. Используй только факты из JSON. Не делай выводов о личности, виновности или незаконности; укажи, что это гипотеза по неполным данным. Если фактов мало, сохрани шаблон."},
        {"role": "user", "content": "Шаблон:\n" + template + "\n\nФакты JSON:\n" + __import__("json").dumps(facts, ensure_ascii=False)},
    ])
    answer = str((response or {}).get("content", "")).strip()
    if answer:
        return {"text": answer, "source": "llm"}
    return {"text": template, "source": "template"}


def ask(question: str, graph: dict) -> dict:
    """Temporary deterministic fallback; tool-backed answering lives in issue #12."""
    text = str(question or "")
    mentioned = [node for node in _nodes(graph) if _node_id(node) and _node_id(node) in text]
    if mentioned:
        node = mentioned[0]
        gid = _node_id(node)
        card = node_card(gid, graph)
        return {"answer": card["text"], "cited_gids": [gid], "source": "fallback"}
    return {
        "answer": "Уточните gid, роль или номер кластера. Я отвечаю только по связям и метрикам, которые есть в графе.",
        "cited_gids": [],
        "source": "fallback",
    }
