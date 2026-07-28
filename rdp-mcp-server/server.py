#!/usr/bin/env python3
"""
RDP Computer Use MCP Server

An MCP (Model Context Protocol) server that provides RDP connection and
computer use tools for interacting with a Windows desktop through a Boundary
proxy. Uses Xvfb + xfreerdp3 + xdotool + scrot as the underlying stack.

Tools provided:
  - connect_rdp: Start an RDP session through Boundary proxy
  - rdp_screenshot: Capture a screenshot of the Windows desktop
  - rdp_click: Click at coordinates on the Windows desktop
  - rdp_double_click: Double-click at coordinates
  - rdp_right_click: Right-click at coordinates
  - rdp_type: Type text on the Windows desktop
  - rdp_key: Send key events (Enter, Escape, Ctrl+S, etc.)
  - rdp_scroll: Scroll at coordinates
  - rdp_disconnect: Close the RDP session
  - rdp_list_recordings: List available session recordings
  - rdp_download_recording: Download a session recording

The server communicates via JSON-RPC over stdin/stdout (MCP stdio transport).
"""

import json
import os
import signal
import subprocess
import sys
import time
import base64
import shutil
from pathlib import Path

# ── State ────────────────────────────────────────────────────────────────

class RdpSession:
    def __init__(self):
        self.xvfb_proc = None
        self.xfreerdp_proc = None
        self.display = ":99"
        self.width = 1920
        self.height = 1080
        self.boundary_proc = None
        self.proxy_host = None
        self.proxy_port = None
        self.session_id = None
        self.screenshot_dir = "/tmp/rdp-screenshots"
        self.connected = False

    def cleanup(self):
        """Kill all subprocesses."""
        if self.xfreerdp_proc:
            try:
                self.xfreerdp_proc.kill()
                self.xfreerdp_proc.wait(timeout=5)
            except Exception:
                pass
        if self.xvfb_proc:
            try:
                self.xvfb_proc.kill()
                self.xvfb_proc.wait(timeout=5)
            except Exception:
                pass
        if self.boundary_proc:
            try:
                self.boundary_proc.kill()
                self.boundary_proc.wait(timeout=5)
            except Exception:
                pass
        self.connected = False


session = RdpSession()
os.makedirs(session.screenshot_dir, exist_ok=True)


# ── MCP Protocol ─────────────────────────────────────────────────────────

def send_json(obj):
    """Send a JSON-RPC response/notification to stdout."""
    data = json.dumps(obj)
    sys.stdout.write(data + "\n")
    sys.stdout.flush()


def read_messages():
    """Read JSON-RPC messages from stdin (line-delimited)."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            send_json({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None})


# ── Tool Implementations ────────────────────────────────────────────────

def install_dependencies():
    """Install required system packages if not present."""
    packages = ["xvfb", "freerdp3-x11", "xdotool", "scrot", "imagemagick"]
    missing = []
    for pkg in packages:
        # Check if the binary exists
        binary_map = {
            "xvfb": "Xvfb",
            "freerdp3-x11": "xfreerdp3",
            "xdotool": "xdotool",
            "scrot": "scrot",
            "imagemagick": "import",
        }
        binary = binary_map.get(pkg, pkg)
        if not shutil.which(binary):
            missing.append(pkg)
    if missing:
        subprocess.run(["apt-get", "update", "-qq"], check=False, timeout=60)
        subprocess.run(["apt-get", "install", "-y", "-qq"] + missing, check=False, timeout=120)
    return len(missing) > 0


def tool_connect_rdp(params):
    """Start an RDP session through Boundary proxy."""
    global session

    target_id = params.get("target_id", "")
    username = params.get("username", "Administrator")
    password = params.get("password", "")
    boundary_addr = params.get("boundary_addr", os.environ.get("BOUNDARY_ADDR", "http://127.0.0.1:9220"))
    boundary_token = params.get("boundary_token", os.environ.get("BOUNDARY_TOKEN", ""))
    width = params.get("width", 1280)
    height = params.get("height", 720)
    domain = params.get("domain", "")

    if not target_id:
        return {"error": "target_id is required"}
    if not password:
        return {"error": "password is required"}
    if not boundary_token:
        return {"error": "boundary_token is required (set BOUNDARY_TOKEN env var or pass as parameter)"}

    # Install dependencies if needed
    install_dependencies()

    # Clean up any existing session
    session.cleanup()

    # Update dimensions
    session.width = width
    session.height = height

    # Step 1: Start Xvfb (virtual framebuffer)
    session.xvfb_proc = subprocess.Popen(
        ["Xvfb", session.display, "-screen", f"0", f"{width}x{height}x24"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)  # Wait for Xvfb to start

    # Verify Xvfb is running
    if session.xvfb_proc.poll() is not None:
        return {"error": "Failed to start Xvfb virtual framebuffer"}

    # Step 2: Start boundary connect to get a local proxy port
    # We use boundary connect (TCP) with -exec to capture the proxy port
    # The proxy gives us BOUNDARY_PROXIED_IP and BOUNDARY_PROXIED_PORT
    # We write a small script that prints these and exits, then parse the output

    proxy_script = """#!/bin/bash
echo "PROXY_IP=$BOUNDARY_PROXIED_IP"
echo "PROXY_PORT=$BOUNDARY_PROXIED_PORT"
# Keep the connection alive
sleep 999999
"""
    proxy_script_path = "/tmp/rdp-proxy-wrapper.sh"
    with open(proxy_script_path, "w") as f:
        f.write(proxy_script)
    os.chmod(proxy_script_path, 0o755)

    env = os.environ.copy()
    env["BOUNDARY_ADDR"] = boundary_addr
    env["BOUNDARY_KEYRING_TYPE"] = "none"
    env["BOUNDARY_TOKEN"] = boundary_token

    # Start boundary connect in background - it will start a proxy and run our wrapper
    # The wrapper prints the proxy IP/port and keeps the connection alive
    session.boundary_proc = subprocess.Popen(
        ["boundary", "connect",
         "-target-id", target_id,
         "-keyring-type", "none",
         "-token", "env://BOUNDARY_TOKEN",
         "-exec", proxy_script_path, "--"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    # Wait for the proxy port to appear
    proxy_info = {}
    for _ in range(30):
        line = session.boundary_proc.stdout.readline().decode("utf-8", errors="replace").strip()
        if "PROXY_IP=" in line:
            proxy_info["ip"] = line.split("=", 1)[1]
        elif "PROXY_PORT=" in line:
            proxy_info["port"] = line.split("=", 1)[1]
        if "ip" in proxy_info and "port" in proxy_info:
            break
        time.sleep(0.5)

    if "port" not in proxy_info:
        stderr_data = session.boundary_proc.stderr.read().decode("utf-8", errors="replace")
        session.cleanup()
        return {"error": f"Failed to get proxy port from boundary connect. stderr: {stderr_data[:500]}"}

    session.proxy_host = proxy_info.get("ip", "127.0.0.1")
    session.proxy_port = proxy_info["port"]

    # Step 3: Start xfreerdp3 connected to the Boundary proxy
    # Note: password is passed as a single argument with /p: prefix.
    # FreeRDP3 parses / as flag prefix, so special chars in password (?, *, !)
    # are safe as long as the whole /p:value is one shell argument.
    rdp_args = [
        "xfreerdp3",
        f"/v:{session.proxy_host}:{session.proxy_port}",
        f"/u:{username}",
        f"/p:{password}",
        f"/size:{width}x{height}",
        "/bpp:24",
        "/cert:ignore",
        "-clipboard",
        "-decorations",
        "/smart-sizing",
        f"/monitors:0",
        f"/wm:{width}x{height}",
        "-wallpaper",
        "-themes",
        "-fonts",
        "-aero",
        "/gdi:hw",
        "/codec:jpeg",
        "/jpeg-quality:75",
    ]

    if domain:
        rdp_args.append(f"/d:{domain}")

    rdp_env = os.environ.copy()
    rdp_env["DISPLAY"] = session.display

    session.xfreerdp_proc = subprocess.Popen(
        rdp_args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=rdp_env,
    )

    # Wait for RDP to connect
    time.sleep(5)

    if session.xfreerdp_proc.poll() is not None:
        stderr_data = session.xfreerdp_proc.stderr.read().decode("utf-8", errors="replace")
        session.cleanup()
        return {"error": f"xfreerdp3 failed to start. stderr: {stderr_data[:500]}"}

    session.connected = True

    # Take an initial screenshot to verify
    screenshot_path = os.path.join(session.screenshot_dir, "initial.png")
    take_screenshot(screenshot_path)

    return {
        "status": "connected",
        "proxy": f"{session.proxy_host}:{session.proxy_port}",
        "display": session.display,
        "resolution": f"{width}x{height}",
        "username": username,
        "initial_screenshot": screenshot_path,
        "message": "RDP session established. Use rdp_screenshot to capture the desktop."
    }


def take_screenshot(path=None):
    """Capture a screenshot from the Xvfb display."""
    if not path:
        path = os.path.join(session.screenshot_dir, f"screenshot_{int(time.time())}.png")

    env = os.environ.copy()
    env["DISPLAY"] = session.display

    # Use import (ImageMagick) for screenshot capture
    result = subprocess.run(
        ["import", "-window", "root", path],
        capture_output=True,
        env=env,
        timeout=10,
    )

    if result.returncode != 0 or not os.path.exists(path):
        # Fallback to scrot
        result = subprocess.run(
            ["scrot", path],
            capture_output=True,
            env=env,
            timeout=10,
        )

    if os.path.exists(path):
        return path
    return None


def tool_rdp_screenshot(params):
    """Capture a screenshot of the Windows desktop."""
    if not session.connected:
        return {"error": "Not connected. Call connect_rdp first."}

    path = params.get("path")
    screenshot_path = take_screenshot(path)

    if not screenshot_path:
        return {"error": "Failed to capture screenshot"}

    # Read the screenshot and return as base64
    with open(screenshot_path, "rb") as f:
        img_data = base64.b64encode(f.read()).decode("utf-8")

    return {
        "screenshot_path": screenshot_path,
        "screenshot_base64": img_data,
        "width": session.width,
        "height": session.height,
        "message": "Screenshot captured. The image is in screenshot_base64 (PNG format)."
    }


def tool_rdp_click(params):
    """Click at coordinates on the Windows desktop."""
    if not session.connected:
        return {"error": "Not connected. Call connect_rdp first."}

    x = params.get("x")
    y = params.get("y")
    button = params.get("button", "left")  # left, right, middle

    if x is None or y is None:
        return {"error": "x and y coordinates are required"}

    env = os.environ.copy()
    env["DISPLAY"] = session.display

    button_map = {"left": 1, "middle": 2, "right": 3}
    btn_num = button_map.get(button, 1)

    # Move mouse to position and click
    subprocess.run(
        ["xdotool", "mousemove", str(x), str(y), "click", str(btn_num)],
        capture_output=True,
        env=env,
        timeout=5,
    )

    time.sleep(0.5)  # Wait for UI to respond

    return {"status": "clicked", "x": x, "y": y, "button": button}


def tool_rdp_double_click(params):
    """Double-click at coordinates."""
    if not session.connected:
        return {"error": "Not connected. Call connect_rdp first."}

    x = params.get("x")
    y = params.get("y")

    if x is None or y is None:
        return {"error": "x and y coordinates are required"}

    env = os.environ.copy()
    env["DISPLAY"] = session.display

    subprocess.run(
        ["xdotool", "mousemove", str(x), str(y), "click", "--repeat", "2", "1"],
        capture_output=True,
        env=env,
        timeout=5,
    )

    time.sleep(0.5)

    return {"status": "double_clicked", "x": x, "y": y}


def tool_rdp_right_click(params):
    """Right-click at coordinates."""
    if not session.connected:
        return {"error": "Not connected. Call connect_rdp first."}

    x = params.get("x")
    y = params.get("y")

    if x is None or y is None:
        return {"error": "x and y coordinates are required"}

    env = os.environ.copy()
    env["DISPLAY"] = session.display

    subprocess.run(
        ["xdotool", "mousemove", str(x), str(y), "click", "3"],
        capture_output=True,
        env=env,
        timeout=5,
    )

    time.sleep(0.5)

    return {"status": "right_clicked", "x": x, "y": y}


def tool_rdp_type(params):
    """Type text on the Windows desktop."""
    if not session.connected:
        return {"error": "Not connected. Call connect_rdp first."}

    text = params.get("text", "")
    if not text:
        return {"error": "text is required"}

    env = os.environ.copy()
    env["DISPLAY"] = session.display

    # Use xdotool to type the text
    subprocess.run(
        ["xdotool", "type", "--clearmodifiers", "--delay", "50", text],
        capture_output=True,
        env=env,
        timeout=max(10, len(text) // 5),
    )

    time.sleep(0.3)

    return {"status": "typed", "text_length": len(text)}


def tool_rdp_key(params):
    """Send key events (Enter, Escape, Ctrl+S, etc.)."""
    if not session.connected:
        return {"error": "Not connected. Call connect_rdp first."}

    keys = params.get("keys", "")
    if not keys:
        return {"error": "keys is required"}

    env = os.environ.copy()
    env["DISPLAY"] = session.display

    # xdotool key syntax: "Return", "Escape", "ctrl+s", "alt+Tab", etc.
    subprocess.run(
        ["xdotool", "key", "--clearmodifiers", keys],
        capture_output=True,
        env=env,
        timeout=5,
    )

    time.sleep(0.3)

    return {"status": "key_sent", "keys": keys}


def tool_rdp_scroll(params):
    """Scroll at coordinates."""
    if not session.connected:
        return {"error": "Not connected. Call connect_rdp first."}

    x = params.get("x", session.width // 2)
    y = params.get("y", session.height // 2)
    direction = params.get("direction", "down")  # up or down
    clicks = params.get("clicks", 3)

    env = os.environ.copy()
    env["DISPLAY"] = session.display

    button = 4 if direction == "up" else 5

    # Move to position and scroll
    args = ["xdotool", "mousemove", str(x), str(y)]
    for _ in range(clicks):
        args.extend(["click", str(button)])
    subprocess.run(args, capture_output=True, env=env, timeout=10)

    time.sleep(0.3)

    return {"status": "scrolled", "direction": direction, "clicks": clicks, "x": x, "y": y}


def tool_rdp_disconnect(params):
    """Close the RDP session."""
    global session
    session.cleanup()

    return {"status": "disconnected", "message": "RDP session closed. All processes terminated."}


def tool_rdp_list_recordings(params):
    """List available session recordings from Boundary."""
    boundary_addr = params.get("boundary_addr", os.environ.get("BOUNDARY_ADDR", "http://127.0.0.1:9220"))
    boundary_token = params.get("boundary_token", os.environ.get("BOUNDARY_TOKEN", ""))
    scope_id = params.get("scope_id", "")

    if not boundary_token:
        return {"error": "boundary_token is required"}

    env = os.environ.copy()
    env["BOUNDARY_ADDR"] = boundary_addr
    env["BOUNDARY_KEYRING_TYPE"] = "none"
    env["BOUNDARY_TOKEN"] = boundary_token

    cmd = ["boundary", "session-recordings", "list", "-token", "env://BOUNDARY_TOKEN", "-format", "json"]
    if scope_id:
        cmd.extend(["-scope-id", scope_id])

    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)

    if result.returncode != 0:
        return {"error": result.stderr[:500]}

    try:
        data = json.loads(result.stdout)
        recordings = data.get("items", [])
        return {
            "recordings": [
                {
                    "id": r.get("id", ""),
                    "session_id": r.get("session_id", ""),
                    "state": r.get("state", ""),
                    "type": r.get("type", ""),
                    "start_time": r.get("start_time", ""),
                    "end_time": r.get("end_time", ""),
                    "duration": str(r.get("duration", "")),
                    "mime_types": r.get("mime_types", []),
                }
                for r in recordings
            ],
            "count": len(recordings),
        }
    except json.JSONDecodeError:
        return {"error": "Failed to parse recordings response"}


def tool_rdp_download_recording(params):
    """Download a session recording from Boundary."""
    recording_id = params.get("recording_id", "")
    output_path = params.get("output_path", f"/tmp/recording_{recording_id}.tar")

    if not recording_id:
        return {"error": "recording_id is required"}

    boundary_addr = params.get("boundary_addr", os.environ.get("BOUNDARY_ADDR", "http://127.0.0.1:9220"))
    boundary_token = params.get("boundary_token", os.environ.get("BOUNDARY_TOKEN", ""))

    if not boundary_token:
        return {"error": "boundary_token is required"}

    env = os.environ.copy()
    env["BOUNDARY_ADDR"] = boundary_addr
    env["BOUNDARY_KEYRING_TYPE"] = "none"
    env["BOUNDARY_TOKEN"] = boundary_token

    # Use the Boundary API to download the recording
    result = subprocess.run(
        ["boundary", "session-recordings", "download",
         "-id", recording_id,
         "-output", output_path,
         "-token", "env://BOUNDARY_TOKEN"],
        capture_output=True, text=True, env=env, timeout=120,
    )

    if result.returncode != 0:
        return {"error": result.stderr[:500]}

    return {
        "status": "downloaded",
        "recording_id": recording_id,
        "output_path": output_path,
        "size_bytes": os.path.getsize(output_path) if os.path.exists(output_path) else 0,
    }


# ── Tool Registry ────────────────────────────────────────────────────────

TOOLS = {
    "connect_rdp": {
        "description": "Connect to a Windows host via RDP through a Boundary proxy. Starts a virtual framebuffer (Xvfb), connects xfreerdp3 to the Boundary proxy, and enables screenshot + input tools. Returns connection status and an initial screenshot.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "description": "The Boundary target ID for the RDP target (TCP target on port 3389)."},
                "username": {"type": "string", "description": "Windows username (e.g. Administrator).", "default": "Administrator"},
                "password": {"type": "string", "description": "Windows password (from brokered credentials)."},
                "boundary_addr": {"type": "string", "description": "Boundary API address.", "default": "http://127.0.0.1:9220"},
                "boundary_token": {"type": "string", "description": "Boundary auth token. If not set, uses BOUNDARY_TOKEN env var."},
                "width": {"type": "integer", "description": "Screen width in pixels.", "default": 1280},
                "height": {"type": "integer", "description": "Screen height in pixels.", "default": 720},
                "domain": {"type": "string", "description": "Windows domain (optional)."},
            },
            "required": ["target_id", "password"],
        },
        "handler": tool_connect_rdp,
    },
    "rdp_screenshot": {
        "description": "Capture a screenshot of the Windows desktop. Returns the screenshot as base64-encoded PNG data. Use this to see what's on screen and determine where to click.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Optional custom path to save the screenshot."},
            },
        },
        "handler": tool_rdp_screenshot,
    },
    "rdp_click": {
        "description": "Click at the specified coordinates on the Windows desktop. Use rdp_screenshot first to identify the correct coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate (pixels from left)."},
                "y": {"type": "integer", "description": "Y coordinate (pixels from top)."},
                "button": {"type": "string", "description": "Mouse button: left, right, or middle.", "default": "left"},
            },
            "required": ["x", "y"],
        },
        "handler": tool_rdp_click,
    },
    "rdp_double_click": {
        "description": "Double-click at the specified coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate."},
                "y": {"type": "integer", "description": "Y coordinate."},
            },
            "required": ["x", "y"],
        },
        "handler": tool_rdp_double_click,
    },
    "rdp_right_click": {
        "description": "Right-click at the specified coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate."},
                "y": {"type": "integer", "description": "Y coordinate."},
            },
            "required": ["x", "y"],
        },
        "handler": tool_rdp_right_click,
    },
    "rdp_type": {
        "description": "Type text on the Windows desktop. Click on a text field first, then use this tool to type into it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type."},
            },
            "required": ["text"],
        },
        "handler": tool_rdp_type,
    },
    "rdp_key": {
        "description": "Send key events to the Windows desktop. Use xdotool key syntax: 'Return', 'Escape', 'ctrl+s', 'alt+Tab', 'win', etc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keys": {"type": "string", "description": "Key combination in xdotool syntax (e.g. 'Return', 'ctrl+s', 'alt+F4')."},
            },
            "required": ["keys"],
        },
        "handler": tool_rdp_key,
    },
    "rdp_scroll": {
        "description": "Scroll at the specified coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate.", "default": 640},
                "y": {"type": "integer", "description": "Y coordinate.", "default": 360},
                "direction": {"type": "string", "description": "Scroll direction: up or down.", "default": "down"},
                "clicks": {"type": "integer", "description": "Number of scroll clicks.", "default": 3},
            },
        },
        "handler": tool_rdp_scroll,
    },
    "rdp_disconnect": {
        "description": "Close the RDP session and terminate all related processes (Xvfb, xfreerdp3, boundary proxy).",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_rdp_disconnect,
    },
    "rdp_list_recordings": {
        "description": "List available session recordings from Boundary. Shows recording ID, session ID, state, timing, and MIME types.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope_id": {"type": "string", "description": "Optional scope ID to filter recordings."},
                "boundary_addr": {"type": "string", "description": "Boundary API address."},
                "boundary_token": {"type": "string", "description": "Boundary auth token."},
            },
        },
        "handler": tool_rdp_list_recordings,
    },
    "rdp_download_recording": {
        "description": "Download a session recording from Boundary. The recording is saved as a TAR file containing the session data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "recording_id": {"type": "string", "description": "The recording ID to download."},
                "output_path": {"type": "string", "description": "Path to save the recording file."},
                "boundary_addr": {"type": "string", "description": "Boundary API address."},
                "boundary_token": {"type": "string", "description": "Boundary auth token."},
            },
            "required": ["recording_id"],
        },
        "handler": tool_rdp_download_recording,
    },
}


# ── MCP Server Loop ─────────────────────────────────────────────────────

def handle_request(msg):
    """Handle a single JSON-RPC request."""
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "rdp-computer-use", "version": "1.0.0"},
            },
        }

    elif method == "tools/list":
        tool_list = []
        for name, tool in TOOLS.items():
            tool_list.append({
                "name": name,
                "description": tool["description"],
                "inputSchema": tool["inputSchema"],
            })
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tool_list}}

    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        if tool_name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }

        try:
            result = TOOLS[tool_name]["handler"](tool_args)
            result_text = json.dumps(result, indent=2)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": result_text}],
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32603, "message": f"Tool execution error: {str(e)}"},
            }

    elif method == "notifications/initialized":
        return None  # No response for notifications

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    else:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        }


def main():
    # Handle cleanup on exit
    def signal_handler(sig, frame):
        session.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    for msg in read_messages():
        response = handle_request(msg)
        if response is not None:
            send_json(response)

    # Cleanup on stdin close
    session.cleanup()


if __name__ == "__main__":
    main()
