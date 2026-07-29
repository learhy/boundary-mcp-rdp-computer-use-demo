#!/usr/bin/env bash
# demo.sh — Boundary MCP RDP Computer Use Demo
#
# Usage:
#   ./demo.sh --setup           # Provision everything, generate .mcp.json, print agent command
#   ./demo.sh --teardown         # Destroy all provisioned resources
#   ./demo.sh --run              # Run the agent with the generated .mcp.json
#   ./demo.sh --export <sr_id>   # Export a session recording as WebM video
#
# Prerequisites:
#   - boundary CLI, terraform, go, python3, docker
#   - System packages: xvfb freerdp3-x11 xdotool imagemagick
#   - A Windows host with RDP (port 3389) accessible from this machine
#
# Configuration:
#   All inputs live in demo.tfvars (created from demo.tfvars.example by --setup).
#   You can also pass --tfvars <path> to use a different file.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TFVARS="${TFVARS:-$SCRIPT_DIR/demo.tfvars}"
BOUNDARY_MCP_DIR="${BOUNDARY_MCP_DIR:-$HOME/software/boundary-mcp}"
ACTION=""

# ── Colors ──────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

# ── Argument parsing ────────────────────────────────────────────────────
EXPORT_SR_ID=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --setup)   ACTION="setup"; shift ;;
        --teardown) ACTION="teardown"; shift ;;
        --run)     ACTION="run"; shift ;;
        --export)  ACTION="export"; EXPORT_SR_ID="$2"; shift 2 ;;
        --tfvars)  TFVARS="$2"; shift 2 ;;
        -h|--help)
            cat << 'USAGE'
demo.sh — Boundary MCP RDP Computer Use Demo

  --setup            Provision HCP Boundary cluster + resources, build boundary-mcp,
                     generate .mcp.json, print the agent run command.
  --teardown         Destroy all Terraform-provisioned resources (cluster + resources).
  --run              Launch the agent using the generated .mcp.json.
  --export <sr_id>   Export a session recording as WebM (downloads from MinIO).
  --tfvars <path>    Use a specific tfvars file (default: demo.tfvars in repo root).
  -h, --help          Show this help.

Configuration file (demo.tfvars):
  HCP_SP_CLIENT_ID       — HCP service principal client ID
  HCP_SP_CLIENT_SECRET   — HCP service principal client secret
  WINDOWS_HOST_IP        — Windows host IP or hostname (RDP target)
  WINDOWS_USERNAME       — Windows RDP username (default: Administrator)
  WINDOWS_PASSWORD       — Windows RDP password
  MINIO_ENDPOINT         — MinIO S3 endpoint URL (must be reachable from worker)
  MINIO_ACCESS_KEY       — MinIO access key (default: minioadmin)
  MINIO_SECRET_KEY       — MinIO secret key (default: minioadmin123)
  BOUNDARY_ADMIN_PASSWORD — Admin password for the Boundary cluster (default: AdminPass123!)
USAGE
            exit 0 ;;
        *) fail "Unknown argument: $1 (use -h for help)" ;;
    esac
done

[[ -z "$ACTION" ]] && fail "No action specified. Use --setup, --teardown, --run, or --export. (-h for help)"

# ── Dependency checks ───────────────────────────────────────────────────
check_deps() {
    local missing=()
    for cmd in boundary terraform go python3; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        fail "Missing required commands: ${missing[*]}\nInstall: boundary CLI, terraform, go, python3"
    fi
    # Check system packages for RDP
    for pkg in xfreerdp3 xdotool import Xvfb; do
        command -v "$pkg" >/dev/null 2>&1 || warn "$pkg not found — run: sudo apt install xvfb freerdp3-x11 xdotool imagemagick"
    done
}

# ── tfvars loader ───────────────────────────────────────────────────────
# demo.tfvars is a flat key=value file (not HCL terraform.tfvars).
# It feeds both Terraform stages and the .mcp.json generation.
load_tfvars() {
    if [[ ! -f "$TFVARS" ]]; then
        return 1
    fi
    # Source as shell variables (safe — key=value format)
    set -a
    # shellcheck disable=SC1090
    source "$TFVARS"
    set +a
    # Defaults
    export WINDOWS_USERNAME="${WINDOWS_USERNAME:-Administrator}"
    export MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-minioadmin}"
    export MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minioadmin123}"
    export MINIO_BUCKET_NAME="${MINIO_BUCKET_NAME:-boundary-session-recordings}"
    export BOUNDARY_ADMIN_PASSWORD="${BOUNDARY_ADMIN_PASSWORD:-AdminPass123!}"
    export BOUNDARY_ADMIN_USERNAME="${BOUNDARY_ADMIN_USERNAME:-admin}"
    export BOUNDARY_CLUSTER_ID="${BOUNDARY_CLUSTER_ID:-rdp-demo-cluster}"
    export ENABLE_RECORDING="${ENABLE_RECORDING:-true}"
    export BOUNDARY_LICENSE="${BOUNDARY_LICENSE:-}"
}

# ── Write Terraform tfvars from demo.tfvars ───────────────────────────────
write_tf_tfvars() {
    local stage="$1"  # 01-cluster or 02-resources
    local tfvars_dir="$SCRIPT_DIR/terraform/$stage"
    local tfvars_file="$tfvars_dir/terraform.tfvars"

    if [[ "$stage" == "01-cluster" ]]; then
        cat > "$tfvars_file" << TFEOF
hcp_client_id          = "$HCP_SP_CLIENT_ID"
hcp_client_secret      = "$HCP_SP_CLIENT_SECRET"
boundary_cluster_id    = "$BOUNDARY_CLUSTER_ID"
boundary_admin_username = "$BOUNDARY_ADMIN_USERNAME"
boundary_admin_password = "$BOUNDARY_ADMIN_PASSWORD"
TFEOF
    elif [[ "$stage" == "02-resources" ]]; then
        cat > "$tfvars_file" << TFEOF
boundary_addr           = "$CLUSTER_URL"
boundary_admin_username = "$BOUNDARY_ADMIN_USERNAME"
boundary_admin_password = "$BOUNDARY_ADMIN_PASSWORD"
windows_host_ip         = "$WINDOWS_HOST_IP"
windows_username        = "$WINDOWS_USERNAME"
windows_password        = "$WINDOWS_PASSWORD"
minio_endpoint          = "$MINIO_ENDPOINT"
minio_access_key        = "$MINIO_ACCESS_KEY"
minio_secret_key        = "$MINIO_SECRET_KEY"
minio_bucket_name       = "$MINIO_BUCKET_NAME"
enable_recording        = $ENABLE_RECORDING
TFEOF
    fi
    echo "$tfvars_file"
}

# ── Worker setup ───────────────────────────────────────────────────────────
setup_worker() {
    local token="$1"
    local cluster_url="$2"

    # Extract cluster ID from URL (e.g. ae0b2e8e-... from https://ae0b2e8e-...boundary.hashicorp.cloud)
    local cluster_id
    cluster_id=$(echo "$cluster_url" | sed 's|https://\([^-]*\)-.*|\1|')
    info "HCP cluster ID: $cluster_id"

    # Get the server's public IP for the worker's public_addr
    local public_ip
    public_ip=$(curl -s4 ifconfig.me 2>/dev/null || echo "127.0.0.1")
    info "Server public IP: $public_ip"

    # Create a controller-led worker to get the activation token
    info "Creating controller-led worker..."
    export BOUNDARY_ADDR="$cluster_url"
    export BOUNDARY_TOKEN="$token"
    local worker_json
    worker_json=$(boundary workers create controller-led \
        -name "rdp-demo-worker" \
        -description "Self-managed worker for RDP demo with recording storage" \
        -format json 2>/dev/null) || fail "Failed to create worker"

    local activation_token worker_id
    activation_token=$(echo "$worker_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['item']['controller_generated_activation_token'])")
    worker_id=$(echo "$worker_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['item']['id'])")
    ok "Worker created: $worker_id"

    # Write the worker config file
    local worker_port=9422
    mkdir -p /tmp/boundary-recordings /tmp/boundary-worker-auth

    cat > "$SCRIPT_DIR/worker.hcl" << WORKEREOF
disable_mlock = true

hcp_boundary_cluster_id = "$cluster_id"

listener "tcp" {
  address = "0.0.0.0:$worker_port"
  purpose = "proxy"
}

worker {
  public_addr = "$public_ip:$worker_port"
  auth_storage_path = "/tmp/boundary-worker-auth"
  recording_storage_path = "/tmp/boundary-recordings"
  controller_generated_activation_token = "$activation_token"
  tags {
    type = ["worker", "worker-session-recording"]
  }
}
WORKEREOF

    # Kill any existing worker process
    pkill -f "boundary server -config=$SCRIPT_DIR/worker.hcl" 2>/dev/null || true
    sleep 1

    # Start the worker as a background process
    info "Starting worker process..."
    export BOUNDARY_LICENSE="${BOUNDARY_LICENSE:-}"
    if [[ -z "$BOUNDARY_LICENSE" ]]; then
        warn "BOUNDARY_LICENSE not set — worker may fail to start without enterprise license"
    fi

    nohup boundary server -config="$SCRIPT_DIR/worker.hcl" > /tmp/boundary-worker.log 2>&1 &
    local worker_pid=$!
    echo "$worker_pid" > "$SCRIPT_DIR/.worker-pid"

    # Wait for the worker to connect
    info "Waiting for worker to connect to HCP..."
    local connected=false
    for i in $(seq 1 15); do
        sleep 2
        if grep -q "upstream connection is ready\|worker has successfully authenticated" /tmp/boundary-worker.log 2>/dev/null; then
            connected=true
            break
        fi
        printf "  %d...\n" "$i"
    done

    if $connected; then
        ok "Worker connected to HCP Boundary cluster"
    else
        warn "Worker may not have connected. Check /tmp/boundary-worker.log"
        warn "Last log lines:"
        tail -5 /tmp/boundary-worker.log 2>/dev/null || true
    fi

    # Add worker.hcl and .worker-pid to .gitignore
    grep -q "worker.hcl" "$SCRIPT_DIR/.gitignore" 2>/dev/null || echo "worker.hcl" >> "$SCRIPT_DIR/.gitignore"
    grep -q ".worker-pid" "$SCRIPT_DIR/.gitignore" 2>/dev/null || echo ".worker-pid" >> "$SCRIPT_DIR/.gitignore"
}

# ── Setup ─────────────────────────────────────────────────────────────────
do_setup() {
    info "Checking dependencies..."
    check_deps

    # If demo.tfvars doesn't exist, create from example and tell user to fill it in
    if [[ ! -f "$TFVARS" ]]; then
        if [[ -f "$SCRIPT_DIR/demo.tfvars.example" ]]; then
            cp "$SCRIPT_DIR/demo.tfvars.example" "$TFVARS"
            warn "Created $TFVARS from example. Edit it with your values, then re-run --setup."
            echo ""
            cat "$TFVARS"
            exit 0
        else
            fail "No $TFVARS found and no example file. Create one with the required variables."
        fi
    fi

    info "Loading config from $TFVARS"
    load_tfvars

    # Validate required fields
    local required=("HCP_SP_CLIENT_ID" "HCP_SP_CLIENT_SECRET" "WINDOWS_HOST_IP" "WINDOWS_PASSWORD" "MINIO_ENDPOINT")
    for var in "${required[@]}"; do
        if [[ -z "${!var:-}" ]]; then
            fail "Missing required variable in $TFVARS: $var"
        fi
    done

    # Step 1: Build boundary-mcp binary
    info "Building boundary-mcp binary..."
    if [[ ! -d "$BOUNDARY_MCP_DIR" ]]; then
        fail "boundary-mcp repo not found at $BOUNDARY_MCP_DIR\nClone it: git clone https://github.com/learhy/boundary-mcp.git $BOUNDARY_MCP_DIR"
    fi
    (cd "$BOUNDARY_MCP_DIR" && go build -o boundary-mcp ./cmd/boundary-mcp/)
    ok "boundary-mcp built at $BOUNDARY_MCP_DIR/boundary-mcp"

    # Step 2: Terraform — create HCP Boundary cluster
    info "Terraform: creating HCP Boundary cluster..."
    local tfvars_file
    tfvars_file=$(write_tf_tfvars "01-cluster")
    (cd "$SCRIPT_DIR/terraform/01-cluster" && terraform init -input=false && terraform apply -auto-approve)

    CLUSTER_URL=$(cd "$SCRIPT_DIR/terraform/01-cluster" && terraform output -raw boundary_cluster_url)
    ok "HCP Boundary cluster created: $CLUSTER_URL"
    export CLUSTER_URL

    # Step 3: Terraform — provision Boundary resources
    info "Terraform: provisioning Boundary resources..."
    tfvars_file=$(write_tf_tfvars "02-resources")

    # First apply without the storage bucket (enable_recording=false initially)
    # because the self-managed worker hasn't been created yet
    sed -i 's/enable_recording\s*=.*/enable_recording = false/' "$tfvars_file"
    (cd "$SCRIPT_DIR/terraform/02-resources" && terraform init -input=false && terraform apply -auto-approve)

    local target_id org_id project_id
    target_id=$(cd "$SCRIPT_DIR/terraform/02-resources" && terraform output -raw target_id)
    org_id=$(cd "$SCRIPT_DIR/terraform/02-resources" && terraform output -raw org_id)
    project_id=$(cd "$SCRIPT_DIR/terraform/02-resources" && terraform output -raw project_id)
    ok "Resources created — target: $target_id, org: $org_id, project: $project_id"

    # Step 3b: Start self-managed worker (required for session recording)
    if [[ "$ENABLE_RECORDING" == "true" ]]; then
        info "Setting up self-managed worker for session recording..."
        setup_worker "$TOKEN" "$CLUSTER_URL"

        # Re-apply Terraform with recording enabled now that the worker is online
        info "Re-applying Terraform with session recording enabled..."
        write_tf_tfvars "02-resources" >/dev/null  # rewrite with enable_recording=true
        (cd "$SCRIPT_DIR/terraform/02-resources" && terraform apply -auto-approve)
        ok "Session recording enabled on target"
    fi

    # Step 4: Authenticate and get token
    info "Authenticating to Boundary..."
    export BOUNDARY_ADDR="$CLUSTER_URL"
    export BOUNDARY_PASSWORD="$BOUNDARY_ADMIN_PASSWORD"
    TOKEN=$(boundary authenticate password \
        -login-name "$BOUNDARY_ADMIN_USERNAME" \
        -password env://BOUNDARY_PASSWORD \
        -format json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['item']['attributes']['token'])")
    ok "Got auth token: ${TOKEN:0:20}..."

    # Step 5: Generate .mcp.json
    info "Generating .mcp.json..."
    cat > "$SCRIPT_DIR/.mcp.json" << MCPJSON
{
  "mcpServers": {
    "boundary": {
      "command": "$BOUNDARY_MCP_DIR/boundary-mcp",
      "env": {
        "BOUNDARY_ADDR": "$CLUSTER_URL",
        "BOUNDARY_TOKEN": "$TOKEN",
        "BOUNDARY_TLS_INSECURE": "true"
      }
    },
    "rdp-computer-use": {
      "command": "python3",
      "args": ["$SCRIPT_DIR/rdp-mcp-server/server.py"],
      "env": {
        "BOUNDARY_ADDR": "$CLUSTER_URL",
        "BOUNDARY_TOKEN": "$TOKEN",
        "MINIO_ENDPOINT": "$MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY": "$MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY": "$MINIO_SECRET_KEY",
        "MINIO_BUCKET": "$MINIO_BUCKET_NAME"
      }
    }
  }
}
MCPJSON
    ok ".mcp.json generated with correct paths and token"

    # Save state for teardown/export
    echo "CLUSTER_URL=$CLUSTER_URL" > "$SCRIPT_DIR/.demo-state"
    echo "TARGET_ID=$target_id" >> "$SCRIPT_DIR/.demo-state"
    echo "ORG_ID=$org_id" >> "$SCRIPT_DIR/.demo-state"
    echo "PROJECT_ID=$project_id" >> "$SCRIPT_DIR/.demo-state"
    echo "MINIO_ENDPOINT=$MINIO_ENDPOINT" >> "$SCRIPT_DIR/.demo-state"
    echo "MINIO_ACCESS_KEY=$MINIO_ACCESS_KEY" >> "$SCRIPT_DIR/.demo-state"
    echo "MINIO_SECRET_KEY=$MINIO_SECRET_KEY" >> "$SCRIPT_DIR/.demo-state"
    echo "MINIO_BUCKET_NAME=$MINIO_BUCKET_NAME" >> "$SCRIPT_DIR/.demo-state"
    echo "BOUNDARY_MCP_DIR=$BOUNDARY_MCP_DIR" >> "$SCRIPT_DIR/.demo-state"
    echo "BOUNDARY_ADMIN_USERNAME=$BOUNDARY_ADMIN_USERNAME" >> "$SCRIPT_DIR/.demo-state"
    echo "BOUNDARY_ADMIN_PASSWORD=$BOUNDARY_ADMIN_PASSWORD" >> "$SCRIPT_DIR/.demo-state"

    # Add .demo-state to .gitignore if not already there
    grep -q "\.demo-state" "$SCRIPT_DIR/.gitignore" 2>/dev/null || echo ".demo-state" >> "$SCRIPT_DIR/.gitignore"

    echo ""
    ok "=== Setup complete! ==="
    echo ""
    echo "  Boundary cluster:  $CLUSTER_URL"
    echo "  Target ID:          $target_id"
    echo "  MCP config:         $SCRIPT_DIR/.mcp.json"
    echo ""
    echo "  Run the agent with:"
    echo "    ./demo.sh --run"
    echo "    # or directly:"
    echo "    ibm-bob --config $SCRIPT_DIR/.mcp.json -p \"\$(cat $SCRIPT_DIR/CLAUDE.md)\""
    echo ""
    echo "  Export a recording:"
    echo "    ./demo.sh --export <sr_ID>"
}

# ── Teardown ───────────────────────────────────────────────────────────────
do_teardown() {
    # Load .demo-state first (has CLUSTER_URL from setup)
    if [[ -f "$SCRIPT_DIR/.demo-state" ]]; then
        set -a; source "$SCRIPT_DIR/.demo-state"; set +a
    fi
    # Load demo.tfvars for HCP credentials (needed for 01-cluster destroy)
    load_tfvars || true

    # Get CLUSTER_URL from .demo-state or terraform output
    if [[ -z "${CLUSTER_URL:-}" ]]; then
        CLUSTER_URL=$(cd "$SCRIPT_DIR/terraform/01-cluster" && terraform output -raw boundary_cluster_url 2>/dev/null) || true
    fi
    export CLUSTER_URL="${CLUSTER_URL:-}"

    # Destroy 02-resources first (needs CLUSTER_URL + credentials in tfvars)
    if [[ -n "$CLUSTER_URL" ]]; then
        info "Terraform: destroying Boundary resources..."
        write_tf_tfvars "02-resources" >/dev/null
        (cd "$SCRIPT_DIR/terraform/02-resources" && terraform init -input=false && terraform destroy -auto-approve) || warn "Resource destroy failed (may already be gone)"
    else
        warn "No CLUSTER_URL found — skipping 02-resources destroy"
    fi

    # Destroy 01-cluster (HCP cluster itself)
    info "Terraform: destroying HCP Boundary cluster..."
    write_tf_tfvars "01-cluster" >/dev/null
    (cd "$SCRIPT_DIR/terraform/01-cluster" && terraform init -input=false && terraform destroy -auto-approve) || warn "Cluster destroy failed (may already be gone)"

    # Kill the self-managed worker if running
    if [[ -f "$SCRIPT_DIR/.worker-pid" ]]; then
        local wpid
        wpid=$(cat "$SCRIPT_DIR/.worker-pid")
        kill "$wpid" 2>/dev/null && info "Killed worker process (PID $wpid)" || true
        rm -f "$SCRIPT_DIR/.worker-pid"
    fi

    # Clean up generated files
    rm -f "$SCRIPT_DIR/.mcp.json" "$SCRIPT_DIR/.demo-state" "$SCRIPT_DIR/worker.hcl"
    rm -f "$SCRIPT_DIR/terraform/01-cluster/terraform.tfvars"
    rm -f "$SCRIPT_DIR/terraform/02-resources/terraform.tfvars"

    ok "Teardown complete. All resources destroyed, generated files removed."
}

# ── Run ─────────────────────────────────────────────────────────────────────
do_run() {
    if [[ ! -f "$SCRIPT_DIR/.mcp.json" ]]; then
        fail ".mcp.json not found. Run ./demo.sh --setup first."
    fi
    info "Launching agent with .mcp.json..."
    if command -v ibm-bob >/dev/null 2>&1; then
        ibm-bob --config "$SCRIPT_DIR/.mcp.json" -p "$(cat "$SCRIPT_DIR/CLAUDE.md")"
    elif command -v claude >/dev/null 2>&1; then
        warn "ibm-bob not found, using claude code"
        claude --dangerously-skip-permissions -p "$(cat "$SCRIPT_DIR/CLAUDE.md")"
    else
        fail "No MCP-compatible agent found (ibm-bob or claude). Install one and try again."
    fi
}

# ── Export recording ────────────────────────────────────────────────────────
do_export() {
    local sr_id="$EXPORT_SR_ID"
    if [[ -z "$sr_id" ]]; then
        fail "Recording ID required: ./demo.sh --export <sr_ID>"
    fi

    # Load state
    if [[ -f "$SCRIPT_DIR/.demo-state" ]]; then
        set -a; source "$SCRIPT_DIR/.demo-state"; set +a
    else
        load_tfvars
    fi

    if [[ -z "${CLUSTER_URL:-}" ]]; then
        fail "No cluster URL. Run --setup first or ensure .demo-state exists."
    fi

    export BOUNDARY_ADDR="$CLUSTER_URL"
    export BOUNDARY_PASSWORD="${BOUNDARY_ADMIN_PASSWORD:-AdminPass123!}"

    info "Authenticating to Boundary..."
    TOKEN=$(boundary authenticate password \
        -login-name "${BOUNDARY_ADMIN_USERNAME:-admin}" \
        -password env://BOUNDARY_PASSWORD \
        -format json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['item']['attributes']['token'])")
    export BOUNDARY_TOKEN="$TOKEN"

    info "Reading recording $sr_id..."
    local conn_rec_id
    conn_rec_id=$(boundary session-recordings read -id "$sr_id" -format json 2>/dev/null | \
        python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('item',d)['connection_recordings'][0]['id'])") || \
        fail "Failed to read recording. Check the SR ID."

    info "Triggering WebM export for connection recording $conn_rec_id..."
    local export_id
    export_id=$(boundary session-recordings export -connection-recording-id "$conn_rec_id" -mime-type video/webm -format json 2>/dev/null | \
        python3 -c "import json,sys; print(json.load(sys.stdin)['item']['id'])") || \
        fail "Export trigger failed."

    info "Waiting for export to finish (export ID: $export_id)..."
    local state="processing"
    for i in $(seq 1 40); do
        sleep 3
        state=$(boundary session-recordings export read -id "$export_id" -format json 2>/dev/null | \
            python3 -c "import json,sys; print(json.load(sys.stdin)['item']['state'])") || true
        printf "  poll %d: state=%s\n" "$i" "$state"
        [[ "$state" == "finished" ]] && break
        [[ "$state" == "failed" ]] && fail "Export failed on worker."
    done
    [[ "$state" != "finished" ]] && fail "Export timed out."

    info "Downloading WebM from MinIO..."
    local output_path="${OUTPUT_PATH:-/tmp/rdp-recording-$sr_id.webm}"
    python3 -c "
import boto3, os, sys
s3 = boto3.client('s3',
    endpoint_url='${MINIO_ENDPOINT}',
    aws_access_key_id='${MINIO_ACCESS_KEY}',
    aws_secret_access_key='${MINIO_SECRET_KEY}',
    region_name='us-east-1')
prefix = '${sr_id}.export/${conn_rec_id}.export/'
objs = s3.list_objects_v2(Bucket='${MINIO_BUCKET_NAME}', Prefix=prefix)
webm_key = None
for o in objs.get('Contents', []):
    if o['Key'].endswith('.webm'):
        webm_key = o['Key']
        break
if not webm_key:
    print('No .webm found at prefix: ' + prefix, file=sys.stderr)
    sys.exit(1)
s3.download_file('${MINIO_BUCKET_NAME}', webm_key, '$output_path')
print(f'Downloaded: {webm_key} -> $output_path ({os.path.getsize(\"$output_path\")} bytes)')
"

    ok "Export complete: $output_path"
    echo ""
    echo "  Recording: $sr_id"
    echo "  Export ID: $export_id"
    echo "  WebM:      $output_path ($(stat -c%s "$output_path" 2>/dev/null || stat -f%z "$output_path") bytes)"
    echo ""
    echo "  Verify:    ffprobe -v quiet -print_format json -show_format \"$output_path\""
}

# ── Main ──────────────────────────────────────────────────────────────────
case "$ACTION" in
    setup)    do_setup ;;
    teardown) do_teardown ;;
    run)      do_run ;;
    export)   do_export ;;
    *)        fail "Unknown action: $ACTION" ;;
esac