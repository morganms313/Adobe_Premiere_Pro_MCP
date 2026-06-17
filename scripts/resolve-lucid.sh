#!/usr/bin/env bash
# resolve-lucid.sh — turn a lucid:// link into a real POSIX path (macOS).
#
# LucidLink's lucid:// scheme carries an internal object-ID (e.g. 722:274313),
# NOT a path. Only the LucidLink client can resolve that ID. The trick: hand the
# URL to the OS (`open`), which makes LucidLink reveal the item in Finder, then
# ask Finder for the selection's POSIX path.
#
# Requirements: macOS, LucidLink app installed/running, the target filespace
# mounted, and the item synced/available. Works headless from a shell/agent.
#
# Usage:   scripts/resolve-lucid.sh "lucid://filespace/file/ID/Name"
# Output:  the resolved /Volumes/... path on stdout (exit 0), or an error.

set -euo pipefail

url="${1:-}"
if [[ -z "$url" ]]; then
  echo "usage: $0 'lucid://...'" >&2
  exit 2
fi
if [[ "$url" != lucid://* ]]; then
  echo "error: not a lucid:// URL: $url" >&2
  exit 2
fi

# Hand off to LucidLink (reveals the item in Finder).
open "$url"

# Poll Finder for the revealed item's path (LucidLink can take a moment).
read -r -d '' script <<'OSA' || true
tell application "Finder"
  set sel to selection
  if (count of sel) > 0 then
    return POSIX path of (item 1 of sel as alias)
  else if (count of windows) > 0 then
    return POSIX path of (target of front window as alias)
  else
    return ""
  end if
end tell
OSA

path=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  path="$(osascript -e "$script" 2>/dev/null || true)"
  [[ -n "$path" ]] && break
  /bin/sleep 0.5
done

if [[ -z "$path" ]]; then
  echo "error: Finder did not surface the item (not synced, or app not running?)" >&2
  exit 1
fi

printf '%s\n' "$path"
