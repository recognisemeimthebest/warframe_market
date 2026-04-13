/* ── 워프봇 — app.js (실제 API 연동 + 전체 기능) ── */

const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");
const statusEl = document.getElementById("status");

let ws = null;
let reconnectDelay = 1000;

// ── 한글 번역 사전 ──
const TIER_KO = { Lith: "리스", Meso: "메소", Neo: "네오", Axi: "엑시", Requiem: "레퀴엠", Omnia: "옴니아" };
const MISSION_KO = {
    Capture: "포획", Survival: "생존", Defense: "방어", Exterminate: "섬멸",
    Sabotage: "파괴공작", Rescue: "구출", Spy: "첩보", "Mobile Defense": "이동 방어",
    Interception: "감청", Excavation: "발굴", Disruption: "교란",
    Assassination: "암살", Hijack: "탈취", Defection: "탈주", Volatile: "변동",
    Alchemy: "연금술", Conjunction: "회합",
};
const PLANET_KO = {
    Mercury: "수성", Venus: "금성", Earth: "지구", Mars: "화성", Phobos: "포보스",
    Ceres: "세레스", Jupiter: "목성", Europa: "유로파", Saturn: "토성",
    Uranus: "천왕성", Neptune: "해왕성", Pluto: "명왕성", Sedna: "세드나",
    Eris: "에리스", Void: "보이드", "Kuva Fortress": "쿠바 요새", Lua: "루아",
    Deimos: "데이모스", "Zariman Ten Zero": "자리만",
};
const ENEMY_KO = { Grineer: "그리니어", Corpus: "코퍼스", Infested: "인페스티드", Corrupted: "커럽티드", Narmer: "나르메르" };
const ELEMENT_KO = {
    toxin: "독성", cold: "냉기", electricity: "전기", heat: "열",
    magnetic: "자기", radiation: "방사능", impact: "충격",
};
const ALL_ELEMENTS = ["toxin", "cold", "electricity", "heat", "magnetic", "radiation", "impact"];

function koNode(node) {
    const m = node.match(/^(.+)\s\((.+)\)$/);
    if (!m) return node;
    return m[1] + " (" + (PLANET_KO[m[2]] || m[2]) + ")";
}
function koMission(type) { return MISSION_KO[type] || type; }
function koEnemy(enemy) { return ENEMY_KO[enemy] || enemy; }
function koTier(tier) { return TIER_KO[tier] || tier; }


// ── 리벤 추천 메타 (stat names match API: url_name with underscores replaced by spaces) ──
const RIVEN_META = {
    "Rubico": {
        good: ["critical chance", "critical damage", "multishot", "toxin damage", "electric damage"],
        goodNeg: ["zoom", "punch through", "impact damage", "finisher damage"],
        badNeg: ["critical chance", "critical damage", "multishot", "damage"],
    },
    "Ignis Wraith": {
        good: ["critical chance", "critical damage", "multishot", "status chance"],
        goodNeg: ["zoom", "punch through", "impact damage", "finisher damage"],
        badNeg: ["multishot", "damage", "range"],
    },
    "Gram Prime": {
        good: ["critical chance", "critical damage", "attack speed", "fire rate", "range", "combo duration"],
        goodNeg: ["channeling efficiency", "finisher damage", "impact damage"],
        badNeg: ["attack speed", "fire rate", "critical chance", "range"],
    },
    "Kuva Zarr": {
        good: ["multishot", "critical chance", "critical damage", "electric damage"],
        goodNeg: ["zoom", "punch through", "impact damage"],
        badNeg: ["multishot", "damage", "critical chance"],
    },
    "Kuva Bramma": {
        good: ["multishot", "critical chance", "critical damage"],
        goodNeg: ["zoom", "punch through", "impact damage"],
        badNeg: ["multishot", "damage"],
    },
};

// 범용 좋은 스탯 (메타 미등록 무기용 제너릭 평가, API stat name 형식)
const _GENERIC_GOOD = ["critical chance", "critical damage", "multishot", "base damage", "melee damage", "fire rate", "attack speed", "status chance", "electric damage", "toxin damage", "cold damage", "combo duration"];
const _GENERIC_GOOD_NEG = ["zoom", "punch through", "impact damage", "finisher damage", "ammo maximum", "recoil", "damage vs infested", "damage vs corpus", "damage vs grineer", "status duration"];
const _GENERIC_BAD_NEG = ["critical chance", "critical damage", "multishot", "base damage", "melee damage", "fire rate", "attack speed"];

function gradeRiven(auction) {
    const meta = RIVEN_META[auction.weapon];
    // 메타에 없는 무기는 범용 기준으로 평가
    const good = meta ? meta.good : _GENERIC_GOOD;
    const goodNeg = meta ? meta.goodNeg : _GENERIC_GOOD_NEG;
    const badNeg = meta ? meta.badNeg : _GENERIC_BAD_NEG;

    let score = 0;
    const details = [];
    const positives = auction.stats.filter((s) => s.positive);
    const negatives = auction.stats.filter((s) => !s.positive);

    positives.forEach((s) => {
        if (good.some((g) => s.name.includes(g) || g.includes(s.name))) {
            score += 2;
            details.push({ text: s.name, type: "good" });
        }
    });

    negatives.forEach((s) => {
        if (goodNeg.some((g) => s.name.includes(g))) {
            score += 1;
            details.push({ text: "-" + s.name + " (좋은 마이너스)", type: "good" });
        } else if (badNeg.some((b) => s.name.includes(b))) {
            score -= 2;
            details.push({ text: "-" + s.name + " (치명적)", type: "bad" });
        }
    });

    if (positives.length === 0) score -= 3;

    let grade;
    if (score >= 5) grade = "S";
    else if (score >= 3) grade = "A";
    else if (score >= 1) grade = "B";
    else grade = "C";

    return { grade, score, details };
}


// ── 복합 정렬 시스템 ──
function buildMultiSortRow(options, sorts, onUpdate) {
    const row = document.createElement("div");
    row.className = "auction-filter-row";
    row.innerHTML = '<span class="auction-filter-label">정렬</span>';

    options.forEach((opt) => {
        const existing = sorts.find((s) => s.key === opt.key);
        const order = existing ? sorts.indexOf(existing) + 1 : 0;
        const arrow = existing ? (existing.dir === "asc" ? "\u25B2" : "\u25BC") : "";
        const badge = order > 0 && sorts.length > 1 ? order : "";

        const btn = document.createElement("div");
        btn.className = "auction-sort-btn" + (existing ? " active" : "");
        btn.innerHTML = opt.label +
            (badge ? '<span style="font-size:9px;margin-left:2px;opacity:0.7;">' + badge + '</span>' : '') +
            (arrow ? ' <span class="auction-sort-arrow">' + arrow + '</span>' : '');
        btn.addEventListener("click", () => {
            const newSorts = [...sorts];
            const idx = newSorts.findIndex((s) => s.key === opt.key);
            if (idx >= 0) {
                if (newSorts[idx].dir === "asc") newSorts[idx].dir = "desc";
                else newSorts.splice(idx, 1);
            } else {
                newSorts.push({ key: opt.key, dir: "asc" });
            }
            onUpdate(newSorts);
        });
        row.appendChild(btn);
    });

    if (sorts.length > 0) {
        const clearBtn = document.createElement("div");
        clearBtn.className = "auction-sort-btn";
        clearBtn.style.cssText = "font-size:10px;padding:4px 8px;";
        clearBtn.textContent = "초기화";
        clearBtn.addEventListener("click", () => onUpdate([]));
        row.appendChild(clearBtn);
    }

    return row;
}

function applyMultiSort(items, sorts, getValue) {
    if (!sorts.length) return items;
    return items.sort((a, b) => {
        for (const s of sorts) {
            const va = getValue(a, s.key);
            const vb = getValue(b, s.key);
            const diff = va - vb;
            if (diff !== 0) return s.dir === "asc" ? diff : -diff;
        }
        return 0;
    });
}


// ── WebSocket ──
function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws`);

    ws.onopen = () => {
        statusEl.textContent = "온라인";
        statusEl.className = "status online";
        reconnectDelay = 1000;
    };
    ws.onclose = () => {
        statusEl.textContent = "오프라인";
        statusEl.className = "status offline";
        setTimeout(connect, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, 30000);
    };
    ws.onerror = () => ws.close();

    ws.onmessage = (event) => {
        let data;
        try { data = JSON.parse(event.data); } catch { return; }

        if (data.type === "chat") {
            addMessage(data.text, "bot");
        } else if (data.type === "price") {
            if (data.error) { addMessage(data.text, "bot"); }
            else { addPriceCard(data); }
        } else if (data.type === "suggest") {
            addSuggestCard(data.query, data.items);
        } else if (data.type === "alert") {
            addMessage(data.text, "bot");
            showAlertNotify(data.text);
        }
    };
}

function escapeHtml(str) {
    const el = document.createElement("span");
    el.textContent = str;
    return el.innerHTML;
}

function addMessage(text, sender) {
    const div = document.createElement("div");
    div.className = `message ${sender}`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = escapeHtml(text).replace(/\n/g, "<br>");
    div.appendChild(bubble);
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function formatPrice(min, count) {
    return min != null ? `${min}p (${count}건)` : "등록 없음";
}

function addPriceCard(price) {
    const div = document.createElement("div");
    div.className = "message bot";
    const card = document.createElement("div");
    card.className = "price-card";
    const avg48h = price.avg_48h != null ? `${price.avg_48h.toFixed(1)}p (거래 ${price.volume_48h}건)` : "-";

    let rankHtml = "";
    if (price.rank_prices && price.rank_prices.length > 0) {
        rankHtml += '<div class="rank-divider"></div>';
        for (const rp of price.rank_prices) {
            const label = rp.rank === 0 ? "랭크 0" : `랭크 MAX (${rp.rank})`;
            rankHtml += `
                <div class="rank-label">${label}</div>
                <div class="row"><span class="label">판매 최저가</span><span class="value">${formatPrice(rp.sell_min, rp.sell_count)}</span></div>
                <div class="row"><span class="label">구매 최고가</span><span class="value">${formatPrice(rp.buy_max, rp.buy_count)}</span></div>
            `;
        }
    }

    card.innerHTML = `
        <div class="title"><a href="https://warframe.market/items/${price.slug}" target="_blank">${escapeHtml(price.item_name)}</a></div>
        <div class="row"><span class="label">판매 최저가</span><span class="value">${formatPrice(price.sell_min, price.sell_count)}</span></div>
        <div class="row"><span class="label">구매 최고가</span><span class="value">${formatPrice(price.buy_max, price.buy_count)}</span></div>
        <div class="row"><span class="label">48시간 평균</span><span class="value">${avg48h}</span></div>
        ${rankHtml}
        <div class="footer">warframe.market · 온라인/인게임 유저 기준</div>
    `;
    div.appendChild(card);
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addSuggestCard(query, items) {
    const div = document.createElement("div");
    div.className = "message bot";
    const card = document.createElement("div");
    card.className = "suggest-card";
    const title = document.createElement("div");
    title.className = "suggest-title";
    title.textContent = "이 아이템을 찾으셨나요?";
    card.appendChild(title);

    items.forEach((item) => {
        const a = document.createElement("a");
        a.className = "suggest-item";
        if (item.ko_name) {
            a.textContent = item.ko_name;
            const sub = document.createElement("span");
            sub.className = "suggest-sub";
            sub.textContent = " " + item.name;
            a.appendChild(sub);
        } else {
            a.textContent = item.name;
        }
        a.addEventListener("click", () => {
            addMessage(item.ko_name || item.name, "user");
            ws.send(JSON.stringify({ text: item.name }));
        });
        card.appendChild(a);
    });

    div.appendChild(card);
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    addMessage(text, "user");
    ws.send(JSON.stringify({ text }));
    input.value = "";
});


// ── 탭 전환 ──
const tabs = document.querySelectorAll(".tab");
const chatFooter = document.getElementById("chat-footer");
const tradeFooter = document.getElementById("trade-footer");
const farmingFooter = document.getElementById("farming-footer");
let activeTab = "chat";

tabs.forEach((btn) => {
    btn.addEventListener("click", () => {
        const tab = btn.dataset.tab;
        if (tab === activeTab) return;

        tabs.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById("tab-" + activeTab).classList.remove("active");
        document.getElementById("tab-" + tab).classList.add("active");

        chatFooter.style.display = "none";
        tradeFooter.style.display = "none";
        farmingFooter.style.display = "none";

        if (tab === "chat") chatFooter.style.display = chatMode === "chat" ? "" : "none";
        if (tab === "trade") { renderTradeTab(); if (tradeUser && tradeUser.status === "approved") tradeFooter.style.display = ""; }
        if (tab === "farming") { farmingFooter.style.display = ""; renderFarmingWelcome(); }
        if (tab === "surges") fetchSurges();
        if (tab === "world") fetchWorldState();
        if (tab === "modding") renderModdingTab();

        activeTab = tab;
    });
});


// ── 시세 조회 모드 전환 (채팅 / 시세 감시 / 경매) ──
let chatMode = "chat";
document.querySelectorAll(".chat-mode").forEach((btn) => {
    btn.addEventListener("click", () => {
        const mode = btn.dataset.mode;
        if (mode === chatMode) return;

        document.querySelectorAll(".chat-mode").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");

        document.getElementById("messages").style.display = mode === "chat" ? "" : "none";
        document.getElementById("chat-watchlist").style.display = mode === "watchlist" ? "" : "none";
        document.getElementById("chat-auction").style.display = mode === "auction" ? "" : "none";
        chatFooter.style.display = mode === "chat" ? "" : "none";

        chatMode = mode;
        if (mode === "watchlist") renderWatchlist();
        if (mode === "auction") renderAuctionView();
    });
});


// ── 급등 알림 ──
let currentPeriod = "";

document.querySelectorAll(".surge-filter").forEach((btn) => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".surge-filter").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        currentPeriod = btn.dataset.period;
        fetchSurges();
    });
});

async function fetchSurges() {
    const params = new URLSearchParams({ limit: "30" });
    if (currentPeriod) params.set("period", currentPeriod);
    try {
        const res = await fetch(`/api/surges?${params}`);
        const json = await res.json();
        renderSurgeList(json.data || []);
    } catch {
        document.getElementById("surge-list").innerHTML = '<div class="surge-empty">데이터를 불러오지 못했습니다.</div>';
    }
}

function renderSurgeList(items) {
    const el = document.getElementById("surge-list");
    if (!items.length) {
        el.innerHTML = '<div class="surge-empty">감지된 급등 아이템이 없습니다.<br><small style="color:var(--text-muted)">급등 알림은 가격 데이터가 24시간 이상 쌓인 후부터 감지됩니다.</small></div>';
        return;
    }
    el.innerHTML = "";
    items.forEach((s) => {
        const card = document.createElement("div");
        card.className = "surge-card";
        const name = s.ko_name || s.en_name || s.slug;
        const sub = s.ko_name ? s.en_name : "";
        const rankTag = s.rank != null ? (s.rank === 0 ? " (랭크0)" : ` (랭크${s.rank})`) : "";
        const periodLabel = { "1d": "1일", "7d": "1주", "30d": "1달" }[s.period] || s.period;

        card.innerHTML = `
            <div class="surge-info">
                <div class="surge-name">
                    <span class="surge-period p-${escapeHtml(s.period)}">${escapeHtml(periodLabel)}</span>
                    ${escapeHtml(name + rankTag)}
                    ${sub ? `<span class="surge-name-sub">${escapeHtml(sub)}</span>` : ""}
                </div>
                <div class="surge-detail">${s.old_price.toFixed(0)}p → ${s.new_price.toFixed(0)}p</div>
            </div>
            <div class="surge-pct">+${s.change_pct.toFixed(1)}%</div>
        `;
        card.addEventListener("click", () => {
            tabs.forEach((b) => b.classList.remove("active"));
            document.querySelector('[data-tab="chat"]').classList.add("active");
            document.getElementById("tab-" + activeTab).classList.remove("active");
            document.getElementById("tab-chat").classList.add("active");
            chatFooter.style.display = "";
            activeTab = "chat";
            const q = s.ko_name || s.en_name || s.slug;
            addMessage(q, "user");
            ws.send(JSON.stringify({ text: s.en_name || s.slug }));
        });
        el.appendChild(card);
    });
}


// ── 거래소 ──
let tradeUser = null;
let tradeFilterType = "";

async function renderTradeTab() {
    const name = localStorage.getItem("tradeName") || "";
    if (name) {
        const res = await fetch(`/api/trade/user?name=${encodeURIComponent(name)}`);
        const json = await res.json();
        tradeUser = json.user;
    }

    document.getElementById("trade-register").style.display = "none";
    document.getElementById("trade-pending").style.display = "none";
    document.getElementById("trade-approved").style.display = "none";

    if (!tradeUser) {
        document.getElementById("trade-register").style.display = "";
    } else if (tradeUser.status === "pending") {
        document.getElementById("trade-pending").style.display = "";
    } else if (tradeUser.status === "approved") {
        document.getElementById("trade-approved").style.display = "";
        tradeFooter.style.display = "";
        fetchListings();
    }
}

async function tradeRegister() {
    const name = document.getElementById("trade-name-input").value.trim();
    if (!name) return;
    const res = await fetch("/api/trade/register", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
    });
    const json = await res.json();
    if (json.ok) {
        localStorage.setItem("tradeName", name);
        tradeUser = json.user;
    } else {
        alert(json.msg);
    }
    renderTradeTab();
}

async function fetchListings() {
    const params = new URLSearchParams({ limit: "50" });
    if (tradeFilterType) params.set("trade_type", tradeFilterType);
    const res = await fetch(`/api/trade/listings?${params}`);
    const json = await res.json();
    renderListings(json.data || []);
}

document.querySelectorAll(".trade-filter").forEach((btn) => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".trade-filter").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        tradeFilterType = btn.dataset.type;
        fetchListings();
    });
});

function renderListings(items) {
    const el = document.getElementById("trade-list");
    if (!items.length) {
        el.innerHTML = '<div class="surge-empty">매물이 없습니다.</div>';
        return;
    }
    el.innerHTML = "";
    items.forEach((l) => {
        const card = document.createElement("div");
        card.className = "trade-card";
        const myName = localStorage.getItem("tradeName") || "";
        const delBtn = l.user_name === myName
            ? `<button class="trade-delete" onclick="deleteListing(${l.id})">삭제</button>` : "";
        const rankStr = l.rank != null ? (l.rank === 0 ? '<span class="trade-rank">랭크0</span>' : '<span class="trade-rank">랭크' + l.rank + '</span>') : '';
        const qtyStr = l.quantity > 1 ? '<span class="trade-qty"> x' + l.quantity + '</span>' : '';
        const marketRef = l.market_min ? '<span class="trade-market-ref">마켓 최저가 ' + l.market_min + 'p</span>' : '';

        card.innerHTML = `
            <div class="trade-card-header">
                <div><span class="trade-type ${l.trade_type}">${l.trade_type === "buy" ? "삽니다" : "팝니다"}</span></div>
                <div style="display:flex;align-items:center;gap:6px;">
                    <span class="trade-user">${escapeHtml(l.user_name)}</span>
                    ${delBtn}
                </div>
            </div>
            <div class="trade-item">${escapeHtml(l.item_name)}${rankStr}${qtyStr}</div>
            <div class="trade-price-row">
                <span class="trade-price">${l.price}p</span>
                ${marketRef}
            </div>
            ${l.memo ? `<div class="trade-memo">${escapeHtml(l.memo)}</div>` : ""}
        `;
        el.appendChild(card);
    });
}

async function deleteListing(id) {
    const name = localStorage.getItem("tradeName") || "";
    await fetch(`/api/trade/listings/${id}?user_name=${encodeURIComponent(name)}`, { method: "DELETE" });
    fetchListings();
}

function toggleTradeForm() {
    const form = document.getElementById("trade-new-form");
    form.style.display = form.style.display === "none" ? "" : "none";
}

async function submitListing() {
    const res = await fetch("/api/trade/listings", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            user_name: localStorage.getItem("tradeName") || "",
            trade_type: document.getElementById("tf-type").value,
            item_slug: document.getElementById("tf-item").value.toLowerCase().replace(/ /g, "_"),
            item_name: document.getElementById("tf-item").value,
            price: parseInt(document.getElementById("tf-price").value) || 0,
            quantity: parseInt(document.getElementById("tf-qty").value) || 1,
            memo: document.getElementById("tf-memo").value,
        }),
    });
    const json = await res.json();
    if (!json.ok) { alert(json.msg); return; }
    toggleTradeForm();
    fetchListings();
}


// ── 월드 상태 ──
let worldSection = "fissures";
let fissureMode = "normal";
let _cachedFissures = [];

document.querySelectorAll(".world-filter").forEach((btn) => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".world-filter").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        worldSection = btn.dataset.section;
        if (worldSection === "alerts") {
            renderAlertSetup();
        } else {
            fissureMode = "normal";
            fetchWorldState();
        }
    });
});

async function fetchWorldState() {
    const el = document.getElementById("world-list");
    el.innerHTML = '<div class="surge-empty">로딩 중...</div>';

    try {
        if (worldSection === "fissures") {
            const res = await fetch("/api/world/fissures");
            const json = await res.json();
            _cachedFissures = json.data || [];
            renderFissures(_cachedFissures);
        } else if (worldSection === "arbitration") {
            const res = await fetch("/api/world/arbitration");
            const json = await res.json();
            renderArbitration(json.data);
        } else if (worldSection === "invasions") {
            const res = await fetch("/api/world/invasions");
            const json = await res.json();
            renderInvasions(json.data || []);
        } else if (worldSection === "cycles") {
            const res = await fetch("/api/world/cycles");
            const json = await res.json();
            renderCycles(json.data || {});
        }
    } catch {
        el.innerHTML = '<div class="surge-empty">데이터를 불러오지 못했습니다.</div>';
    }
}

function renderFissures(items) {
    const el = document.getElementById("world-list");
    el.innerHTML = "";

    // 일반/강철 토글
    const toggle = document.createElement("div");
    toggle.style.cssText = "display:flex;gap:8px;margin-bottom:10px;";
    ["normal", "hard"].forEach((mode) => {
        const btn = document.createElement("button");
        btn.className = "surge-filter" + (fissureMode === mode ? " active" : "");
        btn.textContent = mode === "normal" ? "일반" : "강철의 길";
        btn.addEventListener("click", () => {
            fissureMode = mode;
            renderFissures(_cachedFissures);
        });
        toggle.appendChild(btn);
    });
    el.appendChild(toggle);

    const filtered = items.filter((f) => fissureMode === "hard" ? f.isHard : !f.isHard);

    if (!filtered.length) {
        el.innerHTML += '<div class="surge-empty">현재 ' + (fissureMode === "hard" ? "강철의 길" : "일반") + ' 균열이 없습니다.</div>';
        return;
    }

    filtered.forEach((f) => {
        const card = document.createElement("div");
        card.className = "world-card";
        const tierCls = (f.tier || "").toLowerCase();
        if (f.isHard) card.style.borderColor = "rgba(255,107,107,0.4)";

        card.innerHTML = `
            <div class="world-card-header">
                <div class="world-card-title">
                    <span class="world-tag ${tierCls}">${escapeHtml(koTier(f.tier))}</span>
                    ${escapeHtml(koMission(f.missionType))}
                </div>
                <div class="world-card-timer">${escapeHtml(f.eta)}</div>
            </div>
            <div class="world-card-detail">
                ${escapeHtml(koNode(f.node))} ·
                <span class="world-tag enemy">${escapeHtml(koEnemy(f.enemy))}</span>
            </div>
        `;
        el.appendChild(card);
    });
}

function renderArbitration(arb) {
    const el = document.getElementById("world-list");
    if (!arb) { el.innerHTML = '<div class="surge-empty">현재 중재 정보가 없습니다.</div>'; return; }

    el.innerHTML = "";
    const card = document.createElement("div");
    card.className = "world-card";
    card.style.borderColor = "var(--orange)";
    card.innerHTML = `
        <div class="world-card-header">
            <div class="world-card-title">현재 중재 미션</div>
            <div class="world-card-timer">${escapeHtml(arb.eta)}</div>
        </div>
        <div style="font-size:15px;font-weight:600;color:var(--text);margin:8px 0;">${escapeHtml(koMission(arb.missionType))}</div>
        <div class="world-card-detail">
            ${escapeHtml(koNode(arb.node))} ·
            <span class="world-tag enemy">${escapeHtml(koEnemy(arb.enemy))}</span>
        </div>
    `;
    el.appendChild(card);

    const hint = document.createElement("div");
    hint.className = "surge-empty";
    hint.textContent = "중재 미션은 1시간마다 교체됩니다.";
    el.appendChild(hint);
}

function renderInvasions(items) {
    const el = document.getElementById("world-list");
    if (!items.length) { el.innerHTML = '<div class="surge-empty">활성 침공이 없습니다.</div>'; return; }
    el.innerHTML = "";
    items.forEach((inv) => {
        const card = document.createElement("div");
        card.className = "world-card";
        const atkReward = inv.attackerReward.items.map((i) => escapeHtml(i.name)).join(", ") || "크레딧";
        const defReward = inv.defenderReward.items.map((i) => escapeHtml(i.name)).join(", ") || "크레딧";
        const fillCls = inv.attackingFaction.toLowerCase();
        card.innerHTML = `
            <div class="world-card-header">
                <div class="world-card-title">${escapeHtml(koNode(inv.node))}</div>
                <div class="world-card-timer">${inv.completion}%</div>
            </div>
            <div class="world-card-detail">${escapeHtml(inv.desc)}</div>
            <div class="invasion-rewards">
                <span class="atk">${escapeHtml(koEnemy(inv.attackingFaction))}: ${atkReward}</span>
                <span class="def">${escapeHtml(koEnemy(inv.defendingFaction))}: ${defReward}</span>
            </div>
            <div class="invasion-bar"><div class="invasion-bar-fill ${fillCls}" style="width:${Math.max(0, Math.min(100, inv.completion))}%"></div></div>
        `;
        el.appendChild(card);
    });
}

function renderCycles(data) {
    const el = document.getElementById("world-list");
    el.innerHTML = "";
    const stateMap = {
        day: "낮", night: "밤", warm: "따뜻함", cold: "추위",
        fass: "파스", vome: "봄", corpus: "코퍼스", grineer: "그리니어",
    };
    const stateClass = {
        day: "day", night: "night", warm: "warm", cold: "cold",
        fass: "warm", vome: "cold", corpus: "cold", grineer: "warm",
    };
    const regionNames = { cetus: "세투스", vallis: "오브 밸리스", cambion: "캠비온 퇴적지", zariman: "자리만" };

    for (const [region, info] of Object.entries(data)) {
        if (!info) continue;
        const row = document.createElement("div");
        row.className = "cycle-row";
        const state = info.state || "";
        row.innerHTML = `
            <div class="cycle-name">${regionNames[region] || region}</div>
            <span class="cycle-state ${stateClass[state] || ""}">${stateMap[state] || state}</span>
            <span class="cycle-timer">${escapeHtml(info.timeLeft || info.shortString || "")}</span>
        `;
        el.appendChild(row);
    }
    if (!el.children.length) {
        el.innerHTML = '<div class="surge-empty">사이클 정보를 불러올 수 없습니다.</div>';
    }
}


// ── 알림 설정 시스템 ──
let alertCategory = "fissures";

let alertTiers = JSON.parse(localStorage.getItem("alertTiers") || "[]");
let alertMissions = JSON.parse(localStorage.getItem("alertMissions") || "[]");
let alertHard = JSON.parse(localStorage.getItem("alertHard") || "false");

let alertArbEnemies = JSON.parse(localStorage.getItem("alertArbEnemies") || "[]");
let alertArbMissions = JSON.parse(localStorage.getItem("alertArbMissions") || "[]");

let alertInvRewards = JSON.parse(localStorage.getItem("alertInvRewards") || "[]");

let alertCycleConfigs = JSON.parse(localStorage.getItem("alertCycleConfigs") || "[]");

const ALL_TIERS = [
    { key: "Lith", label: "리스", cls: "lith" },
    { key: "Meso", label: "메소", cls: "meso" },
    { key: "Neo", label: "네오", cls: "neo" },
    { key: "Axi", label: "엑시", cls: "axi" },
    { key: "Requiem", label: "레퀴엠", cls: "requiem" },
];
const ALL_MISSIONS = [
    "Capture", "Survival", "Exterminate", "Defense", "Sabotage",
    "Rescue", "Spy", "Mobile Defense", "Interception", "Excavation", "Disruption",
];
const ALL_ENEMIES = [
    { key: "Grineer", label: "그리니어" },
    { key: "Corpus", label: "코퍼스" },
    { key: "Infested", label: "인페스티드" },
    { key: "Corrupted", label: "커럽티드" },
];
const ALL_INV_REWARDS = [
    { key: "reactor", label: "오로킨 리액터", match: "Orokin Reactor|Reactor" },
    { key: "catalyst", label: "오로킨 카탈리스트", match: "Orokin Catalyst|Catalyst" },
    { key: "forma", label: "포르마", match: "Forma" },
    { key: "weapon_part", label: "무기 부품", match: "Wraith|Vandal|Miter|Twin Vipers|Strun|Karak|Dera|Snipetron|Gorgon|Latron|Boar" },
];
const CYCLE_REGIONS = [
    { key: "cetus", name: "세투스", phases: [
        { key: "day", label: "낮" }, { key: "night", label: "밤" },
    ]},
    { key: "vallis", name: "오브 밸리스", phases: [
        { key: "warm", label: "따뜻함" }, { key: "cold", label: "추위" },
    ]},
    { key: "cambion", name: "캠비온 퇴적지", phases: [
        { key: "fass", label: "파스" }, { key: "vome", label: "봄" },
    ]},
];

const ALERT_CATEGORIES = [
    { key: "fissures", label: "균열" },
    { key: "arbitration", label: "중재" },
    { key: "invasions", label: "침공" },
    { key: "cycles", label: "오픈월드" },
];

function toggleArr(arr, val) {
    const idx = arr.indexOf(val);
    if (idx >= 0) arr.splice(idx, 1); else arr.push(val);
}

function makeChipSection(label, chips) {
    const section = document.createElement("div");
    section.className = "alert-section";
    section.innerHTML = '<div class="alert-section-label">' + escapeHtml(label) + '</div>';
    const row = document.createElement("div");
    row.className = "alert-chips";
    chips.forEach((c) => {
        const chip = document.createElement("div");
        chip.className = "alert-chip" + (c.selected ? " selected" + (c.cls ? " " + c.cls : "") : "");
        chip.textContent = c.label;
        chip.addEventListener("click", c.onClick);
        row.appendChild(chip);
    });
    section.appendChild(row);
    return section;
}

function makeSaveBtn(onSave) {
    const btn = document.createElement("button");
    btn.className = "alert-save-btn";
    btn.textContent = "저장";
    btn.addEventListener("click", onSave);
    return btn;
}

function makeSummary(title, lines) {
    const el = document.createElement("div");
    el.className = "alert-current";
    el.innerHTML = '<div class="alert-current-title">' + escapeHtml(title) + '</div>';
    lines.forEach((line) => {
        el.innerHTML += '<div class="alert-current-item">' + escapeHtml(line) + '</div>';
    });
    return el;
}

function renderAlertSetup() {
    const list = document.getElementById("world-list");
    list.innerHTML = "";

    const wrap = document.createElement("div");
    wrap.className = "alert-setup";
    wrap.innerHTML = '<h3>알림 설정</h3>';

    const tabRow = document.createElement("div");
    tabRow.className = "alert-category-tabs";
    ALERT_CATEGORIES.forEach((cat) => {
        const btn = document.createElement("div");
        btn.className = "alert-category-tab" + (alertCategory === cat.key ? " active" : "");
        btn.textContent = cat.label;
        btn.addEventListener("click", () => { alertCategory = cat.key; renderAlertSetup(); });
        tabRow.appendChild(btn);
    });
    wrap.appendChild(tabRow);

    if (alertCategory === "fissures") renderFissureAlert(wrap);
    else if (alertCategory === "arbitration") renderArbAlert(wrap);
    else if (alertCategory === "invasions") renderInvAlert(wrap);
    else if (alertCategory === "cycles") renderCycleAlert(wrap);

    list.appendChild(wrap);
}

function renderFissureAlert(wrap) {
    wrap.appendChild(makeChipSection("티어 (복수 선택)", ALL_TIERS.map((t) => ({
        label: t.label, selected: alertTiers.includes(t.key), cls: t.cls,
        onClick: () => { toggleArr(alertTiers, t.key); renderAlertSetup(); },
    }))));

    wrap.appendChild(makeChipSection("미션 타입 (복수 선택)", ALL_MISSIONS.map((m) => ({
        label: koMission(m), selected: alertMissions.includes(m),
        onClick: () => { toggleArr(alertMissions, m); renderAlertSetup(); },
    }))));

    wrap.appendChild(makeChipSection("난이도", [false, true].map((h) => ({
        label: h ? "강철의 길" : "일반", selected: alertHard === h,
        onClick: () => { alertHard = h; renderAlertSetup(); },
    }))));

    wrap.appendChild(makeSaveBtn(() => {
        localStorage.setItem("alertTiers", JSON.stringify(alertTiers));
        localStorage.setItem("alertMissions", JSON.stringify(alertMissions));
        localStorage.setItem("alertHard", JSON.stringify(alertHard));
        showAlertNotify("균열 알림 설정 저장!");
        checkFissureAlerts();
    }));

    if (alertTiers.length || alertMissions.length) {
        const hardText = alertHard ? "강철의 길" : "일반";
        const tierText = alertTiers.map((t) => koTier(t)).join(", ") || "전체";
        const missionText = alertMissions.map((m) => koMission(m)).join(", ") || "전체";
        wrap.appendChild(makeSummary("균열 알림 조건", [hardText + " · " + tierText + " · " + missionText]));
    }
}

function renderArbAlert(wrap) {
    wrap.appendChild(makeChipSection("적 종류 (복수 선택)", ALL_ENEMIES.map((e) => ({
        label: e.label, selected: alertArbEnemies.includes(e.key),
        onClick: () => { toggleArr(alertArbEnemies, e.key); renderAlertSetup(); },
    }))));

    wrap.appendChild(makeChipSection("미션 타입 (복수 선택)", ALL_MISSIONS.map((m) => ({
        label: koMission(m), selected: alertArbMissions.includes(m),
        onClick: () => { toggleArr(alertArbMissions, m); renderAlertSetup(); },
    }))));

    wrap.appendChild(makeSaveBtn(() => {
        localStorage.setItem("alertArbEnemies", JSON.stringify(alertArbEnemies));
        localStorage.setItem("alertArbMissions", JSON.stringify(alertArbMissions));
        showAlertNotify("중재 알림 설정 저장!");
        checkArbAlerts();
    }));

    if (alertArbEnemies.length || alertArbMissions.length) {
        const enemyText = alertArbEnemies.map((e) => koEnemy(e)).join(", ") || "전체";
        const missionText = alertArbMissions.map((m) => koMission(m)).join(", ") || "전체";
        wrap.appendChild(makeSummary("중재 알림 조건", [enemyText + " · " + missionText]));
    }
}

function renderInvAlert(wrap) {
    wrap.appendChild(makeChipSection("알림 받을 보상 (복수 선택)", ALL_INV_REWARDS.map((r) => ({
        label: r.label, selected: alertInvRewards.includes(r.key), cls: "orange",
        onClick: () => { toggleArr(alertInvRewards, r.key); renderAlertSetup(); },
    }))));

    wrap.appendChild(makeSaveBtn(() => {
        localStorage.setItem("alertInvRewards", JSON.stringify(alertInvRewards));
        showAlertNotify("침공 알림 설정 저장!");
        checkInvAlerts();
    }));

    if (alertInvRewards.length) {
        const labels = alertInvRewards.map((k) => ALL_INV_REWARDS.find((r) => r.key === k)?.label || k);
        wrap.appendChild(makeSummary("침공 알림 조건", [labels.join(", ")]));
    }
}

function renderCycleAlert(wrap) {
    const desc = document.createElement("div");
    desc.className = "alert-section-label";
    desc.textContent = "원하는 지역 + 시간대를 설정하면 해당 시간대가 시작될 때 알림을 보내드립니다.";
    desc.style.marginBottom = "12px";
    wrap.appendChild(desc);

    alertCycleConfigs.forEach((cfg, idx) => {
        const region = CYCLE_REGIONS.find((r) => r.key === cfg.region);
        if (!region) return;

        const card = document.createElement("div");
        card.className = "cycle-config";

        const header = document.createElement("div");
        header.className = "cycle-config-header";
        header.innerHTML = '<span class="cycle-config-name">' + escapeHtml(region.name) + '</span>';
        const removeBtn = document.createElement("span");
        removeBtn.className = "cycle-config-remove";
        removeBtn.textContent = "삭제";
        removeBtn.addEventListener("click", () => { alertCycleConfigs.splice(idx, 1); renderAlertSetup(); });
        header.appendChild(removeBtn);
        card.appendChild(header);

        const nameSpan = header.querySelector(".cycle-config-name");
        nameSpan.style.cursor = "pointer";
        nameSpan.title = "클릭하여 지역 변경";
        nameSpan.addEventListener("click", () => {
            const currentIdx = CYCLE_REGIONS.findIndex((r) => r.key === alertCycleConfigs[idx].region);
            const nextIdx = (currentIdx + 1) % CYCLE_REGIONS.length;
            alertCycleConfigs[idx].region = CYCLE_REGIONS[nextIdx].key;
            alertCycleConfigs[idx].phases = [];
            renderAlertSetup();
        });

        const phaseChips = document.createElement("div");
        phaseChips.className = "alert-chips";
        region.phases.forEach((p) => {
            const chip = document.createElement("div");
            chip.className = "alert-chip" + (cfg.phases.includes(p.key) ? " selected" : "");
            chip.textContent = p.label;
            chip.addEventListener("click", () => { toggleArr(cfg.phases, p.key); renderAlertSetup(); });
            phaseChips.appendChild(chip);
        });
        card.appendChild(phaseChips);

        const repeatRow = document.createElement("div");
        repeatRow.className = "cycle-repeat-row";
        repeatRow.innerHTML = '<label>반복 횟수</label>';
        const numInput = document.createElement("input");
        numInput.type = "number";
        numInput.min = "0";
        numInput.max = "99";
        numInput.value = cfg.repeat != null ? cfg.repeat : 1;
        numInput.addEventListener("change", () => {
            cfg.repeat = Math.max(0, Math.min(99, parseInt(numInput.value) || 0));
        });
        repeatRow.appendChild(numInput);
        const repeatHint = document.createElement("span");
        repeatHint.style.cssText = "font-size:11px;color:var(--text-muted);";
        repeatHint.textContent = "회 (0 = 무제한)";
        repeatRow.appendChild(repeatHint);
        card.appendChild(repeatRow);

        wrap.appendChild(card);
    });

    const addBtn = document.createElement("div");
    addBtn.className = "cycle-add-btn";
    addBtn.textContent = "+ 지역 추가";
    addBtn.addEventListener("click", () => {
        const usedKeys = alertCycleConfigs.map((c) => c.region);
        const available = CYCLE_REGIONS.find((r) => !usedKeys.includes(r.key)) || CYCLE_REGIONS[0];
        alertCycleConfigs.push({ region: available.key, phases: [], repeat: 1 });
        renderAlertSetup();
    });
    wrap.appendChild(addBtn);

    wrap.appendChild(makeSaveBtn(() => {
        localStorage.setItem("alertCycleConfigs", JSON.stringify(alertCycleConfigs));
        showAlertNotify("오픈월드 알림 설정 저장!");
        checkCycleAlerts();
    }));

    if (alertCycleConfigs.length) {
        const lines = alertCycleConfigs.filter((c) => c.phases.length > 0).map((cfg) => {
            const region = CYCLE_REGIONS.find((r) => r.key === cfg.region);
            const phaseLabels = cfg.phases.map((pk) => region.phases.find((p) => p.key === pk)?.label || pk).join(", ");
            return region.name + ": " + phaseLabels + " (" + (cfg.repeat || "무제한") + "회)";
        });
        if (lines.length) wrap.appendChild(makeSummary("오픈월드 알림 조건", lines));
    }
}

// ── 알림 체크 (실제 API 데이터 기반) ──
async function checkFissureAlerts() {
    if (!alertTiers.length && !alertMissions.length) return;
    try {
        const res = await fetch("/api/world/fissures");
        const json = await res.json();
        const fissures = json.data || [];
        const matches = fissures.filter((f) => {
            if (f.isHard !== alertHard) return false;
            if (alertTiers.length && !alertTiers.includes(f.tier)) return false;
            if (alertMissions.length && !alertMissions.includes(f.missionType)) return false;
            return true;
        });
        if (matches.length > 0) {
            const f = matches[0];
            showAlertNotify("균열: " + koTier(f.tier) + " " + koMission(f.missionType) + " — " + koNode(f.node) + " (" + f.eta + ")");
        }
    } catch {}
}

async function checkArbAlerts() {
    if (!alertArbEnemies.length && !alertArbMissions.length) return;
    try {
        const res = await fetch("/api/world/arbitration");
        const json = await res.json();
        const a = json.data;
        if (!a) return;
        if (alertArbEnemies.length && !alertArbEnemies.includes(a.enemy)) return;
        if (alertArbMissions.length && !alertArbMissions.includes(a.missionType)) return;
        showAlertNotify("중재: " + koMission(a.missionType) + " — " + koNode(a.node) + " [" + koEnemy(a.enemy) + "] (" + a.eta + ")");
    } catch {}
}

async function checkInvAlerts() {
    if (!alertInvRewards.length) return;
    try {
        const res = await fetch("/api/world/invasions");
        const json = await res.json();
        const invasions = json.data || [];
        for (const inv of invasions) {
            const allRewards = (inv.attackerReward?.items || []).map((i) => i.name).join(" ") + " " +
                               (inv.defenderReward?.items || []).map((i) => i.name).join(" ");
            for (const rk of alertInvRewards) {
                const def = ALL_INV_REWARDS.find((r) => r.key === rk);
                if (def && new RegExp(def.match, "i").test(allRewards)) {
                    showAlertNotify("침공: " + koNode(inv.node) + " — " + def.label + " 보상 등장!");
                    return;
                }
            }
        }
    } catch {}
}

async function checkCycleAlerts() {
    if (!alertCycleConfigs.some((c) => c.phases.length > 0)) return;
    try {
        const res = await fetch("/api/world/cycles");
        const json = await res.json();
        const cycles = json.data || {};
        for (const cfg of alertCycleConfigs) {
            if (!cfg.phases.length) continue;
            const info = cycles[cfg.region];
            if (info && cfg.phases.includes(info.state)) {
                const region = CYCLE_REGIONS.find((r) => r.key === cfg.region);
                const stateMap = { day: "낮", night: "밤", warm: "따뜻함", cold: "추위", fass: "파스", vome: "봄" };
                showAlertNotify("오픈월드: " + region.name + " — 현재 " + (stateMap[info.state] || info.state) + "!");
                return;
            }
        }
    } catch {}
}


// ── 파밍 정보 ──
function renderFarmingWelcome() {
    const container = document.getElementById("farming-results");
    container.innerHTML = "";
    const welcome = document.createElement("div");
    welcome.className = "farming-welcome";
    welcome.innerHTML =
        '아이템, 모드, 워프레임 이름을 검색하면<br>파밍 위치와 드롭 정보를 알려드릴게요!' +
        '<div class="farming-suggest"></div>';
    const _suggestionPool = [
        "라이노 프라임", "메사 프라임", "볼트 프라임", "새린 프라임", "가라 프라임",
        "나타 프라임", "바우반 프라임", "이나로스 프라임", "크로마 프라임", "에퀴녹스 프라임",
        "컨디션 오버로드", "어댑테이션", "바이탈리티", "버서커 퓨리", "블러드 러쉬",
        "치명적 가속", "점화 에이전트", "휠윈드",
        "이그니스 레이스", "쿠바 뉴코어", "루비코 프라임", "소마 프라임",
        "헤이트", "드레드", "아크리드", "스트로파 프라임", "그람 프라임",
        "아케인 어벤저", "아케인 에너자이즈", "아케인 그레이스", "아케인 가디언",
        "플레이그 크리파스", "플레이그 키워", "셉판",
    ];
    const suggestions = _suggestionPool.sort(() => Math.random() - 0.5).slice(0, 5);
    const chipContainer = welcome.querySelector(".farming-suggest");
    suggestions.forEach((s) => {
        const chip = document.createElement("div");
        chip.className = "farming-suggest-chip";
        chip.textContent = s;
        chip.addEventListener("click", () => {
            document.getElementById("farming-input").value = s;
            doFarmingSearch(s);
        });
        chipContainer.appendChild(chip);
    });
    container.appendChild(welcome);
}

async function doFarmingSearch(query) {
    const resultsEl = document.getElementById("farming-results");
    resultsEl.innerHTML = '<div class="surge-empty">검색 중...</div>';

    try {
        const res = await fetch(`/api/farming?q=${encodeURIComponent(query)}&limit=5`);
        const json = await res.json();
        renderFarmingResults(json.data || [], query);
    } catch {
        resultsEl.innerHTML = '<div class="surge-empty">검색에 실패했습니다.</div>';
    }
}

document.getElementById("farming-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = document.getElementById("farming-input").value.trim();
    if (!q) return;
    doFarmingSearch(q);
});

function renderFarmingResults(items, query) {
    const el = document.getElementById("farming-results");
    if (!items.length) {
        el.innerHTML = `<div class="surge-empty">"${escapeHtml(query)}"에 대한 파밍 정보를 찾지 못했습니다.</div>`;
        return;
    }

    if (items[0].score === 1) {
        el.innerHTML = "";
        el.appendChild(buildFarmingCard(items[0]));
        return;
    }

    el.innerHTML = "";
    const suggest = document.createElement("div");
    suggest.className = "farming-candidates";
    const card = document.createElement("div");
    card.className = "suggest-card";
    const title = document.createElement("div");
    title.className = "suggest-title";
    title.textContent = "이 아이템을 찾으셨나요?";
    card.appendChild(title);

    items.forEach((item) => {
        const a = document.createElement("a");
        a.className = "suggest-item";
        a.textContent = item.name;
        a.addEventListener("click", () => {
            document.getElementById("farming-input").value = item.name;
            el.innerHTML = "";
            el.appendChild(buildFarmingCard(item));
        });
        card.appendChild(a);
    });

    suggest.appendChild(card);
    el.appendChild(suggest);
}

function buildFarmingCard(item) {
    const card = document.createElement("div");
    card.className = "farming-card";

    const typeLabels = { prime: "프라임", mod: "모드", frame: "워프레임", weapon: "무기", other: "" };
    const typeCls = item.type || "other";

    let dropsHtml = "";
    if (item.drops && item.drops.length) {
        dropsHtml = item.drops.map((d) => `
            <div class="farming-drop">
                <div class="farming-drop-source">
                    ${escapeHtml(d.source)}
                    ${d.rarity ? `<span class="farming-relic-rarity ${d.rarity.toLowerCase()}">${escapeHtml(d.rarity)}</span>` : ""}
                </div>
                <div class="farming-drop-rate">${escapeHtml(d.rate)}</div>
            </div>
        `).join("");
    } else {
        dropsHtml = '<div class="surge-empty">드롭 정보가 없습니다.</div>';
    }

    const wikiHref = item.wiki_url
        || "https://warframe.fandom.com/wiki/" + encodeURIComponent(item.name.replace(/ /g, "_"));

    card.innerHTML = `
        <div class="farming-card-title">
            ${typeCls !== "other" ? `<span class="farming-card-type ${typeCls}">${typeLabels[typeCls]}</span>` : ""}
            ${escapeHtml(item.name)}
        </div>
        ${item.description ? `<div class="farming-card-desc">${escapeHtml(item.description)}</div>` : ""}
        <div class="farming-card-sub">${item.drops ? item.drops.length + "개 드롭 소스" : ""}</div>
        ${dropsHtml}
    `;

    const wiki = document.createElement("div");
    wiki.style.cssText = "margin-top:8px;font-size:11px;color:var(--text-muted);text-align:right;";
    wiki.innerHTML = '출처: <a href="' + escapeHtml(wikiHref) + '" target="_blank" style="color:var(--primary);">Warframe Wiki</a>';
    card.appendChild(wiki);

    return card;
}


// ── 워치리스트 (시세 감시) ──
async function renderWatchlist() {
    const el = document.getElementById("chat-watchlist");
    const name = localStorage.getItem("tradeName") || "";

    let items = [];
    if (name) {
        try {
            const res = await fetch(`/api/watchlist?user_name=${encodeURIComponent(name)}`);
            const json = await res.json();
            items = json.data || [];
        } catch {}
    }

    el.innerHTML = "";

    // 설명
    const hint = document.createElement("div");
    hint.className = "watchlist-hint";
    hint.textContent = "warframe.market에서 지정 가격 이하 매물이 올라오면 알림을 보내드립니다.";
    el.appendChild(hint);

    // 추가 폼
    const addForm = document.createElement("div");
    addForm.className = "watchlist-add-form";
    addForm.innerHTML = `
        <div class="form-row"><label>아이템</label><input type="text" id="wl-item" placeholder="아이템 이름 검색..." autocomplete="off"></div>
        <div class="form-row"><label>목표가</label><input type="number" id="wl-price" placeholder="이 가격 이하면 알림" min="1"><span style="color:var(--text-muted);font-size:13px;margin-left:4px;">p</span></div>
        <div style="display:flex;gap:8px;justify-content:flex-end;">
            <button class="btn-submit" onclick="addWatchItem()" style="padding:6px 14px;border:none;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;background:var(--orange);color:#000;">추가</button>
        </div>
    `;
    el.appendChild(addForm);

    if (!name) {
        const noUser = document.createElement("div");
        noUser.className = "watchlist-hint";
        noUser.textContent = "거래소에서 먼저 닉네임을 등록해주세요.";
        el.appendChild(noUser);
    }

    if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "watchlist-empty";
        empty.textContent = "감시 중인 아이템이 없습니다.";
        el.appendChild(empty);
        return;
    }

    items.forEach((w) => {
        const card = document.createElement("div");
        card.className = "watchlist-card";
        const isHit = w.status === "triggered";
        card.innerHTML = `
            <div class="watchlist-info">
                <div class="watchlist-item">${escapeHtml(w.item_name)}</div>
                <div class="watchlist-price-row">
                    <span class="watchlist-target">목표 ${w.target_price}p</span>
                    <span class="watchlist-market">현재 ${w.current_price != null ? w.current_price + "p" : "-"}</span>
                </div>
            </div>
            <div class="watchlist-actions">
                <span class="watchlist-status ${isHit ? "hit" : "waiting"}">${isHit ? "도달!" : "대기"}</span>
                <button class="watchlist-delete" onclick="removeWatchItem(${w.id})">삭제</button>
            </div>
        `;
        el.appendChild(card);
    });
}

async function addWatchItem() {
    const name = localStorage.getItem("tradeName") || "";
    if (!name) { alert("거래소에서 먼저 닉네임을 등록해주세요."); return; }

    const itemInput = document.getElementById("wl-item").value.trim();
    const price = parseInt(document.getElementById("wl-price").value) || 0;
    if (!itemInput) { alert("아이템을 입력해주세요."); return; }
    if (price < 1) { alert("목표가를 입력해주세요."); return; }

    const searchRes = await fetch(`/api/items/search?q=${encodeURIComponent(itemInput)}&limit=1`);
    const searchJson = await searchRes.json();
    const items = searchJson.data || [];
    if (!items.length) { alert("아이템을 찾을 수 없습니다."); return; }

    const item = items[0];
    const res = await fetch("/api/watchlist", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            user_name: name,
            item_slug: item.slug,
            item_name: item.ko_name || item.name,
            target_price: price,
        }),
    });
    const json = await res.json();
    if (!json.ok) { alert(json.msg); return; }
    renderWatchlist();
}

async function removeWatchItem(id) {
    const name = localStorage.getItem("tradeName") || "";
    await fetch(`/api/watchlist/${id}?user_name=${encodeURIComponent(name)}`, { method: "DELETE" });
    renderWatchlist();
}


// ── 경매 ──
let auctionType = "riven";
let auctionQuery = "";
let rivenFilterGrade = "";
let rivenFilterGroup = "";  // 무기 카테고리: primary/secondary/melee/kitgun/zaw 등
let rivenSorts = [];
let _rivenItemsCache = null;  // 리벤 무기 목록 캐시 (group 필터용)
// 리치/시스터 필터
let lichFilterSource = "";
let lichFilterEphemera = "";
let lichFilterElement = "";
let lichFilterMinBonus = 0;
let lichSorts = [];

let _auctionDebounceTimer = null;

function renderAuctionView() {
    // 디바운스: 빠른 필터 클릭 시 마지막 것만 실행
    if (_auctionDebounceTimer) clearTimeout(_auctionDebounceTimer);
    _auctionDebounceTimer = setTimeout(_renderAuctionViewImpl, 150);
}

function _renderAuctionViewImpl() {
    const container = document.getElementById("chat-auction");
    container.innerHTML = "";

    // 검색바
    const search = document.createElement("div");
    search.className = "auction-search";
    search.innerHTML = `
        <input type="text" id="auction-search-input" placeholder="무기 이름으로 검색..." value="${escapeHtml(auctionQuery)}" autocomplete="off">
        <button onclick="doAuctionSearch()">검색</button>
    `;
    container.appendChild(search);

    // 엔터 처리
    setTimeout(() => {
        const inp = document.getElementById("auction-search-input");
        if (inp) inp.addEventListener("keydown", (e) => { if (e.key === "Enter") doAuctionSearch(); });
    }, 0);

    // 탭
    const atabs = document.createElement("div");
    atabs.className = "auction-tabs";
    [{ key: "riven", label: "리벤 모드" }, { key: "lich", label: "리치 / 시스터 무기" }].forEach((t) => {
        const btn = document.createElement("button");
        btn.className = "auction-tab" + (auctionType === t.key ? " active" : "");
        btn.textContent = t.label;
        btn.onclick = () => { auctionType = t.key; renderAuctionView(); };
        atabs.appendChild(btn);
    });
    container.appendChild(atabs);

    // 리치/시스터 필터 UI
    if (auctionType === "lich") {
        const filters = document.createElement("div");
        filters.className = "auction-filters";

        // 소스
        const sourceRow = document.createElement("div");
        sourceRow.className = "auction-filter-row";
        sourceRow.innerHTML = '<span class="auction-filter-label">종류</span>';
        [{ key: "", label: "전체" }, { key: "lich", label: "리치" }, { key: "sister", label: "시스터" }].forEach((s) => {
            const chip = document.createElement("div");
            chip.className = "auction-filter-chip" + (lichFilterSource === s.key ? " active" : "");
            chip.textContent = s.label;
            chip.addEventListener("click", () => { lichFilterSource = s.key; renderAuctionView(); });
            sourceRow.appendChild(chip);
        });
        filters.appendChild(sourceRow);

        // 에페메라
        const ephRow = document.createElement("div");
        ephRow.className = "auction-filter-row";
        ephRow.innerHTML = '<span class="auction-filter-label">에페메라</span>';
        [{ key: "", label: "전체" }, { key: "yes", label: "있음" }, { key: "no", label: "없음" }].forEach((e) => {
            const chip = document.createElement("div");
            chip.className = "auction-filter-chip" + (lichFilterEphemera === e.key ? " active" : "");
            chip.textContent = e.label;
            chip.addEventListener("click", () => { lichFilterEphemera = e.key; renderAuctionView(); });
            ephRow.appendChild(chip);
        });
        filters.appendChild(ephRow);

        // 속성
        const elemRow = document.createElement("div");
        elemRow.className = "auction-filter-row";
        elemRow.innerHTML = '<span class="auction-filter-label">속성</span>';
        const allChip = document.createElement("div");
        allChip.className = "auction-filter-chip" + (lichFilterElement === "" ? " active" : "");
        allChip.textContent = "전체";
        allChip.addEventListener("click", () => { lichFilterElement = ""; renderAuctionView(); });
        elemRow.appendChild(allChip);
        ALL_ELEMENTS.forEach((el) => {
            const chip = document.createElement("div");
            chip.className = "auction-filter-chip" + (lichFilterElement === el ? " active" : "");
            chip.textContent = ELEMENT_KO[el];
            chip.addEventListener("click", () => { lichFilterElement = el; renderAuctionView(); });
            elemRow.appendChild(chip);
        });
        filters.appendChild(elemRow);

        // 최소 보너스%
        const bonusRow = document.createElement("div");
        bonusRow.className = "auction-filter-row";
        bonusRow.innerHTML = '<span class="auction-filter-label">보너스</span>';
        const bonusInput = document.createElement("input");
        bonusInput.type = "number";
        bonusInput.className = "auction-bonus-input";
        bonusInput.placeholder = "최소 %";
        bonusInput.min = "0";
        bonusInput.max = "60";
        bonusInput.value = lichFilterMinBonus || "";
        bonusInput.addEventListener("change", () => {
            lichFilterMinBonus = parseInt(bonusInput.value) || 0;
            renderAuctionView();
        });
        bonusRow.appendChild(bonusInput);
        const bonusHint = document.createElement("span");
        bonusHint.style.cssText = "font-size:11px;color:var(--text-muted);";
        bonusHint.textContent = "% 이상";
        bonusRow.appendChild(bonusHint);
        filters.appendChild(bonusRow);

        // 정렬
        filters.appendChild(buildMultiSortRow(
            [{ key: "price", label: "가격" }, { key: "bonus", label: "보너스%" }],
            lichSorts,
            (newSorts) => { lichSorts = newSorts; renderAuctionView(); }
        ));

        container.appendChild(filters);
    }

    if (auctionType === "riven") {
        fetchRivenAuctions(container);
    } else {
        fetchLichAuctions(container);
    }
}

function doAuctionSearch() {
    auctionQuery = (document.getElementById("auction-search-input")?.value || "").trim();
    renderAuctionView();
}

function _appendEmpty(container, text) {
    const div = document.createElement("div");
    div.className = "auction-empty";
    div.textContent = text;
    container.appendChild(div);
}

let _auctionRenderId = 0;
let _auctionAbortCtrl = null;

async function fetchRivenAuctions(container) {
    if (_auctionAbortCtrl) _auctionAbortCtrl.abort();
    _auctionAbortCtrl = new AbortController();
    const renderId = ++_auctionRenderId;
    const params = new URLSearchParams({ limit: "30", sort_by: "price_asc" });
    // 검색어를 그대로 전달 (한글/영문 모두 백엔드에서 resolve)
    if (auctionQuery) params.set("weapon", auctionQuery.trim());
    // 카테고리 필터를 백엔드로 전달 (해당 카테고리 인기 무기로 조회)
    if (rivenFilterGroup) params.set("group", rivenFilterGroup);

    // 리벤 무기 목록 캐시 로드 (group 필터용)
    if (!_rivenItemsCache) {
        try {
            const itemsRes = await fetch("/api/auction/riven/items");
            const itemsJson = await itemsRes.json();
            _rivenItemsCache = itemsJson.data || [];
        } catch (e) { _rivenItemsCache = []; }
    }

    // 무기 카테고리 필터 UI
    const groupRow = document.createElement("div");
    groupRow.className = "auction-filter-row";
    groupRow.innerHTML = '<span class="auction-filter-label">무기 종류</span>';
    [
        { val: "", label: "전체" },
        { val: "primary", label: "주무기" },
        { val: "secondary", label: "보조무기" },
        { val: "melee", label: "근접" },
        { val: "kitgun", label: "키트건" },
        { val: "zaw", label: "조우" },
        { val: "archgun", label: "아크윙 무기" },
        { val: "sentinel", label: "센티넬" },
    ].forEach((opt) => {
        const chip = document.createElement("button");
        chip.className = "auction-filter-chip" + (rivenFilterGroup === opt.val ? " active" : "");
        chip.textContent = opt.label;
        chip.onclick = () => { rivenFilterGroup = opt.val; renderAuctionView(); };
        groupRow.appendChild(chip);
    });
    container.appendChild(groupRow);

    // 등급 필터 UI
    const gradeRow = document.createElement("div");
    gradeRow.className = "auction-filter-row";
    gradeRow.innerHTML = '<span class="auction-filter-label">등급</span>';
    [
        { val: "", label: "전체" },
        { val: "recommended", label: "추천 (S+A)" },
        { val: "S", label: "S" },
        { val: "A", label: "A" },
        { val: "B", label: "B" },
        { val: "C", label: "C" },
    ].forEach((opt) => {
        const chip = document.createElement("button");
        chip.className = "auction-filter-chip" + (rivenFilterGrade === opt.val ? " active" : "");
        chip.textContent = opt.label;
        chip.onclick = () => { rivenFilterGrade = opt.val; renderAuctionView(); };
        gradeRow.appendChild(chip);
    });
    container.appendChild(gradeRow);

    // 정렬 UI
    container.appendChild(buildMultiSortRow(
        [{ key: "price", label: "가격" }, { key: "mastery", label: "MR" }, { key: "rerolls", label: "리롤" }, { key: "grade", label: "등급" }],
        rivenSorts,
        (newSorts) => { rivenSorts = newSorts; renderAuctionView(); }
    ));

    // 로딩 표시
    const loadingEl = document.createElement("div");
    loadingEl.className = "surge-empty";
    loadingEl.textContent = "로딩 중...";
    container.appendChild(loadingEl);

    try {
        const res = await fetch(`/api/auction/riven?${params}`, { signal: _auctionAbortCtrl.signal });
        if (renderId !== _auctionRenderId) return; // stale render
        const json = await res.json();
        if (renderId !== _auctionRenderId) return; // stale after parse
        let items = json.data || [];

        loadingEl.remove();

        if (!items.length) {
            _appendEmpty(container, "검색 결과가 없습니다.");
            return;
        }

        // 등급 계산
        items = items.map((a) => ({ ...a, _grade: gradeRiven(a) }));

        // 등급 필터
        if (rivenFilterGrade === "recommended") {
            items = items.filter((a) => a._grade.grade === "S" || a._grade.grade === "A");
        } else if (rivenFilterGrade) {
            items = items.filter((a) => a._grade.grade === rivenFilterGrade);
        }

        // 정렬
        const gradeOrder = { S: 4, A: 3, B: 2, C: 1 };
        items = applyMultiSort([...items], rivenSorts, (item, key) => {
            if (key === "price") return item.buyoutPrice || item.topBid || item.startingPrice || 0;
            if (key === "mastery") return item.mastery;
            if (key === "rerolls") return item.rerolls;
            if (key === "grade") return gradeOrder[item._grade.grade] || 0;
            return 0;
        });

        if (!items.length) {
            _appendEmpty(container, "조건에 맞는 경매가 없습니다.");
            return;
        }

        _renderRivenCards(container, items, 0);
    } catch (err) {
        if (err && err.name === "AbortError") return; // 취소된 요청 무시
        if (renderId !== _auctionRenderId) return;
        loadingEl.remove();
        _appendEmpty(container, "경매 데이터를 불러오지 못했습니다.");
    }
}

const RIVEN_PAGE_SIZE = 10;

function _renderRivenCards(container, items, from) {
    const end = Math.min(from + RIVEN_PAGE_SIZE, items.length);
    for (let i = from; i < end; i++) {
        const a = items[i];
        const card = document.createElement("div");
        card.className = "auction-card";
        const priceText = a.topBid ? a.topBid + "p" : (a.startingPrice + "p 시작");
        const buyoutText = a.buyoutPrice ? `<span class="buyout">즉시 구매 ${a.buyoutPrice}p</span>` : "";

        const g = a._grade;
        let gradeBadge = "";
        if (g.grade) {
            gradeBadge = ' <span class="riven-grade grade-' + g.grade + '">' + g.grade + '</span>';
        }

        let gradeDetail = "";
        if (g.details && g.details.length) {
            gradeDetail = '<div class="riven-grade-detail">' +
                g.details.map((d) => '<span class="' + d.type + '">' + escapeHtml(d.text) + '</span>').join(" · ") +
                '</div>';
        }

        card.innerHTML = `
            <div class="auction-card-header">
                <div class="auction-card-title"><a href="https://warframe.market/auction/${a.id}" target="_blank">${escapeHtml(a.weapon)}${a.name ? ' <span class="riven-suffix">' + escapeHtml(a.name) + '</span>' : ''}</a>${gradeBadge}</div>
                <div class="auction-card-price">${priceText} ${buyoutText}</div>
            </div>
            <div class="auction-stats">
                ${a.stats.map((s) => `<span class="auction-stat ${s.positive ? "positive" : "negative"}">${escapeHtml(s.name)} ${s.value > 0 ? "+" : ""}${s.value.toFixed(1)}%</span>`).join("")}
            </div>
            ${gradeDetail}
            <div class="auction-stats" style="margin-top:4px;">
                <span class="auction-stat">MR ${a.mastery}</span>
                <span class="auction-stat">리롤 ${a.rerolls}회</span>
            </div>
            <div class="auction-seller">
                ${escapeHtml(a.seller)} ·
                <span class="${a.sellerStatus !== "offline" ? "online" : ""}">
                    ${a.sellerStatus === "ingame" ? "인게임" : a.sellerStatus === "online" ? "온라인" : "오프라인"}
                </span>
            </div>
        `;
        container.appendChild(card);
    }

    // 더보기 버튼
    if (end < items.length) {
        const moreBtn = document.createElement("button");
        moreBtn.className = "load-more-btn";
        moreBtn.textContent = `더보기 (${end}/${items.length})`;
        moreBtn.onclick = () => { moreBtn.remove(); _renderRivenCards(container, items, end); };
        container.appendChild(moreBtn);
    }
}

async function fetchLichAuctions(container) {
    if (_auctionAbortCtrl) _auctionAbortCtrl.abort();
    _auctionAbortCtrl = new AbortController();
    const renderId = ++_auctionRenderId;
    const params = new URLSearchParams({ limit: "50", sort_by: "price_asc" });
    if (auctionQuery) params.set("weapon", auctionQuery.toLowerCase().replace(/ /g, "_"));
    // 에페메라 + 속성 필터를 백엔드로도 전달 (API가 지원하므로)
    if (lichFilterEphemera === "yes") params.set("ephemera", "yes");
    else if (lichFilterEphemera === "no") params.set("ephemera", "no");
    if (lichFilterElement) params.set("element", lichFilterElement);
    // 클라이언트 필터 값을 호출 시점에 스냅샷
    const snapshotSource = lichFilterSource;
    const snapshotMinBonus = lichFilterMinBonus;

    const loadingEl = document.createElement("div");
    loadingEl.className = "surge-empty";
    loadingEl.textContent = "로딩 중...";
    container.appendChild(loadingEl);

    try {
        const res = await fetch(`/api/auction/lich?${params}`, { signal: _auctionAbortCtrl.signal });
        if (renderId !== _auctionRenderId) return;
        const json = await res.json();
        if (renderId !== _auctionRenderId) return; // stale after parse
        let items = json.data || [];

        loadingEl.remove();

        // 추가 클라이언트 필터 (소스, 보너스 — API에서 미지원) — 스냅샷 값 사용
        if (snapshotSource) items = items.filter((a) => a.source === snapshotSource);
        if (snapshotMinBonus > 0) items = items.filter((a) => a.bonus >= snapshotMinBonus);

        // 정렬
        items = applyMultiSort([...items], lichSorts, (item, key) => {
            if (key === "price") return item.buyoutPrice || item.topBid || 0;
            if (key === "bonus") return item.bonus;
            return 0;
        });

        if (!items.length) {
            _appendEmpty(container, "조건에 맞는 경매가 없습니다.");
            return;
        }

        _renderLichCards(container, items, 0);
    } catch (err) {
        if (err && err.name === "AbortError") return; // 취소된 요청 무시
        if (renderId !== _auctionRenderId) return;
        loadingEl.remove();
        _appendEmpty(container, "경매 데이터를 불러오지 못했습니다.");
    }
}


const LICH_PAGE_SIZE = 10;

function _renderLichCards(container, items, from) {
    const end = Math.min(from + LICH_PAGE_SIZE, items.length);
    for (let i = from; i < end; i++) {
        const a = items[i];
        const card = document.createElement("div");
        card.className = "auction-card";
        const priceText = a.topBid ? a.topBid + "p" : "-";
        const buyoutText = a.buyoutPrice ? `<span class="buyout">즉시 구매 ${a.buyoutPrice}p</span>` : '<span class="buyout">즉구 없음</span>';
        const sourceLabel = a.source === "lich" ? "리치" : "시스터";
        const ephTag = a.ephemera ? `<span class="auction-ephemera-tag">${escapeHtml(a.ephemeraName || "에페메라")}</span>` : "";

        card.innerHTML = `
            <div class="auction-card-header">
                <div class="auction-card-title"><a href="https://warframe.market/auction/${a.id}" target="_blank">${escapeHtml(a.weapon)}</a> ${ephTag}</div>
                <div class="auction-card-price">${priceText} ${buyoutText}</div>
            </div>
            <div class="auction-stats">
                <span class="auction-stat">${sourceLabel}</span>
                <span class="auction-stat positive">${escapeHtml(a.elementKo || ELEMENT_KO[a.element] || a.element)} ${a.bonus}%</span>
                ${a.ephemera ? '' : '<span class="auction-stat">에페메라 없음</span>'}
            </div>
            <div class="auction-seller">
                ${escapeHtml(a.seller)} ·
                <span class="${a.sellerStatus !== "offline" ? "online" : ""}">
                    ${a.sellerStatus === "ingame" ? "인게임" : a.sellerStatus === "online" ? "온라인" : "오프라인"}
                </span>
            </div>
        `;
        container.appendChild(card);
    }

    if (end < items.length) {
        const moreBtn = document.createElement("button");
        moreBtn.className = "load-more-btn";
        moreBtn.textContent = `더보기 (${end}/${items.length})`;
        moreBtn.onclick = () => { moreBtn.remove(); _renderLichCards(container, items, end); };
        container.appendChild(moreBtn);
    }
}

// ── 모딩 공유 ──
const MODDING_CATEGORIES = [
    { key: "warframe", label: "워프레임" },
    { key: "primary", label: "주무기" },
    { key: "secondary", label: "보조무기" },
    { key: "melee", label: "근접무기" },
    { key: "archwing", label: "아크윙" },
    { key: "necramech", label: "네크라메크" },
    { key: "archgun", label: "아크윙무기" },
    { key: "companion", label: "동반자" },
];

let moddingCategory = "warframe";
let moddingSelectedItem = "";
let moddingFormOpen = false;
let moddingFormImages = [];

async function renderModdingTab() {
    const container = document.getElementById("modding-content");
    container.innerHTML = "";

    const cats = document.createElement("div");
    cats.className = "modding-cats";
    MODDING_CATEGORIES.forEach((cat) => {
        const btn = document.createElement("button");
        btn.className = "modding-cat-btn" + (moddingCategory === cat.key ? " active" : "");
        btn.textContent = cat.label;
        btn.onclick = () => { moddingCategory = cat.key; moddingSelectedItem = ""; moddingFormOpen = false; moddingFormImages = []; renderModdingTab(); };
        cats.appendChild(btn);
    });
    container.appendChild(cats);

    if (moddingSelectedItem) {
        await renderModdingDetail(container);
    } else {
        await renderModdingItemList(container);
    }
}

async function renderModdingItemList(container) {
    const addRow = document.createElement("div");
    addRow.style.cssText = "display:flex;justify-content:flex-end;margin-bottom:10px;";
    const addBtn = document.createElement("button");
    addBtn.className = "modding-add-btn";
    addBtn.innerHTML = "+ 공유하기";
    addBtn.onclick = () => { moddingFormOpen = !moddingFormOpen; renderModdingTab(); };
    addRow.appendChild(addBtn);
    container.appendChild(addRow);

    if (moddingFormOpen) {
        container.appendChild(buildModdingForm());
    }

    try {
        const res = await fetch(`/api/modding/items?category=${moddingCategory}`);
        const json = await res.json();
        const items = json.data || [];

        if (!items.length) {
            container.innerHTML += '<div class="modding-empty">아직 공유된 모딩이 없습니다. 첫 번째로 공유해보세요!</div>';
            return;
        }

        items.forEach((item) => {
            const card = document.createElement("div");
            card.className = "modding-item-card";
            const dateStr = new Date(item.latest).toLocaleDateString("ko-KR", { month: "short", day: "numeric" });
            card.innerHTML = `
                <div class="modding-item-thumb-empty"></div>
                <div class="modding-item-info">
                    <div class="modding-item-name">${escapeHtml(item.item_name)}</div>
                    <div class="modding-item-meta">${item.count}건의 공유 · ${dateStr} 최신</div>
                </div>
                <div class="modding-item-arrow">›</div>
            `;
            card.onclick = () => { moddingSelectedItem = item.item_name; moddingFormOpen = false; renderModdingTab(); };
            container.appendChild(card);
        });
    } catch {
        container.innerHTML += '<div class="modding-empty">데이터를 불러오지 못했습니다.</div>';
    }
}

async function renderModdingDetail(container) {
    const header = document.createElement("div");
    header.className = "modding-detail-header";
    header.innerHTML = `
        <button class="modding-back-btn" onclick="moddingSelectedItem='';renderModdingTab();">← 목록</button>
        <span class="modding-detail-title">${escapeHtml(moddingSelectedItem)}</span>
    `;
    container.appendChild(header);

    const addRow = document.createElement("div");
    addRow.style.cssText = "display:flex;justify-content:flex-end;margin-bottom:10px;";
    const addBtn = document.createElement("button");
    addBtn.className = "modding-add-btn";
    addBtn.innerHTML = "+ 공유하기";
    addBtn.onclick = () => { moddingFormOpen = !moddingFormOpen; renderModdingTab(); };
    addRow.appendChild(addBtn);
    container.appendChild(addRow);

    if (moddingFormOpen) {
        container.appendChild(buildModdingForm(moddingSelectedItem));
    }

    try {
        const res = await fetch(`/api/modding/shares?category=${moddingCategory}&item_name=${encodeURIComponent(moddingSelectedItem)}`);
        const json = await res.json();
        const shares = json.data || [];

        if (!shares.length) {
            container.innerHTML += '<div class="modding-empty">이 아이템에 대한 공유가 없습니다.</div>';
            return;
        }

        shares.forEach((s) => {
            const card = document.createElement("div");
            card.className = "modding-card";
            const dateStr = new Date(s.created_at).toLocaleDateString("ko-KR", { year: "numeric", month: "short", day: "numeric" });
            let imagesHtml = "";
            if (s.images && s.images.length) {
                imagesHtml = '<div class="modding-images">' +
                    s.images.map((src) => `<img src="${escapeHtml(src)}" alt="모딩 이미지" onclick="openModdingLightbox(this.src)">`).join("") +
                    '</div>';
            }
            card.innerHTML = `
                <div class="modding-card-top">
                    <span class="modding-card-author">${escapeHtml(s.author)}</span>
                    <span class="modding-card-date">${dateStr}</span>
                </div>
                ${s.memo ? `<div class="modding-card-memo">${escapeHtml(s.memo)}</div>` : ""}
                ${imagesHtml}
            `;
            container.appendChild(card);
        });
    } catch {
        container.innerHTML += '<div class="modding-empty">데이터를 불러오지 못했습니다.</div>';
    }
}

function buildModdingForm(prefillName) {
    const form = document.createElement("div");
    form.className = "modding-form";
    const catLabel = MODDING_CATEGORIES.find((c) => c.key === moddingCategory)?.label || "";
    const nameVal = prefillName ? escapeHtml(prefillName) : "";
    const nameRo = prefillName ? " readonly" : "";

    form.innerHTML = `
        <div class="form-row"><label>${escapeHtml(catLabel)} 이름</label><input type="text" id="modding-f-name" placeholder="예: Mesa Prime" maxlength="50" value="${nameVal}"${nameRo}></div>
        <div class="form-row">
            <label>메모 (최대 1000자)</label>
            <textarea id="modding-f-memo" maxlength="1000" placeholder="모딩에 대한 설명이나 운영법을 적어주세요..."></textarea>
            <div style="text-align:right;font-size:11px;color:var(--text-muted);margin-top:2px;" id="modding-memo-count">0 / 1000</div>
        </div>
        <div class="form-row">
            <label>이미지 (최대 5장)</label>
            <div class="modding-upload-area" id="modding-upload-area">클릭하거나 이미지를 드래그하여 업로드</div>
            <input type="file" id="modding-file-input" accept="image/*" multiple style="display:none;">
            <div class="modding-upload-preview" id="modding-upload-preview"></div>
        </div>
        <div class="form-row"><label>작성자</label><input type="text" id="modding-f-author" placeholder="닉네임" maxlength="20" value="${escapeHtml(localStorage.getItem("tradeName") || "")}"></div>
        <div class="modding-form-actions">
            <button class="btn-cancel" onclick="moddingFormOpen=false;moddingFormImages=[];renderModdingTab();">취소</button>
            <button class="btn-submit" onclick="submitModdingShare()">공유하기</button>
        </div>
    `;

    setTimeout(() => {
        const area = document.getElementById("modding-upload-area");
        const fileInput = document.getElementById("modding-file-input");
        const memo = document.getElementById("modding-f-memo");

        if (memo) memo.addEventListener("input", () => {
            document.getElementById("modding-memo-count").textContent = memo.value.length + " / 1000";
        });
        if (area && fileInput) {
            area.addEventListener("click", () => fileInput.click());
            area.addEventListener("dragover", (e) => { e.preventDefault(); area.style.borderColor = "var(--primary)"; });
            area.addEventListener("dragleave", () => { area.style.borderColor = "var(--border)"; });
            area.addEventListener("drop", (e) => { e.preventDefault(); area.style.borderColor = "var(--border)"; handleModdingFiles(e.dataTransfer.files); });
            fileInput.addEventListener("change", () => { handleModdingFiles(fileInput.files); fileInput.value = ""; });
        }
        renderModdingUploadPreview();
    }, 0);

    return form;
}

async function handleModdingFiles(files) {
    const remaining = 5 - moddingFormImages.length;
    if (remaining <= 0) return;

    for (const file of Array.from(files).slice(0, remaining)) {
        if (!file.type.startsWith("image/")) continue;

        const formData = new FormData();
        formData.append("file", file);

        try {
            const res = await fetch("/api/modding/upload", { method: "POST", body: formData });
            const json = await res.json();
            if (json.ok) {
                moddingFormImages.push({ filename: json.filename, previewUrl: URL.createObjectURL(file) });
                renderModdingUploadPreview();
            } else {
                alert(json.msg);
            }
        } catch {
            alert("업로드에 실패했습니다.");
        }
    }
}

function renderModdingUploadPreview() {
    const preview = document.getElementById("modding-upload-preview");
    if (!preview) return;
    preview.innerHTML = "";
    moddingFormImages.forEach((img, idx) => {
        const thumb = document.createElement("div");
        thumb.className = "thumb";
        thumb.innerHTML = `<img src="${img.previewUrl}"><button class="thumb-remove" onclick="removeModdingImage(${idx})">×</button>`;
        preview.appendChild(thumb);
    });
    const area = document.getElementById("modding-upload-area");
    if (area) area.style.display = moddingFormImages.length >= 5 ? "none" : "";
}

function removeModdingImage(idx) {
    moddingFormImages.splice(idx, 1);
    renderModdingUploadPreview();
}

async function submitModdingShare() {
    const name = (document.getElementById("modding-f-name")?.value || "").trim();
    const memo = (document.getElementById("modding-f-memo")?.value || "").trim();
    const author = (document.getElementById("modding-f-author")?.value || "").trim();

    if (!name) { alert("이름을 입력해주세요."); return; }
    if (!author) { alert("작성자 이름을 입력해주세요."); return; }
    if (moddingFormImages.length === 0) { alert("이미지를 최소 1장 첨부해주세요."); return; }

    const res = await fetch("/api/modding/shares", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            category: moddingCategory,
            item_name: name,
            author: author,
            memo: memo,
            image_filenames: moddingFormImages.map((img) => img.filename),
        }),
    });
    const json = await res.json();
    if (!json.ok) { alert(json.msg); return; }

    moddingFormOpen = false;
    moddingFormImages = [];
    moddingSelectedItem = name;
    renderModdingTab();
}

function openModdingLightbox(src) {
    const lb = document.createElement("div");
    lb.className = "modding-lightbox";
    lb.innerHTML = `<img src="${src}">`;
    lb.onclick = () => lb.remove();
    document.body.appendChild(lb);
}


// ── 알림 팝업 ──
function showAlertNotify(text) {
    if (JSON.parse(localStorage.getItem("settingDnd") || "false")) return;
    const style = localStorage.getItem("settingNotifyStyle") || "popup";
    if (style === "badge") return;
    const el = document.getElementById("alert-notify");
    if (!el) return;
    el.textContent = text;
    el.style.display = "block";
    setTimeout(() => { el.style.display = "none"; }, 5000);
}


// ── 설정 ──
function toggleSettings() {
    const overlay = document.getElementById("settings-overlay");
    const panel = document.getElementById("settings-panel");
    const show = overlay.style.display === "none";
    overlay.style.display = show ? "" : "none";
    panel.style.display = show ? "" : "none";
    if (show) { loadSettings(); renderPaletteGrid(); }
}

function saveSettings() {
    localStorage.setItem("settingDnd", JSON.stringify(document.getElementById("set-dnd").checked));
    localStorage.setItem("settingNotifyStyle", document.getElementById("set-notify-style").value);
}

function loadSettings() {
    document.getElementById("set-dnd").checked = JSON.parse(localStorage.getItem("settingDnd") || "false");
    document.getElementById("set-notify-style").value = localStorage.getItem("settingNotifyStyle") || "popup";
    document.querySelectorAll(".mode-btn").forEach((b) => b.classList.toggle("active", b.dataset.mode === currentMode));
    document.getElementById("palette-label").textContent = (currentMode === "dark" ? "다크" : "라이트") + " 팔레트";
}

// ── 테마 ──
const PALETTES = {
    dark: [
        { name: "기본", colors: ["#1a1a2e", "#16213e", "#4db8ff", "#e0e0e0"], vars: { "--bg": "#1a1a2e", "--surface": "#16213e", "--primary": "#4db8ff", "--text": "#e0e0e0", "--text-muted": "#888", "--border": "#2a2a4a", "--user-bubble": "#0f3460", "--price-bg": "#0a1628" } },
        { name: "사이버펑크", colors: ["#0d0221", "#150734", "#ff2a6d", "#e0e0e0"], vars: { "--bg": "#0d0221", "--surface": "#150734", "--primary": "#ff2a6d", "--text": "#e0e0e0", "--text-muted": "#888", "--border": "#2a1548", "--user-bubble": "#2d1053", "--price-bg": "#0a0118" } },
        { name: "포레스트", colors: ["#1a2e1a", "#1e3e1e", "#66bb6a", "#dce8dc"], vars: { "--bg": "#1a2e1a", "--surface": "#1e3e1e", "--primary": "#66bb6a", "--text": "#dce8dc", "--text-muted": "#8a9e8a", "--border": "#2a4a2a", "--user-bubble": "#1a3a1a", "--price-bg": "#0e1f0e" } },
        { name: "선셋", colors: ["#2e1a1a", "#3e2116", "#ff9800", "#e8dcd0"], vars: { "--bg": "#2e1a1a", "--surface": "#3e2116", "--primary": "#ff9800", "--text": "#e8dcd0", "--text-muted": "#9e8a7a", "--border": "#4a3020", "--user-bubble": "#4a2a10", "--price-bg": "#1f140a" } },
        { name: "미드나잇", colors: ["#1a1a30", "#22224a", "#b388ff", "#d8d0e8"], vars: { "--bg": "#1a1a30", "--surface": "#22224a", "--primary": "#b388ff", "--text": "#d8d0e8", "--text-muted": "#8878a8", "--border": "#3a3060", "--user-bubble": "#2a2060", "--price-bg": "#12102a" } },
    ],
    light: [
        { name: "기본", colors: ["#f5f5f5", "#ffffff", "#1976d2", "#222222"], vars: { "--bg": "#f5f5f5", "--surface": "#ffffff", "--primary": "#1976d2", "--text": "#222222", "--text-muted": "#777", "--border": "#ddd", "--user-bubble": "#bbdefb", "--price-bg": "#e8f0fe" } },
        { name: "로즈", colors: ["#fdf2f4", "#ffffff", "#e91e63", "#333333"], vars: { "--bg": "#fdf2f4", "--surface": "#ffffff", "--primary": "#e91e63", "--text": "#333333", "--text-muted": "#888", "--border": "#f0d0d8", "--user-bubble": "#fce4ec", "--price-bg": "#fdf2f6" } },
        { name: "민트", colors: ["#f0faf4", "#ffffff", "#00897b", "#2a2a2a"], vars: { "--bg": "#f0faf4", "--surface": "#ffffff", "--primary": "#00897b", "--text": "#2a2a2a", "--text-muted": "#777", "--border": "#c8e6c9", "--user-bubble": "#b2dfdb", "--price-bg": "#e0f5f0" } },
        { name: "피치", colors: ["#fef6f0", "#ffffff", "#e65100", "#333333"], vars: { "--bg": "#fef6f0", "--surface": "#ffffff", "--primary": "#e65100", "--text": "#333333", "--text-muted": "#888", "--border": "#eed8c0", "--user-bubble": "#ffe0b2", "--price-bg": "#fff3e0" } },
        { name: "라벤더", colors: ["#f4f0fa", "#ffffff", "#7b1fa2", "#2a2a2a"], vars: { "--bg": "#f4f0fa", "--surface": "#ffffff", "--primary": "#7b1fa2", "--text": "#2a2a2a", "--text-muted": "#888", "--border": "#d8c8e8", "--user-bubble": "#e1bee7", "--price-bg": "#f3e5f5" } },
    ],
};

let currentMode = localStorage.getItem("themeMode") || "dark";
let currentPalette = parseInt(localStorage.getItem("themePalette_" + currentMode) || "0");

function applyPalette() {
    const palettes = PALETTES[currentMode];
    const p = palettes[currentPalette] || palettes[0];
    for (const [key, val] of Object.entries(p.vars)) {
        document.documentElement.style.setProperty(key, val);
    }
    if (currentMode === "light") {
        document.documentElement.style.setProperty("--green", "#2e7d32");
        document.documentElement.style.setProperty("--red", "#d32f2f");
        document.documentElement.style.setProperty("--orange", "#e65100");
    } else {
        document.documentElement.style.setProperty("--green", "#4caf50");
        document.documentElement.style.setProperty("--red", "#ff6b6b");
        document.documentElement.style.setProperty("--orange", "#ff9800");
    }
}

function switchMode(mode) {
    currentMode = mode;
    localStorage.setItem("themeMode", mode);
    currentPalette = parseInt(localStorage.getItem("themePalette_" + mode) || "0");
    applyPalette();
    document.querySelectorAll(".mode-btn").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
    document.getElementById("palette-label").textContent = (mode === "dark" ? "다크" : "라이트") + " 팔레트";
    renderPaletteGrid();
}

function renderPaletteGrid() {
    const grid = document.getElementById("palette-grid");
    if (!grid) return;
    grid.innerHTML = "";
    const palettes = PALETTES[currentMode];
    palettes.forEach((p, idx) => {
        const opt = document.createElement("div");
        opt.className = "palette-option" + (idx === currentPalette ? " active" : "");
        opt.addEventListener("click", () => {
            currentPalette = idx;
            localStorage.setItem("themePalette_" + currentMode, idx);
            applyPalette();
            renderPaletteGrid();
        });
        const colors = document.createElement("div");
        colors.className = "palette-colors";
        p.colors.forEach((c) => {
            const swatch = document.createElement("div");
            swatch.className = "palette-swatch";
            swatch.style.background = c;
            colors.appendChild(swatch);
        });
        const name = document.createElement("span");
        name.className = "palette-name";
        name.textContent = p.name;
        opt.appendChild(colors);
        opt.appendChild(name);
        grid.appendChild(opt);
    });
}

// ── 관리자 패널 ──

function adminLoadAll() {
    adminLoadUsers();
    adminLoadTrade();
    adminLoadModding();
}

async function adminLoadUsers() {
    const res = await fetch("/api/admin/users");
    const data = await res.json();
    const el = document.getElementById("admin-users-list");
    if (!data.data.length) { el.innerHTML = '<div class="admin-empty">등록된 유저 없음</div>'; return; }
    const STATUS_KO = { pending: "대기", approved: "승인", rejected: "거절" };
    el.innerHTML = data.data.map(u => `
        <div class="admin-row">
            <span class="admin-row-name">${escapeHtml(u.name)}</span>
            <span class="admin-row-status admin-status-${u.status}">${STATUS_KO[u.status] || u.status}</span>
            <div class="admin-row-actions">
                ${u.status === "pending" ? `<button class="admin-btn admin-btn-approve" onclick="adminApprove('${escapeHtml(u.name)}')">승인</button>` : ""}
                ${u.status === "approved" ? `<button class="admin-btn admin-btn-revoke" onclick="adminRevoke('${escapeHtml(u.name)}')">취소</button>` : ""}
            </div>
        </div>
    `).join("");
}

async function adminApprove(name) {
    const data = await (await fetch(`/api/admin/users/${encodeURIComponent(name)}/approve`, { method: "POST" })).json();
    if (data) adminLoadUsers();
}

async function adminRevoke(name) {
    await fetch(`/api/admin/users/${encodeURIComponent(name)}/revoke`, { method: "POST" });
    adminLoadUsers();
}

async function adminLoadTrade() {
    const data = await (await fetch("/api/trade/listings?limit=200")).json();
    const el = document.getElementById("admin-trade-list");
    if (!data.data.length) { el.innerHTML = '<div class="admin-empty">매물 없음</div>'; return; }
    el.innerHTML = data.data.map(l => `
        <div class="admin-row">
            <span class="admin-row-id">#${l.id}</span>
            <span class="admin-row-name">${escapeHtml(l.item_name)}</span>
            <span class="admin-row-meta">${l.trade_type === "sell" ? "팝니다" : "삽니다"} · ${l.price}p · ${escapeHtml(l.user_name)}</span>
            <button class="admin-btn admin-btn-delete" onclick="adminDeleteListing(${l.id})">삭제</button>
        </div>
    `).join("");
}

async function adminDeleteListing(id) {
    await fetch(`/api/admin/trade/${id}`, { method: "DELETE" });
    adminLoadTrade();
}

async function adminLoadModding() {
    const data = await (await fetch("/api/admin/modding")).json();
    const el = document.getElementById("admin-modding-list");
    if (!data.data.length) { el.innerHTML = '<div class="admin-empty">공유 없음</div>'; return; }
    el.innerHTML = data.data.map(s => `
        <div class="admin-row">
            <span class="admin-row-id">#${s.id}</span>
            <span class="admin-row-name">${escapeHtml(s.item_name)}</span>
            <span class="admin-row-meta">${escapeHtml(s.author)} · ${escapeHtml(s.category)}</span>
            <button class="admin-btn admin-btn-delete" onclick="adminDeleteModding(${s.id})">삭제</button>
        </div>
    `).join("");
}

async function adminDeleteModding(id) {
    await fetch(`/api/admin/modding/${id}`, { method: "DELETE" });
    adminLoadModding();
}

document.getElementById("admin-tab")?.addEventListener("click", () => { adminLoadAll(); });

// ── 초기화 ──
applyPalette();
connect();
