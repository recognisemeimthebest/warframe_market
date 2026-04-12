#!/bin/bash
# =============================================================================
# PostToolUse Hook — 자동 수정 기록 + 코드 리뷰 + 오류 분기
# 1) 모든 Write/Edit를 change-log.md에 자동 기록
# 2) 코드 품질·보안·에러처리 체크
# 3) 오류 수에 따라 즉시 수정 또는 전문 에이전트 호출 분기
# =============================================================================

set -uo pipefail

SHARED_DIR=".claude/hooks/shared"
CHANGE_LOG="$SHARED_DIR/change-log.md"
INPUT=$(cat)

# tool_name 추출
TOOL_NAME=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('tool_name', ''))
except:
    print('')
" 2>/dev/null || echo "")

if [ -z "$TOOL_NAME" ]; then
    TOOL_NAME=$(echo "$INPUT" | python -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('tool_name', ''))
except:
    print('')
" 2>/dev/null || echo "")
fi

# Write, Edit, Bash만 분석 대상
case "$TOOL_NAME" in
    Write|Edit|Bash) ;;
    *) exit 0 ;;
esac

# 필요한 필드 추출
FIELDS=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    ti = data.get('tool_input', {})
    print(ti.get('file_path', ti.get('command', '')))
    print('---SPLIT---')
    print(ti.get('content', ti.get('new_string', ti.get('command', ''))))
except:
    print('')
    print('---SPLIT---')
    print('')
" 2>/dev/null || echo "")

FILE_PATH=$(echo "$FIELDS" | sed -n '1p')
CONTENT=$(echo "$FIELDS" | sed '1,/---SPLIT---/d')

# 분석할 내용이 없으면 종료
if [ -z "$CONTENT" ]; then
    exit 0
fi

# =============================================================================
# 0. 수정 기록 자동 로깅
# =============================================================================
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "unknown")

if [ "$TOOL_NAME" = "Write" ] || [ "$TOOL_NAME" = "Edit" ]; then
    # change-log.md가 없으면 생성
    if [ ! -f "$CHANGE_LOG" ]; then
        mkdir -p "$SHARED_DIR"
        echo "# 수정 기록 (Change Log)" > "$CHANGE_LOG"
        echo "" >> "$CHANGE_LOG"
    fi

    # 변경 내용 요약 (첫 80자)
    CONTENT_PREVIEW=$(echo "$CONTENT" | head -3 | tr '\n' ' ' | cut -c1-80)

    echo "| ${TIMESTAMP} | \`${TOOL_NAME}\` | \`${FILE_PATH}\` | \`${CONTENT_PREVIEW}...\` |" >> "$CHANGE_LOG"
fi

REMINDERS=""
ISSUE_COUNT=0

# 파일 확장자 추출
EXT=""
if [ -n "$FILE_PATH" ]; then
    EXT="${FILE_PATH##*.}"
fi

# =============================================================================
# 1. 위험한 작업 감지
# =============================================================================

# --- 파괴적 명령어 ---
if echo "$CONTENT" | grep -qiE 'rm\s+-rf|rmdir|DROP\s+TABLE|DELETE\s+FROM|truncate|format'; then
    REMINDERS+="  - 파괴적인 작업(삭제/포맷) 감지. 대상이 맞는지, 백업은 했는지 확인\n"
    ISSUE_COUNT=$((ISSUE_COUNT + 1))
fi

# --- 하드코딩된 자격증명 ---
if echo "$CONTENT" | grep -qiE 'password\s*=\s*"|api_key\s*=\s*"|secret\s*=\s*"|token\s*=\s*"|DISCORD_TOKEN\s*=\s*"'; then
    REMINDERS+="  - 비밀번호/API키/토큰이 코드에 하드코딩됨. 환경변수(.env)로 분리할 것\n"
    ISSUE_COUNT=$((ISSUE_COUNT + 1))
fi

# --- .env 파일 직접 수정 ---
if echo "$FILE_PATH" | grep -qiE '\.env$'; then
    REMINDERS+="  - .env 파일 수정됨. .gitignore에 .env가 포함되어 있는지 확인할 것\n"
    ISSUE_COUNT=$((ISSUE_COUNT + 1))
fi

# --- git force push ---
if echo "$CONTENT" | grep -qiE 'git\s+push.*--force|git\s+push.*-f\b|git\s+reset\s+--hard'; then
    REMINDERS+="  - force push/hard reset은 되돌리기 어려움. 정말 필요한 작업인지 확인\n"
    ISSUE_COUNT=$((ISSUE_COUNT + 1))
fi

# =============================================================================
# 2. Python 에러 처리 확인
# =============================================================================
if [ "$EXT" = "py" ]; then

    # --- API 호출에 try-except 없음 ---
    if echo "$CONTENT" | grep -qiE 'requests\.|aiohttp\.|httpx\.|fetch\(|urlopen'; then
        if ! echo "$CONTENT" | grep -qE 'try:|except'; then
            REMINDERS+="  - API/HTTP 호출에 try-except 없음. 네트워크 에러 시 크래시 가능\n"
            ISSUE_COUNT=$((ISSUE_COUNT + 1))
        fi
    fi

    # --- 파일 I/O에 에러 처리 없음 ---
    if echo "$CONTENT" | grep -qE 'open\s*\(|json\.load|json\.dump|with open'; then
        if ! echo "$CONTENT" | grep -qE 'try:|except|Path.*exists'; then
            REMINDERS+="  - 파일 I/O에 에러 처리 확인. 파일이 없거나 권한 문제 시 대비 필요\n"
            ISSUE_COUNT=$((ISSUE_COUNT + 1))
        fi
    fi

    # --- async 함수에서 블로킹 호출 ---
    if echo "$CONTENT" | grep -qE 'async\s+def'; then
        if echo "$CONTENT" | grep -qE 'requests\.get|requests\.post|time\.sleep\('; then
            REMINDERS+="  - async 함수 안에서 동기 블로킹 호출(requests/time.sleep) 감지. aiohttp/asyncio.sleep 사용 권장\n"
            ISSUE_COUNT=$((ISSUE_COUNT + 1))
        fi
    fi

    # --- 나눗셈 (0 나누기 위험) ---
    if echo "$CONTENT" | grep -qE 'price.*/' | grep -qivE 'if.*==\s*0|if.*!=\s*0|or\s+1|max\('; then
        REMINDERS+="  - 가격 관련 나눗셈 감지. 분모가 0일 수 있는 경우(데이터 없을 때) 체크\n"
        ISSUE_COUNT=$((ISSUE_COUNT + 1))
    fi

    # --- 무한 루프 ---
    if echo "$CONTENT" | grep -qE 'while\s+(True|1):'; then
        if ! echo "$CONTENT" | grep -qE 'break|await.*sleep|asyncio\.sleep|time\.sleep'; then
            REMINDERS+="  - while True 루프에 break/sleep 없음. CPU 100% 또는 행업 가능\n"
            ISSUE_COUNT=$((ISSUE_COUNT + 1))
        fi
    fi
fi

# =============================================================================
# 3. 보안 체크
# =============================================================================

# --- SQL 인젝션 ---
if echo "$CONTENT" | grep -qiE "execute\s*\(\s*f\"|format\s*\(.*SELECT|format\s*\(.*INSERT|\+.*input.*SELECT"; then
    REMINDERS+="  - SQL 쿼리에 f-string/format 사용 감지. parameterized query로 변경 권장\n"
    ISSUE_COUNT=$((ISSUE_COUNT + 1))
fi

# --- 입력값 검증 없는 외부 데이터 ---
if echo "$CONTENT" | grep -qiE 'message\.content|interaction\.data|request\.(get|post|json)'; then
    if ! echo "$CONTENT" | grep -qiE 'strip\(|len\(|validate|sanitize|[:alnum:]'; then
        REMINDERS+="  - 외부 입력(Discord 메시지/HTTP 요청) 사용 감지. 입력값 검증/길이 제한 확인\n"
        ISSUE_COUNT=$((ISSUE_COUNT + 1))
    fi
fi

# --- 평문 통신 ---
if echo "$CONTENT" | grep -qiE 'http://[^l]|http://[^1]'; then
    REMINDERS+="  - HTTP 평문 통신 감지. 민감한 데이터가 있으면 HTTPS 사용 권장\n"
    ISSUE_COUNT=$((ISSUE_COUNT + 1))
fi

# --- 디버그 코드 잔존 ---
if echo "$CONTENT" | grep -qiE 'print\s*\(\s*["\x27]debug|#\s*TODO.*remove|#\s*FIXME|#\s*HACK|breakpoint\(\)'; then
    REMINDERS+="  - 디버그 코드/TODO 잔존 감지. 배포 전에 정리 필요\n"
    ISSUE_COUNT=$((ISSUE_COUNT + 1))
fi

# =============================================================================
# 4. 프로젝트 특화 체크
# =============================================================================

# --- warframe.market API 레이트 리밋 ---
if echo "$CONTENT" | grep -qiE 'warframe\.market|api\.warframe'; then
    if ! echo "$CONTENT" | grep -qiE 'sleep|rate.*limit|throttle|semaphore|asyncio\.sleep'; then
        REMINDERS+="  - warframe.market API 호출 감지. 초당 3회 제한 준수하는지 확인\n"
        ISSUE_COUNT=$((ISSUE_COUNT + 1))
    fi
fi

# --- Ollama 타임아웃 ---
if echo "$CONTENT" | grep -qiE 'ollama|localhost:11434|generate\s*\(|chat\s*\('; then
    if ! echo "$CONTENT" | grep -qiE 'timeout|asyncio\.wait_for'; then
        REMINDERS+="  - Ollama API 호출에 타임아웃 설정 확인. Pi에서 추론이 느릴 수 있음\n"
        ISSUE_COUNT=$((ISSUE_COUNT + 1))
    fi
fi

# --- Discord 봇 토큰 노출 ---
if echo "$CONTENT" | grep -qiE '[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27}'; then
    REMINDERS+="  - Discord 봇 토큰으로 보이는 문자열 감지. 코드에 절대 하드코딩하지 말 것\n"
    ISSUE_COUNT=$((ISSUE_COUNT + 1))
fi

# =============================================================================
# 5. Bash 명령어 체크
# =============================================================================
if [ "$TOOL_NAME" = "Bash" ]; then
    if echo "$CONTENT" | grep -qiE 'rm\s+-rf\s+/|rm\s+-rf\s+\*|dd\s+if=|mkfs'; then
        REMINDERS+="  - 매우 위험한 명령어. 경로를 한 번 더 확인할 것\n"
        ISSUE_COUNT=$((ISSUE_COUNT + 1))
    fi

    if echo "$CONTENT" | grep -qiE 'pip install(?!.*-r)(?!.*requirements)'; then
        if ! echo "$CONTENT" | grep -qiE 'venv|virtualenv|conda'; then
            REMINDERS+="  - 글로벌 pip install 감지. 가상환경(venv) 안에서 실행하는 게 맞는지 확인\n"
            ISSUE_COUNT=$((ISSUE_COUNT + 1))
        fi
    fi
fi

# =============================================================================
# 6. 오류 수 기반 분기 — 적으면 즉시 수정, 많으면 전문 에이전트 호출
# =============================================================================
ERROR_ACTION=""

if [ "$ISSUE_COUNT" -gt 0 ] && [ "$ISSUE_COUNT" -le 2 ]; then
    ERROR_ACTION="\n[자동 수정 권장] 발견된 이슈 ${ISSUE_COUNT}개 — 경미한 수준입니다. 위 항목을 지금 바로 수정하세요. 별도 에이전트 호출 불필요."
elif [ "$ISSUE_COUNT" -ge 3 ]; then
    ERROR_ACTION="\n[전문 에이전트 호출 권장] 발견된 이슈 ${ISSUE_COUNT}개 — 이슈가 많습니다.\n  → \`code-review-auditor\` 에이전트를 호출하여 전체 파일을 정밀 검토하세요.\n  → 파일: \`${FILE_PATH}\`\n  → 사용법: Agent tool로 code-review-auditor 호출 → 해당 파일 리뷰 요청"
fi

# =============================================================================
# 7. 수정 기록 로그 안내
# =============================================================================
LOG_NOTICE=""
if [ "$TOOL_NAME" = "Write" ] || [ "$TOOL_NAME" = "Edit" ]; then
    LOG_NOTICE="\n[수정 기록] \`${FILE_PATH}\` → \`${CHANGE_LOG}\`에 자동 기록됨"
fi

# =============================================================================
# 8. 체크리스트·맥락노트 업데이트 (필수)
# =============================================================================
DOC_REMINDER=""

# 문서/설정 파일 자체 수정은 리마인더 불필요
if ! echo "$FILE_PATH" | grep -qiE 'context-notes|checklist|change-log|ORCHESTRATION|PROJECT_SPEC'; then
    if [ "$TOOL_NAME" = "Write" ] || [ "$TOOL_NAME" = "Edit" ]; then
        DOC_REMINDER="\n[필수] 이 지시가 끝나면 반드시 아래를 **하나씩** 수행하세요 (한번에 몰아서 하지 말 것):\n  1. 먼저 \`$SHARED_DIR/checklist.md\`를 Edit으로 열어서:\n     - 방금 완료한 항목 **1개만** [x] 체크\n     - 다음에 할 작업이 뭔지 정리\n  2. 그 다음 \`$SHARED_DIR/context-notes.md\`를 Edit으로 열어서:\n     - 방금 내린 결정과 그 이유를 기록\n  ⚠ 체크리스트는 한 번에 여러 항목을 체크하지 마세요. 하나 끝내고 → 체크 → 다음 작업 시작.\n  이 업데이트를 건너뛰면 새 세션에서 AI가 맥락을 잃습니다."
    fi
fi

# =============================================================================
# 9. 출력
# =============================================================================
ALL_CONTEXT=""

if [ -n "$REMINDERS" ]; then
    ALL_CONTEXT+="[코드 리뷰] 발견된 이슈: ${ISSUE_COUNT}개\n${REMINDERS}"
fi

if [ -n "$ERROR_ACTION" ]; then
    ALL_CONTEXT+="$ERROR_ACTION"
fi

if [ -n "$LOG_NOTICE" ]; then
    ALL_CONTEXT+="$LOG_NOTICE"
fi

if [ -n "$DOC_REMINDER" ]; then
    ALL_CONTEXT+="$DOC_REMINDER"
fi

if [ -n "$ALL_CONTEXT" ]; then
    cat <<HOOKJSON
{
  "hookSpecificOutput": {
    "additionalContext": "${ALL_CONTEXT}"
  }
}
HOOKJSON
else
    echo '{}'
fi

exit 0
