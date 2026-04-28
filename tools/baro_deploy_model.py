"""로컬에서 학습한 baro_model.pkl을 Pi로 배포.

사용법:
  python tools/baro_deploy_model.py
  python tools/baro_deploy_model.py --also-db   # model + baro.db도 같이
"""

import argparse
import sys
from pathlib import Path

try:
    import paramiko
except ImportError:
    print("pip install paramiko 필요")
    sys.exit(1)

PI_HOST   = "192.168.0.63"
PI_USER   = "leejongwan"
PI_PASS   = "tlsghktk6"
PI_PATH   = "/home/leejongwan/Desktop/warframe_chatbot"

LOCAL_ROOT = Path(__file__).resolve().parent.parent
MODEL_FILE = LOCAL_ROOT / "data" / "baro_model.pkl"
DB_FILE    = LOCAL_ROOT / "data" / "baro.db"


def _connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(PI_HOST, username=PI_USER, password=PI_PASS, timeout=15)
    return ssh


def deploy(also_db: bool = False):
    if not MODEL_FILE.exists():
        print(f"모델 파일 없음: {MODEL_FILE}")
        print("먼저 `python tools/baro_run.py train` 실행하세요.")
        sys.exit(1)

    ssh = _connect()
    sftp = ssh.open_sftp()

    files = [MODEL_FILE]
    if also_db:
        if DB_FILE.exists():
            files.append(DB_FILE)
        else:
            print(f"baro.db 없음, 모델만 배포합니다.")

    for local in files:
        remote = f"{PI_PATH}/data/{local.name}"
        print(f"  업로드: {local.name} ({local.stat().st_size:,}B) → {remote}")
        sftp.put(str(local), remote)

    sftp.close()

    # 서비스 재시작
    print("  서비스 재시작...")
    _, stdout, stderr = ssh.exec_command(
        f"echo {PI_PASS} | sudo -S systemctl restart warframe-chatbot"
    )
    stdout.channel.recv_exit_status()

    _, out, _ = ssh.exec_command("systemctl is-active warframe-chatbot")
    status = out.read().decode().strip()
    print(f"  서비스 상태: {status}")
    ssh.close()

    print("\n✅ 배포 완료!")
    if status == "active":
        print(f"  http://{PI_HOST}:9000 → 바로 탭에서 예측 확인")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--also-db", action="store_true", help="baro.db도 함께 배포")
    args = parser.parse_args()
    deploy(also_db=args.also_db)
