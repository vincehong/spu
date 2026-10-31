#!/usr/bin/env python3
"""Userspace L2 delay + rate-limit switch for three veth pairs.

This kernel has CONFIG_NET_SCH_NETEM=n and CONFIG_NET_SCH_{HTB,TBF}=n, so
neither `tc netem` nor `tc tbf`/`htb` can shape the path. Each party process
binds the host side of a veth (veth{0,1,2}h). This program reads Ethernet
frames on the switch side (veth{0,1,2}s), holds them for a configured one-way
delay, then writes them to the destination party's switch side.

Ping / TCP RTT is approximately 2 * one-way delay (request delayed once,
reply delayed once), matching `tc qdisc add dev ... netem delay <one-way>`.

Optional `--rate-gbps` applies a token bucket per party interface in both
directions (switch ingress from that party and switch egress to that party),
matching `tc qdisc add dev <veth> root tbf rate <N>gbit` on each end of a
full-duplex 1 Gbit/s NIC.
"""

from __future__ import annotations

import argparse
import heapq
import os
import select
import socket
import struct
import sys
import time

ETH_P_ALL = 0x0003
ETH_P_IP = 0x0800
ETH_P_ARP = 0x0806
ETH_HDR = 14


def mac_from_text(text: str) -> bytes:
    return bytes(int(p, 16) for p in text.strip().split(":"))


def mac(path_or_iface: str) -> bytes:
    if os.path.exists(path_or_iface):
        text = open(path_or_iface, encoding="ascii").read().strip()
    else:
        text = open(f"/sys/class/net/{path_or_iface}/address", encoding="ascii").read().strip()
    return mac_from_text(text)


def ip4(addr: str) -> bytes:
    return socket.inet_aton(addr)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--one-way-ms",
        type=float,
        required=True,
        help="Hold time applied to every forwarded frame (milliseconds). RTT ≈ 2× this.",
    )
    p.add_argument(
        "--ifaces",
        default="veth0s,veth1s,veth2s",
        help="Switch-side interfaces, one per party, comma-separated",
    )
    p.add_argument(
        "--ips",
        default="10.10.0.1,10.10.0.2,10.10.0.3",
        help="Party IPv4 addresses on the host-side veths, comma-separated",
    )
    p.add_argument(
        "--host-ifaces",
        default="",
        help="Host-side interfaces whose MACs are used for ARP replies (optional if --host-macs is set)",
    )
    p.add_argument(
        "--host-macs",
        default="",
        help="Comma-separated MACs for the three party host-side NICs (preferred with netns)",
    )
    p.add_argument("--ready-file", default="", help="Create this file once sockets are bound")
    p.add_argument(
        "--rate-gbps",
        type=float,
        default=0.0,
        help="Per-party full-duplex cap in Gbit/s (0 = unlimited). 1.0 = 1 Gbit/s.",
    )
    p.add_argument(
        "--burst-bytes",
        type=int,
        default=262144,
        help="Token-bucket burst in bytes (default 256 KiB, ~TBF burst 2mbit)",
    )
    return p.parse_args()


class TokenBucket:
    """Byte token bucket. rate_bps is bits/s; burst is bytes."""

    def __init__(self, rate_bps: float, burst_bytes: int):
        self.rate_Bps = rate_bps / 8.0
        self.burst = float(max(burst_bytes, 1))
        self.tokens = self.burst
        self.t = time.monotonic()

    def schedule(self, nbytes: int, now: float) -> float:
        if self.rate_Bps <= 0:
            return now
        need = float(max(nbytes, 1))
        # If the pipe is already booked into the future, do not rewind it.
        if now > self.t:
            self.tokens = min(self.burst, self.tokens + (now - self.t) * self.rate_Bps)
            self.t = now
        if self.tokens >= need:
            self.tokens -= need
            return self.t
        wait = (need - self.tokens) / self.rate_Bps
        self.tokens = 0.0
        self.t += wait
        return self.t


def open_raw(iface: str) -> socket.socket:
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(ETH_P_ALL))
    sock.bind((iface, 0))
    sock.setblocking(False)
    return sock


def arp_reply(req: bytes, sender_mac: bytes, sender_ip: bytes) -> bytes | None:
    if len(req) < ETH_HDR + 28:
        return None
    hwtype, proto, hwlen, protolen, oper = struct.unpack("!HHBBH", req[ETH_HDR : ETH_HDR + 8])
    if hwtype != 1 or proto != ETH_P_IP or hwlen != 6 or protolen != 4 or oper != 1:
        return None
    sha = req[ETH_HDR + 8 : ETH_HDR + 14]
    spa = req[ETH_HDR + 14 : ETH_HDR + 18]
    tpa = req[ETH_HDR + 24 : ETH_HDR + 28]
    if tpa != sender_ip:
        return None
    # Ethernet dest is the requester; src is the target we impersonate.
    eth = sha + sender_mac + struct.pack("!H", ETH_P_ARP)
    payload = struct.pack("!HHBBH", 1, ETH_P_IP, 6, 4, 2) + sender_mac + tpa + sha + spa
    return eth + payload


def dest_index(frame: bytes, ip_to_idx: dict[bytes, int]) -> int | None:
    if len(frame) < ETH_HDR + 1:
        return None
    ethertype = struct.unpack("!H", frame[12:14])[0]
    if ethertype == ETH_P_IP:
        if len(frame) < ETH_HDR + 20:
            return None
        return ip_to_idx.get(frame[ETH_HDR + 16 : ETH_HDR + 20])
    if ethertype == ETH_P_ARP:
        if len(frame) < ETH_HDR + 28:
            return None
        return ip_to_idx.get(frame[ETH_HDR + 24 : ETH_HDR + 28])
    return None


def main() -> int:
    args = parse_args()
    ifaces = [x.strip() for x in args.ifaces.split(",") if x.strip()]
    ips = [x.strip() for x in args.ips.split(",") if x.strip()]
    if args.host_macs:
        host_macs = [mac_from_text(x.strip()) for x in args.host_macs.split(",") if x.strip()]
    else:
        hosts = [x.strip() for x in args.host_ifaces.split(",") if x.strip()]
        host_macs = [mac(h) for h in hosts]
    if not (len(ifaces) == len(ips) == len(host_macs) == 3):
        print("need exactly three ifaces/ips/macs", file=sys.stderr)
        return 2
    delay = max(0.0, args.one_way_ms) / 1000.0
    rate_bps = max(0.0, args.rate_gbps) * 1_000_000_000.0
    ip_to_idx = {ip4(ip): i for i, ip in enumerate(ips)}
    host_ips = [ip4(ip) for ip in ips]
    socks = [open_raw(name) for name in ifaces]
    fd_to_idx = {s.fileno(): i for i, s in enumerate(socks)}
    # Per-party ingress (from party) and egress (to party) buckets.
    ingress = [TokenBucket(rate_bps, args.burst_bytes) for _ in range(3)]
    egress = [TokenBucket(rate_bps, args.burst_bytes) for _ in range(3)]
    print(
        f"delay_switch one-way={args.one_way_ms}ms (expected ping RTT ~ {2 * args.one_way_ms}ms) "
        f"rate_gbps={args.rate_gbps} burst_bytes={args.burst_bytes} "
        f"ifaces={ifaces} ips={ips}",
        flush=True,
    )
    if args.ready_file:
        open(args.ready_file, "w", encoding="ascii").write("ready\n")

    heap: list[tuple[float, int, int, bytes]] = []
    seq = 0
    while True:
        timeout = None
        now = time.monotonic()
        if heap:
            timeout = max(0.0, heap[0][0] - now)
        readable, _, _ = select.select(socks, [], [], timeout)
        now = time.monotonic()
        for sock in readable:
            src = fd_to_idx[sock.fileno()]
            try:
                frame = sock.recv(65535)
            except BlockingIOError:
                continue
            ethertype = struct.unpack("!H", frame[12:14])[0] if len(frame) >= ETH_HDR else 0
            if ethertype == ETH_P_ARP:
                dst = dest_index(frame, ip_to_idx)
                if dst is None:
                    continue
                reply = arp_reply(frame, host_macs[dst], host_ips[dst])
                if reply is not None:
                    # ARP replies are local control; delay them like data so
                    # connection setup sees the same one-way latency.
                    due = now + delay
                    due = max(due, ingress[src].schedule(len(reply), now))
                    due = max(due, egress[src].schedule(len(reply), now))
                    heapq.heappush(heap, (due, seq, src, reply))
                    seq += 1
                continue
            dst = dest_index(frame, ip_to_idx)
            if dst is None or dst == src:
                continue
            due = now + delay
            due = max(due, ingress[src].schedule(len(frame), now))
            due = max(due, egress[dst].schedule(len(frame), now))
            heapq.heappush(heap, (due, seq, dst, frame))
            seq += 1
        now = time.monotonic()
        while heap and heap[0][0] <= now:
            _, _, dst, frame = heapq.heappop(heap)
            try:
                socks[dst].send(frame)
            except OSError as exc:
                print(f"send failed on {ifaces[dst]}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
