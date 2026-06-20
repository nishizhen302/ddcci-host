// 管脚配置器前端: 分组列表 + 详情(切复用/GPIO电平/还原默认), DDC 操作走串行锁。
const el = (id) => document.getElementById(id);
const api = () => window.pywebview.api;

let MON = null;
let DOMAINS = [];
let PIN_BY_BALL = {};
let SELECTED = null;

const DOMAIN_LABEL = {
  GPIO:"数字 GPIO", I2C_DDC:"I²C / DDC", AUX_DP:"AUX / DP",
  LVDS_DISP:"显示 / LVDS", PWM_BL:"PWM / 背光", FLASH_SPI:"Flash / SPI",
  POWER_CTRL:"电源 / 控制", TEST_DBG:"Test / 调试", OTHER:"其他",
};
const KIND_LABEL = {
  gpio_in:"输入", gpio_out_pp:"输出(推挽)", gpio_out_od:"输出(开漏)",
  i2c:"I²C", periph:"外设", reserved:"保留",
};
const GPIO_OUT_KINDS = ["gpio_out_pp","gpio_out_od"];

let _busy=false; const _q=[];
function lock(fn){ return new Promise((res,rej)=>{ _q.push({fn,res,rej}); pump(); }); }
async function pump(){
  if(_busy) return; const job=_q.shift(); if(!job) return;
  _busy=true;
  try{ job.res(await job.fn()); }catch(e){ job.rej(e); }
  finally{ _busy=false; pump(); }
}

function setConn(state){
  const d=el("conn-dot"); d.className="dot"+(state?(" "+state):"");
}

async function pickBoard(){
  const r=await api().list_monitors();
  const sel=el("mon"); sel.innerHTML="";
  if(!r.ok){ setConn("err"); return; }
  r.monitors.forEach(m=>{
    const o=document.createElement("option");
    o.value=m.id; o.textContent=`[${m.id}] ${m.model||m.description||""}`;
    sel.appendChild(o);
  });
  MON = (r.default!=null)? r.default : (r.monitors[0]&&r.monitors[0].id);
  sel.value=MON;
  setConn(MON!=null?"on":"err");
}

async function loadPins(){
  const r=await api().pin_db();
  if(!r.ok){ el("list").innerHTML="<p class='note' style='padding:12px'>读管脚表失败</p>"; return; }
  DOMAINS=r.domains; PIN_BY_BALL={};
  DOMAINS.forEach(g=>g.pins.forEach(p=>{ PIN_BY_BALL[p.ball]=p; }));
  renderList("");
}
function muxSummary(p){
  const f=p.funcs.find(x=>x.val===p.default);
  return f? (f.name+(f.kind&&KIND_LABEL[f.kind]?" · "+KIND_LABEL[f.kind]:"")) : "—";
}
function renderList(filter){
  const f=(filter||"").toLowerCase();
  const list=el("list"); list.innerHTML="";
  DOMAINS.forEach(g=>{
    const pins=g.pins.filter(p=> !f || p.ball.toLowerCase().includes(f)
      || p.funcs.some(x=>(x.name||"").toLowerCase().includes(f)));
    if(!pins.length) return;
    const grp=document.createElement("div");
    grp.className="grp";
    grp.innerHTML=`<span>${DOMAIN_LABEL[g.domain]||g.domain}</span><span class="ct">${pins.length}</span>`;
    const rows=document.createElement("div"); rows.className="rows";
    pins.forEach(p=>{
      const row=document.createElement("div");
      row.className="row"+(p.danger?" danger":"")+(p.ball===SELECTED?" on":"");
      row.innerHTML=`<span class="ball">${p.ball}</span><span class="fn">${muxSummary(p)}</span>`;
      row.onclick=()=>selectPin(p.ball);
      rows.appendChild(row);
    });
    grp.onclick=()=>grp.classList.toggle("collapsed");
    list.appendChild(grp); list.appendChild(rows);
  });
}

async function selectPin(ball){
  SELECTED=ball; renderList(el("search").value);
  const p=PIN_BY_BALL[ball];
  const r=await lock(()=>api().pin_read(ball, MON));
  renderDetail(p, r&&r.ok? r : null);
}
function renderDetail(p, state){
  const d=el("detail");
  const curVal = state? state.mux.val : p.default;
  const curKind = state? state.mux.kind : (p.funcs.find(f=>f.val===p.default)||{}).kind;
  const opts=p.funcs.map(f=>{
    const dis=f.kind==="reserved"?" disabled":"";
    const sel=f.val===curVal?" selected":"";
    return `<option value="${f.val}"${sel}${dis}>${f.val}: ${f.name} (${KIND_LABEL[f.kind]||f.kind})</option>`;
  }).join("");
  const isOut = GPIO_OUT_KINDS.includes(curKind);
  const isIn = curKind==="gpio_in";
  const hasGpio = !!p.gpio;
  const level = state? state.level : null;
  const swCls = "sw"+(level?" on":"")+((!isOut||!hasGpio)?" disabled":"");
  let gpioRow="";
  if(hasGpio && (isOut||isIn)){
    gpioRow = isOut
      ? `<div class="ctl"><label>输出电平</label><div id="sw" class="${swCls}"></div></div>`
      : `<div class="ctl"><label>读回电平</label><span>${level==null?"—":level}</span></div>`;
  } else if(!hasGpio){
    gpioRow = `<div class="note">此脚无 GPIO 数据寄存器映射, 电平不可控。</div>`;
  }
  d.innerHTML = `
    <h4>${p.ball}</h4>
    <div class="sub">复用寄存器 P${p.share.page.toString(16).toUpperCase()}_${p.share.offset.toString(16).toUpperCase().padStart(2,"0")}[${maskBits(p.share)}]</div>
    <div class="chip${p.danger?" danger":""}">${p.danger?("🔴 "+(p.danger_reason||"危险脚")):("当前: "+(state?state.mux.name:"—")+(curKind?" ("+(KIND_LABEL[curKind]||curKind)+")":""))}</div>
    <div class="ctl"><label>复用功能</label><select id="mux">${opts}</select></div>
    ${gpioRow}
    <div class="btns">
      <button id="reset" class="btn">还原默认 (${p.default})</button>
      <button id="apply" class="btn p">应用</button>
    </div>
    ${state?"":"<div class='note'>未读到当前值(板可能不在线), 显示默认值。</div>"}`;
  el("apply").onclick=()=>applyMux(p);
  el("reset").onclick=()=>resetPin(p);
  if(el("sw") && isOut && hasGpio) el("sw").onclick=()=>toggleLevel(p);
}
function maskBits(s){
  let hi=s.shift, m=s.mask>>s.shift, w=0; while(m){m>>=1;w++;} hi=s.shift+w-1;
  return w<=1? String(s.shift) : `${hi}:${s.shift}`;
}

async function applyMux(p){
  const val=parseInt(el("mux").value,10);
  if(p.danger && !confirm(`${p.ball} 是危险脚\n${p.danger_reason}\n\n继续可能黑屏或断开本控制链路(需重新上电)。确定要改吗?`)) return;
  el("apply").disabled=true;
  const r=await lock(()=>api().pin_set_mux(p.ball, val, MON));
  el("apply").disabled=false;
  if(!r||!r.ok){ alert((r&&r.error)||"写失败"); return; }
  selectPin(p.ball);
}
async function resetPin(p){
  if(p.danger && !confirm(`${p.ball} 还原默认值 ${p.default}, 继续?`)) return;
  const r=await lock(()=>api().pin_reset_default(p.ball, MON));
  if(!r||!r.ok){ alert((r&&r.error)||"还原失败"); return; }
  selectPin(p.ball);
}
async function toggleLevel(p){
  const sw=el("sw"); const next=sw.classList.contains("on")?0:1;
  const r=await lock(()=>api().gpio_set(p.ball, next, MON));
  if(!r||!r.ok){ alert((r&&r.error)||"置电平失败"); return; }
  selectPin(p.ball);
}

function wireWindowChrome(){
  el("win-min").onclick=()=>api().minimize_window();
  el("win-close").onclick=()=>api().close_window();
  const HT={n:12,s:15,e:11,w:10,ne:14,nw:13,se:17,sw:16};
  document.querySelectorAll(".resz").forEach(h=>{
    const k=[...h.classList].find(c=>c in HT);
    h.addEventListener("pointerdown",e=>{ e.preventDefault(); api().start_resize(HT[k]); });
  });
}

async function boot(){
  wireWindowChrome();
  el("search").addEventListener("input", e=>renderList(e.target.value));
  el("mon").addEventListener("change", e=>{ MON=parseInt(e.target.value,10);
    if(SELECTED) selectPin(SELECTED); });
  el("refresh").onclick=async()=>{
    const b=el("refresh"); b.classList.add("spin");
    try{ await pickBoard(); await loadPins(); if(SELECTED) await selectPin(SELECTED); }
    finally{ b.classList.remove("spin"); }
  };
  await pickBoard();
  await loadPins();
}
window.addEventListener("pywebviewready", boot);
