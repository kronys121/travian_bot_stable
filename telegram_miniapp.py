"""
Telegram Mini App для Travian Bot.
Роут: GET /miniapp  (регистрируется в app.py)

Экраны (SPA, без перезагрузки):
  screen-list      — список аккаунтов
  screen-settings  — настройки конкретного аккаунта (модули + farm/train/trade)
  screen-logs      — последние 100 строк лога
"""

MINIAPP_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Travian Bot</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root{
    --text:  #eef2f7;
    --hint:  #8fa0b3;
    --accent:#6ab0f3;
    --atext: #0b1420;
    --pos:#4ade80; --neg:#f87171; --warn:#fbbf24;
    --line:rgba(255,255,255,.08);
    --glass:      rgba(255,255,255,.07);
    --glass-hi:   rgba(255,255,255,.12);
    --glass-line: rgba(255,255,255,.14);
    --glass-shadow: 0 8px 32px rgba(0,0,0,.35);
  }
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent;margin:0;padding:0}
  html{background:#0d1420}
  body{font-family:-apple-system,"Segoe UI",Roboto,sans-serif;
    color:var(--text);font-size:15px;line-height:1.5;padding:12px 12px 40px;
    min-height:100vh;
    background:
      radial-gradient(ellipse 80% 50% at 20% -10%, rgba(80,130,220,.28), transparent),
      radial-gradient(ellipse 60% 40% at 90% 10%, rgba(60,180,160,.16), transparent),
      radial-gradient(ellipse 70% 60% at 50% 110%, rgba(120,80,200,.14), transparent),
      #0d1420;
    background-attachment:fixed}

  /* ---- header ---- */
  .top-bar{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;
    padding:12px 16px;border-radius:16px;
    background:var(--glass);border:1px solid var(--glass-line);
    backdrop-filter:blur(18px) saturate(1.5);-webkit-backdrop-filter:blur(18px) saturate(1.5);
    box-shadow:var(--glass-shadow)}
  .top-bar h1{font-size:18px;font-weight:700;
    background:linear-gradient(120deg,#fff,#9cc4f0);
    -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
  .hint-txt{font-size:12px;color:var(--hint)}

  /* ---- back ---- */
  .back-btn{display:inline-flex;align-items:center;gap:6px;
    background:var(--glass);border:1px solid var(--glass-line);
    backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
    color:var(--accent);font-size:14px;font-weight:600;cursor:pointer;
    padding:8px 14px;border-radius:12px;margin-bottom:14px}
  .back-btn:active{background:var(--glass-hi)}

  /* ---- screen ---- */
  .screen{display:none}.screen.active{display:block}

  /* ---- card: жидкое стекло ---- */
  .card{position:relative;border-radius:20px;padding:16px;margin-bottom:14px;
    background:linear-gradient(135deg,rgba(255,255,255,.10),rgba(255,255,255,.04));
    border:1px solid var(--glass-line);
    backdrop-filter:blur(20px) saturate(1.6);-webkit-backdrop-filter:blur(20px) saturate(1.6);
    box-shadow:var(--glass-shadow), inset 0 1px 0 rgba(255,255,255,.12)}
  .card::before{content:"";position:absolute;inset:0;border-radius:20px;pointer-events:none;
    background:linear-gradient(160deg,rgba(255,255,255,.10) 0%,transparent 35%)}
  .acc-head{display:flex;align-items:center;gap:8px;margin-bottom:4px}
  .lamp{width:10px;height:10px;border-radius:50%;flex-shrink:0}
  .lamp.on{background:var(--pos);box-shadow:0 0 10px var(--pos),0 0 20px rgba(74,222,128,.4)}
  .lamp.off{background:var(--neg);box-shadow:0 0 6px rgba(248,113,113,.4)}
  .acc-name{font-weight:700;font-size:16px;flex:1}
  .acc-server{font-size:12px;color:var(--hint)}
  .acc-action{font-size:13px;color:var(--hint);margin-bottom:10px}

  /* ---- icon buttons ---- */
  .icon-btn{background:var(--glass);border:1px solid var(--glass-line);
    padding:5px 8px;cursor:pointer;color:var(--hint);font-size:16px;
    line-height:1;border-radius:10px;
    backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)}
  .icon-btn:active{background:var(--glass-hi)}

  /* ---- control buttons ---- */
  .btns{display:flex;gap:8px;margin-bottom:12px}
  .btn{flex:1;border-radius:12px;padding:10px 0;font-size:14px;font-weight:600;cursor:pointer;
    border:1px solid var(--glass-line);
    backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.15)}
  .btn.start{background:linear-gradient(135deg,rgba(74,222,128,.35),rgba(74,222,128,.15));
    color:#d9ffe6;border-color:rgba(74,222,128,.35)}
  .btn.stop{background:linear-gradient(135deg,rgba(248,113,113,.35),rgba(248,113,113,.15));
    color:#ffe1e1;border-color:rgba(248,113,113,.35)}
  .btn.scan{background:linear-gradient(135deg,rgba(106,176,243,.30),rgba(106,176,243,.12));
    color:#dbeafe;border-color:rgba(106,176,243,.35)}
  .btn:disabled{opacity:.35}
  .btn:not(:disabled):active{transform:scale(.98)}

  /* ---- rows / grid ---- */
  .sec{font-size:11px;text-transform:uppercase;letter-spacing:.5px;
    color:var(--hint);margin:12px 0 5px}
  .row{display:flex;justify-content:space-between;align-items:center;
    padding:5px 0;border-bottom:1px solid var(--line);font-size:14px}
  .row:last-child{border-bottom:none}
  .val{font-weight:600}
  .val.pos{color:var(--pos)}.val.neg{color:var(--neg)}.val.warn{color:var(--warn)}
  .res-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px 12px;font-size:14px}
  .res-item{display:flex;justify-content:space-between;padding:6px 10px;
    background:rgba(255,255,255,.05);border:1px solid var(--line);border-radius:10px}
  .res-item .lbl{color:var(--hint)}
  .empty{color:var(--hint);font-size:13px;padding:3px 0}

  /* ---- toggle switch ---- */
  .toggle-row{display:flex;align-items:center;justify-content:space-between;
    padding:10px 0;border-bottom:1px solid var(--line)}
  .toggle-row:last-child{border-bottom:none}
  .toggle-label{font-size:15px}
  .toggle-sub{font-size:12px;color:var(--hint);display:block}
  .sw{position:relative;width:46px;height:26px;flex-shrink:0}
  .sw input{opacity:0;width:0;height:0}
  .sw-track{position:absolute;inset:0;background:rgba(255,255,255,.10);
    border:1px solid var(--glass-line);border-radius:13px;transition:background .2s;
    backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)}
  .sw input:checked+.sw-track{background:linear-gradient(135deg,rgba(106,176,243,.7),rgba(106,176,243,.4));
    border-color:rgba(106,176,243,.5)}
  .sw-thumb{position:absolute;left:3px;top:3px;width:20px;height:20px;
    background:rgba(255,255,255,.95);border-radius:50%;transition:left .2s;
    box-shadow:0 2px 6px rgba(0,0,0,.3)}
  .sw input:checked~.sw-thumb{left:23px}

  /* ---- fields ---- */
  .field{margin-bottom:13px}
  .field label{display:block;font-size:12px;color:var(--hint);
    text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px}
  .field input,.field select{width:100%;
    background:rgba(255,255,255,.06);
    border:1px solid var(--glass-line);border-radius:12px;
    padding:10px 12px;color:var(--text);font-size:15px;outline:none;
    backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);
    -webkit-appearance:none;appearance:none}
  .field select option{background:#1a2433;color:var(--text)}
  .field input:focus,.field select:focus{border-color:var(--accent);
    box-shadow:0 0 0 3px rgba(106,176,243,.15)}
  .field input[type=range]{padding:0;border:none;background:none;
    accent-color:var(--accent);backdrop-filter:none;-webkit-backdrop-filter:none}

  /* ---- save / section header ---- */
  .save-btn{width:100%;
    background:linear-gradient(135deg,rgba(106,176,243,.85),rgba(82,140,200,.75));
    color:#fff;border:1px solid rgba(106,176,243,.5);
    border-radius:12px;padding:12px;font-size:15px;font-weight:600;cursor:pointer;margin-top:4px;
    box-shadow:0 4px 16px rgba(106,176,243,.25), inset 0 1px 0 rgba(255,255,255,.25)}
  .save-btn:disabled{opacity:.5}
  .save-btn:not(:disabled):active{transform:scale(.99)}
  .save-msg{text-align:center;font-size:13px;margin-top:9px;min-height:16px}
  .save-msg.ok{color:var(--pos)}.save-msg.err{color:var(--neg)}
  .sec-header{font-size:16px;font-weight:700;margin:18px 0 10px;
    padding-bottom:6px;border-bottom:1px solid var(--glass-line)}

  /* ---- logs ---- */
  .log-box{border-radius:16px;padding:14px;
    background:rgba(10,16,26,.55);border:1px solid var(--glass-line);
    backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
    box-shadow:var(--glass-shadow);
    font-family:ui-monospace,Consolas,monospace;font-size:11px;
    color:var(--hint);line-height:1.6;overflow-x:auto;
    max-height:60vh;overflow-y:auto;white-space:pre-wrap;word-break:break-all}
  .log-line.err{color:var(--neg)}.log-line.warn{color:var(--warn)}
  .log-line.ok{color:var(--pos)}
  .log-refresh{text-align:right;font-size:12px;color:var(--hint);margin-bottom:6px}

  /* ---- loading ---- */
  .loading{text-align:center;color:var(--hint);padding:40px 0}
</style>
</head>
<body>

<!-- ===== SCREEN: список аккаунтов ===== -->
<div id="screen-list" class="screen active">
  <div class="top-bar">
    <h1>Travian Bot</h1>
    <span class="hint-txt" id="refreshed"></span>
  </div>
  <div id="app"><div class="loading">Загрузка...</div></div>
</div>

<!-- ===== SCREEN: настройки аккаунта ===== -->
<div id="screen-settings" class="screen">
  <button class="back-btn" onclick="nav('list')">&#8592; Назад</button>
  <div id="settings-body"></div>
</div>

<!-- ===== SCREEN: логи ===== -->
<div id="screen-logs" class="screen">
  <button class="back-btn" onclick="nav('list')">&#8592; Назад</button>
  <div class="log-refresh" id="log-refresh-time"></div>
  <div class="log-box" id="log-box"><span class="loading">Загрузка...</span></div>
</div>

<script>
const tg = window.Telegram?.WebApp;
if(tg){ tg.ready(); tg.expand(); }

// ============================================================
// Navigation
// ============================================================
let _screen = "list";
let _currentAcc = null;
let _allAccounts = [];
let _logInterval = null;

function nav(screen, accName){
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  document.getElementById("screen-"+screen).classList.add("active");
  _screen = screen;
  if(accName) _currentAcc = accName;

  if(screen === "list"){
    if(tg?.BackButton) tg.BackButton.hide();
  } else {
    if(tg?.BackButton){ tg.BackButton.show(); tg.BackButton.onClick(() => nav("list")); }
  }

  if(screen === "settings") renderSettings();
  if(screen === "logs"){
    loadLogs();
    _logInterval = setInterval(loadLogs, 8000);
  } else {
    clearInterval(_logInterval);
  }
}

// ============================================================
// Helpers
// ============================================================
function esc(s){ return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function fmtNum(n){ return (n==null||isNaN(n)) ? '—' : Number(n).toLocaleString('ru-RU'); }
function fmtDur(sec){
  if(sec==null||isNaN(sec)||sec<0) return '';
  sec=Math.floor(sec);
  const h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=sec%60;
  const p=n=>String(n).padStart(2,'0');
  return (h?h+'ч ':'')+p(m)+':'+p(s);
}

// ============================================================
// Render helpers
// ============================================================
function resBlock(r){
  if(!r) return '<div class="empty">нет данных</div>';
  const st = r.storage || r;   // stats возвращает {storage:{wood,clay...}} или напрямую
  const wood  = st.wood  ?? st.lumber ?? null;
  const clay  = st.clay  ?? null;
  const iron  = st.iron  ?? null;
  const crop  = st.crop  ?? null;
  if(wood==null && clay==null && iron==null && crop==null)
    return '<div class="empty">нет данных</div>';
  const item=(l,v)=>`<div class="res-item"><span class="lbl">${l}</span><span>${fmtNum(v)}</span></div>`;
  const fc = r.free_crop;
  const fcCls = fc==null?'': fc<=0?'neg': fc<10?'warn':'pos';
  return `<div class="res-grid">
    ${item('Дерево',wood)}${item('Глина',clay)}
    ${item('Железо',iron)}${item('Зерно',crop)}
  </div>${fc!=null?`<div class="row" style="margin-top:8px">
    <span>Свободное зерно</span><span class="val ${fcCls}">${fmtNum(fc)}</span>
  </div>`:''}`;
}

function buildBlock(q){
  if(!q||!q.length) return '<div class="empty">очередь пуста</div>';
  return q.map(b=>{
    const lvl = b.target_level!=null?` до ур.${b.target_level}`:'';
    const t   = b.seconds!=null ? fmtDur(b.seconds) : (b.timer||'');
    return `<div class="row"><span>${esc(b.name||'?')}${lvl}</span>
      <span class="val">${esc(t)}</span></div>`;
  }).join('');
}

function accountBlock(a){
  if(!a||!Object.keys(a).length) return '<div class="empty">нет данных</div>';
  let h='';
  if(a.gold!=null)   h+=row('Золото', fmtNum(a.gold));
  if(a.silver!=null) h+=row('Серебро', fmtNum(a.silver));
  h += row('Travian Plus',   tag(a.premium,   a.premium?'активен':'нет'));
  if(a.gold_club!=null)
    h += row('Золотой клуб', tag(a.gold_club, a.gold_club?'активен':'нет'));
  if(a.beginner_protection){
    const t=a.beginner_protection_seconds!=null?fmtDur(a.beginner_protection_seconds)
      :(a.beginner_protection_text||'активна');
    h += row('Защита новичка', `<span class="val pos">${esc(t)}</span>`);
  } else {
    h += row('Защита новичка','<span class="val neg">закончилась</span>');
  }
  if(Array.isArray(a.infobox)){
    a.infobox.forEach(it=>{
      if(!it.timer&&it.seconds==null) return;
      if(/(новичк|защит|beginner)/i.test(it.label||'')) return;
      const t=it.seconds!=null?fmtDur(it.seconds):(it.timer||'');
      if(t) h+=row(esc(it.label||'—'),`<span class="val">${esc(t)}</span>`);
    });
  }
  return h;
}

function row(label,valHtml){ return `<div class="row"><span>${label}</span>${valHtml}</div>`; }
function tag(ok,txt){ return `<span class="val ${ok?'pos':'neg'}">${txt}</span>`; }

function attacksBlock(list){
  if(!list||!list.length) return '<div class="empty">атак нет</div>';
  return list.map(a=>{
    const t=a.seconds!=null?fmtDur(a.seconds):(a.timer||a.time||'');
    return `<div class="row"><span class="val neg">&#9876; ${esc(a.type||a.name||'Атака')}</span>
      <span class="val">${esc(t)}</span></div>`;
  }).join('');
}

// ============================================================
// Account card (list screen)
// ============================================================
function accCard(acc){
  const s  = acc.status || {};
  const st = acc.stats  || {};
  const on = !!acc.running;

  // деревни — берём из st.villages или делаем псевдо-деревню из legacy-полей
  const villages = (st.villages&&st.villages.length) ? st.villages : [{
    name: acc.name,
    resources: st.resources || {},
    build_queue: st.build_queue || [],
  }];

  const villHtml = villages.map(v=>`
    <div class="sec">Ресурсы — ${esc(v.name||'Деревня')}</div>
    ${resBlock(v.resources||{})}
    <div class="sec">Строительство — ${esc(v.name||'Деревня')}</div>
    ${buildBlock(v.build_queue||[])}
  `).join('');

  const safeAcc = esc(acc.name);

  return `<div class="card">
    <div class="acc-head">
      <span class="lamp ${on?'on':'off'}"></span>
      <span class="acc-name">${safeAcc}</span>
      <span class="acc-server">${esc(acc.server||'')}</span>
      <button class="icon-btn" onclick="nav('logs','${safeAcc}')" title="Логи">&#128196;</button>
      <button class="icon-btn" onclick="nav('settings','${safeAcc}')" title="Настройки">&#9881;</button>
    </div>
    <div class="acc-action">${esc(s.last_action||'Не запущен')}</div>
    <div class="btns">
      <button class="btn start" ${on?'disabled':''} onclick="ctrl('${safeAcc}','start',this)">&#9654; Старт</button>
      <button class="btn stop"  ${on?'':'disabled'} onclick="ctrl('${safeAcc}','stop',this)">&#9646; Стоп</button>
    </div>
    ${on?`<div class="btns">
      <button class="btn scan" onclick="scanMap('${safeAcc}',this)" title="Полный скан радиуса">&#128506; Полный скан</button>
      <button class="btn scan" onclick="rescanMap('${safeAcc}',this)" title="Перескан известных оазисов">&#8635; Перескан</button>
    </div>`:''}
    ${villHtml}
    <div class="sec">Аккаунт</div>
    ${accountBlock(st.account||{})}
    <div class="sec">Входящие атаки</div>
    ${attacksBlock(st.attacks)}
  </div>`;
}

// ============================================================
// Settings screen
// ============================================================
function sw(id, checked, onchange){
  return `<label class="sw"><input type="checkbox" id="${id}" ${checked?'checked':''} onchange="${onchange}">
    <span class="sw-track"></span><span class="sw-thumb"></span></label>`;
}
function toggleRow(id, label, sub, checked, onchange){
  return `<div class="toggle-row">
    <span><span class="toggle-label">${label}</span>${sub?`<span class="toggle-sub">${sub}</span>`:''}
    </span>${sw(id,checked,onchange)}</div>`;
}
function numField(id, label, val, min, max, step){
  return `<div class="field"><label>${label}</label>
    <input type="number" id="${id}" value="${val}" min="${min}" max="${max}" step="${step||1}"></div>`;
}
function selField(id, label, opts, val){
  const options = opts.map(([v,t])=>`<option value="${v}" ${v==val?'selected':''}>${t}</option>`).join('');
  return `<div class="field"><label>${label}</label><select id="${id}">${options}</select></div>`;
}

function renderSettings(){
  const acc  = _allAccounts.find(a=>a.name===_currentAcc);
  const sets = acc?.settings || {};
  const feat = sets.features || {};
  const farm = sets.farm     || {};
  const trn  = sets.training || {};
  const trd  = sets.trade    || {};

  // helper: immediate-save toggles call saveFeature('key', this.checked)
  const tf = (id,lbl,sub,key)=>toggleRow(id,lbl,sub,!!feat[key],`saveFeature('${key}',this.checked)`);

  const html = `
    <div class="card">
      <h2 style="font-size:17px;font-weight:700;margin-bottom:14px">${esc(_currentAcc)}</h2>

      <!-- Подключение -->
      <div class="sec-header">Подключение</div>
      <div class="field"><label>Скорость (rate)</label>
        <input type="number" id="s-rate" value="${acc?.rate||3}" min="1" max="10"></div>
      ${selField('s-headless','Браузер',[['true','Скрытый (headless)'],['false','Видимый']],String(acc?.headless!==false))}
      <div class="field"><label>Прокси</label>
        <input type="text" id="s-proxy" value="${esc(acc?.proxy||'')}" placeholder="socks5://user:pass@host:port"></div>
      <button class="save-btn" id="s-save" onclick="saveConnection()">Сохранить подключение</button>
      <div class="save-msg" id="s-conn-msg"></div>

      <!-- Модули -->
      <div class="sec-header" style="margin-top:20px">Модули</div>
      <div>
        ${tf('f-farm',    'Фарм оазисов',    'Атаки на оазисы', 'farm_enabled')}
        ${tf('f-build',   'Автостройка',      'По плану постройки', 'build_enabled')}
        ${tf('f-ads',     'Стройка с рекламой', '-25% времени (section2)', 'build_use_ads')}
        ${tf('f-tasks',   'Задания',          'Ежедневные квесты', 'tasks_enabled')}
        ${tf('f-adv',     'Приключения',      'Герой ходит в приключения', 'adventure_enabled')}
        ${tf('f-train',   'Тренировка войск', 'Дотренировка до цели', 'train_enabled')}
        ${tf('f-npc',     'NPC-торговля',     'Авто-обмен ресурсов', 'npc_trade_enabled')}
        ${tf('f-evasion', 'Эвакуация',        'При входящих атаках', 'evasion_enabled')}
      </div>

      <!-- Фарм -->
      <div class="sec-header" style="margin-top:20px">Настройки фарма</div>
      ${numField('farm-troops','Войск на рейд', farm.troops_per_raid||10, 1, 500)}
      ${numField('farm-dist','Макс. расстояние (0 = без лимита)', farm.max_distance||0, 0, 50, 0.5)}
      ${numField('farm-radius','Радиус сканирования', farm.scan_radius||5, 1, 20)}
      ${numField('farm-interval','Интервал фарма (мин)', farm.interval_minutes||60, 5, 360)}
      ${selField('farm-troop','Тип войск',[
          ['1','1 — Фаланга/Легионер'],
          ['2','2 — Мечник/Преторианец'],
          ['3','3 — Конница'],
          ['4','4 — Осада'],
      ], farm.troop_type_index||1)}
      <button class="save-btn" onclick="saveFarm()" style="margin-top:4px">Сохранить фарм</button>
      <div class="save-msg" id="s-farm-msg"></div>

      <!-- Тренировка -->
      <div class="sec-header" style="margin-top:20px">Тренировка войск</div>
      ${numField('trn-target','Цель (кол-во войск)', trn.target_count||100, 1, 5000)}
      ${selField('trn-troop','Тип войск',[
          ['1','1 — Фаланга/Легионер'],
          ['2','2 — Мечник/Преторианец'],
          ['3','3 — Конница'],
      ], trn.troop_type_index||1)}
      ${selField('trn-building','Здание',[
          ['barracks','Казарма'],
          ['stable','Конюшня'],
          ['workshop','Мастерская'],
      ], trn.building||'barracks')}
      <button class="save-btn" onclick="saveTraining()" style="margin-top:4px">Сохранить тренировку</button>
      <div class="save-msg" id="s-trn-msg"></div>

      <!-- NPC-торговля -->
      <div class="sec-header" style="margin-top:20px">NPC-торговля</div>
      ${numField('npc-threshold','Порог для обмена (%)', trd.npc_threshold_pct||85, 50, 99)}
      <button class="save-btn" onclick="saveTrade()" style="margin-top:4px">Сохранить торговлю</button>
      <div class="save-msg" id="s-trd-msg"></div>
    </div>`;
  document.getElementById("settings-body").innerHTML = html;
}

// ---- сохранение настроек по разделам ----
async function saveSection(payload, msgId, btnId){
  const msg = document.getElementById(msgId);
  if(!msg) return;
  if(btnId){ const b=document.getElementById(btnId); if(b) b.disabled=true; }
  msg.textContent='Сохранение...'; msg.className='save-msg';
  try{
    const r = await fetch(`/api/accounts/${encodeURIComponent(_currentAcc)}`, {
      method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)
    });
    if(!r.ok){ const j=await r.json().catch(()=>({})); throw new Error(j.detail||'Ошибка'); }
    if(tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    msg.textContent='Сохранено'; msg.className='save-msg ok';
    // обновить кэш
    const a=_allAccounts.find(a=>a.name===_currentAcc);
    if(a) Object.assign(a, payload.connection||{});
  }catch(e){
    msg.textContent=e.message; msg.className='save-msg err';
    if(tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('error');
  }finally{
    if(btnId){ const b=document.getElementById(btnId); if(b) b.disabled=false; }
  }
}

function saveConnection(){
  saveSection({
    rate:     parseInt(document.getElementById('s-rate').value,10)||3,
    headless: document.getElementById('s-headless').value==='true',
    proxy:    document.getElementById('s-proxy').value.trim(),
  },'s-conn-msg','s-save');
}
async function saveFeature(key, value){
  // мгновенное сохранение при переключении тогла
  const acc=_allAccounts.find(a=>a.name===_currentAcc);
  if(!acc) return;
  const sets=acc.settings||{};
  const feat=Object.assign({},sets.features||{},{[key]:value});
  await fetch(`/api/accounts/${encodeURIComponent(_currentAcc)}/settings`,{
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({features:feat})
  }).catch(()=>{});
}
function saveFarm(){
  saveSection({
    settings:{farm:{
      troops_per_raid: parseInt(document.getElementById('farm-troops').value,10)||10,
      max_distance:    parseFloat(document.getElementById('farm-dist').value)||0,
      scan_radius:     parseInt(document.getElementById('farm-radius').value,10)||5,
      interval_minutes:parseInt(document.getElementById('farm-interval').value,10)||60,
      troop_type_index:parseInt(document.getElementById('farm-troop').value,10)||1,
    }}
  },'s-farm-msg');
}
function saveTraining(){
  saveSection({
    settings:{training:{
      target_count:    parseInt(document.getElementById('trn-target').value,10)||100,
      troop_type_index:parseInt(document.getElementById('trn-troop').value,10)||1,
      building:        document.getElementById('trn-building').value,
    }}
  },'s-trn-msg');
}
function saveTrade(){
  saveSection({
    settings:{trade:{
      npc_threshold_pct:parseInt(document.getElementById('npc-threshold').value,10)||85,
    }}
  },'s-trd-msg');
}

// ============================================================
// Logs screen
// ============================================================
async function loadLogs(){
  if(!_currentAcc) return;
  const box=document.getElementById('log-box');
  try{
    const r=await fetch(`/api/accounts/${encodeURIComponent(_currentAcc)}/logs?lines=100`);
    const j=await r.json();
    const lines=(j.lines||[]).map(l=>{
      const cls=/(ERROR|ОШИБК)/i.test(l)?'err':/(WARNING|ПРЕДУПР)/i.test(l)?'warn':
                /(OK|успеш)/i.test(l)?'ok':'';
      return `<div class="log-line ${cls}">${esc(l)}</div>`;
    });
    box.innerHTML = lines.length ? lines.join('') : '<div class="empty">Лог пуст</div>';
    box.scrollTop=box.scrollHeight;
    document.getElementById('log-refresh-time').textContent =
      'обновлено '+new Date().toLocaleTimeString('ru-RU');
  }catch(e){
    box.innerHTML=`<div class="empty">Ошибка: ${esc(e.message)}</div>`;
  }
}

// ============================================================
// Control (start / stop)
// ============================================================
async function ctrl(name, action, btn){
  btn.disabled=true;
  try{
    if(tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
    const r=await fetch(`/api/accounts/${encodeURIComponent(name)}/${action}`,{method:'POST'});
    if(!r.ok){ const j=await r.json().catch(()=>({})); throw new Error(j.detail||'Ошибка'); }
    await load();
  }catch(e){
    if(tg) tg.showAlert(e.message); else alert(e.message);
  }finally{ btn.disabled=false; }
}

async function _sendScan(name, btn, endpoint){
  btn.disabled=true;
  const orig=btn.innerHTML;
  btn.innerHTML='Отправка…';
  try{
    if(tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
    const r=await fetch(`/api/accounts/${encodeURIComponent(name)}/${endpoint}`,{method:'POST'});
    if(!r.ok){ const j=await r.json().catch(()=>({})); throw new Error(j.detail||'Ошибка'); }
    if(tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    btn.innerHTML='В очереди';
    setTimeout(()=>{ btn.innerHTML=orig; btn.disabled=false; }, 4000);
  }catch(e){
    if(tg) tg.showAlert(e.message); else alert(e.message);
    btn.innerHTML=orig; btn.disabled=false;
  }
}
function scanMap(name, btn){ return _sendScan(name, btn, 'scan'); }
function rescanMap(name, btn){ return _sendScan(name, btn, 'rescan'); }

// ============================================================
// Main load
// ============================================================
async function load(){
  if(_screen!=='list') return;  // не перерисовываем фон пока открыт другой экран
  try{
    const r=await fetch('/api/accounts');
    _allAccounts=await r.json();
    const app=document.getElementById('app');
    if(!_allAccounts.length){
      app.innerHTML='<div class="loading">Нет аккаунтов</div>'; return;
    }
    app.innerHTML=_allAccounts.map(accCard).join('');
    document.getElementById('refreshed').textContent=
      'обновлено '+new Date().toLocaleTimeString('ru-RU');
  }catch(e){
    document.getElementById('app').innerHTML=
      `<div class="loading">Ошибка: ${esc(e.message)}</div>`;
  }
}

load();
setInterval(load, 10000);
</script>
</body>
</html>"""
