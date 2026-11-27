#!/usr/bin/env bash
# Re-point a framework submodule whose recorded commit the remote no longer serves.
#
# The framework records one gitlink per driver. NativeMetal's recorded commit (c6d29caa) was force-pushed away on 2026-11-25 and the
# remote answers "not our ref", so `git submodule update` fails and every kernel build stops before compiling -- in the payload job and in
# the kernel job, because each initializes the submodules separately.
#
# This checks each named submodule, and only when the remote really does not serve the recorded commit, re-points that submodule to the
# remote's current head and records the substitution in the framework's index. It never changes the board or the archive list, and it
# prints what it did so the substitution is visible in the build log.

set -euo pipefail

framework="${1:-unixnu}"
shift || true
paths=("$@")
if [ ${#paths[@]} -eq 0 ]; then
  paths=(drivers/NativeMetal)
fi

for path in "${paths[@]}"; do
  recorded=$(git -C "$framework" ls-tree HEAD "$path" | awk '{print $3}')
  url=$(git -C "$framework" config -f .gitmodules --get "submodule.$path.url")
  echo "$path recorded=$recorded url=$url"
  if [ -z "$recorded" ] || [ -z "$url" ]; then
    echo "  no gitlink or no url; nothing to do"
    continue
  fi
  if git ls-remote "$url" "$recorded" | grep -q .; then
    echo "  the recorded commit is still served; nothing to repair"
    continue
  fi
  fallback=$(git ls-remote "$url" HEAD | awk '{print $1}')
  echo "  ::warning::$path is pinned to $recorded, which $url no longer serves; re-pointing to $fallback"
  rm -rf "${framework:?}/$path"
  git clone --depth 1 "$url" "$framework/$path"
  git -C "$framework/$path" checkout --detach "$fallback"
  git -C "$framework" update-index --add --cacheinfo "160000,$fallback,$path"
  echo "  repaired: $path -> $fallback"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    echo "$path was pinned to $recorded (no longer served); built with $fallback" >> "$GITHUB_STEP_SUMMARY"
  fi
done
