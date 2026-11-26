#!/usr/bin/env bash
# Host test for the bring-up root device's geometry. Same shape as scripts/test-storage.sh: a plain C++
# compiler with sanitizers, no IOKit, so it runs anywhere the repository's checks run.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT=${1:-$ROOT/build/ramblock-tests}
CXX=${CXX:-c++}
mkdir -p "$OUT"
"$CXX" -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined \
  -I "$ROOT/drivers/NativeRamBlock" \
  "$ROOT/drivers/NativeRamBlock/RamBlockCore.cpp" \
  "$ROOT/drivers/NativeRamBlock/Test/check-ram-block-core.cpp" -o "$OUT/check-ram-block-core"
"$OUT/check-ram-block-core"
