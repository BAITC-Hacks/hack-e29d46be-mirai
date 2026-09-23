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

  function directionView(state, direction) {
    const center = state.selected || state.center;
    return {
      direction,
      center,
      mode: center ? "ego" : state.mode,
      cluster: center ? "" : state.cluster,
      role: center ? "" : state.role,
      expanded: new Set(),
      proof: null
    };
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

  // Capture computed styles and public model-space geometry; never rerun layout.
  function svgScene(cy, title) {
    const number = (el, name) => finite(el.numericStyle(name));
    const nodes = cy.nodes().filter(n => n.visible()).map(n => ({
      id: n.id(), ...n.position(), width: n.width(), height: n.height(),
      shape: n.style("shape"), color: n.style("background-color"),
      backgroundOpacity: number(n, "background-opacity"),
      borderColor: n.style("border-color"), borderWidth: number(n, "border-width"),
      borderOpacity: number(n, "border-opacity"), borderStyle: n.style("border-style"),
      opacity: n.effectiveOpacity(), z: number(n, "z-index"),
      label: n.style("label"), fontSize: number(n, "font-size"),
      fontFamily: n.style("font-family"), fontWeight: n.style("font-weight"),
      textColor: n.style("color"), textOpacity: number(n, "text-opacity"),
      textMarginY: number(n, "text-margin-y"),
      textBackground: n.style("text-background-color"),
      textBackgroundOpacity: number(n, "text-background-opacity"),
      textPadding: number(n, "text-background-padding"),
      labelBounds: n.boundingBox({includeNodes: false, includeEdges: false,
        includeLabels: true, includeOverlays: false, includeUnderlays: false})
    })).sort((a, b) => a.z - b.z);
    const edges = cy.edges().filter(e => e.visible()).map(e => ({
      ...e.data(), start: e.sourceEndpoint(), end: e.targetEndpoint(),
      controls: e.controlPoints() || [], width: e.width(),
      color: e.style("line-color"), opacity: e.effectiveOpacity() * number(e, "line-opacity"),
      lineCap: e.style("line-cap"), lineStyle: e.style("line-style"),
      arrowColor: e.style("target-arrow-color"), arrowShape: e.style("target-arrow-shape"),
      arrowScale: number(e, "arrow-scale"), arrowOpacity: e.effectiveOpacity(),
      z: number(e, "z-index")
    })).sort((a, b) => a.z - b.z);
    return {title, nodes, edges};
  }

  function svg(scene) {
    const {nodes, edges} = scene;
    const point = p => p && Number.isFinite(p.x) && Number.isFinite(p.y);
    const xy = p => `${p.x},${p.y}`;
    // A missing renderer endpoint must not silently turn into an invented curve.
    for (const e of edges) {
      if (!point(e.start) || !point(e.end) || !e.controls.every(point))
        throw new Error("Геометрия графа ещё не готова. Повторите экспорт SVG.");
    }
    const bounds = [];
    for (const n of nodes) {
      const pad = n.borderWidth / 2;
      bounds.push({x: n.x - n.width / 2 - pad, y: n.y - n.height / 2 - pad},
        {x: n.x + n.width / 2 + pad, y: n.y + n.height / 2 + pad});
      const b = n.labelBounds;
      if (n.label && b && Number.isFinite(b.x1) && Number.isFinite(b.y1))
        bounds.push({x: b.x1, y: b.y1}, {x: b.x2, y: b.y2});
    }
    for (const e of edges) bounds.push(e.start, e.end, ...e.controls);
    const xs = bounds.map(p => p.x), ys = bounds.map(p => p.y);
    const left = Math.min(0, ...xs) - 40, top = Math.min(0, ...ys) - 70;
    const width = Math.max(720, Math.max(0, ...xs) - left + 40);
    const height = Math.max(240, Math.max(0, ...ys) - top + 70);
    let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${left} ${top} ${width} ${height}" role="img"><title>${xml(scene.title)}</title><rect x="${left}" y="${top}" width="${width}" height="${height}" fill="#0e1621"/><text x="${left+20}" y="${top+30}" fill="#e7edf5" font-family="sans-serif" font-size="16">${xml(scene.title)}</text>`;
    for (const e of edges) {
      const last = e.controls.at(-1) || e.start;
      const dx = e.end.x - last.x, dy = e.end.y - last.y;
      const length = Math.hypot(dx, dy) || 1, ux = dx / length, uy = dy / length;
      const arrow = e.arrowShape === "triangle";
      // Cytoscape 3.30.4 triangle gap/size (vendored renderer, MIT).
      // Public targetEndpoint is the arrow tip; the line stops before it.
      const gap = arrow ? 2 * e.width * e.arrowScale : 0;
      const end = {x: e.end.x - ux * gap, y: e.end.y - uy * gap};
      let d = `M${xy(e.start)}`;
      if (!e.controls.length) d += ` L${xy(end)}`;
      else e.controls.forEach((c, i) => {
        const next = e.controls[i + 1];
        const join = next ? {x: (c.x + next.x) / 2, y: (c.y + next.y) / 2} : end;
        d += ` Q${xy(c)} ${xy(join)}`;
      });
      const dash = e.lineStyle === "dashed" ? ' stroke-dasharray="6 3"' : e.lineStyle === "dotted" ? ' stroke-dasharray="1 1"' : '';
      s += `<g data-edge-id="${xml(e.id)}"><title>${xml(`${e.source} → ${e.target}: ${metric(e.sum_kzt)} ₸, ${metric(e.n_tx)} переводов`)}</title><path d="${d}" fill="none" stroke="${xml(e.color)}" stroke-width="${e.width}" stroke-linecap="${xml(e.lineCap)}" opacity="${e.opacity}"${dash}/>`;
      if (arrow) {
        const size = .3 * Math.max(Math.pow(13.37 * e.width, .9), 29) * e.arrowScale;
        const back = {x: e.end.x - ux * size, y: e.end.y - uy * size};
        const a = {x: back.x - uy * size / 2, y: back.y + ux * size / 2};
        const b = {x: back.x + uy * size / 2, y: back.y - ux * size / 2};
        s += `<polygon points="${xy(e.end)} ${xy(a)} ${xy(b)}" fill="${xml(e.arrowColor)}" opacity="${e.arrowOpacity}"/>`;
      }
      s += '</g>';
    }
    for (const n of nodes) {
      const rx = n.width / 2, ry = n.height / 2;
      const dash = n.borderStyle === "dashed" ? ' stroke-dasharray="4 2"' : n.borderStyle === "dotted" ? ' stroke-dasharray="1 1"' : '';
      const style = `fill="${xml(n.color)}" fill-opacity="${n.backgroundOpacity}" stroke="${xml(n.borderColor)}" stroke-width="${n.borderWidth}" stroke-opacity="${n.borderOpacity}"${dash}`;
      s += `<g data-node-id="${xml(n.id)}" opacity="${n.opacity}"><title>${xml(n.id)}</title>`;
      s += n.shape === "diamond" ?
        `<polygon points="${n.x},${n.y-ry} ${n.x+rx},${n.y} ${n.x},${n.y+ry} ${n.x-rx},${n.y}" ${style}/>` :
        `<ellipse cx="${n.x}" cy="${n.y}" rx="${rx}" ry="${ry}" ${style}/>`;
      if (n.label) {
        const b = n.labelBounds;
        if (n.textBackgroundOpacity && b && Number.isFinite(b.x1)) {
          // Cytoscape label bounding boxes include a 2px renderer allowance.
          const p = n.textPadding - 2;
          s += `<rect x="${b.x1-p}" y="${b.y1-p}" width="${b.x2-b.x1+2*p}" height="${b.y2-b.y1+2*p}" fill="${xml(n.textBackground)}" opacity="${n.textBackgroundOpacity}"/>`;
        }
        s += `<text x="${n.x}" y="${n.y+ry+n.textMarginY}" dominant-baseline="text-before-edge" text-anchor="middle" fill="${xml(n.textColor)}" opacity="${n.textOpacity}" font-size="${n.fontSize}" font-family="${xml(n.fontFamily)}" font-weight="${xml(n.fontWeight)}">${xml(n.label)}</text>`;
      }
      s += '</g>';
    }
    return s + `<text x="${left+20}" y="${top+height-20}" fill="#bdcbe0" font-size="12" font-family="sans-serif">${xml(`${nodes.length} клиентов · ${edges.length} связей. Стрелка — направление. Выводы — гипотезы; выборка неполна.`)}</text></svg>`;
  }
  return {
    index,
    adjacent,
    neighbors,
    strongestNeighbors,
    overviewPositions,
    directionView,
    visible,
    action,
    evidence,
    path,
    commonRecipients,
    localPositions,
    metric,
    finite,
    edgeKey,
    svgScene,
    svg
  };
});
