# Secure SSH Access for Google Colab & Kaggle Notebook Runtimes

This repository provides a complete, production-grade, and security-hardened implementation for securely accessing Google Colab and Kaggle notebook runtimes via SSH using either **Cloudflare Tunnel (`cloudflared`)** or **`ngrok`**.

---

## Quick Start: Notebook Cell Setup

Below are clean, ready-to-use notebook cells for Google Colab and Kaggle environments.

### Option A: Google Colab (Recommended)

1. **Set Up Colab Secrets (Key Icon in Left Sidebar)**:
   - Add `SSH_PUBLIC_KEY`: Contents of your `~/.ssh/id_ed25519.pub` file.
   - Add `CLOUDFLARE_TUNNEL_TOKEN` or `TUNNEL_TOKEN` (optional, if using permanent Cloudflare Zero Trust Tunnels).
   - Add `CLOUDFLARE_HOSTNAME` or `TUNNEL_HOSTNAME` (optional, e.g. `colab.yourdomain.com`).
   - Add `NGROK_AUTHTOKEN` (if using ngrok).

2. **Paste and Run in a Colab Notebook Cell**:

```python
# 1. Clone the repository and navigate into it
!git clone https://github.com/abhijitgayen/notebook-ssh.git
%cd notebook-ssh

# 2. Run setup script (automatically detects Colab Secrets)
!python3 setup_notebook.py
```

---

### Option B: Kaggle / Environment Variables One-Liner

If running on Kaggle or without Colab Secrets, pass parameters directly as environment variables in a single clean cell:

```python
import os

# 1. Define required credentials
os.environ["SSH_PUBLIC_KEY"] = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKey user@localhost"
os.environ["TUNNEL_PROVIDER"] = "cloudflared"  # Or "ngrok"
# os.environ["NGROK_AUTHTOKEN"] = "your_ngrok_authtoken" # Required if TUNNEL_PROVIDER="ngrok"

# 2. Clone repo and execute setup
!git clone https://github.com/abhijitgayen/notebook-ssh.git && cd notebook-ssh && python3 setup_notebook.py
```

---

## Cloudflare Permanent Token Support (Named Tunnels)

### How Permanent Cloudflare Tokens Work

Instead of using ephemeral random URLs (like `*.trycloudflare.com`), you can set up a **Permanent Cloudflare Tunnel** (Named Tunnel) attached to your custom domain or Cloudflare Zero Trust account.

#### Benefits:
- **Fixed Hostname**: Always connect to the same custom domain (e.g. `ssh.yourdomain.com`).
- **No Client Reconfiguration**: You run `client_setup.sh` once on your local computer, and you don't need to update `~/.ssh/config` every time a new notebook session starts.
- **Enhanced Security**: Enforce Zero Trust Access policies (SSO, identity verification, IP rules) at Cloudflare's edge before SSH traffic reaches your notebook.

---

### Step-by-Step Guide for Cloudflare Permanent Token

1. **Create a Cloudflare Tunnel**:
   - Go to [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/) -> **Networks** -> **Tunnels**.
   - Click **Add a tunnel** -> Choose **Cloudflare** (`cloudflared`).
   - Name your tunnel (e.g., `colab-ssh-tunnel`).
   - Copy the generated tunnel token (`cloudflared tunnel run --token <YOUR_PERMANENT_TOKEN>`).

2. **Configure Public Hostname**:
   - Under Public Hostnames tab for the tunnel, add a public route:
     - **Subdomain/Domain**: e.g. `colab.yourdomain.com`
     - **Service Type**: `SSH`
     - **URL**: `localhost:22`

3. **Pass the Token to the Notebook**:
   - **In Colab**: Add `CLOUDFLARE_TUNNEL_TOKEN` (or `TUNNEL_TOKEN`) and optionally `CLOUDFLARE_HOSTNAME` (`colab.yourdomain.com`) in **Colab Secrets** (key icon on left).
   - **In Kaggle / Shell Environment**:
     ```python
     import os
     os.environ["SSH_PUBLIC_KEY"] = "ssh-ed25519 AAAAC3N..."
     os.environ["CLOUDFLARE_TUNNEL_TOKEN"] = "eyJh..."
     os.environ["CLOUDFLARE_HOSTNAME"] = "colab.yourdomain.com"
     !python3 setup_notebook.py
     ```

4. **One-Time Client Setup**:
   On your local machine, configure SSH once:
   ```bash
   ./client_setup.sh --provider cloudflared --host colab.yourdomain.com --user dev
   ```
   Now you can simply run `ssh colab-ssh` whenever your notebook runtime starts!

---

## Features & Defense-in-Depth

- **Least Privilege Access**: Creates a dedicated non-root SSH user (`dev`) with restricted permissions instead of exposing `root`.
- **Key-Based Authentication Only**: Enforces public-key authentication. Password authentication, keyboard-interactive auth, and root logins are explicitly disabled in SSH server configuration.
- **Strict File Permissions**: Enforces `0700` permissions on `~/.ssh` and `0600` on `authorized_keys` and SSH configuration files.
- **Zero Plaintext Secret Storage**: Secrets (SSH public key, authtokens) are provided via environment variables, Google Colab secrets (`userdata`), or interactive masked prompts (`getpass`). They are never saved into notebook cells or output logs.
- **Enforced Host-Key Verification**: StrictHostKeyChecking is preserved on the local client (`StrictHostKeyChecking ask`). Host keys are never ignored (`/dev/null`), preserving Trust On First Use (TOFU) host verification.
- **Safe SSH Config Management**: Creates automatic timestamped backups (`~/.ssh/config.backup_<timestamp>`), updates host blocks without duplication, and sets proper local permissions.

---

## Step-by-Step Usage Guide

### Step 1: Generate SSH Key Pair (Local Machine)

If you do not already have an SSH key pair on your local machine, generate an Ed25519 key pair:

```bash
ssh-keygen -t ed25519 -C "colab-ssh-key"
```

Copy your **public key** (`~/.ssh/id_ed25519.pub`):

```bash
cat ~/.ssh/id_ed25519.pub
```

*Note: Never upload or paste your private key (`id_ed25519`).*

---

### Step 2: Client-Side Setup (Local Machine)

Clone or download `client_setup.sh` onto your local machine and execute the command printed by the notebook cell output:

#### For Cloudflare Tunnel:
```bash
chmod +x client_setup.sh
./client_setup.sh --provider cloudflared --host <YOUR-TUNNEL-HOSTNAME>.trycloudflare.com --user dev
```

#### For ngrok Tunnel:
```bash
chmod +x client_setup.sh
./client_setup.sh --provider ngrok --host 0.tcp.ngrok.io --port <PORT> --user dev
```

The script will:
1. Ensure local `~/.ssh` directory permissions (`0700`).
2. Back up your existing `~/.ssh/config` to `~/.ssh/config.backup_<timestamp>`.
3. Append or update the `Host colab-ssh` block in `~/.ssh/config`.
4. Ensure `0600` file permissions on `~/.ssh/config`.

---

### Step 3: Connect via SSH

Connect to your remote notebook session with a single command:

```bash
ssh colab-ssh
```

When connecting for the first time:
1. SSH will prompt you to verify and accept the target server's host key fingerprint (**Trust On First Use / TOFU**). Type `yes`.
2. You will be logged in as the non-root `dev` user into the notebook environment.

To open an interactive VS Code Remote-SSH session:
1. Install the **Remote - SSH** extension in VS Code.
2. Press `F1` or `Cmd+Shift+P` -> `Remote-SSH: Connect to Host...` -> Select `colab-ssh`.

---

## Security Best Practices

### 1. Principle of Least Privilege
- **Dedicated User**: Connections run under the `dev` user, preventing accidental system-level modifications as root.
- **Explicit Disables**: Password authentication is explicitly disabled (`PasswordAuthentication no`), mitigating brute-force password guessing. Root SSH access is disabled (`PermitRootLogin no`).

### 2. Defense in Depth
- **Zero Trust Cloudflare Access**: For production or sensitive workloads, use Cloudflare Named Tunnels combined with Cloudflare Zero Trust Access policies (e.g. require single sign-on or email OTP verification) at the Cloudflare edge before traffic reaches your ephemeral runtime.
- **Ingress Hardening**: Only port 22 is exposed locally within the notebook; the tunnel acts as a secure, encrypted relay.

### 3. Key Verification & TOFU (Trust On First Use)
- **Do NOT disable StrictHostKeyChecking**: Never set `StrictHostKeyChecking=no` or `UserKnownHostsFile=/dev/null` in SSH configurations. Disabling host verification exposes connections to active Machine-in-the-Middle (MitM) attacks.
- **Verify Host Fingerprints**: When connecting to a new ephemeral runtime, confirm the fingerprint matches the generated key fingerprint logged by the server setup script.

### 4. Ephemeral Secret Management
- **Token Protection**: Tunnel authtokens and private keys should never be committed to Git or stored in notebook files (`.ipynb`).
- **Rotation**: If a tunnel URL or token is inadvertently exposed, immediately revoke and regenerate the token from your ngrok or Cloudflare dashboard.

---

## Running Automated Tests

To run the automated test suite locally:

```bash
python3 test_suite.py
```
