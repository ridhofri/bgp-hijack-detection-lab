#!/usr/bin/env bash
# lint.sh — validasi sintaks semua configs/*/frr.conf via vtysh dry-run
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/.env"
IMG="quay.io/frrouting/frr:${FRR_TAG}"

check() {  # $1 = path absolut file konfigurasi
  docker run --rm --entrypoint vtysh \
    -v "$1:/etc/frr/frr.conf:ro" -v /dev/null:/etc/frr/vtysh.conf:ro \
    "$IMG" -C 2>&1
}

# 1) Self-test: validator WAJIB menolak konfigurasi rusak
bad=$(mktemp)
printf 'router bgp 65000\n neighbr 192.0.2.1 remote-as 65001\n' > "$bad"
if check "$bad" >/dev/null; then
  echo "ABORT: validator TIDAK menolak config rusak — hasil lint tidak bisa dipercaya"
  rm -f "$bad"; exit 2
fi
rm -f "$bad"; echo "SELF-TEST OK  (config rusak ditolak)"

# 2) Lint semua router
fail=0
for conf in "$ROOT"/configs/*/frr.conf; do
  node=$(basename "$(dirname "$conf")")
  if out=$(check "$conf"); then
    echo "PASS  $node"
  else
    echo "FAIL  $node"; echo "$out" | sed 's/^/      /'; fail=1
  fi
done
exit $fail
