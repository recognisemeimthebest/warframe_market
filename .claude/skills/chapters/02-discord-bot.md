# Ch.02 — Discord 봇 가이드

## 기술 스택
- **라이브러리**: discord.py 2.x
- **패턴**: 비동기 (async/await)
- **봇 타입**: commands.Bot (슬래시 커맨드 + 메시지 이벤트 혼합)

## 기본 구조
```python
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"봇 온라인: {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    # 자연어 처리 → LLM으로 전달
    await bot.process_commands(message)
```

## 주의사항
- 봇 토큰은 **절대 코드에 하드코딩 금지** → `.env` + `os.environ`
- `message.content` 접근하려면 `intents.message_content = True` 필수
- LLM 추론은 느리므로 `async with message.channel.typing():` 으로 타이핑 표시
- 에러 시 사용자에게 친절한 메시지 + 로깅
- rate limit 주의: 봇도 Discord API 제한 있음
