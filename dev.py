"""AI-Keeper development launcher.

Starts Docker services (PostgreSQL + Redis), then runs the FastAPI backend
and Vite frontend concurrently.  All output is streamed to this single
terminal with coloured prefixes so you can scan for issues at a glance.

Usage:
    python dev.py          # start everything (default)
    python dev.py --check  # only run health checks, don't start services
    python dev.py --stop   # stop Docker services
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
import signal
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

def _stream(proc, prefix, colour, *, file=None):
    """Read lines from *proc* stdout and print them with a prefix."""
    fp = file or proc.stdout
    for line in iter(fp.readline, b""):
        text = line.decode("utf-8", errors="replace").rstrip("\n").rstrip("\r")
        if text:
            print(f"{C.get(colour, '')}{prefix}{C['RST']} {text}")
    if fp is not proc.stdout:
        fp.close()
    proc.stdout.close()


# ── Main ────────────────────────────────────────────────────────────────

def main():
    _banner()

    # ── 1. Prerequisites ────────────────────────────────────────────
    print(_c("CYN", "-- Prerequisites " + "-" * 40))

    # Docker
    rc, _, _ = _run(["docker", "info"], timeout=15)
    if not _check_step("Docker engine", rc == 0, "Start Docker Desktop first"):
        sys.exit(1)

    # Python >= 3.11
    py_ok = sys.version_info >= (3, 11)
    _check_step(f"Python {sys.version_info.major}.{sys.version_info.minor}", py_ok,
                "Python >= 3.11 required")
    if not py_ok:
        sys.exit(1)

    # Node
    rc, node_ver, _ = _run(["node", "--version"])
    _check_step(f"Node.js {node_ver.strip()}", rc == 0)

    # ── 2. Docker services ──────────────────────────────────────────
    print(_c("CYN", "\n-- Docker Services " + "-" * 40))

    # Start
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

    # ── 4. Launch services ──────────────────────────────────────────
    print(_c("CYN", "\n-- Starting Services " + "-" * 40))
    print(f"  Backend   http://127.0.0.1:3001/docs")
    print(f"  Frontend  http://127.0.0.1:5173")
    print(f"  KP MCP    http://127.0.0.1:9100/mcp")
    print(_c("YEL", "\n  Press Ctrl+C to stop all services.\n"))
    print(_c("DIM", "  " + "─" * 55))

    # Backend process
    be = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "src.server.main:app",
            "--reload", "--port", "3001", "--host", "127.0.0.1",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    # Frontend process (use shell=True on Windows because npm is a .cmd wrapper)
    fe = subprocess.Popen(
        "npm run dev",
        cwd=CLIENT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        shell=True,
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
        )
    except FileNotFoundError:
        print(_c("DIM", "  KP MCP Server not found — skipping (build at hermes side)"))
    except Exception as e:
        print(_c("DIM", f"  KP MCP Server unavailable: {e}"))

    # Stream output from all three
    be_thread = threading.Thread(
        target=_stream, args=(be, "[BE]", "GRN"), daemon=True,
    )
    fe_thread = threading.Thread(
        target=_stream, args=(fe, "[FE]", "BLU"), daemon=True,
    )
    be_thread.start()
    fe_thread.start()
    if kp:
        kp_thread = threading.Thread(
            target=_stream, args=(kp, "[KP]", "MAG"), daemon=True,
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
    """Stop Docker services."""
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
