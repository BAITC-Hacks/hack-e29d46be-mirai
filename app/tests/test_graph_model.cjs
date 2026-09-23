const {
  test
} = require('node:test');
const assert = require('node:assert/strict');
const G = require('../static/graph-model.js');
const A = '100000004015047100',
  B = '100000004015047101',
  C = '100000004015047102';
const graph = {
  nodes: [{
    id: A,
    cluster_id: 0,
    priority_score: .9
  }, {
    id: B,
    cluster_id: 27,
    priority_score: .2
  }, {
    id: C,
    cluster_id: 27,
    priority_score: .1
  }],
  edges: [{
    source: A,
    target: B,
    sum_kzt: 10
  }, {
    source: B,
    target: C,
    sum_kzt: 20
  }]
};
const model = G.index(graph);
const state = extra => ({
  mode: 'top',
  cluster: '',
  selected: null,
  center: null,
  role: '',
  direction: 'both',
  expanded: new Set(),
  ...extra
});
test('cluster selection includes members outside top neighborhood', () => {
  const many = {
    nodes: Array.from({
      length: 110
    }, (_, i) => ({
      id: String(i),
      priority_score: 110 - i,
      cluster_id: i < 105 ? 0 : 27
    })),
    edges: []
  };
  const m = G.index(many);
  assert.equal(G.visible(m, state()).has('109'), false);
  assert.deepEqual([...G.visible(m, state({
    cluster: '27'
  }))], ['105', '106', '107', '108', '109']);
});
test('ego center survives clearing selection and filters respect direction', () => {
  assert.deepEqual([...G.visible(model, state({
    mode: 'ego',
    center: B,
    selected: null,
    direction: 'in'
  }))].sort(), [A, B]);
  assert.deepEqual([...G.visible(model, state({
    mode: 'ego',
    center: B,
    selected: null,
    direction: 'out'
  }))].sort(), [B, C]);
});
test('edge identity is independent of current filtered order', () => {
  const reordered = G.index({
    ...graph,
    edges: [...graph.edges].reverse()
  });
  assert.deepEqual(model.edges.map(e => e.id).sort(), reordered.edges.map(e => e.id).sort());
  assert.notEqual(model.edges[0].source, model.edges[0].target);
});
test('expand never drops existing context; proof remains visible through filters', () => {
  const s = state({
    mode: 'ego',
    center: C,
    expanded: new Set([A])
  });
  assert.deepEqual([...G.visible(model, s)].sort(), [A, B, C]);
  const proof = G.action(model, {
    kind: 'path',
    gids: [A, B, C]
  });
  assert.deepEqual([...G.visible(model, state({
    role: 'missing',
    proof
  }))].sort(), [A, B, C]);
});
test('actions reject reversed, invented and rounded paths', () => {
  assert.equal(G.action(model, {
    kind: 'path',
    gids: [C, A]
  }), null);
  assert.equal(G.action(model, {
    kind: 'path',
    gids: [A, C]
  }), null);
  assert.equal(G.action(model, {
    kind: 'nodes',
    gids: [Number(B)]
  }), null);
  assert.deepEqual(G.action(model, {
    kind: 'path',
    gids: [A, B, C]
  }).edges, [A + '>' + B, B + '>' + C]);
  assert.equal(G.evidence(model, {
    gids: [A],
    edges: [{
      source: A,
      target: C
    }]
  }), null);
  assert.deepEqual(G.evidence(model, {
    gids: [A],
    edges: [{
      source: A,
      target: B
    }]
  }).gids, [A, B]);
});
test('directed path and common recipients use all edges, including beyond first twenty', () => {
  assert.deepEqual(G.path(model, A, C), [A, B, C]);
  assert.equal(G.path(model, C, A), null);
  assert.equal(G.path(model, A, C, 1), null);
  assert.deepEqual(G.path(model, A, A), [A]);
  const nodes = [{
    id: A
  }, {
    id: B
  }, ...Array.from({
    length: 30
  }, (_, i) => ({
    id: String(i)
  }))];
  const m = G.index({
    nodes,
    edges: [...Array.from({
      length: 30
    }, (_, i) => ({
      source: A,
      target: String(i)
    })), {
      source: B,
      target: '29'
    }]
  });
  assert.deepEqual(G.commonRecipients(m, A, B), ['29']);
});
test('formatting preserves small positive metrics and distinguishes missing from zero', () => {
  assert.notEqual(G.metric(.00001345, 'seed_exposure'), '0');
  assert.equal(G.metric(null), '—');
  assert.equal(G.metric(0), '0');
  assert.match(G.metric(.3, 'fast_transit_share'), /30/);
  assert.match(G.metric(2.3, 'pass_through'), /230/);
});
test('local layout is deterministic, finite, and separates payers and recipients', () => {
  const p = G.localPositions(model, B, [A, B, C]);
  assert(p.get(A).x < 0);
  assert.equal(p.get(B).x, 0);
  assert(p.get(C).x > 0);
  assert.deepEqual([...p], [...G.localPositions(model, B, [C, A, B])]);
});
test('closed cycle retains its closing edge when replayed from history', () => {
  const m = G.index({
    ...graph,
    edges: [...graph.edges, {
      source: C,
      target: A
    }]
  });
  const cycle = G.action(m, {
    kind: 'path',
    gids: [A, B, C, A]
  });
  assert.deepEqual(G.action(m, JSON.parse(JSON.stringify(cycle))).edges, [A + '>' + B, B + '>' + C, C +
    '>' + A
  ]);
});

test('overview contains twelve clients without implicitly expanding neighbors',()=>{
  const nodes=Array.from({length:40},(_,i)=>({id:String(i),priority_score:40-i}));
  const m=G.index({nodes,edges:[{source:'0',target:'39',sum_kzt:1000}]});
  const ids=G.visible(m,state({mode:'overview'}));
  assert.equal(ids.size,12);assert(!ids.has('39'));
  const positions=G.overviewPositions(m);
  assert.equal(positions.size,12);
  assert.equal(new Set([...positions.values()].map(p=>p.x+','+p.y)).size,12);
});

test('ego starts with strongest twelve neighbors and explicit expansion restores all',()=>{
  const nodes=[{id:A},...Array.from({length:30},(_,i)=>({id:String(i)}))];
  const edges=Array.from({length:30},(_,i)=>({source:String(i),target:A,sum_kzt:i+1}));
  const m=G.index({nodes,edges});const s=state({mode:'ego',center:A});
  const ids=G.visible(m,s);assert.equal(ids.size,13);assert(ids.has('29'));assert(!ids.has('0'));
  const expanded=G.visible(m,{...s,expanded:G.neighbors(m,A)});assert.equal(expanded.size,31);
  assert.deepEqual([...ids],[...G.visible(m,{...s,zoom:.025})]);
  const proof=G.evidence(m,{gids:[A,'0'],edges:[{source:'0',target:A}]});
  assert(G.visible(m,{...s,proof}).has('0'));
});

test('strongest neighbors sum reciprocal edges and obey direction',()=>{
  const m=G.index({nodes:[{id:A},{id:B},{id:C}],edges:[{source:A,target:B,sum_kzt:6},{source:B,target:A,sum_kzt:6},{source:A,target:C,sum_kzt:10}]});
  assert.deepEqual(G.strongestNeighbors(m,A,'both',1),[B]);
  assert.deepEqual(G.strongestNeighbors(m,A,'out',1),[C]);
  assert.deepEqual(G.strongestNeighbors(m,A,'in',1),[B]);
});

test('direction change follows the clicked client rather than the previous ego center', () => {
  const previous = state({mode: 'ego', center: A, selected: B});
  assert.deepEqual([...G.visible(model, previous)], [A, B]);
  const next = {...previous, ...G.directionView(previous, 'out')};
  assert.equal(next.center, B);
  assert.deepEqual([...G.visible(model, next)], [B, C]);
  assert.equal(previous.center, A); // History can still restore the previous scene.
  assert.deepEqual([...G.visible(model, {...next, ...G.directionView(next, 'in')})], [B, A]);
});

test('direction change clears expansions, proof and filters that hide the selected client neighbors', () => {
  const previous = state({mode: 'all', center: A, selected: B, cluster: '0', role: 'unmatched',
    expanded: new Set([A]), proof: {gids: [A]}});
  const next = {...previous, ...G.directionView(previous, 'out')};
  assert.equal(next.mode, 'ego');
  assert.equal(next.expanded.size, 0);
  assert.equal(next.proof, null);
  assert.deepEqual([...G.visible(model, next)], [B, C]);
  assert.deepEqual([...previous.expanded], [A]);
});

test('direction change retains the ego center when selection has been cleared', () => {
  const previous = state({mode: 'ego', center: B});
  const next = {...previous, ...G.directionView(previous, 'out')};
  assert.equal(next.selected, null);
  assert.deepEqual([...G.visible(model, next)], [B, C]);
});
