# CLAUDE.md — 워프레임 마켓 챗봇

## 프로젝트 요약
워프레임 아이템 시세 조회 + 급등 알림 + 게임 지식 대화를 제공하는 웹 챗봇.
Raspberry Pi 5 (8GB)에서 Gemma 4 E2B (Ollama) + FastAPI로 24시간 구동.

## 기술 스택
- Python 3.11+, FastAPI, uvicorn, WebSocket
- LLM: Gemma 4 E2B via Ollama (localhost:11434)
- 프론트엔드: 순수 HTML/CSS/JS (모바일 최적화)
- 데이터: warframe.market API, Fandom Wiki API, Public Export

## 디렉토리 구조
```
src/web/       — FastAPI 앱, WebSocket, 정적 파일
src/llm/       — Ollama 연동 (client, prompt, context)
src/market/    — 시세 API, 모니터, 알림
src/wiki/      — 위키 데이터, 캐시
src/config.py  — 환경변수 로드
data/          — 캐시 데이터, 시세 히스토리
main.py        — 진입점
```

## 코딩 규칙
- async/await 전용. 동기 블로킹(requests, time.sleep) 금지.
- warframe.market API: 초당 3회 제한 — Semaphore + sleep(0.34) 필수.
- Ollama 호출: timeout 60초, 동시 추론 1개 (asyncio.Lock).
- 로깅: print() 대신 logging 모듈. 배포 시 DEBUG 비활성화.
- 환경변수: .env + python-dotenv. 코드에 토큰 하드코딩 금지.
- 프론트엔드: XSS 방지 — 사용자 입력은 반드시 escapeHtml 처리.

## 실행 방법
```bash
# 개발
cp .env.example .env
pip install -r requirements.txt
python main.py
# → http://localhost:8000

# Pi 배포
sudo systemctl start warframe-chatbot
```

## 기획서
상세 기획: `docs/PROJECT_SPEC.md`
