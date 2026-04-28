"""앱 수명 동안 공유하는 httpx.AsyncClient 싱글턴.

매 요청마다 새 client를 생성하면 TCP 핸드셰이크가 반복되어
커넥션 풀을 활용하지 못한다. 이 모듈로 단일 client를 재활용한다.
"""

import httpx

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """공유 httpx.AsyncClient를 반환한다. 닫혔으면 자동 재생성."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "warframe-chatbot/1.0"},
        )
    return _client


async def close_client() -> None:
    """앱 종료 시 호출하여 커넥션 풀을 정리한다."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
    _client = None
