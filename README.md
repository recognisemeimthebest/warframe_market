# 오디스 프라임 — 워프레임 마켓 챗봇

워프레임 아이템 시세 조회, 급등 알림, 게임 정보 대화를 제공하는 웹 챗봇.
Raspberry Pi 5에서 Gemma 4 E2B (Ollama) + FastAPI로 24시간 구동됩니다.

## 주요 기능

### 시세 조회
- 한국어/영어로 아이템 검색 (예: "레아 프라임", "Rhino Prime")
- 실시간 최저가, 평균가, 48시간 가격 변동 표시
- AI 챗봇과 자연어 대화로 시세 질문 가능

### 시세 감시 (Watchlist)
- 아이템에 목표 가격을 설정하면 도달 시 자동 알림
- 한국어 검색 시 후보 자동 추천 (disambiguation)
- 등록 즉시 현재가 표시

### 급등 알림
- 전체 마켓 아이템의 가격 급등/급락을 자동 감지
- 웹 푸시 알림으로 실시간 전달

### 거래소
- 판매/구매 주문 목록 실시간 조회
- 온라인 상태인 거래자만 필터링

### 월드 상태
- 시터스/포츈아/데이모스 시간대 표시
- 균열 (Fissure), 침공 (Invasion), 중재 (Arbitration) 실시간 정보
- 원하는 조건에 맞는 알림 설정

### 파밍 가이드
- 아이템별 파밍 위치 및 방법 안내
- 위키 데이터 기반 자동 생성

### 모딩 공유
- 무기/프레임 모딩 빌드를 이미지로 공유
- 커뮤니티 평가 (좋아요/싫어요)

## 기술 스택

| 구성요소 | 기술 |
|----------|------|
| 백엔드 | Python 3.11+, FastAPI, uvicorn, WebSocket |
| LLM | Gemma 4 E2B via Ollama |
| 프론트엔드 | HTML / CSS / JS (프레임워크 없음) |
| 시세 데이터 | warframe.market API |
| 게임 데이터 | Warframe Wiki (Fandom API) |
| 하드웨어 | Raspberry Pi 5 (8GB RAM) |

## 설치 및 실행

```bash
git clone https://github.com/recognisemeimthebest/warframe_market.git
cd warframe_market

cp .env.example .env
pip install -r requirements.txt

# Ollama 설치 후
ollama pull gemma4:e2b

python main.py
# → http://localhost:8000
```

## 모바일 앱 (PWA)

브라우저에서 접속 후 설정(톱니바퀴) → **홈 화면에 추가** 버튼으로 앱처럼 설치할 수 있습니다.
주소창 없이 전체화면으로 동작하며, 서버 업데이트 시 자동 반영됩니다.

## 아키텍처

```
┌──────────────────────────────────────────┐
│           Raspberry Pi 5 (8GB)           │
│                                          │
│  FastAPI ←──→ Market Monitor             │
│  + WebSocket    (polling, alerts)        │
│       ↕                                  │
│  Gemma 4 E2B (Ollama)                   │
└──────────┬───────────────────────────────┘
           │
     ┌─────┼─────────────┐
     ▼     ▼             ▼
  브라우저  warframe      Warframe
  (PWA)   .market API    Wiki API
```

## 라이선스

이 프로젝트는 개인 학습 및 소규모 커뮤니티 용도로 제작되었습니다.
워프레임 및 관련 상표는 Digital Extremes의 자산입니다.
