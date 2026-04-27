// ── 음성채팅 (WebRTC P2P) ──────────────────────────────────────────────────

const voiceState = {
    userName:      '',
    roomId:        null,
    roomName:      null,
    ws:            null,
    peers:         {},   // {userName: {pc: RTCPeerConnection, pendingIce: []}}
    localStream:   null,
    isMuted:       false,
    isDeafened:    false,
    volumes:       {},   // {userName: 0~100}
    messages:      [],   // 채팅 기록 (인메모리)
    inRoom:        false,
    rooms:         [],
    speakingMap:   {},   // {userName: bool}
    _pollTimer:    null,
    _speakTimers:  [],
};

const VOICE_ICE = {
    iceServers: [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },
    ],
};

// ── 탭 초기화 ───────────────────────────────────────────────────────────────

function initVoiceTab() {
    voiceState.userName = localStorage.getItem('voiceUserName') || '';
    if (!voiceState.inRoom) {
        _startRoomPoll();
    }
    renderVoiceTab();
}

function destroyVoiceTab() {
    _stopRoomPoll();
}

function _startRoomPoll() {
    _stopRoomPoll();
    _fetchRooms();
    voiceState._pollTimer = setInterval(_fetchRooms, 5000);
}

function _stopRoomPoll() {
    if (voiceState._pollTimer) {
        clearInterval(voiceState._pollTimer);
        voiceState._pollTimer = null;
    }
}

async function _fetchRooms() {
    try {
        const r = await fetch('/api/voice/rooms');
        const d = await r.json();
        if (d.ok) {
            voiceState.rooms = d.rooms || [];
            if (!voiceState.inRoom) _renderRoomList();
        }
    } catch (_) {}
}

// ── 메인 렌더 ───────────────────────────────────────────────────────────────

function renderVoiceTab() {
    const container = document.getElementById('voice-container');
    if (!container) return;

    if (voiceState.inRoom) {
        _renderInRoom(container);
    } else {
        _renderLobby(container);
    }
}

// ── 로비 UI ─────────────────────────────────────────────────────────────────

function _renderLobby(container) {
    const savedName = escapeHtml(voiceState.userName);
    container.innerHTML = `
<div class="voice-lobby">
    <div class="voice-name-bar">
        <input type="text" id="voice-username-input"
            class="voice-username-input"
            placeholder="내 닉네임 입력..."
            maxlength="20"
            value="${savedName}"
            oninput="voiceState.userName=this.value.trim();localStorage.setItem('voiceUserName',this.value.trim())">
        <button class="voice-create-btn" onclick="openCreateRoomModal()">+ 방 만들기</button>
    </div>
    <div class="voice-rooms-header">
        <span class="voice-section-label">🔊 음성채팅 방 목록</span>
        <span class="voice-rooms-count" id="voice-rooms-count"></span>
    </div>
    <div id="voice-room-list" class="voice-room-list">
        <div class="voice-loading">방 목록을 불러오는 중...</div>
    </div>
</div>

<!-- 방 만들기 모달 -->
<div id="voice-create-overlay" style="display:none;" onclick="closeCreateRoomModal()"></div>
<div id="voice-create-modal" style="display:none;" class="voice-modal">
    <div class="voice-modal-header">
        <span>방 만들기</span>
        <button onclick="closeCreateRoomModal()">×</button>
    </div>
    <div class="voice-modal-body">
        <div class="voice-modal-field">
            <label>방 이름</label>
            <input type="text" id="voice-room-name-input"
                placeholder="예: 라이노 파밍팀" maxlength="30"
                onkeydown="if(event.key==='Enter')submitCreateRoom()">
        </div>
        <div class="voice-modal-hint">방에 아무도 없는 상태로 1시간이 지나면 자동 삭제됩니다.</div>
        <div class="voice-modal-btns">
            <button class="voice-btn-cancel" onclick="closeCreateRoomModal()">취소</button>
            <button class="voice-btn-submit" onclick="submitCreateRoom()">만들기</button>
        </div>
    </div>
</div>`;

    _renderRoomList();
}

function _renderRoomList() {
    const listEl = document.getElementById('voice-room-list');
    const countEl = document.getElementById('voice-rooms-count');
    if (!listEl) return;

    const rooms = voiceState.rooms;
    if (countEl) countEl.textContent = rooms.length ? `${rooms.length}개` : '';

    if (!rooms.length) {
        listEl.innerHTML = '<div class="voice-empty">열린 방이 없습니다.<br>방을 만들어 친구를 초대해보세요!</div>';
        return;
    }

    listEl.innerHTML = rooms.map(r => {
        const memberList = r.members.length
            ? r.members.map(m => escapeHtml(m)).join(', ')
            : '(비어있음)';
        const countdown = r.remaining !== null
            ? `<span class="voice-countdown">⏱ ${_formatSeconds(r.remaining)} 후 삭제</span>`
            : '';
        const memberCount = r.members.length;
        const isEmpty = memberCount === 0;
        return `<div class="voice-room-card${isEmpty ? ' voice-room-empty' : ''}">
            <div class="voice-room-info">
                <div class="voice-room-name">${escapeHtml(r.name)}</div>
                <div class="voice-room-meta">
                    <span class="voice-room-creator">👤 ${escapeHtml(r.creator)}</span>
                    <span class="voice-room-members">🎙 ${memberCount}명${memberCount ? ': ' + memberList : ''}</span>
                    ${countdown}
                </div>
            </div>
            <button class="voice-join-btn" onclick="joinVoiceRoom('${escapeHtml(r.id)}','${escapeHtml(r.name)}')">
                참가
            </button>
        </div>`;
    }).join('');
}

function _formatSeconds(sec) {
    if (sec <= 0) return '0초';
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h) return `${h}시간 ${m}분`;
    if (m) return `${m}분 ${s}초`;
    return `${s}초`;
}

// ── 방 만들기 모달 ──────────────────────────────────────────────────────────

function openCreateRoomModal() {
    if (!voiceState.userName) {
        alert('먼저 닉네임을 입력해주세요.');
        document.getElementById('voice-username-input')?.focus();
        return;
    }
    document.getElementById('voice-create-overlay').style.display = 'block';
    document.getElementById('voice-create-modal').style.display   = 'flex';
    setTimeout(() => document.getElementById('voice-room-name-input')?.focus(), 50);
}

function closeCreateRoomModal() {
    document.getElementById('voice-create-overlay').style.display = 'none';
    document.getElementById('voice-create-modal').style.display   = 'none';
}

async function submitCreateRoom() {
    const nameInput = document.getElementById('voice-room-name-input');
    const name = (nameInput?.value || '').trim();
    if (!name) { alert('방 이름을 입력해주세요.'); return; }

    try {
        const r = await fetch('/api/voice/rooms', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ name, creator: voiceState.userName }),
        });
        const d = await r.json();
        if (d.ok) {
            closeCreateRoomModal();
            joinVoiceRoom(d.room_id, d.name);
        } else {
            alert(d.msg || '방 생성 실패');
        }
    } catch (e) {
        alert('네트워크 오류가 발생했습니다.');
    }
}

// ── 방 입장 ─────────────────────────────────────────────────────────────────

async function joinVoiceRoom(roomId, roomName) {
    if (!voiceState.userName) {
        alert('먼저 닉네임을 입력해주세요.');
        return;
    }

    // 마이크 획득
    try {
        voiceState.localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch (e) {
        alert('마이크 권한이 필요합니다.\n브라우저 설정에서 마이크를 허용해주세요.');
        return;
    }

    voiceState.roomId    = roomId;
    voiceState.roomName  = roomName;
    voiceState.inRoom    = true;
    voiceState.peers     = {};
    voiceState.isMuted   = false;
    voiceState.speakingMap = {};
    _stopRoomPoll();

    // 로컬 음성 감지
    _setupLocalSpeaking();

    // 시그널링 WebSocket 연결
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl = `${proto}://${location.host}/api/voice/ws/${roomId}/${encodeURIComponent(voiceState.userName)}`;
    const ws    = new WebSocket(wsUrl);
    voiceState.ws = ws;

    ws.onopen    = () => {};
    ws.onerror   = () => { alert('서버 연결에 실패했습니다.'); leaveVoiceRoom(); };
    ws.onclose   = () => { if (voiceState.inRoom) leaveVoiceRoom(); };
    ws.onmessage = async (ev) => {
        try {
            await _handleSignal(JSON.parse(ev.data));
        } catch (_) {}
    };

    renderVoiceTab();
}

// ── 시그널링 메시지 처리 ─────────────────────────────────────────────────────

async function _handleSignal(msg) {
    switch (msg.type) {
        case 'room_state':
            // 기존 채팅 기록 로드
            voiceState.messages = msg.messages || [];
            // 이미 있던 멤버들에게 오퍼 전송 (내가 새로 들어온 사람)
            for (const member of msg.members) {
                await _createOffer(member);
            }
            _renderInRoom(document.getElementById('voice-container'), msg.members);
            break;

        case 'user_joined':
            // 새 멤버가 들어옴 → 그쪽에서 offer 보낼 것이므로 대기
            _renderInRoom(document.getElementById('voice-container'), msg.members.filter(m => m !== voiceState.userName));
            break;

        case 'user_left':
            _closePeer(msg.user);
            _renderInRoom(document.getElementById('voice-container'), msg.members.filter(m => m !== voiceState.userName));
            break;

        case 'offer':
            await _handleOffer(msg.from, msg.sdp);
            break;

        case 'answer':
            await _handleAnswer(msg.from, msg.sdp);
            break;

        case 'ice':
            await _handleIce(msg.from, msg.candidate);
            break;

        case 'chat':
            voiceState.messages.push(msg);
            _appendChatMessage(msg);
            break;
    }
}

// ── WebRTC 피어 연결 ─────────────────────────────────────────────────────────

function _makePeerConnection(remoteName) {
    const pc = new RTCPeerConnection(VOICE_ICE);
    voiceState.peers[remoteName] = { pc, pendingIce: [] };

    voiceState.localStream.getTracks().forEach(t => pc.addTrack(t, voiceState.localStream));

    pc.onicecandidate = (e) => {
        if (e.candidate && voiceState.ws?.readyState === WebSocket.OPEN) {
            voiceState.ws.send(JSON.stringify({
                type: 'ice', to: remoteName, candidate: e.candidate,
            }));
        }
    };

    pc.ontrack = (e) => {
        _setRemoteAudio(remoteName, e.streams[0]);
        _setupRemoteSpeaking(remoteName, e.streams[0]);
    };

    pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
            _closePeer(remoteName);
        }
    };

    return pc;
}

async function _createOffer(toUser) {
    const pc     = _makePeerConnection(toUser);
    const offer  = await pc.createOffer();
    await pc.setLocalDescription(offer);
    voiceState.ws?.send(JSON.stringify({ type: 'offer', to: toUser, sdp: pc.localDescription }));
}

async function _handleOffer(fromUser, sdp) {
    const pc = _makePeerConnection(fromUser);
    await pc.setRemoteDescription(new RTCSessionDescription(sdp));

    // 버퍼된 ICE 처리
    for (const c of voiceState.peers[fromUser].pendingIce) {
        try { await pc.addIceCandidate(new RTCIceCandidate(c)); } catch (_) {}
    }
    voiceState.peers[fromUser].pendingIce = [];

    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);
    voiceState.ws?.send(JSON.stringify({ type: 'answer', to: fromUser, sdp: pc.localDescription }));
}

async function _handleAnswer(fromUser, sdp) {
    const peer = voiceState.peers[fromUser];
    if (!peer) return;
    await peer.pc.setRemoteDescription(new RTCSessionDescription(sdp));

    for (const c of peer.pendingIce) {
        try { await peer.pc.addIceCandidate(new RTCIceCandidate(c)); } catch (_) {}
    }
    peer.pendingIce = [];
}

async function _handleIce(fromUser, candidate) {
    const peer = voiceState.peers[fromUser];
    if (!peer) return;
    if (peer.pc.remoteDescription) {
        try { await peer.pc.addIceCandidate(new RTCIceCandidate(candidate)); } catch (_) {}
    } else {
        peer.pendingIce.push(candidate);
    }
}

function _closePeer(userName) {
    const peer = voiceState.peers[userName];
    if (peer) { peer.pc.close(); delete voiceState.peers[userName]; }
    document.getElementById(`voice-audio-${CSS.escape(userName)}`)?.remove();
    delete voiceState.speakingMap[userName];
}

function _setRemoteAudio(userName, stream) {
    let el = document.getElementById(`voice-audio-${userName}`);
    if (!el) {
        el = document.createElement('audio');
        el.id       = `voice-audio-${userName}`;
        el.autoplay = true;
        document.body.appendChild(el);
    }
    el.srcObject = stream;
    // 저장된 볼륨 적용
    const vol = voiceState.volumes[userName] ?? 100;
    el.volume = Math.min(vol / 100, 1.0);
    el.muted  = voiceState.isDeafened;
}

// ── 말하기 감지 (AudioContext) ───────────────────────────────────────────────

function _detectSpeaking(stream, onSpeakChange) {
    try {
        const ctx      = new AudioContext();
        const src      = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        src.connect(analyser);
        const data     = new Uint8Array(analyser.frequencyBinCount);
        let speaking   = false;

        const tick = () => {
            analyser.getByteFrequencyData(data);
            const avg    = data.reduce((a, b) => a + b, 0) / data.length;
            const nowSpk = avg > 8;
            if (nowSpk !== speaking) { speaking = nowSpk; onSpeakChange(nowSpk); }
            voiceState._speakTimers.push(requestAnimationFrame(tick));
        };
        tick();
        return () => ctx.close();
    } catch (_) {
        return () => {};
    }
}

function _setupLocalSpeaking() {
    _detectSpeaking(voiceState.localStream, (spk) => {
        voiceState.speakingMap[voiceState.userName] = spk && !voiceState.isMuted;
        _updateSpeakingUI(voiceState.userName);
    });
}

function _setupRemoteSpeaking(remoteName, stream) {
    _detectSpeaking(stream, (spk) => {
        voiceState.speakingMap[remoteName] = spk;
        _updateSpeakingUI(remoteName);
    });
}

function _updateSpeakingUI(userName) {
    const card = document.querySelector(`.voice-member-card[data-user="${CSS.escape(userName)}"]`);
    if (!card) return;
    const spk = voiceState.speakingMap[userName];
    card.classList.toggle('speaking', !!spk);
}

// ── 방 내부 UI ───────────────────────────────────────────────────────────────

function _renderInRoom(container, otherMembers) {
    if (!container) return;

    // 현재 멤버 목록 (나 포함)
    const allMembers = [voiceState.userName, ...(otherMembers || Object.keys(voiceState.peers))];
    const unique     = [...new Set(allMembers)];

    container.innerHTML = `
<div class="voice-room-view">
    <div class="voice-room-topbar">
        <span class="voice-room-title">🔊 ${escapeHtml(voiceState.roomName || '')}</span>
        <button class="voice-leave-btn" onclick="leaveVoiceRoom()">나가기</button>
    </div>

    <div class="voice-members-grid" id="voice-members-grid">
        ${unique.map(m => _memberCardHtml(m)).join('')}
    </div>

    <div class="voice-controls">
        <button class="voice-mute-btn ${voiceState.isMuted ? 'muted' : ''}" id="voice-mute-btn"
            onclick="toggleVoiceMute()">
            ${voiceState.isMuted ? '🔇 마이크 켜기' : '🎤 마이크 끄기'}
        </button>
        <button class="voice-deafen-btn ${voiceState.isDeafened ? 'deafened' : ''}" id="voice-deafen-btn"
            onclick="toggleVoiceDeafen()">
            ${voiceState.isDeafened ? '🔈 스피커 켜기' : '🔊 스피커 끄기'}
        </button>
    </div>

    <div class="voice-chat-panel">
        <div class="voice-chat-log" id="voice-chat-log">
            ${voiceState.messages.map(m => _chatMsgHtml(m)).join('')}
        </div>
        <form class="voice-chat-form" onsubmit="sendVoiceChat(event)">
            <input type="text" id="voice-chat-input"
                class="voice-chat-input"
                placeholder="채팅 입력... (Enter)"
                maxlength="500"
                autocomplete="off">
            <button type="submit" class="voice-chat-send">전송</button>
        </form>
    </div>
</div>`;

    // 채팅 로그 맨 아래로 스크롤
    requestAnimationFrame(() => {
        const log = document.getElementById('voice-chat-log');
        if (log) log.scrollTop = log.scrollHeight;
    });
}

function _memberCardHtml(userName) {
    const isMe  = userName === voiceState.userName;
    const spk   = voiceState.speakingMap[userName] || false;
    const label = isMe ? `${escapeHtml(userName)} (나)` : escapeHtml(userName);
    const vol   = voiceState.volumes[userName] ?? 100;
    const volSlider = isMe ? '' : `
        <div class="voice-vol-row">
            <span class="voice-vol-icon">🔊</span>
            <input type="range" class="voice-vol-slider"
                min="0" max="200" value="${vol}"
                oninput="setUserVolume('${escapeHtml(userName)}', this.value)"
                title="${vol}%">
            <span class="voice-vol-val" id="voice-vol-val-${escapeHtml(userName)}">${vol}%</span>
        </div>`;
    return `<div class="voice-member-card${spk ? ' speaking' : ''}" data-user="${escapeHtml(userName)}">
        <div class="voice-avatar">${escapeHtml(userName.slice(0, 2))}</div>
        <div class="voice-member-name">${label}</div>
        ${volSlider}
    </div>`;
}

function setUserVolume(userName, value) {
    const vol = parseInt(value, 10);
    voiceState.volumes[userName] = vol;
    // audio 엘리먼트 볼륨 적용 (0~1 범위, 최대 2.0배)
    const audio = document.getElementById(`voice-audio-${userName}`);
    if (audio) audio.volume = Math.min(vol / 100, 1.0);
    // 표시값 업데이트
    const valEl = document.getElementById(`voice-vol-val-${userName}`);
    if (valEl) valEl.textContent = `${vol}%`;
}

// ── 컨트롤 ──────────────────────────────────────────────────────────────────

function toggleVoiceMute() {
    voiceState.isMuted = !voiceState.isMuted;
    voiceState.localStream?.getAudioTracks().forEach(t => {
        t.enabled = !voiceState.isMuted;
    });
    const btn = document.getElementById('voice-mute-btn');
    if (btn) {
        btn.textContent = voiceState.isMuted ? '🔇 마이크 켜기' : '🎤 마이크 끄기';
        btn.classList.toggle('muted', voiceState.isMuted);
    }
    if (voiceState.isMuted) {
        voiceState.speakingMap[voiceState.userName] = false;
        _updateSpeakingUI(voiceState.userName);
    }
}

function toggleVoiceDeafen() {
    voiceState.isDeafened = !voiceState.isDeafened;
    // 모든 원격 오디오 엘리먼트 음소거/해제
    document.querySelectorAll('[id^="voice-audio-"]').forEach(el => {
        el.muted = voiceState.isDeafened;
    });
    const btn = document.getElementById('voice-deafen-btn');
    if (btn) {
        btn.textContent = voiceState.isDeafened ? '🔈 스피커 켜기' : '🔊 스피커 끄기';
        btn.classList.toggle('deafened', voiceState.isDeafened);
    }
}

// ── 채팅 ────────────────────────────────────────────────────────────────────

function _chatMsgHtml(msg) {
    const isMe = msg.from === voiceState.userName;
    const time = new Date(msg.ts * 1000).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
    return `<div class="voice-chat-msg${isMe ? ' me' : ''}">
        <span class="voice-chat-name">${escapeHtml(msg.from)}</span>
        <span class="voice-chat-text">${escapeHtml(msg.text)}</span>
        <span class="voice-chat-time">${time}</span>
    </div>`;
}

function _appendChatMessage(msg) {
    const log = document.getElementById('voice-chat-log');
    if (!log) return;
    log.insertAdjacentHTML('beforeend', _chatMsgHtml(msg));
    log.scrollTop = log.scrollHeight;
}

function sendVoiceChat(e) {
    e.preventDefault();
    const input = document.getElementById('voice-chat-input');
    const text = (input?.value || '').trim();
    if (!text || !voiceState.ws || voiceState.ws.readyState !== WebSocket.OPEN) return;
    voiceState.ws.send(JSON.stringify({ type: 'chat', text }));
    input.value = '';
}

function leaveVoiceRoom() {
    // 피어 연결 모두 닫기
    for (const [, peer] of Object.entries(voiceState.peers)) {
        try { peer.pc.close(); } catch (_) {}
    }
    voiceState.peers = {};

    // 오디오 스트림 중단
    voiceState.localStream?.getTracks().forEach(t => t.stop());
    voiceState.localStream = null;

    // WebSocket 닫기
    voiceState.ws?.close();
    voiceState.ws = null;

    // 오디오 엘리먼트 제거
    document.querySelectorAll('[id^="voice-audio-"]').forEach(el => el.remove());

    // rAF 정리
    voiceState._speakTimers.forEach(id => cancelAnimationFrame(id));
    voiceState._speakTimers = [];

    voiceState.inRoom      = false;
    voiceState.roomId      = null;
    voiceState.roomName    = null;
    voiceState.speakingMap = {};
    voiceState.volumes     = {};
    voiceState.messages    = [];
    voiceState.isMuted     = false;
    voiceState.isDeafened  = false;

    _startRoomPoll();
    renderVoiceTab();
}

// ── 페이지 로드 후 voice 탭 활성화 보정 ──────────────────────────────────────
// app.js IIFE가 실행될 때 voice.js가 아직 로드되지 않아 initVoiceTab()이 미호출되는 문제 방어
window.addEventListener('load', () => {
    if (document.getElementById('tab-voice')?.classList.contains('active')) {
        initVoiceTab();
    }
});
