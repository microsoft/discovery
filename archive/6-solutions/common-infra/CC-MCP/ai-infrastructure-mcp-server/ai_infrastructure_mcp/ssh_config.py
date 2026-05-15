import os
from typing import Any, Dict

import paramiko

# Environment variable names for cluster SSH access
ENV_CLUSTER_HOST = "CLUSTER_HOST"
ENV_CLUSTER_USER = "CLUSTER_USER"
ENV_CLUSTER_PRIVATE_KEY = "CLUSTER_PRIVATE_KEY"
ENV_CLUSTER_PORT = "CLUSTER_PORT"


class SSHConfigError(Exception):
    pass


def load_ssh_config() -> Dict[str, Any]:
    """Load SSH configuration from environment variables.

    Required env vars:
      CLUSTER_HOST  : hostname of login node
      CLUSTER_USER  : ssh username
    Optional env vars:
      CLUSTER_PRIVATE_KEY : path to private key (if omitted, agent / default keys used)
      CLUSTER_PORT        : ssh port (defaults 22)
    """
    host = os.getenv(ENV_CLUSTER_HOST)
    user = os.getenv(ENV_CLUSTER_USER)
    if not host:
        raise SSHConfigError(
            f"Missing required environment variable: {ENV_CLUSTER_HOST}"
        )
    if not user:
        raise SSHConfigError(
            f"Missing required environment variable: {ENV_CLUSTER_USER}"
        )

    port_val = os.getenv(ENV_CLUSTER_PORT, "22")
    try:
        port = int(port_val)
    except ValueError:
        raise SSHConfigError(f"Invalid integer for {ENV_CLUSTER_PORT}: {port_val}")

    pkey_path = os.getenv(ENV_CLUSTER_PRIVATE_KEY) or None
    if pkey_path and not os.path.exists(pkey_path):
        raise SSHConfigError(f"Private key not found: {pkey_path}")

    return {
        "login_host": host,
        "username": user,
        "private_key": pkey_path,
        "port": port,
    }


def get_ssh_client() -> paramiko.SSHClient:
    cfg = load_ssh_config()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = None
    pkey_path = cfg.get("private_key")
    if pkey_path:
        try:
            pkey = paramiko.RSAKey.from_private_key_file(pkey_path)
        except paramiko.PasswordRequiredException:
            raise SSHConfigError("Encrypted private keys not supported currently")
    client.connect(
        hostname=cfg["login_host"],
        port=cfg["port"],
        username=cfg["username"],
        pkey=pkey,
        allow_agent=pkey is None,
        look_for_keys=pkey is None,
        timeout=30,
    )
    return client


def run_login_command(command: str) -> str:
    """Run a shell command on the login node, return stdout text."""
    client = get_ssh_client()
    try:
        _, stdout, stderr = client.exec_command(command)
        out = stdout.read().decode()
        err = stderr.read().decode()
        if err.strip():
            out = out + ("\n[stderr]\n" + err)
        return out
    finally:
        client.close()
