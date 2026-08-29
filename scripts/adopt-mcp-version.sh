#!/usr/bin/env bash
# adopt-mcp-version.sh — switch the running Premiere MCP between builds, reversibly.
#
# The installed CEP panel is a COPY, not a symlink, so `install-cep` overwrites it
# and the previous panel is only recoverable if you kept it. This backs it up first
# and can put it back byte-for-byte.
#
#   bash scripts/adopt-mcp-version.sh status     # what is installed vs what is on main
#   bash scripts/adopt-mcp-version.sh adopt      # back up, switch to main, build, install
#   bash scripts/adopt-mcp-version.sh rollback   # restore the most recent backup
#
# Premiere must be CLOSED for adopt/rollback — it reads the panel at launch.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
PANEL="$HOME/Library/Application Support/Adobe/CEP/extensions/MCPBridgeCEP"
BACKUPS="$REPO/.mcp-backups"
KNOWN_GOOD_PANEL="8a8cc33"   # 2026-05-16; matches the panel installed on the MBP

md5of() { [ -f "$1" ] && md5 -q "$1" || echo "(absent)"; }

# Identify a panel by CONTENT rather than by a hardcoded commit. KNOWN_GOOD_PANEL
# below is an MBP-specific constant, and no hardcoded commit can be right on both
# machines: the mini's installed panel is 4e6a2f5 (2026-05-21), five days NEWER
# than the MBP's 8a8cc33 (2026-05-16). An md5 mismatch alone cannot tell you which
# way round that is, so map the md5 back to its commit and print the date.
identify_panel() {
  local target="$1" c m
  [ "$target" = "(absent)" ] && { echo "(absent)"; return 0; }
  for c in $(git log --all --format=%H -- cep-plugin/bridge-cep.js); do
    m="$(git show "${c}:cep-plugin/bridge-cep.js" 2>/dev/null | md5 -q)"
    if [ "$m" = "$target" ]; then
      git log -1 --format='%h (%ad) %s' --date=short "$c" | cut -c1-64
      return 0
    fi
  done
  echo "no commit matches — hand-modified, or predates this history"
}

# Resolve what "main" actually means. The authority is origin/main, NOT a local
# `main`: a clone can be sitting ON a local `main` that is far behind, and
# preferring that ref makes `status` compare the installed panel against a stale
# tree and report a false MATCH — i.e. "nothing to adopt" when a new panel is
# waiting. Measured on the office mini 2026-08-29: local main bcaebc9 (72 behind)
# carried the same bridge-cep.js md5 as the installed panel, while origin/main
# (v1.2.4) carried a different one.
# The old comment claimed this fetched; it did not. Now it does, non-fatally.
git fetch -q origin 2>/dev/null || echo "warning: could not fetch origin — refs below may be stale"
if git rev-parse --verify -q origin/main >/dev/null 2>&1; then
  MAINREF="origin/main"
elif git rev-parse --verify -q main >/dev/null 2>&1; then
  MAINREF="main"
  echo "warning: no origin/main here — falling back to local 'main', which may be stale"
else
  echo "Neither 'origin/main' nor 'main' resolves here — run: git fetch origin"; exit 1
fi

case "${1:-status}" in
  status)
    echo "repo branch : $(git branch --show-current)  ($(git rev-parse --short HEAD))"
    echo "dist built  : $([ -f dist/tools/index.js ] && date -r dist/tools/index.js '+%Y-%m-%d %H:%M' || echo '(not built)')"
    echo "panel md5   : $(md5of "$PANEL/bridge-cep.js")"
    echo "  = installed: $(identify_panel "$(md5of "$PANEL/bridge-cep.js")")"
    INSTALLED="$(md5of "$PANEL/bridge-cep.js")"
    MAINMD5="$(git show "${MAINREF}:cep-plugin/bridge-cep.js" | md5 -q)"
    echo "main   md5  : ${MAINMD5}   (${MAINREF} = $(git rev-parse --short "$MAINREF"))"
    echo "  = main     : $(identify_panel "$MAINMD5")"
    echo "known-good  : $(git show "${KNOWN_GOOD_PANEL}:cep-plugin/bridge-cep.js" 2>/dev/null | md5 -q || echo "(commit absent — fetch)")  (${KNOWN_GOOD_PANEL} = the MBP's panel — an MBP-specific constant, NOT a baseline elsewhere)"
    if git rev-parse --verify -q main >/dev/null 2>&1 && git rev-parse --verify -q origin/main >/dev/null 2>&1; then
      BEHIND="$(git rev-list --count main..origin/main 2>/dev/null || echo 0)"
      if [ "${BEHIND:-0}" -gt 0 ]; then
        echo "            NOTE local 'main' is ${BEHIND} behind origin/main and carries $(git show main:cep-plugin/bridge-cep.js | md5 -q) — do not read it as current"
      fi
    fi
    if [ "$INSTALLED" = "$MAINMD5" ]; then
      echo "verdict     : installed panel MATCHES ${MAINREF} — nothing to adopt"
    else
      echo "verdict     : installed panel DIFFERS from ${MAINREF} — 'adopt' would change it"
    fi
    [ -d "$BACKUPS" ] && { echo "backups     :"; ls -1 "$BACKUPS" | sed 's/^/              /'; } || echo "backups     : (none)"
    ;;

  adopt)
    pgrep -x "Adobe Premiere Pro" >/dev/null && { echo "REFUSING: Premiere is running. Quit it first."; exit 1; }
    STAMP="$(date '+%Y%m%d-%H%M%S')"
    DEST="$BACKUPS/$STAMP"
    mkdir -p "$DEST"
    echo "==> backing up to $DEST"
    [ -d "$PANEL" ] && cp -R "$PANEL" "$DEST/MCPBridgeCEP"
    [ -d dist ]     && cp -R dist "$DEST/dist"
    git rev-parse HEAD > "$DEST/HEAD.txt"
    git branch --show-current > "$DEST/BRANCH.txt"
    echo "    panel + dist + origin branch recorded"

    echo "==> switching to main"
    git rev-parse --verify -q main >/dev/null 2>&1 || git checkout -b main --track origin/main
    git checkout main
    git merge --ff-only origin/main 2>/dev/null || true
    npm install --silent
    npm run build
    node dist/cli.js --install-cep

    echo
    echo "==> installed panel now: $(md5of "$PANEL/bridge-cep.js")"
    echo "==> DONE. Two things before you use it:"
    echo "    1. export DO_NOT_TRACK=1   (upstream v1.2.4 ships default-on telemetry)"
    echo "    2. restart Premiere, then confirm the MCP panel loads"
    echo "    Roll back with: bash scripts/adopt-mcp-version.sh rollback"
    ;;

  rollback)
    pgrep -x "Adobe Premiere Pro" >/dev/null && { echo "REFUSING: Premiere is running. Quit it first."; exit 1; }
    LAST="$(ls -1 "$BACKUPS" 2>/dev/null | tail -1 || true)"
    if [ -z "$LAST" ]; then
      echo "No backup found. Falling back to the known-good panel from git (${KNOWN_GOOD_PANEL})."
      echo "WARNING: ${KNOWN_GOOD_PANEL} is the MBP's panel. On another machine this can be a DOWNGRADE —"
      echo "         the mini's own panel is 4e6a2f5 (2026-05-21), newer than ${KNOWN_GOOD_PANEL} (2026-05-16)."
      printf "         continue? [y/N] "; read -r ans; [ "${ans:-N}" = "y" ] || { echo "aborted"; exit 1; }
      git checkout "$KNOWN_GOOD_PANEL" -- cep-plugin/
      npm run build || true
      node dist/cli.js --install-cep || {
        echo "install-cep failed; copying the panel by hand"
        mkdir -p "$PANEL" && cp -R cep-plugin/. "$PANEL/"
      }
      git checkout HEAD -- cep-plugin/
    else
      SRC="$BACKUPS/$LAST"
      echo "==> restoring backup $LAST"
      [ -d "$SRC/MCPBridgeCEP" ] && { rm -rf "$PANEL"; cp -R "$SRC/MCPBridgeCEP" "$PANEL"; }
      [ -d "$SRC/dist" ]        && { rm -rf dist;    cp -R "$SRC/dist" dist; }
      BR="$(cat "$SRC/BRANCH.txt" 2>/dev/null || echo main)"
      echo "==> returning repo to '$BR'"
      git checkout "$BR"
    fi
    echo "==> panel now: $(md5of "$PANEL/bridge-cep.js")"
    echo "==> restart Premiere."
    ;;

  *) echo "usage: $0 {status|adopt|rollback}"; exit 2 ;;
esac
