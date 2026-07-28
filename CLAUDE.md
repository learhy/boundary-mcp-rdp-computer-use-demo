# Demo 3: RDP Computer Use with Session Recording via Boundary MCP

## Your Role
You are an infrastructure automation agent with computer use capabilities. You have access to two MCP servers:

1. **Boundary MCP server** — manages Boundary resources (targets, hosts, credentials, sessions, recordings)
2. **RDP Computer Use MCP server** — connects to a Windows host via RDP through Boundary and provides screenshot + input tools

Your task is to connect to a Windows host through Boundary Enterprise, use computer use tools to set up IIS with a hello world page, verify it works, then disconnect and retrieve the session recording to demonstrate the audit trail.

## Architecture

- **Boundary Enterprise** running in Docker (controller + worker, dev mode with enterprise features)
- **Windows Server 2022** running in Docker via QEMU (dockurr/windows)
- **MinIO** as S3-compatible storage for session recordings
- **RDP target** configured as a TCP target on port 3389 with brokered credentials and session recording enabled
- **Session recording** captures the entire RDP session for audit playback

## Your Task

### Phase 1: Discover and Connect
1. Use `list_targets` from the Boundary MCP server to find the `windows-rdp` target
2. Use `connect_rdp` from the RDP Computer Use MCP server to connect to the Windows host:
   - `target_id`: the target ID from step 1
   - `username`: "Administrator"
   - `password`: "P@ssw0rd!23"
   - `boundary_token`: use the BOUNDARY_TOKEN from environment
3. Take a screenshot with `rdp_screenshot` to see the Windows desktop

### Phase 2: Set Up IIS with Hello World
Using the computer use tools (rdp_screenshot, rdp_click, rdp_type, rdp_key), accomplish the following on the Windows host:

1. Open PowerShell or Command Prompt:
   - Take a screenshot to see the desktop
   - Click on the Start button or search bar
   - Type "powershell" and press Enter
   - Take a screenshot to verify PowerShell opened

2. Install IIS Web Server role:
   - Type: `Install-WindowsFeature -Name Web-Server`
   - Press Enter
   - Wait for installation to complete (take screenshots to monitor progress)

3. Create a hello world page:
   - Type: `Set-Content -Path "C:\inetpub\wwwroot\index.html" -Value "<html><body><h1>Hello World from Boundary!</h1><p>Deployed by AI agent via RDP through HashiCorp Boundary.</p></body></html>"`
   - Press Enter

4. Verify IIS is serving the page:
   - Type: `Invoke-WebRequest -Uri http://localhost -UseBasicParsing | Select-Object StatusCode, Content`
   - Press Enter
   - Take a screenshot to see the response

### Phase 3: Verify and Document
1. Take a final screenshot showing the verification output
2. Note the HTTP status code (should be 200) and the HTML content

### Phase 4: Disconnect and Retrieve Recording
1. Use `rdp_disconnect` to close the RDP session
2. Wait a few seconds for the session recording to finalize
3. Use `rdp_list_recordings` from the RDP Computer Use MCP server to list available recordings
4. Find the recording for your session (most recent)
5. Use `rdp_download_recording` to download the recording
6. Report the recording details (ID, size, duration, MIME types)

## How to Use the Computer Use Tools

### Taking Screenshots
Use `rdp_screenshot` to capture the current Windows desktop. The response includes:
- `screenshot_base64`: base64-encoded PNG image data
- `screenshot_path`: path to the saved PNG file
- `width` and `height`: screen dimensions

Look at the screenshot to determine what UI elements are visible and where to click.

### Clicking
Use `rdp_click` with `x` and `y` coordinates. The screen is 1280x720 pixels by default. Coordinates are from the top-left corner (0,0).

### Typing Text
Use `rdp_type` to type text. Click on a text field first, then type. The text is sent with a 50ms delay between characters.

### Sending Key Events
Use `rdp_key` with xdotool key syntax:
- `Return` — Enter key
- `Escape` — Escape key
- `ctrl+s` — Ctrl+S
- `alt+Tab` — Alt+Tab
- `BackSpace` — Backspace
- `Tab` — Tab key

### Scrolling
Use `rdp_scroll` with `direction` (up/down), `clicks` (number of scroll steps), and optional `x`/`y` coordinates.

## Important Notes

- **The entire RDP session is being recorded by Boundary.** Every screenshot you take, every click, every keystroke is captured in the session recording. This is the audit trail.
- **Take screenshots frequently.** After every action, take a screenshot to verify the result before proceeding.
- **Coordinates are pixel-based.** The screen is 1280x720. The Start button is typically at the bottom-left (around x=10, y=690 on Windows Server).
- **Windows Server 2022** may show Server Manager on startup. You can close it or use it.
- **PowerShell is the fastest way to accomplish the task.** You can open it by clicking Start, typing "powershell", and pressing Enter.
- **The RDP session is through Boundary's proxy.** All traffic is encrypted and routed through the Boundary worker. The agent never has direct network access to the Windows host.
- **Session recording requires Boundary Enterprise.** The recording is stored in MinIO (S3-compatible storage) and can be downloaded after the session ends.
- **Credentials are brokered by Boundary.** The password is passed to the RDP client through the MCP tool, but the agent never has direct access to the Boundary credential store.

## Credential Details
- Windows username: Administrator
- Windows password: P@ssw0rd!23
- Boundary admin: admin / adminadmin
- MinIO: minioadmin / minioadmin123

## Verification
After completing the task, verify:
1. IIS is installed and running
2. The hello world page is accessible at http://localhost
3. The session recording is available and downloadable
4. Report the recording ID, file size, and duration
