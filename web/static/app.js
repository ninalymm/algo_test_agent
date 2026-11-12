const chat = document.getElementById('chat');
const input = document.getElementById('input');
const form = document.getElementById('composer');

const SID = localStorage.getItem('sid') || (() => {
  const v = 's-' + Math.random().toString(36).slice(2, 10);
  localStorage.setItem('sid', v);
  return v;
})();

let lastPlan = null;
let lastAttempt = null;

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

function addUser(text) {
  const m = el('div', 'msg user');
  m.appendChild(el('div', 'bubble', text));
  chat.appendChild(m);
  chat.scrollTop = chat.scrollHeight;
}

function addBot(reply, card, meta) {
  const m = el('div', 'msg bot');
  const b = el('div', 'bubble');
  b.textContent = reply || '';
  if (card) b.appendChild(renderCard(card, meta));
  m.appendChild(b);
  chat.appendChild(m);
  chat.scrollTop = chat.scrollHeight;
}

function renderCard(card, meta) {
  if (card.type === 'ask') return renderAsk(card);

  const wrap = el('div', 'card');
  const head = el('div', 'head');
  head.appendChild(el('span', '', card.title || '结果'));
  const statusText = {pass: '✅ 通过', fail: '❌ 不通过', warn: '⚠️ 注意'}[card.status] || '';
  head.appendChild(el('span', card.status === 'fail' ? 'bad' : 'ok', statusText));
  wrap.appendChild(head);

  const body = el('div', 'body');

  if (card.change) {
    const c = card.change;
    const box = el('div', 'change');
    box.appendChild(el('div', 'change-title', '本次改动'));
    box.appendChild(el('div', 'change-line', `${c.title}`));
    box.appendChild(el('div', 'change-meta',
      `${c.id} · ${c.commit}${c.mr ? ' · ' + c.mr : ''} · ${c.author || ''} · ${c.ts || ''}`));
    if (c.files && c.files.length) {
      box.appendChild(el('div', 'change-meta', '文件：' + c.files.join('、')));
    }
    box.appendChild(el('div', 'change-meta',
      `影响：图 ${(c.graphs || []).join('、')} → ${(c.scenes || []).length} 个场景`));
    body.appendChild(box);
  }

  (card.metrics || []).forEach(m => {
    const row = el('div', 'metric');
    row.appendChild(el('span', '', m.name));
    row.appendChild(el('span', 'v ' + (m.ok ? 'ok' : 'bad'), m.value));
    body.appendChild(row);
  });
  (card.lines || []).forEach(l => body.appendChild(el('div', '', l)));
  if (card.reasons) card.reasons.forEach(r => body.appendChild(el('div', 'bad', '· ' + r)));

  if (card.rows && card.columns) {
    const tbl = el('div', 'table');
    const headRow = el('div', 'trow thead');
    card.columns.forEach(c => headRow.appendChild(el('span', '', c)));
    tbl.appendChild(headRow);
    card.rows.forEach(r => {
      const row = el('div', 'trow');
      [r.id, r.ts, r.diff, r.p99, r.flag].forEach((v, i) => {
        row.appendChild(el('span', i === 4 && v !== '—' ? 'warn' : '', String(v ?? '')));
      });
      tbl.appendChild(row);
    });
    body.appendChild(tbl);
  }
  if (card.note) body.appendChild(el('div', 'note', card.note));

  if (card.trend) {
    const t = card.trend;
    const box = el('div', 'trendblock');
    box.appendChild(el('div', 'change-title', `近 ${t.n} 次`));
    box.appendChild(el('div', 'change-meta', 'p99：' + t.p99));
    box.appendChild(el('div', 'change-meta', 'diff：' + t.diff));
    if (card.aborted) box.appendChild(el('div', 'change-meta warn',
      `另有 ${card.aborted} 轮失败未计入（见 attempt）`));
    body.appendChild(box);
  }

  const actions = el('div', 'actions');
  (card.actions || []).forEach(a => {
    const btn = el('button', '', a);
    btn.onclick = () => handleAction(a, meta);
    actions.appendChild(btn);
  });
  if (meta && meta.attempt) {
    const btn = el('button', '', '重跑上一轮');
    btn.onclick = () => retry(meta.attempt);
    actions.appendChild(btn);
  }
  body.appendChild(actions);
  wrap.appendChild(body);
  return wrap;
}

function renderAsk(card) {
  const wrap = el('div', 'card');
  const head = el('div', 'head');
  head.appendChild(el('span', '', card.title));
  head.appendChild(el('span', 'warn', '需要确认'));
  wrap.appendChild(head);

  const body = el('div', 'body');
  if (card.hint) body.appendChild(el('div', 'note', card.hint));
  const actions = el('div', 'actions');
  (card.options || []).forEach(o => {
    const btn = el('button', '', o);
    btn.onclick = () => send(o);
    actions.appendChild(btn);
  });
  body.appendChild(actions);
  wrap.appendChild(body);
  return wrap;
}

async function post(path, body) {
  const r = await fetch(path, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({...body, session_id: SID})
  });
  return r.json();
}

async function handleAction(action, meta) {
  if (action === '确认执行' || action === '确认') {
    if (!lastPlan) return addBot('没有待执行的计划。');
    addUser('确认执行');
    const data = await post('/api/execute', {plan: lastPlan});
    if (data.attempt) lastAttempt = data.attempt;
    addBot(data.reply, data.card, {trace: data.trace_id, attempt: data.attempt});
    return;
  }
  if (action === 'trace' || action === '查看 trace') {
    if (!meta || !meta.trace) return addBot('这次没有 trace。');
    const r = await fetch('/api/trace/' + meta.trace);
    const data = await r.json();
    const m = el('div', 'msg bot');
    const b = el('div', 'bubble');
    b.textContent = `trace ${meta.trace}`;
    const pre = el('pre', 'trace');
    pre.textContent = data.spans.map(s =>
      `${s.name.padEnd(18)} ${(s.end_ms - s.start_ms)}ms  ${s.status}  ${s.attrs || ''}`).join('\n');
    b.appendChild(pre);
    m.appendChild(b);
    chat.appendChild(m);
    chat.scrollTop = chat.scrollHeight;
    return;
  }
  addBot(`（演示版未实现「${action}」）`);
}

async function retry(attempt) {
  if (!lastPlan) return addBot('没有可重跑的计划。');
  addUser('重跑上一轮');
  const data = await post('/api/execute', {plan: {...lastPlan, retry_of: attempt}});
  if (data.attempt) lastAttempt = data.attempt;
  addBot(data.reply, data.card, {trace: data.trace_id, attempt: data.attempt});
}

async function send(text) {
  if (!text.trim()) return;
  addUser(text);
  input.value = '';
  const data = await post('/api/chat', {message: text});
  if (data.plan) lastPlan = data.plan;
  if (data.attempt) lastAttempt = data.attempt;
  addBot(data.reply, data.card, {trace: data.trace_id, attempt: data.attempt});
}

form.addEventListener('submit', e => { e.preventDefault(); send(input.value); });
document.querySelectorAll('#chips button').forEach(b =>
  b.addEventListener('click', () => send(b.dataset.q)));
