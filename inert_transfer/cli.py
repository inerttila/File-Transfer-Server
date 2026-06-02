import argparse
import json
import os
import socket
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from importlib.metadata import PackageNotFoundError, version

from packaging.version import InvalidVersion, Version


PID_FILE = Path.home() / ".fts_server.pid"
UPDATE_CACHE_FILE = Path.home() / ".inert_transfer_update_check.json"
UPDATE_CHECK_INTERVAL_SECONDS = 60 * 60 * 24
PACKAGE_NAME = "inert-transfer"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"


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


def _load_update_cache():
    try:
        with UPDATE_CACHE_FILE.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except Exception:
        return {}


def _save_update_cache(cache_data):
    try:
        with UPDATE_CACHE_FILE.open("w", encoding="utf-8") as cache_file:
            json.dump(cache_data, cache_file)
    except Exception:
        pass


def _fetch_latest_version():
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=2.5) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("info", {}).get("version")
    except Exception:
        return None


def check_for_update():
    if os.getenv("INERT_TRANSFER_DISABLE_UPDATE_CHECK") == "1":
        return None

    try:
        current_version = version(PACKAGE_NAME)
    except PackageNotFoundError:
        return None

    now = int(time.time())
    cache = _load_update_cache()
    latest_version = cache.get("latest_version")
    last_check = int(cache.get("last_check", 0))

    if now - last_check >= UPDATE_CHECK_INTERVAL_SECONDS:
        fetched = _fetch_latest_version()
        if fetched:
            latest_version = fetched
        _save_update_cache({"last_check": now, "latest_version": latest_version})

    if not latest_version:
        return None

    try:
        if Version(latest_version) > Version(current_version):
            return (
                f"A new version of {PACKAGE_NAME} is available: "
                f"{current_version} -> {latest_version}\n"
                f"Upgrade with: python -m pip install --upgrade {PACKAGE_NAME}"
            )
    except InvalidVersion:
        return None

    return None


_STARTUP_BANNER = r""" 
 _____  ____  _        ___      ______  ____    ____  ____   _____ _____  ___  ____
|     ||    || |      /  _]    |      ||    \  /    ||    \ / ___/|     |/  _]|    \
|   __| |  | | |     /  [_     |      ||  D  )|  o  ||  _  (   \_ |   __/  [_ |  D  )
|  |_   |  | | |___ |    _]    |_|  |_||    / |     ||  |  |\__  ||  |_|    _]|    /
|   _]  |  | |     ||   [_       |  |  |    \ |  _  ||  |  |/  \ ||   _]   [_ |    \
|  |    |  | |     ||     |      |  |  |  .  \|  |  ||  |  |\    ||  | |     ||  .  \
|__|   |____||_____||_____|      |__|  |__|\_||__|__||__|__| \___||__| |_____||__|\_|
"""


def _enable_windows_ansi():
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def _prepare_terminal_output():
    _enable_windows_ansi()
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _box_chars():
    rounded = ("╭", "╮", "╰", "╯", "│", "├", "┤", "─")
    encoding = sys.stdout.encoding or "utf-8"
    try:
        for char in rounded:
            char.encode(encoding)
        return rounded
    except (UnicodeEncodeError, LookupError):
        return ("+", "+", "+", "+", "|", "+", "+", "-")


def _tty_style(text, *codes):
    if not sys.stdout.isatty() or not codes:
        return text
    return f"\033[{';'.join(codes)}m{text}\033[0m"


def _print_server_status(host, port, url):
    _prepare_terminal_output()
    tl, tr, bl, br, side, mid_l, mid_r, bar = _box_chars()
    title = "> Server listening"
    rows = [("Host", str(host)), ("Port", str(port)), ("URL", url)]
    label_w = max(len(label) for label, _ in rows)
    plain_lines = [f" {title}"] + [
        f"  {label.ljust(label_w)}  |  {value}" for label, value in rows
    ]
    inner_w = max(len(line) for line in plain_lines)
    border = bar * inner_w
    edge = _tty_style(side, "96")

    def _box_line(plain_content, colorize=None):
        pad = inner_w - len(plain_content)
        if colorize and sys.stdout.isatty():
            content = colorize(plain_content) + (" " * pad)
        else:
            content = plain_content + (" " * pad)
        print(edge + content + edge)

    print(_tty_style(f"{tl}{border}{tr}", "96"))
    _box_line(f" {title}", lambda text: _tty_style(text, "1", "96"))
    print(_tty_style(f"{mid_l}{border}{mid_r}", "2"))
    for label, value in rows:
        plain = f"  {label.ljust(label_w)}  |  {value}"
        prefix = f"  {label.ljust(label_w)}  |  "

        def _colorize_row(_text, lbl=label, val=value, pfx=prefix):
            value_style = ("1", "92") if lbl == "URL" else ("97",)
            return _tty_style(pfx, "2") + _tty_style(val, *value_style)

        _box_line(plain, _colorize_row)
    print(_tty_style(f"{bl}{border}{br}", "96"))
    print()
    print(_tty_style("  >> Press Ctrl+C to stop", "2", "33"))


def _print_startup_info(host, port):
    def _detect_lan_ip():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                # No packets are sent; this asks OS for preferred outbound interface.
                sock.connect(("8.8.8.8", 80))
                ip = sock.getsockname()[0]
            if ip and ip != "127.0.0.1":
                return ip
        except Exception:
            pass
        return None

    print(_STARTUP_BANNER)
    print()
    if host == "0.0.0.0":
        lan_ip = _detect_lan_ip()
        url = f"http://{lan_ip}:{port}" if lan_ip else f"http://127.0.0.1:{port}"
    else:
        url = f"http://{host}:{port}"
    _print_server_status(host, port, url)


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
    if argv is None:
        argv = sys.argv[1:]
    # Shortcut: `inert 9001` -> `inert start --port 9001`
    if argv and len(argv) == 1 and str(argv[0]).isdigit():
        argv = ["start", "--port", str(argv[0])]

    update_message = check_for_update()
    if update_message:
        print(update_message)

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