# Ch.05 — 라즈베리파이 배포 가이드

## 하드웨어
- **모델**: Raspberry Pi 5 (8GB RAM)
- **OS**: Raspberry Pi OS (64-bit, Debian Bookworm)
- **쿨러**: 필수 (LLM 추론 시 발열)

## Ollama 설치
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma4:e2b    # Q4 버전 ~1.5GB
# Q8이 필요하면 GGUF를 직접 import
```

## 자동 시작 (systemd)
```ini
# /etc/systemd/system/warframe-bot.service
[Unit]
Description=Warframe Market Chatbot
After=network.target ollama.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/warframe_chatbot
ExecStart=/home/pi/warframe_chatbot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## 리소스 예산 (8GB 기준)
| 항목 | 메모리 |
|------|--------|
| OS + 시스템 | ~1GB |
| Gemma 4 E2B Q8 | ~2.5-3GB |
| 봇 + 폴링 | ~0.5GB |
| 캐시/DB | ~0.5GB |
| 여유 | ~3-3.5GB |

## 주의사항
- **동시 추론 1개로 제한** — 메모리 부족 방지
- **온도 모니터링**: `vcgencmd measure_temp` → 80도 넘으면 경고
- **swap 파일**: 2GB 권장 (OOM 방지)
- **로그 로테이션**: logrotate 설정 필수 (SD카드 용량)
- **Wi-Fi 안정성**: 유선 이더넷 권장 (24시간 서비스)
