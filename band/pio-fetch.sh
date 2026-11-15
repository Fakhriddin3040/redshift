#!/usr/bin/env bash
# usage: ./pio-fetch.sh toolchain-riscv32-esp [version]
set -euo pipefail
pkg=$1; ver=${2:-}
api="https://api.registry.platformio.org/v3/packages/platformio/tool/$pkg"

url=$(curl -fsSL "$api" | jq -r --arg v "$ver" '
  .versions[] | select($v == "" or .name == $v) | .files[]
  | select(any(.system[]?; . == "linux_x86_64" or . == "*")) | .download_url' | head -n1)

[ -n "$url" ] || { echo "url not found"; exit 1; }
echo "$url"
aria2c -x16 -s16 -k1M -c -o "$pkg.tar.gz" "$url"
pio pkg install -g -t "file://$PWD/$pkg.tar.gz"