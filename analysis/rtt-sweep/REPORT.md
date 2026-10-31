# SPDZwise RING vs ABY3 RTT sweep

**Source tip:** `5ca32c7296ecabcab4c69e67ddc89b5be3fe0e5d`
(`opt B2A with width=1 and add PPML benchmark results`, `duan/codex/spdzwise-3pc`).
This work is **not** based on `vincehong/spu` `main`.

## ≤5× vs ABY3 semi at LAN-like RTT ≲1 ms

**It does not hold.**

On this one-VM, three-process FactoryBrpc path, SPDZwise RING (`Z_2^128` internally,
external FM64) is **~8–175×** ABY3 semi at every injected RTT, including ≲1 ms:

| kernel (non-tiny batch) | FactoryMem vs semi | BRPC ~0 ms vs semi | BRPC ~1 ms vs semi | BRPC ~1 ms vs ABY3 exact |
| --- | ---: | ---: | ---: | ---: |
| `trunc` (2048 el) | 78.7× | 158.9× | **135.1×** | 15.1× |
| `linear` (128×64 mmul+trunc) | 16.7× | 65.0× | **83.1×** | 14.2× |
| `a2b` (2048 el) | **2.74×** | 8.40× | **12.0×** | — |

The only ≤5× cell vs ABY3 semi is in-process FactoryMem `a2b` (2.74×), which has
no TCP and no injected RTT.

Against **ABY3 exact** truncation (`A2B → ARShiftB → B2A`, the baseline used in
the branch PPML tables), FactoryMem `trunc` is **3.46×** and FactoryMem `linear`
is **5.12×**. That matches the branch story that *large* exact-trunc PPML graphs
can sit near 5× on FactoryMem. Moving the same kernels onto three TCP processes
and adding LAN-like RTT pushes the exact-trunc ratio to **10–15×** at ≲1 ms and
**15–18×** at 10 ms. Extra RTT does **not** close the gap to ABY3 semi:
SPDZwise `trunc` sends 867 actions / 13.0 MiB versus ABY3 semi 5 actions / 56 KiB,
so the wall-clock ratio stays around **160×** once latency dominates.

Tiny single-sample inference (branch PPML 8–13×, compute-bound) was not rerun.

Python PPML (`jax_lr` / `stax_nn` / ResNet via `benchmark_ppml.py` + `nodectl`)
was **not** executed: this VM has no SPU Python extension or JAX/XLA, and
`examples/python/ml/benchmark_ppml.py` is cited in `readme-malicious-ppml.md`
but is not in the tree. Kernel proxies above stand in for FactoryMem / non-tiny
PPML (trunc + matmul-trunc + A2B), which is what those graphs spend their time on.

## Setup

| Item | Value |
| --- | --- |
| Host | 4× Intel Xeon (KVM), ~16 GiB, Linux 6.12.94+, Ubuntu 24.04, gcc 13.3 |
| Topology | **One VM**, three party processes, not three VMs |
| Addresses | `10.10.0.{1,2,3}:61540-2` in netns `p0`/`p1`/`p2` |
| Transport | FactoryMem (in-process) and FactoryBrpc (three processes) |
| Threads | `YACL_NUM_THREADS=16` (4-core box; branch PPML used 65) |
| SPDZwise | RING, external FM64, `check_threshold=5_000_000`, default `TruncNaive` |
| ABY3 semi | native `trunc_a` / `TruncAPr2` |
| ABY3 exact | `b2a(arshift_b(a2b(x), 16))` as in the PPML reports |
| Batch | trunc/a2b: 2048 elements; linear: 128×64 × 64×1; 1 warmup + 3 measured |
| Binary | `src/libspu/mpc/spdzwise/benchmarks:mparty_rtt_bench` (`-c opt`) |

## RTT injection (one-way vs RTT)

`tc qdisc … netem` is **unavailable**: this kernel is built with
`# CONFIG_NET_SCH_NETEM is not set`. `tc qdisc replace dev lo root netem delay …`
fails with `Error: Specified qdisc kind is unknown.`

Fallback (same semantics as netem):

1. Three veth pairs + three network namespaces so `10.10.0.{1,2,3}` are **not**
   local to one another (otherwise Linux hairpins via `lo` and skips the delay).
2. `delay_switch.py` is an AF_PACKET L2 forwarder. It holds every forwarded
   Ethernet frame for **one-way = target_RTT / 2**.
3. Checksum/GSO offload is disabled on both ends of each veth (`ethtool -K …
   tx off rx off tso off gso off gro off`). Without that, ICMP ping works but
   TCP SYN is dropped (partial checksum).

Convention: `--rtt-ms` / `RTT_MS` is the **target ping RTT**. One-way hold is
`RTT/2`. A ping A→B is delayed once each way, so measured RTT ≈ target.

| target ping RTT | one-way hold | measured ping p0→p1 (avg) |
| ---: | ---: | ---: |
| 0.0 ms | 0.0 ms | 0.245 ms |
| 0.5 ms | 0.25 ms | 0.841 ms |
| 1.0 ms | 0.50 ms | 1.343 ms |
| 2.0 ms | 1.00 ms | 2.384 ms |
| 5.0 ms | 2.50 ms | 5.444 ms |
| 10.0 ms | 5.00 ms | 10.514 ms |

The 0 ms row still traverses the userspace switch (no extra hold). FactoryMem
does not use the switch at all.

## Wall-clock tables

Median of 3 measured iterations (warmup discarded). `sent_bytes` /
`sent_actions` are the **three-party sum** of YACL link counters over the timed
kernel only. Ratios are SPDZwise / ABY3.

### `trunc` (2048 FM64 elements, shift 16)

| setting | meas. ping ms | SPDZwise ms | ABY3 semi ms | ABY3 exact ms | vs semi | vs exact | wise bytes / actions | semi bytes / actions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| factory-mem | — | 9.235 | 0.117 | 2.672 | 78.7× | 3.46× | 13 040 028 / 867 | 57 344 / 5 |
| brpc 0.0 | 0.245 | 95.510 | 0.601 | 9.433 | 158.9× | 10.13× | 13 040 028 / 867 | 57 344 / 5 |
| brpc 0.5 | 0.841 | 183.586 | 1.053 | 13.997 | 174.3× | 13.12× | 13 040 028 / 867 | 57 344 / 5 |
| brpc 1.0 | 1.343 | 256.991 | 1.903 | 16.990 | 135.1× | 15.13× | 13 040 028 / 867 | 57 344 / 5 |
| brpc 2.0 | 2.384 | 405.355 | 2.438 | 25.580 | 166.3× | 15.85× | 13 040 028 / 867 | 57 344 / 5 |
| brpc 5.0 | 5.444 | 952.456 | 5.838 | 54.235 | 163.1× | 17.56× | 13 040 028 / 867 | 57 344 / 5 |
| brpc 10.0 | 10.514 | 1797.067 | 11.087 | 99.910 | 162.1× | 17.99× | 13 040 028 / 867 | 57 344 / 5 |

ABY3 exact bytes/actions: 1 441 792 / 52 (constant across settings).

### `linear` (128×64 · 64×1 mmul + trunc)

| setting | meas. ping ms | SPDZwise ms | ABY3 semi ms | ABY3 exact ms | vs semi | vs exact | wise bytes / actions | semi bytes / actions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| factory-mem | — | 3.616 | 0.217 | 0.706 | 16.7× | 5.12× | 1 328 466 / 882 | 6 656 / 8 |
| brpc 0.0 | 0.245 | 47.723 | 0.734 | 3.728 | 65.0× | 12.80× | 1 328 466 / 882 | 6 656 / 8 |
| brpc 0.5 | 0.841 | 112.453 | 1.342 | 7.982 | 83.8× | 14.09× | 1 328 466 / 882 | 6 656 / 8 |
| brpc 1.0 | 1.343 | 177.004 | 2.129 | 12.443 | 83.1× | 14.23× | 1 328 466 / 882 | 6 656 / 8 |
| brpc 2.0 | 2.384 | 322.450 | 3.700 | 22.216 | 87.2× | 14.51× | 1 328 466 / 882 | 6 656 / 8 |
| brpc 5.0 | 5.444 | 779.772 | 8.414 | 53.969 | 92.7× | 14.45× | 1 328 466 / 882 | 6 656 / 8 |
| brpc 10.0 | 10.514 | 1498.310 | 16.216 | 102.316 | 92.4× | 14.64× | 1 328 466 / 882 | 6 656 / 8 |

### `a2b` (2048 elements)

| setting | meas. ping ms | SPDZwise ms | ABY3 semi ms | vs semi | wise bytes / actions | semi bytes / actions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| factory-mem | — | 3.430 | 1.252 | 2.74× | 5 092 032 / 369 | 688 128 / 24 |
| brpc 0.0 | 0.245 | 44.963 | 5.351 | 8.40× | 5 092 032 / 369 | 688 128 / 24 |
| brpc 0.5 | 0.841 | 72.929 | 6.994 | 10.43× | 5 092 032 / 369 | 688 128 / 24 |
| brpc 1.0 | 1.343 | 94.747 | 7.890 | 12.01× | 5 092 032 / 369 | 688 128 / 24 |
| brpc 2.0 | 2.384 | 169.734 | 13.741 | 12.35× | 5 092 032 / 369 | 688 128 / 24 |
| brpc 5.0 | 5.444 | 353.367 | 24.664 | 14.33× | 5 092 032 / 369 | 688 128 / 24 |
| brpc 10.0 | 10.514 | 674.939 | 45.551 | 14.82× | 5 092 032 / 369 | 688 128 / 24 |

Raw per-run CSVs and `summary.json` live under `analysis/rtt-sweep/results/`.

## How this branch launches 3PC locally

Existing paths on `codex/spdzwise-3pc` (none of them inject RTT):

- **FactoryMem kernel benches** in `src/libspu/mpc/spdzwise/benchmarks/`
  (`truncation_bench`, `conversion_bench`, `mula1b_bench`, …) — three threads,
  one process. This is what the archived PPML / building-block reports used.
  `tc`/`veth` cannot affect them.
- **`//libspu/mpc/tools/benchmark --mode=mparty`** — three localhost processes
  on `127.0.0.1:61540-2`. **ABY3 / Semi2k / Cheetah only**; no SPDZwise.
- **Python `nodectl` + `examples/python/conf/3pc.json`** — five nodes
  (`127.0.0.1:61920-4`) plus SPU internals on `61930-2`, protocol ABY3/FM64.
  SPDZwise PPML would swap the runtime config to `SPDZWISE` + RING (the
  `3pc_spdzwise.json` named in the README is **not in the tree**).
- **This harness** `mparty_rtt_bench` — FactoryMem *or* three FactoryBrpc
  processes, `--protocol=spdzwise|aby3|aby3-exact`.

## Repro

```sh
# 1. tip (do not use vincehong/spu main for protocol code)
git remote add duan https://github.com/DuanYuFi/spu.git   # if needed
git fetch duan codex/spdzwise-3pc
git checkout -B work/spdzwise-rtt-sweep duan/codex/spdzwise-3pc

# 2. build the 3-party bench (Bazel 7.7.1)
export PATH="$HOME/bin:$PATH"   # bazelisk
cd src/libspu/mpc/spdzwise/benchmarks
bazel --output_user_root=/tmp/spu-spdzwise-bazel build -c opt //:mparty_rtt_bench \
  --lockfile_mode=off --jobs=2 \
  --extra_toolchains=@rules_foreign_cc//toolchains:preinstalled_cmake_toolchain

# 3. sweep (FactoryMem + BRPC over veth delay). Needs sudo for netns/veth.
cd ../../../../analysis/rtt-sweep
# Prefer real netem when the kernel has it:
#   sudo tc qdisc replace dev lo root netem delay 0.5ms   # one-way; ping RTT ~1ms
# This VM falls back to veth + delay_switch.py automatically.
python3 run_sweep.py --output results \
  --count 2048 --reps 3 --rows 128 --cols 64 --threads 16 \
  --rtt-ms 0,0.5,1,2,5,10 --ops trunc,linear,a2b
python3 summarize.py results/summary.json -o REPORT.md
```

Single 3-process run without the sweep driver:

```sh
RTT_MS=1 bash netem.sh up          # target ping RTT = 1ms; one-way hold = 0.5ms
PROTOCOL=spdzwise OP=linear TRANSPORT=brpc COUNT=2048 REPS=3 ROWS=128 COLS=64 \
  PARTIES=10.10.0.1:61540,10.10.0.2:61541,10.10.0.3:61542 \
  YACL_NUM_THREADS=16 bash run_3pc.sh
bash netem.sh down
```

## Blockers / caveats

- **No `tc netem`** (`CONFIG_NET_SCH_NETEM` is not set). Userspace L2 delay is
  the documented fallback; measured ping tracks the target within ~0.3–0.8 ms
  plus switch overhead (~0.25 ms at hold=0).
- **No Python PPML** on this VM (no `spu` extension, no JAX; `benchmark_ppml.py`
  missing from the tree). Ratios are kernel proxies, not full LR/DNN/ResNet
  graphs. The branch FactoryMem PPML table (vs ABY3 exact) remains the best
  large-graph 0-RTT reference: LR train 3.05×, DNN train 2.04×, ResNet-50
  infer 1.97×; tiny infer 8.5–12.9× excluded.
- 4 cores / `YACL_NUM_THREADS=16` vs the original 64-worker server. Absolute
  milliseconds are not comparable to those reports; **ratios** are the signal.
- Inter/intra-op parallel is disabled in the bench config (same as several
  branch kernel benches).
- FactoryMem is in-process shared memory: injecting RTT cannot change it, and
  it over-states ABY3 semi on `trunc` (5 local messages, ~0.1 ms).
- Reconstruct after the timed region is used only as a type/size sanity check.

## Files

| path | role |
| --- | --- |
| `analysis/rtt-sweep/run_sweep.py` | FactoryMem + RTT loop |
| `analysis/rtt-sweep/run_3pc.sh` | 1 or 3 processes, optional `ip netns exec` |
| `analysis/rtt-sweep/netem.sh` | try `tc netem`, else veth+switch |
| `analysis/rtt-sweep/setup_veth.sh` | 3 netns + veth, offloads off |
| `analysis/rtt-sweep/delay_switch.py` | AF_PACKET one-way hold |
| `analysis/rtt-sweep/summarize.py` | tables from `summary.json` |
| `analysis/rtt-sweep/results/` | CSVs + `summary.json` |
| `src/libspu/mpc/spdzwise/benchmarks/mparty_rtt_bench.cc` | SPDZwise / ABY3 / ABY3-exact kernels |
