// DDC 控制台 v4 ·「如果苹果来做」
// 控制中心式胶囊滑块、Apple TV 式触控板、灵动岛状态、设置式列表; 背景是屏幕画面的氛围光。
// 后端接口与 ui/nanwei 完全一致 (window.pywebview.api.*), 浏览器直接打开则跑演示数据。

const $ = (s, el) => (el || document).querySelector(s);
const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const hex = (v) => Number(v).toString(16).padStart(2, "0").toUpperCase();

// ---------------------------------------------------------------- 演示桥
// 只在没有 pywebview 时使用; 模拟 USB 小板的延迟和真实帧格式。
function demoFrame(bytes, slave) {
  const all = [slave || 0x5E, 0x51].concat(bytes);
  let chk = 0x50;                       // DDC/CI 校验: 源地址 0x50 起异或
  all.forEach((b) => { chk ^= b; });
  return all.concat([chk]).map(hex).join(" ");
}
const DEMO_META = {
  ok: true, model: "156", features: { macros: true, hold: false },
  colortemp: [{ label: "6500K", value: 0x08 }, { label: "9300K", value: 0x06 }, { label: "User", value: 0x05 }],
  gamma: Array.from({ length: 7 }, (_, i) => ({ label: `γ${i + 1}`, value: 0x06 + i })),
  ops: { brightness: 0x10, contrast: 0x12, colortemp: 0x14, gamma: 0x72 },
};
const DEMO_META_216 = {
  ok: true, model: "216", features: { macros: false, hold: true },
  colortemp: [
    { label: "6500K", value: 0x05 }, { label: "9300K", value: 0x08 }, { label: "7500K", value: 0x06 },
    { label: "5000K", value: 0x04 }, { label: "sRGB", value: 0x01 }, { label: "User", value: 0x0b },
  ],
  gamma: Array.from({ length: 7 }, (_, i) => ({ label: `γ${i + 1}`, value: i + 1 })),
  ops: { brightness: 0x10, contrast: 0x12, colortemp: 0x14, gamma: 0x72 },
};
const DEMO_META_STD = {
  ok: true, model: "std", features: { macros: false, hold: false, keys: false, choices: false },
  colortemp: [], gamma: [],
  ops: { brightness: 0x10, contrast: 0x12, colortemp: 0x14, gamma: 0x72 },
};
const KEY_CODE = { menu: 0x01, left: 0x02, right: 0x03, exit: 0x05, ok: 0x04 };
const demoBridge = {
  _model: "156",
  _v: { 0x10: [64, 100], 0x12: [72, 100], 0x14: [0x06, 0x0d], 0x72: [0x08, 0x0c] },
  async _lag(a, b) { await sleep((a || 70) + Math.random() * ((b || 150) - (a || 70))); },
  _meta() { return this._model === "216" ? DEMO_META_216 : this._model === "std" ? DEMO_META_STD : DEMO_META; },
  async models() {
    return { ok: true, current: this._model, models: [
      { id: "156", label: "156pin", title: "156pin 机型", desc: "南微协议 · 地址 0x5E", slaves: ["0x5E", "0x6E"], macros: true, hold: false },
      { id: "216", label: "216pin", title: "216pin 机型", desc: "标准 DDC/CI · 地址 0x6E", slaves: ["0x6E"], macros: false, hold: true },
      { id: "std", label: "标准显示器", title: "标准显示器", desc: "系统 DDC/CI · 只控亮度/对比度", slaves: ["0x6E"], macros: false, hold: false },
    ] };
  },
  async discover_targets() {
    await sleep(900);
    return { ok: true, errors: [], targets: [
      { id: "rawusb:0x5E:0", backend: "rawusb", address: "0x5E", mon_id: 0, model: "156", description: "JRD UC1190_DVI", recommended: true },
      { id: "gpu:0x6E:1", backend: "gpu", address: "0x6E", mon_id: 1, model: "216", description: "RTK 216pin 样机", recommended: false },
      { id: "dxva2:0x6E:2", backend: "dxva2", address: "0x6E", mon_id: 2, model: "std", description: "DELL U2724D", recommended: false },
    ] };
  },
  async connect_target(t) {
    await this._lag(200, 320);
    this._model = t.model || "156";
    if (this._model === "216") { this._v[0x14] = [0x05, 0x0b]; this._v[0x72] = [3, 7]; }
    else { this._v[0x14] = [0x06, 0x0d]; this._v[0x72] = [0x08, 0x0c]; }
    return { ok: true, backend: t.backend, address: t.address, mon_id: t.mon_id, description: t.description,
      versions: this._model === "216" ? { hw: null, sw: 1 } : this._model === "std" ? { hw: null, sw: null } : { hw: 101, sw: 101 }, model: this._model, meta: this._meta() };
  },
  async protocol_meta() { return this._meta(); },
  async get_param(op) {
    await this._lag();
    const v = this._v[Number(op)] || [0, 100];
    return { ok: true, current: v[0], maximum: v[1], tx: demoFrame([0x01, Number(op)]) };
  },
  async set_param(op, value) {
    await this._lag();
    (this._v[Number(op)] || (this._v[Number(op)] = [0, 100]))[0] = Number(value);
    return { ok: true, tx: demoFrame([0x03, Number(op), 0x00, Number(value)]) };
  },
  async get_choice(kind) { return this.get_param(kind === "gamma" ? 0x72 : 0x14); },
  async set_choice(kind, value) { return this.set_param(kind === "gamma" ? 0x72 : 0x14, value); },
  async press_key(name) { await this._lag(); return { ok: true, tx: demoFrame([0xC0, 0x96, KEY_CODE[name] || 0, 0x00]) }; },
  async press_key_raw(v) { await this._lag(); return { ok: true, tx: demoFrame([0xC0, 0x96, Number(v), 0x00]) }; },
  async hold_key(name, seconds) {
    await sleep(Number(seconds) * 1000);
    return { ok: true, seconds: Number(seconds), tx: `${demoFrame([0xC0, 0x96, KEY_CODE[name] || 0, 0x01], 0x6E)}  … ${Number(seconds).toFixed(1)}s …  ${demoFrame([0xC0, 0x96, 0xFF, 0x00], 0x6E)}` };
  },
  async enter_factory() { await sleep(2 * 350); return { ok: true, keys: ["menu", "ok"], tx: "MENU → OK" }; },
  async start_aging() {
    const keys = ["menu", "ok", "menu", "menu", "right", "menu", "exit", "exit"];
    await sleep(keys.length * 350);
    return { ok: true, keys, tx: keys.map((k) => k.toUpperCase()).join(" → ") };
  },
  async minimize_window() { return { ok: true }; },
  async close_window() { return { ok: true }; },
  async start_resize() { return { ok: true }; },
  async app_version() { return { ok: true, version: "42", sha: "demo", source: "demo" }; },
  async check_update() { return { ok: true, current: "42", has_update: false, behind_by: 0, error: null }; },
  async open_repo() { return { ok: true }; },
};
// Qt 版 (Win7, pywebview 5.4): api 对象比 QWebChannel 先出现。通道没建好就调用, pywebview 只等 100ms
// 重试一次, 还没好那次调用就永远不返回 —— 启动扫描卡死在"正在查找…" (2026-10-12 实遇)。
// 所以 Qt 下必须等 _QWebChannel 到位才算就绪。
const bridgeReady = () => !!(window.pywebview && window.pywebview.api) &&
  (window.pywebview.platform !== "qtwebengine" || !!window.pywebview._QWebChannel);
const bridge = () => (window.pywebview && window.pywebview.api ? window.pywebview.api : demoBridge);
const app = $("#app");

// ---------------------------------------------------------------- 状态
let META = null, TARGETS = [], CURRENT = null, MODELS = [], holding = false;
const VAL = { brightness: 50, contrast: 50, ctIndex: 0, gIndex: 2 };
const MAX = { brightness: 100, contrast: 100 };
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const SVG = {
  check: '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  bang: '<svg viewBox="0 0 24 24"><path d="M12 6v7.5M12 17.6v.1"/></svg>',
  tick: '<svg class="tick" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  monitor: '<svg viewBox="0 0 24 24"><rect x="3" y="4.5" width="18" height="12" rx="2"/><path d="M9 20h6M12 16.5V20"/></svg>',
  hourglass: '<svg viewBox="0 0 24 24"><path d="M7.5 4h9M7.5 20h9M8.5 4c0 4.2 7 4.6 7 8s-7 3.8-7 8M15.5 4c0 4.2-7 4.6-7 8"/></svg>',
  keyboard: '<svg viewBox="0 0 24 24"><rect x="3.5" y="6.5" width="17" height="11" rx="2"/><path d="M7 10h.01M10 10h.01M13 10h.01M16.5 10h.01M8 14h8"/></svg>',
};
function spinner() {
  let s = '<svg class="spin" viewBox="0 0 24 24">';
  for (let i = 0; i < 8; i++) s += `<line x1="12" y1="3.5" x2="12" y2="7.2" transform="rotate(${i * 45} 12 12)" opacity="${((i + 1) / 8).toFixed(2)}"/>`;
  return s + "</svg>";
}

// ---------------------------------------------------------------- 屏幕 / 氛围
function kelvinOf(label) {
  if (/srgb/i.test(label || "")) return 6500;
  const m = /(\d{4,5})\s*K/i.exec(label || "");
  return m ? Number(m[1]) : null;
}
function tintFor(label) {
  const k = kelvinOf(label);
  if (k == null) return "#fff4e8";
  if (k >= 9000) return "#e2eaff";
  if (k >= 7300) return "#edf1ff";
  if (k <= 5500) return "#ffe9d2";
  return "#ffffff";
}
function swatch(label) {
  const k = kelvinOf(label);
  if (k == null) return "conic-gradient(from 210deg, #ff9f0a, #ffd60a, #30d158, #64d2ff, #5e5ce6, #bf5af2, #ff375f, #ff9f0a)";
  return `radial-gradient(circle at 35% 30%, #fff 0%, ${k >= 9000 ? "#c9d8ff" : k >= 7000 ? "#dde6ff" : k <= 5500 ? "#ffd9b0" : "#f4efe8"} 100%)`;
}
const GAMMAS = [1.8, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0];     // 示意曲线, 不代表固件真实值
const gammaOf = (i) => GAMMAS[clamp(i, 0, 6)] || 2.2;
function renderPicture() {
  const b = VAL.brightness / (MAX.brightness || 100), c = VAL.contrast / (MAX.contrast || 100);
  $("#pic").style.filter = `url(#gammaF) brightness(${(0.32 + 0.85 * b).toFixed(3)}) contrast(${(0.55 + 0.9 * c).toFixed(3)})`;
  const ex = (META && !META.gamma.length ? 1 : gammaOf(VAL.gIndex) / 2.2).toFixed(3);   // 没有 Gamma 的机型画面不弯曲线
  ["gR", "gG", "gB"].forEach((id) => document.getElementById(id).setAttribute("exponent", ex));
  const ct = META && META.colortemp[VAL.ctIndex];
  const tint = tintFor(ct && ct.label);
  $("#tint").style.background = tint;
  $("#veil").style.setProperty("--amb-tint", tint);
  // 氛围光一直在 (没连上也保持那层紫蓝), 连上后才跟着亮度变
  const ab = app.dataset.link === "ok" ? b : 0.64;
  $("#amb").style.filter = `blur(70px) saturate(1.5) brightness(${(0.55 + 0.6 * ab).toFixed(3)})`;
}

// ---------------------------------------------------------------- 灵动岛
// 平时是一颗小胶囊 (连接状态), 有动作时撑开显示"在干什么/成没成", 一会儿再缩回去。
const islandEl = $("#island"), islandIn = $("#is-in");
const measurer = document.createElement("span");
measurer.className = "is-in";
measurer.style.cssText = "position:fixed;left:-9999px;top:0;right:auto;visibility:hidden;display:inline-flex";
document.body.appendChild(measurer);
let islandTimer = 0, islandKey = "";
function island(html, hold) {
  clearTimeout(islandTimer);
  if (html !== islandKey) {
    islandKey = html;
    islandIn.innerHTML = html;
    islandIn.classList.remove("swap"); void islandIn.offsetWidth; islandIn.classList.add("swap");
    measurer.innerHTML = html;
    const w = Math.max(30, Math.ceil(measurer.offsetWidth) + 2);
    islandEl.style.width = w + "px";
    islandEl.style.marginLeft = -w / 2 + "px";
  }
  if (hold) islandTimer = setTimeout(islandIdle, hold);
}
function islandIdle() {
  const st = app.dataset.link;
  if (st === "scan") island(`<span class="is-ico">${spinner()}</span>${esc($("#dev-name").dataset.scanText || "正在查找显示器")}`);
  else if (st === "ok") island('<span class="is-ico"><i class="is-dot"></i></span>已连接');
  else if (st === "err") island('<span class="is-ico"><i class="is-dot red"></i></span>连接失败');
  else island('<span class="is-ico"><i class="is-dot red"></i></span>未找到显示器');
}
function islandResult(ok, html, err) {
  island(ok ? `<span class="is-ico is-check">${SVG.check}</span>${html}`
            : `<span class="is-ico is-x">${SVG.bang}</span>${html}<span class="is-sub">${esc(err || "无应答")}</span>`, ok ? 1500 : 2600);
}

// ---------------------------------------------------------------- 日志 / 一次往返
let LOG_N = 0;
function log(label, tx, ok, note) {
  const box = $("#log");
  const empty = $(".nolog", box); if (empty) empty.remove();
  const row = document.createElement("div");
  row.className = "lg" + (ok ? "" : " bad");
  row.innerHTML = `<time>${new Date().toTimeString().slice(0, 8)}</time><span class="st"><i></i></span>` +
    `<div class="w"><b>${esc(label)}${note ? `<em>${esc(note)}</em>` : ""}</b>${tx ? `<code>${esc(tx)}</code>` : ""}</div>`;
  box.insertBefore(row, box.firstChild);
  while (box.children.length > 300) box.removeChild(box.lastChild);
  LOG_N++;
  $("#log-n").textContent = String(LOG_N);
  $("#sheet-n").textContent = LOG_N + " 条";
}
function logEmpty() { $("#log").innerHTML = '<div class="nolog">还没有通信记录</div>'; }

async function io(label, call, opts) {
  opts = opts || {};
  let res;
  try { res = await call(); } catch (e) { res = { ok: false, error: String((e && e.message) || e) }; }
  if (!res) res = { ok: false, error: "无返回" };
  if (!opts.quiet) {
    const note = res.ok ? (opts.note ? opts.note(res) : "") : (res.error || "无应答");
    log(label, res.tx, res.ok, note);
    if (opts.island !== false) islandResult(res.ok, opts.islandHtml || esc(label), res.error);
  }
  return res;
}

// ---------------------------------------------------------------- 胶囊滑块
// 控制中心的手感: 按住拖是相对移动, 轻点直接跳到该处; 拖过头整条橡皮筋似地拉长, 松手弹回。
function sunRays(f) {
  let d = "";
  const r1 = 6.4, r2 = r1 + 1.1 + 2.6 * f;
  for (let i = 0; i < 8; i++) {
    const a = i * Math.PI / 4, cx = Math.cos(a), sy = Math.sin(a);
    d += `M${(12 + cx * r1).toFixed(2)} ${(12 + sy * r1).toFixed(2)}L${(12 + cx * r2).toFixed(2)} ${(12 + sy * r2).toFixed(2)}`;
  }
  return d;
}
function makeSlider(id, name, onInput, onChange) {
  const el = $("#s-" + id);
  const api = { value: 0 };
  api.set = (v, silent) => {
    const max = MAX[id] || 100;
    v = clamp(Math.round(v), 0, max);
    api.value = v;
    el.style.setProperty("--p", (v / max * 100).toFixed(2) + "%");
    $$(".s-val", el).forEach((t) => { t.textContent = String(v); });
    if (id === "brightness") $$(".rays", el).forEach((p) => p.setAttribute("d", sunRays(v / max)));
    el.setAttribute("aria-valuenow", v);
    if (!silent) onInput(v);
  };
  const stretch = (over, side) => {
    const s = 0.06 * (1 - 1 / (Math.abs(over) * 4 + 1));    // 越拉越难拉
    el.style.transformOrigin = side + " center";
    el.style.transform = s ? `scale(${(1 + s).toFixed(4)}, ${(1 - s * 0.7).toFixed(4)})` : "";
  };
  el.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    el.setPointerCapture(e.pointerId);
    const r = el.getBoundingClientRect(), max = MAX[id] || 100;
    const x0 = e.clientX, v0 = api.value;
    let moved = false;
    el.classList.remove("anim");
    el.style.transition = "transform .25s var(--smooth)";
    el.style.transform = "scale(1.012)";
    const move = (ev) => {
      const dx = ev.clientX - x0;
      if (!moved && Math.abs(dx) < 3) return;
      moved = true;
      el.style.transition = "none";
      const raw = v0 + dx / r.width * max;
      api.set(raw);
      if (raw > max) stretch((raw - max) / max, "left");
      else if (raw < 0) stretch(raw / max, "right");
      else stretch(0);
      island(`<span class="is-ico" style="color:#fff">${id === "brightness" ? '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="' + sunRays(api.value / max) + '"/></svg>' : '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="7"/><path d="M12 5a7 7 0 0 1 0 14z" fill="#fff" stroke="none"/></svg>'}</span>${name}<span class="is-sub">${api.value}</span>`);
    };
    const up = (ev) => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      if (!moved) {
        el.classList.add("anim");
        api.set((ev.clientX - r.left) / r.width * max);
      }
      el.style.transition = "transform .55s var(--spring)";
      el.style.transform = "";
      onChange(api.value);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  });
  let t = 0;
  const bump = (d) => {
    el.classList.add("anim");
    api.set(api.value + d);
    clearTimeout(t);
    t = setTimeout(() => onChange(api.value), 320);
  };
  el.addEventListener("wheel", (e) => { e.preventDefault(); bump(e.deltaY < 0 ? 1 : -1); }, { passive: false });
  el.addEventListener("keydown", (e) => {
    const d = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 10, PageDown: -10 }[e.key];
    if (d) { e.preventDefault(); e.stopPropagation(); bump(d); }
  });
  api.bump = bump;
  return api;
}
const SLIDERS = {};
let lastSent = 0;
[["brightness", "亮度"], ["contrast", "对比度"]].forEach(([id, name]) => {
  SLIDERS[id] = makeSlider(id, name,
    (v) => {
      VAL[id] = v; renderPicture();
      const now = Date.now();
      if (META && now - lastSent >= 120) { lastSent = now; io(name, () => bridge().set_param(META.ops[id], v), { quiet: true }); }
    },
    async (v) => {
      if (!META) return;
      const r = await io(`${name} ${v}`, () => bridge().set_param(META.ops[id], v), { island: false });
      if (r.ok) await readParam(id, true);
      else islandResult(false, name, r.error);
    });
});
async function readParam(id, announce) {
  const name = id === "brightness" ? "亮度" : "对比度";
  const r = await io(`读取${name}`, () => bridge().get_param(META.ops[id]), { island: false, note: (x) => `→ ${x.current}/${x.maximum}` });
  if (!r.ok) { $$(`#s-${id} .s-val`).forEach((t) => { t.textContent = "--"; }); return r; }
  if (r.maximum) MAX[id] = r.maximum;
  VAL[id] = r.current;
  $("#s-" + id).classList.add("anim");
  SLIDERS[id].set(r.current, true);
  renderPicture();
  if (announce) islandResult(true, `${name}<span class="is-sub">${r.current}</span>`);
  return r;
}

// ---------------------------------------------------------------- 色温 / Gamma 方块
const CT_NAME = (l) => (l === "User" ? "用户" : l);
const CT_SUB = (l) => {
  if (/srgb/i.test(l || "")) return "标准色域";
  const k = kelvinOf(l);
  return k == null ? "自定义" : k >= 9000 ? "偏冷" : k >= 7000 ? "略冷" : k <= 5500 ? "偏暖" : "标准 D65";
};
function curvePath(g, w, h, closed) {
  let d = "";
  for (let i = 0; i <= 48; i++) {
    const x = i / 48, y = Math.pow(x, g);
    d += (i ? "L" : "M") + (x * w).toFixed(1) + " " + (h - y * h).toFixed(1);
  }
  return closed ? d + `L${w} ${h}L0 ${h}Z` : d;
}
function markColortemp(i) {
  VAL.ctIndex = i;
  const o = META.colortemp[i];
  $("#ct-val").textContent = o ? CT_NAME(o.label) : "--";
  $("#ct-dot").style.background = o ? swatch(o.label) : "transparent";
  $$("#expand .tp").forEach((b) => b.classList.toggle("on", Number(b.dataset.i) === i));
  renderPicture();
}
let curveG = 2.2, curveAnim = 0;
function animateCurve(target) {
  cancelAnimationFrame(curveAnim);
  const from = curveG, t0 = performance.now();
  const step = (now) => {
    const t = clamp((now - t0) / 450, 0, 1), e = 1 - Math.pow(1 - t, 3);
    curveG = from + (target - from) * e;
    const line = $("#expand .bigcurve .line");
    if (line) { line.setAttribute("d", curvePath(curveG, 300, 120)); $("#expand .bigcurve .area").setAttribute("d", curvePath(curveG, 300, 120, true)); }
    $("#gm-mini path").setAttribute("d", curvePath(curveG, 40, 26));
    if (t < 1) curveAnim = requestAnimationFrame(step);
  };
  curveAnim = requestAnimationFrame(step);
}
function markGamma(i) {
  VAL.gIndex = i;
  $("#gm-val").textContent = String(i + 1);
  const th = $("#expand .seg-th");
  if (th) th.style.transform = `translateX(${i * 100}%)`;
  $$("#expand .segc button").forEach((b) => b.classList.toggle("on", Number(b.dataset.i) === i));
  animateCurve(gammaOf(i));
  renderPicture();
}
async function readDiscrete(kind) {
  const list = META[kind];
  const r = await io(kind === "gamma" ? "读取 Gamma" : "读取色温", () => bridge().get_choice(kind), {
    island: false,
    note: (x) => { const h = list.find((o) => Number(o.value) === Number(x.current)); return "→ " + (h ? h.label : "0x" + hex(x.current)); },
  });
  if (!r.ok) return r;
  const i = list.findIndex((o) => Number(o.value) === Number(r.current));
  if (i >= 0) { if (kind === "gamma") markGamma(i); else markColortemp(i); }
  return r;
}
async function chooseColortemp(i) {
  if (i === VAL.ctIndex) return;
  markColortemp(i);
  const o = META.colortemp[i];
  const r = await io(`色温 ${o.label}`, () => bridge().set_choice("colortemp", o.value), { islandHtml: `色温<span class="is-sub">${esc(CT_NAME(o.label))}</span>` });
  if (r.ok) readDiscrete("colortemp");
}
async function chooseGamma(i) {
  if (i === VAL.gIndex) return;
  markGamma(i);
  const o = META.gamma[i];
  const r = await io(`Gamma ${o.label}`, () => bridge().set_choice("gamma", o.value), { islandHtml: `Gamma<span class="is-sub">${i + 1}</span>` });
  if (r.ok) readDiscrete("gamma");
}

// 展开卡: 从方块原地"长"成大卡片 (FLIP), 点外面 / 完成 / Esc 收回原处
const expand = $("#expand"), scrim = $("#scrim");
let openKind = null;
function expandBody(kind) {
  if (kind === "colortemp") {
    return `<div class="ex-body"><div class="ex-head"><b>色温</b><span>白点预设</span><span class="flex"></span><button class="pill" data-done type="button">完成</button></div>
      <div class="temps${META.colortemp.length > 3 ? " many" : ""}">${META.colortemp.map((o, i) =>
        `<button class="tp${i === VAL.ctIndex ? " on" : ""}" data-i="${i}" type="button"><i style="background:${swatch(o.label)}"></i><b>${esc(CT_NAME(o.label))}</b><small>${CT_SUB(o.label)}</small></button>`).join("")}</div>
      <p class="ex-note">选中后立即发送到显示器，屏幕预览和窗口背景会一起变。</p></div>`;
  }
  let grid = "";
  for (let i = 1; i < 4; i++) grid += `<line x1="${75 * i}" y1="0" x2="${75 * i}" y2="120"/><line x1="0" y1="${30 * i}" x2="300" y2="${30 * i}"/>`;
  return `<div class="ex-body"><div class="ex-head"><b>Gamma</b><span>灰阶曲线</span><span class="flex"></span><button class="pill" data-done type="button">完成</button></div>
    <svg class="bigcurve" viewBox="0 0 300 120" preserveAspectRatio="none"><g class="grid">${grid}</g><path class="diag" d="M0 120L300 0"/>
      <path class="area" d="${curvePath(curveG, 300, 120, true)}"/><path class="line" d="${curvePath(curveG, 300, 120)}"/></svg>
    <div class="segc"><i class="seg-th" style="width:calc((100% - 4px) / ${META.gamma.length});transform:translateX(${VAL.gIndex * 100}%)"></i>
      ${META.gamma.map((o, i) => `<button type="button" data-i="${i}" class="${i === VAL.gIndex ? "on" : ""}" title="${esc(o.label)}">${i + 1}</button>`).join("")}</div>
    <p class="ex-note">曲线形状为示意，各档实际值以固件为准。</p></div>`;
}
function openExpand(kind) {
  if (!META || openKind) return;
  openKind = kind;
  const tile = $("#t-" + kind), col = $("#right");
  expand.innerHTML = expandBody(kind);
  const a = app.getBoundingClientRect(), c = col.getBoundingClientRect(), t = tile.getBoundingClientRect();
  expand.style.display = "block";
  expand.style.left = (c.left - a.left) + "px";
  expand.style.width = c.width + "px";
  const h = expand.offsetHeight;
  const top = clamp(c.top - a.top + (c.height - h) / 2, c.top - a.top, a.height - h - 12);
  expand.style.top = top + "px";
  const sx = t.width / c.width, sy = t.height / h;
  expand.style.transition = "none";
  expand.style.transform = `translate(${t.left - c.left}px, ${t.top - a.top - top}px) scale(${sx}, ${sy})`;
  expand.classList.add("morph");
  void expand.offsetWidth;
  expand.style.transition = "transform .55s cubic-bezier(.32, 1.18, .5, 1)";
  expand.style.transform = "none";
  tile.style.visibility = "hidden";
  scrim.classList.add("on");
  setTimeout(() => expand.classList.remove("morph"), 160);
  $("[data-done]", expand).addEventListener("click", closeExpand);
  $$(".tp", expand).forEach((b) => b.addEventListener("click", () => chooseColortemp(Number(b.dataset.i))));
  $$(".segc button", expand).forEach((b) => b.addEventListener("click", () => chooseGamma(Number(b.dataset.i))));
}
function closeExpand() {
  if (!openKind) return;
  const kind = openKind; openKind = null;
  const tile = $("#t-" + kind);
  const a = app.getBoundingClientRect(), e = expand.getBoundingClientRect(), t = tile.getBoundingClientRect();
  expand.classList.add("morph");
  expand.style.transition = "transform .42s cubic-bezier(.4, 0, .2, 1)";
  expand.style.transform = `translate(${t.left - e.left}px, ${t.top - e.top}px) scale(${t.width / e.width}, ${t.height / e.height})`;
  scrim.classList.remove("on");
  setTimeout(() => { expand.style.display = "none"; tile.style.visibility = ""; }, 400);
}
$("#t-colortemp").addEventListener("click", () => openExpand("colortemp"));
$("#t-gamma").addEventListener("click", () => openExpand("gamma"));
scrim.addEventListener("click", closeExpand);

// ---------------------------------------------------------------- OSD 按键
const KEY_LBL = { menu: "MENU", left: "LEFT", right: "RIGHT", exit: "EXIT", ok: "OK" };
function keyVisual(name) {
  const k = $(`.keys .key[data-key="${name}"]`);
  if (!k) return;                                              // OK 键没有实体按钮, 只走灵动岛
  k.classList.remove("hit"); void k.offsetWidth; k.classList.add("hit");
  setTimeout(() => k.classList.remove("hit"), 200);
}
let macroBusy = false;
function pressKey(name) {
  if (app.dataset.link !== "ok" || macroBusy || holding || !hasFeature("keys")) return;
  keyVisual(name);
  io(`按键 ${KEY_LBL[name]}`, () => bridge().press_key(name), { islandHtml: `<span class="is-key">${KEY_LBL[name]}</span>已发送` });
}
$$(".keys .key").forEach((k) => k.addEventListener("click", () => pressKey(k.dataset.key)));

// ---------------------------------------------------------------- 长按 (216pin)
// 后端按住 → 等待 → 松开 (松开帧必发)。期间锁住 OSD 键, 按钮上倒计时, 方块底部进度条。
const holdSec = $("#hold-sec");
function holdSeconds() {
  const v = Number(String(holdSec.value || "").trim());
  return Number.isFinite(v) && v >= 0.2 && v <= 30 ? v : null;
}
$$(".stepper button").forEach((b) => b.addEventListener("click", () => {
  const v = holdSeconds() == null ? 3 : holdSeconds();
  holdSec.value = String(clamp(Math.round((v + Number(b.dataset.d)) * 10) / 10, 0.5, 30));
  $(".stepper").classList.remove("bad");
}));
holdSec.addEventListener("input", () => $(".stepper").classList.remove("bad"));
holdSec.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") $("#hold-send").click(); });
$("#hold-send").addEventListener("click", async () => {
  if (holding || macroBusy || app.dataset.link !== "ok") return;
  const sec = holdSeconds();
  if (sec == null) {
    $(".stepper").classList.add("bad");
    islandResult(false, "长按", "秒数要在 0.2–30 之间");
    return;
  }
  const name = $("#hold-key").value, btn = $("#hold-send"), tile = $("#hold-tile");
  holding = true;
  app.classList.add("holding");
  tile.classList.add("run");
  tile.style.setProperty("--prog", "0%");
  const t0 = Date.now();
  const tick = () => {
    const el = (Date.now() - t0) / 1000, left = Math.max(0, sec - el);
    btn.textContent = left.toFixed(1) + "s";
    tile.style.setProperty("--prog", Math.min(100, el / sec * 100).toFixed(1) + "%");
    island(`<span class="is-key">${KEY_LBL[name]}</span>按住中<span class="is-sub">${left.toFixed(1)}s</span>`);
  };
  tick();
  const timer = setInterval(tick, 100);
  try {
    await io(`长按 ${KEY_LBL[name]}`, () => bridge().hold_key(name, sec), {
      note: (x) => `${x.seconds}s 已松开`,
      islandHtml: `<span class="is-key">${KEY_LBL[name]}</span>已松开<span class="is-sub">${sec}s</span>`,
    });
  } finally {
    clearInterval(timer);
    btn.textContent = "按住";
    tile.classList.remove("run");
    app.classList.remove("holding");
    holding = false;
  }
});

// ---------------------------------------------------------------- 提示框
let alertResolve = null;
function showAlert(o) {
  const box = $("#alert");
  box.innerHTML =
    `<div class="al-icon${o.tone === "red" ? " red" : ""}">${o.icon || SVG.monitor}</div><h3>${esc(o.title)}</h3>` +
    (o.msg ? `<p>${esc(o.msg)}</p>` : "") +
    (o.field ? `<label class="al-field"><em>0x</em><input id="al-input" maxlength="2" spellcheck="false" value="${esc(o.field)}"></label>` : "") +
    `<div class="al-btns">${o.buttons.map((b, i) => `<button type="button" class="ab ${b.kind || ""}" data-i="${i}">${esc(b.text)}</button>`).join("")}</div>`;
  $("#alert-wrap").classList.add("on");
  const input = $("#al-input");
  if (input) { setTimeout(() => { input.focus(); input.select(); }, 60); input.addEventListener("input", () => input.parentNode.classList.remove("bad")); }
  return new Promise((resolve) => {
    alertResolve = (i) => {
      if (i != null && o.validate && !o.validate(input)) { input.parentNode.classList.add("bad"); input.focus(); return; }
      alertResolve = null;
      $("#alert-wrap").classList.remove("on");
      resolve(i == null ? null : { i, value: input ? input.value : null });
    };
    $$(".ab", box).forEach((b) => b.addEventListener("click", () => {
      const i = Number(b.dataset.i);
      alertResolve(o.buttons[i].cancel ? null : i);
    }));
    if (input) input.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") alertResolve(0); if (e.key === "Escape") alertResolve(null); });
  });
}

// ---------------------------------------------------------------- 列表动作
async function runMacro(title, api, seq, tileId) {
  if (app.dataset.link !== "ok" || macroBusy || holding) return;
  macroBusy = true;
  const tile = $("#" + tileId);
  tile.style.setProperty("--prog", "0%");
  tile.classList.add("run");
  const call = io(title, () => bridge()[api](), { island: false, note: () => "序列已发完" });
  for (let i = 0; i < seq.length; i++) {
    island(`${esc(title)}<span class="is-steps">${seq.map((_, j) => `<i class="${j < i ? "done" : j === i ? "now" : ""}"></i>`).join("")}</span>`);
    keyVisual(seq[i]);
    tile.style.setProperty("--prog", ((i + 1) / seq.length * 100).toFixed(1) + "%");
    await sleep(350);                                         // 与后端 AGING_KEY_GAP 同节拍
  }
  const r = await call;
  macroBusy = false;
  setTimeout(() => tile.classList.remove("run"), 500);
  islandResult(r.ok, esc(title), r.error);
}
$("#act-factory").addEventListener("click", () => runMacro("进入工厂菜单", "enter_factory", ["menu", "ok"], "act-factory"));
$("#act-aging").addEventListener("click", async () => {
  const ok = await showAlert({
    tone: "red", icon: SVG.hourglass, title: "开始老化？",
    msg: "将自动进入工厂菜单并打开老化模式，显示器会一直运行老化画面，直到在 OSD 中手动退出。",
    buttons: [{ text: "开始老化", kind: "danger" }, { text: "取消", cancel: true }],
  });
  if (ok) runMacro("开始老化", "start_aging", ["menu", "ok", "menu", "menu", "right", "menu", "exit", "exit"], "act-aging");
});
let rawLast = "04";
$("#act-raw").addEventListener("click", async () => {
  const r = await showAlert({
    icon: SVG.keyboard, title: "发送键值",
    msg: "向显示器发送任意按键码 (00–FF)，用来试规格书里没列出的键，例如 OK = 04。",
    field: rawLast,
    validate: (inp) => /^[0-9a-f]{1,2}$/i.test((inp.value || "").trim()),
    buttons: [{ text: "发送", kind: "primary" }, { text: "取消", cancel: true }],
  });
  if (!r) return;
  const v = parseInt(r.value.trim(), 16);
  rawLast = hex(v);
  io(`键值 0x${rawLast}`, () => bridge().press_key_raw(v), { islandHtml: `<span class="is-key">0x${rawLast}</span>已发送` });
});
const sheet = $("#sheet");
function openSheet() { closeMenu(); closeExpand(); sheet.classList.add("open"); }
function closeSheet() { sheet.classList.remove("open"); }
$("#act-log").addEventListener("click", openSheet);
$("#island").addEventListener("click", () => (sheet.classList.contains("open") ? closeSheet() : openSheet()));
$("#sheet-done").addEventListener("click", closeSheet);
$("#log-clear").addEventListener("click", () => { LOG_N = 0; $("#log-n").textContent = "0"; $("#sheet-n").textContent = ""; logEmpty(); });
$("#log-copy").addEventListener("click", () => {
  const text = $$("#log .lg").map((r) => r.innerText.replace(/\n+/g, "  ")).join("\n");
  const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); } catch (e) {}
  ta.remove();
  const b = $("#log-copy"); b.textContent = "已拷贝"; setTimeout(() => { b.textContent = "拷贝"; }, 1200);
});

// ---------------------------------------------------------------- 机型
// 机型不用手选: 扫描时后端按应答识别, 每个目标带 model; 连上哪台, connect_target 就回传
// 那台的界面参数 (result.meta), 这里一次切完 —— 156pin 显示工厂/老化宏, 216pin 显示长按。
const modelLabel = (id) => { const m = MODELS.find((x) => x.id === id); return m ? m.label : id ? id + "pin" : "--"; };
// 功能开关缺省视为有 (老后端的 meta 没有 keys/choices 字段); 标准显示器两个都关, 只剩亮度/对比度。
const hasFeature = (f) => !META || !META.features || META.features[f] !== false;
function applyModel(meta) {
  META = meta;
  $$("[data-model]").forEach((el) => { el.hidden = el.dataset.model !== meta.model; });
  $$("[data-feature]").forEach((el) => { el.hidden = !hasFeature(el.dataset.feature); });
  VAL.ctIndex = clamp(VAL.ctIndex, 0, meta.colortemp.length - 1);
  VAL.gIndex = clamp(VAL.gIndex, 0, meta.gamma.length - 1);
  $("#ct-val").textContent = "--";
  $("#gm-val").textContent = "--";
  renderPicture();
}
async function initModels() {
  try { const r = await bridge().models(); MODELS = (r && r.models) || []; } catch (e) { MODELS = []; }
  try { applyModel(await bridge().protocol_meta()); } catch (e) {}   // 扫到目标前先按上次的机型摆界面
}

// ---------------------------------------------------------------- 设备菜单 / 连接
const PATH_NAME = { rawusb: "USB 小板", gpu: "显卡", dxva2: "系统 DDC/CI" };
const menu = $("#dev-menu");
function closeMenu() { menu.classList.remove("open"); $("#dev-pick").classList.remove("open"); }
function renderMenu() {
  let h = '<div class="m-hd">控制路径</div>';
  TARGETS.forEach((t) => {
    h += `<button class="m-it" type="button" data-id="${esc(t.id)}" title="${esc(t.id)}">${CURRENT && CURRENT.id === t.id ? SVG.tick : ""}` +
      `<span><b>${esc(t.description)}</b><small>${esc(modelLabel(t.model))} · 通过 ${PATH_NAME[t.backend] || t.backend} · ${esc(t.address)}</small></span>${t.recommended ? "<em>推荐</em>" : ""}</button>`;
  });
  h += `<div class="m-sep"></div><button class="m-it plain" type="button" data-rescan>重新查找显示器</button>`;
  menu.innerHTML = h;
  $$(".m-it[data-id]", menu).forEach((b) => b.addEventListener("click", () => { closeMenu(); selectTarget(b.dataset.id); }));
  $("[data-rescan]", menu).addEventListener("click", () => { closeMenu(); refresh(); });
}
$("#dev-pick").addEventListener("click", (e) => {
  e.stopPropagation();
  if (!TARGETS.length) { if (app.dataset.link !== "scan") refresh(); return; }
  renderMenu();
  // 默认挂在固件版本下面; 窗口矮 (420) 放不下就往上挪, 整个菜单始终留在窗口里
  const fw = $("#dev-fw"), hero = menu.parentNode.getBoundingClientRect();
  const want = fw.offsetTop + fw.offsetHeight + 6;
  const maxTop = window.innerHeight - 10 - hero.top - menu.offsetHeight;
  const top = Math.max(-hero.top + 44, Math.min(want, maxTop));
  menu.style.top = top + "px";
  menu.style.transformOrigin = top < want ? "50% 100%" : "50% 0";
  menu.classList.toggle("open");
  $("#dev-pick").classList.toggle("open", menu.classList.contains("open"));
});
document.addEventListener("click", (e) => { if (!e.target.closest("#dev-menu")) closeMenu(); });

function setLink(st) { app.dataset.link = st; islandIdle(); renderPicture(); renderStatus(); }
// 名称下面那行 = 连接状态 (不可点; 选显示器点名称)
let lastError = "";
function renderStatus() {
  const st = app.dataset.link, t = CURRENT;
  const path = t ? `${PATH_NAME[t.backend] || t.backend} · ${t.address}` : "";
  $("#dev-path").textContent =
    st === "ok" ? `已连接 · ${path}`
    : st === "scan" ? (t ? `正在连接 · ${path}` : "正在查找显示器…")
    : st === "err" ? `连接失败 · ${lastError || "无应答"}`
    : "未找到 · 点名称重新查找";
}
function setDevice(t, res) {
  CURRENT = t;
  $("#dev-name").textContent = t ? t.description : "未找到显示器";
  // 只显示软件版本 (0xC9); 硬件版本 (0xE0) 用户不要看。
  // 216pin 不支持 0xE0 且 0xC9 固定回 1 (见 docs/protocol-216pin.md), 那个 1 不代表真实版本,
  // 所以读不到硬件版本的机型整行不显示, 免得摆出一个误导人的数。
  const v = res && res.versions;
  $("#dev-fw").innerHTML = v && v.hw != null && v.sw != null ? `显示器固件 · 软件版本 ${v.sw}` : "&nbsp;";
  renderStatus();
}
let refreshing = false;
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    app.classList.remove("screen-on");
    $("#dev-name").dataset.scanText = "正在查找显示器";
    setLink("scan");
    CURRENT = null;
    $("#dev-name").textContent = "正在查找…";
    $("#dev-fw").innerHTML = "&nbsp;";
    renderStatus();
    let d;
    try { d = await bridge().discover_targets(); } catch (e) { d = { targets: [], errors: [String(e)] }; }
    TARGETS = (d && d.targets) || [];
    if (!META) applyModel(await bridge().protocol_meta());
    if (!TARGETS.length) {
      setDevice(null, null);
      log("查找显示器", "", false, ((d && d.errors) || []).slice(0, 2).join(" / ") || "没有能应答的目标");
      setLink("none");
      return;
    }
    await selectTarget(TARGETS[0].id);
  } finally { refreshing = false; }
}
async function selectTarget(id) {
  const t = TARGETS.find((x) => x.id === id) || TARGETS[0];
  if (!t || holding) return;            // 长按中不许换目标 (后端正按着键)
  app.classList.remove("screen-on");
  $("#dev-name").dataset.scanText = "正在连接";
  setLink("scan");
  setDevice(t, null);
  const r = await io(`连接 ${t.description}`, () => bridge().connect_target(t), {
    island: false, note: (x) => (x.versions ? `硬件 ${x.versions.hw == null ? "--" : x.versions.hw} · 软件 ${x.versions.sw == null ? "--" : x.versions.sw}` : ""),
  });
  if (!r.ok) { lastError = r.error || ""; setLink("err"); islandResult(false, "连接失败", r.error); return; }
  if (r.meta) applyModel(r.meta);       // 目标的机型 = 界面
  app.dataset.link = "ok";
  setDevice(t, r);
  island(`<span class="is-ico is-check">${SVG.check}</span>已连接<span class="is-sub">${esc(modelLabel(r.model || (r.meta && r.meta.model)))}</span>`, 2200);
  app.classList.add("screen-on");
  await readParam("brightness");
  await readParam("contrast");
  if (!hasFeature("choices")) return;
  await readDiscrete("colortemp");
  await readDiscrete("gamma");
}

// ---------------------------------------------------------------- 键盘
// 键盘操作时才显示焦点框, 鼠标点完不留蓝框
document.addEventListener("keydown", (e) => { if (e.key === "Tab") app.classList.add("kb"); }, true);
document.addEventListener("pointerdown", () => app.classList.remove("kb"), true);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (alertResolve) { alertResolve(null); return; }
    if (openKind) { closeExpand(); return; }
    if (sheet.classList.contains("open")) { closeSheet(); return; }
    if (menu.classList.contains("open")) { closeMenu(); return; }
  }
  if (alertResolve || openKind) return;
  if (e.target.closest && e.target.closest("input, .slider")) return;
  const k = { m: "menu", M: "menu", ArrowLeft: "left", ArrowRight: "right", Escape: "exit" }[e.key];
  if (k && !e.ctrlKey && !e.altKey) { e.preventDefault(); pressKey(k); }
});

// ---------------------------------------------------------------- 外观 / 窗口 / 版本
$("#skin").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("ddc-appearance", next); } catch (e) {}
});
$("#win-min").addEventListener("click", () => bridge().minimize_window());
$("#win-close").addEventListener("click", () => bridge().close_window());
$$(".resz").forEach((el) => el.addEventListener("pointerdown", (e) => { e.preventDefault(); bridge().start_resize(Number(el.dataset.ht)); }));
if (navigator.userAgent.indexOf("QtWebEngine") >= 0) {
  $(".titlebar").addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target.closest(".pywebview-no-drag")) return;
    e.preventDefault(); bridge().start_resize(2);
  });
}
let UPDATE = null;
async function checkUpdate(manual) {
  const label = $("#ver-label");
  if (manual) label.textContent = "检查中…";
  let r;
  try { r = await bridge().check_update(); } catch (e) { r = { error: "检查失败" }; }
  UPDATE = r;
  if (r.current) label.textContent = "v" + r.current;
  label.classList.toggle("update", !!r.has_update);
  label.title = r.error ? r.error + " (点击重试)"
    : r.has_update ? `有新版本, 落后 ${r.behind_by} 个提交 · 点击打开仓库`
    : `已是最新版 v${r.current} (点击重新检查)`;
  if (manual) islandResult(!r.error, r.error ? "检查更新" : r.has_update ? "有新版本" : "已是最新版", r.error);
  else if (r.has_update) island(`<span class="is-ico"><i class="is-dot" style="background:#0a84ff;box-shadow:0 0 6px #0a84ff"></i></span>有新版本<span class="is-sub">落后 ${r.behind_by} 个提交</span>`, 4000);
}
$("#ver-label").addEventListener("click", () => { if (UPDATE && UPDATE.has_update) bridge().open_repo(); else checkUpdate(true); });
async function initVersion() {
  // 先显示本机版本 (不联网), 再联网查更新 —— 产线机器多半没网, 失败只改悬停提示
  try { const v = await bridge().app_version(); if (v && v.version) $("#ver-label").textContent = "v" + v.version; } catch (e) {}
  await checkUpdate(false);
}

// ---------------------------------------------------------------- 启动
let BOOTED = false;
function connectBackend() { if (BOOTED) return; BOOTED = true; initModels().then(refresh).then(initVersion, initVersion); }
logEmpty();
SLIDERS.brightness.set(0, true);
SLIDERS.contrast.set(0, true);
$("#gm-mini path").setAttribute("d", curvePath(2.2, 40, 26));
renderPicture();

requestAnimationFrame(() => setTimeout(() => {
  app.dataset.phase = "live";
  islandIdle();
  if (bridgeReady()) connectBackend();
  else {
    // 事件 + 轮询双保险 (事件可能早于监听就发过了); 只有压根不在 pywebview 里 (浏览器直接打开) 才走演示数据,
    // 慢机器上 pywebview 迟迟没就绪也继续等, 不能掉进演示数据冒充真显示器。
    window.addEventListener("pywebviewready", () => { if (bridgeReady()) connectBackend(); });
    const t0 = Date.now(), demoAfter = location.protocol === "file:" ? 500 : 2500;
    const poll = setInterval(() => {
      if (BOOTED) { clearInterval(poll); return; }
      if (bridgeReady()) { clearInterval(poll); connectBackend(); }
      else if (!window.pywebview && Date.now() - t0 > demoAfter) { clearInterval(poll); connectBackend(); }
    }, 150);
  }
}, 120));
