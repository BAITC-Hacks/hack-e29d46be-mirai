const {test} = require('node:test');
const assert = require('node:assert/strict');
const G = require('../static/graph-model.js');
const A = '100000004015047100', B = '100000001616816100';
const node = (id, x, y, extra = {}) => ({id, x, y, width: 32, height: 32,
  shape: 'ellipse', color: '#e4572e', backgroundOpacity: 1,
  borderColor: '#7ce2bf', borderWidth: 3, borderOpacity: 1, borderStyle: 'solid',
  opacity: 1, label: '', ...extra});
const edge = (extra = {}) => ({id: 'forward', source: A, target: B,
  start: {x: -35, y: 132}, end: {x: -4, y: 15}, controls: [{x: -52, y: 75}],
  width: 2, color: '#b8d9ff', opacity: 1, arrowOpacity: 1, arrowColor: '#b8d9ff',
  arrowShape: 'triangle', arrowScale: .9, lineCap: 'butt', lineStyle: 'solid', ...extra});
const scene = extra => ({title: 'Mirai <script> & path', nodes: [node(A, -35, 150),
  node(B, 0, 0, {shape: 'diamond'})], edges: [edge()], ...extra});

test('reciprocal path keeps its supplied bend side and source/target endpoints', () => {
  const reverse = edge({id: 'reverse', source: B, target: A, start: {x: 4, y: 15},
    end: {x: -30, y: 135}, controls: [{x: 17, y: 75}], color: '#778faa', opacity: .22});
  const s = G.svg(scene({edges: [edge(), reverse]}));
  assert(s.includes('M-35,132 Q-52,75'));
  assert(s.includes('M4,15 Q17,75'));
  assert(s.includes('points="-4,15 ')); // Arrow tip remains on the target boundary.
  assert(s.includes('stroke="#7ce2bf" stroke-width="3"'));
  assert(s.includes('fill="#b8d9ff" opacity="1"'));
  assert(s.includes('opacity="0.22"'));
});

test('SVG keeps computed styles, short labels, shape and boundary dash', () => {
  const n = node(B, 0, 0, {shape: 'diamond', label: '…816100', borderStyle: 'dashed',
    fontFamily: 'Helvetica', fontWeight: '600', fontSize: 14, textOpacity: 1,
    textColor: '#fff', textMarginY: 8, textBackground: '#182c40',
    textBackgroundOpacity: 1, textPadding: 5,
    labelBounds: {x1: -30, y1: 22, x2: 30, y2: 40}});
  const s = G.svg(scene({nodes: [node(A, -35, 150, {opacity: .22}), n]}));
  assert(s.includes('<ellipse')); assert(s.includes('<polygon'));
  assert(s.includes('stroke-dasharray="4 2"'));
  assert(s.includes('fill="#182c40"'));
  assert(s.includes('>…816100</text>'));
  assert(!s.includes(`>${B}</text>`));
  assert(s.includes(`<title>${B}</title>`)); // Exact gid retained as metadata.
  assert(!s.includes('<image')); assert(!s.includes('<script>'));
  assert(s.includes('&lt;script&gt; &amp;'));
});

test('loops use two actual quadratic segments and bounds include off-node controls', () => {
  const s = G.svg(scene({edges: [edge({source: A, target: A,
    controls: [{x: -600, y: -500}, {x: 600, y: -500}]})]}));
  assert(s.includes('Q-600,-500 0,-500 Q600,-500'));
  assert(s.includes('viewBox="-640 -570 1280'));
});

test('straight edges stay straight; an unavailable renderer fails visibly', () => {
  const s = G.svg(scene({edges: [edge({controls: [], arrowShape: 'none'})]}));
  assert(s.includes('M-35,132 L-4,15')); assert(!s.includes(' Q'));
  assert.throws(() => G.svg(scene({edges: [edge({end: {x: NaN, y: 0}})]})), /Геометрия/);
});

test('scene capture uses computed style and fresh model geometry after a drag', () => {
  const computed = {shape: 'diamond', 'background-color': 'rgb(228,87,46)',
    'border-color': 'rgb(124,226,191)', 'border-width': 3, label: '…816100',
    'background-opacity': 1, 'border-opacity': 1, 'line-opacity': 1,
    'line-color': 'rgb(184,217,255)', 'target-arrow-color': 'rgb(184,217,255)',
    'target-arrow-shape': 'triangle', 'arrow-scale': .9};
  let x = 20;
  const common = {visible: () => true, style: key => computed[key] || '',
    numericStyle: key => computed[key] ?? 0, effectiveOpacity: () => .22,
    width: () => 32};
  const n = {...common, id: () => B, position: () => ({x, y: 10}), height: () => 32,
    boundingBox: () => ({x1: 0, y1: 0, x2: 50, y2: 50})};
  const e = {...common, data: () => ({id: 'e', source: A, target: B}),
    sourceEndpoint: () => ({x: 0, y: 0}), targetEndpoint: () => ({x, y: 5}),
    controlPoints: () => [{x: x - 70, y: 0}]};
  const cy = {nodes: () => [n], edges: () => [e]};
  const before = G.svgScene(cy, 'Path'); x = 60;
  const after = G.svgScene(cy, 'Path');
  assert.equal(before.nodes[0].x, 20); assert.equal(after.nodes[0].x, 60);
  assert.equal(after.nodes[0].borderColor, computed['border-color']);
  assert.equal(after.nodes[0].opacity, .22);
  assert.equal(after.edges[0].end.x, 60);
  assert.equal(after.edges[0].controls[0].x, -10);
  assert.equal(after.edges[0].color, computed['line-color']);
});
