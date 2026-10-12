const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function syncMeter(input) {
  const max = Number(input.max || 100);
  const value = Number(input.value || 0);
  const pct = `${Math.round((value / max) * 100)}%`;
  const meter = input.closest(".meter");
  const fill = meter && meter.querySelector("span");
  const out = $(`#${input.id}-out`);
  if (fill) fill.style.setProperty("--value", pct);
  if (out) out.value = value;
}

function addLog(label, frame) {
  const list = $(".log-list");
  if (!list) return;
  const row = document.createElement("p");
  const now = new Date().toTimeString().slice(0, 8);
  row.innerHTML = `<time>${now}</time><span>${label}</span><code>${frame}</code>`;
  list.prepend(row);
  while (list.children.length > 6) list.removeChild(list.lastChild);
}

$("#theme-toggle").addEventListener("click", () => {
  const body = document.body;
  const next = body.dataset.theme === "dark" ? "light" : "dark";
  body.dataset.theme = next;
  addLog("皮肤", next === "dark" ? "theme dark" : "theme light");
});

$$("input[type='range']").forEach((input) => {
  syncMeter(input);
  input.addEventListener("input", () => syncMeter(input));
  input.addEventListener("change", () => {
    const label = input.id === "brightness" ? "写亮度" : "写对比";
    const code = input.id === "brightness" ? "10" : "12";
    const value = Number(input.value).toString(16).padStart(2, "0").toUpperCase();
    addLog(label, `5E 51 84 03 ${code} 00 ${value} --`);
  });
});

$$(".step").forEach((button) => {
  button.addEventListener("click", () => {
    const input = $(`#${button.dataset.target}`);
    const step = Number(button.dataset.step || 0);
    input.value = Math.max(Number(input.min), Math.min(Number(input.max), Number(input.value) + step));
    syncMeter(input);
    input.dispatchEvent(new Event("change"));
  });
});

$$(".seg").forEach((seg) => {
  seg.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    seg.querySelectorAll("button").forEach((item) => item.classList.toggle("active", item === button));
    addLog("选择", button.textContent.trim());
  });
});

$$(".key-grid button").forEach((button) => {
  button.addEventListener("click", () => {
    button.animate(
      [{ transform: "scale(1)" }, { transform: "scale(.96)" }, { transform: "scale(1)" }],
      { duration: 180, easing: "cubic-bezier(.2,.8,.2,1)" }
    );
    addLog("按键", `C0 96 ${button.textContent.trim()} 00`);
  });
});

$$(".target-option").forEach((button) => {
  button.addEventListener("click", () => {
    $$(".target-option").forEach((item) => item.classList.toggle("active", item === button));
    $("#target-name").textContent = button.dataset.name;
    $("#backend-chip").textContent = button.dataset.backend;
    $("#addr-chip").textContent = `addr ${button.dataset.address}`;
    const picker = button.closest(".target-picker");
    if (picker) picker.open = false;
    addLog("切换目标", button.dataset.name);
  });
});
