# RDP Computer Use Tool Evaluation

## Context

This demo needs an agent to connect to a Windows host through Boundary via RDP,
capture screenshots of the desktop, and inject mouse clicks and keyboard input.
The agent operates on a Linux Docker host with no physical display (headless).
The RDP session is proxied through Boundary, meaning the client connects to a
local proxied host:port, not a direct RDP URL.

This document evaluates the available tools and justifies the selection.

## Evaluation Criteria

1. **Screenshot capture** — can it grab a frame from the active RDP session?
2. **Input injection** — can it send mouse clicks and keyboard events?
3. **Linux compatibility** — does it run on the Docker host (Ubuntu 24.04)?
4. **Boundary proxy compatibility** — can it connect to a proxied host:port?
5. **Headless operation** — does it work without a physical display?
6. **Programmatic API** — can it be wrapped as MCP tools (Python, Go, or CLI)?
7. **Maintenance status** — is it actively maintained?
8. **Performance** — is the screenshot + input latency acceptable for agent use?

## Candidates Evaluated

### 1. FreeRDP3 (xfreerdp3-x11)

**Version**: 3.30.0 (Ubuntu 24.04 package)
**Install**: `apt install freerdp3-x11`

- **Screenshot**: Yes. xfreerdp3 has a `/screenshot:filename` flag that captures
  the current frame to a file. However, this is a one-shot capture at connection
  time, not a continuous stream.
- **Input injection**: Yes. FreeRDP3 forwards X11 input events to the RDP session.
  Mouse and keyboard events sent to the X11 window are forwarded to the remote
  Windows host.
- **Linux**: Yes. Native Linux binary.
- **Boundary proxy**: Yes. xfreerdp3 accepts `/v:HOST:PORT` and can connect to
  any TCP endpoint, including a Boundary proxy port.
- **Headless**: Requires Xvfb (virtual framebuffer). Without a real display,
  xfreerdp3 needs `xvfb-run` or a manual Xvfb + DISPLAY setup. This works but
  adds complexity.
- **Programmatic API**: No Python bindings. CLI only. Would need to use
  `xdotool` for input injection and `import`/`scrot` for screenshots on the Xvfb
  display where xfreerdp3 is running.
- **Maintenance**: Actively maintained. FreeRDP 3.x is the current release line.
- **Performance**: Good. RDP is efficient for screen capture. Screenshot via
  `import -window root` on Xvfb is fast (~50ms).

**Verdict**: Viable but requires Xvfb + xdotool + scrot wrapper. The screenshot
  path is indirect (RDP → Xvfb framebuffer → scrot → PNG file). Input injection
  via xdotool is reliable but requires coordinate-based clicking, not element-
  based. Works but is a stack of 3 tools.

### 2. FreeRDP2 (xfreerdp2-x11)

**Version**: 2.11.5 (Ubuntu 24.04 package)
**Install**: `apt install freerdp2-x11`

Same architecture as FreeRDP3 but older. The `--append-header` flag and some
screenshot features differ. FreeRDP2 is the version used by Apache Guacamole
1.3.0 (libguac-client-rdp0t64 depends on libfreerdp2).

**Verdict**: Superseded by FreeRDP3 for direct use. Still relevant as the
  backend for Guacamole.

### 3. Apache Guacamole (guacd)

**Version**: 1.3.0 (Ubuntu 24.04 package)
**Install**: `apt install guacd libguac-dev libguac-client-rdp0t64`

- **Screenshot**: No direct screenshot API. guacd is a proxy daemon that
  translates RDP to Guacamole's own protocol for web-based rendering. There is
  no CLI or API to grab a frame from the RDP session.
- **Input injection**: No direct input API. Input is sent via the Guacamole
  protocol (WebSocket), which requires a WebSocket client implementation.
- **Linux**: Yes.
- **Boundary proxy**: guacd connects to RDP backends, so it could connect to a
  Boundary proxy port. But the output is Guacamole protocol, not screenshots.
- **Headless**: Yes, guacd is designed to run headless.
- **Programmatic API**: C library (libguac). No Python bindings. Would need a
  custom Guacamole protocol client to send/receive frames and input.
- **Maintenance**: v1.3.0 is from 2020. v1.5.5 is the latest but not in Ubuntu
  24.04 repos. Would need to build from source or use a Docker image.
- **Performance**: Low overhead, but the lack of screenshot/input API makes it
  unusable without significant custom development.

**Verdict**: Rejected. The architecture is wrong for this use case. Guacamole
  is designed for web-based RDP access, not programmatic screenshot + input.
  Would require building a custom Guacamole protocol client, which is a
  separate project.

### 4. pyrdp

**Version**: 0.1.6 (PyPI)
**Install**: `pip install pyrdp`

- **Screenshot**: No. pyrdp is a minimal RDP protocol library. It handles the
  RDP handshake and basic channel data but does not decode screen frames.
- **Input injection**: No. No input API.
- **Linux**: Yes.
- **Boundary proxy**: Theoretically yes (it's a TCP connection), but without
  screenshot/input it doesn't matter.
- **Headless**: Yes.
- **Programmatic API**: Python, but the API is too low-level. No screen or
  input abstractions.
- **Maintenance**: Last release 2022. Minimal package (3KB wheel).

**Verdict**: Rejected. Too low-level. No screenshot or input capabilities.

### 5. rdesktop

**Version**: Not in Ubuntu 24.04 repos. Would need to build from source.
**Install**: N/A

- **Screenshot**: No screenshot API.
- **Input injection**: No input API.
- **Maintenance**: Last release 2011. Abandoned.

**Verdict**: Rejected. Abandoned project with no programmatic API.

### 6. Microsoft RDP ActiveX Control (mstscax.dll)

- **Linux**: No. Windows-only COM component.
- **Programmatic API**: COM/Automation, Windows-only.

**Verdict**: Rejected. Not available on Linux.

### 7. xpra

**Version**: 3.1.5 (Ubuntu 24.04)
**Install**: `apt install xpra`

- **Screenshot**: Yes. xpra can capture frames from its session.
- **Input injection**: Yes. xpra has input injection APIs.
- **Linux**: Yes.
- **Boundary proxy**: xpra uses its own protocol, not RDP. Would need an RDP-
  to-xpra bridge, which doesn't exist.
- **Headless**: Yes, xpra is designed for headless operation.
- **Programmatic API**: Python and CLI.
- **Maintenance**: Actively maintained.

**Verdict**: Rejected. xpra is not an RDP client. It's a screen-forwarding
  protocol for X11 applications. Cannot connect to a Windows RDP endpoint.

### 8. Xvfb + xfreerdp3 + xdotool + scrot (The "Virtual Display" Stack)

This is not a single tool but a composition:

1. **Xvfb** starts a virtual framebuffer (e.g., display :99, 1280x720)
2. **xfreerdp3** connects to the RDP target through the Boundary proxy and
   renders into the Xvfb display
3. **scrot** or `import -window root` captures screenshots from the Xvfb
   framebuffer as PNG files
4. **xdotool** sends mouse clicks and keyboard events to the xfreerdp3 window
   on the Xvfb display, which forwards them to the Windows host via RDP

- **Screenshot**: Yes. `DISPLAY=:99 import -window root /tmp/screenshot.png`
- **Input injection**: Yes. `DISPLAY=:99 xdotool click 1` / `xdotool type "text"`
- **Linux**: Yes. All components are native Linux.
- **Boundary proxy**: Yes. xfreerdp3 connects to `BOUNDARY_PROXIED_IP:BOUNDARY_PROXIED_PORT`
- **Headless**: Yes. Xvfb is designed for headless operation.
- **Programmatic API**: CLI tools, easily wrapped in Python or Go.
- **Maintenance**: All components are actively maintained and in Ubuntu 24.04.
- **Performance**: Good. Screenshot capture ~50-100ms. Input injection ~10ms.
  RDP frame updates are near-real-time.

**Verdict**: This is the best approach. Each component is mature, well-
  documented, and available in standard repos. The composition is
  straightforward to wrap as MCP tools:
  - `connect_rdp` — starts Xvfb + xfreerdp3 in the background
  - `rdp_screenshot` — captures the Xvfb framebuffer to PNG
  - `rdp_click` — uses xdotool to click at coordinates
  - `rdp_type` — uses xdotool to type text
  - `rdp_key` — uses xdotool to send key events
  - `rdp_disconnect` — kills the xfreerdp3 + Xvfb processes

### 9. cua-driver (trycua/cua)

This is the computer-use library that Hermes uses for its `computer_use` tool.
It supports Linux (AT-SPI), macOS (AXUI), and Windows (UIA).

- **Screenshot**: Yes, via platform accessibility frameworks.
- **Input injection**: Yes, via platform APIs.
- **Linux**: Yes.
- **Boundary proxy**: No. cua-driver operates on the local desktop, not over
  RDP. It would need to be combined with an RDP client to work with remote
  Windows hosts.
- **Headless**: Needs a display. Could work with Xvfb if the RDP client renders
  to it, but cua-driver expects to interact with local applications, not RDP
  client windows.
- **Programmatic API**: MCP tools.
- **Maintenance**: Actively maintained.

**Verdict**: Not directly applicable. cua-driver drives the local desktop, not
  a remote RDP session. It could potentially be combined with xfreerdp3 on
  Xvfb, but then you'd use xdotool directly instead of going through cua-driver's
  accessibility layer (which would try to parse the RDP client's UI, not the
  Windows desktop inside it).

## Selection: Xvfb + xfreerdp3 + xdotool + scrot

The "Virtual Display Stack" is the best tool for this demo because:

1. **It works with Boundary's proxy model.** xfreerdp3 connects to any TCP
   endpoint, including Boundary's local proxy port. No special integration
   needed.
2. **It's headless.** Xvfb provides a virtual framebuffer, so no physical
   display is required. The entire stack runs in Docker.
3. **Each component is mature and well-documented.** Xvfb, xfreerdp3,
   xdotool, and scrot are all standard Linux tools with years of production use.
4. **The MCP tool wrapper is straightforward.** Each operation (screenshot,
   click, type, key press) maps to a single CLI command. The MCP server is a
   thin Python layer that manages the Xvfb + xfreerdp3 lifecycle and wraps the
   CLI tools.
5. **It's fast enough for agent use.** Screenshot capture takes ~50-100ms,
   input injection ~10ms. The agent can interact with the Windows desktop in
   near-real-time.
6. **It's actively maintained.** All components are in Ubuntu 24.04 repos and
   receive regular updates.

The main limitation is that input is coordinate-based, not element-based. The
agent must look at the screenshot and decide where to click, rather than
targeting UI elements by accessibility tree. This is acceptable for the demo
because the agent (IBM Bob) has vision capabilities and can interpret
screenshots to determine click targets.

## Alternative Considered: FreeRDP3 with /screenshot flag

FreeRDP3 has a built-in `/screenshot:filename` flag. However, this captures
a single frame at connection time (or on demand via a signal), not
continuously. For interactive agent use, we need to capture screenshots on
demand at any point during the session. The Xvfb + scrot approach allows this
without reconnecting.

Additionally, FreeRDP3's `/screenshot` writes to a fixed filename, which makes
it awkward for multiple captures. The Xvfb + scrot approach gives us full
control over filenames and timing.

## Alternative Considered: FreeRDP3 with /smart-sizing and /clipboard

FreeRDP3 supports clipboard redirection (`+clipboard`) and smart sizing
(`/smart-sizing`). These could be useful for the agent to copy/paste text
between the local environment and the Windows host. We include clipboard
support in the xfreerdp3 command line as an enhancement, but the primary
interaction is via screenshot + xdotool.
