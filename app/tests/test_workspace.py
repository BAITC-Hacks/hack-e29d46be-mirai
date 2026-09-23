import json
import sys
import types

from fastapi.testclient import TestClient
from app.server import create_app, checked_actions


def sample():
    return {"meta": {}, "nodes": [{"id": "100000004015047100"}, {"id": "100000004015047101"}],
            "edges": [{"source": "100000004015047100", "target": "100000004015047101"}]}


def write(path, graph):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph), encoding="utf-8")


def test_workspace_version_source_and_original_contract(tmp_path):
    graph = sample()
    write(tmp_path / "shared/sample_graph.json", graph)
    client = TestClient(create_app(tmp_path))
    assert client.get('/api/graph').json() == graph
    data = client.get('/api/graph?workspace=true').json()
    assert data['meta']['app_data_source'] == 'sample'
    assert len(data['meta']['app_version']) == 24
    assert client.get('/api/graph').json() == graph
    write(tmp_path / "outputs/graph.json", {**graph, "meta": {"revision": 2}})
    updated = client.get('/api/graph?workspace=true').json()
    assert updated['meta']['app_data_source'] == 'outputs'
    assert updated['meta']['app_version'] != data['meta']['app_version']


def test_explicit_output_directory_does_not_serve_old_default(tmp_path):
    graph = sample()
    write(tmp_path / 'outputs/graph.json', graph)
    other = tmp_path / 'new-output'
    fresh = {**graph, 'meta': {'revision': 'fresh'}}
    write(other / 'graph.json', fresh)
    client = TestClient(create_app(tmp_path, output_dir=other))
    assert client.get('/api/graph').json()['meta']['revision'] == 'fresh'


def test_stale_assistant_request_is_rejected_before_call(tmp_path, monkeypatch):
    graph = sample()
    path = tmp_path / 'outputs/graph.json'
    write(path, graph)
    client = TestClient(create_app(tmp_path))
    version = client.get('/api/graph?workspace=true').json()['meta']['app_version']
    write(path, {**graph, 'meta': {'revision': 2}})
    def unexpected(*args):
        raise AssertionError('stale request reached provider')
    monkeypatch.setitem(sys.modules, 'assistant', types.SimpleNamespace(ask=unexpected, node_card=unexpected))
    assert client.post('/api/ask', json={'question':'Кого проверить?', 'graph_version':version}).status_code == 409
    assert client.get('/api/node/100000004015047100/card', params={'graph_version':version}).status_code == 409


def test_only_grounded_string_id_actions_cross_boundary(tmp_path, monkeypatch):
    graph = sample()
    a, b = (n['id'] for n in graph['nodes'])
    actions = [{'kind':'path','gids':[a,b], 'label':'Путь'},
               {'kind':'path','gids':[b,a]}, {'kind':'nodes','gids':['missing']},
               {'kind':'nodes','gids':[int(a)]}, {'kind':'nodes','gids':[a]},
               {'kind': [], 'gids':[a]}, None]
    valid = checked_actions(actions, graph)
    assert [r['gids'] for r in valid] == [[a,b], [a]]
    write(tmp_path/'outputs/graph.json', graph)
    monkeypatch.setitem(sys.modules,'assistant',types.SimpleNamespace(ask=lambda *args:{'answer':'Факты','source':'fallback','cited_gids':[a,b],'actions':actions}))
    result=TestClient(create_app(tmp_path)).post('/api/ask',json={'question':'Путь'}).json()
    assert result['actions'] == valid


def test_invalid_new_graph_does_not_change_previous_version(tmp_path):
    graph = sample()
    path = tmp_path/'outputs/graph.json'
    write(path,graph)
    client=TestClient(create_app(tmp_path))
    version=client.get('/api/graph?workspace=true').json()['meta']['app_version']
    path.write_text('{',encoding='utf-8')
    assert client.get('/api/graph?workspace=true').status_code == 503
    assert client.app.state.graph_store.version == version
    write(path,graph)
    assert client.get('/api/graph?workspace=true').json()['meta']['app_version'] == version
