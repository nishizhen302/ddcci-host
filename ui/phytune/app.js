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

  const rec = { def: p, slider, num, cur, last: p.default, pinned: false, pinBtn: null, dragging: false };
  PARAMS[p.name] = rec;

  // 拖动时只更新数字显示(纯 UI, 流畅); 松手(change)才真正写一次寄存器。
  // DDC/CI 每次读写要走 I²C 来回(慢), 拖动途中写会卡顿, 故只在释放时写。
  // dragging 标志: 自动刷新轮询时, 别把用户正在操作的滑杆/输入框拽回硬件值。
  slider.addEventListener('pointerdown', () => { rec.dragging = true; });
  slider.addEventListener('pointerup', () => { rec.dragging = false; });
  slider.addEventListener('input', () => { num.value = slider.value; });
  slider.addEventListener('change', () => { rec.dragging = false; writeParam(p.name, +slider.value); });
  num.addEventListener('focus', () => { rec.dragging = true; });
  num.addEventListener('blur', () => { rec.dragging = false; });
  num.addEventListener('change', () => {
    let v = clamp(+num.value, p.min, p.max); num.value = v; slider.value = v; rec.dragging = false; writeParam(p.name, v);
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
      // 用户正在拖这个滑杆/编辑数字框时不要拽回(自动刷新轮询尤其要避免); 只更新"当前"读数。
      if (!rec.dragging) { rec.slider.value = r.value; rec.num.value = r.value; }
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

// 应急: 一键清空 override 表 + 复位所有📌状态。现场钉了坏值黑屏循环时救场。
function clearAllPins() { return lock(_clearAllPinsInner); }
async function _clearAllPinsInner() {
  const r = await api().phytune_override_clearall(MON);
  if (r && r.ok) {
    for (const name of Object.keys(PARAMS)) {
      const rec = PARAMS[name];
      if (rec.pinned) { rec.pinned = false; paintPin(rec); }
    }
    log('已清空所有固化(override 表)→ 下次重锁全部回固件默认。');
  } else log('清空固化失败: ' + ((r && r.error) || ''));
}

// ---- 🔧 一键开眼: CED 闭环自动扫 LE/Tap1, 停在每 lane 误码最低值 ----
// 机制(固件 TMDSRx2.c:1493-1568 验证): 关自适应环(A1/B1/C1=0)→写 A5/B5/C5(活的 LE+Tap1)
// →翻转 AA/BA/CA[2:1] reload 推进硅片→读该 lane 的 CED 通道。纯 peek/poke, 不改固件。
let _autoEyeRunning = false;
let _autoEyeCancel = false;
const sleep = ms => new Promise(r => setTimeout(r, ms));

function autoEye() {
  if (_autoEyeRunning) { _autoEyeCancel = true; log('一键开眼: 收到停止…'); return; }
  return lock(_autoEyeInner);
}
function _setEyeBtn(running) {
  const b = el('btn-autoeye'); if (!b) return;
  b.textContent = running ? '⏹ 停止开眼' : '🔧 一键开眼';
}

// 测一个 lane 的误码: 读一次清零 → 等窗口累计 → 再读 = 该窗口误码增量。无效链路返回 null。
async function _measureLaneErr(lane, dwell) {
  let r = await api().phytune_ced_read(MON, PORT);
  if (!r || !r.ok || !r.valid) return null;
  await sleep(dwell);
  r = await api().phytune_ced_read(MON, PORT);
  if (!r || !r.ok || !r.channels[lane]) return null;
  return r.channels[lane].count;
}
// 试一个候选值: 写 A5 → reload 推活 → 稳定 → 测该 lane 误码。
async function _tryVal(name, lane, v, dwell) {
  await api().phytune_param_write(name, v, MON, PORT);
  await api().phytune_dfe_reload(MON, PORT, lane);
  await sleep(150);
  return await _measureLaneErr(lane, dwell);
}

async function _sweepLane(lane, dwell) {
  const name = 'dfe_tap1_l' + lane;          // A5/B5/C5 = 活的 LE+Tap1 寄存器
  const rec = PARAMS[name]; if (!rec) return null;
  const p = rec.def;
  const lo = p.min, hi = Math.min(p.max, 40); // 上限 40 够用(LE+Tap1 和), 控制扫描时长
  let best = { v: clamp(+rec.slider.value, lo, hi), e: Infinity };
  const tried = new Set();
  // 粗扫 step 4
  for (let v = lo; v <= hi; v += 4) {
    if (_autoEyeCancel) return best;
    const e = await _tryVal(name, lane, v, dwell);
    if (e === null) { log(`lane${lane}: 链路无误码统计(非高速/未加扰), 跳过`); return null; }
    tried.add(v);
    if (e < best.e) best = { v, e };
    log(`lane${lane} LE/Tap1=${v} → 误码 ${e}${e === best.e ? '  ← 最优' : ''}`);
    if (best.e === 0) break;                  // 已无误码, 无需再扫
  }
  // 细扫 best 附近 ±3 step 1
  if (best.e > 0) {
    for (let v = Math.max(lo, best.v - 3); v <= Math.min(hi, best.v + 3); v++) {
      if (_autoEyeCancel) break;
      if (tried.has(v)) continue;
      const e = await _tryVal(name, lane, v, dwell);
      if (e === null) break;
      if (e < best.e) { best = { v, e }; log(`lane${lane} 细调 ${v} → 误码 ${e}  ← 更优`); }
      if (best.e === 0) break;
    }
  }
  // 落定最优值 + reload + 固化
  await api().phytune_param_write(name, best.v, MON, PORT);
  await api().phytune_dfe_reload(MON, PORT, lane);
  const pr = await api().phytune_override_pin(name, MON, PORT);
  if (pr && pr.ok) { rec.pinned = true; paintPin(rec); }
  await _readInto(name);
  return best;
}

async function _autoEyeInner() {
  _autoEyeRunning = true; _autoEyeCancel = false; _setEyeBtn(true);
  const b = el('btn-autoeye'); if (b) b.disabled = false;
  try {
    log('🔧 一键开眼开始 (D' + PORT + ')。先查链路是否有可测误码…');
    const pre = await api().phytune_ced_read(MON, PORT);
    if (!pre || !pre.ok) { log('读 CED 失败, 终止。确认已选对 HDMI 口、画面已稳。'); return; }
    if (!pre.valid) {
      log('⚠ 当前链路非高速加扰(无 CED 统计)→ 无客观判据可优化, 终止。'
        + ' 一键开眼只在高分辨率/高刷(SSC 点不亮那类)场景有效。');
      return;
    }
    const baseTot = pre.channels.reduce((s, c) => s + c.count, 0);
    log('基线误码 R/G/B = ' + pre.channels.map(c => c.count).join('/'));
    // 关自适应环, 否则手动 LE/Tap1 会被硅片冲掉
    const fz = await api().phytune_dfe_freeze(MON, true, PORT);
    if (!fz || !fz.ok) { log('关自适应失败, 终止: ' + ((fz && fz.error) || '')); return; }
    log('已关 DFE 自适应环(A1/B1/C1=0), 开始逐 lane 扫描…');
    const dwell = 600;
    const res = [];
    for (let lane = 0; lane < 3; lane++) {
      if (_autoEyeCancel) { log('已停止。'); break; }
      log(`—— 扫 lane${lane} (${['R', 'G', 'B'][lane]}) ——`);
      const r = await _sweepLane(lane, dwell);
      if (r === null) { log('该链路不可测, 终止扫描。'); break; }
      res.push({ lane, v: r.v, e: r.e });
      log(`lane${lane} 定为 LE/Tap1=${r.v} (误码 ${r.e}), 已📌固化。`);
    }
    if (res.length) {
      const tot = res.reduce((s, r) => s + r.e, 0);
      log(`✅ 一键开眼完成: ${res.map(r => `L${r.lane}=${r.v}(${r.e})`).join('  ')}`
        + `  | 残余误码合计 ${tot}` + (baseTot ? ` (基线 ${baseTot})` : ''));
      log('值已固化, 本次会话内重锁会盖回。彻底恢复自适应=拔插/断电。坏了点🧹清空固化。');
    }
    await _pollCed();
  } catch (e) { log('一键开眼异常: ' + e); }
  finally { _autoEyeRunning = false; _autoEyeCancel = false; _setEyeBtn(false); }
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
    await _pollCed();   // 顺带刷一次误码
  } finally { spin(false); }
}

// ---- 实时误码 CED: 三通道 R/G/B 字符误码增量(读后清零, 每轮=一段误码率) ----
// 调 LE/Tap1/CDR 时盯哪条通道往下掉 = 方向对。仅高速加扰 HDMI2.0 链路有数。
function setCedState(txt, cls) {
  const st = el('ced-st'); if (!st) return;
  st.textContent = txt; st.className = 'ced-st ' + (cls || '');
}
function paintCed(channels, valid) {
  for (const c of (channels || [])) {
    const cell = el('ced-' + c.name); if (!cell) continue;
    const b = cell.querySelector('b');
    if (!valid || !c.valid) { b.textContent = '—'; cell.className = 'cedc idle'; continue; }
    b.textContent = c.count;
    cell.className = 'cedc ' + (c.count === 0 ? 'zero' : 'err');
  }
}
async function _pollCed() {
  try {
    const r = await api().phytune_ced_read(MON, PORT);
    if (!r || !r.ok) { setCedState('读失败', 'bad'); paintCed(null, false); return; }
    if (!r.valid) {
      setCedState('链路未加扰/低速 — 无误码统计(高分辨率高速链路下才有)', 'idle');
      paintCed(r.channels, false); return;
    }
    setCedState('每≈2秒增量, 越小越好; 某通道在涨=那条lane加LE/Tap1', 'ok');
    paintCed(r.channels, true);
    const tot = r.channels.reduce((s, c) => s + c.count, 0);
    if (tot > 0) log(`误码 R/G/B = ${r.channels.map(c => c.count).join('/')}`);
  } catch (e) { setCedState('异常', 'bad'); }
}

// ---- 自动刷新: 固件会在背后改寄存器(重锁复位 Icp 等), UI 须周期性读回才不显示陈旧值 ----
let _pollTimer = null;
let _polling = false;        // 防止上一轮没读完又叠一轮
function setAutoRefresh(on) {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  if (on) _pollTimer = setInterval(pollTick, 2000);   // 2 秒一轮
}
function pollTick() {
  if (_polling || _busy) return;        // 串行锁忙(用户在写/读)就跳过这一拍
  _polling = true;
  lock(_pollReadAll).finally(() => { _polling = false; });
}
async function _pollReadAll() {
  let okc = 0;
  for (const name of Object.keys(PARAMS)) {
    if (await _readInto(name) !== null) okc++;
  }
  // 全失败 = 句柄可能已失效(拔插过) → 自动重认板一次(免去手动点)。
  if (okc === 0 && Object.keys(PARAMS).length) await pickBoard();
  await _pollCed();   // 误码监视也并入这一轮(同锁内, 不与参数读交错)
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

// 自动刷新开关
function wireAutoRefresh() {
  const cb = el('autoref');
  if (!cb) return;
  cb.addEventListener('change', () => {
    setAutoRefresh(cb.checked);
    log(cb.checked ? '自动刷新已开(2秒/次): 显示实时跟住硬件。' : '自动刷新已关。');
  });
  setAutoRefresh(cb.checked);   // 按初始勾选状态启动
}

async function boot() {
  wireWindowChrome();
  wirePortSel();
  await pickBoard();
  await buildUI();
  await refreshAll();
  wireAutoRefresh();   // 参数表建好后再启动轮询
  log('就绪。先选对你插的 HDMI 口(D2~D5)！绿=在线即时生效; 黄=需📌固化(重锁会被覆盖)。');
}

// 必须等 pywebview 把 api 注入完(pywebviewready)再调, 否则 window.pywebview 还是 undefined。
// 若事件已在挂监听前触发过, 用 api 是否就绪做兜底直接启动。
if (window.pywebview && window.pywebview.api) {
  boot();
} else {
  window.addEventListener('pywebviewready', boot);
}
