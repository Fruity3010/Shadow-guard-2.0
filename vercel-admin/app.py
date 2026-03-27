#!/usr/bin/env python3
"""
Standalone Vercel-ready ShadowGuard cloud admin.
Deploy this folder to Vercel with the project root set to vercel-admin/.
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

try:
    import requests
except ModuleNotFoundError:
    # Fall back to the stdlib so the admin app can still boot in minimal environments.
    class _FallbackRequestException(Exception):
        """Raised when the stdlib HTTP fallback cannot reach the target service."""

    class _FallbackResponse:
        def __init__(self, body, status_code, headers):
            self._body = body
            self.status_code = status_code
            self.headers = headers

        def json(self):
            encoding = self.headers.get_content_charset() or "utf-8"
            return json.loads(self._body.decode(encoding))

    class _RequestsFallback:
        RequestException = _FallbackRequestException

        @staticmethod
        def _request(method, url, json_body=None, timeout=10):
            data = None
            headers = {}

            if json_body is not None:
                data = json.dumps(json_body).encode("utf-8")
                headers["Content-Type"] = "application/json"

            request_obj = urllib_request.Request(url, data=data, headers=headers, method=method)

            try:
                with urllib_request.urlopen(request_obj, timeout=timeout) as response:
                    return _FallbackResponse(response.read(), response.getcode(), response.info())
            except urllib_error.HTTPError as exc:
                return _FallbackResponse(exc.read(), exc.code, exc.headers)
            except urllib_error.URLError as exc:
                raise _FallbackRequestException(str(exc.reason)) from exc

        def get(self, url, timeout=10):
            return self._request("GET", url, timeout=timeout)

        def post(self, url, json=None, timeout=10):
            return self._request("POST", url, json_body=json, timeout=timeout)

    requests = _RequestsFallback()

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS

try:
    import psycopg
    from psycopg.rows import dict_row
except ModuleNotFoundError:
    psycopg = None
    dict_row = None

app = Flask(__name__)
CORS(app)

AGENT_BASE_URL = os.environ.get("SHADOWGUARD_TARGET_AGENT_URL", "").rstrip("/")
AGENT_URL_TEMPLATE = os.environ.get("SHADOWGUARD_TARGET_AGENT_URL_TEMPLATE", "").strip()
ADMIN_PORT = int(os.environ.get("PORT", os.environ.get("SHADOWGUARD_ADMIN_PORT", "8000")))
DEFAULT_MACHINE = os.environ.get("SHADOWGUARD_DEFAULT_MACHINE", "").strip()
ALLOWED_MACHINES = [m.strip() for m in os.environ.get("SHADOWGUARD_ALLOWED_MACHINES", "").split(",") if m.strip()]
POLICY_DB_PATH = Path(__file__).parent / "policy_store.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DEFAULT_GROUPS = [
    ("HR", "Human Resources"),
    ("Finance", "Finance and accounting"),
    ("IT", "Internal technology team"),
]

def utcnow_iso():
    """Return a compact UTC timestamp for policy records."""
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def uses_postgres():
    """Return True when the policy store is configured to use Postgres."""
    return DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")

def sql_placeholders(query):
    """Translate portable placeholders into the active database format."""
    return query.replace("?", "%s") if uses_postgres() else query

def row_as_dict(row):
    """Normalize SQLite or psycopg rows into plain dicts."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    return dict(row)

def get_policy_connection():
    """Create a SQLite connection for the cloud policy store."""
    if uses_postgres():
        if psycopg is None:
            raise RuntimeError("DATABASE_URL is set but psycopg is not installed")
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        return conn

    conn = sqlite3.connect(POLICY_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def fetch_all(query, params=()):
    """Run a query and return all rows as dictionaries."""
    conn = get_policy_connection()
    cursor = conn.cursor()
    cursor.execute(sql_placeholders(query), params)
    rows = [row_as_dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def fetch_one(query, params=()):
    """Run a query and return a single row as a dictionary."""
    conn = get_policy_connection()
    cursor = conn.cursor()
    cursor.execute(sql_placeholders(query), params)
    row = row_as_dict(cursor.fetchone())
    conn.close()
    return row

def execute_write(query, params=()):
    """Run a write query and return the affected row count and last inserted id."""
    conn = get_policy_connection()
    cursor = conn.cursor()
    cursor.execute(sql_placeholders(query), params)
    rowcount = cursor.rowcount
    lastrowid = getattr(cursor, "lastrowid", None)
    if uses_postgres() and lastrowid is None and cursor.description:
        returned = cursor.fetchone()
        lastrowid = returned[0] if returned else None
    conn.commit()
    conn.close()
    return rowcount, lastrowid

def init_policy_store():
    """Initialize local policy storage for groups, assignments, and rules."""
    conn = get_policy_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            name TEXT PRIMARY KEY,
            description TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS machine_assignments (
            machine_name TEXT PRIMARY KEY,
            group_name TEXT,
            department TEXT DEFAULT '',
            user_name TEXT DEFAULT '',
            device_label TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        )
    ''')
    if uses_postgres():
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS policies (
                id SERIAL PRIMARY KEY,
                scope_type TEXT NOT NULL,
                scope_target TEXT NOT NULL,
                app_domain TEXT NOT NULL,
                action TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
    else:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS policies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope_type TEXT NOT NULL,
                scope_target TEXT NOT NULL,
                app_domain TEXT NOT NULL,
                action TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_policies_scope ON policies(scope_type, scope_target)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_policies_domain ON policies(app_domain)')
    for name, description in DEFAULT_GROUPS:
        if uses_postgres():
            cursor.execute(
                'INSERT INTO groups (name, description, created_at) VALUES (%s, %s, %s) ON CONFLICT (name) DO NOTHING',
                (name, description, utcnow_iso())
            )
        else:
            cursor.execute(
                'INSERT OR IGNORE INTO groups (name, description, created_at) VALUES (?, ?, ?)',
                (name, description, utcnow_iso())
            )
    conn.commit()
    conn.close()

def normalize_domain(domain):
    """Normalize app domains for policy matching."""
    normalized = (domain or "").strip().lower()
    normalized = normalized.replace("http://", "").replace("https://", "")
    return normalized.split("/")[0].strip()

def domain_matches(domain, rule_domain):
    """Return True when a rule domain applies to the tested domain."""
    tested = normalize_domain(domain)
    rule = normalize_domain(rule_domain)
    if not tested or not rule:
        return False
    return tested == rule or tested.endswith(f".{rule}")

def list_groups():
    """Return all configured access groups."""
    return fetch_all('SELECT name, description, created_at FROM groups ORDER BY name')

def create_group(name, description=""):
    """Create a new access group."""
    cleaned_name = (name or "").strip()
    if not cleaned_name:
        raise ValueError("Group name is required")

    execute_write(
        'INSERT INTO groups (name, description, created_at) VALUES (?, ?, ?)',
        (cleaned_name, (description or "").strip(), utcnow_iso())
    )
    return {"name": cleaned_name, "description": (description or "").strip()}

def get_machine_assignment(machine_name):
    """Return the current assignment for a machine, if present."""
    cleaned_machine = (machine_name or "").strip()
    if not cleaned_machine:
        return None

    row = fetch_one('''
        SELECT machine_name, group_name, department, user_name, device_label, updated_at
        FROM machine_assignments
        WHERE machine_name = ?
    ''', (cleaned_machine,))
    return row

def upsert_machine_assignment(machine_name, group_name="", department="", user_name="", device_label=""):
    """Assign a machine to a group and metadata fields."""
    cleaned_machine = (machine_name or "").strip()
    if not cleaned_machine:
        raise ValueError("Machine name is required")

    cleaned_group = (group_name or "").strip()
    if cleaned_group:
        available_groups = {group["name"] for group in list_groups()}
        if cleaned_group not in available_groups:
            raise ValueError(f"Unknown group '{cleaned_group}'")

    payload = (
        cleaned_machine,
        cleaned_group,
        (department or "").strip(),
        (user_name or "").strip(),
        (device_label or "").strip(),
        utcnow_iso()
    )

    execute_write('''
        INSERT INTO machine_assignments (
            machine_name, group_name, department, user_name, device_label, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(machine_name) DO UPDATE SET
            group_name = excluded.group_name,
            department = excluded.department,
            user_name = excluded.user_name,
            device_label = excluded.device_label,
            updated_at = excluded.updated_at
    ''', payload)
    return get_machine_assignment(cleaned_machine)

def list_policies():
    """Return configured app access policies."""
    return fetch_all('''
        SELECT id, scope_type, scope_target, app_domain, action, description, created_at, updated_at
        FROM policies
        ORDER BY scope_type, scope_target, app_domain, id DESC
    ''')

def create_policy(scope_type, scope_target, app_domain, action, description=""):
    """Create a policy rule for a machine, group, or all machines."""
    cleaned_scope_type = (scope_type or "").strip().lower()
    cleaned_action = (action or "").strip().lower()
    cleaned_domain = normalize_domain(app_domain)

    if cleaned_scope_type not in {"machine", "group", "global"}:
        raise ValueError("Scope type must be machine, group, or global")
    if cleaned_action not in {"allow", "block", "isolate"}:
        raise ValueError("Action must be allow, block, or isolate")
    if not cleaned_domain:
        raise ValueError("App domain is required")

    if cleaned_scope_type == "machine":
        cleaned_target = (scope_target or "").strip()
        if not cleaned_target:
            raise ValueError("Machine target is required")
    elif cleaned_scope_type == "group":
        cleaned_target = (scope_target or "").strip()
        available_groups = {group["name"] for group in list_groups()}
        if cleaned_target not in available_groups:
            raise ValueError("Select a valid group")
    else:
        cleaned_target = "*"

    now = utcnow_iso()
    if uses_postgres():
        _, policy_id = execute_write('''
            INSERT INTO policies (scope_type, scope_target, app_domain, action, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        ''', (cleaned_scope_type, cleaned_target, cleaned_domain, cleaned_action, (description or "").strip(), now, now))
    else:
        _, policy_id = execute_write('''
            INSERT INTO policies (scope_type, scope_target, app_domain, action, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (cleaned_scope_type, cleaned_target, cleaned_domain, cleaned_action, (description or "").strip(), now, now))

    return next(policy for policy in list_policies() if policy["id"] == policy_id)

def delete_policy(policy_id):
    """Delete a policy rule."""
    deleted, _ = execute_write('DELETE FROM policies WHERE id = ?', (policy_id,))
    deleted = deleted > 0
    return deleted

def resolve_policy(machine_name, app_domain):
    """Compute the effective policy for a machine and app domain."""
    cleaned_machine = (machine_name or "").strip()
    cleaned_domain = normalize_domain(app_domain)
    if not cleaned_machine:
        raise ValueError("Machine name is required")
    if not cleaned_domain:
        raise ValueError("App domain is required")

    assignment = get_machine_assignment(cleaned_machine)
    assigned_group = assignment["group_name"] if assignment else ""

    applicable = []
    for policy in list_policies():
        if not domain_matches(cleaned_domain, policy["app_domain"]):
            continue
        if policy["scope_type"] == "machine" and policy["scope_target"] == cleaned_machine:
            applicable.append(policy)
        elif policy["scope_type"] == "group" and assigned_group and policy["scope_target"] == assigned_group:
            applicable.append(policy)
        elif policy["scope_type"] == "global":
            applicable.append(policy)

    priority = {"machine": 0, "group": 1, "global": 2}
    applicable.sort(key=lambda policy: (priority[policy["scope_type"]], -len(policy["app_domain"]), -policy["id"]))
    matched = applicable[0] if applicable else None

    return {
        "machine": cleaned_machine,
        "app_domain": cleaned_domain,
        "group_name": assigned_group,
        "assignment": assignment,
        "decision": matched["action"] if matched else "allow",
        "matched_policy": matched,
        "applicable_policies": applicable
    }

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
        'allowed_machines': ALLOWED_MACHINES,
        'default_groups': list_groups()
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

@app.route('/api/unblock-requests')
def unblock_requests():
    config_error = ensure_agent_configured()
    if config_error:
        return config_error

    try:
        status = (request.args.get('status') or 'pending').strip()
        limit = (request.args.get('limit') or '25').strip()
        target_url, machine = proxy_target(f'/api/unblock-requests?status={status}&limit={limit}')
        response = requests.get(target_url, timeout=10)
        return proxy_response_json(response, machine)
    except (requests.RequestException, ValueError) as exc:
        return jsonify({'status': 'error', 'error': str(exc)}), 502

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
        response = requests.post(target_url, timeout=10)
        return proxy_response_json(response, machine)
    except (requests.RequestException, ValueError) as exc:
        return jsonify({'status': 'error', 'error': str(exc)}), 502

@app.route('/api/unblock-requests/<int:request_id>/<decision>', methods=['POST'])
def resolve_unblock_request(request_id, decision):
    config_error = ensure_agent_configured()
    if config_error:
        return config_error

    try:
        target_url, machine = proxy_target(f'/api/unblock-requests/{request_id}/{decision}')
        response = requests.post(target_url, timeout=10)
        return proxy_response_json(response, machine)
    except (requests.RequestException, ValueError) as exc:
        return jsonify({'status': 'error', 'error': str(exc)}), 502

@app.route('/api/groups', methods=['GET', 'POST'])
def groups():
    if request.method == 'GET':
        return jsonify({'status': 'ok', 'groups': list_groups()})

    payload = request.get_json(silent=True) or {}
    try:
        group = create_group(payload.get('name'), payload.get('description', ''))
    except ValueError as exc:
        return jsonify({'status': 'error', 'error': str(exc)}), 400
    except Exception as exc:
        if 'unique' in str(exc).lower() or 'already exists' in str(exc).lower():
            return jsonify({'status': 'error', 'error': 'That group already exists'}), 409
        raise

    return jsonify({'status': 'created', 'group': group}), 201

@app.route('/api/machine-assignments', methods=['GET', 'POST'])
def machine_assignments():
    if request.method == 'GET':
        machine = request.args.get('machine') or DEFAULT_MACHINE
        assignment = get_machine_assignment(machine)
        return jsonify({'status': 'ok', 'assignment': assignment})

    payload = request.get_json(silent=True) or {}
    try:
        assignment = upsert_machine_assignment(
            payload.get('machine') or get_requested_machine(),
            group_name=payload.get('group_name', ''),
            department=payload.get('department', ''),
            user_name=payload.get('user_name', ''),
            device_label=payload.get('device_label', '')
        )
    except ValueError as exc:
        return jsonify({'status': 'error', 'error': str(exc)}), 400

    return jsonify({'status': 'saved', 'assignment': assignment})

@app.route('/api/policies', methods=['GET', 'POST'])
def policies():
    if request.method == 'GET':
        return jsonify({'status': 'ok', 'policies': list_policies()})

    payload = request.get_json(silent=True) or {}
    try:
        policy = create_policy(
            payload.get('scope_type'),
            payload.get('scope_target'),
            payload.get('app_domain'),
            payload.get('action'),
            payload.get('description', '')
        )
    except ValueError as exc:
        return jsonify({'status': 'error', 'error': str(exc)}), 400

    return jsonify({'status': 'created', 'policy': policy}), 201

@app.route('/api/policies/<int:policy_id>', methods=['DELETE'])
def remove_policy(policy_id):
    deleted = delete_policy(policy_id)
    if not deleted:
        return jsonify({'status': 'error', 'error': 'Policy not found'}), 404
    return jsonify({'status': 'deleted', 'id': policy_id})

@app.route('/api/policy-lookup')
def policy_lookup():
    machine = request.args.get('machine') or DEFAULT_MACHINE
    app_domain = request.args.get('app_domain', '')
    try:
        result = resolve_policy(machine, app_domain)
    except ValueError as exc:
        return jsonify({'status': 'error', 'error': str(exc)}), 400
    return jsonify({'status': 'ok', **result})

init_policy_store()

if __name__ == '__main__':
    print(f"Starting cloud admin on http://0.0.0.0:{ADMIN_PORT}")
    app.run(host='0.0.0.0', port=ADMIN_PORT, debug=False)
