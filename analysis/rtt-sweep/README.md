# Local 3-party SPDZwise vs ABY3 RTT sweep

See [REPORT.md](REPORT.md) for the measured wall-clock ratios, the ≤5×
statement, and exact commands.

Quick start (from this directory, after building
`//:mparty_rtt_bench` in `src/libspu/mpc/spdzwise/benchmarks`):

```sh
# RTT_MS is the *target ping RTT*. One-way hold is RTT/2.
# This VM has CONFIG_NET_SCH_NETEM=n, so netem.sh uses veth + delay_switch.py.
python3 run_sweep.py --output results \
  --count 2048 --reps 3 --rows 128 --cols 64 --threads 16 \
  --rtt-ms 0,0.5,1,2,5,10 --ops trunc,linear,a2b
python3 summarize.py results/summary.json

# Focused re-run vs ABY3 exact trunc at target ping RTT = 5 ms:
python3 run_sweep.py --skip-mem --output results-5ms-rerun \
  --count 2048 --reps 3 --rows 128 --cols 64 --threads 16 \
  --rtt-ms 5 --ops trunc,linear,a2b --protocols spdzwise,aby3-exact,aby3

# 1 Gbit/s cap + RTT (tc tbf is unavailable on this kernel):
RATE_GBPS=1 RTT_MS=1 bash netem.sh up    # or python3 run_sweep.py --rate-gbps 1 ...
python3 run_sweep.py --skip-mem --output results-1gbit --rate-gbps 1 \
  --count 2048 --reps 3 --rows 128 --cols 64 --threads 16 \
  --rtt-ms 1,5 --ops trunc,linear,a2b --protocols spdzwise,aby3-exact,aby3

# After switching RING Add() to bit-sliced Kogge-Stone:
python3 run_sweep.py --output results-ks --rate-gbps 1 \
  --count 2048 --reps 3 --rows 128 --cols 64 --threads 16 \
  --rtt-ms 1,5 --ops trunc,linear,a2b --protocols spdzwise,aby3-exact,aby3
```

Three processes always bind `127.0.0.1` or `10.10.0.{1,2,3}` on one host.
Do not start three VMs.
