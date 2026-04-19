// ── 가상 모딩 계산기 ──

const calcState = {
    warframe: null,         // {name, health, shield, armor, power, sprintSpeed}
    warframeList: [],       // 전체 워프레임 목록 (드롭다운용)
    mods: Array(10).fill(null),   // {name, effects, rank, fusionLimit} | null
    shards: Array(5).fill(null),  // {color, option_key, tauforged} | null
    arcanes: Array(2).fill(null), // {name, effects, effectText} | null
    shardsData: {},         // /api/calc/shards 응답 캐시
    activeSlotType: null,   // "mod" | "arcane" | null
    activeSlotIdx: -1,
    initialized: false,
};

let _calcSearchDebounceTimer = null;

// ── 한국어 스탯 이름 매핑 ──
const STAT_KO = {
    ability_strength: '위력',
    ability_duration: '지속',
    ability_range: '범위',
    ability_efficiency: '효율',
    health: '체력',
    shield: '실드',
    armor: '방어도',
    energy: '에너지',
    sprint_speed: '속도',
};

function formatEffects(effects) {
    return Object.entries(effects || {})
        .map(([k, v]) => `${v > 0 ? '+' : ''}${v}% ${STAT_KO[k] || k}`)
        .join(', ');
}

// ── 초기화 ──
async function initCalc() {
    if (calcState.initialized) return;
    // 샤드 정적 데이터 + 워프레임 전체 목록 병렬 로드
    try {
        const [shardsRes, wfRes] = await Promise.all([
            fetch('/api/calc/shards'),
            fetch('/api/calc/warframes'),
        ]);
        const [shardsD, wfD] = await Promise.all([shardsRes.json(), wfRes.json()]);
        if (shardsD.ok) calcState.shardsData = shardsD.shards;
        if (wfD.ok) calcState.warframeList = wfD.items || [];
    } catch (e) {
        console.error('[calc] 초기 데이터 로드 실패:', e);
    }
    calcState.initialized = true;
    renderCalc();
    ensureCalcSearchModal();
}

// ── 전체 레이아웃 렌더 ──
function renderCalc() {
    const container = document.getElementById('calc-container');
    if (!container) return;

    container.innerHTML = `
<div class="calc-layout">
    <div class="calc-left">
        <div class="calc-section">
            <div class="calc-section-title">워프레임</div>
            <select id="calc-wf-select" class="calc-wf-select" onchange="onCalcWfSelect(this.value)">
                <option value="">-- 워프레임 선택 --</option>
                ${calcState.warframeList.map(wf =>
                    `<option value="${escapeHtml(wf.name)}">${escapeHtml(wf.name)}</option>`
                ).join('')}
            </select>
            <div id="calc-wf-stats" class="calc-wf-stats"></div>
        </div>

        <div class="calc-section">
            <div class="calc-section-title">모드 슬롯 <span class="calc-capacity-badge" id="calc-capacity">0/72</span></div>
            <div class="calc-mod-grid" id="calc-mod-grid"></div>
        </div>

        <div class="calc-section">
            <div class="calc-section-title">아케인</div>
            <div class="calc-arcane-row" id="calc-arcane-row"></div>
        </div>

        <div class="calc-section">
            <div class="calc-section-title">아케인 샤드</div>
            <div class="calc-shard-row" id="calc-shard-row"></div>
        </div>
    </div>

    <div class="calc-right">
        <div class="calc-section">
            <div class="calc-section-title">빌드 스탯</div>
            <div id="calc-stats-panel" class="calc-stats-panel">
                <div class="calc-stats-empty">워프레임을 선택하면<br>스탯이 표시됩니다</div>
            </div>
        </div>
    </div>
</div>`;

    renderModGrid();
    renderArcaneRow();
    renderShardRow();
}

// ── 모드 슬롯 그리드 ──
function renderModGrid() {
    const grid = document.getElementById('calc-mod-grid');
    if (!grid) return;

    let totalCost = 0;
    let html = '';
    for (let i = 0; i < 10; i++) {
        const mod = calcState.mods[i];
        if (mod) {
            totalCost += (mod.rank || 0);
            html += `<div class="calc-slot calc-slot-filled" onclick="openModSearch(${i})">
                <button class="calc-slot-remove" onclick="event.stopPropagation();clearCalcSlot('mod',${i})">×</button>
                <span class="calc-slot-name">${escapeHtml(mod.name)}</span>
                <span class="calc-slot-rank">R${mod.rank}</span>
            </div>`;
        } else {
            html += `<div class="calc-slot calc-slot-empty" onclick="openModSearch(${i})">
                <span class="calc-slot-plus">+</span>
                <span class="calc-slot-label">모드 ${i + 1}</span>
            </div>`;
        }
    }
    grid.innerHTML = html;

    const badge = document.getElementById('calc-capacity');
    if (badge) badge.textContent = `소모 ${totalCost}`;
}

// ── 아케인 슬롯 ──
function renderArcaneRow() {
    const row = document.getElementById('calc-arcane-row');
    if (!row) return;

    let html = '';
    for (let i = 0; i < 2; i++) {
        const arc = calcState.arcanes[i];
        if (arc) {
            html += `<div class="calc-slot calc-slot-filled calc-arcane-slot" onclick="openArcaneSearch(${i})">
                <button class="calc-slot-remove" onclick="event.stopPropagation();clearCalcSlot('arcane',${i})">×</button>
                <span class="calc-slot-name">${escapeHtml(arc.name)}</span>
                <span class="calc-slot-rank" style="font-size:10px;color:var(--text-muted);">${arc.effectText ? escapeHtml(arc.effectText.slice(0, 30)) : ''}</span>
            </div>`;
        } else {
            html += `<div class="calc-slot calc-slot-empty calc-arcane-slot" onclick="openArcaneSearch(${i})">
                <span class="calc-slot-plus">+</span>
                <span class="calc-slot-label">아케인 ${i + 1}</span>
            </div>`;
        }
    }
    row.innerHTML = html;
}

// ── 샤드 슬롯 ──
function renderShardRow() {
    const row = document.getElementById('calc-shard-row');
    if (!row) return;

    let html = '';
    for (let i = 0; i < 5; i++) {
        const shard = calcState.shards[i];
        const selectedColor = shard ? shard.color : '';
        const selectedOpt = shard ? shard.option_key : '';
        const tauChecked = shard ? shard.tauforged : false;

        const colorOptions = Object.entries(calcState.shardsData)
            .map(([k, v]) => `<option value="${escapeHtml(k)}" ${k === selectedColor ? 'selected' : ''}>${escapeHtml(v.name)}</option>`)
            .join('');

        let optOptions = '<option value="">효과 선택</option>';
        if (selectedColor && calcState.shardsData[selectedColor]) {
            const opts = calcState.shardsData[selectedColor].options || [];
            optOptions += opts
                .map(opt => `<option value="${escapeHtml(opt.key)}" ${opt.key === selectedOpt ? 'selected' : ''}>${escapeHtml(opt.label)}</option>`)
                .join('');
        }

        html += `<div class="calc-shard-slot" id="calc-shard-${i}">
            <select class="calc-shard-color" onchange="onShardColorChange(${i}, this.value)">
                <option value="">색상 선택</option>
                ${colorOptions}
            </select>
            <select class="calc-shard-option" id="calc-shard-opt-${i}" onchange="onShardOptionChange(${i}, this.value)" ${selectedColor ? '' : 'disabled'}>
                ${optOptions}
            </select>
            <label class="calc-shard-tau">
                <input type="checkbox" id="calc-shard-tau-${i}" onchange="onShardTauChange(${i}, this.checked)" ${selectedColor && selectedOpt ? '' : 'disabled'} ${tauChecked ? 'checked' : ''}>
                타우
            </label>
        </div>`;
    }
    row.innerHTML = html;
}

// ── 워프레임 드롭다운 선택 ──
function onCalcWfSelect(name) {
    const wf = calcState.warframeList.find(w => w.name === name);
    calcState.warframe = wf || null;
    // 기본 스탯 미리보기 표시
    const statsEl = document.getElementById('calc-wf-stats');
    if (statsEl && wf) {
        statsEl.innerHTML =
            `<span>체력 ${wf.health}</span><span>실드 ${wf.shield}</span>` +
            `<span>방어도 ${wf.armor}</span><span>에너지 ${wf.power}</span>`;
    } else if (statsEl) {
        statsEl.innerHTML = '';
    }
    computeAndRender();
}

// ── 모드 검색 모달 열기 ──
function openModSearch(idx) {
    calcState.activeSlotType = 'mod';
    calcState.activeSlotIdx = idx;
    openCalcSearchModal('모드 이름...', '/api/calc/mods');
}

function openArcaneSearch(idx) {
    calcState.activeSlotType = 'arcane';
    calcState.activeSlotIdx = idx;
    openCalcSearchModal('아케인 이름...', '/api/calc/arcanes');
}

function ensureCalcSearchModal() {
    if (document.getElementById('calc-search-overlay')) return;

    const overlay = document.createElement('div');
    overlay.id = 'calc-search-overlay';
    overlay.onclick = closeCalcSearch;

    const modal = document.createElement('div');
    modal.id = 'calc-search-modal';
    modal.innerHTML = `
<div class="calc-search-header">
    <input type="text" id="calc-search-input" placeholder="이름 검색..." oninput="onCalcSearchInput()" autocomplete="off">
    <button onclick="closeCalcSearch()">×</button>
</div>
<div id="calc-search-results"></div>`;

    document.body.appendChild(overlay);
    document.body.appendChild(modal);
}

let _calcSearchApiUrl = '';

function openCalcSearchModal(placeholder, apiUrl) {
    ensureCalcSearchModal();
    _calcSearchApiUrl = apiUrl;

    const inp = document.getElementById('calc-search-input');
    if (inp) { inp.placeholder = placeholder; inp.value = ''; }
    const results = document.getElementById('calc-search-results');
    if (results) results.innerHTML = '';

    document.getElementById('calc-search-overlay').style.display = 'block';
    document.getElementById('calc-search-modal').style.display = 'flex';

    setTimeout(() => { if (inp) inp.focus(); }, 50);
}

function closeCalcSearch() {
    const overlay = document.getElementById('calc-search-overlay');
    const modal = document.getElementById('calc-search-modal');
    if (overlay) overlay.style.display = 'none';
    if (modal) modal.style.display = 'none';
    calcState.activeSlotType = null;
    calcState.activeSlotIdx = -1;
}

function onCalcSearchInput() {
    clearTimeout(_calcSearchDebounceTimer);
    _calcSearchDebounceTimer = setTimeout(async () => {
        const inp = document.getElementById('calc-search-input');
        if (!inp) return;
        const q = inp.value.trim();
        const results = document.getElementById('calc-search-results');
        if (!results) return;

        if (!q) {
            results.innerHTML = '';
            return;
        }

        try {
            const r = await fetch(`${_calcSearchApiUrl}?q=${encodeURIComponent(q)}`);
            const d = await r.json();
            const items = d.items || [];
            if (!items.length) {
                results.innerHTML = '<div class="calc-search-empty">검색 결과 없음</div>';
                return;
            }

            if (calcState.activeSlotType === 'mod') {
                results.innerHTML = items.map(item => {
                    const safeItem = JSON.stringify(item).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
                    return `<div class="calc-search-item" onclick='selectCalcItem(${JSON.stringify(item)})'>
                        <span class="calc-search-name">${escapeHtml(item.name)}</span>
                        <span class="calc-search-meta">R${item.maxRank || item.fusionLimit || 0} | ${escapeHtml(item.polarity || '-')}</span>
                        <span class="calc-search-effects">${escapeHtml(formatEffects(item.effects))}</span>
                    </div>`;
                }).join('');
            } else {
                results.innerHTML = items.map(item => {
                    return `<div class="calc-search-item" onclick='selectCalcItem(${JSON.stringify(item)})'>
                        <span class="calc-search-name">${escapeHtml(item.name)}</span>
                        <span class="calc-search-meta">${escapeHtml(item.effectText || '')}</span>
                        <span class="calc-search-effects">${escapeHtml(formatEffects(item.effects))}</span>
                    </div>`;
                }).join('');
            }
        } catch (e) {
            console.error('[calc] 검색 실패:', e);
            const results2 = document.getElementById('calc-search-results');
            if (results2) results2.innerHTML = '<div class="calc-search-empty">오류가 발생했습니다</div>';
        }
    }, 300);
}

function selectCalcItem(item) {
    const { activeSlotType, activeSlotIdx } = calcState;
    if (activeSlotIdx < 0) return;

    if (activeSlotType === 'mod') {
        const rank = item.fusionLimit !== undefined ? item.fusionLimit : (item.maxRank || 0);
        calcState.mods[activeSlotIdx] = { ...item, rank };
    } else if (activeSlotType === 'arcane') {
        calcState.arcanes[activeSlotIdx] = item;
    }

    closeCalcSearch();
    renderModGrid();
    renderArcaneRow();
    computeAndRender();
}

// ── 샤드 이벤트 ──
function onShardColorChange(idx, color) {
    const optSel = document.getElementById(`calc-shard-opt-${idx}`);
    const tauChk = document.getElementById(`calc-shard-tau-${idx}`);

    if (!color) {
        calcState.shards[idx] = null;
        if (optSel) { optSel.innerHTML = '<option value="">효과 선택</option>'; optSel.disabled = true; }
        if (tauChk) { tauChk.disabled = true; tauChk.checked = false; }
        computeAndRender();
        return;
    }

    if (optSel) {
        optSel.disabled = false;
        const shardDef = calcState.shardsData[color];
        const opts = shardDef ? (shardDef.options || []) : [];
        optSel.innerHTML = '<option value="">효과 선택</option>' +
            opts.map(opt => `<option value="${escapeHtml(opt.key)}">${escapeHtml(opt.label)}</option>`).join('');
    }

    if (tauChk) { tauChk.disabled = true; tauChk.checked = false; }
    calcState.shards[idx] = null;
}

function onShardOptionChange(idx, optionKey) {
    const colorSel = document.querySelector(`#calc-shard-${idx} .calc-shard-color`);
    const tauChk = document.getElementById(`calc-shard-tau-${idx}`);
    const color = colorSel ? colorSel.value : '';

    if (!optionKey) {
        calcState.shards[idx] = null;
        if (tauChk) { tauChk.disabled = true; tauChk.checked = false; }
        computeAndRender();
        return;
    }

    calcState.shards[idx] = { color, option_key: optionKey, tauforged: false };
    if (tauChk) { tauChk.disabled = false; tauChk.checked = false; }
    computeAndRender();
}

function onShardTauChange(idx, checked) {
    if (calcState.shards[idx]) {
        calcState.shards[idx].tauforged = checked;
        computeAndRender();
    }
}

// ── 슬롯 제거 ──
function clearCalcSlot(type, idx) {
    if (type === 'mod') calcState.mods[idx] = null;
    else if (type === 'arcane') calcState.arcanes[idx] = null;
    renderModGrid();
    renderArcaneRow();
    computeAndRender();
}

// ── 스탯 계산 ──
async function computeAndRender() {
    if (!calcState.warframe) return;

    const payload = {
        base: calcState.warframe,
        mods: calcState.mods.filter(Boolean).map(m => ({
            name: m.name,
            effects: m.effects,
            rank: m.rank,
            fusionLimit: m.fusionLimit,
        })),
        shards: calcState.shards.filter(Boolean),
        arcanes: calcState.arcanes.filter(Boolean).map(a => ({
            name: a.name,
            effects: a.effects,
        })),
    };

    try {
        const r = await fetch('/api/calc/compute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const d = await r.json();
        if (d.ok) {
            renderStatsPanel(d.stats, d.base);
        } else {
            console.error('[calc] compute 오류:', d);
        }
    } catch (e) {
        console.error('[calc] compute 요청 실패:', e);
    }
}

// ── 스탯 패널 렌더 ──
function renderStatsPanel(stats, base) {
    const panel = document.getElementById('calc-stats-panel');
    if (!panel) return;

    panel.innerHTML = `<div class="calc-stats-grid">
        ${renderStatRow('어빌리티 위력',   base.strength,  stats.strength,  '%')}
        ${renderStatRow('어빌리티 지속시간', base.duration,  stats.duration,  '%')}
        ${renderStatRow('어빌리티 범위',   base.range,     stats.range,     '%')}
        ${renderStatRow('어빌리티 효율',   base.efficiency, stats.efficiency, '%')}
        ${renderStatRow('체력',           base.health,    stats.health,    '')}
        ${renderStatRow('실드',           base.shield,    stats.shield,    '')}
        ${renderStatRow('방어도',         base.armor,     stats.armor,     '')}
        ${renderStatRow('에너지',         base.energy,    stats.energy,    '')}
        ${renderStatRow('이동속도',       base.sprint,    stats.sprint,    'x')}
    </div>`;
}

function renderStatRow(label, baseVal, finalVal, unit) {
    const cls = finalVal > baseVal
        ? 'calc-stat-up'
        : finalVal < baseVal
            ? 'calc-stat-down'
            : '';
    const bv = baseVal !== undefined && baseVal !== null ? baseVal : '?';
    const fv = finalVal !== undefined && finalVal !== null ? finalVal : '?';
    return `<div class="calc-stat-row">
        <span class="calc-stat-label">${escapeHtml(label)}</span>
        <div class="calc-stat-values">
            <span class="calc-stat-base">${bv}${unit}</span>
            <span class="calc-stat-arrow">→</span>
            <span class="calc-stat-final ${cls}">${fv}${unit}</span>
        </div>
    </div>`;
}
