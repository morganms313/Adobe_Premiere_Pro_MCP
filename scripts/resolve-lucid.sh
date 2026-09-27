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
# Usage:   scripts/resolve-lucid.sh [--keep-window] "lucid://filespace/file/ID/Name"
# Output:  the resolved /Volumes/... path on stdout (exit 0), or an error.
#
# The Finder window the reveal opens is closed again once the path is read (only
# windows that did not exist before the call). --keep-window leaves it open.
# Leftovers from older runs: scripts/close-lucid-finder-windows.sh

set -euo pipefail

keep_window=0
if [[ "${1:-}" == "--keep-window" ]]; then keep_window=1; shift; fi

url="${1:-}"
if [[ -z "$url" ]]; then
  echo "usage: $0 [--keep-window] 'lucid://...'" >&2
  exit 2
fi
if [[ "$url" != lucid://* ]]; then
  echo "error: not a lucid:// URL: $url" >&2
  exit 2
fi

# Snapshot the Finder windows that already exist, so we only ever close the one(s)
# this reveal opens -- never a window Morgan had open himself.
before="$(osascript -e 'tell application "Finder" to get id of every Finder window' 2>/dev/null || true)"

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

# Close the Finder window(s) the reveal opened (ids not in the pre-open snapshot).
# Runs on failure too, so a miss doesn't leave a window behind either.
close_new_windows() {
  [[ "$keep_window" == 1 ]] && return 0
  osascript - "$before" >/dev/null 2>&1 <<'OSA' || true
on run argv
  set beforeIds to item 1 of argv
  tell application "Finder"
    -- index backwards: `every Finder window` also enumerates tabs/hidden browsers
    repeat with i from (count of Finder windows) to 1 by -1
      set w to Finder window i
      set wid to (id of w) as text
      if (", " & beforeIds & ", ") does not contain (", " & wid & ", ") then close w
    end repeat
  end tell
end run
OSA
}

if [[ -z "$path" ]]; then
  close_new_windows
  echo "error: Finder did not surface the item (not synced, or app not running?)" >&2
  exit 1
fi

close_new_windows
printf '%s\n' "$path"
