#!/usr/bin/env python3
"""
Retrieve and list session recordings from Boundary.

Usage:
  BOUNDARY_ADDR=http://127.0.0.1:9220 python3 retrieve-recordings.py [--download <recording-id>] [--output <path>]

Without --download: lists all recordings with details.
With --download: downloads the specified recording to the output path.
"""

import json
import os
import subprocess
import sys
import argparse

BOUNDARY_ADDR = os.environ.get("BOUNDARY_ADDR", "http://127.0.0.1:9220")


def get_token():
    """Get token from env or authenticate."""
    token = os.environ.get("BOUNDARY_TOKEN", "")
    if token:
        return token

    # Authenticate as admin
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
        capture_output=True, text=True, env=env,
    )
    if r.returncode != 0:
        print(f"Authentication failed: {r.stderr}")
        sys.exit(1)
    data = json.loads(r.stdout)
    token = data.get("attributes", {}).get("token", {}).get("token", "")
    if not token:
        token = data.get("item", {}).get("attributes", {}).get("token", {}).get("token", "")
    return token


def list_recordings(token):
    """List all session recordings."""
    env = os.environ.copy()
    env["BOUNDARY_ADDR"] = BOUNDARY_ADDR
    env["BOUNDARY_KEYRING_TYPE"] = "none"
    env["BOUNDARY_TOKEN"] = token

    r = subprocess.run(
        ["boundary", "session-recordings", "list",
         "-token", "env://BOUNDARY_TOKEN",
         "-format", "json"],
        capture_output=True, text=True, env=env, timeout=30,
    )

    if r.returncode != 0:
        print(f"Error listing recordings: {r.stderr}")
        sys.exit(1)

    data = json.loads(r.stdout)
    recordings = data.get("items", [])

    if not recordings:
        print("No session recordings found.")
        print()
        print("This could mean:")
        print("  1. No sessions with recording enabled have been completed yet")
        print("  2. The storage bucket is not properly configured")
        print("  3. Boundary Enterprise features are not enabled")
        return

    print(f"Found {len(recordings)} session recording(s):")
    print()
    for i, rec in enumerate(recordings, 1):
        print(f"  Recording {i}:")
        print(f"    ID:          {rec.get('id', 'N/A')}")
        print(f"    Session ID:  {rec.get('session_id', 'N/A')}")
        print(f"    State:       {rec.get('state', 'N/A')}")
        print(f"    Type:        {rec.get('type', 'N/A')}")
        print(f"    Start Time:  {rec.get('start_time', 'N/A')}")
        print(f"    End Time:    {rec.get('end_time', 'N/A')}")
        print(f"    Duration:    {rec.get('duration', 'N/A')}")
        print(f"    MIME Types:  {rec.get('mime_types', [])}")
        print(f"    Bytes Up:    {rec.get('bytes_up', 'N/A')}")
        print(f"    Bytes Down:  {rec.get('bytes_down', 'N/A')}")

        # Show connection recordings if available
        conn_recs = rec.get("connection_recordings", [])
        if conn_recs:
            print(f"    Connections: {len(conn_recs)}")
            for j, conn in enumerate(conn_recs, 1):
                print(f"      Connection {j}:")
                print(f"        ID:          {conn.get('id', 'N/A')}")
                print(f"        Start Time:  {conn.get('start_time', 'N/A')}")
                print(f"        End Time:    {conn.get('end_time', 'N/A')}")
                print(f"        Duration:    {conn.get('duration', 'N/A')}")
                print(f"        MIME Types:  {conn.get('mime_types', [])}")

                # Show channel recordings
                chan_recs = conn.get("channel_recordings", [])
                if chan_recs:
                    print(f"        Channels: {len(chan_recs)}")
                    for k, chan in enumerate(chan_recs, 1):
                        print(f"          Channel {k}: {chan.get('id', 'N/A')} ({chan.get('mime_types', [])})")

        print()

    print("To download a recording:")
    print(f"  python3 {sys.argv[0]} --download <recording-id> --output /path/to/save.tar")


def download_recording(token, recording_id, output_path):
    """Download a specific recording."""
    env = os.environ.copy()
    env["BOUNDARY_ADDR"] = BOUNDARY_ADDR
    env["BOUNDARY_KEYRING_TYPE"] = "none"
    env["BOUNDARY_TOKEN"] = token

    print(f"Downloading recording {recording_id} to {output_path}...")

    r = subprocess.run(
        ["boundary", "session-recordings", "download",
         "-id", recording_id,
         "-output", output_path,
         "-token", "env://BOUNDARY_TOKEN"],
        capture_output=True, text=True, env=env, timeout=120,
    )

    if r.returncode != 0:
        print(f"Download failed: {r.stderr}")
        sys.exit(1)

    if os.path.exists(output_path):
        size = os.path.getsize(output_path)
        print(f"Download complete: {output_path} ({size} bytes, {size/1024/1024:.1f} MB)")
        print()
        print("To play back the recording:")
        print("  1. Extract the TAR file: tar xf <file>.tar")
        print("  2. Look for video/webm or other media files inside")
        print("  3. Play with a media player (VLC, mpv, etc.)")
        print()
        print("Note: Boundary session recordings are stored as channel recordings")
        print("with specific MIME types. The format depends on the target type")
        print("and recording configuration. RDP sessions typically produce video")
        print("streams that can be played with standard media players.")
    else:
        print("Download completed but file not found at expected path.")


def main():
    parser = argparse.ArgumentParser(description="Retrieve Boundary session recordings")
    parser.add_argument("--download", help="Download a specific recording by ID")
    parser.add_argument("--output", default="/tmp/recording.tar", help="Output path for downloaded recording")
    args = parser.parse_args()

    token = get_token()
    if not token:
        print("Failed to obtain Boundary token")
        sys.exit(1)

    if args.download:
        download_recording(token, args.download, args.output)
    else:
        list_recordings(token)


if __name__ == "__main__":
    main()
