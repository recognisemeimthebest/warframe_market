// ── 가상 모딩 계산기 (워프레임 + 무기) ──

// ── 모드 전환 상태 ─────────────────────────────────────────────────────────
let calcRootMode = 'warframe'; // 'warframe' | 'weapon'
let _calcSearchMode = 'warframe'; // 모드 검색 시 어느 쪽 선택인지 구분

// ── 워프레임 상태 ──────────────────────────────────────────────────────────
const calcState = {
    warframe: null,
    warframeItem: null,
    isPrime: false,
    warframeList: [],
    mods: Array(10).fill(null),
    shards: Array(5).fill(null),
    arcanes: Array(2).fill(null),
    shardsData: {},
    activeSlotType: null,
    activeSlotIdx: -1,
    initialized: false,
};

// ── 무기 상태 ──────────────────────────────────────────────────────────────
const weaponCalcState = {
    weaponType: 'primary',  // 'primary' | 'secondary' | 'melee'
    weapon: null,           // 선택된 무기 기본 스탯 객체
    weaponName: '',
    mods: Array(8).fill(null),
    compat: 'RIFLE',        // 무기의 모드 호환 코드
    activeSlotIdx: -1,
    initialized: false,
};

let _calcSearchDebounceTimer = null;
let _weaponSearchDebounce = null;
let _weaponSearchApiUrl = '';

// ── 한국어 스탯 이름 매핑 ──────────────────────────────────────────────────
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

const ELEM_KO = {
    heat: '화염', cold: '냉기', electricity: '전기', toxin: '독',
    magnetic: '자기', radiation: '방사능', viral: '바이러스',
    corrosive: '부식', blast: '폭발', gas: '가스',
};

function formatEffects(effects) {
    return Object.entries(effects || {})
        .map(([k, v]) => `${v > 0 ? '+' : ''}${v}% ${STAT_KO[k] || ELEM_KO[k] || k}`)
        .join(', ');
}

// ══════════════════════════════════════════════════════════════════════════
// ── 루트 초기화 & 모드 전환 ────────────────────────────────────────────────
// ══════════════════════════════════════════════════════════════════════════

async function initCalc() {
    if (!calcState.initialized) {
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
    }
    renderCalcRoot();
    ensureCalcSearchModal();
    ensureWeaponSearchModal();
}

function renderCalcRoot() {
    const container = document.getElementById('calc-container');
    if (!container) return;
    container.innerHTML = `
        <div class="calc-mode-bar">
            <button class="calc-mode-btn${calcRootMode === 'warframe' ? ' active' : ''}" onclick="switchCalcMode('warframe')">워프레임 모딩</button>
            <button class="calc-mode-btn${calcRootMode === 'weapon' ? ' active' : ''}" onclick="switchCalcMode('weapon')">무기 모딩</button>
        </div>
        <div id="calc-wf-inner"${calcRootMode !== 'warframe' ? ' style="display:none;"' : ''}></div>
        <div id="calc-wp-inner"${calcRootMode !== 'weapon' ? ' style="display:none;"' : ''}></div>`;

    if (calcRootMode === 'warframe') {
        renderWfCalc();
    } else {
        if (!weaponCalcState.initialized) {
            weaponCalcState.initialized = true;
        }
        renderWeaponCalc();
    }
}

function switchCalcMode(mode) {
    if (mode === calcRootMode) return;
    calcRootMode = mode;
    renderCalcRoot();
    ensureCalcSearchModal();
    ensureWeaponSearchModal();
}

// ══════════════════════════════════════════════════════════════════════════
// ── 워프레임 모딩 ───────────────────────────────────────────────────────────
// ══════════════════════════════════════════════════════════════════════════

function renderWfCalc() {
    const container = document.getElementById('calc-wf-inner');
    if (!container) return;

    const selName  = calcState.warframeItem?.name || '';
    const hasPrime = calcState.warframeItem?.has_prime || false;
    const isPrime  = calcState.isPrime;

    container.innerHTML = `
<div class="calc-layout">
    <div class="calc-left">
        <div class="calc-section">
            <div class="calc-section-title">워프레임</div>
            <div class="calc-wf-row">
                <select id="calc-wf-select" class="calc-wf-select" onchange="onCalcWfSelect(this.value)">
                    <option value="">-- 워프레임 선택 --</option>
                    ${calcState.warframeList.map(wf =>
                        `<option value="${escapeHtml(wf.name)}"${wf.name === selName ? ' selected' : ''}>${escapeHtml(wf.ko_name || wf.name)}</option>`
                    ).join('')}
                </select>
                <label class="calc-prime-label${hasPrime ? '' : ' calc-prime-disabled'}" id="calc-prime-label">
                    <input type="checkbox" id="calc-prime-chk" onchange="onCalcPrimeChange(this.checked)"${hasPrime ? '' : ' disabled'}${isPrime ? ' checked' : ''}>
                    <span>프라임</span>
                </label>
            </div>
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

        <div class="calc-section calc-builds-section">
            <div class="calc-section-title">내 빌드</div>
            <div class="calc-save-row">
                <input type="text" id="calc-build-name" class="calc-build-name-input"
                    placeholder="빌드 이름..." maxlength="30"
                    onkeydown="if(event.key==='Enter')saveCalcBuild()">
                <button class="calc-save-btn" onclick="saveCalcBuild()">저장</button>
            </div>
            <div id="calc-builds-list"></div>
        </div>

        <button class="calc-share-btn" onclick="openCalcShareModal()">💬 채팅방 공유</button>
    </div>
</div>`;

    renderModGrid();
    renderArcaneRow();
    renderShardRow();
    renderCalcBuildsPanel();
    _updateWfStats();
}

// 슬롯 0 = 오라, 슬롯 1 = 엑실러스, 슬롯 2-9 = 일반
const _SLOT_META = {
    0: { cls: 'calc-slot-aura',   tag: '오라',    tagCls: 'aura-tag',   labelCls: 'aura-label'   },
    1: { cls: 'calc-slot-exilus', tag: '엑실러스', tagCls: 'exilus-tag', labelCls: 'exilus-label' },
};

function renderModGrid() {
    const grid = document.getElementById('calc-mod-grid');
    if (!grid) return;

    let totalCost = 0;
    let html = '';
    for (let i = 0; i < 10; i++) {
        const mod  = calcState.mods[i];
        const meta = _SLOT_META[i];
        const extraCls  = meta ? ` ${meta.cls}` : '';
        const slotLabel = meta ? meta.tag : `모드 ${i - 1}`;

        if (mod) {
            totalCost += (mod.rank || 0);
            const tagHtml = meta
                ? `<span class="calc-slot-type-tag ${meta.tagCls}">${meta.tag}</span>`
                : '';
            html += `<div class="calc-slot calc-slot-filled${extraCls}" onclick="openModSearch(${i})">
                <button class="calc-slot-remove" onclick="event.stopPropagation();clearCalcSlot('mod',${i})">×</button>
                ${tagHtml}
                <span class="calc-slot-name">${escapeHtml(mod.name)}</span>
                <span class="calc-slot-rank">R${mod.rank}</span>
            </div>`;
        } else {
            const lblCls = meta ? ` ${meta.labelCls}` : '';
            html += `<div class="calc-slot calc-slot-empty${extraCls}" onclick="openModSearch(${i})">
                <span class="calc-slot-plus">+</span>
                <span class="calc-slot-label${lblCls}">${slotLabel}</span>
            </div>`;
        }
    }
    grid.innerHTML = html;

    const badge = document.getElementById('calc-capacity');
    if (badge) badge.textContent = `소모 ${totalCost}`;
}

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

function onCalcWfSelect(name) {
    const item = calcState.warframeList.find(w => w.name === name);
    calcState.warframeItem = item || null;
    calcState.isPrime = false;

    const primeChk = document.getElementById('calc-prime-chk');
    const primeLabel = document.getElementById('calc-prime-label');
    if (primeChk) {
        primeChk.checked = false;
        primeChk.disabled = !item || !item.has_prime;
    }
    if (primeLabel) {
        primeLabel.classList.toggle('calc-prime-disabled', !item || !item.has_prime);
    }

    if (item) {
        calcState.warframe = { name: item.name, ...item.base };
    } else {
        calcState.warframe = null;
    }

    _updateWfStats();
    computeAndRender();
}

function onCalcPrimeChange(checked) {
    calcState.isPrime = checked;
    const item = calcState.warframeItem;
    if (!item) return;

    if (checked && item.prime) {
        calcState.warframe = { name: item.name + ' Prime', ...item.prime };
    } else {
        calcState.warframe = { name: item.name, ...item.base };
    }
    _updateWfStats();
    computeAndRender();
}

function _updateWfStats() {
    const statsEl = document.getElementById('calc-wf-stats');
    if (!statsEl) return;
    const wf = calcState.warframe;
    if (wf) {
        statsEl.innerHTML =
            `<span>체력 ${wf.health}</span><span>실드 ${wf.shield}</span>` +
            `<span>방어도 ${wf.armor}</span><span>에너지 ${wf.power}</span>`;
    } else {
        statsEl.innerHTML = '';
    }
}

function openModSearch(idx) {
    _calcSearchMode = 'warframe';
    calcState.activeSlotType = 'mod';
    calcState.activeSlotIdx = idx;
    let apiUrl, placeholder;
    if (idx === 0) {
        apiUrl      = '/api/calc/mods?compat=AURA';
        placeholder = '오라 모드 이름...';
    } else if (idx === 1) {
        apiUrl      = '/api/calc/mods?compat=EXILUS';
        placeholder = '엑실러스 모드 이름...';
    } else {
        apiUrl      = '/api/calc/mods?compat=WARFRAME';
        placeholder = '모드 이름...';
    }
    openCalcSearchModal(placeholder, apiUrl);
}

function openArcaneSearch(idx) {
    _calcSearchMode = 'warframe';
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
            const sep = _calcSearchApiUrl.includes('?') ? '&' : '?';
            const r = await fetch(`${_calcSearchApiUrl}${sep}q=${encodeURIComponent(q)}`);
            const d = await r.json();
            const items = d.items || [];
            if (!items.length) {
                results.innerHTML = '<div class="calc-search-empty">검색 결과 없음</div>';
                return;
            }

            if (_calcSearchMode === 'weapon') {
                results.innerHTML = items.map(item => {
                    return `<div class="calc-search-item" onclick='selectCalcItem(${JSON.stringify(item)})'>
                        <span class="calc-search-name">${escapeHtml(item.name)}</span>
                        <span class="calc-search-meta">R${item.maxRank || item.fusionLimit || 0} | ${escapeHtml(item.polarity || '-')}</span>
                        <span class="calc-search-effects">${escapeHtml(formatEffects(item.effects))}</span>
                    </div>`;
                }).join('');
            } else if (calcState.activeSlotType === 'mod') {
                results.innerHTML = items.map(item => {
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

function _modBaseName(name) {
    return name.replace(/^(Umbral|Primed|Amalgam|Sacrificial)\s+/i, '').trim().toLowerCase();
}

function _findConflictingMod(newName, excludeIdx) {
    const newBase = _modBaseName(newName);
    for (let i = 0; i < calcState.mods.length; i++) {
        if (i === excludeIdx) continue;
        const m = calcState.mods[i];
        if (!m) continue;
        if (m.name === newName) return m.name;
        if (_modBaseName(m.name) === newBase) return m.name;
    }
    return null;
}

function selectCalcItem(item) {
    // 무기 모드 선택
    if (_calcSearchMode === 'weapon') {
        const idx = weaponCalcState.activeSlotIdx;
        if (idx < 0) return;
        const rank = item.fusionLimit !== undefined ? item.fusionLimit : (item.maxRank || 0);
        weaponCalcState.mods[idx] = { ...item, rank };
        closeCalcSearch();
        renderWeaponModGrid();
        computeWeaponAndRender();
        return;
    }

    // 워프레임 모드/아케인 선택
    const { activeSlotType, activeSlotIdx } = calcState;
    if (activeSlotIdx < 0) return;

    if (activeSlotType === 'mod') {
        const conflict = _findConflictingMod(item.name, activeSlotIdx);
        if (conflict) {
            alert(`"${conflict}"이(가) 이미 장착되어 있어\n"${item.name}"을(를) 추가할 수 없습니다.`);
            return;
        }
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

function clearCalcSlot(type, idx) {
    if (type === 'mod') calcState.mods[idx] = null;
    else if (type === 'arcane') calcState.arcanes[idx] = null;
    renderModGrid();
    renderArcaneRow();
    computeAndRender();
}

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
        }
    } catch (e) {
        console.error('[calc] compute 요청 실패:', e);
    }
}

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

// ── 빌드 저장/불러오기 (localStorage) ─────────────────────────────────────

const CALC_BUILDS_KEY = 'wf_calc_builds';

function _getCalcBuilds() {
    try { return JSON.parse(localStorage.getItem(CALC_BUILDS_KEY) || '[]'); }
    catch { return []; }
}

function saveCalcBuild() {
    if (!calcState.warframe) { alert('워프레임을 먼저 선택해주세요.'); return; }
    const nameInput = document.getElementById('calc-build-name');
    const buildName = (nameInput?.value || '').trim();
    if (!buildName) { alert('빌드 이름을 입력해주세요.'); return; }

    const builds = _getCalcBuilds();
    const existing = builds.findIndex(b => b.name === buildName);

    if (existing >= 0 && !confirm(`"${buildName}" 빌드를 덮어쓸까요?`)) return;

    const newBuild = {
        id:            existing >= 0 ? builds[existing].id : Date.now(),
        name:          buildName,
        warframeName:  calcState.warframeItem?.name || '',
        isPrime:       calcState.isPrime,
        mods:          calcState.mods.map(m => m ? { ...m } : null),
        shards:        calcState.shards.map(s => s ? { ...s } : null),
        arcanes:       calcState.arcanes.map(a => a ? { ...a } : null),
        savedAt:       new Date().toLocaleString('ko-KR'),
    };

    if (existing >= 0) builds[existing] = newBuild;
    else builds.unshift(newBuild);

    localStorage.setItem(CALC_BUILDS_KEY, JSON.stringify(builds.slice(0, 20)));
    if (nameInput) nameInput.value = '';
    renderCalcBuildsPanel();
}

function loadCalcBuild(buildId) {
    const build = _getCalcBuilds().find(b => b.id === buildId);
    if (!build) return;

    const wfItem = calcState.warframeList.find(w => w.name === build.warframeName);
    calcState.warframeItem = wfItem || null;
    calcState.isPrime = !!(build.isPrime && wfItem?.has_prime);

    if (wfItem) {
        const stats = calcState.isPrime ? wfItem.prime : wfItem.base;
        const displayName = calcState.isPrime ? wfItem.name + ' Prime' : wfItem.name;
        calcState.warframe = stats ? { name: displayName, ...stats } : null;
    } else {
        calcState.warframe = null;
    }

    const pad = (arr, len) => {
        const r = (arr || []).map(x => x ? { ...x } : null);
        while (r.length < len) r.push(null);
        return r.slice(0, len);
    };
    calcState.mods    = pad(build.mods,    10);
    calcState.shards  = pad(build.shards,   5);
    calcState.arcanes = pad(build.arcanes,  2);

    if (calcRootMode !== 'warframe') {
        calcRootMode = 'warframe';
        renderCalcRoot();
    } else {
        renderWfCalc();
    }
    computeAndRender();
}

function deleteCalcBuild(buildId) {
    if (!confirm('이 빌드를 삭제하시겠습니까?')) return;
    const builds = _getCalcBuilds().filter(b => b.id !== buildId);
    localStorage.setItem(CALC_BUILDS_KEY, JSON.stringify(builds));
    renderCalcBuildsPanel();
}

function renderCalcBuildsPanel() {
    const listEl = document.getElementById('calc-builds-list');
    if (!listEl) return;

    const builds = _getCalcBuilds();
    if (!builds.length) {
        listEl.innerHTML = '<div class="calc-builds-empty">저장된 빌드 없음</div>';
        return;
    }

    listEl.innerHTML = builds.map(b => {
        const wfKo = calcState.warframeList.find(w => w.name === b.warframeName)?.ko_name || b.warframeName || '';
        const label = b.isPrime ? wfKo + ' 프라임' : wfKo;
        return `<div class="calc-build-item">
            <div class="calc-build-item-info" onclick="loadCalcBuild(${b.id})">
                <div class="calc-build-item-name">${escapeHtml(b.name)}</div>
                <div class="calc-build-item-meta">${escapeHtml(label)} · ${escapeHtml(b.savedAt || '')}</div>
            </div>
            <button class="calc-build-delete-btn" onclick="event.stopPropagation();deleteCalcBuild(${b.id})" title="삭제">×</button>
        </div>`;
    }).join('');
}

// ── 채팅방 공유 (워프레임) ─────────────────────────────────────────────────

function _buildMemoText() {
    const item   = calcState.warframeItem;
    const wfKo   = item ? (item.ko_name || item.name) : '?';
    const header = calcState.isPrime ? `${wfKo} 프라임` : wfKo;
    const lines  = [`◆ ${header} 빌드`, ''];

    const filledMods = calcState.mods.filter(Boolean);
    if (filledMods.length) {
        lines.push('[모드]');
        filledMods.forEach(m => {
            const fx = formatEffects(m.effects);
            lines.push(`• ${m.name} R${m.rank}${fx ? '  (' + fx + ')' : ''}`);
        });
        lines.push('');
    }

    const filledShards = calcState.shards.filter(Boolean);
    if (filledShards.length) {
        lines.push('[아케인 샤드]');
        filledShards.forEach(s => {
            const def       = calcState.shardsData[s.color];
            const colorName = def?.name || s.color;
            const opt       = def?.options?.find(o => o.key === s.option_key);
            const optLabel  = opt?.label || s.option_key;
            const tauStr    = s.tauforged ? ' (타우)' : '';
            lines.push(`• ${colorName}: ${optLabel}${tauStr}`);
        });
        lines.push('');
    }

    const filledArcanes = calcState.arcanes.filter(Boolean);
    if (filledArcanes.length) {
        lines.push('[아케인]');
        filledArcanes.forEach(a => lines.push(`• ${a.name}`));
    }

    return lines.join('\n').trim();
}

function openCalcShareModal() {
    if (!calcState.warframe) { alert('워프레임을 먼저 선택해주세요.'); return; }

    const item       = calcState.warframeItem;
    const wfKo       = item ? (item.ko_name || item.name) : (calcState.warframe?.name || '');
    const itemName   = calcState.isPrime ? wfKo + ' 프라임' : wfKo;
    const savedAuthor = localStorage.getItem('tradeName') || '';
    const memo       = _buildMemoText();

    const overlay = document.createElement('div');
    overlay.id = 'calc-share-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:3000;display:flex;align-items:center;justify-content:center;padding:12px;';
    overlay.onclick = e => { if (e.target === overlay) overlay.remove(); };

    overlay.innerHTML = `<div class="calc-share-popup">
        <div class="calc-share-popup-header">
            <span>💬 채팅방 공유</span>
            <button onclick="document.getElementById('calc-share-overlay').remove()">×</button>
        </div>
        <div class="calc-share-popup-body">
            <div class="calc-share-field">
                <label>아이템</label>
                <input type="text" id="csp-item" value="${escapeHtml(itemName)}" maxlength="50" placeholder="워프레임 이름">
            </div>
            <div class="calc-share-field">
                <label>작성자</label>
                <input type="text" id="csp-author" value="${escapeHtml(savedAuthor)}" maxlength="20" placeholder="닉네임">
            </div>
            <div class="calc-share-field">
                <label>빌드 설명 (자동 입력 · 수정 가능)</label>
                <textarea id="csp-memo" rows="7" maxlength="1000">${escapeHtml(memo)}</textarea>
            </div>
            <div class="calc-share-btns">
                <button class="calc-share-cancel" onclick="document.getElementById('calc-share-overlay').remove()">취소</button>
                <button class="calc-share-submit" id="csp-submit-btn" onclick="submitCalcShare()">공유하기</button>
            </div>
        </div>
    </div>`;

    document.body.appendChild(overlay);
    setTimeout(() => overlay.querySelector('#csp-author')?.focus(), 50);
}

async function submitCalcShare() {
    const overlay   = document.getElementById('calc-share-overlay');
    const itemName  = (overlay?.querySelector('#csp-item')?.value   || '').trim();
    const author    = (overlay?.querySelector('#csp-author')?.value || '').trim();
    const memo      = (overlay?.querySelector('#csp-memo')?.value   || '').trim();

    if (!author)   { alert('작성자 이름을 입력해주세요.'); return; }
    if (!itemName) { alert('아이템 이름을 입력해주세요.'); return; }

    const btn = overlay?.querySelector('#csp-submit-btn');
    if (btn) { btn.disabled = true; btn.textContent = '공유 중...'; }

    try {
        const res = await fetch('/api/modding/shares', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({
                category:        'warframe',
                item_name:       itemName,
                author:          author,
                memo:            memo,
                sub_type:        '',
                image_filenames: [],
            }),
        });
        const d = await res.json();
        if (d.ok) {
            localStorage.setItem('tradeName', author);
            overlay?.remove();
            alert('채팅방에 공유됐습니다!\n모딩 공유 탭 → 워프레임에서 확인할 수 있어요.');
        } else {
            alert('공유 실패: ' + (d.msg || '오류'));
            if (btn) { btn.disabled = false; btn.textContent = '공유하기'; }
        }
    } catch (e) {
        alert('네트워크 오류가 발생했습니다.');
        if (btn) { btn.disabled = false; btn.textContent = '공유하기'; }
    }
}

// ══════════════════════════════════════════════════════════════════════════
// ── 무기 모딩 ─────────────────────────────────────────────────────────────
// ══════════════════════════════════════════════════════════════════════════

function renderWeaponCalc() {
    const container = document.getElementById('calc-wp-inner');
    if (!container) return;

    const wt = weaponCalcState.weaponType;
    const w  = weaponCalcState.weapon;
    const frLabel = wt === 'melee' ? '공격속도' : '연사속도';

    container.innerHTML = `
<div class="calc-layout">
    <div class="calc-left">
        <div class="calc-section">
            <div class="calc-section-title">무기 유형</div>
            <div class="calc-weapon-type-bar">
                <button class="calc-weapon-type-btn${wt === 'primary' ? ' active' : ''}" onclick="onWeaponTypeChange('primary')">주무기</button>
                <button class="calc-weapon-type-btn${wt === 'secondary' ? ' active' : ''}" onclick="onWeaponTypeChange('secondary')">보조무기</button>
                <button class="calc-weapon-type-btn${wt === 'melee' ? ' active' : ''}" onclick="onWeaponTypeChange('melee')">근접</button>
            </div>
        </div>

        <div class="calc-section">
            <div class="calc-section-title">무기</div>
            <div class="calc-weapon-search-row">
                <div class="calc-weapon-display${w ? ' calc-weapon-selected' : ''}" onclick="openWeaponSearch()">
                    ${w
                        ? `<span class="calc-weapon-name">${escapeHtml(weaponCalcState.weaponName)}</span>
                           <span class="calc-weapon-type-tag">${escapeHtml(w.type || '')}</span>`
                        : `<span class="calc-weapon-placeholder">무기를 선택하세요...</span>`
                    }
                </div>
                ${w ? `<button class="calc-weapon-clear" onclick="clearWeaponSelection()">×</button>` : ''}
            </div>
            ${w ? `<div class="calc-wf-stats">
                <span>데미지 ${w.totalDamage}</span>
                <span>CC ${(w.critChance * 100).toFixed(0)}%</span>
                <span>CM ${w.critMultiplier}x</span>
                <span>SC ${(w.statusChance * 100).toFixed(0)}%</span>
                <span>${frLabel} ${w.fireRate}</span>
            </div>` : ''}
        </div>

        <div class="calc-section">
            <div class="calc-section-title">모드 슬롯 <span class="calc-capacity-badge" id="wpcalc-capacity">소모 0</span></div>
            <div class="calc-mod-grid" id="wpcalc-mod-grid"></div>
        </div>

        <button class="calc-share-btn" onclick="openWeaponCalcShareModal()" style="margin-top:4px;">💬 채팅방 공유</button>
    </div>

    <div class="calc-right">
        <div class="calc-section">
            <div class="calc-section-title">빌드 스탯</div>
            <div id="wpcalc-stats-panel" class="calc-stats-panel">
                <div class="calc-stats-empty">무기를 선택하면<br>스탯이 표시됩니다</div>
            </div>
        </div>

        <div class="calc-section calc-builds-section">
            <div class="calc-section-title">내 빌드</div>
            <div class="calc-save-row">
                <input type="text" id="wpcalc-build-name" class="calc-build-name-input"
                    placeholder="빌드 이름..." maxlength="30"
                    onkeydown="if(event.key==='Enter')saveWeaponCalcBuild()">
                <button class="calc-save-btn" onclick="saveWeaponCalcBuild()">저장</button>
            </div>
            <div id="wpcalc-builds-list"></div>
        </div>
    </div>
</div>`;

    renderWeaponModGrid();
    renderWeaponCalcBuildsPanel();
    if (w) computeWeaponAndRender();
}

function renderWeaponModGrid() {
    const grid = document.getElementById('wpcalc-mod-grid');
    if (!grid) return;

    let totalCost = 0;
    let html = '';
    for (let i = 0; i < 8; i++) {
        const mod = weaponCalcState.mods[i];
        if (mod) {
            totalCost += (mod.rank || 0);
            html += `<div class="calc-slot calc-slot-filled" onclick="openWeaponModSearch(${i})">
                <button class="calc-slot-remove" onclick="event.stopPropagation();clearWeaponCalcSlot(${i})">×</button>
                <span class="calc-slot-name">${escapeHtml(mod.name)}</span>
                <span class="calc-slot-rank">R${mod.rank}</span>
            </div>`;
        } else {
            html += `<div class="calc-slot calc-slot-empty" onclick="openWeaponModSearch(${i})">
                <span class="calc-slot-plus">+</span>
                <span class="calc-slot-label">모드 ${i + 1}</span>
            </div>`;
        }
    }
    grid.innerHTML = html;

    const badge = document.getElementById('wpcalc-capacity');
    if (badge) badge.textContent = `소모 ${totalCost}`;
}

function onWeaponTypeChange(type) {
    if (type === weaponCalcState.weaponType) return;
    weaponCalcState.weaponType  = type;
    weaponCalcState.weapon      = null;
    weaponCalcState.weaponName  = '';
    weaponCalcState.mods        = Array(8).fill(null);
    weaponCalcState.compat      = type === 'secondary' ? 'PISTOL' : type === 'melee' ? 'MELEE' : 'RIFLE';
    renderWeaponCalc();
}

function openWeaponSearch() {
    openWeaponSearchModal(`/api/calc/weapons?type=${weaponCalcState.weaponType}`);
}

function clearWeaponSelection() {
    weaponCalcState.weapon     = null;
    weaponCalcState.weaponName = '';
    weaponCalcState.mods       = Array(8).fill(null);
    renderWeaponCalc();
}

function openWeaponModSearch(idx) {
    _calcSearchMode = 'weapon';
    weaponCalcState.activeSlotIdx = idx;
    const compat = weaponCalcState.compat || 'RIFLE';
    openCalcSearchModal('모드 이름...', `/api/calc/weapon-mods?compat=${compat}`);
}

function clearWeaponCalcSlot(idx) {
    weaponCalcState.mods[idx] = null;
    renderWeaponModGrid();
    computeWeaponAndRender();
}

// ── 무기 검색 전용 모달 ──────────────────────────────────────────────────────

function ensureWeaponSearchModal() {
    if (document.getElementById('wp-search-overlay')) return;

    const overlay = document.createElement('div');
    overlay.id = 'wp-search-overlay';
    overlay.onclick = closeWeaponSearch;

    const modal = document.createElement('div');
    modal.id = 'wp-search-modal';
    modal.innerHTML = `
<div class="calc-search-header">
    <input type="text" id="wp-search-input" placeholder="무기 이름 검색..." oninput="onWeaponSearchInput()" autocomplete="off">
    <button onclick="closeWeaponSearch()">×</button>
</div>
<div id="wp-search-results"></div>`;

    document.body.appendChild(overlay);
    document.body.appendChild(modal);
}

function openWeaponSearchModal(apiUrl) {
    ensureWeaponSearchModal();
    _weaponSearchApiUrl = apiUrl;

    const inp = document.getElementById('wp-search-input');
    if (inp) { inp.value = ''; inp.placeholder = '무기 이름 검색...'; }
    const results = document.getElementById('wp-search-results');
    if (results) results.innerHTML = '';

    document.getElementById('wp-search-overlay').style.display = 'block';
    document.getElementById('wp-search-modal').style.display = 'flex';
    setTimeout(() => { if (inp) inp.focus(); }, 50);
}

function closeWeaponSearch() {
    const overlay = document.getElementById('wp-search-overlay');
    const modal   = document.getElementById('wp-search-modal');
    if (overlay) overlay.style.display = 'none';
    if (modal)   modal.style.display   = 'none';
}

function onWeaponSearchInput() {
    clearTimeout(_weaponSearchDebounce);
    _weaponSearchDebounce = setTimeout(async () => {
        const inp = document.getElementById('wp-search-input');
        if (!inp) return;
        const q = inp.value.trim();
        const results = document.getElementById('wp-search-results');
        if (!results) return;
        if (!q) { results.innerHTML = ''; return; }

        try {
            const sep = _weaponSearchApiUrl.includes('?') ? '&' : '?';
            const r = await fetch(`${_weaponSearchApiUrl}${sep}q=${encodeURIComponent(q)}`);
            const d = await r.json();
            const items = d.items || [];
            if (!items.length) {
                results.innerHTML = '<div class="calc-search-empty">검색 결과 없음</div>';
                return;
            }
            const wt = weaponCalcState.weaponType;
            const frLabel = wt === 'melee' ? '공격속도' : '연사속도';
            results.innerHTML = items.map(item => {
                const cc = (item.critChance * 100).toFixed(0);
                const sc = (item.statusChance * 100).toFixed(0);
                return `<div class="calc-search-item" onclick='selectWeaponItem(${JSON.stringify(item)})'>
                    <span class="calc-search-name">${escapeHtml(item.name)}</span>
                    <span class="calc-search-meta">${escapeHtml(item.type || '')} | CC ${cc}% CM ${item.critMultiplier}x SC ${sc}%</span>
                    <span class="calc-search-effects">데미지 ${item.totalDamage} | ${frLabel} ${item.fireRate}</span>
                </div>`;
            }).join('');
        } catch (e) {
            console.error('[weapon-calc] 검색 실패:', e);
            const r2 = document.getElementById('wp-search-results');
            if (r2) r2.innerHTML = '<div class="calc-search-empty">오류가 발생했습니다</div>';
        }
    }, 300);
}

function selectWeaponItem(item) {
    weaponCalcState.weapon     = item;
    weaponCalcState.weaponName = item.name;
    weaponCalcState.compat     = item.compat || 'RIFLE';
    weaponCalcState.mods       = Array(8).fill(null);
    closeWeaponSearch();
    renderWeaponCalc();
}

// ── 무기 스탯 계산 ─────────────────────────────────────────────────────────

async function computeWeaponAndRender() {
    if (!weaponCalcState.weapon) return;

    const payload = {
        base: weaponCalcState.weapon,
        mods: weaponCalcState.mods.filter(Boolean).map(m => ({
            name: m.name,
            effects: m.effects,
            rank: m.rank,
            fusionLimit: m.fusionLimit,
        })),
    };

    try {
        const r = await fetch('/api/calc/compute-weapon', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const d = await r.json();
        if (d.ok) {
            renderWeaponStatsPanel(d.stats, weaponCalcState.weapon);
        }
    } catch (e) {
        console.error('[weapon-calc] compute 실패:', e);
    }
}

function renderWeaponStatsPanel(stats, base) {
    const panel = document.getElementById('wpcalc-stats-panel');
    if (!panel) return;

    const wt = weaponCalcState.weaponType;
    const frLabel = wt === 'melee' ? '공격속도' : '연사속도';
    const baseCC = parseFloat((base.critChance * 100).toFixed(1));
    const baseSC = parseFloat((base.statusChance * 100).toFixed(1));

    let elemRows = '';
    if (stats.elemental && Object.keys(stats.elemental).length > 0) {
        elemRows = Object.entries(stats.elemental).map(([k, v]) =>
            `<div class="calc-stat-row">
                <span class="calc-stat-label">${escapeHtml(ELEM_KO[k] || k)} 데미지</span>
                <div class="calc-stat-values">
                    <span class="calc-stat-base">0</span>
                    <span class="calc-stat-arrow">→</span>
                    <span class="calc-stat-final calc-stat-up">${v}</span>
                </div>
            </div>`
        ).join('');
    }

    panel.innerHTML = `<div class="calc-stats-grid">
        ${renderStatRow('총 데미지',   base.totalDamage,  stats.totalDamage,   '')}
        ${renderStatRow('충격',        base.impact,       stats.impact,         '')}
        ${renderStatRow('관통',        base.puncture,     stats.puncture,       '')}
        ${renderStatRow('베기',        base.slash,        stats.slash,          '')}
        ${elemRows}
        ${renderStatRow('치명타 확률', baseCC,            stats.critChance,     '%')}
        ${renderStatRow('치명타 배율', base.critMultiplier, stats.critMultiplier, 'x')}
        ${renderStatRow('상태이상',    baseSC,            stats.statusChance,   '%')}
        ${renderStatRow(frLabel,       base.fireRate,     stats.fireRate,       '')}
        ${renderStatRow('멀티샷',      1.0,               stats.multishot,      'x')}
        <div class="calc-stat-row calc-stat-dps-row">
            <span class="calc-stat-label">예상 DPS</span>
            <div class="calc-stat-values">
                <span class="calc-stat-final calc-stat-up">${stats.dps}</span>
            </div>
        </div>
    </div>`;
}

// ── 무기 빌드 저장/불러오기 ────────────────────────────────────────────────

const WP_CALC_BUILDS_KEY = 'wf_wp_calc_builds';

function _getWeaponCalcBuilds() {
    try { return JSON.parse(localStorage.getItem(WP_CALC_BUILDS_KEY) || '[]'); }
    catch { return []; }
}

function saveWeaponCalcBuild() {
    if (!weaponCalcState.weapon) { alert('무기를 먼저 선택해주세요.'); return; }
    const nameInput = document.getElementById('wpcalc-build-name');
    const buildName = (nameInput?.value || '').trim();
    if (!buildName) { alert('빌드 이름을 입력해주세요.'); return; }

    const builds = _getWeaponCalcBuilds();
    const existing = builds.findIndex(b => b.name === buildName);
    if (existing >= 0 && !confirm(`"${buildName}" 빌드를 덮어쓸까요?`)) return;

    const newBuild = {
        id:         existing >= 0 ? builds[existing].id : Date.now(),
        name:       buildName,
        weaponType: weaponCalcState.weaponType,
        weaponName: weaponCalcState.weaponName,
        weapon:     weaponCalcState.weapon ? { ...weaponCalcState.weapon } : null,
        compat:     weaponCalcState.compat,
        mods:       weaponCalcState.mods.map(m => m ? { ...m } : null),
        savedAt:    new Date().toLocaleString('ko-KR'),
    };

    if (existing >= 0) builds[existing] = newBuild;
    else builds.unshift(newBuild);

    localStorage.setItem(WP_CALC_BUILDS_KEY, JSON.stringify(builds.slice(0, 20)));
    if (nameInput) nameInput.value = '';
    renderWeaponCalcBuildsPanel();
}

function loadWeaponCalcBuild(buildId) {
    const build = _getWeaponCalcBuilds().find(b => b.id === buildId);
    if (!build) return;

    weaponCalcState.weaponType  = build.weaponType || 'primary';
    weaponCalcState.weaponName  = build.weaponName || '';
    weaponCalcState.weapon      = build.weapon ? { ...build.weapon } : null;
    weaponCalcState.compat      = build.compat || 'RIFLE';
    const pad = (arr, len) => {
        const r = (arr || []).map(x => x ? { ...x } : null);
        while (r.length < len) r.push(null);
        return r.slice(0, len);
    };
    weaponCalcState.mods = pad(build.mods, 8);

    if (calcRootMode !== 'weapon') {
        calcRootMode = 'weapon';
        renderCalcRoot();
    } else {
        renderWeaponCalc();
    }
}

function deleteWeaponCalcBuild(buildId) {
    if (!confirm('이 빌드를 삭제하시겠습니까?')) return;
    const builds = _getWeaponCalcBuilds().filter(b => b.id !== buildId);
    localStorage.setItem(WP_CALC_BUILDS_KEY, JSON.stringify(builds));
    renderWeaponCalcBuildsPanel();
}

function renderWeaponCalcBuildsPanel() {
    const listEl = document.getElementById('wpcalc-builds-list');
    if (!listEl) return;

    const builds = _getWeaponCalcBuilds();
    if (!builds.length) {
        listEl.innerHTML = '<div class="calc-builds-empty">저장된 빌드 없음</div>';
        return;
    }

    const typeLabel = t => t === 'primary' ? '주무기' : t === 'secondary' ? '보조무기' : '근접';
    listEl.innerHTML = builds.map(b =>
        `<div class="calc-build-item">
            <div class="calc-build-item-info" onclick="loadWeaponCalcBuild(${b.id})">
                <div class="calc-build-item-name">${escapeHtml(b.name)}</div>
                <div class="calc-build-item-meta">${escapeHtml(b.weaponName || '')} (${typeLabel(b.weaponType)}) · ${escapeHtml(b.savedAt || '')}</div>
            </div>
            <button class="calc-build-delete-btn" onclick="event.stopPropagation();deleteWeaponCalcBuild(${b.id})" title="삭제">×</button>
        </div>`
    ).join('');
}

// ── 무기 채팅방 공유 ──────────────────────────────────────────────────────

function _buildWeaponMemoText() {
    const wt = weaponCalcState.weaponType;
    const typeLabel = wt === 'primary' ? '주무기' : wt === 'secondary' ? '보조무기' : '근접';
    const lines = [`◆ ${weaponCalcState.weaponName} 빌드 (${typeLabel})`, ''];

    const filledMods = weaponCalcState.mods.filter(Boolean);
    if (filledMods.length) {
        lines.push('[모드]');
        filledMods.forEach(m => {
            const fx = formatEffects(m.effects);
            lines.push(`• ${m.name} R${m.rank}${fx ? '  (' + fx + ')' : ''}`);
        });
    }

    return lines.join('\n').trim();
}

function openWeaponCalcShareModal() {
    if (!weaponCalcState.weapon) { alert('무기를 먼저 선택해주세요.'); return; }

    const wt = weaponCalcState.weaponType;
    const catKey = wt === 'primary' ? 'primary_weapon' : wt === 'secondary' ? 'secondary_weapon' : 'melee_weapon';
    const memo = _buildWeaponMemoText();
    const savedAuthor = localStorage.getItem('tradeName') || '';

    const overlay = document.createElement('div');
    overlay.id = 'calc-share-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:3000;display:flex;align-items:center;justify-content:center;padding:12px;';
    overlay.onclick = e => { if (e.target === overlay) overlay.remove(); };

    overlay.innerHTML = `<div class="calc-share-popup">
        <div class="calc-share-popup-header">
            <span>💬 채팅방 공유</span>
            <button onclick="document.getElementById('calc-share-overlay').remove()">×</button>
        </div>
        <div class="calc-share-popup-body">
            <div class="calc-share-field">
                <label>아이템</label>
                <input type="text" id="csp-item" value="${escapeHtml(weaponCalcState.weaponName)}" maxlength="50" placeholder="무기 이름">
            </div>
            <div class="calc-share-field">
                <label>작성자</label>
                <input type="text" id="csp-author" value="${escapeHtml(savedAuthor)}" maxlength="20" placeholder="닉네임">
            </div>
            <div class="calc-share-field">
                <label>빌드 설명 (자동 입력 · 수정 가능)</label>
                <textarea id="csp-memo" rows="7" maxlength="1000">${escapeHtml(memo)}</textarea>
            </div>
            <div class="calc-share-btns">
                <button class="calc-share-cancel" onclick="document.getElementById('calc-share-overlay').remove()">취소</button>
                <button class="calc-share-submit" id="csp-submit-btn" onclick="submitWeaponCalcShare('${catKey}')">공유하기</button>
            </div>
        </div>
    </div>`;

    document.body.appendChild(overlay);
    setTimeout(() => overlay.querySelector('#csp-author')?.focus(), 50);
}

async function submitWeaponCalcShare(catKey) {
    const overlay  = document.getElementById('calc-share-overlay');
    const itemName = (overlay?.querySelector('#csp-item')?.value   || '').trim();
    const author   = (overlay?.querySelector('#csp-author')?.value || '').trim();
    const memo     = (overlay?.querySelector('#csp-memo')?.value   || '').trim();

    if (!author)   { alert('작성자 이름을 입력해주세요.'); return; }
    if (!itemName) { alert('아이템 이름을 입력해주세요.'); return; }

    const btn = overlay?.querySelector('#csp-submit-btn');
    if (btn) { btn.disabled = true; btn.textContent = '공유 중...'; }

    try {
        const res = await fetch('/api/modding/shares', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({
                category:        catKey,
                item_name:       itemName,
                author:          author,
                memo:            memo,
                sub_type:        '',
                image_filenames: [],
            }),
        });
        const d = await res.json();
        if (d.ok) {
            localStorage.setItem('tradeName', author);
            overlay?.remove();
            alert('채팅방에 공유됐습니다!\n모딩 공유 탭에서 확인할 수 있어요.');
        } else {
            alert('공유 실패: ' + (d.msg || '오류'));
            if (btn) { btn.disabled = false; btn.textContent = '공유하기'; }
        }
    } catch (e) {
        alert('네트워크 오류가 발생했습니다.');
        if (btn) { btn.disabled = false; btn.textContent = '공유하기'; }
    }
}
