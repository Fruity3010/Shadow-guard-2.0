#!/usr/bin/env python3
"""
Simple proxy blocker that gets machine policy from the local ShadowGuard agent.
"""
from mitmproxy import http
from pathlib import Path
import json
import time
from datetime import datetime
import threading
import os
import requests as http_requests
from shadowguard_paths import runtime_path

DEFAULT_BLOCKED = ["facebook.com", "twitter.com", "instagram.com", "reddit.com", "youtube.com", "tiktok.com"]
LOG_FILE = runtime_path("proxy_activity.json")
LOG_LOCK = threading.Lock()
LOCAL_AGENT_URL = os.environ.get(
    "SHADOWGUARD_LOCAL_AGENT_URL",
    os.environ.get("SHADOWGUARD_BLOCKLIST_URL", "http://127.0.0.1:5555")
).rstrip("/")

blocklist_cache = []
blocklist_cache_time = 0

def get_default_blocklist():
    """Return the built-in fallback rules."""
    return [{"domain": d, "methods": ["GET", "POST"]} for d in DEFAULT_BLOCKED]

def fetch_blocklist_from_agent():
    """Fetch policy from the local ShadowGuard agent."""
    response = http_requests.get(
        f"{LOCAL_AGENT_URL}/agent/blocked-sites",
        timeout=3
    )
    response.raise_for_status()
    rules = response.json()
    if not isinstance(rules, list):
        raise ValueError("Agent blocklist payload must be a JSON array")
    return rules

def load_blocklist():
    """Refresh block rules from the local agent every 5 seconds."""
    global blocklist_cache, blocklist_cache_time

    if time.time() - blocklist_cache_time > 5:
        try:
            blocklist_cache = fetch_blocklist_from_agent()
            blocklist_cache_time = time.time()
            print(f"Loaded {len(blocklist_cache)} blocking rules from local agent")
        except Exception as e:
            print(f"Local agent blocklist fetch failed: {e}")
            if not blocklist_cache:
                blocklist_cache = get_default_blocklist()

    return blocklist_cache

html_path = Path(__file__).parent / "templates" / "blocked.html"
if html_path.exists():
    with open(html_path, 'r', encoding='utf-8') as f:
        HTML_TEMPLATE = f.read()
    print(f"Loaded custom blocked.html ({len(HTML_TEMPLATE)} bytes)")
else:
    print("Using fallback HTML template")
    HTML_TEMPLATE = """
    <html>
    <body style="background:#2c3e50;color:white;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;font-family:system-ui;">
        <div style="text-align:center;padding:60px;background:linear-gradient(135deg,#e74c3c,#c0392b);border-radius:20px;">
            <h1 style="font-size:80px;margin:0;">BLOCKED</h1>
            <h2>{{DOMAIN}}</h2>
            <p>This site is not allowed</p>
        </div>
    </body>
    </html>
    """

def log_to_file(domain, path="/", method="GET", blocked=False, status="200", response_time=0):
    """Log activity to the shared JSON file."""
    try:
        with LOG_LOCK:
            logs = []
            if LOG_FILE.exists():
                try:
                    with open(LOG_FILE, 'r', encoding='utf-8') as f:
                        logs = json.load(f)
                except Exception:
                    logs = []

            logs.append({
                'timestamp': datetime.now().isoformat(),
                'domain': domain,
                'path': path,
                'method': method,
                'blocked': blocked,
                'status': status,
                'response_time': response_time
            })

            logs = logs[-1000:]

            with open(LOG_FILE, 'w', encoding='utf-8') as f:
                json.dump(logs, f)
    except Exception as e:
        print(f"Logging failed: {e}")

def request(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host.lower()
    path = flow.request.path
    method = flow.request.method
    start_time = time.time()

    if "localhost" in host or "127.0.0.1" in host:
        return

    blocklist = load_blocklist()

    blocked = False
    for rule in blocklist:
        domain = (rule.get('domain') or '').lower()
        methods = rule.get('methods', ['GET', 'POST'])
        if domain and domain in host and method in methods:
            blocked = True
            break

    if blocked:
        html = HTML_TEMPLATE.replace("{{DOMAIN}}", host)

        for rule in blocklist:
            domain = (rule.get('domain') or '').lower()
            reason = rule.get('reason')
            if domain and domain in host and reason:
                html = html.replace(
                    "</p>",
                    f"</p><p style='font-size:14px;opacity:0.8;margin-top:20px;'>Reason: {reason}</p>"
                )
                break

        flow.response = http.Response.make(
            200,
            html.encode('utf-8'),
            {"Content-Type": "text/html; charset=UTF-8"}
        )
        print(f"Blocked: {host} [{method}]")

        response_time = (time.time() - start_time) * 1000
        log_to_file(host, path, method, blocked=True, status="BLOCKED", response_time=response_time)
    else:
        log_to_file(host, path, method, blocked=False, status="200", response_time=0)

def response(flow: http.HTTPFlow) -> None:
    """Log responses for allowed requests."""
    pass
