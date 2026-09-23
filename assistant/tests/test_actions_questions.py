"""Russian intents, explicit context and graph-backed map actions (#37)."""
import copy
import json

import pytest

from assistant import core
from assistant.actions import validated_actions

A, B, C, D = [str(100000000000000101 + i) for i in range(4)]
UNKNOWN = '999999999999999999'


@pytest.fixture
def graph(monkeypatch):
    monkeypatch.setattr(core, 'call_model', None)
    return {'nodes': [{'id': A, 'role': 'consolidator', 'cluster_id': 3, 'priority_score': .9},
                      {'id': B, 'role': 'transit', 'cluster_id': 3},
                      {'id': C}, {'id': D}],
            'edges': [{'source': A, 'target': B, 'sum_kzt': 100},
                      {'source': C, 'target': B, 'sum_kzt': 200},
                      {'source': B, 'target': D, 'sum_kzt': 300}]}


@pytest.mark.parametrize('question', [
    'Кто переводит деньги узлу {gid}?', 'Кто переводил узлу {gid}?',
    'Кто перевёл деньги узлу {gid}?', 'Кто ему отправлял? gid {gid}',
    'Кто перечислял деньги клиенту {gid}?', 'Кто платил узлу {gid}?',
    'От кого узел {gid} получал деньги?', 'Покажи входящие узла {gid}',
    'Расскажи о входящих переводах узла {gid}', 'Отправители для gid {gid}',
    'Кто является плательщиком для узла {gid}?', 'Откуда поступали деньги на gid {gid}?',
])
def test_incoming_russian_forms(graph, question):
    result = core.ask(question.format(gid=B), graph)
    assert result['source'] == 'fallback'
    assert result['answer'].startswith('Входящие связи')
    assert result['cited_gids'] == [B, C, A]
    assert D not in result['cited_gids']


@pytest.mark.parametrize('question', [
    'Кому переводил узел {gid}?', 'Куда он отправлял деньги? gid {gid}',
    'Кто получал деньги от узла {gid}?', 'Покажи исходящие узла {gid}',
    'Об исходящих переводах клиента {gid}', 'Получатели для gid {gid}',
    'Узел {gid} отправлял деньги — покажи связи',
])
def test_outgoing_russian_forms(graph, question):
    result = core.ask(question.format(gid=B), graph)
    assert result['answer'].startswith('Исходящие связи')
    assert result['cited_gids'] == [B, D]


def test_both_directions(graph):
    result = core.ask(f'Покажи входящие и исходящие узла {B}', graph)
    assert 'Входящие связи' in result['answer'] and 'Исходящие связи' in result['answer']
    assert result['cited_gids'] == [B, C, A, D]


def context(gid, question):
    return f'Контекст выбранного клиента: gid {gid}.\nВопрос: {question}'


@pytest.mark.parametrize('question,direction,expected', [
    ('Кто ему отправлял?', 'Входящие', [B, C, A]),
    ('Кому он переводит?', 'Исходящие', [B, D]),
    ('Покажи его карточку', 'Узел', [B, C, A, D]),
])
def test_selected_context(graph, question, direction, expected):
    result = core.ask(context(B, question), graph)
    assert result['answer'].startswith(direction)
    assert result['cited_gids'] == expected


def test_question_gid_overrides_selected_context(graph):
    result = core.ask(context(B, f'Кому переводил узел {A}?'), graph)
    assert result['answer'].startswith(f'Исходящие связи узла {A}')
    assert result['cited_gids'] == [A, B]
    result = core.ask(context(B, f'Кто переводит узлу {UNKNOWN}?'), graph)
    assert 'не найдены' in result['answer'] and result['cited_gids'] == []


@pytest.mark.parametrize('question', ['Кого стоит проверить первым?', 'Покажи консолидаторов кластера 3',
                                      'Какие ограничения есть у данных?', 'Опиши кластер 3',
                                      'Покажи клиентов с признаками консолидации'])
def test_global_questions_ignore_selection(graph, question):
    assert core.ask(context(B, question), graph) == core.ask(question, graph)


def test_no_implicit_history_or_unknown_selection(graph):
    core.ask(f'Покажи узел {B}', graph)
    assert core.ask('Кто ему отправлял?', graph)['cited_gids'] == []
    result = core.ask(context(UNKNOWN, 'Кто ему отправлял?'), graph)
    assert 'не найдены' in result['answer'] and not result['cited_gids']


def test_path_action_is_ordered_and_directed(graph):
    result = core.ask(f'Покажи путь от {A} до {D}', graph)
    assert result['actions'] == [{'kind': 'path', 'label': 'Показать путь', 'gids': [A, B, D]}]
    assert not core.ask(f'Путь от {D} до {A}', graph).get('actions')
    assert not core.ask(f'Путь от {A} до {UNKNOWN}', graph).get('actions')
    result = core.ask(f'Путь от {A} до {A}', graph)
    assert result['actions'][0]['kind'] == 'nodes' and result['actions'][0]['gids'] == [A]


def test_common_recipients_action(graph):
    result = core.ask(f'Общие получатели от {A} и {C}', graph)
    assert result['actions'][0]['kind'] == 'nodes'
    assert result['actions'][0]['gids'] == [A, C, B]
    assert not core.ask(f'Общие получатели от {A} и {D}', graph).get('actions')


@pytest.mark.parametrize('action', [
    {'kind': 'path', 'label': 'bad', 'gids': [D, B, A]},  # reverse only
    {'kind': 'path', 'label': 'bad', 'gids': [A, D]},  # missing direct edge
    {'kind': 'path', 'label': 'bad', 'gids': [A, UNKNOWN]},
    {'kind': 'path', 'label': 'bad', 'gids': [A]},
    {'kind': 'path', 'label': 'bad', 'gids': [A, B, A]},
    {'kind': 'nodes', 'label': 'bad', 'gids': [int(A)]},  # precision must not be inferred
    {'kind': 'nodes', 'label': 'bad', 'gids': [UNKNOWN]},
    {'kind': 'nodes', 'label': 'bad', 'gids': []},
    {'kind': 'nodes', 'label': '', 'gids': [A]},
    {'kind': 'nodes', 'label': {'text': 'bad'}, 'gids': [A]},
    {'kind': 'delete', 'label': 'bad', 'gids': [A]}, None,
])
def test_actions_reject_invalid_or_unproven_paths(graph, action):
    assert validated_actions([action], graph, [A, B, C, D, UNKNOWN]) == []


def test_actions_must_be_cited_deduplicated_and_not_mutate_input(graph):
    action = {'kind': 'nodes', 'label': ' Show ', 'gids': [A, A, B]}
    before = copy.deepcopy(action)
    assert validated_actions([action], graph, [A]) == []
    assert validated_actions([action, action], graph, [A, B]) == [{'kind': 'nodes', 'label': 'Show', 'gids': [A, B]}]
    assert action == before


def test_llm_selects_tool_action_and_cannot_forge_one(graph, monkeypatch):
    replies = iter([
        {'tool_calls': [{'id': 'path1', 'name': 'path_between', 'arguments': {'source_gid': A, 'target_gid': D}}]},
        {'content': json.dumps({'result_indices': [0], 'actions': [{'kind': 'path', 'label': 'forged', 'gids': [D, A]}]}),
         'actions': [{'kind': 'nodes', 'label': 'forged', 'gids': [UNKNOWN]}]},
    ])
    monkeypatch.setattr(core, 'call_model', lambda *args, **kwargs: next(replies))
    result = core.ask(f'Путь от {A} до {D}', graph)
    assert result['source'] == 'llm'
    assert result['actions'] == [{'kind': 'path', 'label': 'Показать путь', 'gids': [A, B, D]}]


@pytest.mark.parametrize('reply', [None, {'content': 'not json'}, {'content': '{"result_indices":[true]}'},
    {'content': json.dumps({'result_indices': [0], 'actions': [{'kind': 'nodes', 'label': 'fake', 'gids': [UNKNOWN]}]})}])
def test_malformed_model_has_only_offline_action(graph, monkeypatch, reply):
    monkeypatch.setattr(core, 'call_model', lambda *args, **kwargs: reply)
    result = core.ask(f'Путь от {A} до {D}', graph)
    assert result['source'] == 'fallback'
    assert result['actions'][0]['gids'] == [A, B, D]


def test_none_provider_without_mocked_core(graph, monkeypatch):
    from assistant.llm import call_model
    monkeypatch.setenv('LLM_PROVIDER', 'none')
    monkeypatch.setattr(core, 'call_model', call_model)
    result = core.ask(f'Путь от {A} до {D}', graph)
    assert result['source'] == 'fallback' and result['actions'][0]['gids'] == [A, B, D]


def test_model_receives_resolved_selection(graph, monkeypatch):
    observed = []
    def callback(messages, **kwargs):
        observed.append(messages[1]['content'])
        return None
    monkeypatch.setattr(core, 'call_model', callback)
    core.ask(context(B, f'Кому переводил узел {A}?'), graph)
    assert observed == [f'Кому переводил узел {A}?']
