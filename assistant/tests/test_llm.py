import json
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from assistant import llm


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for key in list(os.environ):
        if key.startswith(('LLM_', 'NVIDIA_', 'OPENAI_', 'ANTHROPIC_')):
            monkeypatch.delenv(key)
    monkeypatch.setenv('LLM_PROVIDER', 'nvidia')
    monkeypatch.setenv('NVIDIA_API_KEY', 'test-key-not-a-secret')
    monkeypatch.setattr(llm, '_cache_path', lambda key: tmp_path / (key + '.json'))


def stub_openai(monkeypatch):
    import openai
    factory = MagicMock()
    message = SimpleNamespace(content='Ответ', tool_calls=[])
    factory.return_value.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=message)])
    monkeypatch.setattr(openai, 'OpenAI', factory)
    return factory


@pytest.mark.parametrize('provider,default,key', [
    ('nvidia', llm.DEFAULT_NVIDIA_MODEL, 'NVIDIA_API_KEY'),
    ('openai', 'gpt-4o-mini', 'OPENAI_API_KEY'),
])
def test_blank_model_uses_default_in_actual_request(monkeypatch, provider, default, key):
    factory = stub_openai(monkeypatch)
    monkeypatch.setenv('LLM_PROVIDER', provider)
    monkeypatch.setenv(key, 'fake')
    monkeypatch.setenv('LLM_MODEL', '  ')
    monkeypatch.setenv('NVIDIA_BASE_URL', '')
    assert llm.call_model([{'role': 'user', 'content': 'test'}])['content'] == 'Ответ'
    kwargs = factory.return_value.chat.completions.create.call_args.kwargs
    assert kwargs['model'] == default
    assert kwargs['max_tokens'] == 700
    factory.return_value.close.assert_called_once()


@pytest.mark.parametrize('value', ['', 'bad', 'nan', 'inf', '-1', '0'])
def test_invalid_timeout_never_escapes(monkeypatch, value):
    factory = stub_openai(monkeypatch)
    monkeypatch.setenv('LLM_TIMEOUT', value)
    assert llm.call_model([]) is not None
    assert factory.call_args.kwargs['timeout'] == 20


def test_remaining_deadline_respected(monkeypatch):
    factory = stub_openai(monkeypatch)
    llm.call_model([], timeout=.25)
    assert factory.call_args.kwargs['timeout'] == .25


def test_none_and_missing_key_never_send(monkeypatch):
    factory = stub_openai(monkeypatch)
    monkeypatch.setenv('LLM_PROVIDER', 'none')
    assert llm.call_model([]) is None
    monkeypatch.setenv('LLM_PROVIDER', 'nvidia')
    monkeypatch.delenv('NVIDIA_API_KEY')
    assert llm.call_model([]) is None
    factory.assert_not_called()


def test_cache_hit_endpoint_change_corruption_and_secrets(monkeypatch, tmp_path):
    factory = stub_openai(monkeypatch)
    messages = [{'role': 'user', 'content': 'Привет'}]
    assert llm.call_model(messages) == llm.call_model(messages)
    assert factory.call_count == 1
    text = next(tmp_path.glob('*.json')).read_text(encoding='utf-8')
    assert 'test-key-not-a-secret' not in text
    assert 'Ответ' in text
    for file in tmp_path.glob('*.json'):
        file.write_text('{bad', encoding='utf-8')
    assert llm.call_model(messages) is not None
    assert factory.call_count == 2
    monkeypatch.setenv('NVIDIA_BASE_URL', 'https://example.invalid/v1')
    assert llm.call_model(messages) is not None
    assert factory.call_count == 3


def test_concurrent_cache_write_is_atomic(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, '_openai_call', lambda *args: {'content': 'ok', 'tool_calls': []})
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: llm.call_model([]), range(30)))
    assert all(r['content'] == 'ok' for r in results)
    assert len(list(tmp_path.glob('*.json'))) == 1
    assert not list(tmp_path.glob('*.tmp'))
    assert json.loads(next(tmp_path.glob('*.json')).read_text())['content'] == 'ok'


def test_provider_failure_and_unwritable_cache(monkeypatch):
    factory = stub_openai(monkeypatch)
    factory.return_value.chat.completions.create.side_effect = RuntimeError('mock')
    assert llm.call_model([]) is None
    factory.return_value.chat.completions.create.side_effect = None
    monkeypatch.setattr(llm.Path, 'mkdir', MagicMock(side_effect=OSError('read only')))
    assert llm.call_model([])['content'] == 'Ответ'


def test_anthropic_tool_roundtrip_and_invalid_max_tokens(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'anthropic')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake')
    monkeypatch.setenv('LLM_MODEL', '')
    monkeypatch.setenv('LLM_MAX_TOKENS', 'bad')
    opener = MagicMock()
    opener.return_value.__enter__.return_value.read.return_value = json.dumps(
        {'content': [{'type': 'tool_use', 'id': 'next', 'name': 'find_node', 'input': {'gid': '123'}}]}).encode()
    monkeypatch.setattr(llm, 'urlopen', opener)
    messages = [
        {'role': 'user', 'content': 'query'},
        {'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': 'one', 'function': {'name': 'find_node', 'arguments': '{"gid":"123"}'}}]},
        {'role': 'tool', 'tool_call_id': 'one', 'content': '{"gid":"123"}'},
    ]
    assert llm.call_model(messages)['tool_calls'][0]['arguments'] == {'gid': '123'}
    payload = json.loads(opener.call_args.args[0].data)
    assert payload['model'] == 'claude-haiku-4-5-20251001'
    assert payload['max_tokens'] == 700
    assert payload['messages'][1]['content'][0]['id'] == 'one'
    assert payload['messages'][2]['content'][0]['tool_use_id'] == 'one'
