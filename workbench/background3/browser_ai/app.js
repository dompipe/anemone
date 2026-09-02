(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const els = {
    conversation: $('conversation'), welcome: $('welcome'), prompt: $('prompt'), send: $('send'),
    kingdoms: $('kingdoms'), search: $('taxonSearch'), searchResults: $('searchResults'),
    context: $('context'), dataMode: $('dataMode'), leftStats: $('leftStats'),
    runtime: $('runtimePill'), modeTitle: $('modeTitle'), modePill: $('modePill'),
    composerMeta: $('composerMeta'), nav: $('nav'), newChat: $('newChat')
  };

  const state = {
    mode: 'ask', busy: false, bootstrap: null, active: null,
    descriptorFilter: 'present', jx: {}, searchTimer: null
  };

  const MODE = {
    ask: {title: 'Ask Anemone', leaf: 'ask', placeholder: 'Ask about a taxon, lineage, phenotype, or inherited trait…'},
    explore: {title: 'Explore taxonomy', leaf: 'explore', placeholder: 'Ask Anemone to open a kingdom, phylum, class, species, or child branch…'},
    compare: {title: 'Compare traits', leaf: 'compare', placeholder: 'With a taxon selected, enter descriptors separated by commas…'}
  };

  function esc(value) {
    return String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  }

  function fmtInt(n) { return Number(n || 0).toLocaleString(); }
  function fmtBytes(n) {
    n = Number(n || 0);
    if (!n) return '0 B';
    const units = ['B','KiB','MiB','GiB']; let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(i >= 2 ? 2 : 0)} ${units[i]}`;
  }

  async function api(op, options = {}) {
    const url = new URL('api.php', location.href);
    url.searchParams.set('op', op);
    for (const [k,v] of Object.entries(options.query || {})) if (v !== undefined && v !== null) url.searchParams.set(k, v);
    const init = options.body === undefined ? {} : {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(options.body)
    };
    const response = await fetch(url, init);
    if (!response.ok) {
      let detail = response.statusText;
      try { detail = (await response.json()).error || detail; } catch (_) {}
      throw new Error(detail);
    }
    return response.json();
  }

  async function runJxLeaf(leaf) {
    const meta = MODE[leaf] || {leaf};
    const id = meta.leaf || leaf;
    try {
      if (!globalThis.JxPasl || typeof globalThis.JxPasl.run !== 'function') throw new Error('build.php has not copied the browser VM yet');
      const response = await fetch(`build/browser/${id}.pasm`, {cache:'no-store'});
      if (!response.ok) throw new Error('run php build.php');
      const asm = await response.text();
      const out = globalThis.JxPasl.run(asm);
      state.jx[id] = out;
      els.runtime.textContent = `JX browser · ${id} · ${out.steps} ops · result ${out.result}`;
      renderContext();
      return out;
    } catch (error) {
      els.runtime.textContent = `JX browser · ${error.message}`;
      state.jx[id] = {error:error.message};
      renderContext();
      return null;
    }
  }

  function hideWelcome() {
    const welcome = $('welcome');
    if (welcome) welcome.remove();
  }

  function addMessage(role, text = '') {
    hideWelcome();
    const article = document.createElement('article');
    article.className = `message ${role}`;
    const avatar = document.createElement('div');
    avatar.className = 'avatar'; avatar.textContent = role === 'assistant' ? 'A' : 'Y';
    const body = document.createElement('div'); body.className = 'message-body';
    const label = document.createElement('div'); label.className = 'message-label'; label.textContent = role === 'assistant' ? 'Anemone' : 'You';
    const status = document.createElement('div'); status.className = 'thought'; status.hidden = true;
    const copy = document.createElement('div'); copy.className = 'message-copy'; copy.textContent = text;
    body.append(label, status, copy); article.append(avatar, body); els.conversation.append(article);
    els.conversation.scrollTop = els.conversation.scrollHeight;
    return {article, body, label, status, copy, text};
  }

  function setThought(message, label, spinning = true) {
    if (!label) { message.status.hidden = true; return; }
    message.status.hidden = false;
    message.status.innerHTML = `${spinning ? '<span class="spinner"></span>' : ''}<span>${esc(label)}</span>`;
  }

  function addChildChips(message, children) {
    if (!children || !children.length) return;
    let row = message.body.querySelector('.child-row');
    if (!row) { row = document.createElement('div'); row.className = 'child-row'; message.body.append(row); }
    row.innerHTML = '';
    for (const child of children.slice(0,25)) {
      const button = document.createElement('button'); button.className = 'child-chip';
      button.textContent = `${child.rank} · ${child.canonical_name}`;
      button.onclick = () => loadTaxon(Number(child.taxon_id), true);
      row.append(button);
    }
  }

  function renderKingdoms() {
    const rows = state.bootstrap?.kingdoms || [];
    els.kingdoms.innerHTML = '';
    if (!rows.length) { els.kingdoms.innerHTML = '<div class="context-empty">No kingdom rows loaded.</div>'; return; }
    for (const row of rows) {
      const button = document.createElement('button'); button.className = 'kingdom';
      button.innerHTML = `<span>${esc(row.canonical_name)}</span><span>${esc(row.origin_kind || 'taxon')}</span>`;
      button.onclick = () => loadTaxon(Number(row.taxon_id), true);
      els.kingdoms.append(button);
    }
  }

  function renderStats() {
    const b = state.bootstrap; if (!b) return;
    const s = b.stats || {};
    els.dataMode.textContent = b.mode === 'live' ? 'live taxonomy connected' : 'demo taxonomy · database not built yet';
    els.leftStats.textContent = `${fmtInt(s.taxa)} taxa · ${fmtInt(s.descriptor_assignments)} descriptor links`;
    els.modePill.textContent = b.mode === 'live' ? 'live' : 'demo';
  }

  function groupDescriptors() {
    const groups = {present:[], absent:[], variable:[]};
    for (const d of state.active?.descriptors || []) {
      const s = d.state || 'present'; if (groups[s]) groups[s].push(d);
    }
    return groups;
  }

  function renderContext() {
    if (!state.active || !state.active.taxon) {
      els.context.innerHTML = '<div class="context-empty">Select a kingdom, search for a taxon, or ask a question. Lineage and inherited evidence will appear here while Anemone answers.</div>';
      return;
    }
    const t = state.active.taxon;
    const lineage = state.active.lineage || [];
    const children = state.active.children || [];
    const groups = groupDescriptors();
    const filter = state.descriptorFilter;
    const descriptors = groups[filter] || [];
    const stats = state.bootstrap?.stats || {};
    const pct = stats.max_bytes ? Math.min(100, (Number(stats.bytes || 0) / Number(stats.max_bytes)) * 100) : 0;
    const jx = state.jx[state.mode] || state.jx[MODE[state.mode]?.leaf] || {};

    els.context.innerHTML = `
      <section class="taxon-card">
        <div class="taxon-rank">${esc(t.rank)}</div>
        <h2>${esc(t.canonical_name)}</h2>
        <p>${esc(t.common_name || t.scientific_name || '')}</p>
        <span class="origin">${esc(t.origin_kind || 'scientific')}</span>
      </section>
      <section class="context-section">
        <h3>Lineage</h3>
        <div class="lineage">${lineage.map(n => `<div class="lineage-node ${Number(n.taxon_id)===Number(t.taxon_id)?'active':''}"><span class="lineage-dot"></span><button data-taxon="${Number(n.taxon_id)}">${esc(n.canonical_name)}<small>${esc(n.rank)}</small></button></div>`).join('')}</div>
      </section>
      <section class="context-section">
        <h3>Effective descriptors</h3>
        <div class="descriptor-tabs">
          ${['present','absent','variable'].map(s => `<button data-descriptor-filter="${s}" class="${filter===s?'active':''}">${s} ${groups[s].length}</button>`).join('')}
        </div>
        <div class="descriptor-list">${descriptors.length ? descriptors.map(d => `<div class="descriptor"><div class="descriptor-top"><b>${esc(d.descriptor_text)}</b><span class="state ${esc(d.state)}">${esc(d.state)}</span></div><small>${esc(d.kind)} · from ${esc(d.from_rank || t.rank)} ${esc(d.from_name || t.canonical_name)}${Number(d.depth||0)>0?` · inherited ${Number(d.depth)} level${Number(d.depth)===1?'':'s'}`:' · local'}</small></div>`).join('') : '<div class="context-empty">No descriptors in this state.</div>'}</div>
      </section>
      <section class="context-section">
        <h3>Children</h3>
        <div class="child-row">${children.slice(0,25).map(c => `<button class="child-chip" data-taxon="${Number(c.taxon_id)}">${esc(c.canonical_name)}</button>`).join('') || '<span class="context-empty">No loaded children.</span>'}</div>
      </section>
      <section class="context-section">
        <h3>Corpus</h3>
        <div class="db-meter"><span style="width:${pct.toFixed(3)}%"></span></div>
        <div class="db-stats"><span>${fmtBytes(stats.bytes)}</span><span>${fmtBytes(stats.max_bytes)} ceiling</span></div>
      </section>
      <section class="context-section">
        <h3>JX browser leaf</h3>
        <div class="jx-box"><b>${esc(state.mode)}</b><br>${jx.error ? esc(jx.error) : `result=${esc(jx.result ?? '—')} · steps=${esc(jx.steps ?? '—')}`}<br>host=PASM/browser</div>
      </section>`;

    els.context.querySelectorAll('[data-taxon]').forEach((button) => button.addEventListener('click', () => loadTaxon(Number(button.dataset.taxon), false)));
    els.context.querySelectorAll('[data-descriptor-filter]').forEach((button) => button.addEventListener('click', () => { state.descriptorFilter = button.dataset.descriptorFilter; renderContext(); }));
  }

  async function loadTaxon(id, announce = false) {
    try {
      const payload = await api('taxon', {query:{taxon_id:id}});
      state.active = payload;
      renderContext();
      if (announce) {
        const msg = addMessage('assistant', `Opened ${payload.taxon.canonical_name}. It is a ${payload.taxon.rank} with ${payload.children.length} loaded child node${payload.children.length===1?'':'s'}.`);
        addChildChips(msg, payload.children);
      }
    } catch (error) {
      addMessage('assistant', `I could not open that taxon: ${error.message}`);
    }
  }

  function renderSearch(results) {
    els.searchResults.innerHTML = '';
    for (const row of results) {
      const button = document.createElement('button'); button.className = 'search-hit';
      button.innerHTML = `<b>${esc(row.canonical_name)}</b><span>${esc(row.rank)}${row.common_name?` · ${esc(row.common_name)}`:''}</span>`;
      button.onclick = () => { els.search.value = ''; els.searchResults.innerHTML = ''; loadTaxon(Number(row.taxon_id), true); };
      els.searchResults.append(button);
    }
  }

  function setMode(mode) {
    if (!MODE[mode]) return;
    state.mode = mode;
    els.modeTitle.textContent = MODE[mode].title;
    els.prompt.placeholder = MODE[mode].placeholder;
    els.nav.querySelectorAll('[data-mode]').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
    els.composerMeta.textContent = mode === 'compare' ? 'Select a taxon · comma-separate 2–3 word descriptors' : 'Enter to send · Shift+Enter for newline';
    runJxLeaf(MODE[mode].leaf);
    renderContext();
  }

  async function streamAsk(prompt) {
    const user = addMessage('user', prompt);
    void user;
    const assistant = addMessage('assistant', '');
    assistant.copy.classList.add('streaming');
    setThought(assistant, 'Starting JX request');
    state.busy = true; els.send.disabled = true;
    await runJxLeaf('ask');

    const url = new URL('api.php', location.href); url.searchParams.set('op','ask');
    try {
      const response = await fetch(url, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({prompt, taxon_id:state.active?.taxon?.taxon_id ?? null})
      });
      if (!response.ok || !response.body) throw new Error(`stream failed (${response.status})`);
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let pending = '';
      while (true) {
        const {value,done} = await reader.read();
        pending += decoder.decode(value || new Uint8Array(), {stream:!done});
        const lines = pending.split('\n'); pending = lines.pop() || '';
        for (const line of lines) {
          if (!line.trim()) continue;
          let event; try { event = JSON.parse(line); } catch (_) { continue; }
          if (event.type === 'status') setThought(assistant, event.label, event.label !== 'Ready');
          if (event.type === 'chunk') {
            assistant.text += event.text || '';
            assistant.copy.textContent = assistant.text;
            els.conversation.scrollTop = els.conversation.scrollHeight;
          }
          if (event.type === 'context') {
            state.active = {taxon:event.taxon,lineage:event.lineage || [],children:event.children || [],descriptors:state.active?.taxon?.taxon_id===event.taxon?.taxon_id?(state.active.descriptors||[]):[]};
            renderContext(); addChildChips(assistant, event.children || []);
          }
          if (event.type === 'evidence' && state.active) {
            state.active.descriptors = event.descriptors || [];
            state.active.taxon.origin_kind = event.origin_kind || state.active.taxon.origin_kind;
            state.active.taxon.source = event.source || state.active.taxon.source;
            renderContext();
          }
          if (event.type === 'done') setThought(assistant, '', false);
        }
        if (done) break;
      }
    } catch (error) {
      assistant.text += `${assistant.text ? '\n\n' : ''}Stream error: ${error.message}`;
      assistant.copy.textContent = assistant.text;
      setThought(assistant, '', false);
    } finally {
      assistant.copy.classList.remove('streaming'); state.busy = false; els.send.disabled = false; els.prompt.focus();
    }
  }

  async function compareDescriptors(raw) {
    if (!state.active?.taxon) {
      addMessage('assistant', 'Select a taxon first, then enter descriptors such as “hair covered, retractile claws, pack hunting”.');
      return;
    }
    const descriptors = raw.split(',').map(s => s.trim()).filter(Boolean).slice(0,30);
    if (!descriptors.length) return;
    addMessage('user', descriptors.join(', '));
    const message = addMessage('assistant', '');
    setThought(message, 'Comparing effective descriptors'); state.busy = true; els.send.disabled = true;
    await runJxLeaf('compare');
    try {
      const data = await api('compare', {body:{taxon_id:state.active.taxon.taxon_id, descriptors}});
      const r = data.result; const parts = [];
      for (const key of ['present','absent','variable','unknown']) if (r[key]?.length) parts.push(`${key}: ${r[key].map(x=>x.descriptor).join(', ')}`);
      message.text = `${data.taxon.canonical_name} — ${parts.join('; ')}.`;
      message.copy.textContent = message.text;
    } catch (error) { message.copy.textContent = `Comparison failed: ${error.message}`; }
    finally { setThought(message,'',false); state.busy=false; els.send.disabled=false; }
  }

  async function submit() {
    const prompt = els.prompt.value.trim(); if (!prompt || state.busy) return;
    els.prompt.value = '';
    if (state.mode === 'compare') await compareDescriptors(prompt); else await streamAsk(prompt);
  }

  function resetConversation() {
    state.active = null; state.descriptorFilter = 'present';
    els.conversation.innerHTML = `<div class="welcome" id="welcome"><h1>Ask the taxonomy.<br>Watch it reason.</h1><p>Anemone is ready for another lineage.</p><div class="suggestions"><button class="suggestion" data-prompt="Tell me about Canis lupus and show the traits it inherits."><b>Trace inheritance</b><span>Open a lineage and its inherited evidence.</span></button><button class="suggestion" data-prompt="Explore Animalia downward from the kingdom."><b>Walk the tree</b><span>Descend through loaded children.</span></button></div></div>`;
    bindSuggestions(); renderContext();
  }

  function bindSuggestions() {
    document.querySelectorAll('[data-prompt]').forEach(button => button.onclick = () => { els.prompt.value = button.dataset.prompt || ''; submit(); });
  }

  function bind() {
    els.send.onclick = submit;
    els.prompt.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); }
    });
    els.prompt.addEventListener('input', () => {
      els.prompt.style.height = 'auto'; els.prompt.style.height = `${Math.min(160, Math.max(52, els.prompt.scrollHeight))}px`;
    });
    els.nav.querySelectorAll('[data-mode]').forEach(button => button.onclick = () => setMode(button.dataset.mode));
    els.newChat.onclick = resetConversation;
    els.search.addEventListener('input', () => {
      clearTimeout(state.searchTimer); const q = els.search.value.trim();
      if (q.length < 2) { els.searchResults.innerHTML = ''; return; }
      state.searchTimer = setTimeout(async () => {
        try { const data = await api('search',{query:{q}}); renderSearch(data.results || []); }
        catch (_) { els.searchResults.innerHTML = ''; }
      }, 180);
    });
    bindSuggestions();
  }

  async function bootstrap() {
    bind();
    await runJxLeaf('home');
    try {
      state.bootstrap = await api('bootstrap');
      renderKingdoms(); renderStats();
      if (state.bootstrap.mode === 'demo') {
        const demo = document.createElement('div'); demo.className = 'thought'; demo.style.margin = '6px 0 0'; demo.innerHTML = '<span class="live-dot"></span><span>Demo data is live. Build the SQLite corpus to switch automatically.</span>';
        const welcome = $('welcome'); if (welcome) welcome.append(demo);
      }
    } catch (error) {
      els.dataMode.textContent = `API unavailable · ${error.message}`;
      els.kingdoms.innerHTML = '<div class="context-empty">Start a PHP server from this folder to connect the taxonomy API.</div>';
    }
    setMode('ask');
  }

  bootstrap();
})();
