#!/usr/bin/env python3
"""
Bootstrap script for Demo 3: RDP Computer Use with Session Recording.

Creates all Boundary resources needed for the demo:
  - Org and Project
  - Host Catalog (static) with one Windows host
  - Host Set containing the Windows host
  - Credential Store (static) with username/password for Windows
  - Storage Bucket (MinIO/S3) for session recordings
  - TCP target on port 3389 (RDP) with brokered credentials and session recording enabled

Usage:
  BOUNDARY_ADDR=http://127.0.0.1:9220 python3 bootstrap-boundary.py

Prerequisites:
  - Boundary controller running and accessible
  - MinIO running and accessible
  - boundary CLI installed and on PATH
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
WINDOWS_HOST_IP = os.environ.get("WINDOWS_HOST_IP", "10.30.0.40")
WINDOWS_RDP_PORT = "3389"
WINDOWS_USERNAME = os.environ.get("WINDOWS_USERNAME", "Administrator")
WINDOWS_PASSWORD = os.environ.get("WINDOWS_PASSWORD", "P@ssw0rd!23")
BUCKET_NAME = "boundary-session-recordings"


def bcmd(args):
    """Run a boundary CLI command and return parsed JSON."""
    env = os.environ.copy()
    env["BOUNDARY_ADDR"] = BOUNDARY_ADDR
    env["BOUNDARY_KEYRING_TYPE"] = "none"
    cmd = ["boundary"] + args + ["-token", "env://BOUNDARY_TOKEN", "-format", "json"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        return None, r.stderr
    try:
        return json.loads(r.stdout), None
    except json.JSONDecodeError:
        return None, f"Failed to parse JSON: {r.stdout}"


def bcmd_raw(args):
    """Run a boundary CLI command without token (for auth)."""
    env = os.environ.copy()
    env["BOUNDARY_ADDR"] = BOUNDARY_ADDR
    env["BOUNDARY_KEYRING_TYPE"] = "none"
    cmd = ["boundary"] + args + ["-format", "json"]
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
        # Try alternate path
        token = data.get("item", {}).get("attributes", {}).get("token", {}).get("token", "")
    if not token:
        print("FAILED: no token in response")
        print(json.dumps(data, indent=2))
        sys.exit(1)
    print(f"OK (token: {token[:20]}...)")
    return token


def create_org(token):
    """Create the org."""
    result, err = bcmd(["scopes", "create", "-name", "rdp-org", "-description", "RDP Computer Use Demo Org"])
    if err:
        print(f"  Org creation error: {err}")
        return None
    org_id = result.get("item", {}).get("id", "")
    print(f"  Org: {org_id}")
    return org_id


def create_project(token, org_id):
    """Create a project under the org."""
    result, err = bcmd(["projects", "create", "-name", "rdp-project", "-description", "RDP Computer Use Demo Project", "-scope-id", org_id])
    if err:
        print(f"  Project creation error: {err}")
        return None
    proj_id = result.get("item", {}).get("id", "")
    print(f"  Project: {proj_id}")
    return proj_id


def create_host_catalog(token, proj_id):
    """Create a static host catalog."""
    result, err = bcmd(["host-catalogs", "create", "static", "-name", "windows-hosts", "-scope-id", proj_id])
    if err:
        print(f"  Host catalog error: {err}")
        return None
    hc_id = result.get("item", {}).get("id", "")
    print(f"  Host Catalog: {hc_id}")
    return hc_id


def create_host(token, hc_id):
    """Create a static host for the Windows VM."""
    result, err = bcmd(["hosts", "create", "static", "-name", "windows-vm", "-host-catalog-id", hc_id, "-address", WINDOWS_HOST_IP])
    if err:
        print(f"  Host error: {err}")
        return None
    host_id = result.get("item", {}).get("id", "")
    print(f"  Host windows-vm ({WINDOWS_HOST_IP}): {host_id}")
    return host_id


def create_host_set(token, hc_id, host_id):
    """Create a host set containing the Windows host."""
    result, err = bcmd(["host-sets", "create", "static", "-name", "windows-vm-set", "-host-catalog-id", hc_id, "-host-id", host_id])
    if err:
        print(f"  Host set error: {err}")
        return None
    hs_id = result.get("item", {}).get("id", "")
    print(f"  Host Set windows-vm-set: {hs_id}")
    return hs_id


def create_credential_store(token, proj_id):
    """Create a static credential store."""
    result, err = bcmd(["credential-stores", "create", "static", "-name", "windows-creds", "-scope-id", proj_id])
    if err:
        print(f"  Credential store error: {err}")
        return None
    cs_id = result.get("item", {}).get("id", "")
    print(f"  Credential Store: {cs_id}")
    return cs_id


def create_credential(token, cs_id):
    """Create a username/password credential for Windows."""
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
    """Create a storage bucket for session recordings (MinIO/S3)."""
    env = os.environ.copy()
    env["BOUNDARY_ADDR"] = BOUNDARY_ADDR
    env["BOUNDARY_KEYRING_TYPE"] = "none"
    env["BOUNDARY_TOKEN"] = token
    env["SECRET_KEY"] = MINIO_SECRET_KEY

    # The storage bucket plugin uses the S3 plugin
    # Attributes: bucket_name, region, access_key (via attributes)
    # Secrets: secret_access_key (via secrets)
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
             "endpoint": MINIO_URL.replace("127.0.0.1:9230", "10.30.0.30:9000"),
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
    """Create a TCP target on port 3389 (RDP) with brokered credentials and session recording."""
    env = os.environ.copy()
    env["BOUNDARY_ADDR"] = BOUNDARY_ADDR
    env["BOUNDARY_KEYRING_TYPE"] = "none"
    env["BOUNDARY_TOKEN"] = token

    # Create the target with session recording enabled
    # For enterprise, we can set enable_session_recording and storage_bucket_id
    # via the target attributes or update after creation
    cmd_args = [
        "targets", "create", "tcp",
        "-name", "windows-rdp",
        "-scope-id", proj_id,
        "-default-port", WINDOWS_RDP_PORT,
        "-session-max-seconds", "3600",
    ]

    # Add session recording flags if storage bucket was created
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

    # Add host source
    if target_id and hs_id:
        bcmd(["targets", "add-host-sources", "-id", target_id, "-host-source", hs_id])
        print(f"    host source added")

    # Add brokered credential source
    if target_id and cred_id:
        bcmd(["targets", "add-credential-sources", "-id", target_id, "-brokered-credential-source", cred_id])
        print(f"    brokered credential added")

    return target_id


def main():
    print("=== Demo 3: RDP Computer Use with Session Recording Bootstrap ===")
    print()

    if not wait_for_boundary():
        print("Boundary not available. Exiting.")
        sys.exit(1)

    wait_for_minio()

    token = authenticate()
    os.environ["BOUNDARY_TOKEN"] = token

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
