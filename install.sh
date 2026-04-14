#!/usr/bin/env bash
# Nametag A2H Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/nametaginc/nametag-a2h/main/install.sh | bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Color constants
# ---------------------------------------------------------------------------
BOLD='\033[1m'
ACCENT='\033[38;2;99;102;241m'     # indigo
SUCCESS='\033[38;2;34;197;94m'     # green
WARN='\033[38;2;234;179;8m'        # amber
ERROR='\033[38;2;239;68;68m'       # red
MUTED='\033[38;2;107;114;128m'     # gray
INFO='\033[38;2;148;163;184m'      # slate
NC='\033[0m'

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
GUM=""
TMPFILES=()
SETUP_CLAUDE=false
SETUP_OPENCLAW=false
NAMETAG_API_KEY=""
NAMETAG_ENV=""
CLI_PATH=""
SERVER_PATH=""
STAGE_CURRENT=0
STAGE_TOTAL=4

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
cleanup() {
  local exit_code=$?
  for f in "${TMPFILES[@]:-}"; do
    rm -rf "$f" 2>/dev/null || true
  done
  if [[ $exit_code -ne 0 ]]; then
    echo ""
    echo -e "${ERROR}✗${NC} Setup did not complete. Check the messages above."
    echo -e "${MUTED}  Re-run at any time — the script is safe to run multiple times.${NC}"
  fi
}
trap cleanup EXIT

mktempfile() {
  local f
  f="$(mktemp)"
  TMPFILES+=("$f")
  echo "$f"
}

mktempdir() {
  local d
  d="$(mktemp -d)"
  TMPFILES+=("$d")
  echo "$d"
}

# ---------------------------------------------------------------------------
# TTY / interactive checks
# ---------------------------------------------------------------------------
is_promptable() {
  [[ -r /dev/tty && -w /dev/tty ]]
}

require_tty() {
  if ! is_promptable; then
    echo "ERROR: This script requires an interactive terminal (/dev/tty)." >&2
    echo "If piping via curl, run in a real terminal session." >&2
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# UI helpers (gum-aware with plain fallbacks)
# ---------------------------------------------------------------------------
ui_banner() {
  echo ""
  if [[ -n "$GUM" ]]; then
    local title tagline
    title="$("$GUM" style --foreground "#6366f1" --bold "🔐 Nametag A2H Installer")"
    tagline="$("$GUM" style --foreground "#94a3b8" "Identity-verified approvals for AI agents")"
    "$GUM" style --border rounded --border-foreground "#6366f1" --padding "1 2" \
      "$(printf '%s\n%s' "$title" "$tagline")"
  else
    echo -e "${ACCENT}${BOLD}  🔐 Nametag A2H Installer${NC}"
    echo -e "${MUTED}  Identity-verified approvals for AI agents${NC}"
    echo ""
  fi
  echo ""
}

ui_stage() {
  STAGE_CURRENT=$((STAGE_CURRENT + 1))
  local title="[${STAGE_CURRENT}/${STAGE_TOTAL}] $1"
  echo ""
  if [[ -n "$GUM" ]]; then
    "$GUM" style --bold --foreground "#6366f1" "$title"
  else
    echo -e "${ACCENT}${BOLD}${title}${NC}"
  fi
}

ui_section() {
  echo ""
  if [[ -n "$GUM" ]]; then
    "$GUM" style --bold "$1"
  else
    echo -e "${BOLD}$1${NC}"
  fi
}

ui_info() {
  if [[ -n "$GUM" ]]; then
    "$GUM" log --level info "$*"
  else
    echo -e "${MUTED}·${NC} $*"
  fi
}

ui_success() {
  if [[ -n "$GUM" ]]; then
    local mark
    mark="$("$GUM" style --foreground "#22c55e" --bold "✓")"
    echo "${mark} $*"
  else
    echo -e "${SUCCESS}✓${NC} $*"
  fi
}

ui_warn() {
  if [[ -n "$GUM" ]]; then
    "$GUM" log --level warn "$*"
  else
    echo -e "${WARN}!${NC} $*"
  fi
}

ui_error() {
  if [[ -n "$GUM" ]]; then
    "$GUM" log --level error "$*"
  else
    echo -e "${ERROR}✗${NC} $*" >&2
  fi
}

ui_kv() {
  local key="$1" value="$2"
  if [[ -n "$GUM" ]]; then
    local kp vp
    kp="$("$GUM" style --foreground "#6b7280" --width 22 "$key")"
    vp="$("$GUM" style --bold "$value")"
    "$GUM" join --horizontal "$kp" "$vp"
  else
    echo -e "${MUTED}${key}:${NC} ${value}"
  fi
}

ui_panel() {
  local content="$1"
  if [[ -n "$GUM" ]]; then
    "$GUM" style --border rounded --border-foreground "#6b7280" --padding "0 1" "$content"
  else
    echo ""
    while IFS= read -r line; do
      echo "  $line"
    done <<< "$content"
    echo ""
  fi
}

run_quiet_step() {
  local title="$1"; shift
  local log
  log="$(mktempfile)"

  if [[ -n "$GUM" ]]; then
    local cmd_quoted log_quoted
    printf -v cmd_quoted '%q ' "$@"
    printf -v log_quoted '%q' "$log"
    if "$GUM" spin --spinner dot --title "$title" -- bash -c "${cmd_quoted}>${log_quoted} 2>&1"; then
      return 0
    fi
  else
    echo -e "${MUTED}  ${title}...${NC}"
    if "$@" >"$log" 2>&1; then
      return 0
    fi
  fi

  ui_error "${title} failed"
  if [[ -s "$log" ]]; then
    tail -n 40 "$log" >&2 || true
  fi
  return 1
}

# ---------------------------------------------------------------------------
# gum bootstrap (optional — plain bash fallback if unavailable)
# ---------------------------------------------------------------------------
GUM_VERSION="0.17.0"

_gum_arch() {
  case "$(uname -m)" in
    x86_64|amd64) echo "x86_64" ;;
    arm64|aarch64) echo "arm64" ;;
    *) echo "unknown" ;;
  esac
}

bootstrap_gum() {
  # Already on PATH
  if command -v gum >/dev/null 2>&1; then
    GUM="gum"; return 0
  fi
  # Need a real TTY for gum's raw mode
  if ! [[ -t 1 ]] || ! is_promptable; then
    return 1
  fi
  local arch os asset base gum_dir gum_path checksums
  arch="$(_gum_arch)"
  os="Darwin"
  [[ "$arch" == "unknown" ]] && return 1

  asset="gum_${GUM_VERSION}_${os}_${arch}.tar.gz"
  base="https://github.com/charmbracelet/gum/releases/download/v${GUM_VERSION}"
  gum_dir="$(mktempdir)"

  if ! curl -fsSL --retry 2 -o "${gum_dir}/${asset}" "${base}/${asset}" 2>/dev/null; then
    return 1
  fi
  checksums="$(mktempfile)"
  if ! curl -fsSL --retry 2 -o "$checksums" "${base}/checksums.txt" 2>/dev/null; then
    return 1
  fi
  # Verify checksum
  if command -v shasum >/dev/null 2>&1; then
    if ! (cd "$gum_dir" && shasum -a 256 --ignore-missing -c "$checksums" >/dev/null 2>&1); then
      return 1
    fi
  fi
  if ! tar -xzf "${gum_dir}/${asset}" -C "$gum_dir" >/dev/null 2>&1; then
    return 1
  fi
  gum_path="$(find "$gum_dir" -type f -name gum 2>/dev/null | head -n1 || true)"
  [[ -z "$gum_path" ]] && return 1
  chmod +x "$gum_path" 2>/dev/null || true
  [[ -x "$gum_path" ]] || return 1
  GUM="$gum_path"
}

# ---------------------------------------------------------------------------
# Homebrew helpers
# ---------------------------------------------------------------------------
resolve_brew() {
  if command -v brew >/dev/null 2>&1; then command -v brew; return 0; fi
  [[ -x "/opt/homebrew/bin/brew" ]] && echo "/opt/homebrew/bin/brew" && return 0
  [[ -x "/usr/local/bin/brew" ]]    && echo "/usr/local/bin/brew"    && return 0
  return 1
}

activate_brew() {
  local b
  b="$(resolve_brew 2>/dev/null || true)"
  [[ -n "$b" ]] && eval "$("$b" shellenv)" || true
}

# ---------------------------------------------------------------------------
# Phase 1: macOS guard + dependencies
# ---------------------------------------------------------------------------
check_macos() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "ERROR: This installer only supports macOS." >&2
    exit 1
  fi
  ui_success "macOS detected ($(sw_vers -productVersion 2>/dev/null || echo 'unknown'))"
}

prompt_yn() {
  # Usage: prompt_yn "Question" default_y_or_n
  local question="$1"
  local default="${2:-n}"
  local answer
  if [[ -n "$GUM" ]]; then
    if "$GUM" confirm "$question" </dev/tty; then
      echo "y"
    else
      echo "n"
    fi
    return
  fi
  if [[ "$default" == "y" ]]; then
    echo -ne "${question} [Y/n] " >/dev/tty
  else
    echo -ne "${question} [y/N] " >/dev/tty
  fi
  read -r answer </dev/tty || true
  answer="${answer:-$default}"
  echo "${answer:0:1}" | tr '[:upper:]' '[:lower:]'
}

ensure_homebrew() {
  if resolve_brew >/dev/null 2>&1; then
    activate_brew
    ui_success "Homebrew $(brew --version 2>/dev/null | head -1 | awk '{print $2}')"
    return 0
  fi

  ui_warn "Homebrew not found — required to install Python and pipx"
  echo ""
  local ans
  ans="$(prompt_yn "Install Homebrew now?" n)"
  if [[ "$ans" != "y" ]]; then
    echo ""
    ui_panel "$(printf 'To install Homebrew manually:\n  /bin/bash -c "$(curl -fsSL https://brew.sh/install.sh)"\nThen re-run this installer.')"
    exit 1
  fi

  ui_info "Installing Homebrew (this may take a few minutes)..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/tty
  activate_brew
  if ! resolve_brew >/dev/null 2>&1; then
    ui_error "Homebrew install failed"
    ui_panel "$(printf 'Install manually:\n  /bin/bash -c "$(curl -fsSL https://brew.sh/install.sh)"\nThen re-run this installer.')"
    exit 1
  fi
  ui_success "Homebrew installed"
}

_python_version_ok() {
  local bin="$1"
  local ver
  ver="$("$bin" -c 'import sys; print(sys.version_info.major * 100 + sys.version_info.minor)' 2>/dev/null || echo 0)"
  [[ "$ver" -ge 310 ]]
}

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && _python_version_ok "$candidate"; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

ensure_python() {
  if find_python >/dev/null 2>&1; then
    local py ver
    py="$(find_python)"
    ver="$("$py" --version 2>&1 | awk '{print $2}')"
    export PIPX_DEFAULT_PYTHON="$(command -v "$py")"
    ui_success "Python ${ver}"
    return 0
  fi

  # Show what we found (if any)
  if command -v python3 >/dev/null 2>&1; then
    local cur_ver
    cur_ver="$(python3 --version 2>&1 | awk '{print $2}')"
    ui_warn "Python ${cur_ver} found but 3.10+ is required"
  else
    ui_warn "Python not found — 3.10+ is required"
  fi

  echo ""
  local ans
  ans="$(prompt_yn "Install Python 3.13 via Homebrew?" n)"
  if [[ "$ans" != "y" ]]; then
    echo ""
    ui_panel "$(printf 'To install Python manually:\n  brew install python@3.13\n  -- or --\n  Download from: https://www.python.org/downloads/\nThen re-run this installer.')"
    exit 1
  fi

  local brew_bin
  brew_bin="$(resolve_brew)"
  run_quiet_step "Installing Python 3.13" "$brew_bin" install python@3.13
  activate_brew
  hash -r 2>/dev/null || true

  if ! find_python >/dev/null 2>&1; then
    ui_error "Python 3.10+ still not found after install"
    ui_panel "$(printf 'Try:\n  brew install python@3.13\nThen open a new terminal and re-run.')"
    exit 1
  fi
  local py ver
  py="$(find_python)"
  ver="$("$py" --version 2>&1 | awk '{print $2}')"
  export PIPX_DEFAULT_PYTHON="$(command -v "$py")"
  ui_success "Python ${ver} installed"
}

ensure_pipx() {
  if command -v pipx >/dev/null 2>&1; then
    ui_success "pipx $(pipx --version 2>/dev/null | head -1)"
    return 0
  fi

  ui_warn "pipx not found — required to install nametag-a2h"
  echo ""
  local ans
  ans="$(prompt_yn "Install pipx via Homebrew?" n)"
  if [[ "$ans" != "y" ]]; then
    echo ""
    ui_panel "$(printf 'To install pipx manually:\n  brew install pipx && pipx ensurepath\nThen open a new terminal and re-run.')"
    exit 1
  fi

  local brew_bin
  brew_bin="$(resolve_brew)"
  run_quiet_step "Installing pipx" "$brew_bin" install pipx
  run_quiet_step "Configuring pipx PATH" pipx ensurepath

  # Make pipx available in this session
  export PATH="$HOME/.local/bin:$PATH"
  hash -r 2>/dev/null || true

  if ! command -v pipx >/dev/null 2>&1; then
    ui_error "pipx not found after install"
    ui_panel "$(printf 'Try:\n  brew install pipx && pipx ensurepath\nThen open a new terminal and re-run.')"
    exit 1
  fi
  ui_success "pipx $(pipx --version 2>/dev/null | head -1) installed"
}

# ---------------------------------------------------------------------------
# Phase 2: agent selection
# ---------------------------------------------------------------------------
select_agents() {
  local has_claude=false has_openclaw=false

  command -v claude >/dev/null 2>&1 && has_claude=true
  command -v openclaw >/dev/null 2>&1 && has_openclaw=true

  echo ""
  if [[ -n "$GUM" ]]; then
    local selection
    selection="$("$GUM" choose \
      --header "Which agent(s) would you like to configure?" \
      --cursor-prefix "❯ " \
      "Claude Code" \
      "OpenClaw" \
      "Both" </dev/tty || true)"
    case "$selection" in
      "Claude Code") SETUP_CLAUDE=true ;;
      "OpenClaw")    SETUP_OPENCLAW=true ;;
      "Both")        SETUP_CLAUDE=true; SETUP_OPENCLAW=true ;;
      *) ui_error "No selection made"; exit 1 ;;
    esac
  else
    echo -e "${BOLD}Which agent(s) would you like to configure?${NC}"
    echo "  1) Claude Code"
    echo "  2) OpenClaw"
    echo "  3) Both"
    echo ""
    local choice attempt=0
    while true; do
      attempt=$((attempt + 1))
      [[ $attempt -gt 3 ]] && { ui_error "No valid choice made"; exit 1; }
      echo -n "Enter 1, 2, or 3: " >/dev/tty
      read -r choice </dev/tty || true
      case "$choice" in
        1) SETUP_CLAUDE=true; break ;;
        2) SETUP_OPENCLAW=true; break ;;
        3) SETUP_CLAUDE=true; SETUP_OPENCLAW=true; break ;;
        *) echo "Please enter 1, 2, or 3." >/dev/tty ;;
      esac
    done
  fi

  # Validate selected agents are installed
  if [[ "$SETUP_CLAUDE" == true ]] && ! $has_claude; then
    echo ""
    ui_warn "Claude Code CLI (claude) not found"
    ui_panel "$(printf 'Install Claude Code from:\n  https://claude.ai/download\n\nAfter installing, re-run this installer to configure the MCP server.\nOr run manually:\n  claude mcp add nametag-a2h <server-path> -e NAMETAG_API_KEY=... -e NAMETAG_ENV=...')"
    if [[ "$SETUP_OPENCLAW" == false ]]; then
      exit 1
    fi
    ui_warn "Skipping Claude Code configuration — continuing with OpenClaw"
    SETUP_CLAUDE=false
  fi

  if [[ "$SETUP_OPENCLAW" == true ]] && ! $has_openclaw; then
    echo ""
    ui_warn "OpenClaw CLI (openclaw) not found"
    ui_panel "$(printf 'Install OpenClaw first:\n  curl -fsSL https://openclaw.ai/install.sh | bash\n\nThen re-run this installer to configure nametag-a2h.')"
    if [[ "$SETUP_CLAUDE" == false ]]; then
      exit 1
    fi
    ui_warn "Skipping OpenClaw configuration — continuing with Claude Code"
    SETUP_OPENCLAW=false
  fi

  if [[ "$SETUP_CLAUDE" == false && "$SETUP_OPENCLAW" == false ]]; then
    ui_error "No agents available to configure"
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Phase 3: Nametag credentials
# ---------------------------------------------------------------------------
collect_credentials() {
  echo ""
  ui_panel "$(printf 'You will need:\n  API key:   console.nametag.co → Your Environment → API Keys\n             (shown only once at creation — copy it now if you haven'\''t)\n  Env name:  The environment name as shown in the console\n             e.g. "A2H Agent Approvals" or "Production"')"

  # API key (echo suppressed)
  while true; do
    if [[ -n "$GUM" ]]; then
      NAMETAG_API_KEY="$("$GUM" input \
        --password \
        --placeholder "paste your API key" \
        --prompt "  Nametag API key › " </dev/tty || true)"
    else
      echo -n "  Nametag API key (hidden): " >/dev/tty
      read -rs NAMETAG_API_KEY </dev/tty
      echo "" >/dev/tty
    fi
    NAMETAG_API_KEY="${NAMETAG_API_KEY//[[:space:]]/}"
    [[ -n "$NAMETAG_API_KEY" ]] && break
    ui_warn "API key cannot be empty"
  done
  ui_success "API key received"

  # Environment name
  while true; do
    if [[ -n "$GUM" ]]; then
      NAMETAG_ENV="$("$GUM" input \
        --placeholder 'e.g. A2H Agent Approvals' \
        --prompt "  Environment name › " </dev/tty || true)"
    else
      echo -n "  Nametag environment name: " >/dev/tty
      read -r NAMETAG_ENV </dev/tty
    fi
    # Trim leading/trailing whitespace
    NAMETAG_ENV="$(echo "$NAMETAG_ENV" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [[ -n "$NAMETAG_ENV" ]] && break
    ui_warn "Environment name cannot be empty"
  done
  ui_success "Environment: ${NAMETAG_ENV}"

  export NAMETAG_API_KEY
  export NAMETAG_ENV
}

# ---------------------------------------------------------------------------
# Phase 4a: package install
# ---------------------------------------------------------------------------
install_package() {
  # Check if already installed
  if pipx list 2>/dev/null | grep -q "nametag-a2h"; then
    echo ""
    local ans
    ans="$(prompt_yn "nametag-a2h is already installed. Reinstall?" n)"
    if [[ "$ans" == "y" ]]; then
      run_quiet_step "Uninstalling nametag-a2h" pipx uninstall nametag_a2h
    else
      ui_info "Using existing installation"
      return 0
    fi
  fi

  local script_dir=""
  if [[ -n "${BASH_SOURCE[0]:-}" && "${BASH_SOURCE[0]}" != "bash" ]]; then
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
  fi

  if [[ -n "$script_dir" && -f "$script_dir/pyproject.toml" ]]; then
    run_quiet_step "Installing nametag-a2h (local)" pipx install "$script_dir"
  else
    run_quiet_step "Installing nametag-a2h" \
      pipx install "git+https://github.com/nametaginc/nametag-a2h.git"
  fi

  # Ensure binaries are on PATH
  export PATH="$HOME/.local/bin:$PATH"
  hash -r 2>/dev/null || true

  if ! command -v nametag-a2h >/dev/null 2>&1; then
    ui_error "nametag-a2h CLI not found after install"
    ui_panel "$(printf 'Try:\n  pipx install "git+https://github.com/nametaginc/nametag-a2h.git"\n  pipx ensurepath\nThen open a new terminal and re-run.')"
    exit 1
  fi
  if ! command -v nametag-a2h-server >/dev/null 2>&1; then
    ui_error "nametag-a2h-server not found after install"
    exit 1
  fi

  CLI_PATH="$(command -v nametag-a2h)"
  SERVER_PATH="$(command -v nametag-a2h-server)"
  ui_success "nametag-a2h installed (${CLI_PATH})"
}

# ---------------------------------------------------------------------------
# Phase 4b: agent configuration
# ---------------------------------------------------------------------------
_json_escape() {
  # Escape " and \ for embedding in JSON strings
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

configure_claude() {
  ui_section "Configuring Claude Code"

  # Check if already registered
  if claude mcp list 2>/dev/null | grep -q "nametag-a2h"; then
    local ans
    ans="$(prompt_yn "nametag-a2h is already registered with Claude Code. Reconfigure?" n)"
    if [[ "$ans" != "y" ]]; then
      ui_info "Keeping existing Claude Code MCP registration"
      return 0
    fi
    claude mcp remove nametag-a2h 2>/dev/null || true
  fi

  if run_quiet_step "Registering MCP server with Claude Code" \
    claude mcp add nametag-a2h "$SERVER_PATH" \
      -e "NAMETAG_API_KEY=${NAMETAG_API_KEY}" \
      -e "NAMETAG_ENV=${NAMETAG_ENV}"; then
    ui_success "Registered nametag-a2h with Claude Code"
  else
    ui_error "Failed to register with Claude Code"
    ui_panel "$(printf 'Run manually:\n  claude mcp add nametag-a2h "%s" \\\n    -e NAMETAG_API_KEY=<your-key> \\\n    -e NAMETAG_ENV=<your-env>' "$SERVER_PATH")"
  fi
}

configure_openclaw() {
  ui_section "Configuring OpenClaw"

  local escaped_key escaped_env
  escaped_key="$(_json_escape "$NAMETAG_API_KEY")"
  escaped_env="$(_json_escape "$NAMETAG_ENV")"
  local server_json
  server_json="{\"command\":\"${SERVER_PATH}\",\"env\":{\"NAMETAG_API_KEY\":\"${escaped_key}\",\"NAMETAG_ENV\":\"${escaped_env}\"}}"

  # Step 1: MCP server config
  if run_quiet_step "Setting MCP server config" \
    openclaw config set mcp.servers.nametag-a2h "$server_json" --strict-json; then
    ui_success "MCP server config set"
  else
    ui_error "Failed to set MCP server config"
    return 1
  fi

  # Step 2: Plugin install (only if running from local clone)
  local script_dir=""
  if [[ -n "${BASH_SOURCE[0]:-}" && "${BASH_SOURCE[0]}" != "bash" ]]; then
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
  fi

  if [[ -n "$script_dir" && -d "$script_dir/openclaw-plugin" ]]; then
    if run_quiet_step "Installing OpenClaw plugin" \
      openclaw plugins install -l "$script_dir/openclaw-plugin"; then
      ui_success "OpenClaw plugin installed"
    else
      ui_warn "Plugin install failed — slash commands (/nametag-enroll etc.) won't be available"
      ui_info "Install manually: openclaw plugins install -l <path-to>/openclaw-plugin"
    fi
  else
    ui_warn "Plugin directory not available (curl-pipe install)"
    ui_info "For OpenClaw slash commands, clone the repo and run:"
    ui_info "  git clone https://github.com/nametaginc/nametag-a2h"
    ui_info "  bash nametag-a2h/install.sh"
  fi

  # Step 3: Enable plugin (merge into existing list)
  local existing_plugins new_plugins
  existing_plugins="$(openclaw config get plugins.allow 2>/dev/null || echo '[]')"
  existing_plugins="$(echo "$existing_plugins" | tr -d '[:space:]')"
  if [[ "$existing_plugins" == "null" || "$existing_plugins" == "" ]]; then
    existing_plugins="[]"
  fi

  # Check if already in list
  if echo "$existing_plugins" | grep -q '"nametag-a2h"'; then
    ui_info "Plugin already in plugins.allow"
  else
    new_plugins="$(python3 -c "
import json, sys
try:
    lst = json.loads('${existing_plugins}')
    if not isinstance(lst, list):
        lst = []
except Exception:
    lst = []
if 'nametag-a2h' not in lst:
    lst.append('nametag-a2h')
print(json.dumps(lst))
")"
    if run_quiet_step "Enabling nametag-a2h plugin" \
      openclaw config set plugins.allow "$new_plugins" --strict-json; then
      ui_success "Plugin enabled"
    else
      ui_warn "Could not enable plugin automatically"
      ui_info "Run: openclaw config set plugins.allow '[\"nametag-a2h\"]' --strict-json"
    fi
  fi

  # Step 4: Restart gateway
  local ans
  ans="$(prompt_yn "Restart OpenClaw gateway now? (required for changes to take effect)" y)"
  if [[ "$ans" == "y" ]]; then
    if run_quiet_step "Restarting OpenClaw gateway" openclaw gateway restart; then
      ui_success "Gateway restarted"
      # Brief wait for gateway to become healthy
      local attempts=0
      while [[ $attempts -lt 5 ]]; do
        sleep 2
        if openclaw gateway status 2>/dev/null | grep -qi "running\|healthy\|online"; then
          ui_success "Gateway healthy"
          break
        fi
        attempts=$((attempts + 1))
      done
    else
      ui_warn "Gateway restart failed — restart manually: openclaw gateway restart"
    fi
  else
    ui_warn "Remember to restart the gateway: openclaw gateway restart"
  fi
}

# ---------------------------------------------------------------------------
# Phase 4c: enrollment
# ---------------------------------------------------------------------------
enroll_identity() {
  ui_section "Enrolling your identity"

  # Check existing enrollment
  local status_out
  status_out="$(NAMETAG_API_KEY="$NAMETAG_API_KEY" NAMETAG_ENV="$NAMETAG_ENV" \
    "$CLI_PATH" status 2>/dev/null || true)"

  if echo "$status_out" | grep -qi "Enrolled:"; then
    local enrolled_name
    enrolled_name="$(echo "$status_out" | sed 's/Enrolled: //')"
    echo ""
    ui_success "Already enrolled: ${enrolled_name}"
    local ans
    ans="$(prompt_yn "Re-enroll with a different identity?" n)"
    [[ "$ans" != "y" ]] && return 0
  fi

  # Collect phone number
  local phone attempt=0
  while true; do
    attempt=$((attempt + 1))
    [[ $attempt -gt 3 ]] && { ui_error "Too many invalid attempts"; exit 1; }

    if [[ -n "$GUM" ]]; then
      phone="$("$GUM" input \
        --placeholder '+15551234567' \
        --prompt "  Phone number (international format) › " </dev/tty || true)"
    else
      echo -n "  Phone number (e.g. +15551234567): " >/dev/tty
      read -r phone </dev/tty
    fi
    phone="$(echo "$phone" | tr -d '[:space:]')"

    if [[ "$phone" =~ ^\+[1-9][0-9]{6,14}$ ]]; then
      break
    fi
    ui_warn "Invalid format — use international format starting with + (e.g. +15551234567)"
  done

  echo ""
  ui_panel "$(printf 'CHECK YOUR PHONE\n\nYou will receive an SMS with a verification link.\nOpen the link → scan your government ID → take a selfie.\n\nThis window will wait up to 5 minutes for you to complete it.')"
  echo ""

  # Run enrollment — the Python CLI handles all polling internally
  exec </dev/tty
  if NAMETAG_API_KEY="$NAMETAG_API_KEY" NAMETAG_ENV="$NAMETAG_ENV" \
    "$CLI_PATH" enroll "$phone"; then
    echo ""
    ui_success "Identity enrolled"
  else
    echo ""
    ui_warn "Enrollment did not complete"
    ui_info "You can retry at any time:"
    ui_info "  NAMETAG_API_KEY=... NAMETAG_ENV=... nametag-a2h enroll $phone"
  fi
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print_summary() {
  echo ""
  echo ""
  if [[ -n "$GUM" ]]; then
    "$GUM" style --bold --foreground "#22c55e" "✓ Setup complete!"
  else
    echo -e "${SUCCESS}${BOLD}✓ Setup complete!${NC}"
  fi
  echo ""

  local status_out
  status_out="$(NAMETAG_API_KEY="$NAMETAG_API_KEY" NAMETAG_ENV="$NAMETAG_ENV" \
    "$CLI_PATH" status 2>/dev/null || echo "status unavailable")"
  local enrolled_info
  enrolled_info="$(echo "$status_out" | sed 's/Enrolled: //')"

  ui_kv "Identity" "$enrolled_info"
  [[ "$SETUP_CLAUDE"   == true ]] && ui_kv "Claude Code MCP" "nametag-a2h registered"
  [[ "$SETUP_OPENCLAW" == true ]] && ui_kv "OpenClaw MCP"    "nametag-a2h registered"
  ui_kv "CLI installed" "$CLI_PATH"

  echo ""
  if [[ -n "$GUM" ]]; then
    "$GUM" style --bold "Try it:"
  else
    echo -e "${BOLD}Try it:${NC}"
  fi

  if [[ "$SETUP_CLAUDE" == true ]]; then
    echo ""
    ui_info "In a Claude Code session:"
    ui_info "  \"Delete all files in /tmp/test-dir\""
    ui_info "  Claude will pause and send a verification request to your phone."
  fi
  if [[ "$SETUP_OPENCLAW" == true ]]; then
    echo ""
    ui_info "In OpenClaw:"
    ui_info "  \"Delete the old backup files\""
    ui_info "  The agent will request identity verification before proceeding."
  fi

  echo ""
  ui_info "Docs: https://github.com/nametaginc/nametag-a2h"
  echo ""
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
  require_tty
  bootstrap_gum 2>/dev/null || true
  ui_banner

  ui_stage "Dependencies"
  check_macos
  ensure_homebrew
  ensure_python
  ensure_pipx

  ui_stage "Agent setup"
  select_agents

  ui_stage "Nametag credentials"
  collect_credentials

  ui_stage "Install & configure"
  install_package

  if [[ "$SETUP_CLAUDE" == true ]]; then
    configure_claude
  fi
  if [[ "$SETUP_OPENCLAW" == true ]]; then
    configure_openclaw
  fi

  enroll_identity
  print_summary
}

# Don't run if the script is being sourced or tested
if [[ "${NAMETAG_A2H_INSTALL_SH_NO_RUN:-0}" != "1" ]]; then
  main "$@"
fi
