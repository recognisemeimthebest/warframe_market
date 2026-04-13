import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 루트
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

# .env 로드
load_dotenv(ROOT_DIR / ".env")

# Web server
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "9000"))

# warframe.market
MARKET_API_BASE = "https://api.warframe.market/v1"
MARKET_RATE_LIMIT = 3  # 초당 최대 요청 수

# 관리자
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")  # 반드시 .env에 설정 필요

# 로깅
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
