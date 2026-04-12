# Ch.01 — LLM / Ollama 가이드

## 모델 정보
- **모델**: Gemma 4 E2B (Google DeepMind, 2026-04-02 출시)
- **양자화**: Q8 기본, Q4_K_M 폴백
- **서빙**: Ollama (`localhost:11434`)
- **하드웨어**: Raspberry Pi 5 (8GB RAM)

## Ollama API 사용법

### 기본 호출
```python
import httpx

async def generate(prompt: str, system: str = "") -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "gemma4:e2b",
                "prompt": prompt,
                "system": system,
                "stream": False,
            }
        )
        return response.json()["response"]
```

### 채팅 형식 (대화 히스토리 유지)
```python
async def chat(messages: list[dict]) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "gemma4:e2b",
                "messages": messages,
                "stream": False,
            }
        )
        return response.json()["message"]["content"]
```

## 주의사항
- Pi 5에서 첫 토큰 3-4초, 생성 8-12 t/s → **반드시 timeout 설정**
- Q8 기준 메모리 ~2.5-3GB → 동시 추론 1개로 제한
- 시스템 프롬프트에서 워프레임 전용 역할 명시 필수
- 한글 ↔ 영문 아이템명 매핑은 LLM에 의존하지 말고 별도 사전 사용
