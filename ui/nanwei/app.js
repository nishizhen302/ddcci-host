// DDCCI 控制台前端 —— 南微协议固定控件, 视觉复用 ddcci 控制台样式。
// 值表/操作码由后端 protocol_meta() 下发, 单一数据源在 nanwei_core.py。
// 建链流程: connect(地址) -> 枚举显示器进下拉框 -> select_monitor -> 渲染控件。

const $ = (s) => document.querySelector(s);

const I = {
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/>',
  contrast: '<circle cx="12" cy="12" r="9"/><path d="M12 3v18a9 9 0 0 0 0-18z" fill="currentColor" stroke="none"/>',
  thermo: '<path d="M14 14.76V5a2 2 0 0 0-4 0v9.76a4 4 0 1 0 4 0z"/>',
  gamma: '<path d="M3 20c4-12 14-12 18 0"/>',
  usb: '<path d="M12 2v14M12 22a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM12 6l3-3M12 9l-4-2"/><circle cx="17" cy="5" r="1.6"/><rect x="6.8" y="6" width="2.6" height="2.6"/>',
  chipv: '<rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 1v4M15 1v4M9 19v4M15 19v4M1 9h4M1 15h4M19 9h4M19 15h4"/>',
};
const icon = (inner, cls) => `<svg class="i ${cls || ""}" viewBox="0 0 24 24">${inner}</svg>`;

let META = null;      // protocol_meta() 结果
let MONITORS = [];    // connect() 枚举结果
let CURID = null;     // 当前选中显示器 id

function setConn(text, state) {
  $("#conn").textContent = text;
  $("#pulse").dataset.state = state || "idle";
}

// ---- 地址选择 (0x5E 南微文档值 / 0x6E 样机实测值), 记住上次选择 ----
function savedAddr() {
  try { return localStorage.getItem("ddcci-slave") || "0x5E"; } catch (e) { return "0x5E"; }
}
function saveAddr(a) {
  try { localStorage.setItem("ddcci-slave", a); } catch (e) {}
}
function paintAddrSeg(addr) {
  document.querySelectorAll("#addr-seg span").forEach((s) => {
    s.classList.toggle("on", s.dataset.addr.toUpperCase() === String(addr).toUpperCase());
  });
}

// ---- 命令日志 (新的在上, 只留 80 条) ----
function log(label, tx, ok, extra) {
  const box = $("#log");
  const row = document.createElement("div");
  row.className = "log-row";
  const t = new Date().toTimeString().slice(0, 8);
  row.innerHTML =
    `<span class="t tn">${t}</span>` +
    `<span class="${ok ? "r-ok" : "r-err"}">${label}${extra ? " " + extra : ""}</span>` +
    `<span class="frame">${tx || ""}</span>`;
  box.prepend(row);
  while (box.children.length > 80) box.removeChild(box.lastChild);
}

const api = {
  get: async (op, label) => {
    const r = await window.pywebview.api.get_param(op);
    log(`读${label}`, r.tx, r.ok, r.ok ? `→ ${r.current}/${r.maximum}` : `✕ ${r.error || ""}`);
    return r;
  },
  set: async (op, v, label) => {
    const r = await window.pywebview.api.set_param(op, v);
    log(`写${label}=${v}`, r.tx, r.ok, r.ok ? "" : `✕ ${r.error || ""}`);
    return r;
  },
};

// =================== 控件 (骨架同 ddcci 控制台) ===================

function grpShell(name, iconInner) {
  const grp = document.createElement("div");
  grp.className = "grp";
  const head = document.createElement("div");
  head.className = "ghead";
  head.innerHTML = `${icon(iconInner, "gi")}<span class="lbl">${name}</span>`;
  const badge = document.createElement("span");
  badge.className = "badge";
  const val = document.createElement("span");
  val.className = "val";
  head.append(badge, val);
  grp.appendChild(head);
  grp._badge = badge; grp._val = val;
  return grp;
}
function unresponsive(grp) { grp.dataset.unresponsive = "1"; grp._badge.textContent = "未响应"; }

// 亮度/对比度: −/数字/+ 加滑块。USB 链路每条命令有 settle, 拖动节流放宽到 180ms。
async function buildSlider(op, name, iconInner) {
  const grp = grpShell(name, iconInner);
  const init = await api.get(op, name);

  const minus = document.createElement("button"); minus.textContent = "−";
  const plus = document.createElement("button"); plus.textContent = "+";
  const pmL = document.createElement("div"); pmL.className = "pm"; pmL.appendChild(minus);
  const pmR = document.createElement("div"); pmR.className = "pm"; pmR.appendChild(plus);
  const num = document.createElement("input");
  num.type = "number"; num.className = "num tn";
  grp._val.append(pmL, num, pmR);

  if (!init.ok) {
    unresponsive(grp);
    num.value = ""; num.disabled = minus.disabled = plus.disabled = true;
    const note = document.createElement("div"); note.className = "empty"; note.textContent = "读不到当前值/范围";
    grp.appendChild(note);
    return grp;
  }
  const max = init.maximum || 100;
  num.min = 0; num.max = max;

  const sld = document.createElement("div"); sld.className = "sld";
  const fill = document.createElement("div"); fill.className = "f";
  const knob = document.createElement("div"); knob.className = "k";
  sld.append(fill, knob);
  grp.appendChild(sld);

  function paint(v) {
    const pct = max ? (v / max) * 100 : 0;
    fill.style.width = pct + "%"; knob.style.left = pct + "%"; num.value = v;
  }
  async function apply(v) {
    v = Math.max(0, Math.min(max, Math.round(v)));
    paint(v);
    const r = await api.set(op, v, name);
    if (!r.ok) { setConn(`${name} 设置失败: ${r.error}`, "warn"); return; }
    const rb = await api.get(op, name);
    if (rb.ok) paint(rb.current);
    setConn("已连接", "ok");
  }
  paint(init.current);

  num.addEventListener("change", () => apply(Number(num.value)));
  minus.addEventListener("click", () => apply(Number(num.value) - 1));
  plus.addEventListener("click", () => apply(Number(num.value) + 1));

  let dragging = false, lastSent = 0;
  const ratioToV = (clientX) => {
    const r = sld.getBoundingClientRect();
    return Math.round(Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * max);
  };
  function liveSet(v) {
    paint(v);
    const now = Date.now();
    if (now - lastSent >= 180) { lastSent = now; api.set(op, v, name); }
  }
  sld.addEventListener("pointerdown", (e) => {
    dragging = true; sld.setPointerCapture(e.pointerId); liveSet(ratioToV(e.clientX));
  });
  sld.addEventListener("pointermove", (e) => { if (dragging) liveSet(ratioToV(e.clientX)); });
  sld.addEventListener("pointerup", (e) => {
    if (!dragging) return; dragging = false; apply(ratioToV(e.clientX));
  });
  return grp;
}

// 色温 / Gamma: 离散分段按钮, 写后回读确认
async function buildSeg(op, name, iconInner, options, extraCls) {
  const grp = grpShell(name, iconInner);
  const seg = document.createElement("div");
  seg.className = "seg" + (extraCls ? " " + extraCls : "");
  const spans = new Map();
  options.forEach((o) => {
    const s = document.createElement("span");
    s.textContent = o.label;
    s.addEventListener("click", async () => {
      setSel(o.value);
      const r = await api.set(op, o.value, name);
      if (!r.ok) { setConn(`${name} 设置失败: ${r.error}`, "warn"); return; }
      const rb = await api.get(op, name);
      setSel(rb.ok ? rb.current : o.value);
      setConn("已连接", "ok");
    });
    spans.set(o.value, s); seg.appendChild(s);
  });
  grp.appendChild(seg);

  function setSel(v) {
    spans.forEach((s, val) => s.classList.toggle("on", val === v));
    const o = options.find((x) => x.value === v);
    grp._val.innerHTML = `<span class="vtxt tn">${o ? o.label : "0x" + Number(v).toString(16).toUpperCase()}</span>`;
  }

  const cur = await api.get(op, name);
  if (cur.ok) setSel(cur.current);
  else unresponsive(grp);
  return grp;
}

// 模拟按键 (协议 0xC0 帧): menu/right/left/exit
const OSD_KEYS = [
  { name: "menu",  label: "MENU", sub: "进入·确认", cls: "k-menu" },
  { name: "left",  label: "◀",    sub: "左 / −",    cls: "k-left" },
  { name: "right", label: "▶",    sub: "右 / +",    cls: "k-right" },
  { name: "exit",  label: "EXIT", sub: "退出",      cls: "k-exit" },
];

function buildOsdKeys() {
  const wrap = $("#osdkeys");
  wrap.innerHTML = "";
  const div = document.createElement("div");
  div.className = "divtxt"; div.textContent = "模拟按键";
  wrap.appendChild(div);

  const pad = document.createElement("div");
  pad.className = "dpad";
  OSD_KEYS.forEach((key) => {
    const b = document.createElement("button");
    b.className = "dkey " + key.cls;
    b.innerHTML = `<span class="kl">${key.label}</span><span class="ks">${key.sub}</span>`;
    b.addEventListener("click", async () => {
      b.classList.add("press");
      setTimeout(() => b.classList.remove("press"), 170);
      const r = await window.pywebview.api.press_key(key.name);
      log(`按键 ${key.label}`, r.tx, r.ok, r.ok ? "" : `✕ ${r.error || ""}`);
      setConn(r.ok ? "已连接" : `按键失败: ${r.error || ""}`, r.ok ? "ok" : "warn");
    });
    pad.appendChild(b);
  });
  wrap.appendChild(pad);
}

// =================== 建链 + 渲染 ===================

function chip(html, cls, id) {
  const c = document.createElement("span");
  c.className = "chip" + (cls ? " " + cls : "");
  if (id) c.id = id;
  c.innerHTML = html;
  return c;
}

function renderMonitorOptions(monitors, keepId) {
  const sel = $("#monitor-select");
  sel.innerHTML = "";
  monitors.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = String(m.id);
    opt.textContent = `[${m.id}] ${m.description}`;
    sel.appendChild(opt);
  });
  if (keepId != null && monitors.some((m) => m.id === keepId)) sel.value = String(keepId);
}

// 选中一台显示器: 读版本 + 渲染控件
async function pickMonitor(id) {
  CURID = id;
  const m = MONITORS.find((x) => x.id === id) || MONITORS[0];
  $("#sel-name").textContent = m ? m.description : "—";
  $("#sel-id").textContent = m ? `[${m.id}]` : "";

  const r = await window.pywebview.api.select_monitor(id);
  const verChip = $("#chip-ver");
  if (verChip) {
    const v = (r.ok && r.versions) || {};
    const vtxt = (x) => (x == null ? "—" : x);
    verChip.innerHTML = `${icon(I.chipv, "sm")}硬件 v${vtxt(v.hw)} · 软件 v${vtxt(v.sw)}`;
  }
  if (!r.ok) { setConn(`选中失败: ${r.error || ""}`, "warn"); return; }

  const cont = $("#controls"); cont.innerHTML = "";
  const div = document.createElement("div"); div.className = "divtxt"; div.textContent = "图像";
  cont.appendChild(div);
  cont.appendChild(await buildSlider(META.ops.brightness, "亮度", I.sun));
  cont.appendChild(await buildSlider(META.ops.contrast, "对比度", I.contrast));
  cont.appendChild(await buildSeg(META.ops.colortemp, "色温", I.thermo, META.colortemp, "tempseg"));
  cont.appendChild(await buildSeg(META.ops.gamma, "Gamma", I.gamma, META.gamma));

  buildOsdKeys();
  setConn("已连接", "ok");
}

let refreshing = false;
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  const btn = $("#win-refresh");
  btn.classList.add("spin");
  const prevId = CURID;
  try {
    setConn("建链中…", "idle");
    $("#chips").innerHTML = ""; $("#controls").innerHTML = ""; $("#osdkeys").innerHTML = "";
    $("#sel-name").textContent = "—"; $("#sel-id").textContent = "";
    paintAddrSeg(savedAddr());

    const st = await window.pywebview.api.connect(savedAddr());
    if (!st.ok) {
      setConn(`建链失败 (${st.backend || ""})`, "warn");
      const p = document.createElement("p"); p.className = "empty";
      p.textContent = `${st.error || ""}${st.hint ? " — " + st.hint : ""}`;
      $("#controls").appendChild(p);
      MONITORS = []; CURID = null;
      renderMonitorOptions([], null);
      return;
    }
    if (!META) META = await window.pywebview.api.protocol_meta();
    MONITORS = st.monitors || [];
    paintAddrSeg(st.address);

    const chips = $("#chips");
    chips.appendChild(chip(`${icon(I.usb, "sm")}${st.backend} · ${st.address}`, "tn"));
    chips.appendChild(chip(`${icon(I.chipv, "sm")}硬件 v— · 软件 v—`, "tn", "chip-ver"));

    renderMonitorOptions(MONITORS, prevId);
    const pick = Number($("#monitor-select").value || (MONITORS[0] && MONITORS[0].id) || 0);
    await pickMonitor(pick);
  } finally {
    refreshing = false;
    btn.classList.remove("spin");
  }
}

// ---- 换肤 ----
function applyTheme(t) {
  document.body.setAttribute("data-theme", t === "light" ? "light" : "dark");
  try { localStorage.setItem("nanwei-theme", t); } catch (e) {}
}
function initTheme() {
  let t = "dark";
  try { t = localStorage.getItem("nanwei-theme") || "dark"; } catch (e) {}
  applyTheme(t);
}

initTheme();
window.addEventListener("pywebviewready", () => {
  initTheme();
  const toggle = () => applyTheme(document.body.getAttribute("data-theme") === "dark" ? "light" : "dark");
  const skin = $("#skin");
  skin.addEventListener("click", toggle);
  skin.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
  $("#win-min").addEventListener("click", () => window.pywebview.api.minimize_window());
  $("#win-close").addEventListener("click", () => window.pywebview.api.close_window());
  $("#win-refresh").addEventListener("click", () => refresh());
  document.querySelectorAll(".resz").forEach((el) => {
    el.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      window.pywebview?.api?.start_resize(Number(el.dataset.ht));
    });
  });
  // 显示器下拉框
  $("#monitor-select").addEventListener("change", async (e) => {
    const m = MONITORS.find((x) => x.id === Number(e.target.value));
    if (m) await pickMonitor(m.id);
  });
  // IIC 地址切换: 存下来并整体重连
  document.querySelectorAll("#addr-seg span").forEach((s) => {
    s.addEventListener("click", async () => {
      if (s.classList.contains("on")) return;
      saveAddr(s.dataset.addr);
      paintAddrSeg(s.dataset.addr);
      await refresh();
    });
  });
  refresh();
});
