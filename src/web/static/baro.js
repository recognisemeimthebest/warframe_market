/* 바로 키티어 탭 */
(function () {
    'use strict';

    let _currentSub = 'current';
    let _predictData = null;

    // ── 진입점 ─────────────────────────────────────────────────────────────────

    window.initBaroTab = function () {
        renderBaroSubBar();
        switchBaroSub(_currentSub);
    };

    function renderBaroSubBar() {
        const bar = document.getElementById('baro-sub-bar');
        if (!bar) return;
        bar.innerHTML = `
            <button class="baro-sub active" data-bsub="current">현재 방문</button>
            <button class="baro-sub" data-bsub="predict">예측</button>
            <button class="baro-sub" data-bsub="db">DB / 학습</button>
        `;
        bar.querySelectorAll('.baro-sub').forEach(btn => {
            btn.addEventListener('click', () => {
                bar.querySelectorAll('.baro-sub').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                switchBaroSub(btn.dataset.bsub);
            });
        });
    }

    function switchBaroSub(sub) {
        _currentSub = sub;
        ['current', 'predict', 'db'].forEach(s => {
            const el = document.getElementById(`baro-sub-${s}`);
            if (el) el.style.display = s === sub ? '' : 'none';
        });
        if (sub === 'current') loadBaroCurrent();
        if (sub === 'predict') loadBaroPredict();
        if (sub === 'db')      loadBaroDb();
    }

    // ── 현재 방문 ──────────────────────────────────────────────────────────────

    async function loadBaroCurrent() {
        const el = document.getElementById('baro-current-content');
        if (!el) return;
        el.innerHTML = '<p class="baro-loading">불러오는 중...</p>';

        try {
            const r = await fetch('/api/baro/current');
            const d = await r.json();
            el.innerHTML = renderCurrentVisit(d);
        } catch (e) {
            el.innerHTML = '<p class="baro-empty">데이터를 불러오지 못했습니다.</p>';
        }
    }

    function renderCurrentVisit(d) {
        if (!d || (!d.active && !d.inventory?.length)) {
            const eta = d?.eta ? `<p class="baro-eta">도착까지 <strong>${escapeHtml(d.eta)}</strong></p>` : '';
            return `<div class="baro-inactive">
                <div class="baro-icon">🚀</div>
                <p>바로 키티어가 현재 여행 중입니다.</p>
                ${eta}
            </div>`;
        }

        const locHtml = d.location
            ? `<p class="baro-location">📍 ${escapeHtml(d.location)}</p>` : '';
        const etaHtml = d.eta
            ? `<p class="baro-eta-active">${escapeHtml(d.eta_label || '출발까지')} <strong>${escapeHtml(d.eta)}</strong></p>` : '';

        const items = (d.inventory || []).map(item => {
            const name  = escapeHtml(item.item || '');
            const slug  = item.slug || '';
            const sell  = item.market_sell != null ? `<span class="baro-price-sell">${item.market_sell}p 판매</span>` : '';
            const buy   = item.market_buy  != null ? `<span class="baro-price-buy">${item.market_buy}p 구매</span>` : '';
            const mktLink = slug
                ? `<a href="https://warframe.market/items/${slug}" target="_blank" class="baro-mkt-link">시세▸</a>` : '';

            return `<div class="baro-item-card">
                <div class="baro-item-name">${name}</div>
                <div class="baro-item-cost">
                    <span class="baro-ducat">🪙 ${item.ducats ?? 0}</span>
                    <span class="baro-credit">₢ ${(item.credits ?? 0).toLocaleString()}</span>
                </div>
                <div class="baro-item-market">${sell}${buy}${mktLink}</div>
            </div>`;
        }).join('');

        return `<div class="baro-current-header">
            ${locHtml}${etaHtml}
            <p class="baro-item-count">${(d.inventory || []).length}개 아이템</p>
        </div>
        <div class="baro-item-grid">${items}</div>`;
    }

    // ── 예측 ───────────────────────────────────────────────────────────────────

    async function loadBaroPredict() {
        const el = document.getElementById('baro-predict-content');
        if (!el) return;
        el.innerHTML = '<p class="baro-loading">예측 모델 실행 중...</p>';

        try {
            const r = await fetch('/api/baro/predict?top=40');
            const d = await r.json();
            _predictData = d;
            el.innerHTML = renderPredictions(d);
        } catch (e) {
            el.innerHTML = '<p class="baro-empty">예측 데이터를 불러오지 못했습니다.</p>';
        }
    }

    function renderPredictions(d) {
        const preds = d.predictions || [];
        const model = d.model || {};

        if (!model.trained) {
            return `<div class="baro-no-model">
                <p>🤖 학습된 모델이 없습니다.</p>
                <p class="baro-hint">DB 탭에서 스크래핑 → 학습 순서로 진행하세요.</p>
            </div>`;
        }

        const aucBadge = model.best_auc
            ? `<span class="baro-auc-badge">AUC ${model.best_auc.toFixed(3)}</span>` : '';
        const trainDate = model.trained_at
            ? `<span class="baro-train-date">학습: ${model.trained_at.slice(0,10)}</span>` : '';

        const rows = preds.map((p, i) => {
            const bar = Math.round(p.probability_pct);
            const barColor = bar >= 70 ? 'var(--red)' : bar >= 40 ? 'var(--orange)' : 'var(--green)';
            const slug = (p.item_name || '').toLowerCase().replace(/[^a-z0-9]+/g, '_');
            return `<tr class="baro-pred-row ${bar >= 70 ? 'high-prob' : ''}">
                <td class="baro-pred-rank">${i + 1}</td>
                <td class="baro-pred-name">
                    <a href="https://warframe.market/items/${slug}" target="_blank">${escapeHtml(p.item_name)}</a>
                    <span class="baro-pred-type">${escapeHtml(p.item_type || '')}</span>
                </td>
                <td class="baro-pred-prob">
                    <div class="baro-prob-bar-wrap">
                        <div class="baro-prob-bar" style="width:${bar}%;background:${barColor}"></div>
                    </div>
                    <span class="baro-prob-pct" style="color:${barColor}">${p.probability_pct}%</span>
                </td>
                <td class="baro-pred-stat">${p.visits_since_last}회</td>
                <td class="baro-pred-stat">${p.avg_interval.toFixed(1)}</td>
                <td class="baro-pred-stat baro-ducat-col">🪙${p.ducat_cost}</td>
            </tr>`;
        }).join('');

        return `<div class="baro-predict-header">
            <span>총 ${d.total_visits || 0}회 방문 데이터 기반</span>
            ${aucBadge}${trainDate}
        </div>
        <div class="baro-predict-table-wrap">
            <table class="baro-predict-table">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>아이템</th>
                        <th>등장 확률</th>
                        <th>미등장</th>
                        <th>평균간격</th>
                        <th>덕키</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>`;
    }

    // ── DB / 학습 ──────────────────────────────────────────────────────────────

    async function loadBaroDb() {
        const el = document.getElementById('baro-db-content');
        if (!el) return;
        el.innerHTML = '<p class="baro-loading">상태 확인 중...</p>';

        try {
            const r = await fetch('/api/baro/status');
            const d = await r.json();
            el.innerHTML = renderDbPanel(d);
            _bindDbButtons();
        } catch (e) {
            el.innerHTML = '<p class="baro-empty">상태를 불러오지 못했습니다.</p>';
        }
    }

    function renderDbPanel(d) {
        const model = d.model || {};
        const trainRunning = d.train_running;
        const last = d.last_train;

        const dbStats = `
            <div class="baro-stat-grid">
                <div class="baro-stat"><span class="baro-stat-val">${d.total_visits ?? 0}</span><span class="baro-stat-lbl">총 방문</span></div>
                <div class="baro-stat"><span class="baro-stat-val">${d.total_items ?? 0}</span><span class="baro-stat-lbl">아이템</span></div>
                <div class="baro-stat"><span class="baro-stat-val">${d.total_appearances ?? 0}</span><span class="baro-stat-lbl">등장 기록</span></div>
                <div class="baro-stat"><span class="baro-stat-val">${d.last_visit_num ?? '-'}</span><span class="baro-stat-lbl">마지막 방문#</span></div>
            </div>`;

        const modelStats = model.trained
            ? `<div class="baro-model-info">
                <span class="baro-auc-badge">AUC ${(model.best_auc || 0).toFixed(3)}</span>
                <span class="baro-train-date">학습일 ${(model.trained_at || '').slice(0,10)}</span>
                ${renderImportance(model.feature_importance)}
               </div>`
            : `<p class="baro-hint">학습된 모델 없음</p>`;

        const trainBtn = trainRunning
            ? `<button class="baro-btn" disabled>⏳ 학습 중...</button>`
            : `<button class="baro-btn" id="baro-train-btn">🤖 모델 학습 (200 trials)</button>`;

        const lastResult = last
            ? `<p class="baro-hint">${last.ok
                ? `마지막 학습: AUC ${(last.best_auc||0).toFixed(3)}`
                : `학습 실패: ${escapeHtml(last.error||'')}`}</p>` : '';

        return `
            <div class="baro-db-section">
                <div class="baro-section-title">📦 데이터베이스</div>
                ${dbStats}
                <div class="baro-btn-row">
                    <button class="baro-btn" id="baro-scrape-btn">🔄 위키 스크래핑</button>
                    <button class="baro-btn baro-btn-sec" id="baro-sync-btn">📡 현재 방문 동기화</button>
                </div>
                <div id="baro-action-msg" class="baro-hint"></div>
            </div>
            <div class="baro-db-section">
                <div class="baro-section-title">🤖 LightGBM 모델</div>
                ${modelStats}
                <div class="baro-btn-row">${trainBtn}</div>
                ${lastResult}
            </div>`;
    }

    function renderImportance(imp) {
        if (!imp) return '';
        const sorted = Object.entries(imp).sort((a, b) => b[1] - a[1]);
        const max = sorted[0]?.[1] || 1;
        const rows = sorted.map(([k, v]) => {
            const pct = Math.round((v / max) * 100);
            const label = {
                visits_since_last: '미등장 횟수',
                avg_interval:      '평균 간격',
                std_interval:      '간격 편차',
                overdue_ratio:     '오버듀 비율',
                appearances_so_far:'총 등장 수',
                appearance_rate:   '등장률',
                log_ducat:         '덕키 (log)',
                item_type_enc:     '아이템 타입',
            }[k] || k;
            return `<div class="baro-imp-row">
                <span class="baro-imp-name">${label}</span>
                <div class="baro-imp-bar-wrap">
                    <div class="baro-imp-bar" style="width:${pct}%"></div>
                </div>
                <span class="baro-imp-val">${v.toFixed(0)}</span>
            </div>`;
        }).join('');
        return `<div class="baro-importance">${rows}</div>`;
    }

    function _bindDbButtons() {
        const msg = document.getElementById('baro-action-msg');

        document.getElementById('baro-scrape-btn')?.addEventListener('click', async () => {
            if (msg) msg.textContent = '스크래핑 시작...';
            try {
                const r = await fetch('/api/baro/scrape', { method: 'POST' });
                const d = await r.json();
                if (msg) msg.textContent = d.message || '완료';
                setTimeout(() => loadBaroDb(), 3000);
            } catch { if (msg) msg.textContent = '요청 실패'; }
        });

        document.getElementById('baro-sync-btn')?.addEventListener('click', async () => {
            if (msg) msg.textContent = '동기화 중...';
            try {
                const r = await fetch('/api/baro/sync', { method: 'POST' });
                const d = await r.json();
                if (msg) msg.textContent = d.ok
                    ? `동기화 완료 (방문 #${d.visit_num}, ${d.items}개 아이템)`
                    : (d.active === false ? '바로가 현재 방문 중이 아닙니다' : '동기화 실패');
                setTimeout(() => loadBaroDb(), 1500);
            } catch { if (msg) msg.textContent = '요청 실패'; }
        });

        document.getElementById('baro-train-btn')?.addEventListener('click', async () => {
            if (msg) msg.textContent = '학습 요청 중...';
            try {
                const r = await fetch('/api/baro/train?trials=200&workers=4', { method: 'POST' });
                const d = await r.json();
                if (msg) msg.textContent = d.message || (d.ok ? '학습 시작됨' : d.message);
                if (d.ok) _pollTrainStatus();
            } catch { if (msg) msg.textContent = '요청 실패'; }
        });
    }

    function _pollTrainStatus() {
        const msg = document.getElementById('baro-action-msg');
        const interval = setInterval(async () => {
            try {
                const r = await fetch('/api/baro/status');
                const d = await r.json();
                if (!d.train_running) {
                    clearInterval(interval);
                    const res = d.last_train;
                    if (msg) msg.textContent = res?.ok
                        ? `학습 완료! AUC ${(res.best_auc||0).toFixed(3)}`
                        : `학습 실패: ${res?.error || ''}`;
                    loadBaroDb();
                } else {
                    if (msg) msg.textContent = '⏳ 학습 진행 중...';
                }
            } catch { clearInterval(interval); }
        }, 5000);
    }

    // ── 유틸 ───────────────────────────────────────────────────────────────────

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
})();
