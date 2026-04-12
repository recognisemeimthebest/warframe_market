# 스킬 활성화 규칙표

> UserPromptSubmit 훅과 PostToolUse 훅이 이 규칙에 따라 스킬 챕터를 자동 로드한다.

---

## 1. 키워드 감지 → 스킬 활성화

사용자 프롬프트에서 아래 키워드가 감지되면 해당 스킬 챕터를 컨텍스트에 주입한다.

### 도메인 스킬

| 스킬 | 트리거 키워드 | 챕터 파일 |
|------|-------------|-----------|
| LLM/Ollama | `gemma`, `ollama`, `llm`, `모델`, `추론`, `inference`, `프롬프트`, `prompt`, `토큰`, `token`, `양자화`, `quantiz`, `시스템.*프롬프트`, `컨텍스트.*윈도우`, `temperature`, `top_p` | `chapters/01-llm-ollama.md` |
| Discord 봇 | `discord`, `디스코드`, `봇`, `bot`, `슬래시.*커맨드`, `slash.*command`, `이벤트.*핸들`, `on_message`, `on_ready`, `채널`, `서버`, `guild`, `embed`, `interaction` | `chapters/02-discord-bot.md` |
| 마켓 시세 | `market`, `마켓`, `시세`, `가격`, `price`, `폴링`, `polling`, `알림`, `alert`, `급등`, `급락`, `거래`, `주문`, `order`, `아이템.*조회`, `warframe.market` | `chapters/03-market-price.md` |
| 위키 지식 | `wiki`, `위키`, `지식`, `knowledge`, `rag`, `fandom`, `파밍`, `빌드`, `워프레임.*정보`, `캐시`, `cache`, `임베딩`, `embedding`, `청킹`, `chunk` | `chapters/04-wiki-knowledge.md` |
| 라즈베리파이 | `raspberry`, `라즈베리`, `pi`, `배포`, `deploy`, `systemd`, `서비스`, `자동.*시작`, `모니터링`, `로그`, `성능`, `메모리`, `발열`, `쿨러` | `chapters/05-raspberry-deploy.md` |

### 메타 스킬

| 스킬 | 트리거 키워드 | 챕터 파일 |
|------|-------------|-----------|
| Python 품질 | `보안`, `security`, `에러.*처리`, `error.*handl`, `exception`, `취약`, `xss`, `injection`, `테스트`, `test`, `async`, `await`, `타입.*힌트`, `type.*hint` | `ch01-python-quality.md` |

---

## 2. 요청 패턴 감지 → 스킬 활성화

사용자 지시의 **의도 패턴**에 따라 추가 스킬을 활성화한다.

| 패턴 | 감지 키워드 | 활성화 스킬 |
|------|-----------|------------|
| 생성/구현 | `만들`, `생성`, `구현`, `추가`, `작성`, `셋업` | 해당 도메인 스킬 + Python 품질 |
| 수정/리팩토링 | `수정`, `변경`, `바꿔`, `고쳐`, `리팩토링` | 해당 도메인 스킬 + Python 품질 |
| 디버그 | `에러`, `오류`, `버그`, `안됨`, `실패`, `크래시` | Python 품질 (필수) + 해당 도메인 스킬 |
| 성능 최적화 | `느려`, `속도`, `최적화`, `성능`, `메모리` | 라즈베리파이 + 해당 도메인 스킬 |
| 보안 점검 | `보안`, `취약`, `토큰`, `노출`, `인증` | Python 품질 (필수) |

---

## 3. 파일 경로 감지 → 스킬 활성화

사용자 지시에 파일 경로가 포함되면 경로 패턴에 따라 스킬을 활성화한다.

| 경로 패턴 | 활성화 스킬 |
|----------|------------|
| `src/llm/*`, `*ollama*`, `*prompt*` | LLM/Ollama |
| `src/bot/*`, `*discord*`, `*commands*`, `*events*` | Discord 봇 |
| `src/market/*`, `*price*`, `*alert*`, `*monitor*` | 마켓 시세 |
| `src/wiki/*`, `*cache*`, `*fetcher*`, `*knowledge*` | 위키 지식 |
| `*systemd*`, `*service*`, `*deploy*`, `*raspberry*` | 라즈베리파이 |
| `*.py` (모든 Python 파일) | Python 품질 (PostToolUse 시) |
| `.env*`, `*config*`, `*settings*` | Python 품질 (보안 중점) |

---

## 4. 코드 패턴 감지 → 스킬 활성화

사용자 지시나 코드 스니펫에 아래 패턴이 포함되면 스킬을 활성화한다.

| 코드 패턴 | 활성화 스킬 |
|----------|------------|
| `import discord`, `discord.Client`, `commands.Bot`, `@bot.event` | Discord 봇 |
| `import ollama`, `ollama.chat`, `ollama.generate`, `localhost:11434` | LLM/Ollama |
| `warframe.market`, `api/v1/items`, `requests.get.*market` | 마켓 시세 |
| `fandom.com`, `api.php`, `mediawiki` | 위키 지식 |
| `async def`, `await`, `aiohttp`, `asyncio` | Python 품질 (async 섹션) |
| `try:`, `except`, `raise`, `logging` | Python 품질 (에러 처리 섹션) |
| `os.environ`, `dotenv`, `load_dotenv` | Python 품질 (보안 섹션) |

---

## 5. PostToolUse 특화 규칙

Write/Edit/Bash 실행 후 아래 조건에서 추가 리마인더를 출력한다.

| 조건 | 리마인더 내용 |
|------|-------------|
| `.py` 파일에 API 호출 + try 없음 | 에러 처리 누락 경고 |
| 하드코딩된 토큰/키 감지 | 환경변수 분리 권고 |
| async 함수에 동기 블로킹 호출 | aiohttp/asyncio.sleep 전환 권고 |
| warframe.market 호출 + rate limit 없음 | 초당 3회 제한 준수 확인 |
| Ollama 호출 + timeout 없음 | Pi 환경 타임아웃 설정 확인 |
| 평문 HTTP 통신 감지 | HTTPS 전환 권고 |
| 파괴적 명령어 (rm -rf 등) | 대상 확인 + 백업 권고 |
| 글로벌 pip install | 가상환경 확인 권고 |
