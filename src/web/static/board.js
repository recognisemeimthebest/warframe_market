// 거래소 게시판 클라이언트 로직.
// 의존: app.js의 escapeHtml() 글로벌.

let currentBoardType = "WTS";
let _rivenOptionsCache = null;

const _boardTypeLabel = { WTS: "팝니다", WTB: "삽니다", RIVEN: "리벤" };

document.querySelectorAll(".board-subtab").forEach((btn) => {
    btn.addEventListener("click", () => {
        const t = btn.dataset.btype;
        if (t === currentBoardType) return;
        document.querySelectorAll(".board-subtab").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        currentBoardType = t;
        loadBoardList();
    });
});

async function loadBoardList() {
    const el = document.getElementById("board-list");
    el.innerHTML = '<div class="board-empty">불러오는 중...</div>';
    try {
        const res = await fetch(`/api/board/posts?type=${currentBoardType}`);
        const json = await res.json();
        renderBoardList(json.data || []);
    } catch {
        el.innerHTML = '<div class="board-empty">목록을 불러오지 못했습니다.</div>';
    }
}

function _fmtTime(iso) {
    try {
        const d = new Date(iso);
        const now = new Date();
        const diff = (now - d) / 1000;
        if (diff < 60) return "방금";
        if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
        if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}일 전`;
        return d.toLocaleDateString();
    } catch { return iso; }
}

function renderBoardList(posts) {
    const el = document.getElementById("board-list");
    if (!posts.length) {
        el.innerHTML = '<div class="board-empty">아직 게시글이 없어요. 첫 글을 올려보세요!</div>';
        return;
    }
    el.innerHTML = "";
    posts.forEach((p) => {
        const card = document.createElement("div");
        card.className = `board-card btype-${p.type}`;
        const typeLabel = _boardTypeLabel[p.type] || p.type;
        const rivenInfo = p.riven ? renderRivenSummary(p.riven) : "";
        const noteHtml = p.note ? `<div class="board-note">${escapeHtml(p.note)}</div>` : "";
        card.innerHTML = `
            <div class="board-card-head">
                <span class="board-type-tag t-${p.type}">${escapeHtml(typeLabel)}</span>
                <span class="board-item-name">${escapeHtml(p.item_name)}</span>
                <span class="board-price">${p.price.toLocaleString()}p</span>
            </div>
            ${rivenInfo}
            <div class="board-meta">
                <span>${escapeHtml(p.ign)}</span>
                <span>·</span>
                <span>수량 ${p.quantity}</span>
                <span>·</span>
                <span>${_fmtTime(p.created_at)}</span>
            </div>
            ${noteHtml}
            <div class="board-actions">
                <button class="board-btn primary" onclick="openBoardContactModal(${p.id})">구매원해요</button>
                <button class="board-btn" onclick="openBoardEditModal(${p.id})">수정</button>
                <button class="board-btn danger" onclick="openBoardDeleteModal(${p.id})">삭제</button>
            </div>
        `;
        el.appendChild(card);
    });
}

function renderRivenSummary(r) {
    const parts = [];
    if (r.weapon_name) parts.push(`<b>${escapeHtml(r.weapon_name)}</b>`);
    if (r.polarity) parts.push(`극성: ${escapeHtml(r.polarity)}`);
    if (r.mastery_rank) parts.push(`MR ${r.mastery_rank}`);
    if (r.rolls != null) parts.push(`${r.rolls}롤`);
    let stats = "";
    if (r.stats && r.stats.length) {
        stats = '<ul class="board-riven-stats">' +
            r.stats.map((s) => `<li>+ ${escapeHtml(s.name)} ${s.value > 0 ? "+" : ""}${s.value}</li>`).join("") +
            (r.negative_stat ? `<li class="neg">- ${escapeHtml(r.negative_stat)}</li>` : "") +
            "</ul>";
    }
    return `<div class="board-riven">${parts.join(" · ")}${stats}</div>`;
}

// ── 모달 ──

function openBoardModal(title, bodyHtml) {
    document.getElementById("board-modal-title").textContent = title;
    document.getElementById("board-modal-body").innerHTML = bodyHtml;
    document.getElementById("board-modal-overlay").style.display = "block";
    document.getElementById("board-modal").style.display = "block";
}

function closeBoardModal() {
    document.getElementById("board-modal-overlay").style.display = "none";
    document.getElementById("board-modal").style.display = "none";
}

async function _ensureRivenOptions() {
    if (_rivenOptionsCache) return _rivenOptionsCache;
    const res = await fetch("/api/board/riven/options");
    const json = await res.json();
    _rivenOptionsCache = json;
    return json;
}

// ── 글쓰기 모달 ──

async function openBoardWriteModal() {
    const t = currentBoardType;
    const isRiven = t === "RIVEN";
    let rivenForm = "";
    if (isRiven) {
        const opts = await _ensureRivenOptions();
        rivenForm = _buildRivenFormHtml(opts);
    }
    openBoardModal(`글쓰기 — ${_boardTypeLabel[t]}`, `
        <form id="board-write-form" class="board-form">
            <input type="hidden" name="type" value="${t}">
            <label>아이템 이름
                <input name="item_name" required maxlength="80" placeholder="${isRiven ? '예: Rubico Riven' : '예: 라이노 프라임 세트'}">
            </label>
            <div class="board-form-row">
                <label>가격(p)
                    <input name="price" type="number" min="0" required value="0">
                </label>
                <label>수량
                    <input name="quantity" type="number" min="1" value="1">
                </label>
            </div>
            ${rivenForm}
            <label>메모 (200자)
                <textarea name="note" maxlength="200" rows="2" placeholder="협상 가능, 디스코드 ID 등"></textarea>
            </label>
            <div class="board-form-row">
                <label>인게임 이름(IGN)
                    <input name="ign" required maxlength="20">
                </label>
                <label>비밀번호 (수정/삭제용)
                    <input name="password" type="password" required minlength="2" maxlength="64">
                </label>
            </div>
            <div class="board-form-msg" id="board-write-msg"></div>
            <button type="submit" class="board-btn primary full">등록</button>
        </form>
    `);
    document.getElementById("board-write-form").addEventListener("submit", _onBoardWriteSubmit);
    if (isRiven) _wireRivenForm();
}

function _buildRivenFormHtml(opts) {
    const polOptions = opts.polarities.map((p) => `<option value="${escapeHtml(p.value)}">${escapeHtml(p.label)}</option>`).join("");
    const statOptions = opts.stats.map((s) => `<option value="${escapeHtml(s.value)}">${escapeHtml(s.label)}</option>`).join("");
    return `
        <fieldset class="board-riven-fieldset">
            <legend>리벤 상세</legend>
            <div class="board-form-row">
                <label>무기명
                    <input name="weapon_name" required maxlength="40" placeholder="예: Rubico">
                </label>
                <label>극성
                    <select name="polarity"><option value="">미지정</option>${polOptions}</select>
                </label>
            </div>
            <div class="board-form-row">
                <label>요구 MR
                    <input name="mastery_rank" type="number" min="8" max="16" value="8">
                </label>
                <label>롤 수
                    <input name="rolls" type="number" min="0" max="999" value="0">
                </label>
            </div>
            <div id="riven-stats-list"></div>
            <button type="button" class="board-btn" onclick="addRivenStatRow()">+ 옵션 추가</button>
            <label>네거티브 옵션 (있을 경우)
                <select name="negative_stat"><option value="">없음</option>${statOptions}</select>
            </label>
            <input type="hidden" id="riven-stat-options" data-options='${JSON.stringify(opts.stats).replaceAll("'", "&apos;")}'>
        </fieldset>
    `;
}

function _wireRivenForm() {
    addRivenStatRow();
    addRivenStatRow();
}

function addRivenStatRow() {
    const list = document.getElementById("riven-stats-list");
    if (!list) return;
    const optsRaw = document.getElementById("riven-stat-options").dataset.options;
    const opts = JSON.parse(optsRaw);
    const row = document.createElement("div");
    row.className = "board-form-row riven-stat-row";
    row.innerHTML = `
        <select class="riven-stat-name">
            <option value="">옵션 선택</option>
            ${opts.map((s) => `<option value="${escapeHtml(s.label)}">${escapeHtml(s.label)}</option>`).join("")}
        </select>
        <input class="riven-stat-value" type="number" step="0.1" placeholder="값 (%)">
        <button type="button" class="board-btn danger" onclick="this.parentElement.remove()">×</button>
    `;
    list.appendChild(row);
}

function _collectRivenPayload(form) {
    const stats = [];
    document.querySelectorAll("#riven-stats-list .riven-stat-row").forEach((row) => {
        const name = row.querySelector(".riven-stat-name").value.trim();
        const valueRaw = row.querySelector(".riven-stat-value").value;
        if (name && valueRaw !== "") {
            stats.push({ name, value: parseFloat(valueRaw) });
        }
    });
    return {
        weapon_name: form.weapon_name.value.trim(),
        polarity: form.polarity.value,
        mastery_rank: parseInt(form.mastery_rank.value, 10) || 8,
        rolls: parseInt(form.rolls.value, 10) || 0,
        stats,
        negative_stat: form.negative_stat.value || "",
    };
}

async function _onBoardWriteSubmit(ev) {
    ev.preventDefault();
    const form = ev.target;
    const msg = document.getElementById("board-write-msg");
    const type = form.type.value;
    const payload = {
        type,
        item_name: form.item_name.value.trim(),
        price: parseInt(form.price.value, 10),
        quantity: parseInt(form.quantity.value, 10),
        ign: form.ign.value.trim(),
        password: form.password.value,
        note: form.note.value,
    };
    if (type === "RIVEN") payload.riven = _collectRivenPayload(form);

    msg.textContent = "등록 중...";
    try {
        const res = await fetch("/api/board/posts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const json = await res.json();
        if (!json.ok) {
            msg.textContent = json.msg || "등록 실패";
            return;
        }
        closeBoardModal();
        loadBoardList();
    } catch {
        msg.textContent = "네트워크 오류";
    }
}

// ── 구매원해요 모달 ──

function openBoardContactModal(postId) {
    openBoardModal("연락 보내기", `
        <form id="board-contact-form" class="board-form">
            <label>본인 IGN
                <input name="from_ign" required maxlength="20">
            </label>
            <label>메시지 (선택)
                <textarea name="message" maxlength="200" rows="3" placeholder="구매원해요 / 가격 협상 가능?"></textarea>
            </label>
            <div class="board-form-msg" id="board-contact-msg"></div>
            <button type="submit" class="board-btn primary full">보내기</button>
        </form>
    `);
    document.getElementById("board-contact-form").addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const form = ev.target;
        const msg = document.getElementById("board-contact-msg");
        msg.textContent = "전송 중...";
        try {
            const res = await fetch(`/api/board/posts/${postId}/contact`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    from_ign: form.from_ign.value.trim(),
                    message: form.message.value,
                }),
            });
            const json = await res.json();
            if (!json.ok) { msg.textContent = json.msg || "전송 실패"; return; }
            msg.textContent = "전송됨! 판매자에게 알림이 갑니다.";
            setTimeout(closeBoardModal, 1500);
        } catch {
            msg.textContent = "네트워크 오류";
        }
    });
}

// ── 수정 모달 ──

async function openBoardEditModal(postId) {
    let postRes;
    try {
        const r = await fetch(`/api/board/posts/${postId}`);
        postRes = await r.json();
    } catch { return; }
    if (!postRes.ok) return;
    const p = postRes.data;
    const isRiven = p.type === "RIVEN";
    let rivenForm = "";
    if (isRiven) {
        const opts = await _ensureRivenOptions();
        rivenForm = _buildRivenFormHtml(opts);
    }
    openBoardModal(`수정 — ${_boardTypeLabel[p.type]}`, `
        <form id="board-edit-form" class="board-form">
            <label>아이템 이름
                <input name="item_name" required maxlength="80" value="${escapeHtml(p.item_name)}">
            </label>
            <div class="board-form-row">
                <label>가격(p)
                    <input name="price" type="number" min="0" required value="${p.price}">
                </label>
                <label>수량
                    <input name="quantity" type="number" min="1" value="${p.quantity}">
                </label>
            </div>
            ${rivenForm}
            <label>메모
                <textarea name="note" maxlength="200" rows="2">${escapeHtml(p.note || "")}</textarea>
            </label>
            <label>비밀번호
                <input name="password" type="password" required minlength="1" maxlength="64">
            </label>
            <div class="board-form-msg" id="board-edit-msg"></div>
            <button type="submit" class="board-btn primary full">수정</button>
        </form>
    `);
    if (isRiven && p.riven) _prefillRivenForm(p.riven);
    document.getElementById("board-edit-form").addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const form = ev.target;
        const msg = document.getElementById("board-edit-msg");
        const payload = {
            password: form.password.value,
            item_name: form.item_name.value.trim(),
            price: parseInt(form.price.value, 10),
            quantity: parseInt(form.quantity.value, 10),
            note: form.note.value,
        };
        if (isRiven) payload.riven = _collectRivenPayload(form);
        msg.textContent = "수정 중...";
        try {
            const res = await fetch(`/api/board/posts/${postId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const json = await res.json();
            if (!json.ok) { msg.textContent = json.msg || "수정 실패"; return; }
            closeBoardModal();
            loadBoardList();
        } catch { msg.textContent = "네트워크 오류"; }
    });
}

function _prefillRivenForm(r) {
    const form = document.getElementById("board-edit-form");
    if (!form) return;
    if (form.weapon_name) form.weapon_name.value = r.weapon_name || "";
    if (form.polarity) form.polarity.value = r.polarity || "";
    if (form.mastery_rank) form.mastery_rank.value = r.mastery_rank || 8;
    if (form.rolls) form.rolls.value = r.rolls || 0;
    if (form.negative_stat) form.negative_stat.value = r.negative_stat || "";
    const list = document.getElementById("riven-stats-list");
    if (list) list.innerHTML = "";
    (r.stats || []).forEach((s) => {
        addRivenStatRow();
        const rows = document.querySelectorAll("#riven-stats-list .riven-stat-row");
        const last = rows[rows.length - 1];
        last.querySelector(".riven-stat-name").value = s.name;
        last.querySelector(".riven-stat-value").value = s.value;
    });
}

// ── 삭제 모달 ──

function openBoardDeleteModal(postId) {
    openBoardModal("게시글 삭제", `
        <form id="board-delete-form" class="board-form">
            <p>삭제하려면 비밀번호를 입력하세요.</p>
            <label>비밀번호
                <input name="password" type="password" required minlength="1" maxlength="64">
            </label>
            <div class="board-form-msg" id="board-delete-msg"></div>
            <button type="submit" class="board-btn danger full">삭제</button>
        </form>
    `);
    document.getElementById("board-delete-form").addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const password = ev.target.password.value;
        const msg = document.getElementById("board-delete-msg");
        msg.textContent = "삭제 중...";
        try {
            const res = await fetch(`/api/board/posts/${postId}/delete`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ password }),
            });
            const json = await res.json();
            if (!json.ok) { msg.textContent = json.msg || "삭제 실패"; return; }
            closeBoardModal();
            loadBoardList();
        } catch { msg.textContent = "네트워크 오류"; }
    });
}

// ── 내 게시글 + 문의함 ──

function openBoardMyModal() {
    openBoardModal("내 게시글 / 문의함", `
        <form id="board-my-form" class="board-form">
            <div class="board-form-row">
                <label>IGN
                    <input name="ign" required maxlength="20">
                </label>
                <label>비밀번호
                    <input name="password" type="password" required minlength="1" maxlength="64">
                </label>
            </div>
            <div class="board-form-msg" id="board-my-msg"></div>
            <button type="submit" class="board-btn primary full">조회</button>
        </form>
        <div id="board-my-results"></div>
    `);
    document.getElementById("board-my-form").addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const form = ev.target;
        const ign = form.ign.value.trim();
        const password = form.password.value;
        const msg = document.getElementById("board-my-msg");
        msg.textContent = "조회 중...";
        try {
            const res = await fetch("/api/board/my-posts", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ ign, password }),
            });
            const json = await res.json();
            if (!json.ok) { msg.textContent = json.msg || "조회 실패"; return; }
            msg.textContent = "";
            renderMyPosts(json.data, password);
        } catch { msg.textContent = "네트워크 오류"; }
    });
}

function renderMyPosts(posts, password) {
    const el = document.getElementById("board-my-results");
    if (!posts.length) { el.innerHTML = '<div class="board-empty">게시글이 없습니다.</div>'; return; }
    el.innerHTML = "";
    posts.forEach((p) => {
        const div = document.createElement("div");
        div.className = "board-my-card";
        const unread = p.unread_count > 0 ? `<span class="board-unread-badge">${p.unread_count}</span>` : "";
        div.innerHTML = `
            <div class="board-my-head">
                <span class="board-type-tag t-${p.type}">${escapeHtml(_boardTypeLabel[p.type] || p.type)}</span>
                <span>${escapeHtml(p.item_name)}</span>
                <span>${p.price.toLocaleString()}p</span>
                ${unread}
            </div>
            <div class="board-my-actions">
                <button class="board-btn" data-act="contacts">문의 ${p.contact_count}</button>
            </div>
            <div class="board-my-contacts" style="display:none;"></div>
        `;
        div.querySelector('[data-act="contacts"]').addEventListener("click", async (ev) => {
            const target = div.querySelector(".board-my-contacts");
            if (target.style.display === "block") { target.style.display = "none"; return; }
            target.innerHTML = "불러오는 중...";
            target.style.display = "block";
            try {
                const res = await fetch(`/api/board/posts/${p.id}/contacts`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ password }),
                });
                const json = await res.json();
                if (!json.ok) { target.innerHTML = json.msg || "조회 실패"; return; }
                if (!json.data.length) { target.innerHTML = '<div class="board-empty">아직 받은 문의가 없습니다.</div>'; return; }
                target.innerHTML = json.data.map((c) =>
                    `<div class="board-contact-item ${c.is_read ? "" : "unread"}">
                        <b>${escapeHtml(c.from_ign)}</b>
                        <span class="board-contact-time">${_fmtTime(c.created_at)}</span>
                        <div>${escapeHtml(c.message || "(메시지 없음)")}</div>
                    </div>`
                ).join("");
                // 자동으로 읽음 처리
                fetch(`/api/board/posts/${p.id}/contacts/read`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ password }),
                });
            } catch { target.innerHTML = "네트워크 오류"; }
        });
        el.appendChild(div);
    });
}
