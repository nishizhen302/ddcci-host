// DDC 控制台 v3 · 「数字孪生」
// 舞台中间是一台显示器的实时模型: 亮度/对比度/色温/Gamma 改了它就跟着变,
// 每条 DDC 命令都画成一颗沿线跑进显示器的数据包, 应答再跑回来。
// 后端接口与 ui/nanwei 完全一致 (window.pywebview.api.*), 浏览器直接打开则跑演示数据。

const $ = (s, el) => (el || document).querySelector(s);
const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
const app = $("#app");
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
  ok: true,
  colortemp: [{ label: "6500K", value: 0x08 }, { label: "9300K", value: 0x06 }, { label: "User", value: 0x05 }],
  gamma: Array.from({ length: 7 }, (_, i) => ({ label: `γ${i + 1}`, value: 0x06 + i })),
  ops: { brightness: 0x10, contrast: 0x12, colortemp: 0x14, gamma: 0x72 },
};
const KEY_CODE = { menu: 0x01, left: 0x02, right: 0x03, exit: 0x05, ok: 0x04 };
const demoBridge = {
  _v: { 0x10: [64, 100], 0x12: [72, 100], 0x14: [0x06, 0x0d], 0x72: [0x08, 0x0c] },
  async _lag(a, b) { await sleep((a || 70) + Math.random() * ((b || 150) - (a || 70))); },
  async discover_targets() {
    await sleep(900);
    return { ok: true, errors: [], targets: [
      { id: "rawusb:0x5E:0", backend: "rawusb", address: "0x5E", mon_id: 0, description: "JRD UC1190_DVI", recommended: true },
      { id: "gpu:0x5E:0", backend: "gpu", address: "0x5E", mon_id: 0, description: "JRD UC1190_DVI", recommended: false },
      { id: "gpu:0x6E:1", backend: "gpu", address: "0x6E", mon_id: 1, description: "DEL U2412M", recommended: false },
    ] };
  },
  async connect_target(t) {
    await this._lag(200, 320);
    return { ok: true, backend: t.backend, address: t.address, mon_id: t.mon_id, description: t.description, versions: { hw: 12, sw: 31 } };
  },
  async protocol_meta() { return DEMO_META; },
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
  async press_key(name) { await this._lag(); return { ok: true, tx: demoFrame([0xC0, 0x96, KEY_CODE[name] || 0, 0x00]) }; },
  async press_key_raw(v) { await this._lag(); return { ok: true, tx: demoFrame([0xC0, 0x96, Number(v), 0x00]) }; },
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
const bridgeReady = () => !!(window.pywebview && window.pywebview.api);
const bridge = () => (bridgeReady() ? window.pywebview.api : demoBridge);

// ---------------------------------------------------------------- 状态
let META = null;
let TARGETS = [];
let CURRENT = null;
const VAL = { brightness: 50, contrast: 50, ctIndex: 0, gIndex: 2 };
const MAX = { brightness: 100, contrast: 100 };

// ---------------------------------------------------------------- 布局
// 显示器尺寸跟着舞台走: 宽度受舞台宽和高双重约束, 整组(显示器+支架+按键台)垂直居中偏下。
const stage = $("#stage");
const twin = $("#twin");
let CABLE_LEN = 0;
function layout() {
  const sw = stage.clientWidth, sh = stage.clientHeight;
  const tgt = $("#target");
  const top = tgt.offsetTop + tgt.offsetHeight + 18;   // 左上角目标信息下方
  const bottom = 18;
  const avail = sh - top - bottom;
  // 先按宽度给一个上限, 量出整组(显示器+支架+按键台)真实高度, 超了就按比例缩
  let w = Math.max(260, Math.min(sw - 150, 640));
  const setW = (v) => twin.style.setProperty("--w", Math.round(v) + "px");
  setW(w);
  const deckH = $("#deck").offsetHeight + 24;          // 按键台不随 w 缩放
  const scalable = twin.offsetHeight - deckH;
  if (scalable + deckH > avail) {
    w = Math.max(260, w * (avail - deckH) / scalable);
    setW(w);
  }
  const h = twin.offsetHeight;
  const ty = Math.round(top + Math.max(0, (avail - h) / 2));
  twin.style.setProperty("--ty", ty + "px");

  // 地面线 = 底座位置; 屏幕光斑投在显示器后墙 + 桌面
  const footY = ty + $(".foot", twin).offsetTop + 4;
  stage.querySelector(".backdrop").style.setProperty("--floor-y", Math.round(footY / sh * 100) + "%");
  const spill = $("#spill");
  spill.style.left = (sw / 2 - w * 0.75) + "px";
  spill.style.width = (w * 1.5) + "px";
  spill.style.top = (footY - w * 0.07) + "px";
  spill.style.height = (w * 0.22) + "px";

  // DDC 线: 主机图标放在桌面高度, 线沿桌面接进底座左端
  const hostEl = $("#host");
  hostEl.style.bottom = "auto";
  hostEl.style.top = Math.round(footY - hostEl.offsetHeight + 19) + "px";
  const host = $("#host .h-ico");
  const hr = host.getBoundingClientRect(), sr = stage.getBoundingClientRect();
  const x0 = hr.right - sr.left + 1, y0 = hr.top - sr.top + hr.height / 2;
  const x1 = sw / 2 - w * 0.13, y1 = footY;
  const d = `M${x0} ${y0} C ${x0 + 46} ${y0 + 9}, ${x1 - 70} ${y1 + 7}, ${x1} ${y1}`;
  $("#cable-line").setAttribute("d", d);
  $("#cable-under").setAttribute("d", d);
  CABLE_LEN = $("#cable-line").getTotalLength();
}

// ---------------------------------------------------------------- 屏幕
// 色温相对 6500K 的乘色, 与色票颜色同源
function kelvinOf(label) {
  const m = /(\d{4,5})\s*K/i.exec(label || "");
  return m ? Number(m[1]) : null;
}
function tintFor(label) {
  const k = kelvinOf(label);
  if (k == null) return "#fff6ec";                      // User: 示意为略暖
  if (k >= 9000) return "#e4ebff";
  if (k >= 7300) return "#eef2ff";
  if (k <= 5500) return "#ffe8cf";
  return "#ffffff";
}
function swatchFill(label) {
  const k = kelvinOf(label);
  if (k == null) return "conic-gradient(from 200deg, #ff8a80, #ffd180, #ccff90, #80d8ff, #b388ff, #ff8a80)";
  const c = tintFor(label);
  return `radial-gradient(circle at 35% 30%, #ffffff, ${c} 70%)`;
}
const GAMMAS = [1.8, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0];   // 示意值: 只用来画曲线和预览, 不代表固件真实曲线
function gammaOf(i) { return GAMMAS[clamp(i, 0, GAMMAS.length - 1)] || 2.2; }

function renderPicture() {
  const b = VAL.brightness / (MAX.brightness || 100);
  const c = VAL.contrast / (MAX.contrast || 100);
  const pic = $("#pic");
  pic.style.filter = `url(#gammaF) brightness(${(0.3 + 0.85 * b).toFixed(3)}) contrast(${(0.55 + 0.9 * c).toFixed(3)})`;
  const ex = (gammaOf(VAL.gIndex) / 2.2).toFixed(3);
  ["gR", "gG", "gB"].forEach((id) => document.getElementById(id).setAttribute("exponent", ex));
  const ct = META && META.colortemp[VAL.ctIndex];
  const tint = tintFor(ct && ct.label);
  $("#tint").style.background = tint;
  // 屏幕的光: 夕阳暖色 × 色温, 强度跟亮度
  const k = kelvinOf(ct && ct.label);
  const glow = k && k >= 9000 ? "#8fa8ff" : k == null ? "#ff9f6b" : "#ff9a62";
  stage.style.setProperty("--glow", glow);
  twin.style.setProperty("--glow", glow);
  const on = app.classList.contains("screen-on");
  $("#halo").style.opacity = on ? (0.1 + 0.45 * b).toFixed(3) : 0;
  $("#spill").style.opacity = on ? (0.08 + 0.4 * b).toFixed(3) : 0;
}
function buildRamp() {
  const ramp = $("#ramp");
  for (let i = 0; i < 16; i++) {
    const v = Math.round(i * 255 / 15);
    const el = document.createElement("i");
    el.style.background = `rgb(${v},${v},${v})`;
    ramp.appendChild(el);
  }
}

// ---------------------------------------------------------------- 数据包
// 沿 DDC 线跑一颗光点。dir: "tx" 主机→显示器, "rx" 显示器→主机, "err" 跑到一半散掉。
const packetLayer = $("#packets");
let lastPacketAt = 0;
function packet(dir, ms) {
  return new Promise((resolve) => {
    if (!CABLE_LEN) { resolve(); return; }
    const path = $("#cable-line");
    const NS = "http://www.w3.org/2000/svg";
    const g = document.createElementNS(NS, "g");
    const glow = document.createElementNS(NS, "circle");
    glow.setAttribute("r", "10");
    glow.setAttribute("fill", `url(#pk-${dir})`);
    const core = document.createElementNS(NS, "circle");
    core.setAttribute("r", "2.2");
    core.setAttribute("fill", dir === "rx" ? "#eafff0" : dir === "err" ? "#fff0ee" : "#ffffff");
    g.appendChild(glow); g.appendChild(core);
    packetLayer.appendChild(g);
    const dur = ms || 520;
    const t0 = performance.now();
    const stopAt = dir === "err" ? 0.55 : 1;
    function frame(now) {
      let t = clamp((now - t0) / dur, 0, 1);
      const e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;   // easeInOutQuad
      const along = dir === "rx" ? 1 - e : e * stopAt;
      const p = path.getPointAtLength(along * CABLE_LEN);
      g.setAttribute("transform", `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`);
      if (dir === "err" && t > 0.7) g.style.opacity = String(1 - (t - 0.7) / 0.3);
      if (t < 1) requestAnimationFrame(frame);
      else {
        g.style.transition = "opacity .25s"; g.style.opacity = "0";
        setTimeout(() => g.remove(), 260);
        resolve();
      }
    }
    requestAnimationFrame(frame);
  });
}
function blinkLed() {
  const led = $("#led");
  led.classList.remove("blink"); void led.offsetWidth; led.classList.add("blink");
}
let tagTimer = 0;
function showTag(kind, title, frame) {
  const tag = $("#frame-tag");
  const host = $("#host").getBoundingClientRect(), sr = stage.getBoundingClientRect();
  tag.className = "frame-tag " + kind;
  tag.innerHTML = `<b>${title}</b>${frame || ""}`;
  tag.style.left = (host.left - sr.left) + "px";
  tag.style.top = (host.top - sr.top - 34) + "px";
  void tag.offsetWidth;
  tag.classList.add("show");
  clearTimeout(tagTimer);
  tagTimer = setTimeout(() => tag.classList.remove("show"), 1600);
}

// 一次 DDC 往返: 发包动画与后端调用并行, 应答回来且去程到站后再放回程包。
// quiet = 拖滑尺时的中间帧, 只放动画不写日志, 且限流避免满线都是光点。
async function io(label, call, opts) {
  opts = opts || {};
  const now = performance.now();
  const animate = !opts.quiet || now - lastPacketAt > 140;
  let txDone = Promise.resolve();
  if (animate) {
    lastPacketAt = now;
    $("#host").classList.add("tx");
    setLamp("tx");
    txDone = packet("tx", opts.quiet ? 380 : 520).then(blinkLed);
  }
  let res;
  try { res = await call(); } catch (e) { res = { ok: false, error: String(e && e.message || e) }; }
  if (!res) res = { ok: false, error: "无返回" };
  await txDone;
  $("#host").classList.remove("tx");
  if (animate) packet(res.ok ? "rx" : "err", opts.quiet ? 300 : 440);
  if (!opts.quiet) {
    const note = res.ok ? (opts.note ? opts.note(res) : "") : (res.error || "无应答");
    log(label, res.tx, res.ok, note);
    if (opts.tag !== false) showTag(res.ok ? "rx" : "err", label + (note ? " " + note : ""), res.tx || "");
  } else {
    setLamp(res.ok ? "ok" : "err");
  }
  return res;
}

// ---------------------------------------------------------------- 日志
let LOG_N = 0;
function setLamp(kind) { $("#lamp").className = "lamp " + (kind || ""); }
function log(label, tx, ok, note) {
  const box = $("#log");
  const empty = $(".empty", box);
  if (empty) empty.remove();
  const time = new Date().toTimeString().slice(0, 8);
  const row = document.createElement("div");
  row.className = "row" + (ok ? "" : " bad");
  row.innerHTML =
    `<time>${time}</time><span class="dir ${ok ? "ok" : "err"}">${ok ? "✓" : "✕"}</span>` +
    `<div class="what"><b>${label}${note ? `<em>${note}</em>` : ""}</b>${tx ? `<code>${tx}</code>` : ""}</div>`;
  box.insertBefore(row, box.firstChild);
  while (box.children.length > 200) box.removeChild(box.lastChild);
  LOG_N++;
  $("#log-count").textContent = LOG_N + " 条";
  $("#last-label").textContent = label + (note ? " " + note : "");
  $("#last-frame").textContent = tx || "";
  setLamp(ok ? "ok" : "err");
}
function logEmpty() { $("#log").innerHTML = '<div class="empty">还没有通信记录</div>'; }

// ---------------------------------------------------------------- 刻度滑尺
// 41 根刻度, 已到达的点亮; 拇指附近的刻度按高斯放大, 像放大镜扫过尺子。
const TICKS = 41;
function makeScale(id, onInput, onChange) {
  const el = $("#" + id);
  el.innerHTML = `<div class="tks">${'<i class="tk"></i>'.repeat(TICKS)}</div><div class="th"></div><div class="ends"><span>0</span><span class="mx">100</span></div>`;
  const ticks = $$(".tk", el), th = $(".th", el);
  const api = {
    value: 0,
    set(v, silent) {
      const max = MAX[id] || 100;
      v = clamp(Math.round(v), 0, max);
      api.value = v;
      const f = v / max;
      th.style.left = (f * 100) + "%";
      const pos = f * (TICKS - 1);
      ticks.forEach((t, i) => {
        const d = i - pos;
        t.style.height = (8 + 13 * Math.exp(-(d * d) / 3.2)).toFixed(1) + "px";
        t.classList.toggle("on", i <= pos + 0.001);
      });
      $("#" + id + "-out").textContent = String(v);
      $(".mx", el).textContent = String(max);
      if (!silent) onInput(v);
    },
  };
  const fromX = (x) => {
    const r = el.getBoundingClientRect();
    return clamp((x - r.left) / r.width, 0, 1) * (MAX[id] || 100);
  };
  el.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    el.setPointerCapture(e.pointerId);
    el.classList.add("drag");
    api.set(fromX(e.clientX));
    const move = (ev) => api.set(fromX(ev.clientX));
    const up = () => {
      el.classList.remove("drag");
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      onChange(api.value);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  });
  let wheelTimer = 0;
  const bump = (d) => {
    api.set(api.value + d);
    clearTimeout(wheelTimer);
    wheelTimer = setTimeout(() => onChange(api.value), 320);
  };
  el.addEventListener("wheel", (e) => { e.preventDefault(); bump(e.deltaY < 0 ? 1 : -1); }, { passive: false });
  el.addEventListener("keydown", (e) => {
    const step = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 10, PageDown: -10 }[e.key];
    if (step) { e.preventDefault(); e.stopPropagation(); bump(step); }
  });
  $$(".nudge", el.closest(".grp")).forEach((b) => b.addEventListener("click", () => bump(Number(b.dataset.d))));
  return api;
}

const SCALES = {};
let lastSentAt = 0;
["brightness", "contrast"].forEach((id) => {
  const name = id === "brightness" ? "亮度" : "对比度";
  SCALES[id] = makeScale(id,
    (v) => {                                           // 拖动中: 画面实时变, 限流 120ms 发给显示器
      VAL[id] = v; renderPicture();
      const now = Date.now();
      if (META && now - lastSentAt >= 120) {
        lastSentAt = now;
        io(name, () => bridge().set_param(META.ops[id], v), { quiet: true });
      }
    },
    async (v) => {                                     // 松手: 发最终值并回读确认
      if (!META) return;
      const r = await io(`写${name} ${v}`, () => bridge().set_param(META.ops[id], v));
      if (r.ok) await readParam(id);
    });
});

async function readParam(id) {
  const name = id === "brightness" ? "亮度" : "对比度";
  const r = await io(`读${name}`, () => bridge().get_param(META.ops[id]),
    { note: (x) => `→ ${x.current}/${x.maximum}`, tag: false });
  if (r.ok) {
    if (r.maximum) MAX[id] = r.maximum;
    VAL[id] = r.current;
    SCALES[id].set(r.current, true);
    renderPicture();
  } else {
    $("#" + id + "-out").textContent = "--";
  }
}

// ---------------------------------------------------------------- 色温 / Gamma
function buildColortemp() {
  const box = $("#colortemp-seg");
  box.innerHTML = "";
  META.colortemp.forEach((opt, i) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "sw"; b.dataset.i = i;
    b.innerHTML = `<i style="background:${swatchFill(opt.label)}"></i><span>${opt.label === "User" ? "用户" : opt.label}</span>`;
    b.addEventListener("click", async () => {
      markColortemp(i);
      const r = await io(`色温 ${opt.label}`, () => bridge().set_param(META.ops.colortemp, opt.value));
      if (r.ok) readDiscrete("colortemp");
    });
    box.appendChild(b);
  });
}
function markColortemp(i) {
  VAL.ctIndex = i;
  $$("#colortemp-seg .sw").forEach((b) => b.classList.toggle("active", Number(b.dataset.i) === i));
  const opt = META.colortemp[i];
  $("#colortemp-out").textContent = opt ? (opt.label === "User" ? "用户" : opt.label) : "--";
  renderPicture();
}

// Gamma 曲线: y = x^g, 选中时从旧曲线补间到新曲线
const CW = 260, CH = 92;
function curvePath(g, closed) {
  let d = "";
  for (let i = 0; i <= 48; i++) {
    const x = i / 48, y = Math.pow(x, g);
    d += (i ? " L" : "M") + (x * CW).toFixed(1) + " " + (CH - y * CH).toFixed(1);
  }
  return closed ? d + ` L${CW} ${CH} L0 ${CH} Z` : d;
}
let curveG = 2.2, curveAnim = 0;
function drawCurve(target) {
  cancelAnimationFrame(curveAnim);
  const from = curveG, t0 = performance.now();
  const step = (now) => {
    const t = clamp((now - t0) / 420, 0, 1), e = 1 - Math.pow(1 - t, 3);
    curveG = from + (target - from) * e;
    $("#curve-line").setAttribute("d", curvePath(curveG));
    $("#curve-area").setAttribute("d", curvePath(curveG, true));
    if (t < 1) curveAnim = requestAnimationFrame(step);
  };
  curveAnim = requestAnimationFrame(step);
}
function buildGamma() {
  const grid = $("#curve .grid");
  let g = "";
  for (let i = 1; i < 4; i++) {
    g += `<line x1="${CW * i / 4}" y1="0" x2="${CW * i / 4}" y2="${CH}"/><line x1="0" y1="${CH * i / 4}" x2="${CW}" y2="${CH * i / 4}"/>`;
  }
  grid.innerHTML = g;
  const box = $("#gamma-seg");
  box.innerHTML = "";
  META.gamma.forEach((opt, i) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "chip"; b.dataset.i = i;
    b.textContent = String(i + 1);
    b.title = opt.label;
    b.addEventListener("mouseenter", () => {
      $("#curve-ghost").setAttribute("d", curvePath(gammaOf(i)));
      $("#curve").classList.add("peek");
    });
    b.addEventListener("mouseleave", () => $("#curve").classList.remove("peek"));
    b.addEventListener("click", async () => {
      markGamma(i);
      const r = await io(`Gamma ${opt.label}`, () => bridge().set_param(META.ops.gamma, opt.value));
      if (r.ok) readDiscrete("gamma");
    });
    box.appendChild(b);
  });
}
function markGamma(i) {
  VAL.gIndex = i;
  $$("#gamma-seg .chip").forEach((b) => b.classList.toggle("active", Number(b.dataset.i) === i));
  const opt = META.gamma[i];
  $("#gamma-out").textContent = opt ? opt.label : "--";
  drawCurve(gammaOf(i));
  renderPicture();
}
async function readDiscrete(kind) {
  const list = META[kind];
  const r = await io(kind === "gamma" ? "读 Gamma" : "读色温", () => bridge().get_param(META.ops[kind]), {
    tag: false,
    note: (x) => {
      const hit = list.find((o) => Number(o.value) === Number(x.current));
      return "→ " + (hit ? hit.label : "0x" + hex(x.current));
    },
  });
  if (!r.ok) return;
  const i = list.findIndex((o) => Number(o.value) === Number(r.current));
  if (i < 0) return;
  if (kind === "gamma") markGamma(i); else markColortemp(i);
}

// ---------------------------------------------------------------- 目标
const ICONS = {
  rawusb: '<svg viewBox="0 0 24 24"><path d="M12 3v13"/><path d="M12 16a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z"/><path d="M12 12l-4.5-3V6.5"/><circle cx="7.5" cy="5.5" r="1.4"/><path d="M12 10l4.5-2.5V5h-2v-2h2"/><path d="M9.5 3h5"/></svg>',
  gpu: '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="11" rx="2"/><circle cx="9" cy="11.5" r="2.6"/><path d="M14.5 9.5h3.5M14.5 13.5h3.5M6 17v2.5M10 17v2.5M14 17v2.5"/></svg>',
  dxva2: '<svg viewBox="0 0 24 24"><rect x="3" y="4.5" width="18" height="12" rx="2"/><path d="M9 20h6M12 16.5V20"/></svg>',
};
const HOST_NAME = { rawusb: "USB 小板", gpu: "显卡 I²C", dxva2: "系统 DDC/CI" };
const PATH_NAME = { rawusb: "USB 小板", gpu: "显卡通道", dxva2: "系统通道" };
const CHECK = '<svg class="check" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';

function setLink(state, text) {
  app.dataset.link = state;
  $("#conn").textContent = text;
}
function renderTargetMenu() {
  const menu = $("#target-menu");
  menu.innerHTML = "";
  TARGETS.forEach((t) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "opt" + (CURRENT && CURRENT.id === t.id ? " active" : "");
    b.title = t.id;
    b.innerHTML =
      `<span class="o-ico">${ICONS[t.backend] || ICONS.dxva2}</span>` +
      `<span class="o-txt"><b>${t.description}</b><small>${PATH_NAME[t.backend] || t.backend} · ${t.address}</small></span>` +
      (t.recommended ? "<em>推荐</em>" : "") + CHECK;
    b.addEventListener("click", () => { closeMenu(); selectTarget(t.id); });
    menu.appendChild(b);
  });
  const foot = document.createElement("div");
  foot.className = "t-foot";
  foot.innerHTML = `<p>${TARGETS.length ? "地址 0x5E / 0x6E 自动探测。USB 小板和显卡可能指向同一台显示器, 默认优先 USB 小板。" : "没有找到能应答的显示器。检查线缆、地址和显示器的 DDC/CI 开关。"}</p><button type="button">重新扫描</button>`;
  $("button", foot).addEventListener("click", () => { closeMenu(); refresh(); });
  menu.appendChild(foot);
}
function closeMenu() { $("#target").classList.remove("open"); }
function setTargetInfo(t, res) {
  CURRENT = t;
  $("#target-name").textContent = t ? t.description : "未发现显示器";
  $("#m-path").textContent = t ? (PATH_NAME[t.backend] || t.backend) : "—";
  $("#m-addr").textContent = t ? t.address : "0x--";
  const v = res && res.versions;
  $("#m-ver").textContent = v ? `HW v${v.hw == null ? "--" : v.hw} · SW v${v.sw == null ? "--" : v.sw}` : "HW v-- · SW v--";
  const be = t ? t.backend : "dxva2";
  $("#host-ico").innerHTML = ICONS[be] || ICONS.dxva2;
  $("#host-label").textContent = HOST_NAME[be] || "主机";
  const brand = t ? (t.description.split(/\s+/)[0] || "DDC") : "DDC";
  $("#chin-logo").textContent = brand.slice(0, 8).toUpperCase();
  renderTargetMenu();
  requestAnimationFrame(layout);
}

// ---------------------------------------------------------------- 连接
let refreshing = false;
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    app.classList.remove("screen-on");
    renderPicture();
    setLink("scan", "正在扫描显示器…");
    $("#last-label").textContent = "扫描中";
    setLamp("tx");
    let disc;
    try { disc = await bridge().discover_targets(); } catch (e) { disc = { targets: [], errors: [String(e)] }; }
    TARGETS = (disc && disc.targets) || [];
    if (!META) {
      META = await bridge().protocol_meta();
      buildColortemp();
      buildGamma();
    }
    if (!TARGETS.length) {
      setTargetInfo(null, null);
      setLink("none", "未发现显示器 · 点名字重新扫描");
      log("扫描", "", false, ((disc && disc.errors) || []).slice(0, 2).join(" / ") || "没有能应答的目标");
      app.dataset.phase = "live";
      return;
    }
    await selectTarget(TARGETS[0].id);
  } finally {
    refreshing = false;
  }
}

async function selectTarget(id) {
  const t = TARGETS.find((x) => x.id === id) || TARGETS[0];
  if (!t) return;
  app.classList.remove("screen-on");
  setLink("scan", "正在连接…");
  setTargetInfo(t, null);
  const r = await io(`连接 ${PATH_NAME[t.backend] || t.backend} ${t.address}`, () => bridge().connect_target(t), {
    note: (x) => x.versions ? `HW v${x.versions.hw} · SW v${x.versions.sw}` : "",
  });
  if (!r.ok) {
    setLink("err", "连接失败 · " + (r.error || "无应答"));
    app.dataset.phase = "live";
    return;
  }
  setTargetInfo(t, r);
  setLink("ok", "已连接");
  app.dataset.phase = "live";
  // 显示器"开机": 屏幕从中线展开, 再把四个参数依次读上来
  app.classList.add("screen-on");
  renderPicture();
  await readParam("brightness");
  await readParam("contrast");
  await readDiscrete("colortemp");
  await readDiscrete("gamma");
}

// ---------------------------------------------------------------- OSD 按键
const KEY_LABEL = { menu: "MENU", left: "LEFT", right: "RIGHT", exit: "EXIT", ok: "OK" };
function flashKey(name) {
  const k = $(`.deck .k[data-key="${name}"]`);
  if (!k) return;
  k.classList.remove("hit"); void k.offsetWidth; k.classList.add("hit");
  setTimeout(() => k.classList.remove("hit"), 420);
}
function pressKey(name) {
  if (app.dataset.link !== "ok") return;
  flashKey(name);
  io(`按键 ${KEY_LABEL[name]}`, () => bridge().press_key(name));
}
// 彩蛋: 在屏幕上滚滚轮 = 调亮度
$("#screen").addEventListener("wheel", (e) => {
  if (app.dataset.link !== "ok") return;
  e.preventDefault();
  $("#brightness").dispatchEvent(new WheelEvent("wheel", { deltaY: e.deltaY, cancelable: true }));
}, { passive: false });
$("#screen").title = "滚轮调亮度";
$$(".deck .k[data-key]").forEach((k) => k.addEventListener("click", () => pressKey(k.dataset.key)));

// 宏: 后端按 0.35s 间隔发完整序列后才返回; 前端按同样节拍点亮进度点并闪对应的键
const KEY_GAP = 350;
$$(".deck .macro").forEach((btn) => {
  btn.addEventListener("click", async () => {
    if (app.dataset.link !== "ok" || btn.classList.contains("run")) return;
    const seq = btn.dataset.seq.split(",");
    const dots = $(".seq", btn);
    dots.innerHTML = seq.map(() => "<i></i>").join("");
    btn.classList.remove("done", "fail");
    btn.classList.add("run");
    const title = $("span", btn).textContent;
    const call = io(title, () => bridge()[btn.dataset.api](), { note: () => "序列已发完, 看屏幕" });
    const ds = $$("i", dots);
    for (let i = 0; i < seq.length; i++) {
      ds.forEach((d, j) => { d.className = j < i ? "done" : j === i ? "now" : ""; });
      flashKey(seq[i]);
      blinkLed();
      await sleep(KEY_GAP);
    }
    ds.forEach((d) => { d.className = "done"; });
    const r = await call;
    btn.classList.remove("run");
    btn.classList.add(r.ok ? "done" : "fail");
    setTimeout(() => btn.classList.remove("done", "fail"), 1800);
  });
});

// 原始键值: 试 PDF 没列出的键 (OK = 04 就是这么试出来的)
async function sendRaw() {
  const input = $("#raw-key");
  const text = (input.value || "").trim().replace(/^0x/i, "");
  const v = /^[0-9a-f]{1,2}$/i.test(text) ? parseInt(text, 16) : NaN;
  if (!(v >= 0 && v <= 255)) {
    input.classList.add("bad");
    log("键值", "", false, `“${input.value}” 不是 00~FF`);
    return;
  }
  input.classList.remove("bad");
  input.value = hex(v);
  if (app.dataset.link !== "ok") return;
  io(`键值 0x${hex(v)}`, () => bridge().press_key_raw(v));
}
$("#raw-key-send").addEventListener("click", sendRaw);
$("#raw-key").addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") sendRaw(); });
$("#raw-key").addEventListener("input", (e) => e.target.classList.remove("bad"));

// 键盘: M / ← / → / Esc 直接按显示器的键 (焦点在输入框或滑尺上时不抢)
document.addEventListener("keydown", (e) => {
  if (e.target.closest && e.target.closest("input, .scale")) return;
  if (e.key === "Escape" && ($("#target").classList.contains("open") || $("#console").classList.contains("open"))) {
    closeMenu(); $("#console").classList.remove("open"); return;
  }
  const map = { m: "menu", M: "menu", ArrowLeft: "left", ArrowRight: "right", Escape: "exit" };
  if (map[e.key] && !e.ctrlKey && !e.altKey) { e.preventDefault(); pressKey(map[e.key]); }
});

// ---------------------------------------------------------------- 目标菜单 / 日志抽屉
$("#target-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  if (!TARGETS.length && app.dataset.link !== "scan") { refresh(); return; }
  $("#target").classList.toggle("open");
});
document.addEventListener("click", (e) => { if (!e.target.closest("#target")) closeMenu(); });
$("#log-toggle").addEventListener("click", () => $("#console").classList.toggle("open"));
$("#log-clear").addEventListener("click", () => { LOG_N = 0; $("#log-count").textContent = "0 条"; logEmpty(); });
$("#log-copy").addEventListener("click", () => {
  const text = $$("#log .row").map((r) => r.innerText.replace(/\n+/g, "  ")).join("\n");
  const ta = document.createElement("textarea");
  ta.value = text; document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); } catch (e) {}
  ta.remove();
  const b = $("#log-copy"); b.textContent = "已复制"; setTimeout(() => { b.textContent = "复制"; }, 1200);
});

// ---------------------------------------------------------------- 主题 / 窗口 / 版本
$("#skin").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("ddc-theme", next); } catch (e) {}
});
$("#win-min").addEventListener("click", () => bridge().minimize_window());
$("#win-close").addEventListener("click", () => bridge().close_window());
$$(".resz").forEach((el) => el.addEventListener("pointerdown", (e) => { e.preventDefault(); bridge().start_resize(Number(el.dataset.ht)); }));
// Win7 (QtWebEngine) 不认 pywebview-drag-region, 手动走 HTCAPTION 系统移动循环
if (navigator.userAgent.indexOf("QtWebEngine") >= 0) {
  $(".top").addEventListener("pointerdown", (e) => {
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
}
$("#ver-label").addEventListener("click", () => { if (UPDATE && UPDATE.has_update) bridge().open_repo(); else checkUpdate(true); });
async function initVersion() {
  try { const v = await bridge().app_version(); if (v && v.version) $("#ver-label").textContent = "v" + v.version; } catch (e) {}
  checkUpdate(false);
}

// ---------------------------------------------------------------- 开机
// boot: 全黑 → intro: 背景亮起、显示器浮上来、线缆从主机画到底座 → live: 连上后屏幕点亮、检查器滑入
function drawCable() {
  const line = $("#cable-line");
  line.style.transition = "none";
  line.style.strokeDasharray = CABLE_LEN + " " + CABLE_LEN;
  line.style.strokeDashoffset = String(CABLE_LEN);
  void line.getBoundingClientRect();
  line.style.transition = "stroke-dashoffset 1s cubic-bezier(.65,0,.35,1)";
  line.style.strokeDashoffset = "0";
  setTimeout(() => { line.style.transition = ""; line.style.strokeDasharray = ""; line.style.strokeDashoffset = ""; }, 1050);
}
let BOOTED = false;
function connectBackend() {
  if (BOOTED) return;
  BOOTED = true;
  refresh().then(initVersion, initVersion);
}
buildRamp();
logEmpty();
SCALES.brightness.set(0, true);
SCALES.contrast.set(0, true);
$("#curve-line").setAttribute("d", curvePath(2.2));
$("#curve-area").setAttribute("d", curvePath(2.2, true));
setTargetInfo(null, null);
$("#target-name").textContent = "扫描中";
layout();
window.addEventListener("resize", layout);
requestAnimationFrame(() => {
  app.dataset.phase = "intro";
  setTimeout(drawCable, 380);
  if (bridgeReady()) setTimeout(connectBackend, 500);
  else {
    window.addEventListener("pywebviewready", connectBackend);
    // 纯浏览器打开 (样机预览) 很快回落演示数据; pywebview 环境给足注入时间
    setTimeout(() => { if (!bridgeReady()) connectBackend(); }, location.protocol === "file:" ? 700 : 2500);
  }
});
