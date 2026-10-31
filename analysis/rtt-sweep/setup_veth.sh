#!/usr/bin/env bash
# Three netns + veth pairs. Each party process runs in p0/p1/p2 so 10.10.0.{1,2,3}
# are NOT local to one another (otherwise Linux would hairpin via lo and skip
# the delay switch).
set -euo pipefail

PREFIX=${PREFIX:-10.10.0}
MTU=${MTU:-1500}

cleanup() {
  for i in 0 1 2; do
    ip netns del "p$i" 2>/dev/null || true
    ip link del "veth${i}s" 2>/dev/null || true
    ip link del "veth${i}h" 2>/dev/null || true
  done
}

if [[ "${1:-}" == "down" ]]; then
  cleanup
  exit 0
fi

cleanup
sysctl -w net.ipv4.ip_forward=0 >/dev/null
sysctl -w net.ipv4.conf.all.rp_filter=0 >/dev/null

for i in 0 1 2; do
  ip netns add "p$i"
  ip link add "veth${i}s" type veth peer name "veth${i}h"
  ip link set "veth${i}h" netns "p$i"
  ip link set "veth${i}s" up mtu "$MTU" promisc on
  ip netns exec "p$i" ip link set lo up
  ip netns exec "p$i" ip link set "veth${i}h" up mtu "$MTU"
  # AF_PACKET forwarding does not honor veth checksum/GSO offload. Without
  # this, ICMP ping works but TCP SYN is dropped (bad checksum).
  ethtool -K "veth${i}s" tx off rx off tso off gso off gro off sg off 2>/dev/null || true
  ip netns exec "p$i" ethtool -K "veth${i}h" tx off rx off tso off gso off gro off sg off 2>/dev/null || true
  ip netns exec "p$i" ip addr add "${PREFIX}.$((i + 1))/24" dev "veth${i}h"
  ip netns exec "p$i" sysctl -w net.ipv4.conf.all.rp_filter=0 >/dev/null
  ip netns exec "p$i" sysctl -w "net.ipv4.conf.veth${i}h.rp_filter=0" >/dev/null
  # Connected /24 route is created by the address; do not add it again.
done

MAC_FILE=${MAC_FILE:-/tmp/spu-rtt/macs.txt}
mkdir -p "$(dirname "$MAC_FILE")"
chmod 777 "$(dirname "$MAC_FILE")" 2>/dev/null || true
: >"$MAC_FILE"
for i in 0 1 2; do
  ip netns exec "p$i" cat "/sys/class/net/veth${i}h/address" >>"$MAC_FILE"
done
echo "party MACs (p0 p1 p2):"
cat "$MAC_FILE"
echo "netns party addresses:"
for i in 0 1 2; do
  echo -n "p$i: "
  ip netns exec "p$i" ip -4 addr show veth${i}h | awk '/inet / {print $2}'
done
echo "switch-side in root ns:"
ip -br link show | awk '/veth[0-2]s/'
