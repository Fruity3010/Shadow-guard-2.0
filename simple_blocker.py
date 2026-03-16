#!/usr/bin/env python3
"""
Simple proxy blocker that logs to a shared JSON file and reads dynamic blocklist
"""
from mitmproxy import http
from pathlib import Path
import json
import time
import tempfile
from datetime import datetime
import threading
import os

# Dynamic blocklist file
BLOCKLIST_FILE = Path(__file__).parent / "blocklist.json"
# Default blocked sites (fallback)
DEFAULT_BLOCKED = ["facebook.com", "twitter.com", "instagram.com", "reddit.com", "youtube.com", "tiktok.com"]
LOG_FILE = Path(tempfile.gettempdir()) / "proxy_activity.json"
LOG_LOCK = threading.Lock()

# Cache for blocklist (reload periodically)
blocklist_cache = []
blocklist_cache_time = 0

def load_blocklist():
    """Load blocklist from JSON file with caching"""
    global blocklist_cache, blocklist_cache_time
    
    # Reload every 5 seconds for real-time updates
    if time.time() - blocklist_cache_time > 5:
        try:
            if BLOCKLIST_FILE.exists():
                with open(BLOCKLIST_FILE, 'r') as f:
                    blocklist_cache = json.load(f)
                    blocklist_cache_time = time.time()
                    print(f"📋 Loaded {len(blocklist_cache)} blocking rules")
            else:
                # Use default if file doesn't exist
                blocklist_cache = [{"domain": d, "methods": ["GET", "POST"]} for d in DEFAULT_BLOCKED]
        except Exception as e:
            print(f"⚠️ Error loading blocklist: {e}")
            if not blocklist_cache:  # If cache is empty, use defaults
                blocklist_cache = [{"domain": d, "methods": ["GET", "POST"]} for d in DEFAULT_BLOCKED]
    
    return blocklist_cache

# Load the custom HTML template
html_path = Path(__file__).parent / "templates" / "blocked.html"
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

def log_to_file(domain, path="/", method="GET", blocked=False, status="200", response_time=0):
    """Log activity to JSON file"""
    try:
        with LOG_LOCK:
            # Read existing logs
            logs = []
            if LOG_FILE.exists():
                try:
                    with open(LOG_FILE, 'r') as f:
                        logs = json.load(f)
                except:
                    logs = []
            
            # Add new log
            logs.append({
                'timestamp': datetime.now().isoformat(),
                'domain': domain,
                'path': path,
                'method': method,
                'blocked': blocked,
                'status': status,
                'response_time': response_time
            })
            
            # Keep only last 1000 entries
            logs = logs[-1000:]
            
            # Write back
            with open(LOG_FILE, 'w') as f:
                json.dump(logs, f)
                
    except Exception as e:
        print(f"⚠️ Logging failed: {e}")

def request(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host.lower()
    path = flow.request.path
    method = flow.request.method
    start_time = time.time()
    
    # Skip localhost and dashboard
    if "localhost" in host or "127.0.0.1" in host:
        return
    
    # Load current blocklist
    blocklist = load_blocklist()
    
    # Check if domain is blocked and method matches
    blocked = False
    for rule in blocklist:
        if rule['domain'] in host:
            # Check if this method is blocked
            if method in rule.get('methods', ['GET', 'POST']):
                blocked = True
                break
    
    if blocked:
        # Generate block page with reason if available
        html = HTML_TEMPLATE.replace("{{DOMAIN}}", host)
        
        # Add reason if available
        for rule in blocklist:
            if rule['domain'] in host and 'reason' in rule:
                html = html.replace("</p>", f"</p><p style='font-size:14px;opacity:0.8;margin-top:20px;'>Reason: {rule['reason']}</p>")
                break
        
        flow.response = http.Response.make(
            200,
            html.encode('utf-8'),
            {"Content-Type": "text/html; charset=UTF-8"})
        print(f"🚫 Blocked: {host} [{method}]")
        
        # Log blocked request
        response_time = (time.time() - start_time) * 1000
        log_to_file(host, path, method, blocked=True, status="BLOCKED", response_time=response_time)
    else:
        # Log allowed request
        log_to_file(host, path, method, blocked=False, status="200", response_time=0)

def response(flow: http.HTTPFlow) -> None:
    """Log responses for allowed requests"""
    pass