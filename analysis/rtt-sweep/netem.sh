#!/usr/bin/env bash
# Apply synthetic RTT.
#
# Preferred: `tc qdisc ... netem delay <one-way>` on lo or a veth.
# This VM's kernel is built with CONFIG_NET_SCH_NETEM=n, so that path is
# expected to fail. The fallback is three veth pairs plus analysis/rtt-sweep/
# delay_switch.py, which holds every forwarded Ethernet frame for <one-way>.
#
# Convention (same as netem): --rtt-ms is the *target ping RTT*. The one-way
# hold time is RTT/2. ping A->B then is ~RTT.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")" && pwd)
STATE_DIR=${STATE_DIR:-/tmp/spu-rtt}
mkdir -p "$STATE_DIR"
chmod 777 "$STATE_DIR" 2>/dev/null || true
RTT_MS=${RTT_MS:-0}
ACTION=${1:-up}
PID_FILE=${PID_FILE:-$STATE_DIR/delay-switch.pid}
READY_FILE=${READY_FILE:-$STATE_DIR/delay-switch.ready}
SWITCH_LOG=${SWITCH_LOG:-$STATE_DIR/delay-switch.log}
BACKEND_FILE=${BACKEND_FILE:-$STATE_DIR/backend.txt}
MAC_FILE=${MAC_FILE:-$STATE_DIR/macs.txt}

clear_tc() {
  tc qdisc del dev lo root 2>/dev/null || true
}

stop_switch() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid=$(cat "$PID_FILE" || true)
    if [[ -n "${pid:-}" ]]; then
      sudo kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
    sudo rm -f "$PID_FILE"
  fi
    sudo pkill -f 'delay_switch.py' 2>/dev/null || true
  sudo rm -f "$READY_FILE" 2>/dev/null || rm -f "$READY_FILE" || true
}

if [[ "$ACTION" == "down" ]]; then
  clear_tc
  stop_switch
  sudo -n "$ROOT/setup_veth.sh" down 2>/dev/null || "$ROOT/setup_veth.sh" down 2>/dev/null || true
  exit 0
fi

if [[ "$ACTION" != "up" ]]; then
  echo "usage: $0 up|down   (RTT_MS=<ping-rtt-milliseconds>)" >&2
  exit 2
fi

one_way=$(python3 - <<PY
rtt=float("$RTT_MS")
print(max(0.0, rtt / 2.0))
PY
)

echo "target ping RTT=${RTT_MS}ms ; one-way hold=${one_way}ms"

write_backend() {
  printf '%s\n' "$1" | sudo tee "$BACKEND_FILE" >/dev/null
  printf '%s\n' "$1" | sudo tee /tmp/spu-rtt-backend.txt >/dev/null || true
}

# Try real netem first (works on kernels with CONFIG_NET_SCH_NETEM=y).
if [[ "$(python3 -c "print(float('$RTT_MS')>0)")" == "True" ]]; then
  if sudo tc qdisc replace dev lo root netem delay "${one_way}ms" \
      2> >(sudo tee /tmp/spu-tc-netem.err >/dev/null); then
    echo "using tc netem on lo: delay ${one_way}ms one-way"
    tc qdisc show dev lo
    ping -c 5 -n 127.0.0.1 | tail -2
    write_backend "NETEM_BACKEND=tc-lo"
    exit 0
  fi
  echo "tc netem unavailable: $(sudo tr '\n' ' ' </tmp/spu-tc-netem.err 2>/dev/null || true)"
fi

stop_switch
MAC_FILE="$MAC_FILE" sudo "$ROOT/setup_veth.sh" up
macs=$(for i in 0 1 2; do sudo ip netns exec p$i cat /sys/class/net/veth${i}h/address; done | paste -sd,)
sudo rm -f "$READY_FILE"
sudo python3 "$ROOT/delay_switch.py" --one-way-ms "$one_way" --host-macs "$macs" \
  --ready-file "$READY_FILE" >"$SWITCH_LOG" 2>&1 &
echo $! | sudo tee "$PID_FILE" >/dev/null
for _ in $(seq 1 50); do
  if [[ -f "$READY_FILE" ]]; then
    break
  fi
  sleep 0.05
done
if [[ ! -f "$READY_FILE" ]]; then
  echo "delay switch did not become ready:" >&2
  sudo cat "$SWITCH_LOG" >&2 || true
  exit 1
fi
echo "using veth+netns userspace delay switch; one-way=${one_way}ms"
write_backend "NETEM_BACKEND=veth-netns-userspace one-way-ms=${one_way}"
echo "measured ping p0 -> p1:"
sudo ip netns exec p0 ping -c 8 -n 10.10.0.2 | tail -3
