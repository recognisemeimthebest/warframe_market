# Ch.03 — 마켓 시세 가이드

## API 정보
- **베이스 URL**: `https://api.warframe.market/v1`
- **인증**: 공개 API (키 불필요)
- **레이트 리밋**: 초당 3회 (필수 준수)

## 주요 엔드포인트

| 엔드포인트 | 용도 |
|-----------|------|
| `GET /items` | 전체 아이템 목록 |
| `GET /items/{url_name}/orders` | 아이템 현재 주문 목록 |
| `GET /items/{url_name}/statistics` | 48시간/90일 시세 통계 |

## 가격 조회 흐름
1. 유저 자연어 → LLM이 아이템명 추출
2. 아이템명 → 한글/영문 매핑 사전에서 `url_name` 조회
3. `url_name` → `/items/{url_name}/orders` API 호출
4. 결과 필터링: `order_type=sell`, `status=ingame`, `platform=pc`
5. 최저가/평균가/거래량 계산 → LLM이 자연어 응답 생성

## 시세 감시 로직
```
매 5분마다:
  1. 감시 목록 아이템들의 현재가 조회
  2. 1시간 전 가격과 비교
  3. 변동률 ≥ 20% → 알림 발송
  4. 히스토리 DB에 저장
```

## 주의사항
- **초당 3회 제한** → asyncio.Semaphore 또는 sleep으로 조절
- API 응답이 느리거나 다운될 수 있음 → try/except + 캐시 폴백
- 아이템 `url_name`은 영문 소문자 + 언더스코어 (예: `rhino_prime_set`)
- 한글 아이템명 매핑 DB 별도 구축 필요 (API에 한글 없음)
