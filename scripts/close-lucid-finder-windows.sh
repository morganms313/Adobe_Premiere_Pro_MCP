#!/usr/bin/env bash
# close-lucid-finder-windows.sh — end-of-job cleanup: close Finder windows left open on
# the LucidLink volumes (lucid:// reveals, delivery folders opened for checking).
#
# Only windows whose folder is on one of the LucidLink volumes are touched; anything
# else open in Finder (Desktop, Downloads, local drives) is left alone.
#
# Usage:   scripts/close-lucid-finder-windows.sh           # close them, print what closed
#          scripts/close-lucid-finder-windows.sh --list    # dry run, close nothing
# Volumes: LUCID_VOLUMES="crunchyroll,marketing" (default) — Finder volume names.
#
# Implementation notes (macOS 15 Finder):
#  * `POSIX path of (target of w as alias)` FAILS for LucidLink (File Provider) folders;
#    `(target of w) as text` works and yields an HFS path "crunchyroll:mvo:…", so we
#    match on the leading volume name.
#  * `repeat with w in every Finder window` enumerates tabs/hidden browsers (39 items
#    for 5 windows); index 1..(count of Finder windows) instead, backwards when closing.

set -euo pipefail

mode="close"
[[ "${1:-}" == "--list" ]] && mode="list"
vols="${LUCID_VOLUMES:-crunchyroll,marketing}"

osascript - "$mode" "$vols" <<'OSA'
on run argv
  set mode to item 1 of argv
  set AppleScript's text item delimiters to ","
  set volList to text items of (item 2 of argv)
  set AppleScript's text item delimiters to ""
  set report to {}
  tell application "Finder"
    repeat with i from (count of Finder windows) to 1 by -1
      set w to Finder window i
      set p to ""
      try
        set p to (target of w) as text
      end try
      set hit to false
      repeat with v in volList
        if p starts with ((v as text) & ":") then set hit to true
      end repeat
      if hit then
        set end of report to (name of w) & "  —  " & p
        if mode is "close" then close w
      end if
    end repeat
  end tell
  set verb to "closed"
  if mode is "list" then set verb to "would close"
  set AppleScript's text item delimiters to linefeed
  set out to verb & " " & (count of report) & " LucidLink Finder window(s)"
  if (count of report) > 0 then set out to out & linefeed & (report as text)
  set AppleScript's text item delimiters to ""
  return out
end run
OSA
