"""Regression tests use synthetic graphs; demo questions use the real graph."""
import copy
import json
import time

import pytest
from assistant import core

A, B, C, D = (str(100000004015047101 + i) for i in range(4))
MISSING = '999999999999999999'


@pytest.fixture
def graph(monkeypatch):
    monkeypatch.setattr(core, 'call_model', None)
    return {'nodes': [
        {'id': A, 'role': 'consolidator', 'cluster_id': 3, 'priority_score': .9, 'evidence': 'два плательщика', 'metrics': {'in_kzt': 10000}},
        {'id': B, 'role': 'consolidator', 'cluster_id': 4, 'priority_score': .95},
        {'id': C, 'role': 'transit', 'cluster_id': 3, 'priority_score': .8},
        {'id': D, 'depth': 4, 'flags': ['in_cycle']},
    ], 'edges': [
        {'source': A, 'target': C, 'sum_kzt': 5000, 'n_tx': 1},
        {'source': B, 'target': C, 'sum_kzt': 6000, 'n_tx': 2},
        {'source': C, 'target': D, 'sum_kzt': 7000, 'n_tx': 1},
    ], 'clusters': [{'cluster_id': 3, 'hypothesis': 'гипотеза теста', 'sum_kzt_internal': 12000}]}


def scripted(monkeypatch, responses):
    iterator = iter(responses)
    calls = []
    def callback(messages, **kwargs):
        calls.append(copy.deepcopy(messages))
        return next(iterator)
    monkeypatch.setattr(core, 'call_model', callback)
    return calls


def tool(name, arguments, call_id='one'):
    return {'id': call_id, 'name': name, 'arguments': arguments}


def test_ui_questions(graph):
    result = core.ask('Кого стоит проверить первым и почему?', graph)
    assert result['cited_gids'] == [B, A, C, D]
    assert 'два плательщика' in result['answer']
    result = core.ask('Какие узлы имеют признаки консолидации?', graph)
    assert result['cited_gids'] == [B, A]
    result = core.ask('Какие ограничения есть у этих данных?', graph)
    assert result['cited_gids'] == []
    assert 'seed' in result['answer'] and 'четвёртом' in result['answer']


@pytest.mark.parametrize('word', ['кластер', 'кластера', 'кластере'])
def test_cluster_and_role_together(graph, word):
    result = core.ask(f'Покажи консолидаторов {word} 3', graph)
    # Use the role noun and inflected cluster, not only the English enum.
    assert result['cited_gids'] == [A]


def test_cluster_summary(graph):
    result = core.ask('Опиши кластер 3', graph)
    assert result['cited_gids'] == [A, C]
    assert 'гипотеза теста' in result['answer']


def test_exact_gid_missing_metrics_and_unknown(graph):
    result = core.ask(f'Карточка узла {D}', graph)
    assert result['cited_gids'] == [D, C]
    assert 'четвёртом' in result['answer'] and 'не указано' in result['answer']
    assert core.ask(f'Узел {MISSING}', graph)['cited_gids'] == []
    result = core.ask(f'Путь от {A} до {MISSING}', graph)
    assert 'не найдены' in result['answer'] and result['cited_gids'] == []


def test_neighbors_and_paths(graph):
    result = core.ask(f'Кому переводил узел {A}?', graph)
    assert result['cited_gids'] == [A, C] and '5 000.00' in result['answer']
    result = core.ask(f'Входящие узла {C}', graph)
    assert result['cited_gids'] == [C, B, A]
    result = core.ask(f'Путь от {A} до {D}', graph)
    assert result['cited_gids'] == [A, C, D]
    assert ' → '.join([A, C, D]) in result['answer']
    assert 'не найден' in core.ask(f'Путь от {D} до {A}', graph)['answer']
    assert core.ask(f'Путь от {A} до {A}', graph)['cited_gids'] == [A]


def test_common_recipient_beyond_top_twenty(graph):
    for i in range(25):
        gid = str(200000000000000000 + i)
        graph['nodes'].append({'id': gid})
        graph['edges'].append({'source': A, 'target': gid, 'sum_kzt': 100000})
    graph['edges'].append(dict(graph['edges'][0]))  # duplicate edge is not another payer
    result = core.ask(f'Кто общий получатель от {A} и {B}?', graph)
    assert result['cited_gids'] == [A, B, C]
    assert 'всех 2' in result['answer']


def test_empty_and_optional_graph_fields(graph):
    assert core.ask('Кого проверить?', {})['cited_gids'] == []
    assert core.ask('Кого проверить?', None)['source'] == 'fallback'
    graph['nodes'][0]['metrics'] = None
    graph['nodes'][1]['priority_score'] = 'nan'
    graph['extras'] = None
    assert core.ask('Кого проверить?', graph)['cited_gids'][0] == A


@pytest.mark.parametrize('response', [None, {}, {'content': 'Человек украл 5 миллионов'},
    {'content': '{"result_indices":[0]}'}, {'content': '', 'tool_calls': 'wrong'}])
def test_no_tool_fabrications_fall_back(graph, monkeypatch, response):
    scripted(monkeypatch, [response])
    result = core.ask('Кого проверить первым?', graph)
    assert result['source'] == 'fallback' and result['cited_gids'][0] == B
    assert 'украл' not in result['answer']


def test_tool_roundtrip_selects_only_verified_results(graph, monkeypatch):
    calls = scripted(monkeypatch, [
        {'tool_calls': [tool('path_between', {'source_gid': A, 'target_gid': D})]},
        {'content': '{"result_indices":[0], "answer":"Человек украл миллиард"}'},
    ])
    result = core.ask(f'Путь от {A} до {D}', graph)
    assert result['source'] == 'llm' and result['cited_gids'] == [A, C, D]
    assert 'миллиард' not in result['answer']
    assert calls[1][-1]['role'] == 'tool' and C in calls[1][-1]['content']
    assert calls[1][-2]['tool_calls'][0]['function']['name'] == 'path_between'


@pytest.mark.parametrize('call', [tool('unknown', {}), tool('neighbors', {'gid': A, 'direction': 'both'}),
    tool('find_node', {'gid': int(A)}), tool('top_by_role', {'limit': -1}), tool('top_by_role', {'limit': True}),
    tool('common_recipients', {'gids': [A, A]}), tool('find_node', {'gid': A, 'surprise': 1}), None])
def test_invalid_tool_calls_fall_back(graph, monkeypatch, call):
    scripted(monkeypatch, [{'tool_calls': [call]}])
    assert core.ask('Кого проверить первым?', graph)['source'] == 'fallback'


@pytest.mark.parametrize('content', ['bad JSON', '{"result_indices":[9]}', '{"result_indices":[true]}', '{"result_indices":[]}'])
def test_invalid_result_selection_falls_back(graph, monkeypatch, content):
    scripted(monkeypatch, [{'tool_calls': [tool('find_node', {'gid': A})]}, {'content': content}])
    assert core.ask(f'Узел {A}', graph)['source'] == 'fallback'


def test_multi_tool_and_multi_turn(graph, monkeypatch):
    calls = scripted(monkeypatch, [
        {'tool_calls': [tool('top_by_role', {'role': 'consolidator', 'cluster_id': 3}), tool('data_limitations', {}, 'two')]},
        {'tool_calls': [tool('neighbors', {'gid': A, 'direction': 'out'}, 'three')]},
        {'content': '{"result_indices":[0,1,2]}'},
    ])
    result = core.ask('Сборщики кластера 3, их связи и ограничения', graph)
    assert result['source'] == 'llm' and result['cited_gids'] == [A, C]
    assert len(calls) == 3 and 'seed' in result['answer']


def test_provider_error_and_wall_clock_deadline(graph, monkeypatch):
    def fail(*a, **k):
        raise RuntimeError('provider unavailable')
    monkeypatch.setattr(core, 'call_model', fail)
    assert core.ask(f'Узел {A}', graph)['source'] == 'fallback'
    def slow(*a, **k):
        time.sleep(.3)
    monkeypatch.setattr(core, 'call_model', slow)
    monkeypatch.setattr(core, 'MODEL_BUDGET', .015)
    start = time.monotonic()
    assert core.ask(f'Узел {A}', graph)['source'] == 'fallback'
    assert time.monotonic() - start < .2


def test_input_graph_is_not_mutated(graph):
    before = copy.deepcopy(graph)
    for q in ['Кого проверить?', f'Узел {D}', 'Кластер 3', f'Путь от {A} до {D}']:
        core.ask(q, graph)
    assert graph == before


def test_short_unknown_path_gid(graph):
    tiny = {'nodes': [{'id': '1'}], 'edges': []}
    result = core.ask('Путь от 1 до 2', tiny)
    assert 'не найдены' in result['answer'] and result['cited_gids'] == []
