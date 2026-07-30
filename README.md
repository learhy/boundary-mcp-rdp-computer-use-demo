# Boundary MCP RDP Computer Use Demo

An AI agent (IBM Bob) connects to a remote Windows host through HashiCorp Boundary using the RDP target type, uses computer use tools (screenshot, click, type, key press) to install IIS, create a new Windows user, serve a hello world web page, verify it in a browser, edit the page, verify the update, and retrieves the session recording to demonstrate the audit trail.

## Two Modes

This demo supports two Boundary deployment modes:

### Mode 1: HCP Boundary (recommended, with session recording)

Uses [HCP Boundary](https://developer.hashicorp.com/hcp/docs/boundary) (managed SaaS) with Terraform to provision the cluster and all resources. Users supply only an HCP service principal client ID and secret — Terraform creates the cluster, provisions all Boundary resources, and outputs the target ID.

**Pros:** Session recording supported, no license management, managed infrastructure, fully automated via Terraform.
**Cons:** Requires an HCP account. For session recording, the S3-compatible storage endpoint (MinIO) must be publicly reachable from HCP workers. Use an actual S3 bucket or deploy MinIO on a cloud VM if your local MinIO isn't publicly accessible.

### Mode 2: Self-hosted Boundary dev mode (for local testing, no recording)

Uses `boundary dev` in Docker. Works for the RDP computer use flow but does NOT support session recording (dev mode doesn't enable enterprise features even with a license).

**Pros:** No HCP account needed, everything runs locally.
**Cons:** No session recording.

## What the Demo Shows

1. **RDP access via Boundary** — a remote Windows host (e.g. AWS EC2 Windows Server) is registered as a Boundary TCP target on port 3389. Boundary brokers credentials so the agent authenticates without handling passwords directly. The entire session is proxied through a Boundary worker.

2. **Agent-driven computer use** — the agent takes screenshots of the Windows desktop, identifies UI elements by looking at the pixels, clicks on targets, types commands, and sends key events. It installs IIS, creates a hello world page, creates a new Windows local user, opens the page in Edge browser, edits the page content, and verifies the update in the browser.

3. **Session recording for audit** (HCP mode only) — the RDP target has session recording enabled with a MinIO storage bucket. Every frame, every click, every keystroke is captured. After the session ends, the recording is available for download and playback.

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
            +-- rdp_export_recording --> boundary export → poll → MinIO download (WebM)

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
| Docker + Docker Compose | [docs.docker.com](https://docs.docker.com/get-docker/) | For MinIO (Mode 1) or full stack (Mode 2) |
| Go 1.22+ | [go.dev/dl](https://go.dev/dl/) | For building boundary-mcp |
| `boundary` CLI | [developer.hashicorp.com/boundary/install](https://developer.hashicorp.com/boundary/install) | |
| `python3` | `apt install python3` | |
| `terraform` | [developer.hashicorp.com/terraform/install](https://developer.hashicorp.com/terraform/install) | Required for Mode 1 (HCP Boundary) |
| IBM Bob | Internal IBM tool | Any MCP-compatible agent works |
| HCP Boundary account | [cloud.hashicorp.com](https://cloud.hashicorp.com) | Required for Mode 1 (session recording) |
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

## Quick Start

```bash
# 1. Clone repos
git clone https://github.com/learhy/boundary-mcp.git ~/software/boundary-mcp
git clone https://github.com/learhy/boundary-mcp-rdp-computer-use-demo.git

# 2. Configure
cd boundary-mcp-rdp-computer-use-demo
cp demo.tfvars.example demo.tfvars
# Edit demo.tfvars with your HCP SP credentials + Windows host + MinIO endpoint

# 3. Provision everything (builds boundary-mcp, creates HCP cluster, provisions resources, generates .mcp.json)
./demo.sh --setup

# 4. Run the agent
./demo.sh --run

# 5. Export the session recording as WebM
./demo.sh --export <sr_ID>

# 6. Tear everything down when done
./demo.sh --teardown
```

## Manual Step-by-Step Reproduction

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

### Step 3: Choose your Boundary mode

#### Mode 1: HCP Boundary (with session recording)

**3a. Create the HCP Boundary cluster with Terraform**

```bash
cd boundary-mcp-rdp-computer-use-demo/terraform/01-cluster
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your HCP service principal client ID and secret

terraform init
terraform apply
```

This creates an HCP Boundary cluster. Note the `boundary_cluster_url` from the output.

**3b. Provision Boundary resources with Terraform**

```bash
cd ../02-resources
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars:
#   boundary_addr = the cluster URL from step 3a
#   boundary_admin_password = the admin password from step 3a
#   windows_host_ip, windows_username, windows_password = your Windows host
#   minio_endpoint = publicly reachable MinIO URL (for session recording)
#   enable_recording = true (set to false if MinIO isn't publicly reachable)

terraform init
terraform apply
```

Terraform creates: org, project, host catalog, host, host set, credential store, credential, storage bucket (if `enable_recording=true`), and the RDP target.

Note the `target_id` and `boundary_addr` from the Terraform output.

**3c. Get an auth token**

```bash
export BOUNDARY_ADDR=https://YOUR_CLUSTER.boundary.hashicorp.cloud
boundary authenticate password \
  -login-name admin \
  -password env://BOUNDARY_ADMIN_PASSWORD
```

Save the token from the output.

#### Mode 2: Self-hosted Boundary dev mode (no recording)

```bash
cd boundary-mcp-rdp-computer-use-demo/docker
docker compose up -d
```

This starts 3 services:

| Container | Purpose | Host port |
|---|---|---|
| `rdp-demo-boundary` | Boundary (controller + worker, dev mode) | 9220 (API), 9322 (proxy) |
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
6. Clicks on the Start button or search bar, types "powershell", presses Enter
7. In PowerShell, types `Install-WindowsFeature -Name Web-Server` and presses Enter
8. Waits for IIS installation to complete (takes screenshots to monitor)
9. Creates the hello world page: `Set-Content -Path "C:\inetpub\wwwroot\hello.html" -Value "<html><body><h1>Hello World from Boundary!</h1><p>Deployed by AI agent via RDP through HashiCorp Boundary.</p></body></html>" -Force`
10. Verifies with: `C:\Windows\System32\curl.exe -s http://localhost/hello.html` and checks HTTP status is 200

**Phase 3: Create a New Windows User**
11. Creates a local user: `New-LocalUser -Name "demo-user" -Description "Demo user created by AI agent" -NoPassword`
12. Adds to Users group: `Add-LocalGroupMember -Group "Users" -Member "demo-user"`
13. Verifies the user: `Get-LocalUser -Name "demo-user" | Select-Object Name, Enabled, Description`

**Phase 4: Open the Web Page in a Browser**
14. Opens Edge: `Start-Process msedge "http://localhost/hello.html"`
15. Waits 3-4 seconds, takes a screenshot to see the page rendered in the browser
16. Verifies the page shows "Hello World from Boundary!"

**Phase 5: Edit the Page and Verify the Update**
17. Returns to PowerShell (Alt+Tab or click)
18. Edits the page: `Set-Content -Path "C:\inetpub\wwwroot\hello.html" -Value "<html><body><h1>Hello World from Boundary - UPDATED!</h1><p>This page was edited by an AI agent via RDP.</p><p>User demo-user was created.</p></body></html>" -Force`
19. Switches to Edge, presses F5 to refresh
20. Takes a screenshot to verify the page now shows "Hello World from Boundary - UPDATED!"
21. Confirms the update with curl back in PowerShell

**Phase 6: Disconnect and Retrieve Recording**
22. Calls `rdp_disconnect` to close the RDP session
23. Waits for the session recording to finalize
24. Calls `rdp_list_recordings` to list available recordings
25. Calls `rdp_export_recording` to export the recording as WebM video
26. Reports the recording ID, file size, and duration

### Step 8: Export the session recording as WebM video

After the agent completes its task and the session is disconnected, export the recording as a WebM video:

```bash
# Set MinIO credentials for the export download
export MINIO_ENDPOINT=http://178.104.180.23:9230
export MINIO_ACCESS_KEY=minioadmin
export MINIO_SECRET_KEY=minioadmin123

# Export via the RDP MCP server tool (if running the agent)
# The agent calls rdp_export_recording with the session recording ID

# Or manually: trigger export via boundary CLI, then download from MinIO
boundary session-recordings export -connection-recording-id <cr_ID> -mime-type video/webm
# Poll until state=finished, then download the .webm from MinIO at:
#   {recording_id}.export/{connection_recording_id}.export/srv_*/srv_*.webm
```

The WebM export requires the `/gfx` flag in xfreerdp3 (enabled by default in the RDP MCP server). This enables the RDP 8.0+ graphics pipeline, which is required for the BSR recording to include the `Microsoft::Windows::RDS::Graphics` dynamic virtual channel. Without it, the WebM export will fail.

### Step 9: Access and replay the session recording

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

### Session Recording (HCP Boundary mode only)

Boundary captures the entire RDP session as a recording:

1. The target is created with `enable_session_recording=true` and a `storage_bucket_id` pointing to the MinIO bucket (done by Terraform in HCP mode)
2. When the agent connects, Boundary starts recording all traffic on the session
3. The recording includes all screen updates, input events, and channel data
4. When the session ends (agent disconnects), Boundary finalizes the recording and stores it in MinIO
5. The recording can be listed, downloaded, and played back

This is the PAM audit story: every action the agent took on the Windows host is captured and verifiable. A security team can review the recording to confirm the agent only did what it was supposed to do.

> **Note:** Session recording requires HCP Boundary or a self-hosted Boundary Enterprise deployment (not dev mode). The Terraform config in `terraform/main.tf` provisions the storage bucket and enables recording on the target.

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

### WebM export fails (no graphics channel)
- The `/gfx` flag must be present in the xfreerdp3 args (it is by default in the RDP MCP server)
- Without `/gfx`, the BSR recording lacks the `Microsoft::Windows::RDS::Graphics` dynamic virtual channel
- The export will complete but the WebM will be empty or fail to render
- **Do NOT use `/gfx:on`** — FreeRDP 3.30.0 rejects this syntax. Use the bare `/gfx` flag.

### IIS returns HTTP 500 (0x80070020 sharing violation)
- On Windows Server 2022, the default `index.html` in `C:\inetpub\wwwroot` can get locked by the IIS worker process
- Use a unique filename like `hello.html` instead of `index.html`
- Access the page at `http://localhost/hello.html` (not the root)
- Use `C:\Windows\System32\curl.exe` instead of the PowerShell `curl` alias (which is `Invoke-WebRequest`)
- If the file is already locked: `iisreset /stop`, `Get-Process w3wp | Stop-Process -Force`, then create a new file

### Port conflicts
- This demo uses ports 9220-9222 (Boundary), 9230-9231 (MinIO)
- If you have other services on these ports, edit `docker-compose.yml`

## File Structure

```
boundary-mcp-rdp-computer-use-demo/
+-- demo.sh                          # One-command setup/run/teardown/export script
+-- demo.tfvars.example              # Configuration template (copy to demo.tfvars)
+-- README.md                        # This file
+-- TOOLS_EVAL.md                    # RDP tool evaluation and selection rationale
+-- CLAUDE.md                          # Agent prompt for IBM Bob
+-- .mcp.json                          # MCP server config (template)
+-- docker/
|    +-- docker-compose.yml            # 3 services: Boundary + Postgres + MinIO
+-- terraform/
|    +-- 01-cluster/
|    |    +-- main.tf                   # Create HCP Boundary cluster (SP client_id/secret)
|    |    +-- terraform.tfvars.example  # Template for HCP SP credentials
|    +-- 02-resources/
|         +-- main.tf                   # Provision org, project, host, target, storage bucket
|         +-- terraform.tfvars.example  # Template for cluster URL + Windows host + MinIO
+-- rdp-mcp-server/
|    +-- server.py                     # RDP Computer Use MCP server (Python)
|    +-- Dockerfile                    # Docker image with all system dependencies
|    +-- requirements.txt              # Python dependencies (stdlib only)
+-- scripts/
     +-- bootstrap-boundary.py          # Create Boundary resources (Mode 2: dev mode)
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