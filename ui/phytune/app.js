const MON = 0;                       // P0 固定 0 号; P2 改成认 RTK 板
const hx = id => parseInt(document.getElementById(id).value, 16);
const log = m => { document.getElementById('log').textContent =
  new Date().toLocaleTimeString() + '  ' + m + '\n' + document.getElementById('log').textContent; };

async function doPeek() {
  const r = await window.pywebview.api.phytune_peek(hx('page'), hx('off'), MON);
  document.getElementById('rd').textContent = r.ok ? '= 0x' + r.value.toString(16).toUpperCase() : r.error;
  log(r.ok ? `peek ${document.getElementById('page').value}:${document.getElementById('off').value} = 0x${r.value.toString(16)}` : 'peek 失败: ' + r.error);
}
async function doPoke() {
  const r = await window.pywebview.api.phytune_poke(hx('page'), hx('off'), hx('data'), 0, MON);
  log(r.ok ? `poke ok` : 'poke 失败: ' + r.error);
}
