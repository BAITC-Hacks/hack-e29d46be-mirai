"use strict";
(() => {
  const M=window.Mirai;if(!M)return;window.MiraiPanels=true;
  const {$,element,api,badge,number,compact,state}=M;
  const host=$("details-panel");host.replaceChildren();
  const tabs=element("div","detail-tabs");tabs.setAttribute("role","tablist");
  const detailTab=element("button","","Клиент");detailTab.id="detail-tab";
  const chatTab=element("button","","✧ Ассистент");chatTab.id="chat-tab";
  const panel=element("div","detail-scroll");panel.id="node-panel";panel.setAttribute("role","tabpanel");panel.setAttribute("aria-labelledby","detail-tab");
  const chat=element("div","chat-panel");chat.id="chat-panel";chat.hidden=true;chat.setAttribute("role","tabpanel");chat.setAttribute("aria-labelledby","chat-tab");
  for(const [button,target] of [[detailTab,panel],[chatTab,chat]]){button.type="button";button.setAttribute("role","tab");button.setAttribute("aria-controls",target.id);button.addEventListener("click",()=>showTab(target===chat));tabs.append(button);}
  host.append(tabs,panel,chat);
  function showTab(isChat){panel.hidden=isChat;chat.hidden=!isChat;detailTab.setAttribute("aria-selected",String(!isChat));chatTab.setAttribute("aria-selected",String(isChat));}
  showTab(false);
  function empty(){panel.replaceChildren();const block=element("div","empty detail-empty");block.append(element("span","empty-symbol","◎"),element("h3","","Выберите клиента"),element("p","","Нажмите на узел или найдите gid. Здесь появятся потоки, метрики и обоснование роли."));panel.append(block);}
  empty();
  let selectionId=0;
  const labels={in_deg:"Плательщиков",out_deg:"Получателей",in_kzt:"Входящие, ₸",out_kzt:"Исходящие, ₸",in_tx:"Входящих переводов",out_tx:"Исходящих переводов",pagerank:"PageRank",pass_through:"Доля проходящего потока",n_seed_upstream:"Seed выше по потоку",betweenness:"Посредничество",fast_transit_share:"Доля быстрого транзита",sync_in_days:"Дней синхронных входящих",in_cycle:"Участие в цикле",likely_true_terminal:"Признаки конечного получателя",truncated_by_depth:"Обрыв по глубине"};
  const flagNames={fast_transit:"Быстрый транзит",in_cycle:"Участие в цикле",truncated_by_depth:"Обрыв на 4-м колене",synchronous_in:"Синхронные входящие",likely_true_terminal:"Признаки конечного получателя"};
  function formatted(value,key="") {if(value===null||value===undefined)return "—";if(typeof value==="boolean")return value?"Да":"Нет";if(typeof value==="number"){if(!Number.isFinite(value))return "—";if(["pagerank","betweenness"].includes(key))return value.toLocaleString("ru-RU",{maximumSignificantDigits:4});return number.format(value);}return typeof value==="object"?JSON.stringify(value):String(value);}
  function section(title){const block=element("section","node-section");if(title)block.append(element("h3","",title));panel.append(block);return block;}
  function connections(title,edges,direction){const block=element("details","connections");const summary=element("summary","",title);summary.append(element("span","",String(edges.length)));block.append(summary);const list=element("div","connection-list");if(!edges.length)list.append(element("p","empty","В выборке нет переводов."));edges.slice().sort((a,b)=>M.numeric(b.sum_kzt)-M.numeric(a.sum_kzt)).forEach(edge=>{const gid=edge[direction];const button=element("button","",`${direction==="source"?"←":"→"} ${gid}`);button.type="button";button.append(element("span","",`${formatted(edge.sum_kzt)} ₸ · ${formatted(edge.n_tx)} пер.`));button.addEventListener("click",()=>M.focus(gid));list.append(button);});block.append(list);panel.append(block);}
  async function render(gid){
    const token=++selectionId;showTab(false);panel.replaceChildren(element("p","empty","Загружаем карточку…"));
    try {const data=await api(`/api/node/${encodeURIComponent(gid)}`);if(token!==selectionId)return;
      const n=data.node;panel.replaceChildren();panel.scrollTop=0;
      const header=element("div","node-header");header.append(element("span","eyebrow","КЛИЕНТ / GID"),element("h2","",String(n.id)),badge(n.role));
      const meta=element("div","node-meta");meta.append(element("span","",`Колено ${formatted(n.depth)}`));if(n.is_seed)meta.append(element("span","","◇ Seed-клиент"));
      if(n.cluster_id!==undefined&&n.cluster_id!==null){const button=element("button","",`Кластер ${n.cluster_id} ↗`);button.addEventListener("click",()=>{$("cluster").value=String(n.cluster_id);$("cluster").dispatchEvent(new Event("change"));});meta.append(button);}header.append(meta);panel.append(header);
      const scores=section();const grid=element("div","node-scores");for(const [label,value] of [["Приоритет проверки",n.priority_score],["Оценка роли",n.role_score]]){const item=element("div");item.append(element("span","",label),element("strong","",value==null?"—":M.numeric(value).toFixed(2)));grid.append(item);}scores.append(grid);
      const evidence=section("Почему этот клиент");evidence.append(element("p","evidence",n.evidence||"Обоснование пока не передано пайплайном."));
      const flags=Array.isArray(n.flags)?n.flags:[];if(n.depth===4||flags.includes("truncated_by_depth")||n.metrics?.truncated_by_depth)evidence.append(element("p","warning","Связи на четвёртом колене могут быть обрезаны. Отсутствие исходящих не означает, что деньги осели."));
      if(n.is_seed)evidence.append(element("p","warning","У seed-клиента входящие занижены: переводы извне выборки не видны."));
      const metricSection=section("Метрики потока");const dl=element("dl","metrics");const metrics=n.metrics&&typeof n.metrics==="object"?Object.entries(n.metrics):[];
      if(!metrics.length)metricSection.append(element("p","muted","Метрики пока не переданы."));
      for(const [key,value] of metrics){dl.append(element("dt","",labels[key]||key),element("dd","",formatted(value,key)));}metricSection.append(dl);
      if(flags.length){const block=section("Сигналы");const list=element("div","flags");flags.forEach(flag=>list.append(element("span","flag",flagNames[flag]||flag)));block.append(list);}
      const cluster=state.graph?.clusters?.find(c=>String(c.cluster_id)===String(n.cluster_id));if(cluster?.hypothesis){const block=section("Гипотеза кластера");block.append(element("p","cluster-summary",cluster.hypothesis));}
      connections("Входящие связи",data.incoming||[],"source");connections("Исходящие связи",data.outgoing||[],"target");
      const ai=section();const button=element("button","ai-card-button","✧ Составить AI-карточку");button.type="button";const result=element("div","ai-response");result.setAttribute("aria-live","polite");ai.append(button,result);
      button.addEventListener("click",async()=>{button.disabled=true;button.textContent="Составляем карточку…";result.replaceChildren();try{const card=await api(`/api/node/${encodeURIComponent(gid)}/card`);if(token!==selectionId)return;result.append(document.createTextNode(card.text),element("span","response-source",card.source==="llm"?"AI · проверьте гипотезу по метрикам":"Шаблон по данным · без LLM"));}catch(error){if(token===selectionId)result.textContent=error.message;}finally{button.disabled=false;button.textContent="✧ Обновить AI-карточку";}});
    }catch(error){if(token===selectionId)panel.replaceChildren(element("p","empty",error.message));}
  }
  window.addEventListener("mirai:select",event=>render(event.detail.gid));
  window.addEventListener("mirai:clear",()=>{selectionId++;empty();});
  window.addEventListener("mirai:loaded",()=>{if(!state.selected){selectionId++;empty();}});
  const messages=element("div","chat-messages");messages.setAttribute("role","log");messages.setAttribute("aria-live","polite");
  const intro=element("div","chat-intro");intro.append(element("span","eyebrow","ПОМОЩНИК АНАЛИТИКА"),element("h3","","Задайте вопрос о сети"),element("p","","Ответы опираются на граф. Ссылки на клиентов открывают их связи и метрики."));
  const suggestions=element("div","suggestions");["Кого стоит проверить первым и почему?","Какие узлы имеют признаки консолидации?","Какие ограничения есть у этих данных?"].forEach(text=>{const button=element("button","",text);button.type="button";button.addEventListener("click",()=>{input.value=text;input.focus();});suggestions.append(button);});intro.append(suggestions);messages.append(intro);
  const form=element("form","chat-form");const input=element("textarea");input.id="question";input.placeholder="Спросите о клиентах или потоках…";input.maxLength=4000;input.rows=2;input.required=true;input.setAttribute("aria-label","Вопрос ассистенту");const send=element("button","","↑");send.type="submit";send.setAttribute("aria-label","Отправить вопрос");form.append(input,send);chat.append(messages,form,element("p","chat-foot","Enter — отправить · Shift+Enter — новая строка"));
  function bubble(kind,text){const message=element("div",`message ${kind}`);message.append(element("div","message-label",kind==="user"?"ВЫ":"MIRAI · АССИСТЕНТ"));const body=element("div","message-body",text);message.append(body);messages.append(message);messages.scrollTop=messages.scrollHeight;return {message,body};}
  let sending=false;
  form.addEventListener("submit",async event=>{event.preventDefault();const question=input.value.trim();if(!question||sending)return;sending=true;send.disabled=true;intro.hidden=true;bubble("user",question);input.value="";const pending=bubble("assistant","Изучаем граф…");
    try{const answer=await api("/api/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question})});pending.body.replaceChildren();
      const ids=new Set((answer.cited_gids||[]).map(String).filter(gid=>state.nodes.has(gid)));const used=new Set();
      String(answer.answer).split(/(\d+)/g).forEach(part=>{if(ids.has(part)){const link=element("button","gid-link",part);link.type="button";link.addEventListener("click",()=>M.focus(part));pending.body.append(link);used.add(part);}else pending.body.append(document.createTextNode(part));});
      const citations=element("div","citations");for(const id of ids)if(!used.has(id)){const link=element("button","",`Клиент ${id} ↗`);link.type="button";link.addEventListener("click",()=>M.focus(id));citations.append(link);}pending.message.append(citations,element("span","response-source",answer.source==="llm"?"AI · гипотеза по данным":"Ответ без LLM"));
    }catch(error){pending.message.classList.add("error");pending.body.textContent=error.message;}finally{sending=false;send.disabled=false;messages.scrollTop=messages.scrollHeight;input.focus();}
  });
  input.addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();form.requestSubmit();}});
})();
