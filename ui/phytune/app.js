let MON = 0;                         // 启动时自动认 RTK 板(list_monitors 的 default)
const hx = id => parseInt(document.getElementById(id).value, 16);
const log = m => { document.getElementById('log').textContent =
  new Date().toLocaleTimeString() + '  ' + m + '\n' + document.getElementById('log').textContent; };

async function pickBoard() {
  try {
    const r = await window.pywebview.api.list_monitors();
    if (r && r.ok) {
      if (r.default !== null && r.default !== undefined) { MON = r.default; }
      const names = (r.monitors || []).map(m => `[${m.id}] ${m.model || m.description}`).join('  ');
      log(`显示器: ${names || '(无)'}  → 用 [${MON}]`);
    } else {
      log('枚举显示器失败: ' + ((r && r.error) || '未知'));
    }
  } catch (e) { log('枚举异常: ' + e); }
}
window.addEventListener('load', pickBoard);

async function doPeek() {
  const r = await window.pywebview.api.phytune_peek(hx('page'), hx('off'), MON);
  document.getElementById('rd').textContent = r.ok ? '= 0x' + r.value.toString(16).toUpperCase() : r.error;
  log(r.ok ? `peek ${document.getElementById('page').value}:${document.getElementById('off').value} = 0x${r.value.toString(16)}` : 'peek 失败: ' + r.error);
}
async function doPoke() {
  const r = await window.pywebview.api.phytune_poke(hx('page'), hx('off'), hx('data'), 0, MON);
  log(r.ok ? `poke ok` : 'poke 失败: ' + r.error);
}
