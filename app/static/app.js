/* Offline graph workspace. The model owns data; Cytoscape owns the persistent scene. */
"use strict";
(() => {
  const G = window.MiraiGraph,
    $ = id => document.getElementById(id);
  const roles = {
    consolidator: "Консолидация",
    transit: "Транзит",
    distributor: "Распределение",
    terminal: "Конечный",
    coordinator: "Координация",
    peripheral: "Периферия"
  };
  const colors = {
    consolidator: "#e4572e",
    transit: "#f3a712",
    distributor: "#2a9d8f",
    terminal: "#457b9d",
    coordinator: "#9d4edd",
    peripheral: "#b0b0b0"
  };
  const number = new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 2
  });
  const compact = new Intl.NumberFormat("ru-RU", {
    notation: "compact",
    maximumFractionDigits: 1
  });
  const state = {
    graph: null,
    model: null,
    nodes: new Map(),
    cy: null,
    selected: null,
    center: null,
    mode: "overview",
    cluster: "",
    role: "",
    direction: "both",
    expanded: new Set(),
    proof: null,
    positions: new Map(),
    locals: new Map(),
    viewKey: "global",
    history: [],
    compare: null,
    loadId: 0,
    version: "",
    bookmarks: []
  };
  const numeric = G.finite,
    priority = n => Math.max(0, Math.min(1, numeric(n.priority_score)));
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

  function element(tag, cls, text) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function roleColor(role) {
    const c = state.graph?.meta?.role_colors?.[role] || colors[role];
    return /^#[0-9a-f]{6}$/i.test(c || "") ? c : colors.peripheral;
  }

  function badge(role) {
    const el = element("span", "badge"),
      dot = element("i", "role-dot");
    dot.style.backgroundColor = roleColor(role);
    el.append(dot, document.createTextNode(roles[role] || role || "Нет роли"));
    return el;
  }

  function notice(text = "") {
    $("notice").textContent = text;
    $("notice").hidden = !text;
  }

  function emit(name, detail = {}) {
    window.dispatchEvent(new CustomEvent("mirai:" + name, {
      detail
    }));
  }
  const api = window.MiraiHttp.createRequest(window.fetch.bind(window));

  function graphState(text, loading = false) {
    const el = $("graph-state");
    el.replaceChildren();
    el.hidden = !text;
    if (loading) el.append(element("div", "spinner"));
    if (text) el.append(element("p", "", text));
    if (text && !loading && !state.graph) {
      const retry = element("button", "retry-load", "Повторить загрузку");
      retry.addEventListener("click", load);
      el.append(retry);
    }
  }

  function savePositions() {
    if (!state.cy) return;
    const map = state.viewKey === "global" ? state.positions : state.locals.get(state.viewKey);
    if (map) state.cy.nodes().forEach(n => map.set(n.id(), {
      ...n.position()
    }));
  }

  function snapshot() {
    return {
      selected: state.selected,
      center: state.center,
      mode: state.mode,
      cluster: state.cluster,
      role: state.role,
      direction: state.direction,
      expanded: [...state.expanded],
      proof: state.proof,
      zoom: state.cy?.zoom(),
      pan: state.cy ? {
        ...state.cy.pan()
      } : null
    };
  }

  function remember() {
    if (!state.graph) return;
    state.history.push(snapshot());
    if (state.history.length > 40) state.history.shift();
    $("back").disabled = false;
  }

  function restore(s) {
    const valid = id => id && state.nodes.has(id) ? id : null;
    state.selected = valid(s.selected);
    state.center = valid(s.center);
    state.mode = s.mode || "overview";
    if (state.mode === "ego" && !state.center) state.mode = "overview";
    state.cluster = state.model.clusters.has(String(s.cluster)) ? String(s.cluster) : "";
    state.role = Object.hasOwn(roles, s.role) ? s.role : "";
    state.direction = ["in", "out", "both"].includes(s.direction) ? s.direction : "both";
    state.expanded = new Set((s.expanded || []).filter(id => state.nodes.has(id)));
    state.proof = null;
    if (s.proof) state.proof = s.proof.kind === "evidence" ? G.evidence(state.model, {
      ...s.proof,
      edges: s.proof.edges.map(key => {
        const [source, target] = key.split(">");
        return {
          source,
          target
        };
      })
    }) : G.action(state.model, s.proof);
    draw();
    state.cy.stop();
    if (Number.isFinite(s.zoom) && s.pan) state.cy.viewport({
      zoom: s.zoom,
      pan: s.pan
    });
    else fit();
    emit(state.selected ? "select" : "clear", {
      gid: state.selected
    });
  }

  function topList() {
    const host = $("top-list");
    host.replaceChildren();
    const ids = state.model.ordered.slice(0, 50);
    $("top-count").textContent = ids.length;
    ids.forEach((id, i) => {
      const n = state.nodes.get(id),
        b = element("button", "top-row");
      b.type = "button";
      b.dataset.gid = id;
      b.title = n.priority_why || n.evidence || "Показать связи";
      const label = element("span", "node-label");
      label.append(element("strong", "", id), badge(n.role));
      b.append(element("span", "rank", String(i + 1).padStart(2, "0")), label, element("span",
        "priority-score", priority(n).toFixed(2)));
      b.addEventListener("click", () => focus(id));
      host.append(b);
    });
  }

  function camera(eles, {
    animate = true,
    padding = 45
  } = {}) {
    if (!eles?.length) return;
    state.cy.stop();
    const nodes = eles.nodes();
    if (!nodes.length) return;
    const xs = nodes.map(n => n.position("x")),
      ys = nodes.map(n => n.position("y"));
    const minX = Math.min(...xs) - 25,
      maxX = Math.max(...xs) + 25,
      minY = Math.min(...ys) - 25,
      maxY = Math.max(...ys) + 25;
    if (state.mode === "ego") padding = 24;
    const zoom = Math.max(.025, Math.min(1.6, (state.cy.width() - 2 * padding) / (maxX - minX), (state.cy
      .height() - 2 * padding) / (maxY - minY)));
    const pan = {
      x: state.cy.width() / 2 - (minX + maxX) / 2 * zoom,
      y: state.cy.height() / 2 - (minY + maxY) / 2 * zoom
    };
    if (animate && !reduced.matches) state.cy.animate({
      zoom,
      pan
    }, {
      duration: 220,
      easing: "ease-out-cubic"
    });
    else state.cy.viewport({
      zoom,
      pan
    });
  }

  function fit(animate = true) {
    camera(state.cy?.elements(), {
      animate
    });
  }
  let lodFrame = 0,
    lastLod = "";

  function detailLevel() {
    if (lodFrame) return;
    lodFrame = requestAnimationFrame(() => {
      lodFrame = 0;
      if (!state.cy) return;
      const z = state.cy.zoom();
      const scale = z < .07 ? 5 : z < .14 ? 3 : z < .28 ? 1.8 : 1;
      const fontScale = z < .2 ? 5 : z < .4 ? 3 : z < .8 ? 1.8 : 1;
      const key = scale + ":" + fontScale;
      if (key === lastLod) return;
      lastLod = key;
      state.cy.style().selector("node").style({
          width: n => n.data("size") * scale,
          height: n => n.data("size") * scale
        })
        .selector("edge").style({
          width: e => e.data("width") * Math.max(1, scale * .65),
          "arrow-scale": Math.max(.85, scale * .5)
        })
        .selector("node.hovered").style({
          label: "data(label)",
          "font-size": 11 * fontScale
        })
        .selector("node.focused").style({
          "font-size": 14 * fontScale
        }).update();
    });
  }

  function highlight() {
    if (!state.cy) return;
    const cy = state.cy;
    cy.batch(() => {
      cy.elements().removeClass("dim focused neighbor flow proof pinned compare");
      const selected = state.selected ? cy.getElementById(state.selected) : cy.collection();
      if (state.proof) {
        const ids = new Set(state.proof.gids),
          pairs = new Set(state.proof.edges || []);
        cy.elements().addClass("dim");
        cy.nodes().filter(n => ids.has(n.id())).removeClass("dim").addClass("proof");
        cy.edges().filter(e => pairs.size ? pairs.has(G.edgeKey(e.data("source"), e.data("target"))) :
          ids.has(e.data("source")) && ids.has(e.data("target"))).removeClass("dim").addClass("flow");
      } else if (selected.length) {
        const links = new Set(G.adjacent(state.model, state.selected, state.direction).map(e => e.id));
        cy.elements().addClass("dim");
        selected.removeClass("dim");
        cy.edges().filter(e => links.has(e.id())).removeClass("dim").addClass("flow").connectedNodes()
          .removeClass("dim").addClass("neighbor");
      }
      selected.removeClass("dim neighbor").addClass("focused");
      if (state.compare) cy.getElementById(state.compare).addClass("compare");
    });
    document.querySelectorAll(".top-row").forEach(el => {
      const yes = el.dataset.gid === state.selected;
      el.classList.toggle("selected", yes);
      el.setAttribute("aria-pressed", String(yes));
    });
    $("selection-state").textContent = state.proof?.label || (state.selected ? "Клиент " + state.selected :
      state.cluster !== "" ? "Кластер " + state.cluster : "Выберите клиента или кластер");
    $("clear-proof").hidden = !state.proof;
    $("direction").disabled = !state.center && !state.selected;
    $("expand").disabled = !state.selected;
    $("bookmark").disabled = !state.selected;
    updateExpansion();
    emit("context");
  }

  function updateExpansion() {
    if (!state.model || !state.cy) return;
    const selected = state.selected || (state.mode === "ego" ? state.center : null);
    const ids = new Set(state.cy.nodes().map(n => n.id()));
    const missing = selected ? [...G.neighbors(state.model, selected, state.direction)].filter(id => !ids.has(id)).length : 0;
    $("expand").textContent = !selected ? "Раскрыть связи" : missing ? "Ещё соседи: " + missing : "Все соседи показаны";
    $("expand").disabled = !selected || !missing;
  }

  function draw() {
    if (!state.cy || !state.model) return;
    savePositions();
    const ids = G.visible(state.model, state),
      key = state.cluster !== "" ? "global" : state.mode === "ego" ? "ego:" + state.center : state.mode === "overview" ? "overview" : "global";
    const changed = key !== state.viewKey;
    state.viewKey = key;
    if (key !== "global" && !state.locals.has(key)) state.locals.set(key, key === "overview" ? G.overviewPositions(state.model) : G.localPositions(state.model, state.center, ids));
    const positions = key === "global" ? state.positions : state.locals.get(key);
    const localDefaults = key === "global" ? null : key === "overview" ? G.overviewPositions(state.model) : G.localPositions(state.model, state.center, ids);
    const edges = state.model.edges.filter(e => ids.has(e.source) && ids.has(e.target));
    const wanted = new Set([...ids, ...edges.map(e => e.id)]),
      cy = state.cy;
    const max = Math.max(1, ...state.model.edges.map(e => numeric(e.sum_kzt))),
      logMax = Math.log1p(max);
    cy.batch(() => {
      cy.elements().filter(e => !wanted.has(e.id())).remove();
      for (const id of ids) {
        const n = state.nodes.get(id);
        if (!n) continue;
        if (!positions.has(id)) {
          const p = {...(localDefaults?.get(id) || {x: numeric(n.x), y: numeric(n.y)})};
          if (localDefaults) {
            while ([...positions.values()].some(old => Math.hypot(old.x - p.x, old.y - p.y) < 42)) p.y += 52;
          }
          positions.set(id, p);
        }
        const data = {
          id,
          label: id.length > 9 ? "…" + id.slice(-6) : id,
          color: roleColor(n.role),
          size: 16 + priority(n) * 18,
          cluster: String(n.cluster_id ?? ""),
          seed: !!n.is_seed,
          boundary: n.depth === 4 || n.flags?.includes("terminal_unknown")
        };
        let el = cy.getElementById(id);
        if (!el.length) el = cy.add({
          group: "nodes",
          data,
          position: positions.get(id)
        });
        else {
          el.data(data);
          if (changed) el.position(positions.get(id));
        }
      }
      for (const e of edges) {
        const data = {
          ...e,
          width: 1 + 2.5 * Math.log1p(Math.max(0, numeric(e.sum_kzt))) / logMax
        };
        const el = cy.getElementById(e.id);
        if (!el.length) cy.add({
          group: "edges",
          data
        });
        else el.data(data);
      }
    });
    cy.resize();
    highlight();
    detailLevel();
    $("visible-count").textContent = number.format(ids.size) + " из " + number.format(state.nodes.size) +
      " клиентов · " + number.format(edges.length) + " связей";
    document.querySelectorAll("[data-mode]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset
      .mode === state.mode && state.cluster === "")));
    $("cluster").value = state.cluster;
    $("role-filter").value = state.role;
    $("direction").value = state.direction;
    const local = state.mode === "ego" && state.cluster === "";
    const omitted = local ? [...G.neighbors(state.model, state.center, state.direction)].filter(id => !ids.has(id)).length : 0;
    $("view-description").textContent = local ?
      "Стрелка: отправитель → получатель. Плательщики слева, получатели справа. " +
      (omitted ? "Вне вида соседей: " + omitted + ". Начали с 12 крупнейших по сумме; раскройте остальные кнопкой выше." : "Все соседи выбранного направления показаны.") :
      state.mode === "overview" && state.cluster === "" ?
      "12 приоритетных клиентов. Нажмите на узел, чтобы открыть его связи. Здесь показаны только переводы между видимыми клиентами." :
      "Стрелка: отправитель → получатель. Толщина — сумма. Масштаб не скрывает связи.";
    updateExpansion();
    graphState(ids.size ? "" : "По выбранному фильтру нет клиентов. Сбросьте фильтр.");
  }

  function focus(gid, options = {}) {
    const id = String(gid);
    if (!state.nodes.has(id)) {
      notice("Клиент " + id + " не найден.");
      return;
    }
    if (options.remember !== false) remember();
    state.selected = id;
    state.proof = null;
    if (!options.keepView) {
      state.cluster = "";
      state.role = "";
      state.mode = "ego";
      state.center = id;
      state.expanded = new Set();
      state.direction = "both";
    }
    notice();
    draw();
    if (!options.keepView) fit();
    emit("select", {
      gid: id,
      fromChat: !!options.fromChat
    });
  }

  function showProof(proof) {
    if (!proof) return false;
    remember();
    state.proof = proof;
    state.role = "";
    state.expanded = new Set([...state.expanded, ...proof.gids]);
    draw();
    camera(state.cy.nodes().filter(n => proof.gids.includes(n.id())));
    return true;
  }

  function showAction(raw) {
    return showProof(G.action(state.model, raw));
  }

  function showEvidence(raw) {
    return showProof(G.evidence(state.model, raw));
  }

  function showConnections(gid, direction) {
    const edges = G.adjacent(state.model, gid, direction);
    showEvidence({
      label: (direction === "in" ? "Входящие" : "Исходящие") + " связи клиента " + gid,
      gids: [gid],
      edges
    });
  }

  function setCluster(value) {
    remember();
    state.cluster = String(value);
    state.selected = null;
    state.proof = null;
    state.mode = "top";
    state.expanded = new Set();
    state.role = "";
    draw();
    fit();
    emit("clear");
  }

  function initGraph() {
    if (state.cy) return;
    if (typeof cytoscape !== "function") throw new Error("Не загрузилась локальная библиотека графа.");
    state.cy = cytoscape({
      container: $("graph"),
      elements: [],
      layout: {
        name: "preset"
      },
      pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
      minZoom: .025,
      maxZoom: 4,
      hideEdgesOnViewport: false,
      textureOnViewport: false,
      motionBlur: false,
      boxSelectionEnabled: false,
      style: [{
        selector: "node",
        style: {
          "background-color": "data(color)",
          width: "data(size)",
          height: "data(size)",
          label: "",
          "border-width": 1.5,
          "border-color": "#152131",
          "overlay-opacity": 0
        }
      }, {
        selector: "node[?seed]",
        style: {
          shape: "diamond",
          "border-width": 2,
          "border-color": "#e2ecfa"
        }
      }, {
        selector: "node[?boundary]",
        style: {
          "border-style": "dashed",
          "border-width": 3,
          "border-color": "#edbd79"
        }
      }, {
        selector: "edge",
        style: {
          width: "data(width)",
          "line-color": "#778faa",
          "target-arrow-color": "#9eb4d0",
          "target-arrow-shape": "triangle",
          "curve-style": "bezier",
          "control-point-step-size": 35,
          opacity: .65,
          "arrow-scale": .9
        }
      }, {
        selector: ".dim",
        style: {
          opacity: .22
        }
      }, {
        selector: "node.hovered",
        style: {
          label: "data(label)",
          "font-size": 11,
          "color": "#dce7f5",
          "text-background-color": "#0e1621",
          "text-background-opacity": .95,
          "text-background-padding": "3px",
          "text-valign": "bottom",
          "text-margin-y": 6
        }
      }, {
        selector: "node.focused",
        style: {
          label: "data(label)",
          "font-size": 14,
          "font-weight": 600,
          color: "#fff",
          "text-background-color": "#182c40",
          "text-background-opacity": 1,
          "text-background-padding": "5px",
          "text-valign": "bottom",
          "text-margin-y": 8,
          "border-width": 4,
          "border-color": "#fff",
          opacity: 1,
          "z-index": 10
        }
      }, {
        selector: "node.proof",
        style: {
          "border-width": 3,
          "border-color": "#7ce2bf",
          opacity: 1
        }
      }, {
        selector: "node.compare",
        style: {
          "border-width": 4,
          "border-color": "#ffd58e"
        }
      }, {
        selector: "edge.flow",
        style: {
          opacity: 1,
          "line-color": "#b8d9ff",
          "target-arrow-color": "#b8d9ff",
          "z-index": 5
        }
      }]
    });
    state.cy.on("tap", "node", e => focus(e.target.id(), {
      keepView: state.mode !== "overview" || state.cluster !== ""
    }));
    state.cy.on("mouseover", "node", e => e.target.addClass("hovered"));
    state.cy.on("mouseout", "node", e => e.target.removeClass("hovered"));
    state.cy.on("tap", "edge", e => {
      state.cy.stop();
      emit("edge", {
        edge: e.target.data()
      });
    });
    state.cy.on("tap", e => {
      if (e.target === state.cy) {
        remember();
        state.selected = null;
        state.proof = null;
        highlight();
        emit("clear");
      }
    });
    state.cy.on("grab", () => state.cy.stop());
    state.cy.on("dragfree", "node", () => savePositions());
    state.cy.on("zoom", () => {
      $("zoom-level").textContent = Math.round(state.cy.zoom() * 100) + "%";
      detailLevel();
    });
    new ResizeObserver(() => {
      state.cy?.resize();
    }).observe($("graph"));
  }

  function readBookmarks() {
    try {
      const items = JSON.parse(localStorage.getItem("mirai.bookmarks.v1") || "[]");
      state.bookmarks = Array.isArray(items) ? items.filter(x => x && typeof x.gid === "string").slice(0,
        30) : [];
    } catch {
      state.bookmarks = [];
    }
    renderBookmarks();
  }

  function renderBookmarks() {
    const host = $("bookmarks");
    host.replaceChildren();
    for (const entry of state.bookmarks) {
      const row = element("div", "bookmark-row"),
        b = element("button", "", entry.gid + (entry.version !== state.version ? " · другая версия" : ""));
      b.type = "button";
      b.disabled = !state.nodes.has(entry.gid);
      b.addEventListener("click", () => {
        remember();
        if (entry.version === state.version && entry.view) restore(entry.view);
        else {
          focus(entry.gid, {
            remember: false
          });
          notice("Закладка из другой версии данных. Показаны актуальные связи.");
        }
      });
      const remove = element("button", "", "×");
      remove.setAttribute("aria-label", "Удалить закладку " + entry.gid);
      remove.addEventListener("click", () => {
        state.bookmarks = state.bookmarks.filter(x => x !== entry);
        persistBookmarks();
      });
      row.append(b, remove);
      host.append(row);
    }
    if (!state.bookmarks.length) host.append(element("p", "muted",
      "Сохраните клиента кнопкой ☆ над картой."));
  }

  function persistBookmarks() {
    try {
      localStorage.setItem("mirai.bookmarks.v1", JSON.stringify(state.bookmarks));
    } catch {
      notice("Хранилище браузера недоступно. Закладки останутся до закрытия страницы.");
    }
    renderBookmarks();
  }
  async function load() {
    const token = ++state.loadId;
    $("reload").disabled = true;
    graphState("Загружаем сеть…", true);
    try {
      const graph = await api("/api/graph?workspace=true");
      if (token !== state.loadId) return;
      if (!Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) throw new Error(
        "В ответе нет узлов или связей.");
      const previous = state.version,
        view = state.graph ? snapshot() : null;
      notice();
      savePositions();
      state.graph = graph;
      state.model = G.index(graph);
      state.nodes = state.model.nodes;
      state.version = String(graph.meta?.app_version || graph.meta?.dataset_version || graph.meta
        ?.generated_at || "unknown") + ":" + state.nodes.size + ":" + state.model.edges.length;
      if (previous && previous !== state.version) {
        state.history = [];
        state.locals.clear();
        state.positions.clear();
        state.viewKey = "global";
        state.cy?.elements().remove();
        state.proof = null;
        state.expanded = new Set();
        notice("Загружена новая версия данных. Проверьте прежние выводы и закладки.");
      }
      if (state.selected && !state.nodes.has(state.selected)) state.selected = null;
      if (state.center && !state.nodes.has(state.center)) {
        state.center = null;
        state.mode = "overview";
      }
      if (!state.model.clusters.has(state.cluster)) state.cluster = "";
      $("stat-nodes").textContent = number.format(state.nodes.size);
      $("stat-edges").textContent = number.format(state.model.edges.length);
      $("stat-volume").textContent = compact.format(numeric(graph.meta?.total_kzt));
      const date = new Date(graph.meta?.generated_at);
      $("generated").textContent = Number.isNaN(date.getTime()) ? "Данные загружены" : "Расчёт: " + date
        .toLocaleString("ru-RU", {
          day: "2-digit",
          month: "2-digit",
          hour: "2-digit",
          minute: "2-digit"
        });
      $("data-source").textContent = graph.meta?.app_data_source === "sample" ? "ДЕМО-ДАННЫЕ" :
        "Локальные данные";
      $("data-source").classList.toggle("sample-warning", graph.meta?.app_data_source === "sample");
      $("period").textContent = graph.meta?.period_start && graph.meta?.period_end ? "Период: " + graph
        .meta.period_start + " — " + graph.meta.period_end : "Период переводов: см. описание выборки";
      $("legend").replaceChildren(...Object.keys(roles).map(badge), element("span", "boundary-key",
        "◌ Граница данных"));
      const select = $("cluster");
      select.replaceChildren(new Option("Все кластеры", ""));
      [...state.model.clusters.keys()].filter(x => x !== "").sort((a, b) => numeric(a) - numeric(b))
        .forEach(id => select.add(new Option("Кластер " + id + " · " + state.model.clusters.get(id)
          .length, id)));
      topList();
      initGraph();
      draw();
      if (!view || previous !== state.version) fit(false);
      $("back").disabled = !state.history.length;
      readBookmarks();
      emit("loaded");
      if (state.selected) emit("select", {
        gid: state.selected
      });
    } catch (error) {
      if (token === state.loadId) {
        if (state.graph) {
          graphState("");
          notice(error.message + " На экране последний загруженный граф.");
          const retry = element("button", "retry-load", "Повторить загрузку");
          retry.addEventListener("click", load);
          $("notice").append(retry);
        } else graphState(error.message);
      }
    } finally {
      if (token === state.loadId) $("reload").disabled = false;
    }
  }
  let searchId = 0,
    searchTimer;

  function closeSearch() {
    searchId++;
    $("search-results").hidden = true;
    $("search").setAttribute("aria-expanded", "false");
  }

  function search(submit = false) {
    const q = $("search").value.trim(),
      host = $("search-results");
    if (!q || !state.model) {
      closeSearch();
      return;
    }
    const ids = state.model.ordered.filter(id => id.includes(q)).sort((a, b) => Number(b === q) - Number(
      a === q)).slice(0, 20);
    if (submit && (ids.includes(q) || ids.length === 1)) {
      focus(ids.includes(q) ? q : ids[0]);
      closeSearch();
      return;
    }
    host.replaceChildren();
    if (!ids.length) host.append(element("p", "", "Клиент не найден. Проверьте gid."));
    for (const id of ids) {
      const b = element("button", "", id);
      b.type = "button";
      b.append(badge(state.nodes.get(id).role));
      b.addEventListener("click", () => {
        focus(id);
        closeSearch();
      });
      host.append(b);
    }
    host.hidden = false;
    $("search").setAttribute("aria-expanded", "true");
  }
  $("search-form").addEventListener("submit", e => {
    e.preventDefault();
    clearTimeout(searchTimer);
    search(true);
  });
  $("search").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => search(), 120);
  });
  $("search-form").addEventListener("keydown", e => {
    if (e.key === "Escape") closeSearch();
    if (["ArrowDown", "ArrowUp"].includes(e.key)) {
      const list = [...$("search-results").querySelectorAll("button")];
      if (list.length) {
        e.preventDefault();
        const i = list.indexOf(document.activeElement);
        list[(i + (e.key === "ArrowDown" ? 1 : -1) + list.length) % list.length].focus();
      }
    }
  });
  document.addEventListener("click", e => {
    if (!$("search-form").contains(e.target)) closeSearch();
  });
  document.querySelectorAll("[data-mode]").forEach(b => b.addEventListener("click", () => {
    if (!state.graph) return;
    const mode = b.dataset.mode;
    if (mode === "ego" && !state.selected && !state.center) {
      notice("Выберите клиента для локальной схемы.");
      return;
    }
    remember();
    state.mode = mode;
    state.center = state.selected || state.center;
    if (mode === "overview") {
      state.selected = null;
      state.center = null;
      emit("clear");
    }
    state.cluster = "";
    state.proof = null;
    state.expanded = new Set();
    state.role = "";
    draw();
    fit();
  }));
  $("cluster").addEventListener("change", () => setCluster($("cluster").value));
  $("role-filter").append(...Object.entries(roles).map(([key, label]) => new Option(label, key)));
  $("role-filter").addEventListener("change", () => {
    if (!state.graph) return;
    remember();
    state.role = $("role-filter").value;
    state.proof = null;
    draw();
    fit();
  });
  $("direction").addEventListener("change", () => {
    if (!state.graph) return;
    remember();
    Object.assign(state, G.directionView(state, $("direction").value));
    draw();
    fit();
  });
  $("clear-proof").addEventListener("click", () => {
    state.proof = null;
    highlight();
  });
  $("expand").addEventListener("click", () => {
    const selected = state.selected || (state.mode === "ego" ? state.center : null);
    if (!selected) return;
    remember();
    const before = G.visible(state.model, state),
      add = G.neighbors(state.model, selected, state.direction);
    for (const id of add) state.expanded.add(id);
    draw();
    const after = G.visible(state.model, state);
    notice("Добавлено клиентов: " + [...after].filter(id => !before.has(id)).length +
      ". Уже открытые узлы сохранили положение.");
    fit();
  });
  $("back").addEventListener("click", () => {
    const view = state.history.pop();
    if (view) restore(view);
    $("back").disabled = !state.history.length;
  });
  $("reset-view").addEventListener("click", () => {
    remember();
    state.mode = "overview";
    state.cluster = "";
    state.role = "";
    state.direction = "both";
    state.selected = null;
    state.center = null;
    state.proof = null;
    state.expanded = new Set();
    draw();
    fit();
    notice();
    emit("clear");
  });
  $("reset-layout").addEventListener("click", () => {
    if (!state.cy) return;
    const ids = G.visible(state.model, state),
      map = state.viewKey === "global" ? state.positions : state.locals.get(state.viewKey),
      local = state.viewKey === "global" ? null : state.viewKey === "overview" ? G.overviewPositions(state.model) : G.localPositions(state.model, state.center, ids);
    state.cy.stop();
    state.cy.batch(() => state.cy.nodes().forEach(n => {
      const source = state.nodes.get(n.id()),
        p = local?.get(n.id()) || {
          x: numeric(source.x),
          y: numeric(source.y)
        };
      map.set(n.id(), p);
      n.position(p);
    }));
    fit();
    notice("Исходная раскладка текущего вида восстановлена.");
  });
  $("bookmark").addEventListener("click", () => {
    if (!state.selected) return;
    const entry = {
      gid: state.selected,
      version: state.version,
      view: snapshot()
    };
    state.bookmarks = state.bookmarks.filter(x => x.gid !== entry.gid || x.version !== entry.version);
    state.bookmarks.unshift(entry);
    state.bookmarks = state.bookmarks.slice(0, 30);
    persistBookmarks();
    notice("Клиент и текущий вид сохранены в закладках на этом устройстве.");
  });
  $("reload").addEventListener("click", load);
  $("fit").addEventListener("click", () => fit());
  for (const [id, m] of [
      ["zoom-in", 1.3],
      ["zoom-out", 1 / 1.3]
    ]) $(id).addEventListener("click", () => {
    if (!state.cy) return;
    state.cy.stop();
    const p = state.cy.pan(),
      z = state.cy.zoom(),
      next = Math.max(.025, Math.min(4, z * m)),
      cx = state.cy.width() / 2,
      cy = state.cy.height() / 2;
    const pan = {
      x: cx - (cx - p.x) * next / z,
      y: cy - (cy - p.y) * next / z
    };
    if (reduced.matches) state.cy.viewport({
      zoom: next,
      pan
    });
    else state.cy.animate({
      zoom: next,
      pan
    }, {
      duration: 160
    });
  });
  $("map-space").addEventListener("click", () => {
    const expanded = document.body.classList.toggle("map-expanded");
    $("map-space").setAttribute("aria-pressed", String(expanded));
    $("map-space").textContent = expanded ? "Вернуть панели" : "Больше карты";
  });
  $("export-svg").addEventListener("click", () => {
    if (!state.cy) return;
    const cy = state.cy;
    savePositions();
    const nodes = cy.nodes().map(n => ({
      id: n.id(),
      ...n.position(),
      color: n.data("color"),
      size: n.width(),
      seed: n.data("seed"),
      boundary: n.data("boundary"),
      label: n.hasClass("focused") || n.hasClass("proof"),
      opacity: n.hasClass("dim") ? .3 : 1
    }));
    const edges = cy.edges().map(e => ({
      ...e.data(),
      width: e.width(),
      color: e.hasClass("flow") ? "#b8d9ff" : "#9eb4d0",
      opacity: e.hasClass("dim") ? .25 : .85
    }));
    const text = G.svg({
      nodes,
      edges,
      title: "Mirai · " + (state.proof?.label || "наблюдаемые переводы")
    });
    const url = URL.createObjectURL(new Blob([text], {
      type: "image/svg+xml;charset=utf-8"
    }));
    const a = element("a");
    a.href = url;
    a.download = "mirai-graph.svg";
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    notice("SVG содержит текущий набор узлов и связей, включая элементы за краями окна.");
  });
  window.Mirai = {
    state,
    $,
    api,
    element,
    badge,
    roles,
    number,
    compact,
    focus,
    notice,
    numeric,
    showAction,
    showEvidence,
    showConnections,
    setCluster,
    highlight,
    metric: G.metric
  };
  load();
})();
