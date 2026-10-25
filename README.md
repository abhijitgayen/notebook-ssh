# Secure SSH Access for Google Colab & Kaggle Notebook Runtimes

This repository provides a complete, production-grade, and security-hardened implementation for securely accessing Google Colab and Kaggle notebook runtimes via SSH using either **Cloudflare Tunnel (`cloudflared`)** or **`ngrok`**.

## Features & Defense-in-Depth

- **Least Privilege Access**: Creates a dedicated non-root SSH user (`dev`) with restricted permissions instead of exposing `root`.
- **Key-Based Authentication Only**: Enforces public-key authentication. Password authentication, keyboard-interactive auth, and root logins are explicitly disabled in SSH server configuration.
- **Strict File Permissions**: Enforces `0700` permissions on `~/.ssh` and `0600` on `authorized_keys` and SSH configuration files.
- **Zero Plaintext Secret Storage**: Secrets (SSH public key, authtokens) are provided via environment variables, Google Colab secrets (`userdata`), or interactive masked prompts (`getpass`). They are never saved into notebook cells or output logs.
- **Enforced Host-Key Verification**: StrictHostKeyChecking is preserved on the local client (`StrictHostKeyChecking ask`). Host keys are never ignored (`/dev/null`), preserving Trust On First Use (TOFU) host verification.
- **Safe SSH Config Management**: Creates automatic timestamped backups (`~/.ssh/config.backup_<timestamp>`), updates host blocks without duplication, and sets proper local permissions.

---

## Deliverables in this Repository

- `setup_notebook.py`: Python script for Google Colab or Kaggle cell execution (server-side setup).
- `client_setup.sh`: Shell script for local machine setup (macOS / Linux / WSL).
- `test_suite.py`: Automated test suite covering input validation, SSH config modification, backups, and secret handling.

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

### Step 2: Set Up Tunnel Credentials

#### Option A: Cloudflare Tunnel (Recommended)
1. **Quick Tunnels (No setup required)**: Cloudflare provides free, ephemeral tunnels (`*.trycloudflare.com`) out of the box without requiring a Cloudflare account.
2. **Named Tunnels (Cloudflare Zero Trust / Access)**:
   - Create a tunnel in the Cloudflare Zero Trust dashboard (`Tunnels -> Create a Tunnel`).
   - Copy the Tunnel Token provided by Cloudflare.
   - Configure an SSH Access Application in Cloudflare Zero Trust to enforce multi-factor authentication / Email OTP before granting access.

#### Option B: ngrok
1. Sign up for an account at [ngrok.com](https://ngrok.com).
2. Retrieve your **Authtoken** from the ngrok dashboard.

---

### Step 3: Run Server-Side Setup on Google Colab or Kaggle

Add a cell in your notebook and run:

```python
# Save setup_notebook.py in the runtime or clone this repo
!python3 setup_notebook.py
```

#### Secret Parameter Passing Options:
To avoid interactive prompts, you can pass parameters via environment variables or Colab Secrets:

**Using Environment Variables:**
```python
import os
os.environ["SSH_PUBLIC_KEY"] = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI..."
os.environ["TUNNEL_PROVIDER"] = "cloudflared" # or "ngrok"
os.environ["NGROK_AUTHTOKEN"] = "your_ngrok_token" # if using ngrok

!python3 setup_notebook.py
```

**Using Google Colab Secrets (`userdata`):**
In Colab, click the **Secrets** tab (key icon in left panel) and add the following secrets:
- `SSH_PUBLIC_KEY`: Your local SSH public key content.
- `CLOUDFLARE_TUNNEL_TOKEN`: (Optional) Your Cloudflare Named Tunnel token.
- `NGROK_AUTHTOKEN`: (Optional) Your ngrok authtoken.

When execution completes, the script outputs the exact client command to execute locally.

---

### Step 4: Run Client-Side Setup (Local Machine)

Clone or download `client_setup.sh` onto your local machine and execute the command printed by the notebook cell:

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

### Step 5: Connect via SSH

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
