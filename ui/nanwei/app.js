// 南微 DDCCI 控制台前端。
// 设计目标: 默认像一个小遥控器; 图像、色彩和日志收在更多设置里。

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

let META = null;
let TARGETS = [];
let CURRENT_TARGET = null;
let refreshing = false;

const DEMO_META = {
  ok: true,
  colortemp: [
    { label: "6500K", value: 0x08 },
    { label: "9300K", value: 0x06 },
    { label: "User", value: 0x05 },
  ],
  gamma: Array.from({ length: 7 }, (_, i) => ({ label: `γ${i + 1}`, value: 0x06 + i })),
  ops: { brightness: 0x10, contrast: 0x12, colortemp: 0x14, gamma: 0x72 },
};

const demoBridge = {
  _values: { 0x10: [64, 100], 0x12: [72, 100], 0x14: [0x06, 0x0d], 0x72: [0x08, 0x0c] },
  async discover_targets() {
    return {
      ok: true,
      targets: [
        { id: "rawusb:0x5E:0", backend: "rawusb", address: "0x5E", mon_id: 0,
          description: "Realtek USB ISP", recommended: true },
        { id: "gpu:0x5E:0", backend: "gpu", address: "0x5E", mon_id: 0,
          description: "NVIDIA display #0", recommended: false },
        { id: "gpu:0x6E:1", backend: "gpu", address: "0x6E", mon_id: 1,
          description: "NVIDIA display #1", recommended: false },
      ],
      errors: [],
    };
  },
  async connect_target(target) {
    return { ok: true, backend: target.backend, address: target.address, mon_id: target.mon_id,
      description: target.description, versions: { hw: 12, sw: 31 } };
  },
  async protocol_meta() { return DEMO_META; },
  async get_param(op) {
    const value = this._values[Number(op)] || [0, 100];
    return { ok: true, current: value[0], maximum: value[1], tx: `5E 51 82 01 ${hex(op)} --` };
  },
  async set_param(op, value) {
    const cur = this._values[Number(op)] || [0, 100];
    cur[0] = Number(value);
    this._values[Number(op)] = cur;
    return { ok: true, tx: `5E 51 84 03 ${hex(op)} 00 ${hex(value)} --` };
  },
  async press_key(name) { return { ok: true, tx: `5E 51 84 C0 96 ${name} 00 --` }; },
  async minimize_window() { return { ok: true }; },
  async close_window() { return { ok: true }; },
  async start_resize() { return { ok: true }; },
};

function bridge() {
  return (window.pywebview && window.pywebview.api) || demoBridge;
}

function hex(value) {
  return Number(value).toString(16).padStart(2, "0").toUpperCase();
}

function setConn(text, state = "idle") {
  $("#conn").textContent = text;
  $("#pulse").dataset.state = state;
}

function log(label, tx, ok = true, extra = "") {
  const box = $("#log");
  const row = document.createElement("p");
  const time = new Date().toTimeString().slice(0, 8);
  row.innerHTML =
    `<time>${time}</time><span class="${ok ? "ok" : "err"}">${label}${extra ? " " + extra : ""}</span>` +
    `<code>${tx || ""}</code>`;
  box.prepend(row);
  while (box.children.length > 80) box.removeChild(box.lastChild);
}

function applyTheme(theme) {
  const next = theme === "dark" ? "dark" : "light";
  document.body.dataset.theme = next;
  try { localStorage.setItem("nanwei-theme", next); } catch (e) {}
}

function initTheme() {
  let theme = "light";
  try { theme = localStorage.getItem("nanwei-theme") || "light"; } catch (e) {}
  applyTheme(theme);
}

function setTargetSummary(target, state) {
  CURRENT_TARGET = target;
  const name = target
    ? `${target.backend === "rawusb" ? "USB 小板" : "GPU"} · ${target.description} · ${target.address}`
    : "未发现可用目标";
  $("#target-name").textContent = name;
  $("#backend-chip").textContent = target ? target.backend : "none";
  $("#addr-chip").textContent = target ? `addr ${target.address}` : "addr --";
  const versions = state && state.versions;
  $("#version-chip").textContent = versions
    ? `HW v${versions.hw == null ? "--" : versions.hw} · SW v${versions.sw == null ? "--" : versions.sw}`
    : "HW v-- · SW v--";
}

function renderTargetMenu(targets) {
  const menu = $("#target-menu");
  menu.innerHTML = "";
  targets.forEach((target, index) => {
    const button = document.createElement("button");
    button.className = `target-option${index === 0 ? " active" : ""}`;
    button.type = "button";
    button.dataset.id = target.id;
    button.innerHTML =
      `<span><b>${target.recommended ? "自动推荐" : target.backend === "gpu" ? "显卡通道" : "控制路径"}</b>` +
      `<small>${target.backend} · ${target.description} · ${target.address}</small></span>` +
      `<em>${target.recommended ? "稳" : "可选"}</em>`;
    button.addEventListener("click", () => selectTarget(target.id));
    menu.appendChild(button);
  });
  const hint = document.createElement("p");
  hint.textContent = "地址 0x5E / 0x6E 自动探测。检测到 USB 与 GPU 可能指向同一台显示器时, 默认优先使用 USB 小板。";
  menu.appendChild(hint);
}

async function selectTarget(targetId) {
  const target = TARGETS.find((item) => item.id === targetId) || TARGETS[0];
  if (!target) return;
  $$(".target-option").forEach((button) => button.classList.toggle("active", button.dataset.id === target.id));
  $("#target-picker").open = false;
  setConn("连接中...", "idle");
  const result = await bridge().connect_target(target);
  if (!result.ok) {
    setConn(`连接失败: ${result.error || ""}`, "warn");
    log("连接失败", "", false, result.error || "");
    return;
  }
  setTargetSummary(target, result);
  setConn("已连接", "ok");
  log("切换目标", `${target.backend} · ${target.address} · ${target.description}`, true);
  await loadParams();
}

function syncMeter(input, value, max) {
  if (typeof max === "number" && max > 0) input.max = String(max);
  if (typeof value === "number") input.value = String(value);
  const current = Number(input.value || 0);
  const maximum = Number(input.max || 100) || 100;
  const pct = `${Math.max(0, Math.min(100, Math.round((current / maximum) * 100)))}%`;
  const fill = input.closest(".meter").querySelector("span");
  const out = $(`#${input.id}-out`);
  fill.style.setProperty("--value", pct);
  out.value = Number.isFinite(current) ? current : "--";
}

async function loadParam(inputId, op) {
  const input = $(`#${inputId}`);
  const result = await bridge().get_param(op);
  if (!result.ok) {
    syncMeter(input, 0, 100);
    $(`#${inputId}-out`).value = "--";
    log(`读${inputId}`, result.tx, false, result.error || "无应答");
    return;
  }
  syncMeter(input, result.current, result.maximum || 100);
  log(`读${inputId}`, result.tx, true, `→ ${result.current}/${result.maximum}`);
}

async function loadParams() {
  if (!META) META = await bridge().protocol_meta();
  await loadParam("brightness", META.ops.brightness);
  await loadParam("contrast", META.ops.contrast);
  await loadDiscrete("colortemp", META.ops.colortemp, META.colortemp);
  await loadDiscrete("gamma", META.ops.gamma, META.gamma);
}

async function loadDiscrete(kind, op, options) {
  const result = await bridge().get_param(op);
  if (result.ok) {
    markSeg(kind, result.current);
    log(`读${kind}`, result.tx, true, `→ ${result.current}/${result.maximum}`);
  } else {
    log(`读${kind}`, result.tx, false, result.error || "无应答");
  }
}

function markSeg(kind, value) {
  $$(`#${kind}-seg button`).forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.value) === Number(value));
  });
}

function buildSeg(id, options, op) {
  const box = $(`#${id}-seg`);
  box.innerHTML = "";
  options.forEach((option) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = option.label;
    button.dataset.value = option.value;
    button.addEventListener("click", async () => {
      markSeg(id, option.value);
      const result = await bridge().set_param(op, option.value);
      log(`写${id}`, result.tx, result.ok, result.ok ? "" : result.error || "");
      if (result.ok) await loadDiscrete(id, op, options);
    });
    box.appendChild(button);
  });
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  $("#win-refresh").classList.add("spin");
  try {
    setConn("扫描中...", "idle");
    const discovery = await bridge().discover_targets();
    TARGETS = (discovery && discovery.targets) || [];
    renderTargetMenu(TARGETS);
    if (!META) {
      META = await bridge().protocol_meta();
      buildSeg("colortemp", META.colortemp, META.ops.colortemp);
      buildSeg("gamma", META.gamma, META.ops.gamma);
    }
    if (!TARGETS.length) {
      setTargetSummary(null, null);
      setConn("未发现目标", "warn");
      log("扫描失败", "", false, (discovery.errors || []).slice(0, 2).join(" / "));
      return;
    }
    await selectTarget(TARGETS[0].id);
  } finally {
    refreshing = false;
    $("#win-refresh").classList.remove("spin");
  }
}

function bindControls() {
  document.addEventListener("click", (event) => {
    const picker = $("#target-picker");
    if (picker && picker.open && !picker.contains(event.target)) picker.open = false;
  });

  $("#skin").addEventListener("click", () => {
    applyTheme(document.body.dataset.theme === "dark" ? "light" : "dark");
  });
  $("#win-refresh").addEventListener("click", refresh);
  $("#win-min").addEventListener("click", () => bridge().minimize_window());
  $("#win-close").addEventListener("click", () => bridge().close_window());
  $$(".resz").forEach((el) => {
    el.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      bridge().start_resize(Number(el.dataset.ht));
    });
  });

  ["brightness", "contrast"].forEach((id) => {
    const input = $(`#${id}`);
    input.addEventListener("input", () => syncMeter(input));
    input.addEventListener("change", async () => {
      const op = META.ops[id];
      const result = await bridge().set_param(op, Number(input.value));
      log(`写${id}`, result.tx, result.ok, result.ok ? "" : result.error || "");
      if (result.ok) await loadParam(id, op);
    });
  });

  $$(".step").forEach((button) => {
    button.addEventListener("click", () => {
      const input = $(`#${button.dataset.target}`);
      const step = Number(button.dataset.step || 0);
      input.value = String(Math.max(Number(input.min), Math.min(Number(input.max), Number(input.value) + step)));
      syncMeter(input);
      input.dispatchEvent(new Event("change"));
    });
  });

  $$(".key-grid button").forEach((button) => {
    button.addEventListener("click", async () => {
      button.animate(
        [{ transform: "scale(1)" }, { transform: "scale(.96)" }, { transform: "scale(1)" }],
        { duration: 180, easing: "cubic-bezier(.2,.8,.2,1)" }
      );
      const key = button.dataset.key;
      const result = await bridge().press_key(key);
      log(`按键 ${button.textContent.trim()}`, result.tx, result.ok, result.ok ? "" : result.error || "");
      setConn(result.ok ? "已连接" : `按键失败: ${result.error || ""}`, result.ok ? "ok" : "warn");
    });
  });
}

function boot() {
  initTheme();
  bindControls();
  refresh();
}

if (window.pywebview) {
  window.addEventListener("pywebviewready", boot);
} else {
  boot();
}
