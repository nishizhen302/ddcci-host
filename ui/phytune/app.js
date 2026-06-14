// RL6410 PHY 调试 —— 分组命名滑杆。启动自动认板 → 拉参数表建控件 → 读当前值。
let MON = 0;
let PORT = 2;   // HDMI 物理端口 D2~D5; 决定寄存器页(D3=P72/P7C...)。默认 D2。
const api = () => window.pywebview.api;
const el = id => document.getElementById(id);
const log = m => { el('log').textContent =
  new Date().toLocaleTimeString() + '  ' + m + '\n' + el('log').textContent; };

const PARAMS = {};          // name -> {def, slider, num, cur, last}

// ---- DDC 操作串行锁 ----
// peek=锁存地址(0xE5)+读回(0xE5) 两步; 多个读/写重叠会交错 → 读到别人锁的地址 = 数值乱跳。
// 所有用户触发的操作(读全部/写/钉住/切端口)都排队串行执行, 杜绝交错。
let _busy = false;
const _queue = [];
function lock(fn) {
  return new Promise((res, rej) => { _queue.push({ fn, res, rej }); pump(); });
}
async function pump() {
  if (_busy) return;
  const job = _queue.shift();
  if (!job) return;
  _busy = true;
  try { job.res(await job.fn()); }
  catch (e) { job.rej(e); }
  finally { _busy = false; pump(); }
}

// ↻读取全部 按钮转圈 + 禁用 + 文字提示(读取期间)
function spin(on) {
  const b = el('btn-refresh');
  if (!b) return;
  b.classList.toggle('spin', !!on);
  b.disabled = !!on;
  const tx = b.querySelector('.rtx');
  if (tx) tx.textContent = on ? '读取中…' : '读取全部';
}

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

  const rec = { def: p, slider, num, cur, last: p.default, pinned: false, pinBtn: null };
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
  // P1: 非在线参数(slot!=null)给个"钉住"按钮, 把当前值固化到 override 槽(重锁后固件自动盖回)。
  if (!p.live && p.slot !== null && p.slot !== undefined) {
    const pin = document.createElement('button');
    pin.className = 'pin'; pin.textContent = '📌 钉住';
    pin.title = '把当前值固化, 信号重锁后不被默认值覆盖';
    pin.addEventListener('click', () => togglePin(p.name));
    rec.pinBtn = pin;
    right.appendChild(pin);
  }
  row.appendChild(right);
  return row;
}

// ---- 锁内核(unlocked, 只在已持锁的上下文里调, 避免嵌套死锁) ----
async function _readInto(name) {
  const rec = PARAMS[name];
  try {
    const r = await api().phytune_param_read(name, MON, PORT);
    if (r && r.ok) {
      rec.cur.textContent = '当前 ' + r.value; rec.last = r.value;
      rec.slider.value = r.value; rec.num.value = r.value;
      return r.value;
    }
    rec.cur.textContent = '读失败'; return null;
  } catch (e) { rec.cur.textContent = '读异常'; return null; }
}

async function _writeOnce(name, v) {
  const rec = PARAMS[name];
  try {
    const r = await api().phytune_param_write(name, v, MON, PORT);
    if (r && r.ok) {
      rec.last = v; await _readInto(name);
      // 已固化的参数改了值 → 同步刷新 override 槽, 否则重锁后会盖回旧的固化值(就是那个"又变 24"的 bug)。
      if (rec.pinned && rec.def.slot !== null && rec.def.slot !== undefined) {
        const pr = await api().phytune_override_pin(name, MON, PORT);
        if (pr && pr.ok) log(`${name} 固化值已更新为 ${v}`);
        else log(`${name} 更新固化值失败: ${(pr && pr.error) || ''}`);
      }
      return true;
    }
    log(`写 ${name}=${v} 失败: ${(r && r.error) || ''}`);
    rec.slider.value = rec.last; rec.num.value = rec.last; return false;
  } catch (e) { log(`写 ${name} 异常: ${e}`); return false; }
}

// ---- 公开入口(全部走串行锁)----
function writeParam(name, v) { return lock(() => _writeOnce(name, v)); }

function togglePin(name) { return lock(() => _togglePinInner(name)); }
async function _togglePinInner(name) {
  const rec = PARAMS[name];
  try {
    if (!rec.pinned) {
      await _writeOnce(name, +rec.slider.value);   // PIN 抓寄存器现值, 先把当前值写进去
      const r = await api().phytune_override_pin(name, MON, PORT);
      if (r && r.ok) { rec.pinned = true; paintPin(rec); log(`已固化 ${name} → 槽${r.slot}`); }
      else log(`固化 ${name} 失败: ${(r && r.error) || ''}`);
    } else {
      const r = await api().phytune_override_clear(name, MON);
      if (r && r.ok) { rec.pinned = false; paintPin(rec); log(`已取消固化 ${name}`); }
      else log(`取消固化 ${name} 失败: ${(r && r.error) || ''}`);
    }
  } catch (e) { log(`固化 ${name} 异常: ${e}`); }
}

function paintPin(rec) {
  if (!rec.pinBtn) return;
  rec.pinBtn.textContent = rec.pinned ? '✅ 已固化' : '📌 钉住';
  rec.pinBtn.classList.toggle('on', rec.pinned);
}

const clamp = (v, lo, hi) => v < lo ? lo : v > hi ? hi : v;

// [自检 B] 强制黑屏: 关 RGB 输出 → 黑 ~0.8s → 恢复。肉眼证明写实时到画面/硅片。
function blankTest() { return lock(_blankTestInner); }
async function _blankTestInner() {
  const b = el('btn-blank');
  if (b) b.disabled = true;
  try {
    log('黑屏自检: 画面应黑约 0.8 秒…');
    const off = await api().phytune_output_enable(MON, false, PORT);
    if (!off || !off.ok) { log('关输出失败: ' + ((off && off.error) || '')); return; }
    await new Promise(r => setTimeout(r, 800));
    const on = await api().phytune_output_enable(MON, true, PORT);
    if (on && on.ok) log('画面已恢复 ✅ — 黑了一下 = 写实时到了硅片/画面, 通道确认无误。');
    else log('⚠ 恢复输出失败! 手动恢复: 拔插信号线或断电重启。错误: ' + ((on && on.error) || ''));
  } catch (e) { log('黑屏自检异常: ' + e + ' (如画面仍黑, 拔插信号线恢复)'); }
  finally { if (b) b.disabled = false; }
}

function refreshAll() { return lock(_refreshAllInner); }
async function _refreshAllInner() {
  spin(true);
  try {
    // 拔插过信号后旧物理显示器句柄已失效(永久读失败), 必须先重新枚举认板才能恢复。
    await pickBoard();
    let okCount = 0, fail = 0;
    for (const name of Object.keys(PARAMS)) {
      const v = await _readInto(name);
      if (v === null) fail++; else okCount++;
    }
    if (okCount === 0 && fail > 0) {
      log('全部读失败 → 已自动重认板。若仍失败: ①等画面完全稳定(重锁后 DDC 要缓几秒) ②确认线接在所选 HDMI 口。');
    }
  } finally { spin(false); }
}

// frameless 窗口: 关闭/最小化/边角缩放/拖动全靠前端接到 Api(同主 UI 机制)。
function wireWindowChrome() {
  const min = el('win-min'), close = el('win-close');
  if (min) min.addEventListener('click', () => api().minimize_window());
  if (close) close.addEventListener('click', () => api().close_window());
  // 边/角缩放: pointerdown 交给系统原生缩放循环
  document.querySelectorAll('.resz').forEach(elm => {
    elm.addEventListener('pointerdown', e => {
      e.preventDefault();
      api().start_resize(Number(elm.dataset.ht));
    });
  });
  // 标题栏拖动: WebView2(Win11) 由 pywebview-drag-region 原生处理;
  // QtWebEngine(Win7) 不认 drag-region, 手动用 HTCAPTION(2) 走系统移动循环。
  if (navigator.userAgent.includes('QtWebEngine')) {
    const HTCAPTION = 2;
    document.querySelectorAll('.pywebview-drag-region').forEach(bar => {
      bar.addEventListener('pointerdown', e => {
        if (e.button !== 0) return;
        if (e.target.closest('.pywebview-no-drag')) return;
        e.preventDefault();
        api().start_resize(HTCAPTION);
      });
    });
  }
}

// 端口选择: 切换 HDMI 物理口(D2~D5) → 寄存器页随之偏移, 重读全部。
function wirePortSel() {
  const ps = el('port');
  if (!ps) return;
  ps.value = String(PORT);
  ps.addEventListener('change', () => {
    PORT = +ps.value;
    log('切到 D' + PORT + ' 口 (寄存器页随端口偏移); 重读中…');
    refreshAll();
  });
}

async function boot() {
  wireWindowChrome();
  wirePortSel();
  await pickBoard();
  await buildUI();
  await refreshAll();
  log('就绪。先选对你插的 HDMI 口(D2~D5)！绿=在线即时生效; 黄=需📌固化(重锁会被覆盖)。');
}

// 必须等 pywebview 把 api 注入完(pywebviewready)再调, 否则 window.pywebview 还是 undefined。
// 若事件已在挂监听前触发过, 用 api 是否就绪做兜底直接启动。
if (window.pywebview && window.pywebview.api) {
  boot();
} else {
  window.addEventListener('pywebviewready', boot);
}
