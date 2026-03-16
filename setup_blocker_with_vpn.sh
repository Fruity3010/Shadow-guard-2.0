#!/bin/bash
# setup_blocker_with_vpn.sh - Shadow IT Control Platform with VPN Prevention

echo "🛡️ Shadow IT Control Platform + VPN Prevention"
echo "================================================"
echo "⚡ Starting website blocker with VPN detection..."

# Kill any existing mitmproxy processes
killall mitmdump 2>/dev/null
killall python 2>/dev/null || true
sleep 1

PORT=8888

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BLOCKED_HTML="$SCRIPT_DIR/templates/blocked.html"
VPN_WARNING_HTML="$SCRIPT_DIR/templates/vpn_warning.html"

# Check if blocked.html exists
if [ ! -f "$BLOCKED_HTML" ]; then
    echo "⚠️  Warning: blocked.html not found at $BLOCKED_HTML"
    echo "⚠️  Using default blocking page"
fi

# Check if vpn_warning.html exists
if [ ! -f "$VPN_WARNING_HTML" ]; then
    echo "⚠️  Warning: vpn_warning.html not found"
fi

# Install dependencies if needed
if ! command -v mitmdump &> /dev/null; then
    echo "📦 Installing mitmproxy..."
    brew install mitmproxy
fi

# Check if virtual environment exists
if [ -d "$SCRIPT_DIR/.venv" ]; then
    echo "✅ Using virtual environment"
    source "$SCRIPT_DIR/.venv/bin/activate"
else:
    echo "📦 Creating virtual environment..."
    python3 -m venv "$SCRIPT_DIR/.venv"
    source "$SCRIPT_DIR/.venv/bin/activate"
    pip install -r "$SCRIPT_DIR/requirements.txt"
fi

# Add VPN providers to blocklist
echo "🚫 Adding VPN providers to blocklist..."
python3 << EOF
from vpn_detector import VPNDetector
import json
from pathlib import Path

detector = VPNDetector()
vpn_blocklist = detector.get_vpn_provider_blocklist()

# Load existing blocklist
blocklist_file = Path('$SCRIPT_DIR/blocklist.json')
if blocklist_file.exists():
    with open(blocklist_file, 'r') as f:
        blocklist = json.load(f)
else:
    blocklist = []

# Get existing domains
existing_domains = {b['domain'] for b in blocklist}

# Add VPN domains
added = 0
for vpn_entry in vpn_blocklist:
    if vpn_entry['domain'] not in existing_domains:
        blocklist.append(vpn_entry)
        added += 1

# Save
with open(blocklist_file, 'w') as f:
    json.dump(blocklist, f, indent=2)

print(f"✅ Added {added} VPN provider domains to blocklist")
print(f"📋 Total blocking rules: {len(blocklist)}")
EOF

# Start the dashboard in background
echo "📊 Starting dashboard server..."
cd "$SCRIPT_DIR"
python dashboard.py > /tmp/dashboard.log 2>&1 &
DASHBOARD_PID=$!
sleep 2

# Check if dashboard started successfully
if kill -0 $DASHBOARD_PID 2>/dev/null; then
    echo "✅ Dashboard running at http://localhost:5555"
    echo "📱 Open http://localhost:5555 in your browser to view statistics"
else
    echo "⚠️  Dashboard failed to start, but proxy will continue"
    echo "Check /tmp/dashboard.log for errors"
fi

# Start VPN monitoring in background
echo "🔍 Starting VPN monitor..."
python monitor_vpn.py > /tmp/vpn_monitor.log 2>&1 &
VPN_MONITOR_PID=$!
sleep 1

if kill -0 $VPN_MONITOR_PID 2>/dev/null; then
    echo "✅ VPN monitor active (checking every 60s)"
else
    echo "⚠️  VPN monitor failed to start"
    echo "Check /tmp/vpn_monitor.log for errors"
fi

# Start mitmproxy in background to generate certificates
echo "🔐 Setting up certificates..."
mitmdump --listen-port $PORT --set confdir=~/.mitmproxy &
MITM_PID=$!
sleep 3
kill $MITM_PID 2>/dev/null

# Install the certificate automatically
CERT_PATH=~/.mitmproxy/mitmproxy-ca-cert.pem
if [ -f "$CERT_PATH" ]; then
    echo "📜 Installing mitmproxy certificate (requires password)..."

    # Add certificate to system keychain
    sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "$CERT_PATH" 2>/dev/null || {
        # Alternative method if first fails
        sudo security add-certificates -k /System/Library/Keychains/SystemRootCertificates.keychain "$CERT_PATH" 2>/dev/null
    }

    echo "✅ Certificate installed!"
else
    echo "⚠️  Certificate not found, HTTPS sites might show warnings"
fi

# Configure system proxy
echo "⚙️  Configuring Mac network proxy..."
networksetup -setwebproxy "Wi-Fi" 127.0.0.1 $PORT
networksetup -setsecurewebproxy "Wi-Fi" 127.0.0.1 $PORT
networksetup -setwebproxystate "Wi-Fi" on
networksetup -setsecurewebproxystate "Wi-Fi" on

# Cleanup function
cleanup() {
    echo -e "\n🧹 Cleaning up..."
    networksetup -setwebproxystate "Wi-Fi" off
    networksetup -setsecurewebproxystate "Wi-Fi" off
    killall mitmdump 2>/dev/null

    # Stop dashboard if running
    if [ ! -z "$DASHBOARD_PID" ] && kill -0 $DASHBOARD_PID 2>/dev/null; then
        echo "📊 Stopping dashboard..."
        kill $DASHBOARD_PID 2>/dev/null
    fi

    # Stop VPN monitor if running
    if [ ! -z "$VPN_MONITOR_PID" ] && kill -0 $VPN_MONITOR_PID 2>/dev/null; then
        echo "🔍 Stopping VPN monitor..."
        kill $VPN_MONITOR_PID 2>/dev/null
    fi

    echo "✅ Proxy, dashboard, and VPN monitor disabled!"
}

trap cleanup EXIT INT TERM

# Display features
echo ""
echo "✅ Ready!"
echo "⚡ Features Active:"
echo "  • Dynamic blocklist management"
echo "  • VPN provider blocking (${#VPN_PROVIDERS[@]} domains)"
echo "  • Real-time VPN detection"
echo "  • Network monitoring & statistics"
echo ""
echo "📊 Dashboard: http://localhost:5555"
echo "📋 Admin Panel: http://localhost:5555/admin"
echo "🔍 VPN Status: http://localhost:5555/api/vpn-status"
echo ""
echo "⚠️  Press Ctrl+C to stop"
echo "=========================================="

# Run the proxy
mitmdump -s "$SCRIPT_DIR/simple_blocker.py" --listen-port $PORT --set confdir=~/.mitmproxy
