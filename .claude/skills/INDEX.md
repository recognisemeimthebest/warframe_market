# 스킬 매뉴얼 목차

> 필요한 챕터만 Read 도구로 로드하세요. 전체를 한번에 읽지 마세요.
> UserPromptSubmit 훅이 키워드를 감지하여 관련 챕터를 자동 주입합니다.

## 도메인 스킬 (기술 영역별)

| # | 챕터 | 파일 | 트리거 키워드 |
|---|------|------|--------------|
| 01 | LLM / Ollama | `chapters/01-llm-ollama.md` | gemma, ollama, llm, 모델, 프롬프트, 추론, 토큰, 양자화 |
| 02 | Discord 봇 | `chapters/02-discord-bot.md` | discord, 디스코드, 봇, 슬래시, 커맨드, 이벤트, 채널 |
| 03 | 마켓 시세 | `chapters/03-market-price.md` | market, 마켓, 시세, 가격, 폴링, 알림, 급등, 거래 |
| 04 | 위키 지식 | `chapters/04-wiki-knowledge.md` | wiki, 위키, 지식, rag, fandom, 파밍, 캐시 |
| 05 | 라즈베리파이 배포 | `chapters/05-raspberry-deploy.md` | raspberry, 라즈베리, pi, 배포, systemd, 모니터링 |

## 메타 스킬 (프로세스/품질)

| 챕터 | 파일 | 용도 |
|------|------|------|
| Python 품질 | `ch01-python-quality.md` | 에러 처리, 보안, async 패턴, 코드 품질 기준 |
| 스킬 활성화 규칙 | `ch02-skill-activation.md` | 키워드·패턴·경로·코드 감지 규칙 상세 |

## 자동 로드 규칙
- 사용자 지시에서 키워드가 감지되면 → 해당 챕터가 Claude 컨텍스트에 자동 주입
- PostToolUse에서 보안/에러 이슈 감지 → `ch01-python-quality.md` 참고 안내
- 수동으로 읽으려면: `.claude/skills/chapters/XX-name.md` 또는 `.claude/skills/chXX-name.md`
