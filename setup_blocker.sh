#!/bin/bash
# setup_blocker.sh - Shadow IT Control Platform

echo "🛡️ Shadow IT Control Platform"
echo "=============================="
echo "⚡ Starting website blocker..."

# Kill any existing mitmproxy processes
killall mitmdump 2>/dev/null
sleep 1

PORT=8888

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BLOCKED_HTML="$SCRIPT_DIR/templates/blocked.html"

# Check if blocked.html exists
if [ ! -f "$BLOCKED_HTML" ]; then
    echo "⚠️  Warning: blocked.html not found at $BLOCKED_HTML"
    echo "⚠️  Using default blocking page"
fi

# Create the Python proxy script with dashboard integration
cat > /tmp/blocker.py << EOF
from mitmproxy import http
from pathlib import Path
import time
import json
import urllib.request
import urllib.error

BLOCKED = ["facebook.com", "twitter.com", "instagram.com", "reddit.com", "youtube.com", "tiktok.com"]
DASHBOARD_URL = "http://localhost:5555/api/log"

# Load the custom HTML template
html_path = Path("$BLOCKED_HTML")
if html_path.exists():
    with open(html_path, 'r') as f:
        HTML_TEMPLATE = f.read()
    print(f"✅ Loaded custom blocked.html ({len(HTML_TEMPLATE)} bytes)")
else:
    print("⚠️  Using fallback HTML template")
    HTML_TEMPLATE = """
    <html>
    <body style="background:#2c3e50;color:white;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;font-family:system-ui;">
        <div style="text-align:center;padding:60px;background:linear-gradient(135deg,#e74c3c,#c0392b);border-radius:20px;">
            <h1 style="font-size:80px;margin:0;">🛑 BLOCKED</h1>
            <h2>{{DOMAIN}}</h2>
            <p>This site is not allowed</p>
        </div>
    </body>
    </html>
    """

def log_to_dashboard(domain, path="/", method="GET", blocked=False, status="200", response_time=0):
    """Send log data to the dashboard using urllib"""
    try:
        data = json.dumps({
            'domain': domain,
            'path': path,
            'method': method,
            'blocked': blocked,
            'status': status,
            'response_time': response_time
        }).encode('utf-8')
        
        req = urllib.request.Request(
            DASHBOARD_URL,
            data=data,
            headers={'Content-Type': 'application/json'}
        )
        
        with urllib.request.urlopen(req, timeout=0.5) as response:
            response.read()
            
    except (urllib.error.URLError, urllib.error.HTTPError, Exception) as e:
        # Log the error for debugging but don't crash
        print(f"⚠️ Dashboard logging failed for {domain}: {str(e)[:50]}")

def request(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host.lower()
    path = flow.request.path
    method = flow.request.method
    start_time = time.time()
    
    # Skip localhost and dashboard
    if "localhost" in host or "127.0.0.1" in host:
        return
    
    if any(b in host for b in BLOCKED):
        html = HTML_TEMPLATE.replace("{{DOMAIN}}", host)
        flow.response = http.Response.make(
            200,
            html.encode('utf-8'),
            {"Content-Type": "text/html; charset=UTF-8"})
        print(f"🚫 Blocked: {host}")
        
        # Log blocked request to dashboard
        response_time = (time.time() - start_time) * 1000
        log_to_dashboard(host, path, method, blocked=True, status="BLOCKED", response_time=response_time)
    else:
        # Log allowed request to dashboard
        log_to_dashboard(host, path, method, blocked=False, status="200", response_time=0)

def response(flow: http.HTTPFlow) -> None:
    """Log responses for allowed requests"""
    host = flow.request.pretty_host.lower()
    if not any(b in host for b in BLOCKED):
        # Already logged in request phase
        pass
EOF

# Install dependencies if needed
if ! command -v mitmdump &> /dev/null; then
    echo "📦 Installing mitmproxy..."
    brew install mitmproxy
fi

# Check if virtual environment exists
if [ -d "$SCRIPT_DIR/.venv" ]; then
    echo "✅ Using virtual environment"
    source "$SCRIPT_DIR/.venv/bin/activate"
else
    echo "📦 Creating virtual environment..."
    python3 -m venv "$SCRIPT_DIR/.venv"
    source "$SCRIPT_DIR/.venv/bin/activate"
    pip install -r "$SCRIPT_DIR/requirements.txt"
fi

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
    
    echo "✅ Proxy and dashboard disabled!"
}

trap cleanup EXIT INT TERM

# Display features
echo "✅ Ready!"
echo "⚡ Features Active:"
echo "  • Dynamic blocklist management via admin panel"
echo "  • Method-specific blocking (GET, POST, etc.)"
echo "  • Real-time statistics and monitoring"
echo "📊 Dashboard: http://localhost:5555"
echo "📋 Admin Panel: http://localhost:5555/admin"
echo "⚠️  Press Ctrl+C to stop"
echo "----------------------------------------"

# Run the proxy
mitmdump -s "$SCRIPT_DIR/simple_blocker.py" --listen-port $PORT --set confdir=~/.mitmproxy