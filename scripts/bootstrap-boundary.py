#!/usr/bin/env python3
"""
Bootstrap script for Demo 3: RDP Computer Use with Session Recording.

Creates all Boundary resources needed for the demo:
  - Org and Project
  - Host Catalog (static) with one Windows host (remote, e.g. AWS EC2)
  - Host Set containing the Windows host
  - Credential Store (static) with username/password for Windows
  - Storage Bucket (MinIO/S3) for session recordings
  - TCP target on port 3389 (RDP) with brokered credentials and session recording enabled

Usage:
  BOUNDARY_ADDR=http://127.0.0.1:9220 \
  WINDOWS_HOST_IP=10.0.1.42 \
  WINDOWS_USERNAME=Administrator \
  WINDOWS_PASSWORD=YourPassword123 \
  python3 bootstrap-boundary.py

Environment variables:
  BOUNDARY_ADDR       - Boundary API address (default: http://127.0.0.1:9220)
  MINIO_URL           - MinIO S3 API URL (default: http://127.0.0.1:9230)
  MINIO_ACCESS_KEY    - MinIO access key (default: minioadmin)
  MINIO_SECRET_KEY    - MinIO secret key (default: minioadmin123)
  WINDOWS_HOST_IP     - IP/hostname of the remote Windows host (REQUIRED)
  WINDOWS_USERNAME    - Windows RDP username (default: Administrator)
  WINDOWS_PASSWORD    - Windows RDP password (REQUIRED)
  BOUNDARY_LICENSE    - Boundary Enterprise license key (optional, can be in compose env)
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

BOUNDARY_ADDR = os.environ.get("BOUNDARY_ADDR", "http://127.0.0.1:9220")
MINIO_URL = os.environ.get("MINIO_URL", "http://127.0.0.1:9230")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin123")
WINDOWS_HOST_IP = os.environ.get("WINDOWS_HOST_IP", "")
WINDOWS_RDP_PORT = os.environ.get("WINDOWS_RDP_PORT", "3389")
WINDOWS_USERNAME = os.environ.get("WINDOWS_USERNAME", "Administrator")
WINDOWS_PASSWORD = os.environ.get("WINDOWS_PASSWORD", "")
BUCKET_NAME = "boundary-session-recordings"


def bcmd(args, token=None):
    """Run a boundary CLI command and return parsed JSON."""
    env = os.environ.copy()
    env["BOUNDARY_ADDR"] = BOUNDARY_ADDR
    env["BOUNDARY_KEYRING_TYPE"] = "none"
    if token:
        env["BOUNDARY_TOKEN"] = token
    cmd = ["boundary"] + args + ["-token", "env://BOUNDARY_TOKEN", "-format", "json"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        return None, r.stderr
    try:
        return json.loads(r.stdout), None
    except json.JSONDecodeError:
        return None, f"Failed to parse JSON: {r.stdout}"


def wait_for_boundary():
    """Wait for Boundary controller to be ready."""
    print("Waiting for Boundary controller...", end=" ", flush=True)
    for _ in range(60):
        try:
            req = urllib.request.Request(f"{BOUNDARY_ADDR}/v1/scopes/global")
            req.add_header("Content-Type", "application/json")
            urllib.request.urlopen(req, timeout=5)
            print("OK")
            return True
        except Exception:
            time.sleep(2)
    print("FAILED")
    return False


def wait_for_minio():
    """Wait for MinIO to be ready."""
    print("Waiting for MinIO...", end=" ", flush=True)
    for _ in range(30):
        try:
            urllib.request.urlopen(f"{MINIO_URL}/minio/health/live", timeout=5)
            print("OK")
            return True
        except Exception:
            time.sleep(2)
    print("FAILED (continuing anyway)")
    return False


def authenticate():
    """Authenticate as admin and return token."""
    print("Authenticating...", end=" ", flush=True)
    env = os.environ.copy()
    env["BOUNDARY_ADDR"] = BOUNDARY_ADDR
    env["BOUNDARY_KEYRING_TYPE"] = "none"
    env["BOUNDARY_PASSWORD"] = "adminadmin"
    r = subprocess.run(
        ["boundary", "authenticate", "password",
         "-auth-method-id", "ampw_1234567890",
         "-login-name", "admin",
         "-password", "env://BOUNDARY_PASSWORD",
         "-format", "json"],
        capture_output=True, text=True, env=env
    )
    if r.returncode != 0:
        print(f"FAILED: {r.stderr}")
        sys.exit(1)
    data = json.loads(r.stdout)
    token = data.get("attributes", {}).get("token", {}).get("token", "")
    if not token:
        token = data.get("item", {}).get("attributes", {}).get("token", {}).get("token", "")
    if not token:
        print("FAILED: no token in response")
        print(json.dumps(data, indent=2))
        sys.exit(1)
    print(f"OK (token: {token[:20]}...)")
    return token


def create_org(token):
    result, err = bcmd(["scopes", "create", "-name", "rdp-org", "-description", "RDP Computer Use Demo Org"], token)
    if err:
        print(f"  Org creation error: {err}")
        return None
    org_id = result.get("item", {}).get("id", "")
    print(f"  Org: {org_id}")
    return org_id


def create_project(token, org_id):
    result, err = bcmd(["projects", "create", "-name", "rdp-project", "-description", "RDP Computer Use Demo Project", "-scope-id", org_id], token)
    if err:
        print(f"  Project creation error: {err}")
        return None
    proj_id = result.get("item", {}).get("id", "")
    print(f"  Project: {proj_id}")
    return proj_id


def create_host_catalog(token, proj_id):
    result, err = bcmd(["host-catalogs", "create", "static", "-name", "windows-hosts", "-scope-id", proj_id], token)
    if err:
        print(f"  Host catalog error: {err}")
        return None
    hc_id = result.get("item", {}).get("id", "")
    print(f"  Host Catalog: {hc_id}")
    return hc_id


def create_host(token, hc_id):
    result, err = bcmd(["hosts", "create", "static", "-name", "windows-remote", "-host-catalog-id", hc_id, "-address", WINDOWS_HOST_IP], token)
    if err:
        print(f"  Host error: {err}")
        return None
    host_id = result.get("item", {}).get("id", "")
    print(f"  Host windows-remote ({WINDOWS_HOST_IP}): {host_id}")
    return host_id


def create_host_set(token, hc_id, host_id):
    result, err = bcmd(["host-sets", "create", "static", "-name", "windows-remote-set", "-host-catalog-id", hc_id, "-host-id", host_id], token)
    if err:
        print(f"  Host set error: {err}")
        return None
    hs_id = result.get("item", {}).get("id", "")
    print(f"  Host Set windows-remote-set: {hs_id}")
    return hs_id


def create_credential_store(token, proj_id):
    result, err = bcmd(["credential-stores", "create", "static", "-name", "windows-creds", "-scope-id", proj_id], token)
    if err:
        print(f"  Credential store error: {err}")
        return None
    cs_id = result.get("item", {}).get("id", "")
    print(f"  Credential Store: {cs_id}")
    return cs_id


def create_credential(token, cs_id):
    env = os.environ.copy()
    env["BOUNDARY_ADDR"] = BOUNDARY_ADDR
    env["BOUNDARY_KEYRING_TYPE"] = "none"
    env["BOUNDARY_TOKEN"] = token
    env["WIN_PASS"] = WINDOWS_PASSWORD
    r = subprocess.run(
        ["boundary", "credentials", "create", "username-password",
         "-credential-store-id", cs_id,
         "-name", "windows-admin",
         "-username", WINDOWS_USERNAME,
         "-password", "env://WIN_PASS",
         "-token", "env://BOUNDARY_TOKEN",
         "-format", "json"],
        capture_output=True, text=True, env=env
    )
    if r.returncode != 0:
        print(f"  Credential error: {r.stderr}")
        return None
    data = json.loads(r.stdout)
    cred_id = data.get("item", {}).get("id", "")
    print(f"  Credential: {cred_id}")
    return cred_id


def create_storage_bucket(token, proj_id):
    env = os.environ.copy()
    env["BOUNDARY_ADDR"] = BOUNDARY_ADDR
    env["BOUNDARY_KEYRING_TYPE"] = "none"
    env["BOUNDARY_TOKEN"] = token

    minio_internal = os.environ.get("MINIO_INTERNAL_URL", "http://10.30.0.30:9000")

    r = subprocess.run(
        ["boundary", "storage-buckets", "create",
         "-name", "session-recording-bucket",
         "-scope-id", proj_id,
         "-bucket-name", BUCKET_NAME,
         "-plugin-name", "aws",
         "-attributes", json.dumps({
             "bucket_name": BUCKET_NAME,
             "region": "us-east-1",
             "access_key": MINIO_ACCESS_KEY,
             "endpoint": minio_internal,
         }),
         "-secrets", json.dumps({
             "secret_access_key": MINIO_SECRET_KEY,
         }),
         "-token", "env://BOUNDARY_TOKEN",
         "-format", "json"],
        capture_output=True, text=True, env=env
    )
    if r.returncode != 0:
        print(f"  Storage bucket error: {r.stderr}")
        print(f"  (This requires Boundary Enterprise - session recording is an enterprise feature)")
        return None
    data = json.loads(r.stdout)
    sb_id = data.get("item", {}).get("id", "")
    print(f"  Storage Bucket: {sb_id}")
    return sb_id


def create_tcp_target(token, proj_id, hs_id, cred_id, sb_id):
    env = os.environ.copy()
    env["BOUNDARY_ADDR"] = BOUNDARY_ADDR
    env["BOUNDARY_KEYRING_TYPE"] = "none"
    env["BOUNDARY_TOKEN"] = token

    cmd_args = [
        "targets", "create", "tcp",
        "-name", "windows-rdp",
        "-scope-id", proj_id,
        "-default-port", WINDOWS_RDP_PORT,
        "-session-max-seconds", "3600",
    ]

    if sb_id:
        cmd_args.extend(["-enable-session-recording", "-storage-bucket-id", sb_id])

    r = subprocess.run(
        ["boundary"] + cmd_args + ["-token", "env://BOUNDARY_TOKEN", "-format", "json"],
        capture_output=True, text=True, env=env
    )
    if r.returncode != 0:
        print(f"  Target creation error: {r.stderr}")
        return None
    data = json.loads(r.stdout)
    target_id = data.get("item", {}).get("id", "")
    print(f"  Target windows-rdp: {target_id}")

    if target_id and hs_id:
        bcmd(["targets", "add-host-sources", "-id", target_id, "-host-source", hs_id], token)
        print(f"    host source added")

    if target_id and cred_id:
        bcmd(["targets", "add-credential-sources", "-id", target_id, "-brokered-credential-source", cred_id], token)
        print(f"    brokered credential added")

    return target_id


def main():
    print("=== Demo 3: RDP Computer Use with Session Recording Bootstrap ===")
    print()

    if not WINDOWS_HOST_IP:
        print("ERROR: WINDOWS_HOST_IP is required.")
        print("Set it to the IP or hostname of your remote Windows host:")
        print("  export WINDOWS_HOST_IP=10.0.1.42")
        sys.exit(1)

    if not WINDOWS_PASSWORD:
        print("ERROR: WINDOWS_PASSWORD is required.")
        print("Set it to the RDP password for your Windows host:")
        print("  export WINDOWS_PASSWORD=YourPassword123")
        sys.exit(1)

    print(f"Windows host: {WINDOWS_HOST_IP}:{WINDOWS_RDP_PORT}")
    print(f"Windows user: {WINDOWS_USERNAME}")
    print()

    if not wait_for_boundary():
        print("Boundary not available. Exiting.")
        sys.exit(1)

    wait_for_minio()

    token = authenticate()

    print()
    print("=== Creating org and project ===")
    org_id = create_org(token)
    if not org_id:
        sys.exit(1)
    proj_id = create_project(token, org_id)
    if not proj_id:
        sys.exit(1)

    print()
    print("=== Creating host catalog, host, and host set ===")
    hc_id = create_host_catalog(token, proj_id)
    host_id = create_host(token, hc_id) if hc_id else None
    hs_id = create_host_set(token, hc_id, host_id) if host_id else None

    print()
    print("=== Creating credentials ===")
    cs_id = create_credential_store(token, proj_id)
    cred_id = create_credential(token, cs_id) if cs_id else None

    print()
    print("=== Creating storage bucket for session recordings ===")
    sb_id = create_storage_bucket(token, proj_id)
    if not sb_id:
        print("  WARNING: Storage bucket creation failed. Session recording will not work.")
        print("  This requires Boundary Enterprise. Continuing without recording.")

    print()
    print("=== Creating RDP target (TCP port 3389) ===")
    target_id = create_tcp_target(token, proj_id, hs_id, cred_id, sb_id)

    print()
    print("=== Bootstrap complete ===")
    print()
    print(f"Org ID:              {org_id}")
    print(f"Project ID:          {proj_id}")
    print(f"Host Catalog ID:     {hc_id}")
    print(f"Host ID:             {host_id}")
    print(f"Host Set ID:         {hs_id}")
    print(f"Credential Store ID: {cs_id}")
    print(f"Credential ID:       {cred_id}")
    print(f"Storage Bucket ID:   {sb_id}")
    print(f"Target ID:           {target_id}")
    print()
    print(f"Token for .mcp.json: {token}")
    print()
    print("Next steps:")
    print("  1. Update .mcp.json with the token above")
    print("  2. Update .mcp.json with the boundary-mcp binary path")
    print("  3. Update .mcp.json with the rdp-mcp-server path")
    print("  4. Run: ibm-bob --config .mcp.json -p \"$(cat CLAUDE.md)\"")


if __name__ == "__main__":
    main()