# SPDZwise RING vs ABY3 RTT sweep

**Source tip:** `5ca32c7296ecabcab4c69e67ddc89b5be3fe0e5d`
(`opt B2A with width=1 and add PPML benchmark results`, `duan/codex/spdzwise-3pc`),
plus this change: RING `Add()` in `ring_conversion.cc` is bit-sliced
**Kogge–Stone** (TruncNaive / A2B / B2A). `MsbA2B`’s carry tree is unchanged.
This work is **not** based on `vincehong/spu` `main`.

## Kogge–Stone A2B (vs the RCA tables below)

The 100k FactoryMem candidate run ranked **RCA 145 ms / BK 306 ms / KS 626 ms**
(AND/input 125 / 291 / 832, AND-layers 63 / 12 / 8) and then **deleted** KS/BK
from the running tree. Those KS/BK sources are gone; only
`benchmarks/a2b-split3-100k-2026-10-22/RESULTS.md` remains. There was no
enable-flag. For LAN RTT the ranking is inverted: KS has the fewest AND
layers, so `Add()` is now bit-sliced Kogge–Stone on the existing Planes
(generate + distances 1,2,4,8,16,32, last layer G-only, CSA still 1
`AndLayer`; A2B skips the public-zero LSB; carry-out of bit 63 discarded).

Smoke: `conversion_bench` verified a2b/b2a at 1 / 65 / 130 elements.
Packed AND words per 64-lane block: **A2B 718**, **B2A 1380** (RCA was 125 /
188). TruncNaive AND-round depth **23** (A2B 8 + B2A 15) vs RCA **189** vs
ABY3 exact **~14**.

`sent_actions` is still the **three-party YACL Send() sum**, not rounds.

| quantity (trunc 2048 FM64) | RCA (previous) | **KS (this run)** | ABY3 exact |
| --- | ---: | ---: | ---: |
| `sent_actions` **3-party sum** | 867 | **426** | **52** |
| `sent_actions` per party | 289 | **142** | 17 or 18 |
| sequential **AND rounds** | ~189 | **23** | ~14 |
| `sent_bytes` 3-party sum | 13 040 028 | **64 751 388** | 1 441 792 |

linear: 882 → **384** actions, 1 328 466 → **5 372 802** bytes (exact 55 /
93 184). a2b: 369 → **183** actions, 5 092 032 → **22 060 704** bytes
(ABY3 A2B 24 / 688 128). AND messages for trunc are now 23×3 = **69** of
the 426; the other 357 are MAC/ABFL/open/AllGather. ABFL grew because it
checks every packed AND word.

Re-run: FactoryMem + BRPC target ping **1 ms** and **5 ms**, 1 Gbit/s cap
(userspace token bucket). Measured ping **1.342 ms** / **5.449 ms**. 1
warmup + 3 measured.

| kernel | FactoryMem vs exact | **BRPC ~1 ms + 1 Gbit/s vs exact** | **BRPC ~5 ms + 1 Gbit/s vs exact** |
| --- | ---: | ---: | ---: |
| `trunc` 2048 el | **15.79×** (41.2 / 2.61 ms) | **25.84×** (521.3 / 20.2 ms) | **25.09×** (1351 / 53.9 ms) |
| `linear` 128×64 mmul+trunc | **9.28×** (7.59 / 0.82 ms) | **7.81×** (95.2 / 12.2 ms) | **6.25×** (336.5 / 53.9 ms) |
| `a2b` vs native ABY3 A2B | **9.29×** (13.3 / 1.43 ms) | **20.80×** (168.4 / 8.10 ms) | **19.16×** (482.7 / 25.2 ms) |

RCA (same harness, previous commits) was FactoryMem trunc **3.46×**, BRPC
~1 ms **15.0×**, ~5 ms **17.6×**; linear 5.12× / 14.5× / 14.6×; a2b 2.74× /
12.1× / 14.2×.

**Is ≤5× closer?** Only for **linear** on BRPC (14.5× → **7.81×** @1 ms,
**6.25×** @5 ms) — still above 5×. `trunc` and `a2b` moved **away** from
5×, and FactoryMem **lost** the RCA ≤5× cells (trunc 3.46×, linear 5.12×).

Why: KS buys rounds (189 → 23) and pays AND-volume (~7× packed words, ~5×
bytes). FactoryMem is ABFL-bound, matching the 100k ranking. BRPC `trunc`
at 1 ms is 521 / 1.34 ≈ **388** ping RTTs, not 23 — ABFL + 62 MiB now
dominate, so the round win does not show up. `linear` truncates 128
elements (2 blocks vs 32), so the same 23 AND rounds ride on ~16× less
ABFL traffic and the wall-clock ratio drops. Vs ABY3 **semi**, `trunc` is
still **~230–340×**.

JSON: [`results/vs_aby3_exact_ks.json`](results/vs_aby3_exact_ks.json),
[`results/actions_vs_rounds_ks.json`](results/actions_vs_rounds_ks.json),
[`results-ks/summary.json`](results-ks/summary.json).

## What `sent_actions` means — are 867 rounds wrong?

**No. 867 is not round depth.** It is a **message-count**, and it is a
**three-party sum**. The figures in this section are the **ripple-carry**
adder (commits through `6a0260b3`). After the Kogge–Stone switch, trunc is
**426** actions / **~23** AND rounds (see above); 426 is still a Send sum
(142/party), not rounds. The BRPC ~15× wall-clock under RCA came from
~189 sequential AND rounds vs ABY3 exact Kogge-Stone (~14), not from 867 vs
52 as “rounds”.

### What the counter actually is

YACL `link::Statistics::sent_actions` is incremented **once per
`Send` / `SendAsync` / `SendAsyncThrottled`** on that party’s `Context`
(`yacl/link/context.cc`). The header says *“chunked mode is treated as a
single action”* — HTTP fragmentation does **not** inflate the counter. Recv
is a separate `recv_actions` and is not in our CSV.

Our bench (`mparty_rtt_bench`) then **adds the three parties together** for
the timed kernel only (warmup excluded). FactoryMem and BRPC report the same
867 / 52, so this is protocol structure, not TCP.

| quantity | SPDZwise `trunc` 2048 FM64 | ABY3 exact `trunc` |
| --- | ---: | ---: |
| `sent_actions` **3-party sum** (CSV) | **867** | **52** |
| `sent_actions` **per party** | **289** | **17 or 18** (reveal is 1-sided, 17+17+18=52) |
| sequential **AND / rotate rounds** (critical path) | **~189** | **~14** |
| extra auth / open / AllGather rounds | ~20–40 (MAC + ABFL) | ~4 (B2A reveal + extra rotate) |
| estimated **critical-path rounds** | **~210–230** | **~18** |
| `sent_bytes` 3-party sum | 13 040 028 | 1 441 792 |

A single SPDZwise `and_bb` is 1 `SendAsync` to `PrevRank` + `Recv` from
`NextRank` — the same ring-rotate as ABY3 `Communicator::rotate`, which
increments SPU `Communicator.latency` by 1. Tests pin this:
`boolean_test.cc` expects `sent_actions += 1` per `and_bb`. AllGather is
**2** `SendAsync`s (one to each peer) in **1** round, so it inflates
`sent_actions` more than round depth.

### Expected rounds for batch 2048 FM64 (`nbits = 64`)

Batch size does **not** change AND-round depth: 2048 lanes pack into 32
64-bit words. Bytes scale with `n`; rounds do not.

**SPDZwise `TruncNaive`** (`ring_truncation.cc`): `a2b` → local arithmetic
right shift → `b2a`.

Split-3 A2B (`ring_conversion.cc`):

1. `SplitSummands`: 63 CSA ANDs **batched** into **1** `AndLayer` / 1 round.
2. `Add(..., zero_lsb=true)`: **ripple-carry**, one AND per retained carry
   for bits 1…62 → **62 sequential rounds**.

A2B AND rounds = **63**. (Not `log 64`.)

B2A (width=64, not the width=1 daBit path):

1. `Sliced(mask)` = another A2B of a fresh authenticated mask → **63** AND
   rounds.
2. `Add(x, r)` with `zero_lsb=false` → **63** sequential AND rounds
   (bits 0…62).
3. `verify()` (MAC check + ABFL) then a Boolean open.

AND subtotal = **189 sequential rotate-rounds**. Three-party AND messages =
189×3 = **567**. The remaining **300** of 867 are MAC/ABFL/open/AllGather
(`RequireAll` is two AllGathers; `gather` is two peer Sends + a digest
AllGather). `a2b` alone is 369 = 189 AND messages + ~180 check messages,
because `prepareOutputs`/`commit` runs ABFL when A2B did not verify itself.

**ABY3 exact** (`b2a(arshift_b(a2b(x), 16))`), FM64:

- A2B (`conversion.cc`): 1 rotate + `add_bb` Kogge-Stone. Comment:
  *“Latency: 2 + log(nbits) from 1 rotate and 1 ppa”*.
- `ppa_kogge_stone` (`ab_api.cc`): 1 AND for generate, then `log2(64)=6`
  levels; `vmap` **packs the two ANDs per level into one** `and_bb` → **7
  AND rounds**.
- B2A-by-PPA (`nbits > 8`): 1 rotate + 7 AND + 1 P2→P0 reveal + 1 rotate.

Action check: A2B 3+21=24, B2A 3+21+1+3=28, **total 52**. Round depth
**~18**. ARShiftB is local.

ABY3 semi `TruncAPr2` is 5 three-party actions (~1–2 rounds). That is a
different algorithm, not “exact trunc with fewer rounds”.

### Why BRPC is still ~15× if rounds are “only” ~13×

Rounds are **not** similar. Ripple 189 vs Kogge-Stone 14 is already
**~13.5×** on the AND critical path; ~18 vs ~220 with checks is
**~12×**. Message-count ratio 867/52 = **16.7×** is the same ratio as
per-party Sends (289/17) because each AND round is one Send per party.

Wall-clock tracks **round depth**, not the 867 figure as a round count:

| setting | SPDZwise / ABY3 exact | ping | SPDZwise ms / ping |
| --- | ---: | ---: | ---: |
| FactoryMem | 3.46× | — | compute (MAC/ABFL/ripple locally) |
| BRPC ~0.25 ms (veth hold=0) | 10.13× | 0.245 ms | mixed |
| BRPC ~1.34 ms | **15.13×** | 1.343 ms | 257 / 1.34 ≈ **192** sequential RTTs |
| BRPC ~10.5 ms | 17.99× | 10.514 ms | 1797 / 10.5 ≈ **171** sequential RTTs |

~190 RTTs ≈ the **189 AND rounds**. That is why 1 Gbit/s did not move the
ratio (round-dominated, not byte-dominated). Bytes still differ ~9×, which
adds a little on top of the round ratio and pushes ~13× toward the measured
~15–18×.

Vs **semi**, the round gap is ~189 vs ~2, so ~160× at LAN RTT is expected
and is **not** a counter bug.

JSON: [`results/actions_vs_rounds.json`](results/actions_vs_rounds.json).

## SPDZwise RING vs ABY3 exact at 1 Gbit/s

**≤5× vs ABY3 exact still does not hold** with each party link capped at
**1 Gbit/s** plus LAN-like RTT.

This kernel has `# CONFIG_NET_SCH_TBF is not set` and
`# CONFIG_NET_SCH_HTB is not set`, so the preferred command

```sh
sudo tc qdisc replace dev veth0h root tbf rate 1gbit burst 256kb latency 50ms
```

fails with `Specified qdisc kind is unknown`. The working equivalent is the
existing veth + `delay_switch.py` token bucket (per-party full-duplex ingress
and egress, burst 256 KiB):

```sh
RATE_GBPS=1 RTT_MS=1 bash analysis/rtt-sweep/netem.sh up
# delay_switch.py --one-way-ms 0.5 --rate-gbps 1 --burst-bytes 262144
```

Shaper check (32 MiB TCP p0→p1, RTT hold = 0): **0.1 Gbit/s → 0.105 Gbit/s**,
**1.0 → 1.051 Gbit/s**, unlimited path **1.734 Gbit/s**. With RTT hold, a single
stream is also window-limited (1 ms probe **0.97 Gbit/s**, 5 ms probe
**0.24 Gbit/s**).

Dedicated BRPC re-run (1 warmup + 3 measured). FactoryMem is the previous
in-process reference (no TCP, so neither RTT nor the 1 Gbit/s cap apply).
ABY3 exact = `A2B → ARShiftB → B2A`. `a2b` is vs native ABY3 A2B.

| kernel | FactoryMem vs exact | **BRPC ~1 ms + 1 Gbit/s vs exact** | **BRPC ~5 ms + 1 Gbit/s vs exact** |
| --- | ---: | ---: | ---: |
| `trunc` 2048 el | 3.46× | **15.04×** (246.5 / 16.4 ms) | **17.58×** (941.4 / 53.6 ms) |
| `linear` 128×64 mmul+trunc | 5.12× | **14.45×** (175.3 / 12.1 ms) | **14.62×** (776.7 / 53.1 ms) |
| `a2b` vs native ABY3 A2B | 2.74× | **12.09×** (99.4 / 8.2 ms) | **14.24×** (362.3 / 25.4 ms) |

Measured ping: **1.36 ms** / **5.44 ms**. Bytes/actions unchanged (`trunc`
13 040 028 / 867 vs exact 1 441 792 / 52). ABY3 semi at 1 ms+1 Gbit/s is
still ~168× on `trunc` (246.5 / 1.47 ms) — kept because it is cheap.

Capping at 1 Gbit/s does **not** move the exact-trunc ratio: these kernels are
round-dominated (ripple ~189 AND rounds vs Kogge-Stone ~14; `sent_actions`
867 vs 52 is the 3-party Send sum, not round depth), and the uncapped veth
path was only ~1.7 Gbit/s. Ratios match the earlier uncapped 1 ms / 5 ms
tables (15.1× / 17.5× on `trunc`). The ≤5× exact budget remains FactoryMem-only.

JSON: [`results/vs_aby3_exact_1gbit.json`](results/vs_aby3_exact_1gbit.json),
[`results-1gbit/summary.json`](results-1gbit/summary.json).

## SPDZwise RING vs ABY3 exact at ~5 ms

**≤5× vs ABY3 exact does not hold at ~5 ms RTT on 3-process FactoryBrpc.**

ABY3 exact is `b2a(arshift_b(a2b(x), 16))` — the truncation used in the branch
PPML reports — not ABY3 semi `TruncAPr2`. SPDZwise RING uses default
`TruncNaive` (same A2B → shift → B2A shape, with MAC/ABFL). `a2b` has no
exact-trunc variant; that row is SPDZwise A2B vs native ABY3 A2B.

The **~5 ms** column is a dedicated re-run (2026-10-31 12:34 UTC, measured ping
**5.431 ms**, one-way hold 2.5 ms, 1 warmup + 3 measured). The **~1 ms** column
is the original sweep (measured ping **1.343 ms**), kept for context. FactoryMem
is in-process and has no injected RTT.

| kernel | FactoryMem vs exact | BRPC ~1 ms vs exact | **BRPC ~5 ms vs exact (re-run)** | SPDZwise ms @5 ms (min–max) | ABY3 exact ms @5 ms (min–max) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `trunc` 2048 el | 3.46× | 15.13× | **17.52×** | 953.6 (951.5–970.6) | 54.4 (53.9–56.4) |
| `linear` 128×64 mmul+trunc | 5.12× | 14.23× | **14.69×** | 788.8 (784.0–799.8) | 53.7 (52.2–56.4) |
| `a2b` 2048 el (vs native ABY3 A2B) | 2.74× | 12.01× | **14.33×** | 354.2 (352.6–354.6) | 24.7 (24.6–25.1) |

Bytes/actions are unchanged from the original sweep (three-party sum, timed
kernel only): `trunc` 13 040 028 / 867 vs exact 1 441 792 / 52; `linear`
1 328 466 / 882 vs 93 184 / 55; `a2b` 5 092 032 / 369 vs 688 128 / 24.

The 5 ms re-run matches the first pass (`trunc` 17.56× then, 17.52× now).
Raising RTT from ~1 ms to ~5 ms does **not** bring SPDZwise within 5× of ABY3
exact: both sides grow with latency, and SPDZwise still has ~13× more
AND-round depth on `trunc` (ripple ~189 vs Kogge-Stone ~14; 867 vs 52 is
the 3-party Send sum), so the ratio stays in the mid-teens. The ≤5×
exact-trunc budget only appears on **FactoryMem** (`trunc` 3.46×, `linear`
5.12×), which cannot see injected RTT.

JSON: [`results/vs_aby3_exact.json`](results/vs_aby3_exact.json),
[`results-5ms-rerun/summary.json`](results-5ms-rerun/summary.json).

## ≤5× vs ABY3 semi at LAN-like RTT ≲1 ms

**It does not hold.**

On this one-VM, three-process FactoryBrpc path, SPDZwise RING (`Z_2^128` internally,
external FM64) is **~8–175×** ABY3 semi at every injected RTT, including ≲1 ms:

| kernel (non-tiny batch) | FactoryMem vs semi | BRPC ~0 ms vs semi | BRPC ~1 ms vs semi | BRPC ~1 ms vs ABY3 exact |
| --- | ---: | ---: | ---: | ---: |
| `trunc` (2048 el) | 78.7× | 158.9× | **135.1×** | 15.1× |
| `linear` (128×64 mmul+trunc) | 16.7× | 65.0× | **83.1×** | 14.2× |
| `a2b` (2048 el) | **2.74×** | 8.40× | **12.0×** | — |

The only ≤5× cell vs ABY3 semi under **RCA** was in-process FactoryMem `a2b`
(2.74×), which has no TCP and no injected RTT. After Kogge–Stone that cell
is **9.29×**.

Against **ABY3 exact** truncation (`A2B → ARShiftB → B2A`, the baseline used in
the branch PPML tables), RCA FactoryMem `trunc` is **3.46×** and FactoryMem
`linear` is **5.12×**. Kogge–Stone **loses** those FactoryMem cells (15.8× /
9.3×) because ABFL AND-count rises ~7×. On BRPC, KS **linear** is the only
kernel that moves toward 5× (**7.81×** @1 ms, **6.25×** @5 ms); `trunc` /
`a2b` get worse (~26× / ~20×) as 5× more bytes plus ABFL swamp the 189→23
round cut. Extra RTT does **not** close the gap to ABY3 semi:
SPDZwise `trunc` is still hundreds of times slower than ABY3 semi
`TruncAPr2` (~2 rounds / 56 KiB, 5 `sent_actions` 3-party sum).

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
| SPDZwise | RING, external FM64, `check_threshold=5_000_000`, default `TruncNaive` (bit-sliced KS A2B) |
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

### 1 Gbit/s cap (exact commands)

Preferred, if the kernel has TBF (this VM does not:
`# CONFIG_NET_SCH_TBF is not set`, `# CONFIG_NET_SCH_HTB is not set`):

```sh
# one qdisc per party host-side veth (full-duplex 1 Gbit/s NIC)
for i in 0 1 2; do
  sudo tc qdisc replace dev veth${i}h root tbf rate 1gbit burst 256kb latency 50ms
done
```

That fails here with `Specified qdisc kind is unknown`. Working equivalent —
same veth + netns topology, userspace token bucket in `delay_switch.py`
(per-party ingress and egress, burst 256 KiB):

```sh
RATE_GBPS=1 BURST_BYTES=262144 RTT_MS=1 bash analysis/rtt-sweep/netem.sh up
# → sudo python3 delay_switch.py --one-way-ms 0.5 --rate-gbps 1 --burst-bytes 262144 \
#      --host-macs <p0,p1,p2 MACs> --ready-file /tmp/spu-rtt/delay-switch.ready
# sweep wrapper:
python3 run_sweep.py --skip-mem --output results-1gbit --rate-gbps 1 \
  --rtt-ms 1,5 --ops trunc,linear,a2b --protocols spdzwise,aby3-exact,aby3
```

`netem.sh` still tries `tc qdisc replace dev lo root tbf rate 1gbit burst 256kb latency 50ms`
first, then falls back. Probe (32 MiB TCP p0→p1, hold=0): **0.1 → 0.105 Gbit/s**,
**1.0 → 1.051 Gbit/s**, unlimited **1.734 Gbit/s**. With RTT hold a single stream
is also window-limited (1 ms **0.97 Gbit/s**, 5 ms **0.24 Gbit/s**).

## Wall-clock tables

Median of 3 measured iterations (warmup discarded). `sent_bytes` /
`sent_actions` are the **three-party sum** of YACL `Send*` calls over the timed
kernel only (not critical-path rounds; see above). Ratios are SPDZwise / ABY3.

### `trunc` (2048 FM64 elements, shift 16)

| setting | meas. ping ms | SPDZwise ms | ABY3 semi ms | ABY3 exact ms | vs semi | vs exact | wise bytes / actions | semi bytes / actions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| factory-mem | — | 9.235 | 0.117 | 2.672 | 78.7× | 3.46× | 13 040 028 / 867 | 57 344 / 5 |
| brpc 0.0 | 0.245 | 95.510 | 0.601 | 9.433 | 158.9× | 10.13× | 13 040 028 / 867 | 57 344 / 5 |
| brpc 0.5 | 0.841 | 183.586 | 1.053 | 13.997 | 174.3× | 13.12× | 13 040 028 / 867 | 57 344 / 5 |
| brpc 1.0 | 1.343 | 256.991 | 1.903 | 16.990 | 135.1× | 15.13× | 13 040 028 / 867 | 57 344 / 5 |
| **brpc 1.0 + 1 Gbit/s** | 1.360 | 246.494 | 1.470 | 16.385 | 167.7× | **15.04×** | 13 040 028 / 867 | 57 344 / 5 |
| brpc 2.0 | 2.384 | 405.355 | 2.438 | 25.580 | 166.3× | 15.85× | 13 040 028 / 867 | 57 344 / 5 |
| brpc 5.0 | 5.444 | 952.456 | 5.838 | 54.235 | 163.1× | 17.56× | 13 040 028 / 867 | 57 344 / 5 |
| **brpc 5.0 + 1 Gbit/s** | 5.441 | 941.420 | 5.920 | 53.555 | 159.0× | **17.58×** | 13 040 028 / 867 | 57 344 / 5 |
| brpc 10.0 | 10.514 | 1797.067 | 11.087 | 99.910 | 162.1× | 17.99× | 13 040 028 / 867 | 57 344 / 5 |

ABY3 exact bytes/actions: 1 441 792 / 52 (constant across settings).

### `linear` (128×64 · 64×1 mmul + trunc)

| setting | meas. ping ms | SPDZwise ms | ABY3 semi ms | ABY3 exact ms | vs semi | vs exact | wise bytes / actions | semi bytes / actions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| factory-mem | — | 3.616 | 0.217 | 0.706 | 16.7× | 5.12× | 1 328 466 / 882 | 6 656 / 8 |
| brpc 0.0 | 0.245 | 47.723 | 0.734 | 3.728 | 65.0× | 12.80× | 1 328 466 / 882 | 6 656 / 8 |
| brpc 0.5 | 0.841 | 112.453 | 1.342 | 7.982 | 83.8× | 14.09× | 1 328 466 / 882 | 6 656 / 8 |
| brpc 1.0 | 1.343 | 177.004 | 2.129 | 12.443 | 83.1× | 14.23× | 1 328 466 / 882 | 6 656 / 8 |
| **brpc 1.0 + 1 Gbit/s** | 1.360 | 175.341 | 1.996 | 12.134 | 87.8× | **14.45×** | 1 328 466 / 882 | 6 656 / 8 |
| brpc 2.0 | 2.384 | 322.450 | 3.700 | 22.216 | 87.2× | 14.51× | 1 328 466 / 882 | 6 656 / 8 |
| brpc 5.0 | 5.444 | 779.772 | 8.414 | 53.969 | 92.7× | 14.45× | 1 328 466 / 882 | 6 656 / 8 |
| **brpc 5.0 + 1 Gbit/s** | 5.441 | 776.665 | 9.215 | 53.143 | 84.3× | **14.62×** | 1 328 466 / 882 | 6 656 / 8 |
| brpc 10.0 | 10.514 | 1498.310 | 16.216 | 102.316 | 92.4× | 14.64× | 1 328 466 / 882 | 6 656 / 8 |

### `a2b` (2048 elements)

| setting | meas. ping ms | SPDZwise ms | ABY3 semi ms | vs semi | wise bytes / actions | semi bytes / actions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| factory-mem | — | 3.430 | 1.252 | 2.74× | 5 092 032 / 369 | 688 128 / 24 |
| brpc 0.0 | 0.245 | 44.963 | 5.351 | 8.40× | 5 092 032 / 369 | 688 128 / 24 |
| brpc 0.5 | 0.841 | 72.929 | 6.994 | 10.43× | 5 092 032 / 369 | 688 128 / 24 |
| brpc 1.0 | 1.343 | 94.747 | 7.890 | 12.01× | 5 092 032 / 369 | 688 128 / 24 |
| **brpc 1.0 + 1 Gbit/s** | 1.360 | 99.382 | 8.221 | **12.09×** | 5 092 032 / 369 | 688 128 / 24 |
| brpc 2.0 | 2.384 | 169.734 | 13.741 | 12.35× | 5 092 032 / 369 | 688 128 / 24 |
| brpc 5.0 | 5.444 | 353.367 | 24.664 | 14.33× | 5 092 032 / 369 | 688 128 / 24 |
| **brpc 5.0 + 1 Gbit/s** | 5.441 | 362.289 | 25.445 | **14.24×** | 5 092 032 / 369 | 688 128 / 24 |
| brpc 10.0 | 10.514 | 674.939 | 45.551 | 14.82× | 5 092 032 / 369 | 688 128 / 24 |

Uncapped BRPC rows are from `results/summary.json`. **1 Gbit/s** rows are the
dedicated re-run in `results-1gbit/` (FactoryMem is unchanged — no TCP). Raw
per-run CSVs live next to those summaries.

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

# 4. 1 Gbit/s cap + ~1 ms / ~5 ms BRPC (tc tbf unavailable → userspace bucket)
python3 run_sweep.py --skip-mem --output results-1gbit --rate-gbps 1 \
  --count 2048 --reps 3 --rows 128 --cols 64 --threads 16 \
  --rtt-ms 1,5 --ops trunc,linear,a2b --protocols spdzwise,aby3-exact,aby3

# 5. After switching Add() to bit-sliced Kogge-Stone: FactoryMem + BRPC
#    ~1 ms / ~5 ms with 1 Gbit/s cap
python3 run_sweep.py --output results-ks --rate-gbps 1 \
  --count 2048 --reps 3 --rows 128 --cols 64 --threads 16 \
  --rtt-ms 1,5 --ops trunc,linear,a2b --protocols spdzwise,aby3-exact,aby3
```

Single 3-process run without the sweep driver:

```sh
RTT_MS=1 RATE_GBPS=1 BURST_BYTES=262144 bash netem.sh up
# target ping RTT = 1ms; one-way hold = 0.5ms; 1 Gbit/s per-party token bucket
PROTOCOL=spdzwise OP=linear TRANSPORT=brpc COUNT=2048 REPS=3 ROWS=128 COLS=64 \
  PARTIES=10.10.0.1:61540,10.10.0.2:61541,10.10.0.3:61542 \
  YACL_NUM_THREADS=16 bash run_3pc.sh
bash netem.sh down
```

## Blockers / caveats

- **No `tc netem` / `tbf` / `htb`** (`CONFIG_NET_SCH_{NETEM,TBF,HTB}` unset).
  Userspace L2 delay + token bucket is the documented fallback; measured ping
  tracks the target within ~0.3–0.8 ms plus switch overhead (~0.25 ms at hold=0).
  The 1 Gbit/s cap is verified at hold=0 (1.051 Gbit/s); with RTT hold a single
  TCP stream is also window-limited.
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
| `analysis/rtt-sweep/delay_switch.py` | AF_PACKET one-way hold + optional per-party token bucket |
| `analysis/rtt-sweep/summarize.py` | tables from `summary.json` |
| `analysis/rtt-sweep/results/` | original sweep CSVs + `summary.json` |
| `analysis/rtt-sweep/results/vs_aby3_exact.json` | FactoryMem / ~1 ms / ~5 ms vs ABY3 exact |
| `analysis/rtt-sweep/results-5ms-rerun/` | dedicated ~5 ms BRPC re-run |
| `analysis/rtt-sweep/results-1gbit/` | BRPC ~1 ms / ~5 ms with 1 Gbit/s cap |
| `analysis/rtt-sweep/results/vs_aby3_exact_1gbit.json` | 1 Gbit/s vs ABY3 exact table |
| `analysis/rtt-sweep/results/actions_vs_rounds.json` | `sent_actions` vs true round-depth breakdown (RCA) |
| `analysis/rtt-sweep/results/actions_vs_rounds_ks.json` | same breakdown after Kogge–Stone |
| `analysis/rtt-sweep/results/vs_aby3_exact_ks.json` | FactoryMem / ~1 ms / ~5 ms vs exact after KS |
| `analysis/rtt-sweep/results-ks/` | KS re-run CSVs + `summary.json` |
| `analysis/rtt-sweep/measure_tput.py` | 32 MiB TCP probe through the switch |
| `src/libspu/mpc/spdzwise/benchmarks/mparty_rtt_bench.cc` | SPDZwise / ABY3 / ABY3-exact kernels |
