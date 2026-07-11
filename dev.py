"""AI-Keeper development launcher.

Starts Docker services (PostgreSQL + Redis), then runs the FastAPI backend
and Vite frontend concurrently.  All output is streamed to this single
terminal with coloured prefixes so you can scan for issues at a glance.

Usage:
    python dev.py               # start everything (default)
    python dev.py --skip-docker # skip Docker — use native PG/Redis on :5432/:6379
    python dev.py --check       # only run health checks, don't start services
    python dev.py --stop        # stop Docker services
"""

import subprocess
import sys
import time
import threading
import os
import socket
import urllib.request
import urllib.error
import json
import re as _re
import signal
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIENT_DIR = ROOT / "src" / "client"

# ── ANSI colours ────────────────────────────────────────────────────────
C = {
    "RST": "\033[0m",
    "RED": "\033[31m",    "GRN": "\033[32m",   "YEL": "\033[33m",
    "BLU": "\033[34m",    "MAG": "\033[35m",   "CYN": "\033[36m",
    "WHT": "\033[37m",    "BOLD": "\033[1m",   "DIM": "\033[2m",
}


def _c(colour, text):
    return f"{C.get(colour, '')}{text}{C['RST']}"


def _banner():
    print(_c("BOLD", "\n" + "=" * 52))
    print(_c("BOLD", "  ") + _c("YEL", "AI-Keeper  Development  Launcher"))
    print(_c("BOLD", "=" * 52 + "\n"))


def _run(cmd, **kwargs):
    """Run a command, return (returncode, stdout, stderr)."""
    r = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    return r.returncode, r.stdout, r.stderr


def _check_step(label, ok, detail=""):
    mark = _c("GRN", "[OK]") if ok else _c("RED", "[FAIL]")
    line = f"  {mark}  {label}"
    if detail and not ok:
        line += f"  {_c('DIM', detail)}"
    print(line)
    return ok


# ── Port helpers ────────────────────────────────────────────────────────

def _is_port_open(host, port, timeout=2):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return True
    except (ConnectionRefusedError, OSError, socket.timeout):
        return False


def _kill_port(port):
    """Kill the process listening on `port` (Windows only)."""
    if os.name != "nt":
        return
    code, out, _ = _run(
        f'netstat -ano | findstr ":{port}" | findstr "LISTENING"',
        shell=True,
    )
    if code != 0:
        return
    for line in out.strip().splitlines():
        parts = line.split()
        try:
            pid = parts[-1]
            _run(["taskkill", "/F", "/PID", pid])
        except (ValueError, IndexError):
            pass


# ── Health check ────────────────────────────────────────────────────────

def _api_health():
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:3001/api/health",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _print_health():
    print(_c("CYN", "\n-- Health Check " + "-" * 40))
    h = _api_health()

    status_colour = "GRN" if h.get("status") == "ok" else "RED"
    print(_c(status_colour, f"  Overall: {h.get('status', 'unknown')}"))

    components = h.get("components", {})
    for name, state in components.items():
        if state == "ok" or state == "available":
            print(f"    {name:<14} {_c('GRN', state)}")
        elif "error" in str(state):
            print(f"    {name:<14} {_c('RED', state)}")
        elif state in ("missing", "disabled"):
            print(f"    {name:<14} {_c('DIM', state)}")
        else:
            print(f"    {name:<14} {_c('YEL', state)}")
    print()


# ── Output streaming ────────────────────────────────────────────────────

def _stream(proc, prefix, colour, *, log_files=None):
    """Read lines from *proc* stdout, print with prefix, and write plain-text
    to each file handle in *log_files* (a list of open file handles or None)."""
    for line in iter(proc.stdout.readline, b""):
        text = line.decode("utf-8", errors="replace").rstrip("\n").rstrip("\r")
        if text:
            clean = _re.sub(r"\x1b\[[0-9;]*m", "", text)
            print(f"{C.get(colour, '')}{prefix}{C['RST']} {text}")
            if log_files:
                for fh in log_files:
                    try:
                        fh.write(f"{prefix} {clean}\n")
                        fh.flush()
                    except Exception:
                        pass
    proc.stdout.close()


# ── Main ────────────────────────────────────────────────────────────────

def main():
    _banner()
    skip_docker = "--skip-docker" in sys.argv

    # ── 1. Prerequisites ────────────────────────────────────────────
    print(_c("CYN", "-- Prerequisites " + "-" * 40))

    # Check if essential services are already reachable (native install, etc.)
    pg_native = _is_port_open("127.0.0.1", 5432, timeout=2)
    redis_native = _is_port_open("127.0.0.1", 6379, timeout=2)
    services_ready = pg_native and redis_native

    if services_ready:
        print(f"  {_c('GRN', '[OK]')}  PostgreSQL :5432 + Redis :6379 already running — skip Docker")
        docker_ok = False
    elif skip_docker:
        print(f"  {_c('YEL', '[SKIP]')} Docker check skipped (--skip-docker)")
        docker_ok = False
    else:
        # Docker fallback — only needed when native services aren't available
        rc, _, _ = _run(["docker", "info"], timeout=5)
        docker_ok = rc == 0
        if not docker_ok:
            print(f"  {_c('YEL', '[WARN]')} Docker not available (timeout or not running)")
            print(f"  {_c('DIM', '       Tip: use --skip-docker if PG/Redis are running natively')}")

    # Python >= 3.11
    py_ok = sys.version_info >= (3, 11)
    _check_step(f"Python {sys.version_info.major}.{sys.version_info.minor}", py_ok,
                "Python >= 3.11 required")
    if not py_ok:
        sys.exit(1)

    # Node
    rc, node_ver, _ = _run(["node", "--version"])
    _check_step(f"Node.js {node_ver.strip()}", rc == 0)

    # ── 2. Database / cache services ────────────────────────────────
    print(_c("CYN", "\n-- Database / Cache Services " + "-" * 40))

    if docker_ok:
        # Use Docker Compose
        _run(["docker", "compose", "up", "-d"], cwd=ROOT, timeout=60)

        # Wait for PostgreSQL
        pg_ok = False
        for i in range(30):
            rc, out, _ = _run(
                ["docker", "compose", "exec", "-T", "postgres", "pg_isready", "-U", "aikeeper"],
                cwd=ROOT, timeout=10,
            )
            if rc == 0:
                pg_ok = True
                break
            time.sleep(1)
        _check_step("PostgreSQL (pgvector:pg16)", pg_ok,
                    "docker compose up -d first, then retry")

        # Wait for Redis
        redis_ok = False
        for i in range(10):
            rc, out, _ = _run(
                ["docker", "compose", "exec", "-T", "redis", "redis-cli", "ping"],
                cwd=ROOT, timeout=10,
            )
            if rc == 0 and "PONG" in out:
                redis_ok = True
                break
            time.sleep(1)
        _check_step("Redis (7-alpine)", redis_ok)

        if not pg_ok:
            print(_c("RED", "\nPostgreSQL is required.  Check docker compose logs.\n"))
            sys.exit(1)
    else:
        # Verify native services are reachable
        pg_ok = _is_port_open("127.0.0.1", 5432, timeout=2)
        redis_ok = _is_port_open("127.0.0.1", 6379, timeout=2)
        _check_step("PostgreSQL :5432", pg_ok,
                    "No native PostgreSQL found — install it or start Docker")
        _check_step("Redis :6379", redis_ok,
                    "No native Redis found — install it or start Docker")

        if not pg_ok:
            print(_c("RED", "\nPostgreSQL is required.  Start Docker or install natively.\n"))
            sys.exit(1)

    # ── 3. Free ports ───────────────────────────────────────────────
    print(_c("CYN", "\n-- Port Check " + "-" * 40))
    for port in (3001, 5173, 9100):
        if _is_port_open("127.0.0.1", port, timeout=1):
            _kill_port(port)
            time.sleep(1)
            if _is_port_open("127.0.0.1", port, timeout=1):
                _check_step(f"Port {port}", False, "still in use after kill attempt")
            else:
                _check_step(f"Port {port}", True, "freed")
        else:
            _check_step(f"Port {port}", True, "free")

    # ── 3.5. Log cleanup (keep 7 days) ─────────────────────────────
    log_root = ROOT / "log"
    log_root.mkdir(parents=True, exist_ok=True)
    _now_ts = datetime.now().timestamp()
    _retention_secs = 7 * 24 * 3600
    _cleaned = 0
    for _entry in log_root.iterdir():
        if _entry.is_dir() and _entry.name != "." and _entry.name != "..":
            try:
                _dir_ts = datetime.strptime(_entry.name, "%Y-%m-%d").timestamp()
                if _now_ts - _dir_ts > _retention_secs:
                    import shutil
                    shutil.rmtree(_entry, ignore_errors=True)
                    _cleaned += 1
            except (ValueError, OSError):
                pass
    if _cleaned:
        print(_c("DIM", f"  Log cleanup: removed {_cleaned} old dir(s) (7-day retention)\n"))

    log_date_dir = log_root / datetime.now().strftime("%Y-%m-%d")
    log_date_dir.mkdir(parents=True, exist_ok=True)

    combined_fh = open(log_date_dir / "combined.log", "w", encoding="utf-8")
    be_fh = open(log_date_dir / "backend.log", "w", encoding="utf-8")
    fe_fh = open(log_date_dir / "frontend.log", "w", encoding="utf-8")
    kp_fh = open(log_date_dir / "kp-mcp.log", "w", encoding="utf-8")

    _log_files = [combined_fh, be_fh, fe_fh, kp_fh]

    # UTF-8 env for all subprocesses
    sub_env = os.environ.copy()
    sub_env["PYTHONUTF8"] = "1"
    sub_env["PYTHONIOENCODING"] = "utf-8"
    sub_env["PYTHONUNBUFFERED"] = "1"

    # ── 4. Launch services ──────────────────────────────────────────
    print(_c("CYN", "\n-- Starting Services " + "-" * 40))
    print(f"  Backend   http://127.0.0.1:3001/docs")
    print(f"  Frontend  http://127.0.0.1:5173")
    print(f"  KP MCP    http://127.0.0.1:9100/mcp")
    print(_c("YEL", "\n  Press Ctrl+C to stop all services.\n"))
    print(_c("DIM", "  " + "─" * 55))

    be_env = sub_env.copy()
    be_env["LOG_FILE"] = str(log_date_dir / "backend.log")
    be_env["AIKEEPER_DEV_MODE"] = "1"

    # Backend process
    be = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "src.server.main:app",
            "--reload", "--port", "3001", "--host", "127.0.0.1",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=be_env,
    )

    # Frontend process (use shell=True on Windows because npm is a .cmd wrapper)
    fe = subprocess.Popen(
        "npm run dev",
        cwd=CLIENT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        shell=True,
        env=sub_env,
    )

    # KP MCP Server process (optional — skip if module not installed)
    kp = None
    try:
        kp = subprocess.Popen(
            [sys.executable, "-m", "kp_mcp_server"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            env=sub_env,
        )
    except FileNotFoundError:
        print(_c("DIM", "  KP MCP Server not found — skipping (build at hermes side)"))
    except Exception as e:
        print(_c("DIM", f"  KP MCP Server unavailable: {e}"))

    # Stream output from all three (terminal + dedicated log + combined log)
    be_thread = threading.Thread(
        target=_stream, args=(be, "[BE]", "GRN"),
        kwargs={"log_files": [combined_fh]}, daemon=True,  # backend.log written by FileHandler
    )
    fe_thread = threading.Thread(
        target=_stream, args=(fe, "[FE]", "BLU"),
        kwargs={"log_files": [fe_fh, combined_fh]}, daemon=True,
    )
    be_thread.start()
    fe_thread.start()
    if kp:
        kp_thread = threading.Thread(
            target=_stream, args=(kp, "[KP]", "MAG"),
            kwargs={"log_files": [kp_fh, combined_fh]}, daemon=True,
        )
        kp_thread.start()

    # Shutdown handler
    def _shutdown(sig=None, frame=None):
        print(_c("YEL", "\n\nShutting down …"))
        for p in (be, fe, kp):
            if p is None:
                continue
            if p.poll() is None:
                p.terminate()
        time.sleep(1)
        for p in (be, fe, kp):
            if p is None:
                continue
            if p.poll() is None:
                p.kill()
        # Close log file handles
        for fh in _log_files:
            try:
                fh.close()
            except Exception:
                pass
        print(_c("GRN", "Stopped."))
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # ── 5. Wait for health ──────────────────────────────────────────
    backend_up = False
    for i in range(20):
        if _is_port_open("127.0.0.1", 3001, timeout=2):
            backend_up = True
            break
        time.sleep(1.5)

    if backend_up:
        print(_c("DIM", "  " + "─" * 55))
        _print_health()

        # Quick frontend check
        if _is_port_open("127.0.0.1", 5173, timeout=2):
            print(_c("GRN", "  Frontend dev server is responding on :5173"))
        else:
            print(_c("DIM", "  Frontend still starting … (Vite may take a moment)"))

        print(_c("BOLD", "\n  All systems ready.  "))
        print(_c("DIM", "  Open http://127.0.0.1:5173 in your browser.\n"))
    else:
        print(_c("YEL", "\n  Backend hasn't responded yet — output above may show why.\n"))

    # Wait for either process to exit
    try:
        while be.poll() is None and fe.poll() is None:
            time.sleep(1)
        while kp is not None and kp.poll() is None:
            time.sleep(1)
            time.sleep(1)
        # Something exited — report
        if be.poll() is not None:
            print(_c("RED", f"\nBackend exited with code {be.returncode}"))
        if fe.poll() is not None:
            print(_c("RED", f"\nFrontend exited with code {fe.returncode}"))
        if kp.poll() is not None:
            print(_c("RED", f"\nKP MCP Server exited with code {kp.returncode}"))
        _shutdown()
    except KeyboardInterrupt:
        _shutdown()


# ── CLI ──────────────────────────────────────────────────────────────────

def _cmd_check():
    """Just run health checks without starting services."""
    _banner()
    if _is_port_open("127.0.0.1", 3001, timeout=2):
        _print_health()
        if _is_port_open("127.0.0.1", 5173, timeout=1):
            print(_c("GRN", "  Frontend is also responding on :5173"))
    else:
        print(_c("RED", "  Backend is not running on :3001.  Start it with: python dev.py"))


def _cmd_stop():
    """Stop Docker services (no-op if using native PG/Redis)."""
    rc, _, _ = _run(["docker", "info"], timeout=3)
    if rc != 0:
        print(_c("YEL", "Docker not running — nothing to stop."))
        print(_c("DIM", "  If using native PG/Redis, stop them manually (e.g. net stop postgresql)."))
        return
    print(_c("YEL", "Stopping Docker services …"))
    _run(["docker", "compose", "down"], cwd=ROOT)
    print(_c("GRN", "Done."))


if __name__ == "__main__":
    if "--check" in sys.argv:
        _cmd_check()
    elif "--stop" in sys.argv:
        _cmd_stop()
    else:
        main()
