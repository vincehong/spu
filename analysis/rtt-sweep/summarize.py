#!/usr/bin/env python3
"""Turn summary.json from run_sweep.py into REPORT.md tables."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def md_cell(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    data = json.loads(args.summary.read_text())
    runs = data.get("runs", [])

    by_op = defaultdict(list)
    for run in runs:
        by_op[run.get("op", "?")].append(run)

    lines = []
    lines.append("# SPDZwise RING vs ABY3 RTT sweep")
    lines.append("")
    lines.append(f"Source tip: `{data.get('git', '')}`")
    lines.append("")
    lines.append(data.get("note", ""))
    lines.append("")
    lines.append(f"Host: {data.get('host', '')}")
    lines.append("")

    for op, group in by_op.items():
        lines.append(f"## `{op}`")
        lines.append("")
        lines.append(
            "| setting | target RTT ms | measured ping ms | protocol | "
            "median ms | min–max ms | sent bytes | actions | ratio vs ABY3 |"
        )
        lines.append("|---|---:|---:|---|---:|---|---:|---:|---:|")
        baselines = {}
        for run in group:
            if run.get("protocol") == "aby3" and run.get("median_ms"):
                key = (run.get("setting"), run.get("target_rtt_ms"))
                baselines[key] = run["median_ms"]
        for run in group:
            ping = None
            measured = run.get("measured_ping") or {}
            if isinstance(measured, dict):
                ping = measured.get("avg_ms")
            key = (run.get("setting"), run.get("target_rtt_ms"))
            base = baselines.get(key)
            ratio = None
            if base and run.get("median_ms"):
                ratio = run["median_ms"] / base
            mm = run.get("min_ms")
            mx = run.get("max_ms")
            rng = f"{mm:.3f}–{mx:.3f}" if mm is not None and mx is not None else "—"
            lines.append(
                "| {setting} | {rtt} | {ping} | {proto} | {med} | {rng} | {b} | {a} | {ratio} |".format(
                    setting=run.get("setting", ""),
                    rtt=md_cell(run.get("target_rtt_ms")),
                    ping=md_cell(ping),
                    proto=run.get("protocol", ""),
                    med=md_cell(run.get("median_ms")),
                    rng=rng,
                    b=run.get("sent_bytes", "—"),
                    a=run.get("sent_actions", "—"),
                    ratio=f"{ratio:.3f}×" if ratio else "—",
                )
            )
        lines.append("")

    # 5x statement
    lines.append("## ≤5× vs ABY3 semi at LAN-like RTT ≲1 ms")
    lines.append("")
    holds = []
    for run in runs:
        if run.get("protocol") != "spdzwise":
            continue
        rtt = run.get("target_rtt_ms")
        if rtt is None or rtt > 1.0001:
            continue
        if run.get("op") in ("trunc", "linear") and run.get("setting") == "factory-mem":
            continue
        peers = [
            x
            for x in runs
            if x.get("protocol") == "aby3"
            and x.get("op") == run.get("op")
            and x.get("setting") == run.get("setting")
            and x.get("median_ms")
        ]
        if not run.get("median_ms") or not peers:
            continue
        ratio = run["median_ms"] / peers[0]["median_ms"]
        holds.append((run.get("op"), run.get("setting"), rtt, ratio, ratio <= 5.0))
    if not holds:
        lines.append("No completed SPDZwise/ABY3 pairs at RTT ≤ 1 ms.")
    else:
        yes = all(h[4] for h in holds)
        lines.append(
            "The ≤5× budget **holds** at LAN-like RTT ≲1 ms for every completed "
            "non-tiny pair."
            if yes
            else "The ≤5× budget **does not hold** for at least one completed pair "
            "at RTT ≲1 ms."
        )
        lines.append("")
        for op, setting, rtt, ratio, ok in holds:
            flag = "yes" if ok else "NO"
            lines.append(f"- `{op}` {setting} RTT={rtt} ms: {ratio:.3f}× ({flag})")
    lines.append("")

    text = "\n".join(lines) + "\n"
    dest = args.output or args.summary.with_name("REPORT.md")
    dest.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
