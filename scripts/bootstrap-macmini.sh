#!/usr/bin/env bash
#
# bootstrap-macmini.sh — reproduce Morgan's Premiere-MCP + Claude Code setup
# on a fresh macOS machine (office Mac mini).
#
# What this DOES (automatable):
#   - Installs Homebrew (arm64) + both ffmpeg builds (arm64 + x86/Rosetta split-brain)
#   - Installs Node + Claude Code CLI
#   - Clones the three sync repos (this MCP repo, the Obsidian vault, claude-dotfiles)
#   - Builds the MCP server and installs the Premiere CEP bridge (npm run setup:mac)
#   - Symlinks the portable ~/.claude config + project memory from claude-dotfiles
#   - Runs the doctor to verify
#
# What it does NOT do (needs you, in a GUI, with credentials) — printed as a
# checklist at the end:
#   - Adobe Creative Cloud sign-in + Premiere install
#   - `gh auth login` for both GitHub accounts
#   - Re-auth the claude.ai remote MCP connectors (Slack/Gmail/Adobe/Drive/Calendar)
#   - Mount + sign into Lucid
#   - Enable the CEP panel inside Premiere
#
# Usage:  bash scripts/bootstrap-macmini.sh
# Safe to re-run: every step is idempotent / guarded.

set -euo pipefail

# ---- config (edit if your layout differs) ----------------------------------
PROJECTS_DIR="$HOME/Documents/Projects"
MCP_REPO_URL="https://github.com/morganms313/Adobe_Premiere_Pro_MCP.git"
MCP_REPO_DIR="$PROJECTS_DIR/Adobe_Premiere_Pro_MCP"
VAULT_REPO_URL="https://github.com/morganms313/obsidian-vault.git"
VAULT_DIR="$HOME/Obsidian/Vault"
DOTFILES_REPO_URL="https://github.com/morganms313/claude-dotfiles.git"
DOTFILES_DIR="$PROJECTS_DIR/claude-dotfiles"
# ----------------------------------------------------------------------------

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
step() { printf "\n\033[1;36m==> %s\033[0m\n" "$1"; }
warn() { printf "\033[1;33m[!] %s\033[0m\n" "$1"; }

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS only."; exit 1
fi

ARCH="$(uname -m)"  # arm64 on Apple Silicon

# ---- 1. Homebrew (arm64, /opt/homebrew) ------------------------------------
step "Homebrew (arm64)"
if ! command -v /opt/homebrew/bin/brew >/dev/null 2>&1; then
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
eval "$(/opt/homebrew/bin/brew shellenv)"

# ---- 2. ffmpeg split-brain -------------------------------------------------
# Modern ffmpeg (7.x) at /opt/homebrew — transparent ProRes 4444 canvas.
# Legacy ffmpeg (4.2.1) at /usr/local via x86 brew — has the libass build that
# burns .ass subs correctly. BOTH are required (see ass_subtitle_overlay_recipe).
step "ffmpeg (arm64, /opt/homebrew)"
brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg

step "ffmpeg (x86 / Rosetta, /usr/local) — the libass burn-in build"
if [[ "$ARCH" == "arm64" ]]; then
  if ! /usr/bin/pgrep -q oahd 2>/dev/null && ! /usr/sbin/sysctl -n sysctl.proc_translated >/dev/null 2>&1; then
    warn "Rosetta 2 may not be installed. Run: softwareupdate --install-rosetta --agree-to-license"
  fi
  if [[ ! -x /usr/local/bin/brew ]]; then
    warn "x86 Homebrew not found at /usr/local. To install the legacy ffmpeg:"
    echo "      softwareupdate --install-rosetta --agree-to-license"
    echo "      arch -x86_64 /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo "      arch -x86_64 /usr/local/bin/brew install ffmpeg@4    # or tap the 4.2.1 formula you use"
    warn "Skipping x86 ffmpeg auto-install — do the above manually, then re-run."
  else
    arch -x86_64 /usr/local/bin/brew list ffmpeg >/dev/null 2>&1 || \
      warn "/usr/local brew present but ffmpeg not installed there — install your 4.2.1 build manually."
  fi
fi

# ---- 3. Node + Claude Code -------------------------------------------------
step "Node.js (>=18)"
command -v node >/dev/null 2>&1 || brew install node
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[[ "$NODE_MAJOR" -ge 18 ]] || { echo "Node >=18 required, found $(node -v)"; exit 1; }

step "Claude Code CLI"
command -v claude >/dev/null 2>&1 || npm install -g @anthropic-ai/claude-code

step "GitHub CLI"
command -v gh >/dev/null 2>&1 || brew install gh

# ---- 4. Clone the three sync repos -----------------------------------------
step "Cloning repos"
mkdir -p "$PROJECTS_DIR" "$HOME/Obsidian"
[[ -d "$MCP_REPO_DIR/.git" ]]  || git clone "$MCP_REPO_URL" "$MCP_REPO_DIR"
[[ -d "$VAULT_DIR/.git" ]]     || git clone "$VAULT_REPO_URL" "$VAULT_DIR"
[[ -d "$DOTFILES_DIR/.git" ]]  || git clone "$DOTFILES_REPO_URL" "$DOTFILES_DIR"

# ---- 5. Link portable Claude config ----------------------------------------
step "Linking ~/.claude config from claude-dotfiles"
if [[ -x "$DOTFILES_DIR/link.sh" ]]; then
  bash "$DOTFILES_DIR/link.sh"
else
  warn "claude-dotfiles/link.sh not found — skipping config link."
fi

# ---- 5b. Skill runtime deps (cr-image-subtitles QA scripts) ----------------
# The image-sub QA scripts (subcheck/fncheck/fntiming/imgeval/...) need Pillow +
# numpy, and a local vision model served by ollama (qwen2.5vl baseline).
step "Skill runtime deps: ollama, tesseract, Python Pillow/numpy"
brew list ollama >/dev/null 2>&1    || brew install ollama
brew list tesseract >/dev/null 2>&1 || brew install tesseract
python3 -m pip install --quiet --upgrade pip pillow numpy || \
  warn "pip install pillow/numpy failed — install into your preferred Python env manually."

# ---- 6. Build + install the Premiere MCP bridge ----------------------------
step "Building MCP server + installing CEP bridge"
npm run setup:mac --prefix "$MCP_REPO_DIR"

# ---- 7. Verify -------------------------------------------------------------
step "Doctor"
npm run setup:doctor --prefix "$MCP_REPO_DIR" || warn "Doctor reported issues — review above."

# ---- 8. Manual checklist ---------------------------------------------------
cat <<'EOF'

============================================================
  MANUAL STEPS (cannot be scripted — needs GUI + credentials)
============================================================
  [ ] Install + sign into Adobe Creative Cloud, install Premiere Pro 2020+
  [ ] In Premiere: Window > Extensions > MCPBridgeCEP — enable the panel
  [ ] gh auth login   (do BOTH: morganms313 AND morganstarling-pxl)
        Reminder: NEVER push to morganstarling-pxl without an explicit ask.
  [ ] Launch `claude` once so it installs plugins from settings.json
  [ ] Re-auth remote MCP connectors inside Claude Code:
        Slack, Gmail, Google Drive, Google Calendar, Adobe creativity
        (run: claude mcp list   to see auth status)
  [ ] Mount + sign into Lucid cloud storage (the fast-pipe payoff)
  [ ] Copy local brand assets not in git: ~/Downloads/CR_NoReg_Review/ etc.
  [ ] Pull the vision model(s) for the image-sub QA skill (multi-GB — the fast
      office pipe makes this quick):
        ollama serve &            # if not already running as a service
        ollama pull qwen2.5vl:7b  # baseline; optionally also qwen3-vl:8b

  Optional — to use the mini as a REMOTE render/upload node later:
  [ ] System Settings > General > Sharing: enable Screen Sharing + Remote Login
  [ ] Set the mini to auto-login to a GUI session (CEP automation needs a
      live display — bare SSH won't drive Premiere).
============================================================
EOF

bold "Bootstrap complete."
