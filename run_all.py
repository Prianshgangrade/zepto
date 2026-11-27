"""Launches all Zepto microservices + API Gateway (+ optional Front End dev server)."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.security.secrets import SecretsManager


SERVICES: list[tuple[str, str, int]] = [
    ("catalogues", "services.catalogues.api.main:app", 8001),
    ("cart", "services.cart.api.main:app", 8002),
    ("payments", "services.payments.api.main:app", 8004),
    ("orders", "services.orders.api.main:app", 8003),
    ("notification", "services.notification.api.main:app", 8005),
    ("api-gateway", "services.api_gateway.main:app", 8000),
]


def wait_for_health(port: int, timeout_s: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout_s
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(url, timeout=1.0)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Zepto Microservices stack")
    parser.add_argument("--with-frontend", action="store_true", help="Also run Vite frontend dev server")
    args = parser.parse_args()

    SecretsManager.ensure_vault()
    procs: list[tuple[str, subprocess.Popen]] = []

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

    try:
        for name, target, port in SERVICES:
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", target, "--host", "127.0.0.1", "--port", str(port)],
                cwd=str(ROOT),
                env=env,
            )
            procs.append((name, proc))

        for name, _, port in SERVICES:
            ok = wait_for_health(port)
            status_label = "READY" if ok else "TIMEOUT"
            print(f"[{status_label}] {name} -> http://127.0.0.1:{port}")

        if args.with_frontend:
            fe_dir = ROOT / "frontend"
            fe_proc = subprocess.Popen(
                ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"],
                cwd=str(fe_dir),
                shell=(os.name == "nt"),
            )
            procs.append(("frontend", fe_proc))
            print("[READY] frontend -> http://127.0.0.1:5173")

        print("All services running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1.0)
            for name, proc in procs:
                if proc.poll() is not None:
                    raise RuntimeError(f"Process '{name}' exited with code {proc.returncode}")
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        for _, proc in reversed(procs):
            if proc.poll() is None:
                if os.name == "nt":
                    proc.terminate()
                else:
                    proc.send_signal(signal.SIGTERM)
        for _, proc in reversed(procs):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
