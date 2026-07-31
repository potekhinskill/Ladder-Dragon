// SPDX-License-Identifier: MIT
// Copyright (c) 2026 IURII Potekhin
// Purpose: render the read-only Ladder Dragon dashboard without inline JavaScript.
const LOCALES = window.LadderDragonLocales || {defaultLocale:'en',labels:[['en','English']],translations:{en:{}}};
const LOCALE_KEY = 'ladder-dragon-locale';
const browserLocale = (navigator.language||'en').toLowerCase().split('-')[0];
const storedLocale = localStorage.getItem(LOCALE_KEY);
let CURRENT_LOCALE = LOCALES.translations[storedLocale] ? storedLocale : (LOCALES.translations[browserLocale] ? browserLocale : LOCALES.defaultLocale);
function tr(key, vars={}){
  const fallback = LOCALES.translations[LOCALES.defaultLocale] || {};
  const dict = LOCALES.translations[CURRENT_LOCALE] || fallback;
  return String(dict[key] ?? fallback[key] ?? key).replace(/\{(\w+)\}/g, (_, name)=>String(vars[name] ?? `{${name}}`));
}
const POSITION_STATUS_KEYS = Object.freeze({
  partial_inventory_lots: 'position_status_partial_inventory_lots',
  verified_full_inventory: 'position_status_verified_full_inventory',
  unverified_inventory_history: 'position_status_unverified_inventory_history',
  unavailable: 'position_status_unavailable',
  confirmed: 'position_status_confirmed',
  pending: 'position_status_pending',
  missing_or_incomplete: 'position_status_missing_or_incomplete',
  not_applicable: 'position_status_not_applicable',
  not_checked: 'position_status_not_checked',
  managed_lot_armed_only: 'position_status_managed_lot_armed_only',
  not_applicable_legacy_inventory: 'position_status_not_applicable_legacy_inventory',
  unmanaged_unprotected: 'position_status_unmanaged_unprotected',
  journal_exchange_mismatch: 'position_status_journal_exchange_mismatch'
});
function positionStatusText(code){
  return tr(POSITION_STATUS_KEYS[String(code||'')] || 'position_status_unknown');
}
function positionProtectionTone(code){
  const normalized=String(code||'');
  if(normalized==='confirmed'||normalized==='armed') return 'ok';
  if(normalized==='missing_or_incomplete'||normalized==='journal_exchange_mismatch'||normalized==='warning') return 'bad';
  return 'warn';
}
function userStreamSummary(stream){
  const symbol=String(stream.symbol||'').toUpperCase();
  const state=String(stream.state||'');
  if(state==='not_configured_or_not_started'){
    return `🟡 ${symbol} · ${tr('user_stream_not_started')} · ${tr('user_stream_rest_fallback')}`;
  }
  if(state==='connected'&&!stream.stale&&!stream.last_error){
    const session=Number(stream.current_session_hours||0);
    const age=stream.order_events>0&&stream.age_sec!=null?` · ${tr('user_stream_last_event')} ${fmt(stream.age_sec,0)}s`:'';
    return `🟢 ${symbol} · ${tr('user_stream_connected')} · ${tr('user_stream_session')} ${fmt(session,2)}h${age}`;
  }
  return `🔴 ${symbol} · ${stream.stale?tr('user_stream_stale'):tr('user_stream_unavailable')}`;
}
function userStreamDiagnostics(streams){
  const labels=[
    ['sessions','sessions'],['order_events','events'],['bad_frames','bad frames'],
    ['duplicates','duplicates'],['out_of_order_events','out-of-order'],
    ['reconnects','reconnects'],['connection_attempts','connection attempts'],
    ['disconnects','disconnects']
  ];
  return streams.flatMap(stream=>{
    const prefix=String(stream.symbol||'').toUpperCase();
    const counters=labels
      .filter(([key])=>Number(stream[key]||0)>0)
      .map(([key,label])=>`${label} ${Number(stream[key])}`);
    if(stream.last_error) counters.push(`error ${String(stream.last_error)}`);
    return counters.length?[`${prefix} · ${counters.join(' · ')}`]:[];
  });
}
function applyLocale(){
  document.documentElement.lang = CURRENT_LOCALE;
  document.querySelectorAll('[data-i18n]').forEach(el=>{ el.textContent = tr(el.dataset.i18n); });
  const select = $('#language-select');
  if(select){ select.value = CURRENT_LOCALE; select.setAttribute('aria-label', tr('language')); }
  const subtitle = $('#subtitle'); if(subtitle) subtitle.textContent = tr('auto_refresh');
  const link = $('#changelog-link'); if(link) link.textContent = tr('changelog');
  const version = $('#product-version'); if(version && version.dataset.productName){ version.textContent = `${version.dataset.productName} — ${tr('version')} ${version.dataset.productVersion}`; }
}
function initLocalePicker(){
  const select = $('#language-select'); if(!select) return;
  select.replaceChildren(...LOCALES.labels.map(([id,label])=>new Option(label,id)));
  select.value = CURRENT_LOCALE;
  select.addEventListener('change', ()=>{ CURRENT_LOCALE=LOCALES.translations[select.value] ? select.value : LOCALES.defaultLocale; localStorage.setItem(LOCALE_KEY,CURRENT_LOCALE); applyLocale(); refresh(); refreshOrders(); refreshOpenOrders(); });
}
const $ = s=>document.querySelector(s);
const fmt = (x,d=2)=> (Number.isFinite(x)?Number(x).toFixed(d):'—');
const unresolvedFillText = knowledge => {
  const total = Number(knowledge?.unresolved_fills || 0);
  const attribution = Number(
    knowledge?.unresolved_attribution_fills || 0
  );
  const inventory = Number(knowledge?.unresolved_inventory_fills || 0);
  return `${total} · attribution ${attribution} / inventory ${inventory}`;
};
const NF2 = new Intl.NumberFormat('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2});
const NF4 = new Intl.NumberFormat('ru-RU',{minimumFractionDigits:4,maximumFractionDigits:4});
const LOG_MAX_LINES = 500; // Keep at most 500 log lines in the dashboard.
const LOG_TAIL_BYTES = 256 * 1024;
const FILLED_PAGE_SIZE = 300;

let SYMBOLS_CACHE = null;      // Cached comma-separated symbols.
let SYMBOLS_TS = 0;
let BALANCE_SNAPSHOT = null;   // Last read-only snapshot used by the local filter.

function setPill(el, state){ el.classList.remove('ok','warn','bad'); el.classList.add(state); }
function mountLine(mounts, mp, id){
  const m = mounts.find(x=>x.mountpoint===mp);
  const el = $(id);
  if(!m){ el.textContent = mp+' — none'; return; }
  const flags = m.opts.split(',').filter(o=>['rw','ro','noatime'].includes(o)).join(',');
  el.textContent = `${mp} ${flags||'rw'}`;
}

const API_RESPONSE_CACHE = new Map();
const API_RESPONSE_CACHE_TTL_MS = 300000;
const API_RESPONSE_CACHE_MAX_KEYS = 24;
const API_RESPONSE_CACHE_MAX_ENTRY_BYTES = 128 * 1024;
const API_RESPONSE_CACHE_MAX_BYTES = 512 * 1024;
const FETCH_TIMEOUT_MS = 8000;
const ACTIVE_FETCH_CONTROLLERS = new Set();

function payloadSize(payload){
  try{ return JSON.stringify(payload).length * 2; }
  catch(_error){ return API_RESPONSE_CACHE_MAX_ENTRY_BYTES + 1; }
}

function trimResponseCache(){
  let total = [...API_RESPONSE_CACHE.values()].reduce((sum,entry)=>sum+(entry.size||0),0);
  while(API_RESPONSE_CACHE.size > API_RESPONSE_CACHE_MAX_KEYS || total > API_RESPONSE_CACHE_MAX_BYTES){
    const oldest = API_RESPONSE_CACHE.keys().next().value;
    if(oldest === undefined) break;
    total -= API_RESPONSE_CACHE.get(oldest)?.size || 0;
    API_RESPONSE_CACHE.delete(oldest);
  }
}

function cacheResponse(url,payload){
  const size = payloadSize(payload);
  if(size > API_RESPONSE_CACHE_MAX_ENTRY_BYTES) return;
  API_RESPONSE_CACHE.delete(url);
  API_RESPONSE_CACHE.set(url,{payload,cachedAt:Date.now(),size});
  trimResponseCache();
}

async function fetchWithTimeout(url,options={},timeoutMs=FETCH_TIMEOUT_MS){
  const controller = new AbortController();
  const timer = setTimeout(()=>controller.abort('timeout'),timeoutMs);
  ACTIVE_FETCH_CONTROLLERS.add(controller);
  try{
    return await fetch(url,{...options,signal:controller.signal});
  }finally{
    clearTimeout(timer);
    ACTIVE_FETCH_CONTROLLERS.delete(controller);
  }
}

function abortActiveFetches(){
  for(const controller of ACTIVE_FETCH_CONTROLLERS) controller.abort('page inactive');
  ACTIVE_FETCH_CONTROLLERS.clear();
}

async function getJSON(url){
  try{
    const r = await fetchWithTimeout(url,{cache:'no-store'});
    if(!r.ok) throw new Error(`HTTP ${r.status}`);
    const payload = await r.json();
    if(url !== '/api/security/csrf'){
      cacheResponse(url,payload);
    }
    return payload;
  }catch(error){
    if(url !== '/api/security/csrf' && API_RESPONSE_CACHE.has(url)){
      const entry = API_RESPONSE_CACHE.get(url);
      if(entry && Date.now() - entry.cachedAt <= API_RESPONSE_CACHE_TTL_MS){
        const cached = entry.payload;
        if(cached && typeof cached === 'object' && !Array.isArray(cached)){
          return {...cached, stale:true, transport_stale:true, transport_error:String(error)};
        }
        return cached;
      }
      API_RESPONSE_CACHE.delete(url);
    }
    throw error;
  }
}

let charts;
function ensureCharts(){
  if(charts) return;
  const base = {
    type:'line',
    options:{
      responsive:true,maintainAspectRatio:false,animation:false,resizeDelay:100,
      plugins:{legend:{display:false}},
      scales:{x:{ticks:{color:'#9aa6b2'}},y:{ticks:{color:'#9aa6b2'}}}
    }
  };
  charts = {
    t: new Chart($('#chartTemp'), { ...base, data:{labels:[],datasets:[{data:[],borderWidth:2}]} }),
    c: new Chart($('#chartCPU'),  { ...base, data:{labels:[],datasets:[{data:[],borderWidth:2}]} }),
    m: new Chart($('#chartMem'),  { ...base, data:{labels:[],datasets:[{data:[],borderWidth:2}]} }),
    v: new Chart($('#chartTradingVolume'), { ...base, data:{labels:[],datasets:[{data:[],borderWidth:2}]} }),
  };
}

function updateKpis(h){
  const product = h.product || {};
  const versionEl = $('#product-version');
  if(versionEl){ versionEl.dataset.productName = product.name || 'Ladder Dragon'; versionEl.dataset.productVersion = product.version || '—'; }
  applyLocale();
  $('#changelog-link').href = h.changelog_url || '/CHANGELOG.md';

  // Temperature.
  $('#temp-val').textContent = h.temp_c!=null ? `${h.temp_c.toFixed(1)} °C` : '— °C';
  setPill($('#temp-pill'), h.temp_c==null ? 'warn' : (h.temp_c>=80?'bad':'ok'));

  // Memory.
  const mt=h.mem_gib?.total, mu=h.mem_gib?.used, mp=h.mem_gib?.percent;
  $('#mem-val').textContent = `${fmt(mu)}/${fmt(mt)} GiB`;
  $('#mem-pct').textContent = Number.isFinite(mp)?`${mp}%`:'—%';
  $('#mem-bar').style.width = Number.isFinite(mp)?`${mp}%`:'0%';

  // Swap
  const st=h.swap_gib?.total, su=h.swap_gib?.used, sp=h.swap_gib?.percent;
  $('#swap-val').textContent = `${fmt(su)}/${fmt(st)} GiB`;
  $('#swap-pct').textContent = Number.isFinite(sp)?`${sp}%`:'—%';
  $('#swap-bar').style.width = Number.isFinite(sp)?`${sp}%`:'0%';

  // Disk.
  const dt=h.disk_gib?.total, du=h.disk_gib?.used, dp=h.disk_gib?.percent;
  $('#disk-val').textContent = `${fmt(du)}/${fmt(dt)} GiB`;
  $('#disk-pct').textContent = Number.isFinite(dp)?`${dp}%`:'—%';
  $('#disk-bar').style.width = Number.isFinite(dp)?`${dp}%`:'0%';

  // Mounts.
  mountLine(h.mounts||[], h.host?.root_mount || '/', '#mnt-root');
  mountLine(h.mounts||[], '/tmp', '#mnt-tmp');
  mountLine(h.mounts||[], '/var/tmp', '#mnt-vtmp');

  // Services.
  const s = (h.services?.mybot||'').trim();
  $('#bot-status').textContent = s || '—';
  $('#dot-bot').style.background = s==='active' ? '#21c07a' : (s ? '#f3c24d' : '#ff6e6e');
  $('#bans').textContent = `${h.services?.fail2ban_sshd_bans ?? 0} ${tr('bans')}`;

  // Network.
  $('#net-text').textContent = tr(h.network_ok ? 'online' : 'offline');
  $('#dot-net').style.background = h.network_ok ? '#21c07a' : '#ff6e6e';

  // System.
  $('#kernel').textContent = `kernel ${h.kernel||'—'}`;
  const up = h.uptime_sec|0; const d=Math.floor(up/86400), H=Math.floor((up%86400)/3600), M=Math.floor((up%3600)/60);
  $('#uptime').textContent = `uptime ${d?d+'d ':''}${H}h ${M}m`;

  // Footer.
  $('#footer').textContent = `API ok · ${h.time}`;
}

function ageText(seconds){
  if(!Number.isFinite(Number(seconds))) return '—';
  const s=Math.max(0,Math.floor(Number(seconds)));
  if(s<60) return `${s}s ago`;
  if(s<3600) return `${Math.floor(s/60)}m ago`;
  return `${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}m ago`;
}
function bytesText(bytes){
  if(!Number.isFinite(Number(bytes))) return '—';
  const n=Number(bytes); return n>=1024*1024 ? `${(n/1024/1024).toFixed(1)} MiB` : `${Math.round(n/1024)} KiB`;
}
function esc(value){
  return String(value ?? '—').replace(/[&<>"']/g, ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function updateOperations(h){
  const o=h.operations||{}, load=o.load_avg||{};
  $('#ops-load').textContent=[load['1m'],load['5m'],load['15m']].map(x=>Number.isFinite(Number(x))?Number(x).toFixed(2):'—').join(' / ');
  const bot=o.services?.mybot||{}, heartbeat=o.heartbeat||{};
  $('#ops-heartbeat').textContent=heartbeat.state ? `${heartbeat.state} · ${ageText(heartbeat.age_sec)}` : '—';
  $('#ops-heartbeat').className=heartbeat.fresh?'risk-ok':'risk-bad';
  $('#ops-restart').textContent=bot.started_at ? `${bot.started_at} · restarts ${bot.restart_count??0}` : '—';
  const ntp=o.ntp||{}, ping=o.binance||{};
  $('#ops-ntp').textContent=`${ntp.synchronized?'OK':'no'} · offset ${ping.offset_ms!=null?fmt(ping.offset_ms,0)+' ms':'—'}`;
  $('#ops-binance-latency').textContent=ping.ok
    ? `${Math.abs(Number(ping.offset_ms||0))>1000||Number(ping.latency_ms)>1000?'WARNING · ':''}${fmt(ping.latency_ms,0)} ms · offset ${fmt(ping.offset_ms,0)} ms`
    : `error: ${ping.error||'—'}`;
  const throttle=h.throttled||{};
  const host=h.host||{};
  $('#ops-platform').textContent=host.system ? `${host.system} · ${host.machine||'—'}${host.is_raspberry_pi?' · Raspberry Pi':''}` : tr('unavailable');
  const throttleBad=['under_voltage_now','freq_capped_now','throttled_now','temp_limit_now','under_voltage_hist','freq_capped_hist','throttled_hist','temp_limit_hist'].some(k=>throttle[k]);
  $('#ops-throttle').textContent=throttle.supported===false ? tr('unavailable') : (throttleBad ? `WARNING · ${throttle.raw||'—'}` : `OK · ${throttle.raw||'throttled=0x0'}`);
  const watchdog=o.services?.watchdog||{};
  $('#ops-watchdog').textContent=`${watchdog.state||'unknown'} · ${watchdog.enabled?tr('enabled'):tr('disabled')}`;
  $('#ops-watchdog').className=(watchdog.state==='active'&&watchdog.enabled)?'risk-ok':'risk-warn';
  const streams=o.user_stream?.streams||[];
  $('#ops-user-stream').textContent=streams.length?streams.map(userStreamSummary).join(', '):tr('no_data');
  $('#ops-user-stream').className=streams.length&&streams.every(s=>s.state==='connected'&&!s.stale&&!s.last_error)?'risk-ok':'risk-warn';
  const streamDiagnostics=userStreamDiagnostics(streams);
  const streamDetails=$('#ops-user-stream-details');
  streamDetails.hidden=streamDiagnostics.length===0;
  $('#ops-user-stream-diagnostics').textContent=streamDiagnostics.join('\n');
  const usb=o.usb_backup||{};
  $('#ops-usb').textContent=usb.mounted?`mounted · ${usb.writable?'rw':'dashboard namespace RO'}`:'not mounted';
  $('#ops-usb').className=usb.mounted?(usb.writable?'risk-ok':'risk-warn'):'risk-bad';
  $('#ops-usb-free').textContent=usb.free_gib!=null?`${fmt(usb.free_gib,2)} GiB · ${fmt(usb.used_percent,1)}% used`:'—';
  const disk=h.disk_gib||{};
  $('#ops-root-free').textContent=(disk.total!=null&&disk.used!=null)?`${fmt(Number(disk.total)-Number(disk.used),2)} / ${fmt(disk.total,2)} GiB free`:'—';
  const backup=o.backup||{};
  $('#ops-backup').textContent=backup.status||'—';
  const latest=backup.last_success||{};
  $('#ops-backup-age').textContent=latest.updated_at?`${latest.updated_at} · ${ageText(latest.age_sec)}`:'—';
  $('#ops-backup-size').textContent=bytesText(latest.size_bytes);
  $('#ops-backup-reason').textContent=backup.reason||tr('no');
}
function updateTrading(t){
  const mode=String(t.execution_mode||'UNKNOWN').toUpperCase();
  const banner=$('#execution-banner'); banner.textContent=`${mode} · ${(t.symbols||[]).join(', ')||'—'}`; banner.className=`live-banner ${mode==='LIVE'?'live':(mode==='DRY'?'dry':(mode==='STOPPED'?'stopped':''))}`;
  $('#trade-free-usdt').textContent=fmtUSDT(Number(t.free_usdt));
  $('#trade-reserve').textContent=t.reserve_usdt!=null?fmtUSDT(Number(t.reserve_usdt)):'—';
  const caps=t.caps||{};
  const activeCap=caps.per_order_usdt!=null?fmtUSDT(Number(caps.per_order_usdt)):'—';
  const hardCap=caps.operator_hard_usdt!=null?fmtUSDT(Number(caps.operator_hard_usdt)):'—';
  $('#trade-cap-order').textContent=`${activeCap} · hard ${hardCap}`;
  $('#trade-cap-portfolio').textContent=caps.portfolio_usdt!=null?fmtUSDT(Number(caps.portfolio_usdt)):'—';
  const perSymbol=caps.per_symbol||{};
  $('#trade-cap-symbol').textContent=Object.keys(perSymbol).length?Object.entries(perSymbol).map(([s,v])=>`${s} ${v}`).join(', '):'—';
  const risk=t.risk||{}, blocked=Boolean(risk.buy_blocked||risk.halted);
  $('#trade-risk').textContent=risk.halted?'HALTED':(risk.buy_blocked?'BUY BLOCKED':'OK');
  $('#trade-risk').className=blocked?'risk-bad':'risk-ok';
  $('#trade-risk-reasons').textContent=Array.isArray(risk.reasons)&&risk.reasons.length?risk.reasons.join(' · '):tr('no');
  const cooldown=Number(risk.cooldown_until||0);
  $('#trade-cooldown').textContent=cooldown>Math.floor(Date.now()/1000)?new Date(cooldown*1000).toLocaleString(CURRENT_LOCALE):tr('no');
  $('#trade-recon').textContent=risk.reconciliation_delta!=null?JSON.stringify(risk.reconciliation_delta):tr('no_data');
  const orders=t.orders||{};
  const orderSummary=$('#trade-order-summary');
  if(orders.journal_available===false){
    orderSummary.textContent=`${orders.open??0} / — / — · ${tr('unavailable')}`;
    orderSummary.title=orders.journal_reason||tr('unavailable');
    orderSummary.className='risk-warn';
  }else{
    orderSummary.textContent=`${orders.open??0} / ${orders.cancelled??0} / ${orders.pending??0}`;
    orderSummary.title='';
    orderSummary.className='';
  }
  const reanchor=t.reanchor||{}, reanchorTotals=reanchor.totals||{};
  const triggerPct=Number(reanchor.trigger_pct);
  $('#trade-reanchor').textContent=reanchor.mode
    ? `${reanchor.mode} · trigger ${Number.isFinite(triggerPct)?fmt(triggerPct*100,3)+'%':'—'} · age ${reanchor.min_age_sec??'—'}s`
    : '—';
  const symbolStates=reanchor.symbols||{};
  const latestProposal=Object.values(symbolStates).flatMap(state=>Array.isArray(state?.proposals)?state.proposals:[])[0];
  $('#trade-reanchor-activity').textContent=`shadow ${reanchorTotals.shadow_candidates??0} · apply ${reanchorTotals.apply_cancels??0}`+
    (latestProposal?` · ${latestProposal.old_price}→${latestProposal.target_price}`:'');
  const last=t.last_order;
  const lifecycle=orders.lifecycle||{};
  const exact=Number(lifecycle.closed_exact||0), required=Number(lifecycle.required||3);
  const cycleNode=$('#trade-canary-cycles');
  cycleNode.textContent=`${exact} / ${required} · TP ${Number(lifecycle.tp||0)} · STOP ${Number(lifecycle.stop||0)}`;
  cycleNode.className=lifecycle.promotion_ready?'risk-ok':'risk-warn';
  $('#trade-last-order').textContent=last?`${last.symbol} ${last.side} ${last.status} id=${last.order_id??'—'}${last.partial_fill?' partial':''} · latency ${last.latency_ms??'—'} ms · fee ${last.commission_usdt??'—'} · ${last.updated_at||'—'}`:tr('no');
  const rows=Array.isArray(t.positions)?t.positions:[];
  $('#positions-body').innerHTML=rows.length?rows.map(p=>{
    const protection=p.protection||{};
    const state=protection.state||'not_checked';
    const managedQty=Number(p.managed_quantity||0), legacyQty=Number(p.legacy_quantity||0);
    const lockedQty=Math.max(0,Number(protection.locked_quantity||0));
    const managedProtectedQty=Math.min(managedQty,lockedQty);
    const managedUnprotectedQty=Math.max(0,managedQty-managedProtectedQty);
    const managedState=protection.managed_state||state;
    const managedTone=positionProtectionTone(managedState);
    const asset=String(p.base_asset||p.symbol||'').replace(/USDT$/,'');
    const protectionRequired=managedQty>0&&managedUnprotectedQty>1e-12;
    const protectionConfirmed=managedQty>0&&!protectionRequired&&managedTone==='ok';
    const statusIcon=protectionRequired?'🔴':(protectionConfirmed?'🟢':'🟡');
    const statusKey=protectionRequired?'position_action_required':(protectionConfirmed?'position_protection_confirmed':'position_legacy_only');
    const basisHidden=p.average_entry_usdt==null||p.unrealized_pnl_usdt==null;
    return `<article class="position-card">
      <div class="position-card-head">
        <div class="position-symbol mono">${esc(p.symbol)}</div>
        <div class="position-alert ${protectionRequired?'bad':(protectionConfirmed?'ok':'warn')}">${statusIcon} ${esc(tr(statusKey))}</div>
      </div>
      <div class="position-summary">
        <div><span>${esc(tr('position_managed_position'))}</span><strong class="mono">${fmt(managedQty,8)} ${esc(asset)}</strong></div>
        <div><span>${esc(tr('position_protected'))}</span><strong class="mono">${fmt(managedProtectedQty,8)} ${esc(asset)}</strong></div>
        <div><span>${esc(tr('position_unprotected'))}</span><strong class="mono ${protectionRequired?'position-unprotected':''}">${fmt(managedUnprotectedQty,8)} ${esc(asset)}</strong></div>
      </div>
      ${protectionRequired?`<p class="position-buy-blocked">${esc(tr('position_new_buys_blocked'))}</p>`:''}
      <div class="position-summary position-account">
        <div><span>${esc(tr('position_total_balance'))}</span><strong class="mono">${fmt(p.quantity,8)} ${esc(asset)}</strong></div>
        <div><span>${esc(tr('position_legacy_outside'))}</span><strong class="mono">${fmt(legacyQty,8)} ${esc(asset)}</strong></div>
      </div>
      ${basisHidden?`<p class="position-basis-hidden">${esc(tr('position_basis_hidden'))}</p>`:''}
    </article>`;
  }).join(''):`<div class="position-empty muted">${esc(tr('no_positions'))}</div>`;
}
function updateAIQuality(ai){
  const src=ai.data_sources||{}, usage=ai.usage_today||{}, kb=ai.knowledge_base||{};
  $('#ai-context-age').textContent=ageText(src.context_age_sec);
  $('#ai-decision-db-age').textContent=ageText(src.decision_db_age_sec);
  $('#ai-usage-age').textContent=ageText(src.usage_log_age_sec);
  const limits=(ai.runtime||{}).budgets||{};
  $('#ai-budget').textContent=`${usage.requests??0}/${limits.max_requests_per_day??'—'} req · ${usage.tokens??0}/${limits.max_tokens_per_day??'—'} tok · $${usage.cost_usd??'0'}/$${limits.max_cost_usd_per_day??'—'}`;
  $('#ai-errors').textContent=`${usage.recent_errors??0} recent · ${usage.errors??0} total`;
  const recent=Array.isArray(ai.recent)?ai.recent:[];
  const rejected=recent.filter(row=>String(row.status||'').toUpperCase()==='REJECTED').length;
  $('#ai-decisions-quality').textContent=`${ai.applied_count??0} applied / ${rejected} rejected`;
  $('#ai-unresolved-quality').textContent=unresolvedFillText(kb);
  const edge=ai.ai_vs_baseline_1h||{};
  $('#ai-edge-quality').textContent=edge.samples?`${fmt(Number(edge.edge)*100,2)}% / ${edge.samples}`:tr('no_data');
  $('#ai-rag-quality').textContent=`${kb.documents??0} / ${kb.archived_virtual_documents??0} / ${kb.retrievals??0}`;
  const degraded=Array.isArray(ai.degraded_reasons)?ai.degraded_reasons:[];
  $('#ai-degraded-quality').textContent=degraded.length?degraded.join(' · '):tr('no');
}

/* USDT and percentage formatting. */
function fmtUSDT(x){
  if(!Number.isFinite(x)) return '—';
  return NF2.format(x) + ' USDT';
}
function fmtPct(p){
  if(!Number.isFinite(p)) return '—';
  const sign = p>0?'+':'';
  return `${sign}${p.toFixed(2)}%`;
}

/* --- symbol discovery (once per minute) --- */
async function getSymbols(){
  const now = Date.now();
  if(SYMBOLS_CACHE && (now - SYMBOLS_TS) < 60_000) return SYMBOLS_CACHE;
  try{
    const j = await getJSON('/api/trades/symbols?hours=168');
    const arr = (j && j.ok && Array.isArray(j.symbols)) ? j.symbols : [];
    SYMBOLS_CACHE = arr.join(',');
    SYMBOLS_TS = now;
    return SYMBOLS_CACHE;
  }catch(e){
    return SYMBOLS_CACHE || '';
  }
}

/* Fetch the summary with the symbols= filter when possible. */
async function getTradeSummary24h(){
  const symbols = await getSymbols();
  const urls = [
    `/api/trades/summary?hours=24${symbols?`&symbols=${encodeURIComponent(symbols)}`:''}`,
    `/api/bot/trades/summary?hours=24${symbols?`&symbols=${encodeURIComponent(symbols)}`:''}`,
    '/api/stats/24h'
  ];
  for(const u of urls){
    try{
      const j = await getJSON(u);
      if(j) return {ok:true, data:j, url:u};
    }catch(e){}
  }
  return {ok:false};
}

function updateTrade24(sum, balances){
  const pill = $('#t24-pill');
  const setNA = ()=>{
    $('#t24-trades').textContent='—';
    $('#t24-volume').textContent='—';
    $('#t24-fees').textContent='—';
    $('#t24-portfolio').textContent='—';
    $('#t24-portfolio-sub').textContent='';
    $('#t24-fifo').textContent='—';
    $('#t24-fifo-sub').textContent='';
    $('#t24-cashflow').textContent='—';
    $('#t24-equity').textContent='—';
    $('#t24-assets').textContent='';
  };

  if(!sum || !sum.ok){
    setPill(pill,'warn'); pill.textContent=tr('no_data');
    setNA(); return;
  }
  setPill(pill,'ok'); pill.textContent='ok';
  const d = sum.data;

  const trades = d.total_trades ?? d.count ?? d.trades ?? d.num_trades ?? null;
  const vol    = d.sell_volume_usdt ?? d.volume_sell_usdt ?? d.sell_usdt ?? d.volume_usdt ?? null;
  const fees   = d.fees_usdt ?? d.total_fees_usdt ?? d.total_fees ?? null;

  const summaryEqNow = (d.equity_now_usdt ?? d.equity_now_usdt_approx ?? null);
  // The account total must use the same live Binance snapshot as the balances
  // table. The symbol-filtered summary remains responsible only for 24h PnL.
  const liveAccountTotal = balances?.ok ? Number(balances.total_value_usdt) : NaN;
  const eqNow = Number.isFinite(liveAccountTotal) ? liveAccountTotal : summaryEqNow;
  const eqThen = d.equity_then_usdt ?? null;
  const portfolioChange = (d.portfolio_change_usdt ?? d.equity_pnl_usdt ?? null);
  const fifoPnl = (d.net_pnl_usdt ?? d.realized_pnl_usdt ?? null);
  const cashflowPnl = (d.cashflow_pnl_usdt ?? null);

  $('#t24-trades').textContent = Number.isFinite(trades) ? trades : '—';
  $('#t24-volume').textContent = fmtUSDT(vol);
  $('#t24-fees').textContent   = fmtUSDT(fees);

  // Current equity (an approximation is acceptable here).
  $('#t24-equity').textContent = Number.isFinite(eqNow) ? fmtUSDT(eqNow) : '—';

  // Portfolio change is mark-to-market and is not bot earnings.
  const pct = Number.isFinite(d.equity_pct) ? d.equity_pct
             : (Number.isFinite(portfolioChange) && Number.isFinite(eqThen) && eqThen>0 ? (portfolioChange/eqThen*100) : null);

  const portfolioEl = $('#t24-portfolio');
  portfolioEl.textContent = Number.isFinite(portfolioChange) ? fmtUSDT(portfolioChange) : '—';
  portfolioEl.style.color = (Number.isFinite(portfolioChange) && portfolioChange < 0) ? 'var(--bad)' : 'var(--ok)';
  $('#t24-portfolio-sub').textContent = Number.isFinite(pct) ? `(${fmtPct(pct)})` : '';

  // FIFO PnL realizes the historical lot cost only for SELL fills in the window.
  const fifoEl = $('#t24-fifo');
  fifoEl.textContent = Number.isFinite(fifoPnl) ? fmtUSDT(fifoPnl) : '—';
  fifoEl.style.color = (Number.isFinite(fifoPnl) && fifoPnl < 0) ? 'var(--bad)' : 'var(--ok)';
  const fifoExcluded = Array.isArray(d.realized_pnl_excluded_symbols)
    ? d.realized_pnl_excluded_symbols : [];
  $('#t24-fifo-sub').textContent = d.realized_pnl_status==='incomplete_fifo_history'
    ? `${tr('fifo_history_incomplete')}: ${fifoExcluded.join(', ')||'—'}`
    : '';

  // Cash flow uses only BUY/SELL notional and fees that occurred in the window.
  const cashflowEl = $('#t24-cashflow');
  cashflowEl.textContent = Number.isFinite(cashflowPnl) ? fmtUSDT(cashflowPnl) : '—';
  cashflowEl.style.color = (Number.isFinite(cashflowPnl) && cashflowPnl < 0) ? 'var(--bad)' : 'var(--ok)';

  // Assets included in the equity calculation.
  if (Array.isArray(d.equity_assets) && d.equity_assets.length){
    $('#t24-assets').textContent = `${tr('assets_in_equity')}: ` + d.equity_assets.join(', ');
  }else{
    $('#t24-assets').textContent = '';
  }
}

function fmtQty(x){
  if(!Number.isFinite(Number(x))) return '—';
  return Number(x).toLocaleString('ru-RU',{minimumFractionDigits:0,maximumFractionDigits:8});
}

function updateBalances(snapshot){
  const pill = $('#balance-pill');
  const body = $('#balance-body');
  if(!snapshot || !snapshot.ok || !Array.isArray(snapshot.assets)){
    setPill(pill,'warn'); pill.textContent=tr('no_data');
    $('#balance-total').textContent='—';
    $('#balance-updated').textContent='—';
    body.innerHTML = `<tr><td class="muted" colspan="6">${tr('no_balance')}</td></tr>`;
    $('#balance-unvalued').textContent='';
    $('#balance-hidden').textContent='';
    return;
  }
  BALANCE_SNAPSHOT = snapshot;
  setPill(pill,snapshot.stale?'warn':'ok');
  pill.textContent=snapshot.stale?tr('stale'):tr('current');
  $('#balance-total').textContent = fmtUSDT(snapshot.total_value_usdt);
  $('#balance-updated').textContent = `${tr('updated')} ${snapshot.updated_at || '—'}`;
  const hideSmall = $('#balance-hide-small')?.checked ?? true;
  const hidden = hideSmall
    ? snapshot.assets.filter(row=>row.asset !== 'USDT' && (row.value_usdt == null || Number(row.value_usdt) < 1))
    : [];
  const visible = hideSmall
    ? snapshot.assets.filter(row=>!hidden.includes(row))
    : snapshot.assets;
  body.innerHTML = visible.length ? visible.map(row=>{
    const unvalued = row.valuation_status !== 'priced';
    return `<tr>
      <td class="mono">${escapeHtml(row.asset)}</td>
      <td class="right mono">${fmtQty(row.free)}</td>
      <td class="right mono">${fmtQty(row.locked)}</td>
      <td class="right mono">${fmtQty(row.total)}</td>
      <td class="right mono ${unvalued?'balance-unvalued':''}">${unvalued?tr('unvalued'):fmtUSDT(row.price_usdt)}</td>
      <td class="right mono ${unvalued?'balance-unvalued':''}">${unvalued?'—':fmtUSDT(row.value_usdt)}</td>
    </tr>`;
  }).join('') : `<tr><td class="muted" colspan="6">${tr('positive_balances')}</td></tr>`;
  const unvalued = Array.isArray(snapshot.unvalued_assets) ? snapshot.unvalued_assets : [];
  $('#balance-unvalued').textContent = unvalued.length
    ? `${tr('unvalued_assets')}: ${unvalued.join(', ')}`
    : '';
  $('#balance-hidden').textContent = hidden.length
    ? `${tr('hidden_assets')}: ${hidden.length}`
    : '';
}

function escapeHtml(value){
  return String(value ?? '—').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function updateOpenOrders(snapshot){
  const pill = $('#open-orders-pill');
  const body = $('#open-orders-body');
  if(!snapshot || !snapshot.ok || !Array.isArray(snapshot.orders)){
    setPill(pill,'warn'); pill.textContent=tr('no_data');
    $('#open-orders-updated').textContent='—';
    body.innerHTML = `<tr><td class="muted" colspan="10">${tr('unavailable')}</td></tr>`;
    return;
  }
  setPill(pill, snapshot.stale ? 'warn' : 'ok');
  pill.textContent = `${snapshot.count ?? snapshot.orders.length}${snapshot.stale ? ` · ${tr('stale')}` : ''}`;
  $('#open-orders-updated').textContent = `${tr('updated')} ${snapshot.updated_at || '—'}`;
  const rows = snapshot.orders.map(row=>{
    const side = escapeHtml(row.side || '—');
    const sideClass = row.side === 'BUY' ? 'side-buy' : (row.side === 'SELL' ? 'side-sell' : '');
    const price = Number(row.price);
    const stop = Number(row.stop_price);
    const created = Number(row.created_at);
    return `<tr>
      <td class="mono">${escapeHtml(row.symbol)}</td>
      <td class="${sideClass}">${side}</td>
      <td>${escapeHtml(row.type || '—')}</td>
      <td class="right mono">${Number.isFinite(price) && price > 0 ? NF4.format(price) : '—'}</td>
      <td class="right mono">${Number.isFinite(stop) && stop > 0 ? NF4.format(stop) : '—'}</td>
      <td class="right mono">${fmtQty(row.orig_qty)}</td>
      <td class="right mono">${fmtQty(row.executed_qty)}</td>
      <td class="right mono">${fmtQty(row.remaining_qty)}</td>
      <td>${escapeHtml(row.status || 'OPEN')}</td>
      <td class="nowrap">${Number.isFinite(created) && created > 0 ? tsShort(created * 1000) : '—'}</td>
    </tr>`;
  });
  body.innerHTML = rows.length
    ? rows.join('')
    : `<tr><td class="muted" colspan="10">${tr('no_open_orders')}</td></tr>`;
}

function updateCharts(hist){
  ensureCharts();
  charts.t.data.labels = hist.labels; charts.t.data.datasets[0].data = hist.temp_c; charts.t.update();
  charts.c.data.labels = hist.labels; charts.c.data.datasets[0].data = hist.cpu_pct; charts.c.update();
  charts.m.data.labels = hist.labels; charts.m.data.datasets[0].data = hist.mem_used_gib; charts.m.update();
  charts.v.data.labels = hist.labels;
  charts.v.data.datasets[0].data = (hist.trading_volume_24h_usdt||[]).map(value=>{
    const parsed=Number(value);
    return Number.isFinite(parsed)?parsed:null;
  });
  charts.v.update();
}

/* ==== Realized orders for the last 24 hours ==== */
let FILLED_PAGE = 0;
async function getFilledOrders24h(){
  const symbols = await getSymbols();
  const offset = FILLED_PAGE * FILLED_PAGE_SIZE;
  const urls = [
    `/api/trades/filled?hours=24&limit=${FILLED_PAGE_SIZE}&offset=${offset}${symbols?`&symbols=${encodeURIComponent(symbols)}`:''}`,
    `/api/orders/filled?hours=24&limit=${FILLED_PAGE_SIZE}&offset=${offset}${symbols?`&symbols=${encodeURIComponent(symbols)}`:''}`,
    `/api/fills?hours=24&limit=${FILLED_PAGE_SIZE}&offset=${offset}${symbols?`&symbols=${encodeURIComponent(symbols)}`:''}`
  ];
  for(const u of urls){
    try{
      const j = await getJSON(u);
      if(!j) continue;
      let arr = Array.isArray(j) ? j : (j.items||j.data||j.orders||j.trades||[]);
      if(!Array.isArray(arr)) continue;
      return {ok:true, url:u, items:arr, hasMore:arr.length===FILLED_PAGE_SIZE};
    }catch(e){}
  }
  return {ok:false, items:[]};
}

function normFill(o){
  const num = v => v==null ? null : (typeof v==='string'? parseFloat(v) : v);
  const time = o.time ?? o.transactTime ?? o.updateTime ?? o.T ?? (o.dt?Date.parse(o.dt):null);
  const symbol = o.symbol || o.pair || o.market || '—';
  let side = (o.side||'').toString().toUpperCase();
  if(!side){
    if (o.isBuyer===true) side='BUY';
    else if (o.isBuyer===false) side='SELL';
    else if (o.side_int!=null) side= o.side_int>0?'BUY':'SELL';
  }
  const price = num(o.price ?? o.avgPrice ?? o.executedPrice ?? o.lastFillPrice);
  const qty   = num(o.qty ?? o.executedQty ?? o.amount ?? o.baseQty);
  let quote   = num(o.quoteQty ?? o.cummulativeQuoteQty ?? o.quote_amount ?? (price!=null&&qty!=null?price*qty:null));
  const fee   = num(o.commission ?? o.fee_usdt ?? o.fee ?? o.fees);
  const feeAsset = o.commissionAsset || o.fee_asset || o.feeAsset || 'USDT';
  return {time, symbol, side, price, qty, quote, fee, feeAsset};
}

function tsShort(ms){
  if(!Number.isFinite(ms)) return '—';
  const d = new Date(ms), now = new Date();
  const sameDay = d.toDateString()===now.toDateString();
  return d.toLocaleString(CURRENT_LOCALE, sameDay
    ? {hour:'2-digit',minute:'2-digit'}
    : {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
}

function updateFilled24h(resp){
  const pill = $('#filled-pill');
  const tbody = $('#orders-body');
  if(!resp || !resp.ok){
    pill.textContent = tr('no_data'); setPill(pill,'warn');
    tbody.innerHTML = `<tr><td class="muted" colspan="7">${tr('no_data')}</td></tr>`;
    return;
  }
  setPill(pill,'ok'); pill.textContent='ok';
  $('#filled-page').textContent=String(FILLED_PAGE+1);
  $('#filled-prev').disabled=FILLED_PAGE===0;
  $('#filled-next').disabled=!resp.hasMore;

  const rows = resp.items.map(normFill)
    .filter(x=>x.time!=null)
    .sort((a,b)=>b.time-a.time)
    .map(x=>{
      const sideClass = x.side==='SELL' ? 'side-sell' : 'side-buy';
      const feeCell = Number.isFinite(x.fee)
        ? `${NF2.format(x.fee)} ${x.feeAsset||''}`.trim()
        : '—';
      // Strict formats: price 2 decimals, quantity 4, total 2.
      const priceTxt = Number.isFinite(x.price) ? NF2.format(x.price) : '—';
      const qtyTxt   = Number.isFinite(x.qty)   ? NF4.format(x.qty)   : '—';
      const quoteTxt = Number.isFinite(x.quote) ? NF2.format(x.quote) : '—';
      return `<tr>
        <td class="nowrap">${tsShort(x.time)}</td>
        <td>${escapeHtml(x.symbol)}</td>
        <td class="${sideClass}">${escapeHtml(x.side||'—')}</td>
        <td class="right mono">${priceTxt}</td>
        <td class="right mono">${qtyTxt}</td>
        <td class="right mono">${quoteTxt}</td>
        <td class="right mono">${escapeHtml(feeCell)}</td>
      </tr>`;
    });

  tbody.innerHTML = rows.length
    ? rows.join('')
    : `<tr><td class="muted" colspan="7">${tr('no_recent_fills')}</td></tr>`;
}

let REFRESH_IN_FLIGHT = false;
async function refresh(){
  if(REFRESH_IN_FLIGHT) return;
  REFRESH_IN_FLIGHT = true;
  try{
    const [h, hist, sum, ai, aiControl, balances, trading] = await Promise.all([
      getJSON('/api/health'),
      getJSON('/api/history?hours=24&points=288'),
      getTradeSummary24h(),
      getJSON('/api/ai/status?limit=100'),
      getJSON('/api/ai/control'),
      getJSON('/api/account/balances'),
      getJSON('/api/trading/overview')
    ]);
    updateKpis(h);
    updateCharts(hist);
    updateTrade24(sum, balances);
    updateBalances(balances);
    updateOperations(h);
    updateTrading(trading);
    updateAIQuality(ai);
    $('#ai-state').textContent = ai.state || '—';
    $('#ai-mode').textContent = ai.mode || '—';
    const runtime = ai.runtime || {};
    $('#ai-venue').textContent = [runtime.venue, runtime.execution_mode].filter(Boolean).join(' / ') || '—';
    $('#ai-model').textContent = [runtime.provider, runtime.model].filter(Boolean).join(' / ') || '—';
    const latest = Array.isArray(ai.recent) && ai.recent.length ? ai.recent[0] : {};
    $('#ai-decision-id').textContent = latest.decision_id || runtime.last_decision || '—';
    $('#ai-rationale').textContent = latest.rationale || (latest.policy_reasons || '—');
    $('#ai-runtime').textContent = runtime.connected
      ? `${runtime.stale ? tr('stale') : (runtime.process_state || tr('online_state'))} · ${runtime.updated_at ? tsShort(Date.parse(runtime.updated_at)) : '—'}`
      : tr('no');
    $('#ai-applied').textContent = ai.applied_count ?? 0;
    const edge = ai.ai_vs_baseline_1h || {};
    $('#ai-edge').textContent = edge.samples
      ? `${(Number(edge.edge)*100).toFixed(1)}% / ${edge.samples}`
      : tr('no_data');
    const knowledge = ai.knowledge_base || {};
    $('#ai-rag').textContent = `${knowledge.documents ?? 0} / ${knowledge.archived_virtual_documents ?? 0} / ${knowledge.retrievals ?? 0}`;
    const ragDocuments = Array.isArray(latest.rag_documents) ? latest.rag_documents : [];
    $('#ai-rag-recent').textContent = ragDocuments.length
      ? ragDocuments.map(item=>`${String(item.document_id).slice(0,8)}:${Number(item.score).toFixed(3)}`).join(', ')
      : tr('no');
    $('#ai-realized-pnl').textContent = fmtUSDT(Number(knowledge.realized_net_pnl_quote || 0));
    $('#ai-unresolved').textContent = unresolvedFillText(knowledge);
    $('#ai-degraded-reasons').textContent = Array.isArray(ai.degraded_reasons) && ai.degraded_reasons.length
      ? ai.degraded_reasons.join(', ')
      : tr('no');
    $('#ai-tokens').textContent = ai.usage_today?.tokens ?? 0;
    $('#ai-cost').textContent = `$${Number(ai.usage_today?.cost_usd || 0).toFixed(6)}`;
    const toggle = $('#ai-toggle');
    const enabled = Boolean(aiControl.enabled);
    toggle.disabled = !aiControl.configured;
    toggle.dataset.enabled = enabled ? 'true' : 'false';
    const visual = toggle.querySelector('.switch-visual');
    visual?.classList.toggle('on', enabled);
    toggle.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    toggle.setAttribute('aria-label', !aiControl.configured ? tr('ai_not_configured') : tr(enabled ? 'ai_on' : 'ai_off'));
    if([h, hist, sum, ai, aiControl, balances, trading].some(item=>item?.transport_stale)){
      $('#footer').textContent = `API: ${tr('stale')} · transport retry`;
    }
  }catch(e){
    $('#footer').textContent = `${tr('api_error')}: ${e}`;
  }finally{
    REFRESH_IN_FLIGHT = false;
  }
}

async function refreshGithubUpdate(){
  const status = $('#github-update-status');
  if(!status) return;
  const setState = (state, url='') => {
    status.classList.remove('is-current','is-available','is-unavailable');
    status.classList.add(`is-${state}`);
    if(state === 'available' && typeof url === 'string' && url.startsWith('https://github.com/')){
      status.href = url;
      status.setAttribute('aria-label', `${tr('github_update_available')}: GitHub`);
    }else{
      status.removeAttribute('href');
      status.removeAttribute('aria-label');
    }
  };
  try{
    const payload = await getJSON('/api/update/check');
    if(!payload.ok){
      status.textContent = tr('github_update_unavailable');
      status.title = payload.error || tr('github_update_unavailable');
      setState('unavailable');
      return;
    }
    const checked = payload.checked_at
      ? `${payload.checked_at} · ${ageText(payload.cache_age_sec)}`
      : ageText(payload.cache_age_sec);
    if(payload.stale){
      status.textContent = `GitHub: ${tr('stale')}`;
      status.title = `${payload.error || tr('stale')} · checked ${checked}`;
      setState('unavailable');
      return;
    }
    status.textContent = payload.update_available
      ? tr('github_update_available')
      : tr('github_update_current');
    status.title = payload.remote_commit
      ? `GitHub ${payload.branch || ''}: ${payload.remote_commit.slice(0,8)} · checked ${checked}`
      : `checked ${checked}`;
    setState(payload.update_available ? 'available' : 'current', payload.remote_url);
  }catch(e){
    status.textContent = tr('github_update_unavailable');
    status.title = String(e);
    setState('unavailable');
  }
}

async function toggleAI(){
  const button = $('#ai-toggle');
  if (button.disabled) return;
  const enabled = button.dataset.enabled === 'true';
  const action = enabled ? tr('disable') : tr('enable');
  if (!window.confirm(tr('confirm',{action}))) return;
  button.disabled = true;
  try{
    const csrf = await getJSON('/api/security/csrf');
    const response = await fetchWithTimeout('/api/ai/control', {
      method:'POST',
      headers:{'Content-Type':'application/json','X-CSRF-Token':csrf.csrf_token},
      body:JSON.stringify({enabled:!enabled}),
      cache:'no-store'
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || response.status);
    await refresh();
  }catch(e){
    $('#footer').textContent = `${tr('unable_ai')}: ${e}`;
    button.disabled = false;
  }
}

$('#ai-toggle').addEventListener('click', toggleAI);

const balanceFilter = $('#balance-hide-small');
if (balanceFilter){
  balanceFilter.checked = localStorage.getItem('balance-hide-small') !== '0';
  balanceFilter.addEventListener('change', ()=>{
    localStorage.setItem('balance-hide-small', balanceFilter.checked ? '1' : '0');
    if (BALANCE_SNAPSHOT) updateBalances(BALANCE_SNAPSHOT);
  });
}

$('#filled-prev').addEventListener('click',()=>{
  if(FILLED_PAGE===0 || FILLED_ORDERS_REFRESH_IN_FLIGHT) return;
  FILLED_PAGE-=1;
  refreshOrders();
});
$('#filled-next').addEventListener('click',()=>{
  if(FILLED_ORDERS_REFRESH_IN_FLIGHT) return;
  FILLED_PAGE+=1;
  refreshOrders();
});

/* Separate refresh so the existing refresh() does not need modification. */
let FILLED_ORDERS_REFRESH_IN_FLIGHT = false;
async function refreshOrders(){
  if(FILLED_ORDERS_REFRESH_IN_FLIGHT) return;
  FILLED_ORDERS_REFRESH_IN_FLIGHT = true;
  try{
    const fills = await getFilledOrders24h();
    updateFilled24h(fills);
  }catch(e){
    const pill = $('#filled-pill');
    setPill(pill,'bad'); pill.textContent=tr('error');
    const body = $('#orders-body');
    body.replaceChildren();
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.className = 'muted'; cell.colSpan = 7;
    cell.textContent = `${tr('api_error')}: ${e}`;
    row.appendChild(cell); body.appendChild(row);
  }finally{
    FILLED_ORDERS_REFRESH_IN_FLIGHT = false;
  }
}

let OPEN_ORDERS_REFRESH_IN_FLIGHT = false;
async function refreshOpenOrders(){
  if(OPEN_ORDERS_REFRESH_IN_FLIGHT) return;
  OPEN_ORDERS_REFRESH_IN_FLIGHT = true;
  try{
    updateOpenOrders(await getJSON('/api/account/open-orders'));
  }catch(e){
    updateOpenOrders(null);
    $('#open-orders-updated').textContent = `${tr('error')}: ${e}`;
  }finally{
    OPEN_ORDERS_REFRESH_IN_FLIGHT = false;
  }
}

let LOGS_REFRESH_IN_FLIGHT = false;
async function refreshLogs(){
  if(LOGS_REFRESH_IN_FLIGHT) return;
  LOGS_REFRESH_IN_FLIGHT = true;
  const box = $('#logs'), pill = $('#log-pill');
  try{
      const response = await fetchWithTimeout('/logs/current.log',{
        cache:'no-store',headers:{Range:`bytes=-${LOG_TAIL_BYTES}`}
      });
      if(!response.ok) throw new Error(response.status);
      const text = await response.text();
      const tail = text.slice(-LOG_TAIL_BYTES);
      const allLines = tail.split('\n');
      const lines = allLines.slice(Math.max(0,allLines.length-LOG_MAX_LINES-1)).filter(Boolean);
      box.replaceChildren(...lines.map(line=>{
        const div=document.createElement('div'); div.textContent=line; return div;
      }));
      box.scrollTop=box.scrollHeight;
      setPill(pill,'ok'); pill.textContent=tr('ok');
  }catch(e){
      setPill(pill,'warn'); pill.textContent=tr('no_export');
  }finally{
    LOGS_REFRESH_IN_FLIGHT = false;
  }
}

const POLL_JOBS = [
  {interval:5000,next:0,run:refresh},
  {interval:8000,next:0,run:refreshOrders},
  {interval:8000,next:0,run:refreshOpenOrders},
  {interval:10000,next:0,run:refreshLogs},
  {interval:60*60*1000,next:0,run:refreshGithubUpdate},
];
let POLL_TIMER = null;
let POLLING_STOPPED = false;

function schedulePoll(delay=250){
  if(POLLING_STOPPED || POLL_TIMER !== null) return;
  POLL_TIMER = setTimeout(runPollScheduler,delay);
}

async function runPollScheduler(){
  POLL_TIMER = null;
  if(POLLING_STOPPED) return;
  if(document.hidden) return;
  const now = Date.now();
  for(const job of POLL_JOBS){
    if(job.next > now) continue;
    job.next = now + job.interval;
    await job.run();
    if(POLLING_STOPPED || document.hidden) break;
  }
  schedulePoll(250);
}

document.addEventListener('visibilitychange',()=>{
  if(document.hidden){
    if(POLL_TIMER !== null) clearTimeout(POLL_TIMER);
    POLL_TIMER = null;
    abortActiveFetches();
    return;
  }
  const now = Date.now();
  for(const job of POLL_JOBS) job.next = Math.min(job.next,now);
  schedulePoll(0);
});

window.addEventListener('pagehide',()=>{
  POLLING_STOPPED = true;
  if(POLL_TIMER !== null) clearTimeout(POLL_TIMER);
  POLL_TIMER = null;
  abortActiveFetches();
  API_RESPONSE_CACHE.clear();
  if(charts){ Object.values(charts).forEach(chart=>chart.destroy()); charts=null; }
});

initLocalePicker(); applyLocale(); schedulePoll(0);
