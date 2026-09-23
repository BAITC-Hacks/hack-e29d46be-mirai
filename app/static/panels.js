"use strict";
(() => {
  const M = window.Mirai,
    G = window.MiraiGraph;
  if (!M) return;
  window.MiraiPanels = true;
  const {
    $,
    element,
    api,
    badge,
    state,
    metric
  } = M;
  const labels = {
    in_deg: "Плательщиков",
    out_deg: "Получателей",
    in_kzt: "Входящие, ₸",
    out_kzt: "Исходящие, ₸",
    in_tx: "Входящих переводов",
    out_tx: "Исходящих переводов",
    pagerank: "Влияние (PageRank)",
    pass_through: "Видимые исходящие / входящие",
    seed_exposure: "Близость к seed по потоку",
    n_seed_up2: "Seed в пределах 2 переводов",
    betweenness: "Посредничество",
    fast_forward_share: "Исходящие рядом по датам с поступлением",
    fast_transit_share: "Входящие, сопоставленные с выходом за 1–2 дня",
    same_day_transit_share_upper_bound: "Верхняя оценка с учётом того же дня",
    sync_in_days: "Дней синхронных поступлений",
    sync_max_payers: "Максимум плательщиков за день",
    transit_observation_complete_share: "Доля поступлений с полным окном наблюдения",
    repeated_route_count: "Найденных повторяющихся маршрутов",
    in_cycle: "Есть направленный цикл",
    likely_true_terminal: "Признаки конечного получателя",
    terminal_unknown: "Нельзя установить оседание средств",
    truncated_by_depth: "Граница четвёртого колена",
    transit_seed_caveat: "Неполные входящие seed"
  };
  const flags = {
    fast_transit: "Сопоставленный транзит за 1–2 дня",
    rapid_outflow: "Исходящие вскоре после поступления",
    gather_scatter: "Сбор и раздача",
    in_cycle: "Найден направленный цикл",
    truncated_by_depth: "Обрыв на 4-м колене",
    sync_inflow: "Синхронные поступления",
    synchronous_in: "Синхронные поступления",
    likely_true_terminal: "Признаки конечного получателя",
    terminal_unknown: "Конечный получатель не установлен",
    isolated_seed: "Seed без наблюдаемых переводов"
  };

  function label(key, kind = "metric") {
    const meta = state.graph?.meta?.[kind === "metric" ? "metric_labels" : "flag_labels"];
    return meta && typeof meta[key] === "string" ? meta[key] : (kind === "metric" ? labels[key] : flags[
      key]) || key;
  }
  const host = $("details-panel");
  host.replaceChildren();
  const tabs = element("div", "detail-tabs");
  tabs.setAttribute("role", "tablist");
  const detailTab = element("button", "", "Клиент"),
    chatTab = element("button", "", "Ассистент");
  detailTab.id = "detail-tab";
  chatTab.id = "chat-tab";
  const panel = element("div", "detail-scroll");
  panel.id = "node-panel";
  panel.setAttribute("role", "tabpanel");
  panel.setAttribute("aria-labelledby", "detail-tab");
  const chat = element("div", "chat-panel");
  chat.id = "chat-panel";
  chat.setAttribute("role", "tabpanel");
  chat.setAttribute("aria-labelledby", "chat-tab");
  chat.hidden = true;
  let hasChat = false,
    selectionId = 0;

  function showTab(isChat) {
    panel.hidden = isChat;
    chat.hidden = !isChat;
    for (const [b, selected] of [
        [detailTab, !isChat],
        [chatTab, isChat]
      ]) {
      b.setAttribute("aria-selected", String(selected));
      b.tabIndex = selected ? 0 : -1;
    }
  }
  for (const [button, target] of [
      [detailTab, panel],
      [chatTab, chat]
    ]) {
    button.type = "button";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", target.id);
    button.addEventListener("click", () => showTab(target === chat));
    tabs.append(button);
  }
  tabs.addEventListener("keydown", e => {
    if (["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) {
      e.preventDefault();
      const next = e.key === "Home" ? false : e.key === "End" ? true : chat.hidden;
      showTab(next);
      (next ? chatTab : detailTab).focus();
    }
  });
  host.append(tabs, panel, chat);
  showTab(false);

  function button(text, fn, cls = "") {
    const b = element("button", cls, text);
    b.type = "button";
    b.addEventListener("click", fn);
    return b;
  }

  function section(title, parent = panel) {
    const s = element("section", "node-section");
    if (title) s.append(element("h3", "", title));
    parent.append(s);
    return s;
  }

  function backToChat() {
    if (hasChat) panel.append(button("← Вернуться к ответу ассистента", () => showTab(true),
    "return-chat"));
  }

  function empty() {
    selectionId++;
    panel.replaceChildren();
    backToChat();
    const block = element("div", "empty detail-empty");
    block.append(element("span", "empty-symbol", "◎"), element("h3", "", "Выберите клиента"), element("p",
      "",
      "Поиск и список открывают локальную схему. Нажмите на связь, чтобы увидеть сумму и направление."));
    panel.append(block);
  }
  empty();

  function connections(title, edges, direction, gid) {
    const block = element("details", "connections"),
      summary = element("summary", "", title + " · " + edges.length);
    block.append(summary);
    block.append(button("Показать эти связи на карте", () => M.showConnections(gid, direction === "source" ?
      "in" : "out"), "text-action"));
    const list = element("div", "connection-list");
    if (!edges.length) list.append(element("p", "muted", "В выборке нет таких переводов."));
    for (const e of edges.slice().sort((a, b) => M.numeric(b.sum_kzt) - M.numeric(a.sum_kzt))) {
      const id = e[direction],
        b = button((direction === "source" ? "← " : "→ ") + id, () => M.focus(id));
      b.append(element("span", "", metric(e.sum_kzt) + " ₸ · " + metric(e.n_tx) + " пер."));
      list.append(b);
    }
    block.append(list);
    panel.append(block);
  }

  function compare(gid) {
    if (!state.compare || state.compare === gid || !state.nodes.has(state.compare)) return;
    const a = state.nodes.get(state.compare),
      b = state.nodes.get(gid),
      s = section("Сравнение клиентов");
    s.append(button("A: " + a.id, () => M.focus(a.id), "text-action"), element("p", "", "B: " + gid));
    const table = element("table", "compare-table"),
      head = element("tr");
    for (const t of ["Показатель", "A", "B"]) head.append(element("th", "", t));
    table.append(head);
    for (const [name, av, bv] of [
        ["Роль", M.roles[a.role] || a.role, M.roles[b.role] || b.role],
        ["Приоритет", metric(a.priority_score), metric(b.priority_score)], ...["in_kzt", "out_kzt",
          "in_deg", "out_deg"
        ].map(k => [label(k), metric(a.metrics?.[k], k), metric(b.metrics?.[k], k)])
      ]) {
      const row = element("tr");
      for (const v of [name, av, bv]) row.append(element("td", "", v || "—"));
      table.append(row);
    }
    s.append(table);
    const common = G.commonRecipients(state.model, a.id, gid);
    s.append(button("Общие получатели: " + common.length, () => M.showEvidence({
      label: "Общие получатели двух клиентов",
      gids: [a.id, gid, ...common],
      edges: common.flatMap(target => [{
        source: a.id,
        target
      }, {
        source: gid,
        target
      }])
    })), button("Путь A → B", () => {
      const path = G.path(state.model, a.id, gid);
      if (path) M.showAction({
        kind: "path",
        label: "Направленный путь A → B (до 12 шагов)",
        gids: path
      });
      else M.notice(
        "В пределах 12 шагов направленный путь не найден. Это не исключает более длинный путь.");
    }));
    if (!common.length) s.querySelectorAll("button")[1].disabled = true;
    s.append(element("p", "muted", "Общие связи и путь не доказывают перевод одной и той же суммы."));
  }

  function extras(n) {
    const x = state.graph.extras || {},
      cycles = Array.isArray(x.cycles) ? x.cycles.filter(c => Array.isArray(c) && c.includes(n.id)) : [],
      routes = Array.isArray(x.repeated_routes) ? x.repeated_routes.filter(r => Array.isArray(r.gids) && r
        .gids.includes(n.id)) : [];
    if (!cycles.length && !routes.length && x.cycles_complete !== false && x.repeated_routes_complete !==
      false) return;
    const s = section("Паттерны сети");
    for (const [items, title] of [
        [cycles.map(gids => ({
          gids
        })), "Цикл"],
        [routes, "Маршрут"]
      ]) {
      for (const r of items.slice(0, 5)) s.append(button(title + " · " + new Set(r.gids).size + " узлов" + (
        r.occurrences ? " · повторений: " + r.occurrences : ""), () => M.showAction({
        kind: "path",
        label: title + ": структура связей, не трассировка денег",
        gids: r.gids
      }), "text-action"));
      if (items.length > 5) s.append(element("p", "muted", title + ": показано 5 из " + items.length));
    }
    if (x.cycles_complete === false || x.repeated_routes_complete === false) s.append(element("p",
      "warning",
      "Поиск паттернов ограничен. Отсутствие найденного паттерна не означает его отсутствия в сети."));
  }

  function render(gid, fromChat = false) {
    const token = ++selectionId,
      n = state.nodes.get(gid);
    if (!n) {
      empty();
      return;
    }
    showTab(false);
    panel.replaceChildren();
    panel.scrollTop = 0;
    backToChat();
    const header = element("div", "node-header");
    header.append(element("span", "eyebrow", "КЛИЕНТ / GID"), element("h2", "", gid), badge(n.role));
    header.append(button("Копировать gid", async () => {
      try {
        await navigator.clipboard.writeText(gid);
        M.notice("Gid скопирован.");
      } catch {
        M.notice("Копирование недоступно: выделите gid в карточке.");
      }
    }, "text-action"));
    const meta = element("div", "node-meta");
    meta.append(element("span", "", "Колено " + metric(n.depth)));
    if (n.is_seed) meta.append(element("span", "", "◇ Seed-клиент"));
    if (n.cluster_id !== undefined && n.cluster_id !== null) meta.append(button("Кластер " + n.cluster_id +
      " ↗", () => M.setCluster(n.cluster_id)));
    header.append(meta);
    panel.append(header);
    const tools = section();
    tools.classList.add("card-actions");
    tools.append(button(state.compare === gid ? "Убрать из сравнения" : "Сравнить с другим клиентом",
  () => {
      state.compare = state.compare === gid ? null : gid;
      M.highlight();
      render(gid);
      M.notice(state.compare ? "Клиент A закреплён. Выберите второго клиента для сравнения." :
        "Сравнение очищено.");
    }), button("Спросить об этом клиенте", () => {
      contextCheck.checked = true;
      updateContext();
      showTab(true);
      input.focus();
    }));
    const scores = section(),
      grid = element("div", "node-scores");
    for (const [name, value] of [
        ["Приоритет проверки", n.priority_score],
        ["Оценка правила роли", n.role_score]
      ]) {
      const item = element("div");
      item.append(element("span", "", name), element("strong", "", value == null ? "—" : M.numeric(value)
        .toFixed(2)));
      grid.append(item);
    }
    scores.append(grid);
    const boundary = n.depth === 4 || (Array.isArray(n.flags) ? n.flags : []).some(f => [
      "truncated_by_depth", "terminal_unknown"
    ].includes(f));
    if (boundary) scores.append(element("p", "warning",
      "Граница наблюдения: отсутствие исходящих не доказывает, что деньги остались на счёте. Нужны переводы за пределами выборки."
      ));
    if (n.is_seed) scores.append(element("p", "warning",
      "Входящие seed видны не полностью. Отношение исходящих к входящим не является полным балансом."));
    const evidence = section("Основание роли");
    evidence.append(element("p", "evidence", n.evidence || "Обоснование пока не передано."));
    const incoming = state.model.incoming.get(gid) || [],
      outgoing = state.model.outgoing.get(gid) || [];
    const proof = element("div", "proof-actions");
    proof.append(button("← Плательщики: " + incoming.length, () => M.showConnections(gid, "in")), button(
      "Получатели: " + outgoing.length + " →", () => M.showConnections(gid, "out")));
    evidence.append(proof);
    for (const item of Array.isArray(n.evidence_items) ? n.evidence_items : [])
      if (G.evidence(state.model, item)) evidence.append(button(item.label || "Показать основание", () => M
        .showEvidence(item), "text-action"));
    const why = section("Почему этот приоритет");
    why.append(element("p", "", n.priority_why || "Разложение приоритета пока не передано пайплайном."));
    why.append(element("p", "muted", "Приоритет задаёт порядок проверки, а не вероятность нарушения."));
    if (Array.isArray(n.priority_components)) {
      const dl = element("dl", "metrics");
      for (const c of n.priority_components)
        if (c && Number.isFinite(c.contribution)) dl.append(element("dt", "", String(c.label || c.key)),
          element("dd", "", metric(c.contribution)));
      why.append(dl);
    }
    const stability = n.rank_stability;
    if (stability && Number.isFinite(stability.min_rank) && Number.isFinite(stability.max_rank)) why.append(
      element("p", "muted", "Ранг в проверенных сценариях: " + stability.min_rank + "–" + stability
        .max_rank + "; попадание в топ-" + stability.top_k + ": " + metric(stability.top_k_share,
        "share") + ". Это чувствительность методики."));
    const nf = Array.isArray(n.flags) ? n.flags : [];
    if (nf.length) {
      const s = section("Сигналы"),
        list = element("div", "flags");
      for (const f of nf) list.append(element("span", "flag", label(f, "flag")));
      s.append(list);
    }
    compare(gid);
    connections("Входящие связи", incoming, "source", gid);
    connections("Исходящие связи", outgoing, "target", gid);
    extras(n);
    const metrics = element("details", "connections");
    metrics.append(element("summary", "", "Все метрики потока"));
    const dl = element("dl", "metrics");
    for (const [key, value] of Object.entries(n.metrics || {})) dl.append(element("dt", "", label(key)),
      element("dd", "", metric(value, key)));
    metrics.append(dl);
    panel.append(metrics);
    const cluster = state.graph.clusters?.find(c => String(c.cluster_id) === String(n.cluster_id));
    if (cluster?.hypothesis) section("Гипотеза кластера").append(element("p", "cluster-summary", cluster
      .hypothesis));
    const ai = section(),
      result = element("div", "ai-response"),
      b = button("Составить AI-карточку", async () => {
        b.disabled = true;
        b.textContent = "Составляем карточку…";
        result.replaceChildren();
        const version = state.version;
        try {
          const card = await api("/api/node/" + encodeURIComponent(gid) + "/card?graph_version=" +
            encodeURIComponent(state.graph.meta.app_version || ""));
          if (token !== selectionId) return;
          if (version !== state.version) throw new Error(
            "Данные обновились. Запросите карточку заново.");
          result.append(document.createTextNode(card.text), element("span", "response-source", card
            .source === "llm" ? "AI выбрал следующий шаг · факты из графа" :
            "Шаблон по данным · без LLM"));
        } catch (e) {
          if (token === selectionId) result.textContent = e.message;
        } finally {
          b.disabled = false;
          b.textContent = "Обновить AI-карточку";
        }
      }, "ai-card-button");
    result.setAttribute("aria-live", "polite");
    ai.append(b, result);
  }

  function edgeCard(edge) {
    selectionId++;
    showTab(false);
    panel.replaceChildren();
    panel.scrollTop = 0;
    backToChat();
    const s = section("Наблюдаемая связь");
    s.append(element("p", "eyebrow", "ОТПРАВИТЕЛЬ → ПОЛУЧАТЕЛЬ"), button(edge.source, () => M.focus(edge
      .source), "gid-link"), element("p", "flow-arrow", "↓"), button(edge.target, () => M.focus(edge
      .target), "gid-link"));
    const dl = element("dl", "metrics");
    dl.append(element("dt", "", "Сумма"), element("dd", "", metric(edge.sum_kzt) + " ₸"), element("dt", "",
      "Число переводов"), element("dd", "", metric(edge.n_tx)));
    s.append(dl);
    s.append(button("Выделить эту связь", () => M.showAction({
      kind: "path",
      label: "Переводы отправитель → получатель",
      gids: [edge.source, edge.target]
    })), element("p", "muted",
      "Агрегат за период выборки. Связь не является доказательством нарушения."));
  }
  window.addEventListener("mirai:select", e => render(e.detail.gid, e.detail.fromChat));
  window.addEventListener("mirai:edge", e => edgeCard(e.detail.edge));
  window.addEventListener("mirai:clear", empty);
  window.addEventListener("mirai:loaded", () => {
    if (!state.selected) empty();
  });
  const messages = element("div", "chat-messages");
  messages.setAttribute("role", "log");
  messages.setAttribute("aria-live", "polite");
  const intro = element("div", "chat-intro");
  intro.append(element("span", "eyebrow", "ПОМОЩНИК АНАЛИТИКА"), element("h3", "", "Спросите о сети"),
    element("p", "",
      "Ответы опираются на граф. Каждый вопрос рассматривается отдельно; контекст выбранного клиента можно включить ниже."
      ));
  const suggestions = element("div", "suggestions");
  for (const text of ["Кого стоит проверить первым и почему?", "Какие узлы имеют признаки консолидации?",
      "Какие ограничения есть у этих данных?"
    ]) suggestions.append(button(text, () => {
    input.value = text;
    contextCheck.checked = false;
    input.focus();
  }));
  intro.append(suggestions);
  messages.append(intro);
  const context = element("label", "chat-context"),
    contextCheck = element("input"),
    contextText = element("span");
  contextCheck.type = "checkbox";
  contextCheck.checked = false;
  context.append(contextCheck, contextText);

  function updateContext() {
    context.hidden = !state.selected;
    contextText.textContent = "Контекст: клиент " + (state.selected || "");
  }
  window.addEventListener("mirai:context", updateContext);
  updateContext();
  const form = element("form", "chat-form"),
    input = element("textarea"),
    send = element("button", "", "↑");
  input.id = "question";
  input.placeholder = "Вопрос о клиентах или потоках…";
  input.maxLength = 3600;
  input.rows = 2;
  input.required = true;
  input.setAttribute("aria-label", "Вопрос ассистенту");
  send.type = "submit";
  send.setAttribute("aria-label", "Отправить вопрос");
  form.append(input, send);
  chat.append(messages, context, form, element("p", "chat-foot",
    "Enter — отправить · Shift+Enter — новая строка"));

  function bubble(kind, text) {
    hasChat = true;
    const message = element("div", "message " + kind);
    message.append(element("div", "message-label", kind === "user" ? "ВЫ" : "MIRAI · АССИСТЕНТ"));
    const body = element("div", "message-body", text);
    message.append(body);
    messages.append(message);
    messages.scrollTop = messages.scrollHeight;
    return {
      message,
      body
    };
  }
  let sending = false;
  async function ask(question, contextGid = null) {
    if (sending) return;
    sending = true;
    send.disabled = true;
    intro.hidden = true;
    const full = contextGid ? "Контекст выбранного клиента: gid " + contextGid + ".\nВопрос: " +
      question : question;
    bubble("user", question + (contextGid ? "\nКонтекст: " + contextGid : ""));
    const pending = bubble("assistant", "Читаем данные графа…"),
      version = state.version;
    try {
      const answer = await api("/api/ask", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          question: full,
          graph_version: state.graph?.meta?.app_version
        })
      });
      if (version !== state.version) throw new Error(
        "Граф обновился во время ответа. Повторите вопрос по новой версии.");
      pending.body.replaceChildren();
      const ids = new Set((answer.cited_gids || []).filter(id => typeof id === "string" && state.nodes
          .has(id))),
        used = new Set();
      String(answer.answer).split(/(\d+)/g).forEach(part => {
        if (ids.has(part)) {
          pending.body.append(button(part, () => M.focus(part, {
            fromChat: true
          }), "gid-link"));
          used.add(part);
        } else pending.body.append(document.createTextNode(part));
      });
      const citations = element("div", "citations");
      for (const id of ids)
        if (!used.has(id)) citations.append(button("Клиент " + id + " ↗", () => M.focus(id, {
          fromChat: true
        })));
      pending.message.append(citations);
      for (const action of Array.isArray(answer.actions) ? answer.actions : [])
        if (G.action(state.model, action)) pending.message.append(button(action.label ||
          "Показать на карте", () => M.showAction(action), "map-action"));
      pending.message.append(element("span", "response-source", answer.source === "llm" ?
        "AI выбрал запрос · ответ по данным" : "Локальный ответ по графу · без LLM"));
    } catch (error) {
      pending.message.classList.add("error");
      pending.body.textContent = error.message;
      pending.message.append(button("Повторить вопрос", () => ask(question, state.nodes.has(contextGid) ?
        contextGid : null)));
    } finally {
      sending = false;
      send.disabled = false;
      messages.scrollTop = messages.scrollHeight;
      input.focus();
    }
  }
  form.addEventListener("submit", e => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q || sending) return;
    const contextGid = contextCheck.checked && state.selected && !/\d{6,20}/.test(q) ? state.selected :
      null;
    input.value = "";
    ask(q, contextGid);
  });
  input.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
})();
