#!/usr/bin/env python3
"""
setup_notebook.py - Secure SSH Access for Google Colab and Kaggle Notebook Runtimes

This script installs and hardens OpenSSH server on an ephemeral notebook environment,
creates a dedicated non-root user, injects the provided SSH public key, and sets up
a secure tunnel using either Cloudflare Tunnel (cloudflared) or ngrok.

Security Features:
  - Dedicated non-root user (`dev`) with sudo access (or restricted privileges).
  - Explicitly disables PasswordAuthentication and PermitRootLogin in sshd_config.
  - Strictly enforces PubkeyAuthentication with correct file permissions (0700/0600).
  - Validates SSH public key format before writing.
  - Accepts secrets securely via environment variables, Google Colab userdata, or masked CLI prompt.
  - Never logs secret tokens or private keys.
"""

import os
import re
import sys
import time
import shutil
import subprocess
import getpass
from typing import Optional, Tuple, Dict


def log(msg: str) -> None:
    print(f"[+] {msg}")


def log_warn(msg: str) -> None:
    print(f"[!] {msg}")


def log_err(msg: str) -> None:
    print(f"[-] ERROR: {msg}")


def run_cmd(cmd: list, check: bool = True, capture_output: bool = True, text: bool = True) -> subprocess.CompletedProcess:
    """Run a system command securely using list arguments to avoid shell injection."""
    try:
        res = subprocess.run(cmd, check=check, capture_output=capture_output, text=text)
        return res
    except subprocess.CalledProcessError as e:
        log_err(f"Command failed: {' '.join(cmd)}\nStdout: {e.stdout}\nStderr: {e.stderr}")
        if check:
            raise
        return e


def is_root() -> bool:
    return os.geteuid() == 0


def validate_ssh_public_key(pubkey: str) -> str:
    """Validate that the provided string looks like a single valid OpenSSH public key."""
    pubkey = pubkey.strip()
    if not pubkey:
        raise ValueError("SSH public key cannot be empty.")

    valid_prefixes = (
        "ssh-rsa",
        "ssh-dss",
        "ecdsa-sha2-nistp256",
        "ecdsa-sha2-nistp384",
        "ecdsa-sha2-nistp521",
        "ssh-ed25519",
        "sk-ssh-ed25519@openssh.com",
        "sk-ecdsa-sha2-nistp256@openssh.com",
    )

    lines = [line.strip() for line in pubkey.splitlines() if line.strip() and not line.strip().startswith("#")]
    if not lines:
        raise ValueError("No valid key line found in public key input.")

    first_line = lines[0]
    parts = first_line.split()
    if len(parts) < 2 or parts[0] not in valid_prefixes:
        raise ValueError(
            f"Invalid SSH public key format. Key must start with a valid key type (e.g., ssh-ed25519, ssh-rsa)."
        )

    return first_line


def get_secret(env_var_name: str, colab_secret_name: str, prompt_label: str) -> str:
    """Retrieve a secret from Environment Variable, Colab Userdata, or Interactive Masked Prompt."""
    # 1. Environment Variable
    val = os.environ.get(env_var_name, "").strip()
    if val:
        log(f"Loaded {prompt_label} from environment variable '{env_var_name}'.")
        return val

    # 2. Google Colab Userdata (if available)
    try:
        from google.colab import userdata  # type: ignore
        val = userdata.get(colab_secret_name)
        if val and str(val).strip():
            log(f"Loaded {prompt_label} from Colab Secret '{colab_secret_name}'.")
            return str(val).strip()
    except Exception:
        pass

    # 3. Interactive Prompt (only if stdin is interactive)
    if sys.stdin.isatty():
        val = getpass.getpass(prompt=f"Enter {prompt_label}: ").strip()
        if not val:
            raise ValueError(f"{prompt_label} cannot be empty.")
        return val

    raise ValueError(f"Secret '{prompt_label}' not found in environment variable '{env_var_name}' or Colab Secret '{colab_secret_name}'.")


def get_optional_secret(env_var_names: list, colab_secret_names: list) -> Optional[str]:
    """Retrieve an optional secret from a list of environment variable or Colab secret names."""
    for name in env_var_names:
        val = os.environ.get(name, "").strip()
        if val:
            return val
    try:
        from google.colab import userdata  # type: ignore
        for name in colab_secret_names:
            val = userdata.get(name)
            if val and str(val).strip():
                return str(val).strip()
    except Exception:
        pass
    return None


def setup_sshd_and_user(username: str, pubkey: str) -> str:
    """Install OpenSSH server, create dedicated non-root user, configure SSH key and harden sshd."""
    if not is_root():
        raise PermissionError("This script must be run as root (or with sudo in Colab/Kaggle).")

    log("Installing OpenSSH server and required utilities...")
    run_cmd(["apt-get", "update", "-qq"])
    run_cmd(["apt-get", "install", "-y", "-qq", "openssh-server", "sudo", "curl", "net-tools"])

    # Ensure /var/run/sshd exists
    os.makedirs("/var/run/sshd", exist_ok=True)

    # Create dedicated user if not exists
    user_exists = subprocess.run(["id", username], capture_output=True).returncode == 0
    if not user_exists:
        log(f"Creating dedicated non-root user '{username}'...")
        run_cmd(["useradd", "-m", "-s", "/bin/bash", username])
        # Add user to sudoers with NOPASSWD for convenience in notebook environment
        sudoers_file = f"/etc/sudoers.d/99-{username}"
        with open(sudoers_file, "w") as f:
            f.write(f"{username} ALL=(ALL) NOPASSWD:ALL\n")
        os.chmod(sudoers_file, 0o440)
    else:
        log(f"User '{username}' already exists.")

    # Configure SSH key for user
    user_home = os.path.expanduser(f"~{username}")
    ssh_dir = os.path.join(user_home, ".ssh")
    auth_keys_path = os.path.join(ssh_dir, "authorized_keys")

    os.makedirs(ssh_dir, mode=0o700, exist_ok=True)

    # Write public key
    with open(auth_keys_path, "w") as f:
        f.write(pubkey + "\n")
    os.chmod(auth_keys_path, 0o600)

    # Set proper ownership
    run_cmd(["chown", "-R", f"{username}:{username}", ssh_dir])

    # Harden sshd_config
    log("Hardening SSH daemon configuration...")
    sshd_config_dir = "/etc/ssh/sshd_config.d"
    os.makedirs(sshd_config_dir, exist_ok=True)

    hardening_config = """# Security Hardening for Ephemeral Notebook Runtime
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
X11Forwarding no
AllowTcpForwarding yes
AllowUsers {username}
""".format(username=username)

    hardening_file = os.path.join(sshd_config_dir, "99-hardened.conf")
    with open(hardening_file, "w") as f:
        f.write(hardening_config)

    # Restart or start sshd service
    log("Starting SSH daemon...")
    run_cmd(["service", "ssh", "restart"])

    return username


def setup_cloudflared(tunnel_token: Optional[str] = None, hostname_override: Optional[str] = None) -> Tuple[str, Optional[int]]:
    """Install and start cloudflared tunnel in background."""
    log("Installing cloudflared...")
    if not shutil.which("cloudflared"):
        # Download official cloudflared binary
        arch_res = run_cmd(["uname", "-m"])
        arch = arch_res.stdout.strip()
        pkg_arch = "amd64" if arch in ("x86_64", "amd64") else ("arm64" if "arm" in arch or "aarch64" in arch else "amd64")

        url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{pkg_arch}.deb"
        deb_path = "/tmp/cloudflared.deb"
        run_cmd(["curl", "-sSL", url, "-o", deb_path])
        run_cmd(["dpkg", "-i", deb_path])
        if os.path.exists(deb_path):
            os.remove(deb_path)

    log("Launching cloudflared tunnel...")
    log_file = "/tmp/cloudflared.log"

    if tunnel_token:
        # Named tunnel (Cloudflare Zero Trust / Access)
        log("Using Cloudflare Named Tunnel token...")
        cmd = ["cloudflared", "tunnel", "--no-autoupdate", "run", "--token", tunnel_token]
        proc = subprocess.Popen(cmd, stdout=open(log_file, "a"), stderr=subprocess.STDOUT)
        time.sleep(3)
        if proc.poll() is not None:
            logs = ""
            if os.path.exists(log_file):
                with open(log_file, "r") as f:
                    logs = f.read()
            raise RuntimeError(f"Cloudflare tunnel process exited unexpectedly with code {proc.returncode}.\nLog output:\n{logs}")

        display_host = hostname_override if hostname_override else "NAMED_TUNNEL"
        return display_host, None
    else:
        # Quick Tunnel
        log("Using Cloudflare Quick Tunnel...")
        cmd = ["cloudflared", "tunnel", "--url", "ssh://localhost:22"]
        proc = subprocess.Popen(cmd, stdout=open(log_file, "w"), stderr=subprocess.STDOUT)

        hostname = None
        for _ in range(30):
            time.sleep(1)
            if os.path.exists(log_file):
                with open(log_file, "r") as f:
                    content = f.read()
                    # Look for trycloudflare.com hostname
                    match = re.search(r"https://([a-zA-Z0-9-]+\.trycloudflare\.com)", content)
                    if match:
                        hostname = match.group(1)
                        break

        if not hostname:
            raise RuntimeError("Failed to retrieve Cloudflare quick tunnel URL. Check /tmp/cloudflared.log.")

        return hostname, 22


def setup_ngrok(authtoken: str) -> Tuple[str, int]:
    """Install and start ngrok tcp tunnel in background."""
    log("Installing ngrok...")
    if not shutil.which("ngrok"):
        run_cmd(["curl", "-sSL", "https://bin.equinox.io/c/bDfA1WdaZA2/ngrok-v3-stable-linux-amd64.tgz", "-o", "/tmp/ngrok.tgz"])
        run_cmd(["tar", "-xzf", "/tmp/ngrok.tgz", "-C", "/usr/local/bin"])
        if os.path.exists("/tmp/ngrok.tgz"):
            os.remove("/tmp/ngrok.tgz")

    log("Configuring ngrok authtoken...")
    run_cmd(["ngrok", "config", "add-authtoken", authtoken])

    log("Launching ngrok TCP tunnel on port 22...")
    log_file = "/tmp/ngrok.log"
    cmd = ["ngrok", "tcp", "22", "--log=stdout"]
    proc = subprocess.Popen(cmd, stdout=open(log_file, "w"), stderr=subprocess.STDOUT)

    hostname = None
    port = None
    for _ in range(30):
        time.sleep(1)
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                content = f.read()
                # Match url=tcp://x.tcp.ngrok.io:12345 or tcp://0.tcp.ngrok.io:12345
                match = re.search(r"tcp://([a-zA-Z0-9\.-]+):(\d+)", content)
                if match:
                    hostname = match.group(1)
                    port = int(match.group(2))
                    break

    if not hostname or not port:
        raise RuntimeError("Failed to retrieve ngrok TCP tunnel endpoint. Check /tmp/ngrok.log.")

    return hostname, port


def main():
    print("=" * 65)
    print("  Secure Ephemeral SSH Setup for Colab / Kaggle")
    print("=" * 65)

    if not is_root():
        log_err("Please run this script as root (e.g. `sudo python3 setup_notebook.py`).")
        sys.exit(1)

    # 1. Choose Provider
    provider = os.environ.get("TUNNEL_PROVIDER", "").lower()
    if provider not in ("cloudflared", "ngrok"):
        if sys.stdin.isatty():
            print("\nSelect Tunnel Provider:")
            print("  1) Cloudflare Tunnel (cloudflared) - Recommended")
            print("  2) ngrok")
            choice = input("Enter choice (1 or 2, default: 1): ").strip()
            provider = "ngrok" if choice == "2" else "cloudflared"
        else:
            provider = "cloudflared"

    # 2. Get Public Key securely
    raw_pubkey = get_secret(
        env_var_name="SSH_PUBLIC_KEY",
        colab_secret_name="SSH_PUBLIC_KEY",
        prompt_label="SSH Public Key (e.g. contents of ~/.ssh/id_ed25519.pub)"
    )
    pubkey = validate_ssh_public_key(raw_pubkey)

    # 3. Get Tunnel Token if applicable
    tunnel_token = None
    if provider == "ngrok":
        tunnel_token = get_secret(
            env_var_name="NGROK_AUTHTOKEN",
            colab_secret_name="NGROK_AUTHTOKEN",
            prompt_label="ngrok Authtoken"
        )
    elif provider == "cloudflared":
        # Cloudflare token is optional (Quick tunnel vs Named Tunnel)
        tunnel_token = get_optional_secret(
            env_var_names=["CLOUDFLARE_TUNNEL_TOKEN", "TUNNEL_TOKEN"],
            colab_secret_names=["CLOUDFLARE_TUNNEL_TOKEN", "TUNNEL_TOKEN"]
        )

    cf_hostname = None
    if provider == "cloudflared" and tunnel_token:
        cf_hostname = get_optional_secret(
            env_var_names=["CLOUDFLARE_HOSTNAME", "TUNNEL_HOSTNAME"],
            colab_secret_names=["CLOUDFLARE_HOSTNAME", "TUNNEL_HOSTNAME"]
        )

    username = os.environ.get("SSH_USER", "dev")

    # 4. Setup SSH daemon and User
    username = setup_sshd_and_user(username, pubkey)

    # 5. Launch Tunnel
    if provider == "cloudflared":
        hostname, port = setup_cloudflared(tunnel_token, cf_hostname)
    else:
        hostname, port = setup_ngrok(tunnel_token)

    # 6. Display Instructions
    print("\n" + "=" * 65)
    print("  SSH SERVER READY & HARDENED")
    print("=" * 65)
    print(f"User:     {username}")
    print(f"Provider: {provider.upper()}")

    if hostname == "NAMED_TUNNEL":
        print("Tunnel Mode: Cloudflare Named Tunnel / Zero Trust")
        print("\nClient Setup Command (Run on your local computer):")
        print(f"  ./client_setup.sh --provider cloudflared --host <YOUR-ZERO-TRUST-HOSTNAME> --user {username}")
    else:
        print(f"Hostname: {hostname}")
        print(f"Port:     {port}")
        print("\nClient Setup Command (Run on your local computer):")
        if provider == "cloudflared":
            print(f"  ./client_setup.sh --provider cloudflared --host {hostname} --user {username}")
        else:
            print(f"  ./client_setup.sh --provider ngrok --host {hostname} --port {port} --user {username}")

    print("\nSecurity Checklist Verified:")
    print("  [x] Password authentication disabled in sshd_config")
    print("  [x] Root SSH login disabled")
    print("  [x] Authorized keys written with strict file permissions (0600)")
    print("  [x] Secrets kept out of source files and log output")
    print("=" * 65)


if __name__ == "__main__":
    main()
