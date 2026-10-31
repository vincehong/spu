#!/usr/bin/env python3
"""Sweep SPDZwise RING vs ABY3 wall-clock over synthetic RTT settings.

FactoryMem is the in-process baseline (no TCP, so RTT injection does not
apply). Three-process FactoryBrpc runs on 127.0.0.1 (~0 RTT) and on the veth
delay switch (target ping RTT = 2 * one-way hold).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BENCH_DIR = ROOT / "src/libspu/mpc/spdzwise/benchmarks"
DEFAULT_BIN = BENCH_DIR / "bazel-bin/mparty_rtt_bench"


def run(cmd, **kwargs):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, check=True, **kwargs)


def median_wall(csv_path: Path) -> dict:
    rows = []
    with csv_path.open() as fh:
        for row in csv.DictReader(fh):
            iteration = row.get("iteration")
            if iteration is None or not str(iteration).strip().lstrip("-").isdigit():
                continue  # spdlog / banner lines mixed into stdout
            if int(iteration) == 0:
                continue  # warmup
            rows.append(row)
    if not rows:
        with csv_path.open() as fh:
            rows = [
                row
                for row in csv.DictReader(fh)
                if row.get("iteration")
                and str(row["iteration"]).strip().lstrip("-").isdigit()
            ]
    walls = [float(r["total_ms"]) for r in rows]
    bytes_ = [int(r["sent_bytes"]) for r in rows]
    actions = [int(r["sent_actions"]) for r in rows]
    return {
        "n": len(walls),
        "median_ms": statistics.median(walls) if walls else None,
        "min_ms": min(walls) if walls else None,
        "max_ms": max(walls) if walls else None,
        "sent_bytes": bytes_[0] if len(set(bytes_)) == 1 else bytes_,
        "sent_actions": actions[0] if len(set(actions)) == 1 else actions,
        "rows": rows,
    }


def ping_rtt(dest: str, source: str | None = None) -> dict:
    cmd = ["ping", "-c", "8", "-n", dest]
    if source:
        cmd[1:1] = ["-I", source]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    text = proc.stdout + proc.stderr
    avg = None
    for line in text.splitlines():
        if "rtt min/avg/max" in line or "round-trip" in line:
            # rtt min/avg/max/mdev = 0.040/0.055/0.071/0.015 ms
            try:
                avg = float(line.split("=")[1].split("/")[1])
            except (IndexError, ValueError):
                pass
    return {"dest": dest, "source": source, "avg_ms": avg, "raw": text}


def set_delay(rtt_ms: float, rate_gbps: float = 0.0) -> dict:
    env = os.environ.copy()
    env["RTT_MS"] = str(rtt_ms)
    env["RATE_GBPS"] = str(rate_gbps)
    run(["bash", str(HERE / "netem.sh"), "up"], env=env)
    backend = Path("/tmp/spu-rtt/backend.txt")
    if not backend.exists():
        backend = Path("/tmp/spu-rtt-backend.txt")
    info = backend.read_text() if backend.exists() else ""
    if "veth" in info:
        proc = subprocess.run(
            ["sudo", "ip", "netns", "exec", "p0", "ping", "-c", "8", "-n", "10.10.0.2"],
            capture_output=True, text=True, check=False)
        avg = None
        for line in (proc.stdout + proc.stderr).splitlines():
            if "rtt min/avg/max" in line or "round-trip" in line:
                try:
                    avg = float(line.split("=")[1].split("/")[1])
                except (IndexError, ValueError):
                    pass
        measured = {"dest": "10.10.0.2", "source": "p0", "avg_ms": avg,
                    "raw": proc.stdout + proc.stderr}
        parties = "10.10.0.1:61540,10.10.0.2:61541,10.10.0.3:61542"
    else:
        measured = ping_rtt("127.0.0.1")
        parties = "127.0.0.1:61540,127.0.0.1:61541,127.0.0.1:61542"
    tput = None
    tput_path = Path("/tmp/spu-rtt/tput.txt")
    if tput_path.exists():
        first = tput_path.read_text().split()
        try:
            tput = {
                "gbps": float(first[0]),
                "bytes": int(first[1]),
                "seconds": float(first[2]),
                "raw": tput_path.read_text(),
            }
        except (IndexError, ValueError):
            tput = {"raw": tput_path.read_text()}
    return {
        "target_rtt_ms": rtt_ms,
        "one_way_ms": rtt_ms / 2.0,
        "rate_gbps": rate_gbps,
        "backend": info.strip(),
        "measured_ping": measured,
        "parties": parties,
        "measured_tput": tput,
    }


def clear_delay():
    subprocess.run(["bash", str(HERE / "netem.sh"), "down"], check=False)


def run_one(bin_path: Path, out_dir: Path, protocol: str, op: str, transport: str,
            parties: str, args) -> dict:
    env = os.environ.copy()
    env.update({
        "BIN": str(bin_path),
        "PROTOCOL": protocol,
        "OP": op,
        "TRANSPORT": transport,
        "PARTIES": parties,
        "COUNT": str(args.count),
        "REPS": str(args.reps),
        "ROWS": str(args.rows),
        "COLS": str(args.cols),
        "YACL_NUM_THREADS": str(args.threads),
        "OUT_DIR": str(out_dir),
        "TIMEOUT_SEC": str(args.timeout_sec),
    })
    started = time.monotonic()
    proc = subprocess.run(["bash", str(HERE / "run_3pc.sh")], env=env,
                          capture_output=True, text=True)
    elapsed = time.monotonic() - started
    (out_dir / "harness.stdout").write_text(proc.stdout)
    (out_dir / "harness.stderr").write_text(proc.stderr)
    csv_path = out_dir / f"{protocol}_{op}.csv"
    if transport == "mem":
        csv_path = out_dir / f"{protocol}_{op}_mem.csv"
        if not csv_path.exists():
            # run_3pc names mem as protocol_op_mem.csv
            pass
    record = {
        "protocol": protocol,
        "op": op,
        "transport": transport,
        "parties": parties,
        "returncode": proc.returncode,
        "harness_seconds": elapsed,
        "csv": str(csv_path) if csv_path.exists() else None,
    }
    if proc.returncode != 0:
        record["error"] = (proc.stderr or proc.stdout)[-4000:]
        print(record["error"], file=sys.stderr)
        return record
    if csv_path.exists():
        record.update(median_wall(csv_path))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin", type=Path, default=DEFAULT_BIN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=2048)
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--rows", type=int, default=128)
    parser.add_argument("--cols", type=int, default=64)
    parser.add_argument("--threads", type=int, default=16)
    parser.add_argument("--timeout-sec", type=int, default=600)
    parser.add_argument(
        "--rtt-ms",
        default="0,0.5,1,2,5,10",
        help="Comma-separated target ping RTT in milliseconds",
    )
    parser.add_argument(
        "--ops",
        default="trunc,linear,a2b",
        help="Comma-separated ops: trunc,linear,a2b,b2a,mmul",
    )
    parser.add_argument("--skip-mem", action="store_true")
    parser.add_argument("--skip-brpc", action="store_true")
    parser.add_argument(
        "--protocols",
        default="",
        help="Optional comma-separated protocol filter (spdzwise,aby3,aby3-exact)",
    )
    parser.add_argument(
        "--rate-gbps",
        type=float,
        default=0.0,
        help="Per-party full-duplex cap in Gbit/s (0 = unlimited). 1 = 1 Gbit/s.",
    )
    args = parser.parse_args()
    rtts = [float(x) for x in args.rtt_ms.split(",") if x.strip()]
    ops = [x.strip() for x in args.ops.split(",") if x.strip()]
    protocols = {
        "trunc": ["spdzwise", "aby3", "aby3-exact"],
        "linear": ["spdzwise", "aby3", "aby3-exact"],
        "a2b": ["spdzwise", "aby3"],
        "b2a": ["spdzwise", "aby3"],
        "mmul": ["spdzwise", "aby3"],
    }
    if args.protocols.strip():
        wanted = {x.strip() for x in args.protocols.split(",") if x.strip()}
        protocols = {op: [p for p in ps if p in wanted] for op, ps in protocols.items()}
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "host": subprocess.check_output(["uname", "-a"], text=True).strip(),
        "git": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "args": vars(args) | {"bin": str(args.bin)},
        "note": (
            "SPDZwise RING internally uses Z_2^128 with external FM64. "
            "ABY3 is semi-honest; aby3-exact uses A2B/ARShiftB/B2A truncation "
            "as in the branch PPML reports. Tiny single-sample inference is omitted."
        ),
        "runs": [],
    }
    (out / "lscpu.txt").write_text(subprocess.check_output(["lscpu"], text=True))
    try:
        if not args.skip_mem:
            for op in ops:
                for protocol in protocols[op]:
                    dest = out / f"mem_{protocol}_{op}"
                    dest.mkdir(exist_ok=True)
                    print(f"=== FactoryMem {protocol} {op} ===", flush=True)
                    record = run_one(args.bin, dest, protocol, op, "mem",
                                     "in-process", args)
                    record["setting"] = "factory-mem"
                    record["target_rtt_ms"] = 0.0
                    summary["runs"].append(record)
                    (out / "summary.json").write_text(
                        json.dumps(summary, indent=2, default=str) + "\n"
                    )
        if not args.skip_brpc:
            for rtt in rtts:
                print(f"=== RTT target {rtt} ms ===", flush=True)
                delay = set_delay(rtt, args.rate_gbps)
                lo_parties = "127.0.0.1:61540,127.0.0.1:61541,127.0.0.1:61542"
                parties = delay["parties"]
                # RTT 0 uses loopback without the delay switch if the backend
                # fell through to veth with 0 hold; still bind the reported
                # parties so TCP traverses the same path as delayed runs when
                # the veth switch is active.
                for op in ops:
                    for protocol in protocols[op]:
                        dest = out / f"rtt{rtt}_{protocol}_{op}"
                        if args.rate_gbps:
                            dest = out / f"rtt{rtt}_{args.rate_gbps:g}g_{protocol}_{op}"
                        dest.mkdir(exist_ok=True)
                        print(f"=== brpc {protocol} {op} rtt={rtt} ===", flush=True)
                        record = run_one(args.bin, dest, protocol, op, "brpc",
                                         parties, args)
                        tag = f"brpc-rtt-{rtt}ms"
                        if args.rate_gbps:
                            tag += f"-{args.rate_gbps:g}g"
                        record["setting"] = tag
                        record.update({k: delay[k] for k in
                                       ("target_rtt_ms", "one_way_ms", "rate_gbps",
                                        "backend", "measured_ping", "measured_tput")})
                        summary["runs"].append(record)
                        (out / "summary.json").write_text(
                            json.dumps(summary, indent=2, default=str) + "\n"
                        )
                clear_delay()
    finally:
        clear_delay()
    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
