"""Generate and check twelve offline questions using IDs from a supplied graph."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from assistant import cards, core


def evaluate(graph):
    # This evaluation never spends API credits, even if a local .env has a key.
    core.call_model = cards.call_model = None
    nodes = cards.node_map(graph)
    assert nodes, 'Evaluation requires a nonempty graph'
    ordered = core._ordered(list(nodes.values()))
    gid = cards.node_id(ordered[0])
    role_node = next((n for n in ordered if n.get('role') in cards.ROLE_RU and n.get('cluster_id') is not None), ordered[0])
    role = role_node.get('role', 'consolidator')
    cluster = role_node.get('cluster_id', 0)
    boundary = next((cards.node_id(n) for n in ordered if cards.number(n.get('depth')) == 4), gid)
    edges = [cards.edge_ends(e) for e in cards.records(graph.get('edges'))]
    edges = [(a, b) for a, b in edges if a in nodes and b in nodes]
    source, target = edges[0] if edges else (gid, gid)
    incoming = {}
    for a, b in edges:
        incoming.setdefault(b, set()).add(a)
    pool = max(incoming.values(), key=len, default=set())
    payers = sorted(pool)[:5] if len(pool) >= 2 else list(nodes)[:2]
    missing = '9' * 20
    while missing in nodes:
        missing = str(int(missing) - 1)
    questions = [
        'Кого стоит проверить первым и почему?',
        'Какие узлы имеют признаки консолидации?',
        'Какие ограничения есть у этих данных?',
        f'Карточка узла {gid}',
        f'Покажи входящие связи узла {gid}',
        f'Кому переводил узел {gid}?',
        f'Покажи {role} кластера {cluster}',
        f'Опиши кластер {cluster}',
        f'Есть ли направленный путь от {source} до {target}?',
        'Кто общий получатель от ' + ', '.join(payers) + '?',
        f'Карточка узла {boundary}',
        f'Покажи узел {missing}',
    ]
    answers = []
    for index, question in enumerate(questions, 1):
        answer = core.ask(question, graph)
        assert answer['source'] == 'fallback'
        assert answer['answer'] and all(type(g) is str and g in nodes for g in answer['cited_gids'])
        answers.append(answer)
        print(f'{index:02d}. OK | {question} | citations={len(answer["cited_gids"])}')
    assert answers[0]['cited_gids'] == [cards.node_id(n) for n in ordered[:10]]
    assert answers[1]['cited_gids'] == [cards.node_id(n) for n in ordered if n.get('role') == 'consolidator'][:10]
    assert 'seed' in answers[2]['answer'] and not answers[2]['cited_gids']
    assert gid in answers[3]['cited_gids']
    assert answers[6]['cited_gids'] == [cards.node_id(n) for n in ordered if n.get('role') == role and n.get('cluster_id') == cluster][:10]
    assert source in answers[8]['cited_gids'] and target in answers[8]['cited_gids']
    if len(payers) >= 2:
        common = set.intersection(*(set(b for a, b in edges if a == payer) for payer in payers))
        expected = [cards.node_id(n) for n in ordered if cards.node_id(n) in common][:20]
        assert set(answers[9]['cited_gids']) == set(payers + expected)
    if cards.number(nodes[boundary].get('depth')) == 4:
        assert 'четвёртом' in answers[10]['answer']
    assert not answers[11]['cited_gids'] and 'не найдены' in answers[11]['answer']
    print(f'PASS: 12 questions; {len(nodes)} nodes; {len(edges)} directed edges; no API calls.')
    return answers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph', type=Path, default=Path('outputs/graph.json'))
    args = parser.parse_args()
    evaluate(json.loads(args.graph.read_text(encoding='utf-8-sig')))


if __name__ == '__main__':
    main()
