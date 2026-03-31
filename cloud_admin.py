#!/usr/bin/env python3
"""
Isolated cloud admin for ShadowGuard.
This service proxies admin actions to the authenticated machine agent.
"""

import os
import requests
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

AGENT_BASE_URL = os.environ.get("SHADOWGUARD_TARGET_AGENT_URL", "").rstrip("/")
AGENT_URL_TEMPLATE = os.environ.get("SHADOWGUARD_TARGET_AGENT_URL_TEMPLATE", "").strip()
ADMIN_PORT = int(os.environ.get("SHADOWGUARD_ADMIN_PORT", "8000"))
DEFAULT_MACHINE = os.environ.get("SHADOWGUARD_DEFAULT_MACHINE", "").strip()
ALLOWED_MACHINES = [m.strip() for m in os.environ.get("SHADOWGUARD_ALLOWED_MACHINES", "").split(",") if m.strip()]

def get_requested_machine():
    """Resolve the machine identifier from query string, body, or default config."""
    body = request.get_json(silent=True) or {}
    machine = (
        request.args.get('machine')
        or body.get('machine')
        or DEFAULT_MACHINE
    )
    return (machine or "").strip()

def resolve_agent_base_url():
    """Resolve the final machine-agent URL for this request."""
    machine = get_requested_machine()

    if machine and ALLOWED_MACHINES and machine not in ALLOWED_MACHINES:
        raise ValueError(f"Machine '{machine}' is not in SHADOWGUARD_ALLOWED_MACHINES")

    if machine and AGENT_URL_TEMPLATE:
        return AGENT_URL_TEMPLATE.format(machine=machine), machine

    if AGENT_BASE_URL:
        return AGENT_BASE_URL, machine

    if AGENT_URL_TEMPLATE:
        raise ValueError("A machine value is required when SHADOWGUARD_TARGET_AGENT_URL_TEMPLATE is used")

    raise ValueError("No machine agent URL is configured")

def ensure_agent_configured():
    """Return a JSON error response when the target machine agent is missing."""
    if not (AGENT_BASE_URL or AGENT_URL_TEMPLATE):
        return jsonify({
            'status': 'error',
            'error': 'Set SHADOWGUARD_TARGET_AGENT_URL or SHADOWGUARD_TARGET_AGENT_URL_TEMPLATE for the cloud admin.'
        }), 500
    return None

def proxy_target(path):
    """Build the proxied target URL and machine label."""
    base_url, machine = resolve_agent_base_url()
    return f"{base_url}{path}", machine or base_url

def proxy_response_json(response, machine):
    """Normalize proxied JSON and include the resolved machine."""
    payload = response.json()
    if isinstance(payload, dict):
        payload.setdefault('machine', machine)
    return jsonify(payload), response.status_code

def request_payload():
    """Return the request payload without the local-only machine selector."""
    payload = request.get_json(silent=True) or {}
    if isinstance(payload, dict):
        payload.pop('machine', None)
    return payload

def template_context():
    """Build shared template context for the admin UI."""
    return {
        'agent_base_url': AGENT_BASE_URL,
        'agent_url_template': AGENT_URL_TEMPLATE,
        'default_machine': DEFAULT_MACHINE,
        'allowed_machines': ALLOWED_MACHINES
    }

def proxy_get(path):
    """Proxy a GET request to the machine agent."""
    config_error = ensure_agent_configured()
    if config_error:
        return config_error

    try:
        target_url, machine = proxy_target(path)
        response = requests.get(target_url, timeout=10)
        return proxy_response_json(response, machine)
    except (requests.RequestException, ValueError) as exc:
        return jsonify({'status': 'error', 'error': str(exc)}), 502

@app.route('/')
@app.route('/admin')
def admin():
    """Serve the isolated admin panel."""
    return render_template('admin.html', **template_context())

@app.route('/api/blocked-sites')
def blocked_sites():
    return proxy_get('/agent/blocked-sites')

@app.route('/api/admin-stats')
def admin_stats():
    return proxy_get('/agent/admin-stats')

@app.route('/api/blocklist-version')
def blocklist_version():
    return proxy_get('/agent/blocklist-version')

@app.route('/api/block-site', methods=['POST'])
def block_site():
    config_error = ensure_agent_configured()
    if config_error:
        return config_error

    try:
        target_url, machine = proxy_target('/agent/block-site')
        response = requests.post(
            target_url,
            json=request_payload(),
            timeout=10
        )
        return proxy_response_json(response, machine)
    except (requests.RequestException, ValueError) as exc:
        return jsonify({'status': 'error', 'error': str(exc)}), 502

@app.route('/api/unblock-site', methods=['POST'])
def unblock_site():
    config_error = ensure_agent_configured()
    if config_error:
        return config_error

    try:
        target_url, machine = proxy_target('/agent/unblock-site')
        response = requests.post(
            target_url,
            json=request_payload(),
            timeout=10
        )
        return proxy_response_json(response, machine)
    except (requests.RequestException, ValueError) as exc:
        return jsonify({'status': 'error', 'error': str(exc)}), 502

@app.route('/api/clear-all-blocks', methods=['POST'])
def clear_all_blocks():
    config_error = ensure_agent_configured()
    if config_error:
        return config_error

    try:
        target_url, machine = proxy_target('/agent/clear-all-blocks')
        response = requests.post(
            target_url,
            timeout=10
        )
        return proxy_response_json(response, machine)
    except (requests.RequestException, ValueError) as exc:
        return jsonify({'status': 'error', 'error': str(exc)}), 502

if __name__ == '__main__':
    print(f"Starting cloud admin on http://0.0.0.0:{ADMIN_PORT}")
    app.run(host='0.0.0.0', port=ADMIN_PORT, debug=False)
