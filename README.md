# Boundary MCP RDP Computer Use Demo

An AI agent (IBM Bob) connects to a remote Windows host through HashiCorp Boundary Enterprise using the RDP target type, uses computer use tools (screenshot, click, type, key press) to set up IIS with a hello world page, and retrieves the session recording to demonstrate the audit trail.

## What the Demo Shows

1. **RDP access via Boundary Enterprise** — a remote Windows host (e.g. AWS EC2 Windows Server) is registered as a Boundary TCP target on port 3389. Boundary brokers credentials so the agent authenticates without handling passwords directly. The entire session is proxied through a Boundary worker.

2. **Agent-driven computer use** — the agent takes screenshots of the Windows desktop, identifies UI elements by looking at the pixels, clicks on targets, types commands, and sends key events. It installs IIS, creates a hello world page, and verifies the site is serving.

3. **Session recording for audit** — the RDP target has session recording enabled with a MinIO storage bucket. Every frame, every click, every keystroke is captured. After the session ends, the recording is available for download and playback.

## Architecture

```
IBM Bob (agent)
    |
    +-- Boundary MCP Server (48 tools)
    |       +-- list_targets, authorize_session, etc.
    |
    +-- RDP Computer Use MCP Server (11 tools)
            +-- connect_rdp --> boundary connect (TCP proxy)
            |                       +-- xfreerdp3 -> Xvfb (headless)
            +-- rdp_screenshot --> import/scrot on Xvfb display
            +-- rdp_click --> xdotool on Xvfb display
            +-- rdp_type --> xdotool on Xvfb display
            +-- rdp_key --> xdotool on Xvfb display
            +-- rdp_disconnect --> kill xfreerdp3 + Xvfb
            +-- rdp_list_recordings --> boundary session-recordings list
            +-- rdp_download_recording --> boundary session-recordings download

                    [Internet / VPC]
                          |
                    +-----------+
                    | Windows   |
                    | Host      |
                    | (AWS EC2) |
                    | RDP :3389 |
                    +-----------+
```

## Prerequisites

| Requirement | Install command | Notes |
|---|---|---|
| Docker + Docker Compose | [docs.docker.com](https://docs.docker.com/get-docker/) | |
| Go 1.22+ | [go.dev/dl](https://go.dev/dl/) | For building boundary-mcp |
| `boundary` CLI | [developer.hashicorp.com/boundary/install](https://developer.hashicorp.com/boundary/install) | |
| `python3` | `apt install python3` | |
| IBM Bob | Internal IBM tool | Any MCP-compatible agent works |
| Boundary Enterprise license | HashiCorp sales / trial | Required for session recording |
| Remote Windows host | AWS EC2 / Azure VM / etc. | RDP enabled on port 3389 |

### System packages for the RDP MCP server

```bash
sudo apt install xvfb freerdp3-x11 xdotool scrot imagemagick
```

### Windows host setup (AWS EC2 or similar)

1. Launch a Windows Server instance (2019 or 2022) on AWS EC2
2. Ensure the security group allows RDP (port 3389) from the Boundary worker's IP
3. Note the instance's private or public IP
4. Set the Administrator password (or use the EC2 key pair retrieval)
5. Verify RDP is enabled (it is by default on AWS Windows AMIs)

## Step-by-Step Reproduction

### Step 1: Clone the repos

```bash
git clone https://github.com/learhy/boundary-mcp.git
git clone https://github.com/learhy/boundary-mcp-rdp-computer-use-demo.git
```

### Step 2: Build the Boundary MCP server

```bash
cd boundary-mcp
go build -o boundary-mcp ./cmd/boundary-mcp/
```

Note the absolute path to the built binary.

### Step 3: Start the Docker stack

The Docker stack runs Boundary, PostgreSQL, and MinIO. The Windows host is NOT in the stack — it runs separately on AWS.

```bash
cd boundary-mcp-rdp-computer-use-demo/docker
docker compose up -d --build
```

This starts 3 services:

| Container | Purpose | Host port |
|---|---|---|
| `rdp-demo-boundary` | Boundary Enterprise (controller + worker, dev mode) | 9220 (API), 9222 (proxy) |
| `rdp-demo-db` | PostgreSQL for Boundary state | internal |
| `rdp-demo-minio` | MinIO (S3-compatible storage for session recordings) | 9230 (S3 API), 9231 (console) |

Wait ~15 seconds for Boundary to initialize. Verify:

```bash
# Check Boundary is up
curl -s http://127.0.0.1:9220/v1/scopes/global
# Should return JSON (401 is expected -- API is working)

# Check MinIO is up
curl -s http://127.0.0.1:9230/minio/health/live
# Should return 200 OK
```

### Step 4: Bootstrap Boundary resources

The bootstrap script creates all the Boundary resources needed: org, project, host catalog, remote Windows host, host set, credential store with username/password, MinIO storage bucket for session recordings, and a TCP target on port 3389 with brokered credentials and session recording enabled.

You need to provide the Windows host's IP and credentials via environment variables:

```bash
cd boundary-mcp-rdp-computer-use-demo/scripts

export WINDOWS_HOST_IP=10.0.1.42       # Your Windows host's IP
export WINDOWS_USERNAME=Administrator  # Windows RDP username
export WINDOWS_PASSWORD=YourPassword123 # Windows RDP password

BOUNDARY_ADDR=http://127.0.0.1:9220 python3 bootstrap-boundary.py
```

Expected output:

```
=== Demo 3: RDP Computer Use with Session Recording Bootstrap ===
Windows host: 10.0.1.42:3389
Windows user: Administrator

Waiting for Boundary controller... OK
Waiting for MinIO... OK
Authenticating... OK (token: at_xxxxx...)

=== Creating org and project ===
Org: o_xxx  Project: p_xxx

=== Creating host catalog, host, and host set ===
  Host Catalog: hcst_xxx
  Host windows-remote (10.0.1.42): hst_xxx
  Host Set windows-remote-set: hsst_xxx

=== Creating credentials ===
  Credential Store: csst_xxx
  Credential: credup_xxx

=== Creating storage bucket for session recordings ===
  Storage Bucket: ssob_xxx

=== Creating RDP target (TCP port 3389) ===
  Target windows-rdp: ttcp_xxx
    host source added
    brokered credential added

=== Bootstrap complete ===
Token for .mcp.json: at_xxxxxxxxx
```

Save the token from the last line.

### Step 5: Configure the MCP servers

Update `.mcp.json` in the repo root with the correct paths and token:

```bash
cd boundary-mcp-rdp-computer-use-demo
cat > .mcp.json << 'EOF'
{
  "mcpServers": {
    "boundary": {
      "command": "/absolute/path/to/boundary-mcp/boundary-mcp",
      "env": {
        "BOUNDARY_ADDR": "http://127.0.0.1:9220",
        "BOUNDARY_TOKEN": "PASTE_TOKEN_FROM_BOOTSTRAP",
        "BOUNDARY_TLS_INSECURE": "true"
      }
    },
    "rdp-computer-use": {
      "command": "python3",
      "args": ["/absolute/path/to/demo3-rdp-computer-use/rdp-mcp-server/server.py"],
      "env": {
        "BOUNDARY_ADDR": "http://127.0.0.1:9220",
        "BOUNDARY_TOKEN": "PASTE_TOKEN_FROM_BOOTSTRAP"
      }
    }
  }
}
EOF
```

Replace the paths and token with your actual values.

### Step 6: Run the agent

```bash
cd boundary-mcp-rdp-computer-use-demo
ibm-bob --config .mcp.json -p "$(cat CLAUDE.md)"
```

Or interactively:

```bash
ibm-bob --config .mcp.json
# Then paste the contents of CLAUDE.md as your prompt
```

### Step 7: What the agent does

**Phase 1: Discover and Connect**
1. Calls `list_targets` to find the `windows-rdp` target
2. Calls `connect_rdp` with the target ID, username, and password
3. The RDP MCP server starts Xvfb (virtual framebuffer), connects `boundary connect` to get a local proxy port, then launches `xfreerdp3` to connect to the remote Windows host through the Boundary proxy
4. Takes an initial screenshot to verify the connection

**Phase 2: Set Up IIS**
5. Takes a screenshot to see the Windows desktop
6. Clicks on the Start button or search bar
7. Types "powershell" and presses Enter
8. In PowerShell, types `Install-WindowsFeature -Name Web-Server` and presses Enter
9. Waits for IIS installation to complete (takes screenshots to monitor)
10. Types the command to create `index.html` with hello world content
11. Types `Invoke-WebRequest -Uri http://localhost -UseBasicParsing` to verify

**Phase 3: Verify**
12. Takes a final screenshot showing the HTTP 200 response and HTML content

**Phase 4: Disconnect and Retrieve Recording**
13. Calls `rdp_disconnect` to close the RDP session
14. Waits for the session recording to finalize
15. Calls `rdp_list_recordings` to list available recordings
16. Calls `rdp_download_recording` to download the recording
17. Reports the recording ID, file size, and duration

### Step 8: Access and replay the session recording

After the agent completes its task, you can retrieve and play back the session recording:

```bash
# List all recordings
cd boundary-mcp-rdp-computer-use-demo/scripts
BOUNDARY_ADDR=http://127.0.0.1:9220 python3 retrieve-recordings.py

# Download a specific recording
BOUNDARY_ADDR=http://127.0.0.1:9220 python3 retrieve-recordings.py \
  --download <recording-id> --output /tmp/session-recording.tar

# Extract and play
tar xf /tmp/session-recording.tar
# Look for video/webm or other media files
# Play with VLC, mpv, or any media player
```

You can also access the MinIO web console to browse recordings directly:

```
http://127.0.0.1:9231
Username: minioadmin
Password: minioadmin123
```

## How It Works

### The Virtual Display Stack (Xvfb + xfreerdp3 + xdotool + scrot)

The RDP Computer Use MCP server uses a "virtual display" approach to interact with the Windows desktop programmatically:

1. **Xvfb** starts a virtual framebuffer on display `:99` at 1280x720x24 resolution. This provides a "screen" without requiring a physical monitor.

2. **boundary connect** starts a local TCP proxy that tunnels traffic to the remote Windows host through the Boundary worker. The proxy listens on a random local port.

3. **xfreerdp3** connects to the Boundary proxy port (not directly to the Windows host) and renders the Windows desktop into the Xvfb framebuffer. The RDP protocol handles screen updates, input forwarding, and clipboard sync.

4. **scrot / import (ImageMagick)** captures the Xvfb framebuffer as a PNG file. This is the screenshot the agent sees.

5. **xdotool** sends mouse clicks and keyboard events to the xfreerdp3 window on the Xvfb display. xfreerdp3 forwards these to the Windows host via RDP input channels.

```
Agent -> MCP tools -> xdotool -> Xvfb display :99 -> xfreerdp3 -> RDP -> Boundary proxy -> [network] -> Windows host
Agent <- MCP tools <- scrot    <- Xvfb display :99 <- xfreerdp3 <- RDP <- Boundary proxy <- [network] <- Windows host
```

### Why This Approach?

See [TOOLS_EVAL.md](TOOLS_EVAL.md) for the full evaluation of RDP automation tools. The short version: FreeRDP3 + Xvfb + xdotool + scrot is the only stack that simultaneously supports screenshot capture, input injection, headless operation, and Boundary proxy compatibility on Linux.

### Session Recording

Boundary Enterprise captures the entire RDP session as a recording:

1. The target is created with `enable_session_recording=true` and a `storage_bucket_id` pointing to the MinIO bucket
2. When the agent connects, Boundary starts recording all traffic on the session
3. The recording includes all screen updates, input events, and channel data
4. When the session ends (agent disconnects), Boundary finalizes the recording and stores it in MinIO
5. The recording can be listed, downloaded, and played back

This is the PAM audit story: every action the agent took on the Windows host is captured and verifiable. A security team can review the recording to confirm the agent only did what it was supposed to do.

### Boundary Resource Model

```
Org: rdp-org
  +-- Project: rdp-project
       +-- Host Catalog: windows-hosts (static)
       |    +-- Host Set: windows-remote-set -> [windows-remote (REMOTE_IP)]
       +-- Credential Store: windows-creds (static)
       |    +-- Credential: windows-admin (username_password: Administrator / ***)
       +-- Storage Bucket: session-recording-bucket (MinIO/S3)
       +-- Target: windows-rdp (tcp, port 3389, host source: windows-remote-set,
                                 brokered cred: windows-admin,
                                 enable_session_recording: true,
                                 storage_bucket_id: session-recording-bucket)
```

## Troubleshooting

### Boundary won't start
- Check PostgreSQL: `docker logs rdp-demo-db`
- Check Boundary logs: `docker logs rdp-demo-boundary` -- look at the **first** error
- Enterprise features require a license. Set `BOUNDARY_LICENSE` env var or use HCP Boundary.
- If you see "license required" errors, session recording and RDP targets need Enterprise.

### Cannot connect to the remote Windows host
- Verify the Windows host is running and RDP is enabled
- Verify the security group / firewall allows port 3389 from the Boundary worker's IP
- Test RDP directly (bypassing Boundary): `xfreerdp3 /v:WINDOWS_HOST_IP:3389 /u:Administrator /p:PASSWORD`
- If the Windows host is in a private subnet, ensure the Boundary worker can reach it (VPN, peering, etc.)
- Check that the IP registered in Boundary matches the Windows host's reachable IP

### Storage bucket creation fails
- Verify MinIO is running: `curl http://127.0.0.1:9230/minio/health/live`
- Check MinIO credentials match between docker-compose.yml and bootstrap script
- The storage bucket plugin requires the `aws` plugin name with custom endpoint attributes
- Boundary Enterprise is required for storage buckets

### xfreerdp3 fails to connect through Boundary
- Verify the Boundary proxy is running: the `connect_rdp` tool starts `boundary connect` which creates a local proxy
- Check xfreerdp3 error output in the MCP server stderr
- Verify the Windows host has RDP enabled (port 3389)
- If you get "authentication error", verify the Windows username and password are correct
- If you get "connection refused", the Windows host may not be reachable from the Boundary worker

### Screenshots are black
- Verify Xvfb is running: `ps aux | grep Xvfb`
- Verify xfreerdp3 is running: `ps aux | grep xfreerdp`
- Check DISPLAY environment: the MCP server sets `DISPLAY=:99` for xfreerdp3 and screenshot tools
- Try `DISPLAY=:99 xdotool getactivewindow` to verify the display is working

### Agent can't click or type
- The agent must take a screenshot first to see the screen dimensions
- Coordinates are pixel-based: (0,0) is top-left, (1280,720) is bottom-right
- Click accuracy depends on the screenshot resolution matching the Xvfb resolution
- If clicks are offset, check that xfreerdp3 is using the same resolution as Xvfb

### Session recording is empty or missing
- Verify the target has `enable_session_recording=true`
- Verify the storage bucket ID is set on the target
- Check Boundary logs for recording errors: `docker logs rdp-demo-boundary 2>&1 | grep -i recording`
- The recording may take a few seconds to finalize after session end
- Try listing recordings: `BOUNDARY_ADDR=http://127.0.0.1:9220 python3 scripts/retrieve-recordings.py`

### Port conflicts
- This demo uses ports 9220-9222 (Boundary), 9230-9231 (MinIO)
- If you have other services on these ports, edit `docker-compose.yml`

## File Structure

```
boundary-mcp-rdp-computer-use-demo/
+-- README.md                          # This file
+-- TOOLS_EVAL.md                      # RDP tool evaluation and selection rationale
+-- CLAUDE.md                          # Agent prompt for IBM Bob
+-- .mcp.json                          # MCP server config (template)
+-- docker/
|    +-- docker-compose.yml            # 3 services: Boundary + Postgres + MinIO
+-- rdp-mcp-server/
|    +-- server.py                     # RDP Computer Use MCP server (Python)
|    +-- Dockerfile                    # Docker image with all system dependencies
|    +-- requirements.txt              # Python dependencies (stdlib only)
+-- scripts/
     +-- bootstrap-boundary.py          # Create all Boundary resources
     +-- retrieve-recordings.py        # List and download session recordings
```

## Using Other Agents

This demo works with any MCP-compatible AI agent. To use Claude Code instead of IBM Bob:

```bash
claude --dangerously-skip-permissions -p "$(cat CLAUDE.md)"
```

Configure Claude Code's MCP settings to point to both the `boundary` and `rdp-computer-use` MCP servers.

## Related

- [boundary-mcp](https://github.com/learhy/boundary-mcp) -- the Boundary MCP server (48 tools)
- [boundary-mcp-router-config-demo](https://github.com/learhy/boundary-mcp-router-config-demo) -- Demo 1: BGP router configuration
- [boundary-mcp-cert-rotation-demo](https://github.com/learhy/boundary-mcp-cert-rotation-demo) -- Demo 2: SSH certificate rotation