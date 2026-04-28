"""로컬에서 학습한 baro_model*.pkl을 Pi로 배포.

사용법:
  python tools/baro_deploy_model.py
  python tools/baro_deploy_model.py --also-db   # model + baro.db도 같이
  python tools/baro_deploy_model.py --pull       # Pi에서 git pull 후 재시작만
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

LOCAL_ROOT        = Path(__file__).resolve().parent.parent
MODEL_FILE        = LOCAL_ROOT / "data" / "baro_model.pkl"
MODEL_FILE_PRIMED = LOCAL_ROOT / "data" / "baro_model_primed.pkl"
DB_FILE           = LOCAL_ROOT / "data" / "baro.db"


def _restart(ssh):
    print("  서비스 재시작...")
    _, stdout, _ = ssh.exec_command(
        f"echo {PI_PASS} | sudo -S systemctl restart warframe-chatbot"
    )
    stdout.channel.recv_exit_status()
    _, out, _ = ssh.exec_command("systemctl is-active warframe-chatbot")
    status = out.read().decode().strip()
    print(f"  서비스 상태: {status}")
    return status


def _connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(PI_HOST, username=PI_USER, password=PI_PASS, timeout=15)
    return ssh


def git_pull_and_restart(ssh):
    print("  Pi git pull...")
    _, out, err = ssh.exec_command(
        f"cd {PI_PATH} && git pull --ff-only 2>&1"
    )
    print(" ", out.read().decode().strip())


def deploy(also_db: bool = False, pull_only: bool = False):
    ssh = _connect()

    if pull_only:
        git_pull_and_restart(ssh)
        _restart(ssh)
        ssh.close()
        return

    models_found = [f for f in [MODEL_FILE, MODEL_FILE_PRIMED] if f.exists()]
    if not models_found:
        print("모델 파일 없음. 먼저 `python tools/baro_run.py train` 실행하세요.")
        sys.exit(1)

    sftp = ssh.open_sftp()

    files = list(models_found)
    if also_db:
        if DB_FILE.exists():
            files.append(DB_FILE)
        else:
            print(f"baro.db 없음, 모델만 배포합니다.")

    git_pull_and_restart(ssh)

    for local in files:
        remote = f"{PI_PATH}/data/{local.name}"
        print(f"  업로드: {local.name} ({local.stat().st_size:,}B) → {remote}")
        sftp.put(str(local), remote)

    sftp.close()
    _restart(ssh)
    ssh.close()

    print(f"\n배포 완료! http://{PI_HOST}:9000 에서 바로 탭 확인")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--also-db",   action="store_true", help="baro.db도 함께 배포")
    parser.add_argument("--pull",      action="store_true", help="git pull + 재시작만 (모델 업로드 없음)")
    args = parser.parse_args()
    deploy(also_db=args.also_db, pull_only=args.pull)
