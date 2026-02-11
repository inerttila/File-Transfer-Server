import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


PID_FILE = Path.home() / ".fts_server.pid"


def _read_pid():
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _is_running(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _write_pid(pid):
    PID_FILE.write_text(str(pid), encoding="utf-8")


def _clear_pid_if_matches(pid):
    current = _read_pid()
    if current == pid:
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass


def _print_startup_info(host, port):
    print("File Transfer Server starting...")
    print(f"Host: {host}")
    print(f"Port: {port}")
    if host == "0.0.0.0":
        print(f"Local:  http://127.0.0.1:{port}")
    else:
        print(f"URL:    http://{host}:{port}")
    print("Press Ctrl+C to stop.")


def _listening_pids(port):
    pids = set()
    if os.name != "nt":
        return []
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return []

    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        proto = parts[0].upper()
        if not proto.startswith("TCP"):
            continue
        local_addr = parts[1]
        state = parts[3].upper()
        pid_txt = parts[4]
        is_target_port = local_addr.endswith(f":{port}") or local_addr.endswith(f"]:{port}")
        if state == "LISTENING" and is_target_port and pid_txt.isdigit():
            pids.add(int(pid_txt))
    return sorted(pids)


def _terminate_pid(pid):
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        return False

    for _ in range(20):
        if not _is_running(pid):
            return True
        time.sleep(0.1)

    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=True, capture_output=True)
            return not _is_running(pid)
        except Exception:
            return False

    return not _is_running(pid)


def start_server(host, port):
    existing_pid = _read_pid()
    if _is_running(existing_pid):
        print(f"Server already running (PID {existing_pid}).")
        print("Use `fts stop` to stop it first.")
        return 1
    port_pids = _listening_pids(port)
    if port_pids:
        print(f"Port {port} is already in use by PID(s): {', '.join(map(str, port_pids))}.")
        print(f"Run `fts stop --port {port}` or free that port first.")
        return 1

    _write_pid(os.getpid())
    _print_startup_info(host, port)
    try:
        # Lazy imports keep `fts stop`/`fts status` working
        # even if runtime dependencies are not installed.
        from waitress import serve
        from server import app

        serve(app, host=host, port=port)
    except KeyboardInterrupt:
        print("\nServer stopped.")
    except OSError as exc:
        print(f"Could not start server on {host}:{port}: {exc}")
        return 1
    except Exception as exc:
        print(f"Server stopped due to error: {exc}")
        return 1
    finally:
        _clear_pid_if_matches(os.getpid())
    return 0


def stop_server(port=8069):
    stopped_any = False
    failed = False
    pid = _read_pid()
    if pid and _is_running(pid):
        if _terminate_pid(pid):
            _clear_pid_if_matches(pid)
            print(f"Server stopped (PID {pid}).")
            stopped_any = True
        else:
            print(f"Could not stop PID {pid}.")
            failed = True
    elif pid:
        print(f"No running process for PID {pid}. Cleaning stale PID file.")
        _clear_pid_if_matches(pid)
    port_pids = _listening_pids(port)
    for listener_pid in port_pids:
        if listener_pid == pid:
            continue
        if _terminate_pid(listener_pid):
            print(f"Stopped process on port {port} (PID {listener_pid}).")
            stopped_any = True
        else:
            print(f"Could not stop process on port {port} (PID {listener_pid}).")
            failed = True

    if not stopped_any and not failed:
        print(f"No running server found on port {port}.")
        return 0
    return 1 if failed else 0


def status_server(port=8069):
    port_pids = _listening_pids(port)
    pid = _read_pid()
    if pid and _is_running(pid) and (pid in port_pids or not port_pids):
        print(f"Server is running (PID {pid}) on port {port}.")
        return 0
    if port_pids:
        pids_text = ", ".join(map(str, port_pids))
        print(f"A server is listening on port {port} (PID(s): {pids_text}).")
        if not pid:
            print("No PID file found, so it may not have been started by this `fts` instance.")
        elif pid not in port_pids:
            print(f"PID file points to {pid}, but that process is not the current port listener.")
        return 0
    print(f"Server is not running on port {port}.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="File Transfer Server CLI")
    sub = parser.add_subparsers(dest="command")

    start_parser = sub.add_parser("start", help="Start the server")
    start_parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    start_parser.add_argument("--port", type=int, default=8069, help="Port to bind (default: 8069)")

    stop_parser = sub.add_parser("stop", help="Stop the server started by fts")
    stop_parser.add_argument("--port", type=int, default=8069, help="Port to check/stop (default: 8069)")

    status_parser = sub.add_parser("status", help="Show server status")
    status_parser.add_argument("--port", type=int, default=8069, help="Port to check (default: 8069)")

    args = parser.parse_args(argv)
    command = args.command or "start"

    if command == "start" or command is None:
        host = getattr(args, "host", "0.0.0.0")
        port = getattr(args, "port", 8069)
        return start_server(host, port)
    if command == "stop":
        return stop_server(getattr(args, "port", 8069))
    if command == "status":
        return status_server(getattr(args, "port", 8069))

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())