/* Mirai graph workspace. No build step and no external runtime requests. */
"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const roles = {consolidator:"Консолидация", transit:"Транзит", distributor:"Распределение", terminal:"Конечный", coordinator:"Координация", peripheral:"Периферия"};
  const colors = {consolidator:"#e4572e",transit:"#f3a712",distributor:"#2a9d8f",terminal:"#457b9d",coordinator:"#9d4edd",peripheral:"#b0b0b0"};
  const number = new Intl.NumberFormat("ru-RU", {maximumFractionDigits:2});
  const compact = new Intl.NumberFormat("ru-RU", {notation:"compact",maximumFractionDigits:1});
  const state = {graph:null, nodes:new Map(), neighbors:new Map(), cy:null, selected:null, mode:"top", cluster:"", loadId:0};
  function element(tag, cls, text) { const el=document.createElement(tag); if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el; }
  const numeric = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
  const priority = (node) => Math.max(0,Math.min(1,numeric(node.priority_score)));
  function roleColor(role) { const color=state.graph?.meta?.role_colors?.[role] || colors[role];return /^#[0-9a-f]{6}$/i.test(color || "") ? color : colors.peripheral; }
  function badge(role) { const el=element("span","badge");const dot=element("i","role-dot");dot.style.backgroundColor=roleColor(role);el.append(dot,document.createTextNode(roles[role] || role || "Нет роли"));return el; }
  function notice(text="") {$("notice").textContent=text;$("notice").hidden=!text;}
  async function api(path, options={}) { const response=await fetch(path,options);let data;try{data=await response.json();}catch{throw new Error("Сервер вернул некорректный ответ.");}if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:"Не удалось выполнить запрос.");return data; }
  function graphState(text,loading=false) {const target=$("graph-state");target.replaceChildren();target.hidden=!text;if(loading)target.append(element("div","spinner"));if(text)target.append(element("p","",text));}
  function orderedNodes(){return [...state.nodes.values()].sort((a,b)=>priority(b)-priority(a)||String(a.id).localeCompare(String(b.id)));}
  function makeTop(rows) {
    const container=$("top-list");container.replaceChildren();$("top-count").textContent=rows.length;
    if(!rows.length){container.append(element("p","empty","Нет клиентов для анализа."));return;}
    rows.forEach((row,index)=>{
      const button=element("button","top-row");button.type="button";button.dataset.gid=String(row.gid);button.title=row.why || "Показать связи клиента";
      button.append(element("span","rank",String(row.rank || index+1).padStart(2,"0")));
      const label=element("span","node-label");label.append(element("strong","",String(row.gid)),badge(row.role));button.append(label);
      const score=element("span","priority-score",numeric(row.priority_score).toFixed(2));const track=element("div","score-track");const fill=element("div","score-fill");fill.style.width=`${priority(row)*100}%`;track.append(fill);score.append(track);button.append(score);
      button.addEventListener("click",()=>focus(row.gid));container.append(button);
    });
  }
  function visibleIds() {
    if(state.mode==="all")return new Set(state.nodes.keys());
    const seeds=state.mode==="ego"?[state.selected]:orderedNodes().slice(0,100).map(n=>String(n.id));
    if(state.selected && state.mode==="top")seeds.push(state.selected);
    const ids=new Set(seeds.filter(Boolean));for(const id of seeds)for(const neighbor of state.neighbors.get(id)||[])ids.add(neighbor);return ids;
  }
  function draw() {
    if(!state.cy || !state.graph)return;
    const ids=visibleIds();const nodes=state.graph.nodes.filter(n=>ids.has(String(n.id)));
    const edges=state.graph.edges.filter(e=>ids.has(String(e.source))&&ids.has(String(e.target)));
    let maxAmount=1;for(const e of state.graph.edges)maxAmount=Math.max(maxAmount,numeric(e.sum_kzt));
    const elements=nodes.map(n=>({group:"nodes",data:{id:String(n.id),label:String(n.id),color:roleColor(n.role),size:10+priority(n)*23,cluster:String(n.cluster_id ?? ""),seed:!!n.is_seed},position:{x:numeric(n.x),y:numeric(n.y)}}));
    edges.forEach((e,i)=>elements.push({group:"edges",data:{id:`edge-${i}`,source:String(e.source),target:String(e.target),width:0.6+2.6*Math.log1p(Math.max(0,numeric(e.sum_kzt)))/Math.log1p(maxAmount)}}));
    state.cy.batch(()=>{state.cy.elements().remove();state.cy.add(elements);});
    state.cy.layout({name:"preset",fit:false}).run();
    highlight();state.cy.resize();state.cy.fit(state.cy.elements(),45);
    $("visible-count").textContent=`${number.format(nodes.length)} клиентов · ${number.format(edges.length)} связей`;
    document.querySelectorAll("[data-mode]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.mode===state.mode)));
    graphState(nodes.length?"":"В этом режиме нет узлов.");
  }
  function highlight() {
    if(!state.cy)return;
    const cy=state.cy;cy.batch(()=>{
      cy.elements().removeClass("dim focused neighbor flow cluster");
      if(state.cluster!=="") {cy.elements().addClass("dim");const group=cy.nodes().filter(n=>n.data("cluster")===state.cluster);group.removeClass("dim").addClass("cluster");group.edgesWith(group).removeClass("dim");}
      if(state.selected){const node=cy.getElementById(state.selected);if(node.length){cy.elements().addClass("dim");node.closedNeighborhood().removeClass("dim");node.addClass("focused");node.neighborhood().nodes().addClass("neighbor");node.connectedEdges().addClass("flow");}}
    });
  }
  function focus(gid) {
    const id=String(gid);if(!state.nodes.has(id)){notice(`Клиент ${id} не найден в графе.`);return;}
    state.selected=id;state.cluster="";$("cluster").value="";notice();
    if(state.mode!=="all" || !state.cy.getElementById(id).length)draw();else highlight();
    const node=state.cy.getElementById(id);
    state.cy.fit(node.closedNeighborhood(),65);
    if(state.cy.zoom()>1.7){state.cy.zoom(1.7);state.cy.center(node);}
    document.querySelectorAll(".top-row").forEach(el=>{const selected=el.dataset.gid===id;el.classList.toggle("selected",selected);el.setAttribute("aria-pressed",String(selected));});
    const panel=$("node-panel");if(!window.MiraiPanels){panel.replaceChildren(element("h3","empty",`Клиент ${id}`),element("p","empty",state.nodes.get(id).evidence || "Обоснование пока не передано."));}
    window.dispatchEvent(new CustomEvent("mirai:select",{detail:{gid:id}}));
  }
  function initGraph() {
    if(typeof cytoscape!=="function")throw new Error("Библиотека графа не загрузилась. Проверьте app/static/vendor/.");
    if(state.cy)state.cy.destroy();
    state.cy=cytoscape({container:$("graph"),elements:[],layout:{name:"preset"},pixelRatio:1,minZoom:0.03,maxZoom:5,hideEdgesOnViewport:true,textureOnViewport:true,boxSelectionEnabled:false,
      style:[
        {selector:"node",style:{"background-color":"data(color)",width:"data(size)",height:"data(size)",label:"","border-width":1.5,"border-color":"#101925","overlay-opacity":0}},
        {selector:"node[?seed]",style:{shape:"diamond","border-width":2,"border-color":"#dce6f2"}},
        {selector:"edge",style:{width:"data(width)","line-color":"#536680","target-arrow-color":"#657e9b","target-arrow-shape":"triangle","curve-style":"bezier","control-point-step-size":20,"opacity":0.38,"arrow-scale":0.65}},
        {selector:".cluster",style:{"border-width":3,"border-color":"#dfe8ff"}},
        {selector:".dim",style:{opacity:0.13}},
        {selector:"node.neighbor",style:{label:"data(label)","font-size":9,"color":"#c7d2e3","text-background-color":"#0d1723","text-background-opacity":0.9,"text-background-padding":"3px","text-valign":"bottom","text-margin-y":5}},
        {selector:"node.focused",style:{label:"data(label)","font-size":13,"font-weight":600,"color":"#fff","text-background-color":"#182638","text-background-opacity":1,"text-background-padding":"5px","text-valign":"bottom","text-margin-y":9,"border-width":4,"border-color":"#eff5ff",opacity:1,"z-index":10}},
        {selector:"edge.flow",style:{opacity:0.85,"line-color":"#afc4e8","target-arrow-color":"#afc4e8","z-index":5}}
      ]});
    state.cy.on("tap","node",event=>focus(event.target.id()));
    state.cy.on("tap",event=>{if(event.target===state.cy){state.selected=null;highlight();document.querySelectorAll(".top-row").forEach(el=>{el.classList.remove("selected");el.setAttribute("aria-pressed","false");});window.dispatchEvent(new CustomEvent("mirai:clear"));}});
  }
  async function load() {
    const token=++state.loadId;$("reload").disabled=true;$("search").disabled=true;$("search-form").querySelector("button").disabled=true;closeSearch();graphState("Загружаем сеть…",true);notice();
    try {
      const [graph,top]=await Promise.all([api("/api/graph"),api("/api/top?n=100")]);if(token!==state.loadId)return;
      state.graph=graph;state.nodes=new Map(graph.nodes.map(n=>[String(n.id),n]));state.neighbors=new Map(graph.nodes.map(n=>[String(n.id),new Set()]));
      for(const edge of graph.edges){state.neighbors.get(String(edge.source))?.add(String(edge.target));state.neighbors.get(String(edge.target))?.add(String(edge.source));}
      if(state.selected&&!state.nodes.has(state.selected))state.selected=null;
      $("stat-nodes").textContent=number.format(graph.nodes.length);$("stat-edges").textContent=number.format(graph.edges.length);$("stat-volume").textContent=compact.format(numeric(graph.meta?.total_kzt));
      const date=new Date(graph.meta?.generated_at);$("generated").textContent=Number.isNaN(date.getTime())?"Граф загружен":`Обновлено ${date.toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"})}`;
      $("legend").replaceChildren(...Object.keys(roles).map(badge));
      const cluster=$("cluster");cluster.replaceChildren(new Option("Все кластеры",""));
      const clusterIds=[...new Set(graph.nodes.map(n=>n.cluster_id).filter(id=>id!==null&&id!==undefined))].sort((a,b)=>numeric(a)-numeric(b));
      clusterIds.forEach(id=>cluster.add(new Option(`Кластер ${id}`,String(id))));if(!clusterIds.some(id=>String(id)===state.cluster))state.cluster="";cluster.value=state.cluster;
      makeTop(top);initGraph();draw();
      window.dispatchEvent(new CustomEvent("mirai:loaded"));if(state.selected)focus(state.selected);
      if(graph.nodes.some(n=>!Number.isFinite(n.x)||!Number.isFinite(n.y)))notice("Для части узлов не переданы координаты. Пайплайн должен добавить x/y для корректной карты.");
    }catch(error){graphState(error.message);notice(error.message);$("top-list").replaceChildren(element("p","empty","Данные недоступны. Нажмите ↻, чтобы повторить."));}finally{if(token===state.loadId){$("reload").disabled=false;$("search").disabled=false;$("search-form").querySelector("button").disabled=false;}}
  }
  let searchId=0,searchTimer;
  function closeSearch(){searchId++;$("search-results").hidden=true;$("search").setAttribute("aria-expanded","false");}
  async function search(submit=false){
    const query=$("search").value.trim();const token=++searchId;const results=$("search-results");if(!query){closeSearch();return;}
    try{const matches=await api(`/api/search?q=${encodeURIComponent(query)}`);if(token!==searchId)return;
      const exact=matches.find(n=>String(n.id)===query);
      if(submit&&(exact||matches.length===1)){focus((exact||matches[0]).id);closeSearch();return;}
      results.replaceChildren();if(!matches.length)results.append(element("p","","Клиент не найден. Проверьте gid."));
      else matches.forEach(n=>{const button=element("button","",String(n.id));button.type="button";button.append(badge(n.role));button.addEventListener("click",()=>{$("search").value=n.id;focus(n.id);closeSearch();});results.append(button);});
      results.hidden=false;$("search").setAttribute("aria-expanded","true");if(submit&&matches.length>1)results.querySelector("button")?.focus();
    }catch(error){if(token===searchId){results.replaceChildren(element("p","",error.message));results.hidden=false;}}
  }
  $("search-form").addEventListener("submit",e=>{e.preventDefault();clearTimeout(searchTimer);search(true);});
  $("search").addEventListener("input",()=>{searchId++;clearTimeout(searchTimer);searchTimer=setTimeout(()=>search(),180);});
  $("search-form").addEventListener("keydown",e=>{if(e.key==="Escape")closeSearch();if(e.key==="ArrowDown"||e.key==="ArrowUp"){const choices=[...$("search-results").querySelectorAll("button")];if(choices.length){e.preventDefault();const current=choices.indexOf(document.activeElement);choices[(current+(e.key==="ArrowDown"?1:-1)+choices.length)%choices.length].focus();}}});
  document.addEventListener("click",e=>{if(!$("search-form").contains(e.target))closeSearch();});
  document.querySelectorAll("[data-mode]").forEach(button=>button.addEventListener("click",()=>{if(!state.graph)return;if(button.dataset.mode==="ego"&&!state.selected){notice("Сначала выберите клиента для эго-сети.");return;}notice();state.mode=button.dataset.mode;draw();}));
  $("cluster").addEventListener("change",()=>{state.cluster=$("cluster").value;state.selected=null;if(state.mode==="ego")state.mode="top";draw();document.querySelectorAll(".top-row").forEach(el=>{el.classList.remove("selected");el.setAttribute("aria-pressed","false");});window.dispatchEvent(new CustomEvent("mirai:clear"));});
  $("reload").addEventListener("click",load);$("fit").addEventListener("click",()=>{if(state.cy)state.cy.fit(state.cy.elements(),45);});
  for(const [id,multiplier] of [["zoom-in",1.35],["zoom-out",1/1.35]])$(id).addEventListener("click",()=>{if(state.cy)state.cy.zoom({level:state.cy.zoom()*multiplier,renderedPosition:{x:state.cy.width()/2,y:state.cy.height()/2}});});
  window.Mirai={state,$,api,element,badge,roles,number,compact,focus,notice,numeric};
  load();
})();
