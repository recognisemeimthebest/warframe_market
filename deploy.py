"""Pi deploy script via paramiko SFTP.

Usage:
  python deploy.py              # upload + restart
  python deploy.py --restart    # restart only
  python deploy.py --cmd "..."  # run arbitrary SSH command
"""

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

RESTART_CMD = (
    "sudo systemctl restart warframe-chatbot 2>/dev/null || "
    "(pkill -f 'python main.py' 2>/dev/null; echo 'pkill done')"
)


def _connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(PI_HOST, port=PI_PORT, username=PI_USER, password=PI_PASS, timeout=10)
    return client


def _run(client, cmd):
    _, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    code = stdout.channel.recv_exit_status()
    if out:
        print(out)
    if err:
        print("[stderr] " + err)
    return code


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


def cmd_restart():
    print("Restarting warframe-chatbot on Pi...")
    client = _connect()
    try:
        code = _run(client, RESTART_CMD)
        print("Done! (exit " + str(code) + ")")
    finally:
        client.close()


def cmd_run(command):
    print("Running: " + command)
    print("-" * 50)
    client = _connect()
    try:
        _run(client, command)
    finally:
        client.close()


def cmd_deploy():
    print("Pi deploy: " + PI_USER + "@" + PI_HOST + ":" + PI_BASE)
    print("-" * 50)

    client = _connect()
    try:
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
        _run(client, RESTART_CMD)

    except Exception as e:
        print("ERROR: " + str(e))
        sys.exit(1)
    finally:
        client.close()

    print("\nDone!")


if __name__ == "__main__":
    args = sys.argv[1:]

    try:
        if not args:
            cmd_deploy()
        elif args[0] == "--restart":
            cmd_restart()
        elif args[0] == "--cmd" and len(args) >= 2:
            cmd_run(" ".join(args[1:]))
        else:
            print("Usage:")
            print("  python deploy.py              # upload + restart")
            print("  python deploy.py --restart    # restart only")
            print("  python deploy.py --cmd \"...\"  # run SSH command")
            sys.exit(1)
    except Exception as e:
        print("ERROR: " + str(e))
        sys.exit(1)
