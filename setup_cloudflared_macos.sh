#!/bin/bash
# setup_cloudflared_macos.sh - ShadowGuard Cloudflare Tunnel helper for macOS

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MACHINE_NAME=""
HOSTNAME_SUFFIX=""
TUNNEL_NAME=""
BASE_DIR="${SHADOWGUARD_BASE_DIR:-$SCRIPT_DIR/.shadowguard}"
CLOUDFLARED_DIR=""
CLOUDFLARED_EXE=""
CLOUDFLARED_CONFIG_DIR=""
AGENT_PORT="5555"
CREATE_TUNNEL=0
ROUTE_DNS=0
INSTALL_SERVICE=0
SERVICE_SCOPE="login"

write_step() {
    echo "[ShadowGuard Cloudflare] $1"
}

fail() {
    echo "Error: $1" >&2
    exit 1
}

ensure_directory() {
    local path_value="$1"
    mkdir -p "$path_value"
}

resolve_cloudflared_exe() {
    local candidate_exe="$1"
    local base_dir="$2"

    if [ -n "$candidate_exe" ] && [ -x "$candidate_exe" ]; then
        printf '%s\n' "$candidate_exe"
        return 0
    fi

    if [ -x "$base_dir/cloudflared" ]; then
        printf '%s\n' "$base_dir/cloudflared"
        return 0
    fi

    if command -v cloudflared >/dev/null 2>&1; then
        command -v cloudflared
        return 0
    fi

    return 1
}

install_cloudflared_if_needed() {
    local candidate_exe="$1"
    local base_dir="$2"
    local resolved_exe=""

    if resolved_exe="$(resolve_cloudflared_exe "$candidate_exe" "$base_dir")"; then
        printf '%s\n' "$resolved_exe"
        return 0
    fi

    write_step "cloudflared was not found. Attempting automatic install with Homebrew."
    if ! command -v brew >/dev/null 2>&1; then
        fail "cloudflared was not found and Homebrew is not available for automatic install."
    fi

    brew install cloudflared

    if resolved_exe="$(resolve_cloudflared_exe "$candidate_exe" "$base_dir")"; then
        printf '%s\n' "$resolved_exe"
        return 0
    fi

    fail "cloudflared install completed but the binary could not be found."
}

search_for_credential_file() {
    local primary_dir="$1"
    local legacy_dir="$HOME/.cloudflared"
    local newest_file=""
    local candidate=""
    local newest_mtime="0"
    local current_mtime=""

    for candidate in "$primary_dir"/*.json "$legacy_dir"/*.json; do
        [ -f "$candidate" ] || continue
        current_mtime="$(stat -f "%m" "$candidate" 2>/dev/null || echo 0)"
        if [ "$current_mtime" -gt "$newest_mtime" ]; then
            newest_file="$candidate"
            newest_mtime="$current_mtime"
        fi
    done

    if [ -n "$newest_file" ]; then
        printf '%s\n' "$newest_file"
        return 0
    fi

    return 1
}

copy_if_present() {
    local source_path="$1"
    local destination_dir="$2"

    if [ -f "$source_path" ]; then
        cp "$source_path" "$destination_dir/"
    fi
}

write_config_file() {
    local config_path="$1"
    local tunnel_id="$2"
    local credential_file="$3"
    local resolved_hostname="$4"
    local agent_port="$5"

    cat > "$config_path" <<EOF
tunnel: $tunnel_id
credentials-file: $credential_file

ingress:
  - hostname: $resolved_hostname
    service: http://127.0.0.1:$agent_port
  - service: http_status:404
EOF
}

install_service_login() {
    local cloudflared_exe="$1"
    local tunnel_id="$2"
    local resolved_hostname="$3"
    local agent_port="$4"
    local runtime_config_dir="$5"
    local credential_file="$6"
    local user_config_dir="$HOME/.cloudflared"
    local service_credential_file="$user_config_dir/$tunnel_id.json"

    ensure_directory "$user_config_dir"
    cp "$credential_file" "$service_credential_file"
    copy_if_present "$runtime_config_dir/cert.pem" "$user_config_dir"
    write_config_file "$user_config_dir/config.yml" "$tunnel_id" "$service_credential_file" "$resolved_hostname" "$agent_port"

    write_step "Installing cloudflared as a launch agent for the current user"
    "$cloudflared_exe" service install
}

install_service_boot() {
    local cloudflared_exe="$1"
    local tunnel_id="$2"
    local resolved_hostname="$3"
    local agent_port="$4"
    local runtime_config_dir="$5"
    local credential_file="$6"
    local system_config_dir="/etc/cloudflared"
    local service_credential_file="$system_config_dir/$tunnel_id.json"

    write_step "Installing cloudflared as a launch daemon (requires sudo)"
    sudo mkdir -p "$system_config_dir"
    sudo cp "$credential_file" "$service_credential_file"
    if [ -f "$runtime_config_dir/cert.pem" ]; then
        sudo cp "$runtime_config_dir/cert.pem" "$system_config_dir/"
    fi

    local temp_config
    temp_config="$(mktemp)"
    write_config_file "$temp_config" "$tunnel_id" "$service_credential_file" "$resolved_hostname" "$agent_port"
    sudo cp "$temp_config" "$system_config_dir/config.yml"
    rm -f "$temp_config"

    sudo "$cloudflared_exe" service install
    sudo launchctl start com.cloudflare.cloudflared || true
}

print_usage() {
    cat <<EOF
Usage:
  ./setup_cloudflared_macos.sh --machine-name NAME --hostname-suffix SUFFIX [options]

Options:
  --machine-name, -MachineName           Machine name used in the public hostname.
  --hostname-suffix, -HostnameSuffix     Hostname suffix such as guard.example.com.
  --tunnel-name, -TunnelName             Optional Cloudflare tunnel name. Defaults to machine name.
  --base-dir, -BaseDir                   Base directory for generated runtime files.
  --cloudflared-dir, -CloudflaredDir     Directory where cloudflared may be installed.
  --cloudflared-exe, -CloudflaredExe     Explicit path to the cloudflared binary.
  --cloudflared-config-dir, -CloudflaredConfigDir
                                         Directory for runtime tunnel config and credentials.
  --agent-port, -AgentPort               Local ShadowGuard agent port. Defaults to 5555.
  --create-tunnel, -CreateTunnel         Run cloudflared login and create the named tunnel.
  --route-dns, -RouteDns                 Create the DNS route for the machine hostname.
  --install-service, -InstallService     Install cloudflared as a macOS service.
  --service-scope                        login (default) or boot.
  --help, -h                             Show this help text.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --machine-name|-MachineName)
            MACHINE_NAME="${2:-}"
            shift 2
            ;;
        --hostname-suffix|-HostnameSuffix)
            HOSTNAME_SUFFIX="${2:-}"
            shift 2
            ;;
        --tunnel-name|-TunnelName)
            TUNNEL_NAME="${2:-}"
            shift 2
            ;;
        --base-dir|-BaseDir)
            BASE_DIR="${2:-}"
            shift 2
            ;;
        --cloudflared-dir|-CloudflaredDir)
            CLOUDFLARED_DIR="${2:-}"
            shift 2
            ;;
        --cloudflared-exe|-CloudflaredExe)
            CLOUDFLARED_EXE="${2:-}"
            shift 2
            ;;
        --cloudflared-config-dir|-CloudflaredConfigDir)
            CLOUDFLARED_CONFIG_DIR="${2:-}"
            shift 2
            ;;
        --agent-port|-AgentPort)
            AGENT_PORT="${2:-}"
            shift 2
            ;;
        --create-tunnel|-CreateTunnel)
            CREATE_TUNNEL=1
            shift
            ;;
        --route-dns|-RouteDns)
            ROUTE_DNS=1
            shift
            ;;
        --install-service|-InstallService)
            INSTALL_SERVICE=1
            shift
            ;;
        --service-scope)
            SERVICE_SCOPE="${2:-}"
            shift 2
            ;;
        --help|-h)
            print_usage
            exit 0
            ;;
        *)
            fail "Unknown argument: $1"
            ;;
    esac
done

[ -n "$MACHINE_NAME" ] || fail "Machine name is required. Use --machine-name."
[ -n "$HOSTNAME_SUFFIX" ] || fail "Hostname suffix is required. Use --hostname-suffix."
[ "$SERVICE_SCOPE" = "login" ] || [ "$SERVICE_SCOPE" = "boot" ] || fail "Service scope must be login or boot."

if [ -z "$CLOUDFLARED_DIR" ]; then
    CLOUDFLARED_DIR="$BASE_DIR/cloudflared/bin"
fi

if [ -z "$CLOUDFLARED_CONFIG_DIR" ]; then
    CLOUDFLARED_CONFIG_DIR="$BASE_DIR/cloudflared"
fi

ensure_directory "$BASE_DIR"
ensure_directory "$CLOUDFLARED_DIR"
ensure_directory "$CLOUDFLARED_CONFIG_DIR"
export SHADOWGUARD_BASE_DIR="$BASE_DIR"

RESOLVED_TUNNEL_NAME="$MACHINE_NAME"
if [ -n "$TUNNEL_NAME" ]; then
    RESOLVED_TUNNEL_NAME="$TUNNEL_NAME"
fi

RESOLVED_HOSTNAME="$MACHINE_NAME.$HOSTNAME_SUFFIX"
RESOLVED_EXE="$(install_cloudflared_if_needed "$CLOUDFLARED_EXE" "$CLOUDFLARED_DIR")"

write_step "Using machine hostname $RESOLVED_HOSTNAME"
write_step "Using tunnel name $RESOLVED_TUNNEL_NAME"
write_step "Using base directory $BASE_DIR"
write_step "Using cloudflared at $RESOLVED_EXE"
write_step "Using config directory $CLOUDFLARED_CONFIG_DIR"

if [ "$CREATE_TUNNEL" -eq 1 ]; then
    write_step "Logging into Cloudflare. A browser window may open."
    "$RESOLVED_EXE" tunnel login

    if [ -f "$HOME/.cloudflared/cert.pem" ]; then
        copy_if_present "$HOME/.cloudflared/cert.pem" "$CLOUDFLARED_CONFIG_DIR"
    fi

    write_step "Creating named tunnel $RESOLVED_TUNNEL_NAME"
    "$RESOLVED_EXE" tunnel create "$RESOLVED_TUNNEL_NAME"
fi

CREDENTIAL_FILE="$(search_for_credential_file "$CLOUDFLARED_CONFIG_DIR" || true)"
[ -n "$CREDENTIAL_FILE" ] || fail "No tunnel credential JSON file was found. Run with --create-tunnel or create the tunnel first."

TUNNEL_ID="$(basename "$CREDENTIAL_FILE" .json)"
RUNTIME_CREDENTIAL_FILE="$CLOUDFLARED_CONFIG_DIR/$TUNNEL_ID.json"
if [ "$CREDENTIAL_FILE" != "$RUNTIME_CREDENTIAL_FILE" ]; then
    cp "$CREDENTIAL_FILE" "$RUNTIME_CREDENTIAL_FILE"
    CREDENTIAL_FILE="$RUNTIME_CREDENTIAL_FILE"
    write_step "Copied tunnel credentials into $CLOUDFLARED_CONFIG_DIR"
fi

copy_if_present "$HOME/.cloudflared/cert.pem" "$CLOUDFLARED_CONFIG_DIR"

CONFIG_PATH="$CLOUDFLARED_CONFIG_DIR/config.yml"
write_config_file "$CONFIG_PATH" "$TUNNEL_ID" "$CREDENTIAL_FILE" "$RESOLVED_HOSTNAME" "$AGENT_PORT"
write_step "Wrote config to $CONFIG_PATH"

if [ "$ROUTE_DNS" -eq 1 ]; then
    write_step "Creating Cloudflare DNS route for $RESOLVED_HOSTNAME"
    "$RESOLVED_EXE" tunnel route dns "$RESOLVED_TUNNEL_NAME" "$RESOLVED_HOSTNAME"
fi

if [ "$INSTALL_SERVICE" -eq 1 ]; then
    if [ "$SERVICE_SCOPE" = "boot" ]; then
        install_service_boot "$RESOLVED_EXE" "$TUNNEL_ID" "$RESOLVED_HOSTNAME" "$AGENT_PORT" "$CLOUDFLARED_CONFIG_DIR" "$CREDENTIAL_FILE"
    else
        install_service_login "$RESOLVED_EXE" "$TUNNEL_ID" "$RESOLVED_HOSTNAME" "$AGENT_PORT" "$CLOUDFLARED_CONFIG_DIR" "$CREDENTIAL_FILE"
    fi
fi

echo
echo "Done."
echo "Machine hostname: https://$RESOLVED_HOSTNAME"
echo "Tunnel config: $CONFIG_PATH"
echo "Credential file: $CREDENTIAL_FILE"
if [ "$INSTALL_SERVICE" -eq 1 ]; then
    if [ "$SERVICE_SCOPE" = "boot" ]; then
        echo "Service config directory: /etc/cloudflared"
    else
        echo "Service config directory: $HOME/.cloudflared"
    fi
fi
echo
echo "Suggested cloud admin settings:"
echo "  SHADOWGUARD_TARGET_AGENT_URL_TEMPLATE=https://{machine}.$HOSTNAME_SUFFIX"
echo "  SHADOWGUARD_DEFAULT_MACHINE=$MACHINE_NAME"
