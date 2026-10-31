#!/usr/bin/env bash
# Launch three localhost party processes for mparty_rtt_bench.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
BENCH="$ROOT/src/libspu/mpc/spdzwise/benchmarks"
BIN="${BIN:-$BENCH/bazel-bin/mparty_rtt_bench}"
PROTOCOL=${PROTOCOL:-spdzwise}
OP=${OP:-trunc}
COUNT=${COUNT:-4096}
REPS=${REPS:-3}
ROWS=${ROWS:-256}
COLS=${COLS:-64}
TRANSPORT=${TRANSPORT:-brpc}
PARTIES=${PARTIES:-127.0.0.1:61540,127.0.0.1:61541,127.0.0.1:61542}
YACL_NUM_THREADS=${YACL_NUM_THREADS:-16}
TIMEOUT_SEC=${TIMEOUT_SEC:-600}
OUT_DIR=${OUT_DIR:-/tmp/spu-rtt-one}
mkdir -p "$OUT_DIR"

if [[ ! -x "$BIN" ]]; then
  echo "missing binary $BIN" >&2
  exit 1
fi

export YACL_NUM_THREADS
base=(
  "$BIN"
  "--protocol=$PROTOCOL"
  "--op=$OP"
  "--count=$COUNT"
  "--reps=$REPS"
  "--rows=$ROWS"
  "--cols=$COLS"
  "--transport=$TRANSPORT"
)

if [[ "$TRANSPORT" == "mem" ]]; then
  "${base[@]}" | tee "$OUT_DIR/${PROTOCOL}_${OP}_mem.csv"
  exit 0
fi

wrap_rank() {
  local rank=$1
  shift
  if [[ "$PARTIES" == 10.10.0.* ]]; then
    sudo ip netns exec "p${rank}" env YACL_NUM_THREADS="$YACL_NUM_THREADS" "$@"
  else
    env YACL_NUM_THREADS="$YACL_NUM_THREADS" "$@"
  fi
}

kill_parties() {
  for rank in 0 1 2; do
    if [[ -f "$OUT_DIR/rank${rank}.pid" ]]; then
      kill "$(cat "$OUT_DIR/rank${rank}.pid")" 2>/dev/null || true
    fi
  done
  pkill -f mparty_rtt_bench 2>/dev/null || true
}

# Drop a previous crashed mesh so the bind is free.
pkill -f mparty_rtt_bench 2>/dev/null || true
sleep 0.3

for rank in 1 2; do
  wrap_rank "$rank" "${base[@]}" --rank="$rank" --parties="$PARTIES" \
    >"$OUT_DIR/${PROTOCOL}_${OP}_rank${rank}.log" 2>&1 &
  echo $! >"$OUT_DIR/rank${rank}.pid"
  sleep 0.2
done

# Rank 0 prints the CSV on stdout (three-party max wall clock).
wrap_rank 0 "${base[@]}" --rank=0 --parties="$PARTIES" \
  >"$OUT_DIR/${PROTOCOL}_${OP}_rank0.stdout" \
  2>"$OUT_DIR/${PROTOCOL}_${OP}_rank0.log" &
echo $! >"$OUT_DIR/rank0.pid"
r0=$(cat "$OUT_DIR/rank0.pid")
deadline=$((SECONDS + TIMEOUT_SEC))
status=0
while kill -0 "$r0" 2>/dev/null; do
  if (( SECONDS >= deadline )); then
    echo "rank0 timed out after ${TIMEOUT_SEC}s" >&2
    status=124
    kill_parties
    break
  fi
  sleep 0.2
done
if [[ $status -eq 0 ]]; then
  wait "$r0" || status=$?
fi
for rank in 1 2; do
  if [[ -f "$OUT_DIR/rank${rank}.pid" ]]; then
    wait "$(cat "$OUT_DIR/rank${rank}.pid")" || true
  fi
done
if [[ $status -ne 0 ]]; then
  echo "rank0 failed; logs:" >&2
  tail -n 40 "$OUT_DIR/${PROTOCOL}_${OP}_rank0.log" >&2 || true
  tail -n 20 "$OUT_DIR/${PROTOCOL}_${OP}_rank1.log" >&2 || true
  tail -n 20 "$OUT_DIR/${PROTOCOL}_${OP}_rank2.log" >&2 || true
  exit $status
fi
cp "$OUT_DIR/${PROTOCOL}_${OP}_rank0.stdout" "$OUT_DIR/${PROTOCOL}_${OP}.csv"
cat "$OUT_DIR/${PROTOCOL}_${OP}.csv"
