"""Graph grounded response helpers for the analyst assistant."""
from __future__ import annotations

import json
import re
from collections import Counter, deque
from typing import Any

try:
    from assistant.llm import call_model
except Exception:
    call_model = None

_ROLE_ALIASES = {
    "consolidator": ("consolidator", "сборщик", "собирает", "консолидац"),
    "transit": ("transit", "транзит", "переводит дальше"),
    "distributor": ("distributor", "распределитель", "раздаёт", "веер"),
    "terminal": ("terminal", "конечный", "сток", "получател"),
    "coordinator": ("coordinator", "координатор", "координиру"),
    "peripheral": ("peripheral", "перифер"),
}


def _nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    raw = graph.get("nodes", [])
    values = list(raw.values()) if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    return [item for item in values if isinstance(item, dict)]


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("id", node.get("gid", "")))


def _edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    raw = graph.get("edges", [])
    return [edge for edge in raw if isinstance(edge, dict)] if isinstance(raw, list) else []


def _node_map(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {gid: node for node in _nodes(graph) if (gid := _node_id(node))}


def _find_node(gid: str, graph: dict[str, Any]) -> dict[str, Any] | None:
    return _node_map(graph).get(str(gid))


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


def _edge_ends(edge: dict[str, Any]) -> tuple[str, str]:
    return str(edge.get("source", edge.get("src", ""))), str(edge.get("target", edge.get("dst", "")))


def _neighbors(gid: str, graph: dict[str, Any], direction: str, limit: int = 10) -> list[dict[str, Any]]:
    found = []
    for edge in _edges(graph):
        source, target = _edge_ends(edge)
        if direction == "out" and source == gid:
            found.append({"gid": target, "sum_kzt": edge.get("sum_kzt"), "n_tx": edge.get("n_tx")})
        elif direction == "in" and target == gid:
            found.append({"gid": source, "sum_kzt": edge.get("sum_kzt"), "n_tx": edge.get("n_tx")})
    found.sort(key=lambda item: (-(float(item["sum_kzt"] or 0) if isinstance(item["sum_kzt"], (int, float)) else 0), item["gid"]))
    return found[:max(1, min(limit, 20))]


def _card_facts(gid: str, node: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    metrics = node.get("metrics") if isinstance(node.get("metrics"), dict) else {}
    flags = node.get("flags") if isinstance(node.get("flags"), list) else []
    return {
        "gid": gid,
        "role": str(node.get("role") or "не указана"),
        "role_score": node.get("role_score"),
        "priority_score": node.get("priority_score"),
        "cluster_id": node.get("cluster_id"),
        "depth": node.get("depth"),
        "evidence": str(node.get("evidence") or ""),
        "flags": [str(flag) for flag in flags],
        "metrics": {key: metrics[key] for key in (
            "in_deg", "out_deg", "in_kzt", "out_kzt", "in_tx", "out_tx",
            "pass_through", "fast_forward_share", "betweenness", "pagerank",
        ) if key in metrics},
        "incoming": _neighbors(gid, graph, "in", 5),
        "outgoing": _neighbors(gid, graph, "out", 5),
    }


def _template_card(facts: dict[str, Any]) -> str:
    role_ru = {
        "consolidator": "сборщик", "transit": "транзитный узел",
        "distributor": "распределитель", "terminal": "наблюдаемый конечный узел",
        "coordinator": "возможный координирующий узел", "peripheral": "периферийный узел",
    }.get(facts["role"], facts["role"])
    metrics = facts["metrics"]
    parts = [
        f"Узел {facts['gid']} — {role_ru} (роль: {facts['role']}, оценка {facts['role_score'] if facts['role_score'] is not None else 'н/д'}).",
        f"Приоритет: {facts['priority_score'] if facts['priority_score'] is not None else 'н/д'}; кластер: {facts['cluster_id'] if facts['cluster_id'] is not None else 'н/д'}; колено: {facts['depth'] if facts['depth'] is not None else 'н/д'}.",
    ]
    if facts["evidence"]:
        parts.append(f"Основание в данных: {facts['evidence']}")
    if metrics:
        parts.append(
            f"Входящие: {metrics.get('in_deg', 'н/д')} отправителей, {_amount(metrics.get('in_kzt'))}; "
            f"исходящие: {metrics.get('out_deg', 'н/д')} получателей, {_amount(metrics.get('out_kzt'))}."
        )
    if facts["flags"]:
        parts.append("Флаги: " + ", ".join(facts["flags"]) + ".")
    if str(facts["depth"]) == "4":
        parts.append("Обход остановился на 4-м колене: отсутствие исходящих в этой выгрузке не доказывает, что деньги остались на счёте.")
    for key, label in (("incoming", "Крупнейшие входящие связи"), ("outgoing", "Крупнейшие исходящие связи")):
        if facts[key]:
            parts.append(label + ": " + "; ".join(f"{e['gid']} ({_amount(e.get('sum_kzt'))})" for e in facts[key]) + ".")
    parts.append("Это описание признаков в доступном графе, а не вывод о личности или незаконной деятельности.")
    return " ".join(parts)


def node_card(gid: str, graph: dict) -> dict:
    """Return a graph-derived template card, optionally improved by the configured LLM."""
    node = _find_node(str(gid), graph)
    if node is None:
        return {"text": f"Узел {gid} не найден в графе.", "source": "template"}
    facts = _card_facts(str(gid), node, graph)
    template = _template_card(facts)
    if call_model is None:
        return {"text": template, "source": "template"}
    response = call_model([
        {"role": "system", "content": "Перефразируй факты по-русски. Используй только предоставленный JSON: не добавляй факты, атрибуты личности, обвинения или причинные выводы. Подчеркни, что это признаки по неполным данным."},
        {"role": "user", "content": "Шаблон:\n" + template + "\nФакты JSON:\n" + json.dumps(facts, ensure_ascii=False)},
    ])
    answer = str((response or {}).get("content", "")).strip()
    return {"text": answer or template, "source": "llm" if answer else "template"}


def _tool_specs() -> list[dict[str, Any]]:
    def spec(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return {"type": "function", "function": {
            "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        }}
    string = {"type": "string"}
    return [
        spec("find_node", "Find one node by its exact string gid and return its graph facts.",
             {"gid": string}, ["gid"]),
        spec("neighbors", "Read direct incoming or outgoing edges for an exact gid.",
             {"gid": string, "direction": {"type": "string", "enum": ["in", "out"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, ["gid", "direction"]),
        spec("top_by_role", "List highest priority nodes for a role.",
             {"role": string, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, ["role"]),
        spec("cluster_summary", "Summarize one cluster from graph metadata and its nodes.",
             {"cluster_id": {"type": "integer"}}, ["cluster_id"]),
        spec("path_between", "Find the shortest directed path between two gids in the visible graph.",
             {"source_gid": string, "target_gid": string}, ["source_gid", "target_gid"]),
    ]


def _run_tool(name: str, args: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    nodes = _node_map(graph)
    if name == "find_node":
        gid = str(args.get("gid", ""))
        node = nodes.get(gid)
        return {"gid": gid, "node": _card_facts(gid, node, graph) if node else None}
    if name == "neighbors":
        gid, direction = str(args.get("gid", "")), str(args.get("direction", "out"))
        if gid not in nodes:
            return {"gid": gid, "error": "gid not found"}
        records = _neighbors(gid, graph, direction, int(args.get("limit", 10)))
        return {"gid": gid, "direction": direction, "neighbors": records}
    if name == "top_by_role":
        role = str(args.get("role", "")).lower()
        role = next((key for key, aliases in _ROLE_ALIASES.items() if role == key or any(alias in role for alias in aliases)), role)
        limit = max(1, min(int(args.get("limit", 10)), 20))
        matches = [n for n in nodes.values() if str(n.get("role", "")).lower() == role]
        matches.sort(key=lambda n: (-(float(n.get("priority_score") or 0)), _node_id(n)))
        return {"role": role, "nodes": [
            {"gid": _node_id(n), "priority_score": n.get("priority_score"), "evidence": n.get("evidence", ""), "cluster_id": n.get("cluster_id")}
            for n in matches[:limit]
        ]}
    if name == "cluster_summary":
        cluster_id = int(args.get("cluster_id", -1))
        members = [n for n in nodes.values() if n.get("cluster_id") == cluster_id]
        members.sort(key=lambda n: (-(float(n.get("priority_score") or 0)), _node_id(n)))
        clusters = graph.get("clusters", [])
        summary = next((c for c in clusters if isinstance(c, dict) and c.get("cluster_id") == cluster_id), {})
        return {"cluster_id": cluster_id, "summary": summary, "n_visible_nodes": len(members),
                "top_nodes": [{"gid": _node_id(n), "role": n.get("role"), "priority_score": n.get("priority_score"), "evidence": n.get("evidence", "")} for n in members[:10]]}
    if name == "path_between":
        start, end = str(args.get("source_gid", "")), str(args.get("target_gid", ""))
        if start not in nodes or end not in nodes:
            return {"source_gid": start, "target_gid": end, "path": None, "error": "gid not found"}
        adjacency: dict[str, list[str]] = {}
        for edge in _edges(graph):
            source, target = _edge_ends(edge)
            if source in nodes and target in nodes:
                adjacency.setdefault(source, []).append(target)
        queue = deque([start])
        previous: dict[str, str | None] = {start: None}
        while queue and end not in previous:
            current = queue.popleft()
            for neighbor in adjacency.get(current, []):
                if neighbor not in previous:
                    previous[neighbor] = current
                    queue.append(neighbor)
        if end not in previous:
            return {"source_gid": start, "target_gid": end, "path": None}
        path, current = [], end
        while current is not None:
            path.append(current)
            current = previous[current]
        return {"source_gid": start, "target_gid": end, "path": list(reversed(path))}
    return {"error": "unknown tool"}


def _fallback(question: str, graph: dict[str, Any]) -> dict[str, Any]:
    text = str(question or "")
    lower = text.lower()
    nodes = _node_map(graph)
    gids_in_text = re.findall(r"(?<!\d)\d{3,20}(?!\d)", text)
    gids = list(dict.fromkeys(gid for gid in gids_in_text if gid in nodes))
    citations: set[str] = set()

    if len(gids) >= 2 and any(word in lower for word in ("путь", "маршрут", "path", "между")):
        result = _run_tool("path_between", {"source_gid": gids[0], "target_gid": gids[1]}, graph)
        path = result.get("path")
        if path:
            citations.update(path)
            answer = "Направленный путь в графе: " + " → ".join(path) + "."
        else:
            answer = f"Направленный путь между {gids[0]} и {gids[1]} в доступном графе не найден."
            citations.update(gids[:2])
        return {"answer": answer, "cited_gids": sorted(citations), "source": "fallback"}

    if len(gids) >= 2 and any(word in lower for word in ("собира", "получает от", "плательщик", "collect")):
        counts: Counter[str] = Counter()
        for gid in gids:
            citations.add(gid)
            for edge in _neighbors(gid, graph, "out", 20):
                counts[edge["gid"]] += 1
        common = [gid for gid, count in counts.most_common(10) if count >= 2]
        citations.update(common)
        if common:
            return {"answer": "Общие получатели минимум от двух указанных gid: " + ", ".join(common) + ". Сверьте исходящие рёбра в графе.", "cited_gids": sorted(citations), "source": "fallback"}
        return {"answer": "В видимом графе не нашёл общего получателя минимум от двух указанных gid.", "cited_gids": sorted(citations), "source": "fallback"}

    if gids:
        gid = gids[0]
        if any(word in lower for word in ("вход", "кто отправ", "кто плат", "от кого", "incoming")):
            data = _run_tool("neighbors", {"gid": gid, "direction": "in"}, graph)
            records = data.get("neighbors", [])
            citations.add(gid)
            citations.update(e["gid"] for e in records)
            answer = f"Входящие связи узла {gid}: " + (", ".join(f"{e['gid']} ({_amount(e.get('sum_kzt'))})" for e in records) if records else "не найдены") + "."
        elif any(word in lower for word in ("исход", "кому", "куда", "платеж", "переводит", "outgoing")):
            data = _run_tool("neighbors", {"gid": gid, "direction": "out"}, graph)
            records = data.get("neighbors", [])
            citations.add(gid)
            citations.update(e["gid"] for e in records)
            answer = f"Исходящие связи узла {gid}: " + (", ".join(f"{e['gid']} ({_amount(e.get('sum_kzt'))})" for e in records) if records else "не найдены") + "."
        else:
            card = node_card(gid, graph)
            return {"answer": card["text"], "cited_gids": [gid], "source": "fallback"}
        return {"answer": answer, "cited_gids": sorted(citations), "source": "fallback"}

    cluster = re.search(r"(?:кластер|cluster)\s*#?\s*(\d+)", lower)
    if cluster:
        data = _run_tool("cluster_summary", {"cluster_id": int(cluster.group(1))}, graph)
        top = data.get("top_nodes", [])
        citations.update(item["gid"] for item in top)
        return {"answer": f"Кластер {data['cluster_id']}: {data['n_visible_nodes']} видимых узлов. " + "; ".join(f"{n['gid']} ({n.get('role')}, приоритет {n.get('priority_score')})" for n in top[:5]), "cited_gids": sorted(citations), "source": "fallback"}

    role = next((key for key, aliases in _ROLE_ALIASES.items() if any(alias in lower for alias in aliases)), None)
    if role:
        data = _run_tool("top_by_role", {"role": role, "limit": 10}, graph)
        top = data.get("nodes", [])
        citations.update(item["gid"] for item in top)
        return {"answer": f"Узлы с ролью «{role}» по приоритету: " + ("; ".join(f"{n['gid']} ({n.get('priority_score')})" for n in top) if top else "не найдены") + ".", "cited_gids": sorted(citations), "source": "fallback"}

    return {
        "answer": "Уточните gid, роль или номер кластера. Поддерживаются карточка узла, входящие/исходящие связи, путь между gid, топ узлов по роли и сводка кластера.",
        "cited_gids": [],
        "source": "fallback",
    }


def ask(question: str, graph: dict) -> dict:
    """Answer with graph tools when configured; fall back to deterministic graph queries."""
    fallback = _fallback(str(question or ""), graph)
    if call_model is None:
        return fallback
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": (
            "Ты помощник AML-аналитика. Граф — единственный источник фактов. "
            "Перед ответом используй подходящие инструменты; не угадывай отсутствующие данные. "
            "Ссылайся на точные gid, формулируй выводы как гипотезы по неполной выборке, "
            "не выдумывай личные атрибуты и не называй людей преступниками. Отвечай по-русски кратко. "
            "Если инструмент не нашёл путь/узел, сообщи именно это."
        )},
        {"role": "user", "content": str(question or "")},
    ]
    specs = _tool_specs()
    citations: set[str] = set()
    try:
        for _ in range(4):
            response = call_model(messages, tools=specs)
            if not response:
                return fallback
            calls = response.get("tool_calls") or []
            if not calls:
                answer = str(response.get("content") or "").strip()
                if not answer:
                    return fallback
                valid_ids = set(_node_map(graph))
                cited = [gid for gid in valid_ids if gid in citations]
                for gid in re.findall(r"(?<!\d)\d{3,20}(?!\d)", answer):
                    if gid in valid_ids:
                        citations.add(gid)
                cited = sorted(citations)
                return {"answer": answer, "cited_gids": cited, "source": "llm"}
            assistant_calls = []
            for index, call in enumerate(calls):
                call_id = str(call.get("id") or f"tool_{index}")
                name = str(call.get("name", ""))
                args = call.get("arguments", {})
                if not isinstance(args, dict):
                    args = {}
                assistant_calls.append({
                    "id": call_id, "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
                })
            messages.append({"role": "assistant", "content": response.get("content") or "", "tool_calls": assistant_calls})
            for call in calls:
                name, args = str(call.get("name", "")), call.get("arguments", {})
                if not isinstance(args, dict):
                    args = {}
                result = _run_tool(name, args, graph)
                payload = json.dumps(result, ensure_ascii=False, default=str)
                for gid in re.findall(r'"(?:gid|source_gid|target_gid)"\s*:\s*"([^"]+)"', payload):
                    if gid in _node_map(graph):
                        citations.add(gid)
                messages.append({"role": "tool", "tool_call_id": str(call.get("id") or ""), "name": name, "content": payload})
        return fallback
    except Exception:
        return fallback


__all__ = ["ask", "node_card"]
