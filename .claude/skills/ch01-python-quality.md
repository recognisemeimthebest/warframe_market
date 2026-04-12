# Python 품질 체크리스트

> PostToolUse 훅이 코드 작성/수정 후 이 기준으로 리마인더를 출력한다.

---

## 1. 에러 처리

### 필수 try-except 대상
- HTTP/API 호출 (requests, aiohttp, httpx)
- 파일 I/O (open, json.load/dump)
- 외부 프로세스 (subprocess, Ollama 호출)
- JSON 파싱 (사용자 입력, API 응답)

### 패턴
```python
# 좋은 예
try:
    response = await client.get(url, timeout=10.0)
    response.raise_for_status()
    data = response.json()
except httpx.TimeoutException:
    logger.warning(f"타임아웃: {url}")
    return cached_data  # 폴백
except httpx.HTTPStatusError as e:
    logger.error(f"HTTP {e.response.status_code}: {url}")
    return None
```

## 2. 보안

### 자격증명 관리
- 토큰/키는 **`.env` 파일** + `python-dotenv`
- `.env`는 **반드시 `.gitignore`에 포함**
- 코드에 하드코딩 절대 금지

### 입력 검증
- Discord 메시지 내용: 길이 제한 (2000자), 특수문자 이스케이프
- API 응답: 스키마 검증, null 체크
- 파일 경로: path traversal 방지

## 3. async 패턴

### 금지 패턴
```python
# 나쁜 예 — async 안에서 동기 블로킹
async def handle(message):
    data = requests.get(url)      # 블로킹!
    time.sleep(5)                  # 블로킹!

# 좋은 예
async def handle(message):
    async with httpx.AsyncClient() as client:
        data = await client.get(url)
    await asyncio.sleep(5)
```

### rate limit 패턴
```python
semaphore = asyncio.Semaphore(3)  # 초당 3회 제한

async def rate_limited_request(url):
    async with semaphore:
        result = await client.get(url)
        await asyncio.sleep(0.34)  # 1/3초 간격
        return result
```

## 4. 로깅
- `print()` 대신 `logging` 모듈 사용
- 레벨: DEBUG(개발) / INFO(운영) / WARNING(경고) / ERROR(에러)
- 배포 시 DEBUG 비활성화 (Pi 성능)

## 5. 프로젝트 특화 규칙
- warframe.market API: 초당 3회 제한 필수
- Ollama 호출: timeout 60초 (Pi에서 느림)
- Discord 메시지: 2000자 제한 → 긴 응답은 분할 또는 embed
- 동시 LLM 추론: 1개로 제한 (asyncio.Lock)
