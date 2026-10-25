#!/usr/bin/env bash
# client_setup.sh - Local machine SSH config setup for Colab / Kaggle SSH connection
#
# Usage:
#   ./client_setup.sh [OPTIONS]
#
# Options:
#   -p, --provider PROVIDER   Tunnel provider: 'cloudflared' or 'ngrok'
#   -h, --host HOSTNAME       Tunnel hostname (e.g. xyz.trycloudflare.com or 0.tcp.ngrok.io)
#   -P, --port PORT           Port number (for ngrok, e.g. 12345; defaults to 22 for cloudflared)
#   -u, --user USERNAME       Remote SSH username (default: dev)
#   -a, --alias ALIAS         SSH Host alias (default: colab-ssh)
#   -i, --identity FILE       Local SSH identity file (default: ~/.ssh/id_ed25519 or ~/.ssh/id_rsa)
#   --help                    Show help message

set -euo pipefail

# Default values
PROVIDER=""
HOSTNAME=""
PORT=""
SSH_USER="dev"
ALIAS="colab-ssh"
IDENTITY_FILE=""

# Helper log functions
log() {
    echo -e "[+] $1"
}

log_warn() {
    echo -e "[!] $1"
}

log_err() {
    echo -e "[-] ERROR: $1" >&2
}

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Options:
  -p, --provider PROVIDER   Tunnel provider: 'cloudflared' or 'ngrok'
  -h, --host HOSTNAME       Tunnel hostname (e.g. xyz.trycloudflare.com or 0.tcp.ngrok.io)
  -P, --port PORT           Port number (for ngrok, e.g. 12345; defaults to 22 for cloudflared)
  -u, --user USERNAME       Remote SSH username (default: dev)
  -a, --alias ALIAS         SSH Host alias (default: colab-ssh)
  -i, --identity FILE       Local SSH identity file (default: auto-detected)
  --help                    Show help message

Examples:
  Cloudflare Quick/Named Tunnel:
    $0 --provider cloudflared --host foo.trycloudflare.com --user dev

  ngrok TCP Tunnel:
    $0 --provider ngrok --host 0.tcp.ngrok.io --port 12345 --user dev
EOF
}

# Parse CLI flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--provider)
            PROVIDER="$2"
            shift 2
            ;;
        -h|--host)
            HOSTNAME="$2"
            shift 2
            ;;
        -P|--port)
            PORT="$2"
            shift 2
            ;;
        -u|--user)
            SSH_USER="$2"
            shift 2
            ;;
        -a|--alias)
            ALIAS="$2"
            shift 2
            ;;
        -i|--identity)
            IDENTITY_FILE="$2"
            shift 2
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            log_err "Unknown parameter: $1"
            usage
            exit 1
            ;;
    esac
done

# Prompt interactively if required options are missing
if [[ -z "$PROVIDER" ]]; then
    echo "Select Tunnel Provider:"
    echo "  1) Cloudflare Tunnel (cloudflared)"
    echo "  2) ngrok"
    read -rp "Choice (1 or 2, default: 1): " choice
    if [[ "$choice" == "2" ]]; then
        PROVIDER="ngrok"
    else
        PROVIDER="cloudflared"
    fi
fi

PROVIDER=$(echo "$PROVIDER" | tr '[:upper:]' '[:lower:]')
if [[ "$PROVIDER" != "cloudflared" && "$PROVIDER" != "ngrok" ]]; then
    log_err "Provider must be 'cloudflared' or 'ngrok'."
    exit 1
fi

if [[ -z "$HOSTNAME" ]]; then
    read -rp "Enter tunnel hostname (e.g. xyz.trycloudflare.com or 0.tcp.ngrok.io): " HOSTNAME
fi

if [[ -z "$HOSTNAME" ]]; then
    log_err "Hostname is required."
    exit 1
fi

if [[ "$PROVIDER" == "ngrok" && -z "$PORT" ]]; then
    read -rp "Enter ngrok port number: " PORT
fi

if [[ "$PROVIDER" == "cloudflared" && -z "$PORT" ]]; then
    PORT="22"
fi

if [[ -z "$PORT" ]]; then
    log_err "Port is required."
    exit 1
fi

# Auto-detect identity file if not provided
if [[ -z "$IDENTITY_FILE" ]]; then
    if [[ -f "$HOME/.ssh/id_ed25519" ]]; then
        IDENTITY_FILE="$HOME/.ssh/id_ed25519"
    elif [[ -f "$HOME/.ssh/id_rsa" ]]; then
        IDENTITY_FILE="$HOME/.ssh/id_rsa"
    else
        log_warn "No default SSH key (~/.ssh/id_ed25519 or ~/.ssh/id_rsa) found."
        read -rp "Enter path to local SSH private key file: " IDENTITY_FILE
    fi
fi

# Expand tilde in IDENTITY_FILE if present
IDENTITY_FILE="${IDENTITY_FILE/#\~/$HOME}"

if [[ ! -f "$IDENTITY_FILE" ]]; then
    log_err "Identity file does not exist at path: $IDENTITY_FILE"
    exit 1
fi

# Ensure ~/.ssh directory exists with correct permissions
SSH_DIR="$HOME/.ssh"
if [[ ! -d "$SSH_DIR" ]]; then
    log "Creating $SSH_DIR directory..."
    mkdir -p "$SSH_DIR"
    chmod 700 "$SSH_DIR"
else
    chmod 700 "$SSH_DIR"
fi

SSH_CONFIG="$SSH_DIR/config"

# Check for cloudflared dependency if using cloudflared
if [[ "$PROVIDER" == "cloudflared" ]]; then
    if ! command -v cloudflared &>/dev/null; then
        log_warn "'cloudflared' binary was not found in your PATH."
        log_warn "To connect using Cloudflare Tunnel, please install cloudflared locally:"
        log_warn "  macOS: brew install cloudflared"
        log_warn "  Linux: https://pkg.cloudflare.com/"
    fi
fi

# Backup existing SSH config file if present
if [[ -f "$SSH_CONFIG" ]]; then
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="${SSH_CONFIG}.backup_${TIMESTAMP}"
    log "Backing up existing $SSH_CONFIG to $BACKUP_FILE..."
    cp "$SSH_CONFIG" "$BACKUP_FILE"
    chmod 600 "$BACKUP_FILE"
else
    log "Creating new SSH config file at $SSH_CONFIG..."
    touch "$SSH_CONFIG"
    chmod 600 "$SSH_CONFIG"
fi

# Ensure 600 permissions on SSH config file
chmod 600 "$SSH_CONFIG"

# Prepare SSH Config Block
# Notice: HostKey verification is explicitly preserved (no StrictHostKeyChecking=no or /dev/null).
CONFIG_BLOCK_START="# --- BEGIN ${ALIAS} AUTOMATED CONFIG ---"
CONFIG_BLOCK_END="# --- END ${ALIAS} AUTOMATED CONFIG ---"

if [[ "$PROVIDER" == "cloudflared" ]]; then
    BLOCK=$(cat <<EOF
$CONFIG_BLOCK_START
Host $ALIAS
    HostName $HOSTNAME
    User $SSH_USER
    IdentityFile $IDENTITY_FILE
    ProxyCommand cloudflared access ssh --hostname %h
    # Secure host key checking enabled (TOFU - Trust On First Use)
    StrictHostKeyChecking ask
$CONFIG_BLOCK_END
EOF
)
else
    BLOCK=$(cat <<EOF
$CONFIG_BLOCK_START
Host $ALIAS
    HostName $HOSTNAME
    Port $PORT
    User $SSH_USER
    IdentityFile $IDENTITY_FILE
    # Secure host key checking enabled (TOFU - Trust On First Use)
    StrictHostKeyChecking ask
$CONFIG_BLOCK_END
EOF
)
fi

# Safely replace existing block if present, or append
if grep -q "$CONFIG_BLOCK_START" "$SSH_CONFIG"; then
    log "Updating existing Host configuration '$ALIAS' in $SSH_CONFIG..."
    # Remove existing block using python or awk safely
    python3 -c "
import sys, re
path = sys.argv[1]
start = sys.argv[2]
end = sys.argv[3]
with open(path, 'r') as f:
    content = f.read()
pattern = re.escape(start) + r'.*?' + re.escape(end) + r'\n?'
new_content = re.sub(pattern, '', content, flags=re.DOTALL)
with open(path, 'w') as f:
    f.write(new_content.strip() + '\n\n')
" "$SSH_CONFIG" "$CONFIG_BLOCK_START" "$CONFIG_BLOCK_END"
fi

# Append new block
echo "" >> "$SSH_CONFIG"
echo "$BLOCK" >> "$SSH_CONFIG"
echo "" >> "$SSH_CONFIG"

# Clean up empty lines
chmod 600 "$SSH_CONFIG"

log "SSH configuration successfully updated in $SSH_CONFIG."
echo ""
echo "================================================================="
echo "  LOCAL CLIENT SETUP COMPLETE"
echo "================================================================="
echo "Host Alias: $ALIAS"
echo "Hostname:   $HOSTNAME"
echo "Port:       $PORT"
echo "User:       $SSH_USER"
echo "Identity:   $IDENTITY_FILE"
echo ""
echo "To connect to your remote notebook session, run:"
echo "  ssh $ALIAS"
echo ""
echo "Security Note:"
echo "  Host-key verification is ENFORCED. On your first connection, SSH will ask"
echo "  you to confirm the host key fingerprint (TOFU). Verify and accept it."
echo "================================================================="
