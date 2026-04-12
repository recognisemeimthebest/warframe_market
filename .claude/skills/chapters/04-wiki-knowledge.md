# Ch.04 — 위키 지식 가이드

## 데이터 소스

### Warframe Wiki (Fandom API)
- **엔드포인트**: `https://warframe.fandom.com/api.php`
- **용도**: 워프레임/무기 상세, 게임 메카닉, 파밍 위치
- **방식**: `action=parse&page={PageName}&prop=text&format=json`

### Warframe Public Export
- **엔드포인트**: `http://content.warframe.com/PublicExport/`
- **용도**: 공식 게임 데이터 (DE 제공)
- **갱신**: 게임 업데이트마다 변경됨

### warframe-items (커뮤니티)
- **GitHub**: `WFCD/warframe-items`
- **용도**: 아이템 정보 통합, 드롭률, 이미지

## RAG 구조
```
질문 → 키워드 추출 → 위키 캐시 검색 → 관련 문서 선택
  → LLM 프롬프트에 컨텍스트로 주입 → 답변 생성
```

## 캐싱 전략
- 위키 페이지를 로컬 JSON으로 저장
- 갱신 주기: 일 1회 (게임 업데이트 확인)
- 자주 조회되는 페이지는 메모리 캐시 유지

## 주의사항
- 위키 HTML → 텍스트 변환 시 테이블/인포박스 파싱 필요
- 위키 데이터가 항상 최신은 아님 → "위키 기준" 면책 표기
- LLM 컨텍스트 윈도우 제한 → 관련 부분만 잘라서 주입
- Fandom API도 rate limit 있음 → 캐시 우선
