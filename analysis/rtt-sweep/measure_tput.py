#!/usr/bin/env python3
"""TCP throughput p0 (10.10.0.1) -> p1 (10.10.0.2) through the delay switch."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

BYTES = int(os.environ.get("TPUT_BYTES", str(32 * 1024 * 1024)))
PORT = int(os.environ.get("TPUT_PORT", "61550"))
NS0 = os.environ.get("TPUT_NS0", "p0")
NS1 = os.environ.get("TPUT_NS1", "p1")
DST = os.environ.get("TPUT_DST", "10.10.0.2")


def ns_python(ns: str, code: str, extra_env: dict[str, str] | None = None) -> subprocess.Popen:
    extra_env = extra_env or {}
    cmd = ["sudo", "ip", "netns", "exec", ns, "env"]
    for key, value in extra_env.items():
        cmd.append(f"{key}={value}")
    cmd.extend(["python3", "-c", code])
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def main() -> int:
    server_code = r"""
import socket, sys, os
port = int(os.environ["TPUT_PORT"])
want = int(os.environ["TPUT_BYTES"])
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("0.0.0.0", port))
s.listen(1)
s.settimeout(15)
c, _ = s.accept()
c.settimeout(30)
got = 0
while got < want:
    chunk = c.recv(min(1 << 16, want - got))
    if not chunk:
        break
    got += len(chunk)
c.close()
s.close()
print(got, flush=True)
"""
    client_code = r"""
import socket, os, time, sys
dst = os.environ["TPUT_DST"]
port = int(os.environ["TPUT_PORT"])
want = int(os.environ["TPUT_BYTES"])
payload = b"x" * (1 << 16)
s = socket.socket()
s.settimeout(15)
s.connect((dst, port))
s.settimeout(30)
sent = 0
t0 = time.monotonic()
while sent < want:
    n = s.send(payload[: want - sent])
    sent += n
s.close()
dt = time.monotonic() - t0
gbps = (sent * 8) / dt / 1e9 if dt > 0 else 0
print(f"{sent} {dt:.6f} {gbps:.4f}", flush=True)
"""
    env = {
        "TPUT_PORT": str(PORT),
        "TPUT_BYTES": str(BYTES),
        "TPUT_DST": DST,
    }
    srv = ns_python(NS1, server_code, env)
    time.sleep(0.3)
    cli = ns_python(NS0, client_code, env)
    try:
        out, err = cli.communicate(timeout=40)
    except subprocess.TimeoutExpired:
        cli.kill()
        srv.kill()
        print("throughput probe timed out", file=sys.stderr)
        return 1
    try:
        srv.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        srv.kill()
    line = (out or "").strip().splitlines()[-1] if out.strip() else ""
    parts = line.split()
    if len(parts) != 3:
        srv_err = ""
        if srv.stderr:
            try:
                srv_err = srv.stderr.read()
            except ValueError:
                srv_err = ""
        print(f"throughput probe failed: stdout={out!r} stderr={err!r} srv={srv_err!r}")
        return 1
    sent, dt, gbps = int(parts[0]), float(parts[1]), float(parts[2])
    line = f"sent {sent} bytes in {dt:.3f}s = {gbps:.3f} Gbit/s"
    print(line)
    Path("/tmp/spu-rtt").mkdir(parents=True, exist_ok=True)
    Path("/tmp/spu-rtt/tput.txt").write_text(
        f"{gbps:.4f} {sent} {dt:.6f}\n{line}\n"
    )
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
