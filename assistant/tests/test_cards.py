import json
import time
from unittest.mock import Mock

import pytest
from assistant import cards


@pytest.fixture
def graph(monkeypatch):
    monkeypatch.setattr(cards, 'call_model', None)
    return {'nodes': [{'id': '100000004015047100', 'depth': 4, 'is_seed': True,
                       'flags': ['truncated_by_depth'], 'metrics': {'in_deg': 2}},
                      {'id': '100000004015047101'}],
            'edges': [{'source': '100000004015047101', 'target': '100000004015047100'}]}


def test_boundary_warning_seed_missing_role_and_amount(graph):
    text = cards.node_card('100000004015047100', graph)['text']
    assert 'не найден' not in text
    assert 'роль не указана' in text
    assert 'не доказывает' in text
    assert 'Входящие seed' in text
    assert 'Входящие: не указано' in text
    assert '100000004015047101' in text
    assert '0.00 ₸' not in text


def test_unknown_gid_and_minimal_graph():
    assert cards.node_card('404', {})['source'] == 'template'
    assert 'не найден' in cards.node_card('404', {})['text']


def test_provider_failure_returns_template(graph, monkeypatch):
    monkeypatch.setattr(cards, 'call_model', Mock(side_effect=RuntimeError('failed')))
    assert cards.node_card('100000004015047100', graph)['source'] == 'template'


@pytest.mark.parametrize('reply', ['invented person and balance', '{"attention_index":99}', '{"attention_index":true}', 'null'])
def test_generated_unverified_facts_never_displayed(graph, monkeypatch, reply):
    monkeypatch.setattr(cards, 'call_model', lambda *args, **kwargs: {'content': reply})
    assert cards.node_card('100000004015047100', graph)['source'] == 'template'


def test_llm_selects_grounded_followup(graph, monkeypatch):
    monkeypatch.setattr(cards, 'call_model', lambda *args, **kwargs: {'content': json.dumps({'attention_index': 3})})
    answer = cards.node_card('100000004015047100', graph)
    assert answer['source'] == 'llm'
    assert 'за пределами четвёртого колена' in answer['text']


def test_wall_clock_timeout():
    started = time.monotonic()
    assert cards.bounded_call(lambda **kwargs: time.sleep(.3), timeout=.015) is None
    assert time.monotonic() - started < .2


def test_inputs_not_mutated_and_zero_preserved(graph):
    before = json.dumps(graph)
    cards.node_card('100000004015047101', graph)
    assert json.dumps(graph) == before
    assert cards.amount(0) == '0.00 ₸'


def test_pipeline_signal_labels_and_different_denominators(graph):
    graph['meta'] = {'flag_labels': {'rapid_outflow': 'Близость дат без сопоставления сумм',
                                     'fast_transit': 'Строгое сопоставление входящих'},
                     'metric_labels': {'sync_in_days': 'Дней синхронных поступлений'}}
    node = graph['nodes'][0]
    node['flags'] = ['rapid_outflow', 'fast_transit', 'terminal_unknown']
    node['metrics'].update(fast_forward_share=.6, fast_transit_share=.8, sync_in_days=2)
    before = json.dumps(graph, ensure_ascii=False)
    text = cards.node_card(node['id'], graph)['text']
    assert '60.0% исходящей суммы' in text
    assert '80.0% входящей суммы' in text
    assert 'суммы не сопоставлены' in text and 'FIFO' in text
    assert 'Близость дат без сопоставления сумм (rapid_outflow)' in text
    assert 'Строгое сопоставление входящих (fast_transit)' in text
    assert 'Дней синхронных поступлений: 2' in text
    assert 'Конечный получатель не подтверждён' in text and 'четвёртом' in text
    assert json.dumps(graph, ensure_ascii=False) == before


@pytest.mark.parametrize('meta', [None, {}, {'flag_labels': None, 'metric_labels': []},
                                  {'flag_labels': {'rapid_outflow': 42}}])
def test_missing_or_invalid_labels_keep_raw_flags(graph, meta):
    graph['meta'] = meta
    graph['nodes'][0]['flags'] = ['rapid_outflow']
    text = cards.node_card(graph['nodes'][0]['id'], graph)['text']
    assert 'rapid_outflow' in text and 'четвёртом' in text


def test_terminal_unknown_metric_without_flags(graph):
    node = graph['nodes'][1]
    node['metrics'] = {'terminal_unknown': True}
    assert 'Конечный получатель не подтверждён' in cards.node_card(node['id'], graph)['text']
