"""Pi deploy script via paramiko SFTP."""

import os
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import paramiko

PI_HOST = "192.168.0.63"
PI_PORT = 22
PI_USER = "leejongwan"
PI_PASS = "tlsghktk6"
PI_BASE = "/home/leejongwan/Desktop/warframe_chatbot"

LOCAL_BASE = Path(__file__).parent

UPLOAD_DIRS = ["src"]
UPLOAD_FILES = ["main.py", "requirements.txt"]

EXCLUDE_SUFFIXES = {".pyc", ".db", ".db-shm", ".db-wal"}
EXCLUDE_DIRS = {"__pycache__", ".git", "venv", "data", ".claude"}


def sftp_mkdir_p(sftp, remote_path):
    parts = [p for p in remote_path.split("/") if p]
    current = ""
    for part in parts:
        current = current + "/" + part
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)


def upload_dir(sftp, local_dir, remote_dir):
    count = 0
    sftp_mkdir_p(sftp, remote_dir)
    for item in sorted(local_dir.iterdir()):
        if item.name in EXCLUDE_DIRS:
            continue
        remote_item = remote_dir + "/" + item.name
        if item.is_dir():
            count += upload_dir(sftp, item, remote_item)
        elif item.is_file():
            if item.suffix in EXCLUDE_SUFFIXES:
                continue
            sftp.put(str(item), remote_item)
            print("[OK] " + str(item.relative_to(LOCAL_BASE)))
            count += 1
    return count


def deploy():
    print("Pi deploy: " + PI_USER + "@" + PI_HOST + ":" + PI_BASE)
    print("-" * 50)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(PI_HOST, port=PI_PORT, username=PI_USER, password=PI_PASS, timeout=10)
        print("SSH connected\n")

        sftp = client.open_sftp()
        total = 0

        for fname in UPLOAD_FILES:
            local_path = LOCAL_BASE / fname
            if not local_path.exists():
                print("[skip] " + fname)
                continue
            sftp.put(str(local_path), PI_BASE + "/" + fname)
            print("[OK] " + fname)
            total += 1

        for dname in UPLOAD_DIRS:
            local_dir = LOCAL_BASE / dname
            if not local_dir.exists():
                print("[skip] " + dname)
                continue
            print("\n[dir: " + dname + "/]")
            total += upload_dir(sftp, local_dir, PI_BASE + "/" + dname)

        sftp.close()
        print("\nUploaded: " + str(total) + " files")

        print("\nRestarting server...")
        _, stdout, stderr = client.exec_command(
            "sudo systemctl restart warframe-chatbot 2>/dev/null || "
            "(pkill -f 'python main.py' 2>/dev/null; echo 'pkill done')"
        )
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        if out:
            print("  " + out)
        if err:
            print("  stderr: " + err)

    except Exception as e:
        print("ERROR: " + str(e))
        sys.exit(1)
    finally:
        client.close()

    print("\nDone!")


if __name__ == "__main__":
    deploy()
