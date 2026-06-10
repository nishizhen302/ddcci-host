// DDC/CI 控制台前端 —— 复刻定稿样机 panel-v3-final 的视觉与交互，
// 骨架沿用阶段 1-3: caps 驱动控件、pywebview 桥、即时回读确认。

const $ = (s) => document.querySelector(s);
const hex2 = (n) => "0x" + Number(n).toString(16).toUpperCase().padStart(2, "0");

// ---- 24px 线性图标 (inner svg) ----
const I = {
  signal: '<path d="M3 8l9 6 9-6"/><rect x="3" y="5" width="18" height="14" rx="2"/>',
  gamma: '<path d="M3 20c4-12 14-12 18 0"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/>',
  contrast: '<circle cx="12" cy="12" r="9"/><path d="M12 3v18a9 9 0 0 0 0-18z" fill="currentColor" stroke="none"/>',
  thermo: '<path d="M14 14.76V5a2 2 0 0 0-4 0v9.76a4 4 0 1 0 4 0z"/>',
};
const icon = (inner, cls) => `<svg class="i ${cls || ""}" viewBox="0 0 24 24">${inner}</svg>`;

// ---- VCP -> 控件提示 (caps 决定哪些真正出现) ----
const CONTROL_HINTS = {
  0x72: { name: "Gamma", type: "gamma", icon: I.gamma,
          options: [{ label: "OFF", v: 0 }, { label: "1.8", v: 1 }, { label: "2.0", v: 2 },
                    { label: "2.2", v: 3 }, { label: "2.4", v: 4 }] },
  0x10: { name: "亮度",   type: "slider", icon: I.sun },
  0x12: { name: "对比度", type: "slider", icon: I.contrast },
  0x14: { name: "色温",   type: "temp",   icon: I.thermo },
};
const SIGNAL_VCP = 0x60;
const MAIN_ORDER = [0x72, 0x10, 0x12, 0x14];

const GAMMA_EXP = { 0: 1.0, 1: 1.8, 2: 2.0, 3: 2.2, 4: 2.4 };
const VCP14_LABELS = { 1: "sRGB", 2: "原生", 3: "4000K", 4: "5000K", 5: "6500K", 6: "7500K",
                       7: "8200K", 8: "9300K", 9: "10000K", 10: "11500K", 11: "User1", 12: "User2" };
const VCP60_LABELS = { 1: "VGA-1", 3: "DVI-1", 4: "DVI-2", 15: "DP-1", 16: "DP-2", 17: "HDMI-1", 18: "HDMI-2" };
const labelFor = (t, v) => t[v] || hex2(v);

let MONITORS = [];
let CUR = null;

const api = {
  get: (code) => window.pywebview.api.get_vcp(code, CUR.id),
  set: (code, v) => window.pywebview.api.set_vcp(code, v, CUR.id),
};

function setConn(text, state) {
  $("#conn").textContent = text;
  $("#pulse").dataset.state = state || "idle";
}

// =================== 控件构建 ===================

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
  grp._head = head; grp._badge = badge; grp._val = val;
  return grp;
}
function unresponsive(grp) { grp.dataset.unresponsive = "1"; grp._badge.textContent = "未响应"; }

// γ 曲线采样点 -> path
function gammaPts(g, W, H, p) {
  const N = 44, pts = [];
  for (let i = 0; i <= N; i++) {
    const x = i / N, y = Math.pow(x, g);
    pts.push([p + x * (W - 2 * p), (H - p) - y * (H - 2 * p)]);
  }
  return pts;
}
const ptsToLine = (pts) => pts.map((q, i) => (i ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1)).join(" ");

// Gamma: 横排分段 + 下方满宽实时曲线 (含淡色填充)
async function buildGamma(code, hint, allowed) {
  const grp = grpShell(hint.name, hint.icon);
  const opts = allowed && allowed.length
    ? hint.options.filter((o) => allowed.includes(o.v)) : hint.options;

  const seg = document.createElement("div");
  seg.className = "seg";
  const spans = new Map();
  opts.forEach((o) => {
    const s = document.createElement("span");
    s.textContent = o.label;
    s.addEventListener("click", async () => {
      highlight(o.v); // 立即响应观感
      const r = await api.set(code, o.v);
      if (!r.ok) { setConn(`Gamma 设置失败: ${r.error}`, "warn"); return; }
      const rb = await api.get(code);
      highlight(rb.ok ? rb.current : o.v);
      setConn(`${CUR.model || CUR.description} · 已连接`, "ok");
    });
    spans.set(o.v, s); seg.appendChild(s);
  });
  grp.appendChild(seg);

  const W = 300, H = 82, p = 11;
  const box = document.createElement("div");
  box.className = "curve";
  box.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">` +
    `<line class="grid" x1="${p}" y1="${H - p}" x2="${W - p}" y2="${H - p}"/>` +
    `<line class="grid" x1="${p}" y1="${p}" x2="${p}" y2="${H - p}"/>` +
    `<line class="diag" x1="${p}" y1="${H - p}" x2="${W - p}" y2="${p}"/>` +
    `<path class="area" d=""/><path class="plot" d=""/></svg>` +
    `<span class="tag tn"></span>`;
  const area = box.querySelector(".area"), plot = box.querySelector(".plot"), tag = box.querySelector(".tag");
  grp.appendChild(box);

  function highlight(v) {
    spans.forEach((s, val) => s.classList.toggle("on", val === v));
    const opt = opts.find((o) => o.v === v);
    grp._val.innerHTML = `<span class="vtxt tn">${opt ? opt.label : "?"}</span>`;
    const g = GAMMA_EXP[v] != null ? GAMMA_EXP[v] : 1.0;
    tag.textContent = v === 0 ? "线性" : (opt ? "γ " + opt.label : "");
    const line = ptsToLine(gammaPts(g, W, H, p));
    plot.setAttribute("d", line);
    area.setAttribute("d", `${line} L ${W - p} ${H - p} L ${p} ${H - p} Z`);
  }

  const cur = await api.get(code);
  if (cur.ok) highlight(cur.current);
  else { unresponsive(grp); highlight(-1); }
  return grp;
}

// 亮度/对比度: ghead 右侧 −/数字/+, 下方自定义滑块
async function buildSlider(code, hint) {
  const grp = grpShell(hint.name, hint.icon);
  const init = await api.get(code);

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
    const r = await api.set(code, v);
    if (!r.ok) { setConn(`${hint.name} 设置失败: ${r.error}`, "warn"); return; }
    const rb = await api.get(code);
    if (rb.ok) paint(rb.current);
    setConn(`${CUR.model || CUR.description} · 已连接`, "ok");
  }
  paint(init.current);

  num.addEventListener("change", () => apply(Number(num.value)));
  minus.addEventListener("click", () => apply(Number(num.value) - 1));
  plus.addEventListener("click", () => apply(Number(num.value) + 1));

  // 拖动: 实时改屏(节流发命令, 不回读避免卡), 松手再回读确认。
  let dragging = false, lastSent = 0;
  const ratioToV = (clientX) => {
    const r = sld.getBoundingClientRect();
    return Math.round(Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * max);
  };
  function liveSet(v) {
    paint(v);
    const now = Date.now();
    if (now - lastSent >= 50) { lastSent = now; api.set(code, v); }
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

// 色温: 离散分段按钮 (固定档, 不误导成可滑动) + 下方暖->冷指示条
async function buildTemp(code, hint, allowed) {
  const grp = grpShell(hint.name, hint.icon);
  const opts = (allowed && allowed.length ? allowed : [1, 5, 8])
    .map((v) => ({ v, label: labelFor(VCP14_LABELS, v) }));

  const seg = document.createElement("div");
  seg.className = "seg tempseg";
  const spans = new Map();
  opts.forEach((o) => {
    const s = document.createElement("span");
    s.textContent = o.label;
    s.addEventListener("click", async () => {
      setSel(o.v); // 立即响应
      const r = await api.set(code, o.v);
      if (!r.ok) { setConn(`色温设置失败: ${r.error}`, "warn"); return; }
      const rb = await api.get(code);
      setSel(rb.ok ? rb.current : o.v);
      setConn(`${CUR.model || CUR.description} · 已连接`, "ok");
    });
    spans.set(o.v, s); seg.appendChild(s);
  });
  grp.appendChild(seg);

  const wrap = document.createElement("div"); wrap.className = "tempwrap";
  const bar = document.createElement("div"); bar.className = "tempbar";
  const lab = document.createElement("div"); lab.className = "tempbar-labels";
  lab.innerHTML = `<span>暖 5000K</span><span>冷 9300K</span>`;
  wrap.append(bar, lab);
  grp.appendChild(wrap);

  function setSel(v) {
    spans.forEach((s, val) => s.classList.toggle("on", val === v));
    const o = opts.find((x) => x.v === v);
    grp._val.innerHTML = `<span class="vtxt tn">${o ? o.label : "?"}</span>`;
  }

  const cur = await api.get(code);
  if (cur.ok) setSel(cur.current);
  else unresponsive(grp);
  return grp;
}

// raw 控件
function buildRaw(code) {
  const row = document.createElement("div"); row.className = "raw-row";
  const tag = document.createElement("span"); tag.className = "raw-code tn"; tag.textContent = hex2(code);
  const num = document.createElement("input"); num.type = "number"; num.placeholder = "值";
  const getB = document.createElement("button"); getB.className = "mini-btn"; getB.textContent = "读";
  const setB = document.createElement("button"); setB.className = "mini-btn"; setB.textContent = "写";
  const out = document.createElement("span"); out.className = "raw-out";
  getB.addEventListener("click", async () => {
    const r = await api.get(code);
    if (r.ok) { num.value = r.current; out.textContent = `cur=${r.current} max=${r.maximum}`; }
    else out.textContent = "读不回";
  });
  setB.addEventListener("click", async () => {
    if (num.value === "") return;
    const r = await api.set(code, Number(num.value));
    out.textContent = r.ok ? "OK" : ("失败 " + (r.error || ""));
  });
  row.append(tag, num, getB, setB, out);
  return row;
}

// =================== 渲染 ===================

function parseRes(desc) {
  const m = (desc || "").match(/(\d{3,4})\s*[x×]\s*(\d{3,4})(?:\D+(\d{2,3})\s*hz)?/i);
  if (!m) return null;
  return `${m[1]}×${m[2]}` + (m[3] ? ` · ${m[3]}Hz` : "");
}

async function renderControls(mon) {
  CUR = mon;
  const codes = new Set(mon.vcp_codes || []);
  const vals = mon.vcp_values || {};

  $("#sel-name").textContent = mon.description;
  $("#sel-id").textContent = `[${mon.id}]`;
  setConn(`${mon.model || mon.description} · 已连接`, "ok");

  // chips: 信号源 + 分辨率/型号
  const chips = $("#chips"); chips.innerHTML = "";
  if (codes.has(SIGNAL_VCP)) {
    const r = await api.get(SIGNAL_VCP);
    const src = r.ok ? labelFor(VCP60_LABELS, r.current) : "未响应";
    const c = document.createElement("span"); c.className = "chip";
    c.innerHTML = `${icon(I.signal, "sm")}信号源 · ${src}`;
    chips.appendChild(c);
  }
  const res = parseRes(mon.description);
  const c2 = document.createElement("span"); c2.className = "chip tn";
  c2.textContent = res || (mon.model ? `model ${mon.model}` : (mon.type || "—"));
  chips.appendChild(c2);

  // 主控件
  const cont = $("#controls"); cont.innerHTML = "";
  const div = document.createElement("div"); div.className = "divtxt"; div.textContent = "图像";
  cont.appendChild(div);
  let built = 0;
  for (const code of MAIN_ORDER) {
    if (!codes.has(code)) continue;
    const hint = CONTROL_HINTS[code];
    let el;
    if (hint.type === "gamma") el = await buildGamma(code, hint, vals[String(code)]);
    else if (hint.type === "slider") el = await buildSlider(code, hint);
    else if (hint.type === "temp") el = await buildTemp(code, hint, vals[String(code)]);
    cont.appendChild(el); built++;
  }
  if (!built) {
    const p = document.createElement("p"); p.className = "empty";
    p.textContent = "这台显示器没有已知可控 VCP，下方 raw 区可手动尝试。";
    cont.appendChild(p);
  }

  // raw 兜底
  const known = new Set([...MAIN_ORDER, SIGNAL_VCP]);
  const rawCodes = [...codes].filter((c) => !known.has(c)).sort((a, b) => a - b);
  const rawWrap = $("#raw-controls"); rawWrap.innerHTML = "";
  $("#advanced").hidden = rawCodes.length === 0;
  rawCodes.forEach((c) => rawWrap.appendChild(buildRaw(c)));
}

function renderMonitorOptions(monitors, defaultId) {
  const sel = $("#monitor-select"); sel.innerHTML = "";
  monitors.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = String(m.id);
    opt.textContent = `[${m.id}] ${m.description}${m.model ? " · " + m.model : ""}`;
    sel.appendChild(opt);
  });
  if (defaultId != null) sel.value = String(defaultId);
}

let refreshing = false;
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  const btn = $("#win-refresh");
  if (btn) btn.classList.add("spin");
  const prevId = CUR ? CUR.id : null;
  try {
    setConn("枚举显示器中…", "idle");
    const res = await window.pywebview.api.list_monitors();
    if (!res.ok) { setConn(`枚举失败: ${res.error || ""}`, "warn"); return; }
    MONITORS = res.monitors;
    if (!MONITORS.length) {
      setConn("未扫到显示器 · 请接独显输出并开 DDC/CI", "warn");
      $("#chips").innerHTML = ""; $("#controls").innerHTML = ""; $("#advanced").hidden = true;
      $("#sel-name").textContent = "—"; $("#sel-id").textContent = "";
      CUR = null;
      return;
    }
    renderMonitorOptions(MONITORS, res.default);
    // 保留用户当前选中的那台 (若还在); 否则用默认 (认 RTK)
    if (prevId != null && MONITORS.some((m) => m.id === prevId)) {
      $("#monitor-select").value = String(prevId);
    }
    const pick = MONITORS.find((m) => m.id === Number($("#monitor-select").value)) || MONITORS[0];
    await renderControls(pick);
  } finally {
    refreshing = false;
    if (btn) btn.classList.remove("spin");
  }
}

// ---- 换肤 ----
function applyTheme(t) {
  document.body.setAttribute("data-theme", t === "light" ? "light" : "dark");
  try { localStorage.setItem("ddcci-theme", t); } catch (e) {}
}
function initTheme() {
  let t = "dark";
  try { t = localStorage.getItem("ddcci-theme") || "dark"; } catch (e) {}
  applyTheme(t);
}
function toggleTheme() {
  applyTheme(document.body.getAttribute("data-theme") === "dark" ? "light" : "dark");
}

initTheme();
window.addEventListener("pywebviewready", () => {
  initTheme();
  const skin = $("#skin");
  skin.addEventListener("click", toggleTheme);
  skin.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleTheme(); } });
  $("#win-min").addEventListener("click", () => window.pywebview.api.minimize_window());
  $("#win-close").addEventListener("click", () => window.pywebview.api.close_window());
  $("#win-refresh").addEventListener("click", () => refresh());
  // 注: 不再用 window focus 自动刷新 (会被其他程序抢焦点频繁误触发); 改由 ↻ 按钮手动刷新
  $("#monitor-select").addEventListener("change", async (e) => {
    const m = MONITORS.find((x) => x.id === Number(e.target.value));
    if (m) await renderControls(m);
  });
  refresh();
});
