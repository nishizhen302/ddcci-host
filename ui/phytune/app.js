// RL6410 PHY 调试 —— 分组命名滑杆。启动自动认板 → 拉参数表建控件 → 读当前值。
let MON = 0;
const api = () => window.pywebview.api;
const el = id => document.getElementById(id);
const log = m => { el('log').textContent =
  new Date().toLocaleTimeString() + '  ' + m + '\n' + el('log').textContent; };

const PARAMS = {};          // name -> {def, slider, num, cur, last}

async function pickBoard() {
  try {
    const r = await api().list_monitors();
    if (r && r.ok) {
      if (r.default !== null && r.default !== undefined) MON = r.default;
      const names = (r.monitors || []).map(m => `[${m.id}] ${m.model || m.description}`).join('  ');
      el('board').textContent = `${names || '(无显示器)'}  → 调试目标 [${MON}]`;
    } else { el('board').textContent = '枚举失败: ' + ((r && r.error) || '未知'); }
  } catch (e) { el('board').textContent = '枚举异常: ' + e; }
}

async function buildUI() {
  const r = await api().phytune_params();
  if (!r || !r.ok) { log('拉参数表失败: ' + ((r && r.error) || '未知')); return; }
  const wrap = el('groups'); wrap.innerHTML = '';
  for (const g of r.groups) {
    const ps = r.params.filter(p => p.group === g.id);
    if (!ps.length) continue;
    const card = document.createElement('div'); card.className = 'group';
    card.innerHTML = `<div class="ghead">${g.label}</div>`;
    for (const p of ps) card.appendChild(rowFor(p));
    wrap.appendChild(card);
  }
}

function rowFor(p) {
  const row = document.createElement('div'); row.className = 'row';
  const badge = p.live ? '<span class="badge b-live">在线</span>'
                       : '<span class="badge b-p1">需P1固化</span>';
  const left = document.createElement('div'); left.className = 'pname';
  left.innerHTML = `<b>${p.label}${badge}</b><span class="note">${p.note || ''}</span>`;
  const slider = document.createElement('input');
  slider.type = 'range'; slider.min = p.min; slider.max = p.max; slider.value = p.default;
  const num = document.createElement('input');
  num.className = 'num'; num.type = 'number'; num.min = p.min; num.max = p.max; num.value = p.default;
  const cur = document.createElement('div'); cur.className = 'cur'; cur.textContent = '当前 …';

  const rec = { def: p, slider, num, cur, last: p.default };
  PARAMS[p.name] = rec;

  // 拖动时只更新数字显示(纯 UI, 流畅); 松手(change)才真正写一次寄存器。
  // DDC/CI 每次读写要走 I²C 来回(慢), 拖动途中写会卡顿, 故只在释放时写。
  slider.addEventListener('input', () => { num.value = slider.value; });
  slider.addEventListener('change', () => writeParam(p.name, +slider.value));
  num.addEventListener('change', () => {
    let v = clamp(+num.value, p.min, p.max); num.value = v; slider.value = v; writeParam(p.name, v);
  });

  row.appendChild(left); row.appendChild(slider);
  const right = document.createElement('div'); right.appendChild(num); right.appendChild(cur);
  row.appendChild(right);
  return row;
}

const clamp = (v, lo, hi) => v < lo ? lo : v > hi ? hi : v;

async function writeParam(name, v) {
  const rec = PARAMS[name];
  try {
    const r = await api().phytune_param_write(name, v, MON);
    if (r && r.ok) { rec.last = v; readParam(name); }
    else { log(`写 ${name}=${v} 失败: ${(r && r.error) || ''}`);
           rec.slider.value = rec.last; rec.num.value = rec.last; }
  } catch (e) { log(`写 ${name} 异常: ${e}`); }
}

async function readParam(name) {
  const rec = PARAMS[name];
  try {
    const r = await api().phytune_param_read(name, MON);
    if (r && r.ok) { rec.cur.textContent = '当前 ' + r.value; rec.last = r.value; }
    else { rec.cur.textContent = '读失败'; }
  } catch (e) { rec.cur.textContent = '读异常'; }
}

async function refreshAll() {
  for (const name of Object.keys(PARAMS)) {
    const rec = PARAMS[name];
    await readParam(name);
    if (rec.cur.textContent.startsWith('当前 ')) {
      const v = parseInt(rec.cur.textContent.slice(3), 10);
      if (!isNaN(v)) { rec.slider.value = v; rec.num.value = v; }
    }
  }
}

async function boot() {
  await pickBoard();
  await buildUI();
  await refreshAll();
  log('就绪。绿=在线即时生效; 黄=需 P1 override 固化(重锁会被覆盖)。');
}

// 必须等 pywebview 把 api 注入完(pywebviewready)再调, 否则 window.pywebview 还是 undefined。
// 若事件已在挂监听前触发过, 用 api 是否就绪做兜底直接启动。
if (window.pywebview && window.pywebview.api) {
  boot();
} else {
  window.addEventListener('pywebviewready', boot);
}
