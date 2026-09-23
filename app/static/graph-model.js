/* Shared graph operations: browser + Node regression tests. IDs are always strings. */
(function(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.MiraiGraph = api;
})(typeof window === "undefined" ? globalThis : window, function() {
  "use strict";
  const finite = (v, fallback = 0) => v !== null && v !== "" && Number.isFinite(Number(v)) ? Number(v) :
    fallback;
  const edgeKey = (a, b) => `${a}>${b}`;

  function index(graph) {
    const nodes = new Map(graph.nodes.map(n => [String(n.id), n]));
    const incoming = new Map(),
      outgoing = new Map(),
      clusters = new Map();
    for (const [id, n] of nodes) {
      incoming.set(id, []);
      outgoing.set(id, []);
      const cluster = String(n.cluster_id ?? "");
      if (!clusters.has(cluster)) clusters.set(cluster, []);
      clusters.get(cluster).push(id);
    }
    const counts = new Map();
    const edges = graph.edges.filter(e => nodes.has(String(e.source)) && nodes.has(String(e.target))).map(
      e => {
        const source = String(e.source),
          target = String(e.target),
          key = edgeKey(source, target);
        const occurrence = counts.get(key) || 0;
        counts.set(key, occurrence + 1);
        const edge = {
          ...e,
          source,
          target,
          id: `edge:${key}:${occurrence}`
        };
        incoming.get(target).push(edge);
        outgoing.get(source).push(edge);
        return edge;
      });
    const pairs = new Set(edges.map(e => edgeKey(e.source, e.target)));
    const ordered = [...nodes.values()].sort((a, b) => finite(b.priority_score) - finite(a
      .priority_score) || String(a.id).localeCompare(String(b.id))).map(n => String(n.id));
    return {
      nodes,
      incoming,
      outgoing,
      clusters,
      edges,
      pairs,
      ordered
    };
  }

  function adjacent(model, gid, direction = "both") {
    return [...(direction !== "out" ? model.incoming.get(gid) || [] : []), ...(direction !== "in" ? model
      .outgoing.get(gid) || [] : [])];
  }

  function neighbors(model, gid, direction = "both") {
    return new Set(adjacent(model, gid, direction).map(e => e.source === gid ? e.target : e.source).filter(
      id => id !== gid));
  }

  function strongestNeighbors(model, gid, direction = "both", limit = 12) {
    const sums = new Map();
    for (const e of adjacent(model, gid, direction)) {
      const id = e.source === gid ? e.target : e.source;
      if (id !== gid) sums.set(id, (sums.get(id) || 0) + Math.max(0, finite(e.sum_kzt)));
    }
    return [...sums].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, limit).map(([id]) => id);
  }

  function overviewPositions(model) {
    return new Map(model.ordered.slice(0, 12).map((id, i) => [id, {
      x: (i % 4) * 140, y: Math.floor(i / 4) * 95
    }]));
  }

  function visible(model, state) {
    let ids;
    if (state.cluster !== "") ids = new Set(model.clusters.get(String(state.cluster)) || []);
    else if (state.mode === "all") ids = new Set(model.nodes.keys());
    else if (state.mode === "overview") ids = new Set(model.ordered.slice(0, 12));
    else if (state.mode === "ego") {
      const center = state.center || state.selected;
      ids = new Set(center && model.nodes.has(center) ? [center, ...strongestNeighbors(model, center, state
        .direction)] : []);
    } else {
      const seeds = model.ordered.slice(0, 100);
      ids = new Set(seeds);
      for (const gid of seeds)
        for (const id of neighbors(model, gid)) ids.add(id);
    }
    for (const id of state.expanded || [])
      if (model.nodes.has(id)) ids.add(id);
    if (state.role) ids = new Set([...ids].filter(id => model.nodes.get(id)?.role === state.role));
    if (state.selected && model.nodes.has(state.selected)) ids.add(state.selected);
    if (state.proof)
      for (const id of state.proof.gids) ids.add(id);
    return ids;
  }

  function action(model, raw) {
    if (!raw || !["nodes", "path"].includes(raw.kind) || !Array.isArray(raw.gids) || !raw.gids.length || raw
      .gids.length > 500) return null;
    if (!raw.gids.every(id => typeof id === "string" && model.nodes.has(id))) return null;
    // Preserve the closing node of a cycle so history/bookmarks can replay it.
    const gids = raw.kind === "path" ? [...raw.gids] : [...new Set(raw.gids)],
      edges = [];
    if (raw.kind === "path") {
      for (let i = 1; i < raw.gids.length; i++) {
        const key = edgeKey(raw.gids[i - 1], raw.gids[i]);
        if (!model.pairs.has(key)) return null;
        edges.push(key);
      }
    }
    return {
      kind: raw.kind,
      gids,
      edges,
      label: typeof raw.label === "string" ? raw.label.slice(0, 180) : "Фрагмент графа"
    };
  }

  function evidence(model, raw) {
    if (!raw || !Array.isArray(raw.gids) || !Array.isArray(raw.edges) || raw.gids.length + raw.edges
      .length > 1000) return null;
    if (!raw.gids.every(g => typeof g === "string" && model.nodes.has(g))) return null;
    const gids = new Set(raw.gids),
      edges = [];
    for (const e of raw.edges) {
      if (!e || !model.pairs.has(edgeKey(e.source, e.target))) return null;
      gids.add(e.source);
      gids.add(e.target);
      edges.push(edgeKey(e.source, e.target));
    }
    return gids.size ? {
      kind: "evidence",
      gids: [...gids],
      edges,
      label: String(raw.label || "Основание в графе").slice(0, 180)
    } : null;
  }

  function path(model, source, target, maxHops = 12) {
    if (!model.nodes.has(source) || !model.nodes.has(target)) return null;
    const parents = new Map([
        [source, null]
      ]),
      queue = [
        [source, 0]
      ];
    for (let i = 0; i < queue.length && !parents.has(target); i++) {
      const [id, depth] = queue[i];
      if (depth >= maxHops) continue;
      for (const e of model.outgoing.get(id))
        if (!parents.has(e.target)) {
          parents.set(e.target, id);
          queue.push([e.target, depth + 1]);
        }
    }
    if (!parents.has(target)) return null;
    const result = [];
    for (let id = target; id !== null; id = parents.get(id)) result.push(id);
    return result.reverse();
  }

  function commonRecipients(model, a, b) {
    const recipients = new Set((model.outgoing.get(a) || []).map(e => e.target));
    return [...new Set((model.outgoing.get(b) || []).map(e => e.target).filter(id => recipients.has(id)))];
  }

  function localPositions(model, center, ids) {
    const positions = new Map([
      [center, {
        x: 0,
        y: 0
      }]
    ]);
    const ins = new Set((model.incoming.get(center) || []).map(e => e.source));
    const outs = new Set((model.outgoing.get(center) || []).map(e => e.target));
    const groups = [
      [],
      [],
      []
    ];
    for (const id of ids)
      if (id !== center) groups[ins.has(id) && !outs.has(id) ? 0 : outs.has(id) && !ins.has(id) ? 1 : 2]
        .push(id);
    groups.forEach((group, side) => {
      group.sort((a, b) => finite(model.nodes.get(b).priority_score) - finite(model.nodes.get(a)
        .priority_score) || a.localeCompare(b));
      group.forEach((id, i) => {
        const row = i % 6,
          column = Math.floor(i / 6),
          rows = Math.min(6, group.length - column * 6);
        const x = side === 0 ? -170 - column * 110 : side === 1 ? 170 + column * 110 : (row - (
          rows - 1) / 2) * 70;
        const y = side === 2 ? 150 + column * 85 : (row - (rows - 1) / 2) * 52;
        positions.set(id, {
          x,
          y
        });
      });
    });
    return positions;
  }

  function metric(value, key = "") {
    if (value === null || value === undefined) return "—";
    if (typeof value === "boolean") return value ? "Да" : "Нет";
    if (typeof value !== "number") return typeof value === "object" ? JSON.stringify(value) : String(value);
    if (!Number.isFinite(value)) return "—";
    if (key.includes("share") || key === "pass_through") return value.toLocaleString("ru-RU", {
      style: "percent",
      maximumFractionDigits: 1
    });
    if (["pagerank", "seed_exposure", "betweenness", "priority_contribution"].includes(key) || (value !== 0 && Math.abs(value) <
      .01)) return value.toLocaleString("ru-RU", {
      maximumSignificantDigits: 4
    });
    return value.toLocaleString("ru-RU", {
      maximumFractionDigits: 2
    });
  }
  const xml = value => String(value).replace(/[&<>"']/g, c => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&apos;"
  } [c]));

  function svg(scene) {
    const ns = scene.nodes,
      es = scene.edges,
      pos = new Map(ns.map(n => [n.id, n]));
    const pairs = new Set(es.map(e => edgeKey(e.source, e.target)));
    const xs = ns.map(n => n.x),
      ys = ns.map(n => n.y);
    const margin = Math.max(100, ...ns.map(n => (n.size || 20) / 2 + 30));
    const left = Math.min(0, ...xs) - margin - 60,
      top = Math.min(0, ...ys) - margin;
    const width = Math.max(320, Math.max(0, ...xs) - left + margin + 60),
      height = Math.max(240, Math.max(0, ...ys) - top + margin);
    let s =
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${left} ${top} ${width} ${height}" role="img"><title>${xml(scene.title || "Mirai: фрагмент графа")}</title><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L8,4 L0,8 Z" fill="#9eb4d0"/></marker></defs><rect x="${left}" y="${top}" width="${width}" height="${height}" fill="#0e1621"/><text x="${left+20}" y="${top+30}" fill="#e7edf5" font-family="sans-serif" font-size="16">${xml(scene.title || "Mirai · наблюдаемые переводы")}</text>`;
    for (const e of es) {
      const a = pos.get(e.source),
        b = pos.get(e.target);
      if (!a || !b) continue;
      const dx = b.x - a.x,
        dy = b.y - a.y,
        d = Math.hypot(dx, dy) || 1,
        r = (b.size || 20) / 2 + 7;
      let curve;
      if (a.id === b.id) curve =
        `M${a.x-8},${a.y-8} C${a.x-70},${a.y-90} ${a.x+70},${a.y-90} ${a.x+8},${a.y-8}`;
      else if (pairs.has(edgeKey(e.target, e.source))) {
        const bend = 28;
        curve =
          `M${a.x},${a.y} Q${(a.x+b.x)/2-dy/d*bend},${(a.y+b.y)/2+dx/d*bend} ${b.x-dx/d*r},${b.y-dy/d*r}`;
      } else curve = `M${a.x},${a.y} L${b.x-dx/d*r},${b.y-dy/d*r}`;
      s +=
        `<path d="${curve}" fill="none" stroke="${xml(e.color||"#9eb4d0")}" stroke-width="${finite(e.width,1.5)}" opacity="${finite(e.opacity,.8)}" marker-end="url(#arrow)"><title>${xml(`${e.source} → ${e.target}: ${metric(e.sum_kzt)} ₸, ${metric(e.n_tx)} переводов`)}</title></path>`;
    }
    for (const n of ns) {
      const r = (n.size || 20) / 2,
        color = /^#[0-9a-f]{6}$/i.test(n.color || "") ? n.color : "#b0b0b0";
      s += `<g opacity="${finite(n.opacity,1)}"><title>${xml(n.id)}</title>`;
      s += n.seed ?
        `<polygon points="${n.x},${n.y-r} ${n.x+r},${n.y} ${n.x},${n.y+r} ${n.x-r},${n.y}" fill="${color}" stroke="#e7edf5"/>` :
        `<circle cx="${n.x}" cy="${n.y}" r="${r}" fill="${color}" stroke="#c7d3e2"${n.boundary?' stroke-dasharray="3 3"':''}/>`;
      if (n.label) s +=
        `<text x="${n.x}" y="${n.y+r+16}" text-anchor="middle" fill="#e7edf5" font-size="12" font-family="sans-serif">${xml(n.id)}</text>`;
      s += '</g>';
    }
    return s +
      `<text x="${left+20}" y="${top+height-20}" fill="#bdcbe0" font-size="12" font-family="sans-serif">${xml(`${ns.length} клиентов · ${es.length} связей. Стрелка — направление. Выводы — гипотезы; выборка неполна.`)}</text></svg>`;
  }
  return {
    index,
    adjacent,
    neighbors,
    strongestNeighbors,
    overviewPositions,
    visible,
    action,
    evidence,
    path,
    commonRecipients,
    localPositions,
    metric,
    finite,
    edgeKey,
    svg
  };
});
