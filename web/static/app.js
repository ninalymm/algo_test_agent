const chat = document.getElementById('chat');
const input = document.getElementById('input');
const form = document.getElementById('composer');
let lastPlan = null;

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

function addBot(reply, card, traceId) {
  const m = el('div', 'msg bot');
  const b = el('div', 'bubble');
  b.textContent = reply || '';
  if (card) b.appendChild(renderCard(card, traceId));
  m.appendChild(b);
  chat.appendChild(m);
  chat.scrollTop = chat.scrollHeight;
}

function renderCard(card, traceId) {
  const wrap = el('div', 'card');
  const head = el('div', 'head');
  head.appendChild(el('span', '', card.title || '结果'));
  const statusText = {pass: '✅ 通过', fail: '❌ 不通过', warn: '⚠️ 注意'}[card.status] || '';
  head.appendChild(el('span', card.status === 'fail' ? 'bad' : 'ok', statusText));
  wrap.appendChild(head);

  const body = el('div', 'body');

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
    const head = el('div', 'trow thead');
    card.columns.forEach(c => head.appendChild(el('span', '', c)));
    tbl.appendChild(head);
    card.rows.forEach(r => {
      const row = el('div', 'trow');
      const vals = [r.id, r.ts, r.diff, r.p99, r.flag];
      vals.forEach((v, i) => {
        const cell = el('span', i === 4 && v !== '—' ? 'warn' : '', String(v ?? ''));
        row.appendChild(cell);
      });
      tbl.appendChild(row);
    });
    body.appendChild(tbl);
  } else if (card.rows) {
    card.rows.forEach(r => {
      const row = el('div', 'metric');
      row.appendChild(el('span', '', r.stage));
      row.appendChild(el('span', 'v', String(r.median)));
      body.appendChild(row);
    });
  }

  if (card.note) body.appendChild(el('div', 'note', card.note));

  const actions = el('div', 'actions');
  (card.actions || []).forEach(a => {
    const btn = el('button', '', a);
    btn.onclick = () => handleAction(a, card, traceId);
    actions.appendChild(btn);
  });
  body.appendChild(actions);
  wrap.appendChild(body);
  return wrap;
}

async function handleAction(action, card, traceId) {
  if (action === '确认执行' && lastPlan) {
    addUser('确认执行');
    const r = await fetch('/api/execute', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({plan: lastPlan})
    });
    const data = await r.json();
    addBot(data.reply, data.card, data.trace_id);
    return;
  }
  if (action === 'trace' || action === '查看 trace') {
    if (!traceId) return addBot('这次没有 trace（只读查询不产生执行链路）。');
    const r = await fetch('/api/trace/' + traceId);
    const data = await r.json();
    const m = el('div', 'msg bot');
    const b = el('div', 'bubble');
    b.textContent = `trace ${traceId}`;
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

async function send(text) {
  if (!text.trim()) return;
  addUser(text);
  input.value = '';
  const r = await fetch('/api/chat', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({message: text})
  });
  const data = await r.json();
  if (data.plan) lastPlan = data.plan;
  addBot(data.reply, data.card, data.trace_id);
}

form.addEventListener('submit', e => { e.preventDefault(); send(input.value); });
document.querySelectorAll('#chips button').forEach(b =>
  b.addEventListener('click', () => send(b.dataset.q)));
