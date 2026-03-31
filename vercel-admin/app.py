#!/usr/bin/env python3
"""
Standalone Vercel-ready ShadowGuard cloud admin.
Deploy this folder to Vercel with the project root set to vercel-admin/.
"""

import json
import os
import sqlite3
import hashlib
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
        def _request(method, url, json_body=None, timeout=10, headers=None):
            data = None
            request_headers = dict(headers or {})

            if json_body is not None:
                data = json.dumps(json_body).encode("utf-8")
                request_headers["Content-Type"] = "application/json"

            request_obj = urllib_request.Request(
                url, data=data, headers=request_headers, method=method
            )

            try:
                with urllib_request.urlopen(request_obj, timeout=timeout) as response:
                    return _FallbackResponse(
                        response.read(), response.getcode(), response.info()
                    )
            except urllib_error.HTTPError as exc:
                return _FallbackResponse(exc.read(), exc.code, exc.headers)
            except urllib_error.URLError as exc:
                raise _FallbackRequestException(str(exc.reason)) from exc

        def get(self, url, timeout=10, headers=None):
            return self._request("GET", url, timeout=timeout, headers=headers)

        def post(self, url, json=None, timeout=10, headers=None):
            return self._request("POST", url, json_body=json, timeout=timeout, headers=headers)

    requests = _RequestsFallback()


def load_local_env():
    """Load a local .env file for development without requiring python-dotenv."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_local_env()

from flask import Flask, render_template, jsonify, request, redirect, session, url_for
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
_configured_secret = (
    os.environ.get("SHADOWGUARD_ADMIN_SESSION_SECRET")
    or os.environ.get("FLASK_SECRET_KEY")
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("VERCEL") == "1"
    or os.environ.get("SHADOWGUARD_SESSION_COOKIE_SECURE", "").strip().lower()
    in {"1", "true", "yes", "on"}
)
RUNNING_ON_VERCEL = os.environ.get("VERCEL") == "1"

AGENT_BASE_URL = os.environ.get("SHADOWGUARD_TARGET_AGENT_URL", "").rstrip("/")
AGENT_URL_TEMPLATE = os.environ.get("SHADOWGUARD_TARGET_AGENT_URL_TEMPLATE", "").strip()
ADMIN_PORT = int(
    os.environ.get("PORT", os.environ.get("SHADOWGUARD_ADMIN_PORT", "8000"))
)
DEFAULT_MACHINE = os.environ.get("SHADOWGUARD_DEFAULT_MACHINE", "").strip()
ALLOWED_MACHINES = [
    m.strip()
    for m in os.environ.get("SHADOWGUARD_ALLOWED_MACHINES", "").split(",")
    if m.strip()
]
POLICY_DB_PATH = (
    Path(os.environ.get("SHADOWGUARD_POLICY_DB_PATH", "")).expanduser().resolve()
    if os.environ.get("SHADOWGUARD_POLICY_DB_PATH")
    else Path(os.environ.get("TMPDIR", "/tmp")) / "policy_store.db"
)
try:
    POLICY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except Exception:
    POLICY_DB_PATH = Path("/tmp") / "policy_store.db"
DEFAULT_GROUPS = [
    ("HR", "Human Resources"),
    ("Finance", "Finance and accounting"),
    ("IT", "Internal technology team"),
]
SUPABASE_URL = (
    os.environ.get("SUPABASE_URL")
    or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    or ""
).rstrip("/")
SUPABASE_ANON_KEY = (
    os.environ.get("SUPABASE_ANON_KEY")
    or os.environ.get("SUPABASE_PUBLISHABLE_KEY")
    or os.environ.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
    or os.environ.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY")
    or os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    or ""
).strip()
SUPABASE_ALLOWED_EMAILS = {
    email.strip().lower()
    for email in os.environ.get("SHADOWGUARD_SUPABASE_ALLOWED_EMAILS", "").split(",")
    if email.strip()
}
SUPABASE_ALLOWED_DOMAIN = os.environ.get("SHADOWGUARD_SUPABASE_ALLOWED_DOMAIN", "").strip().lower()
app.secret_key = _configured_secret or hashlib.sha256(
    f"shadowguard-admin:{SUPABASE_URL}:{SUPABASE_ANON_KEY}:session".encode("utf-8")
).hexdigest()


def auth_enabled():
    """Return True when login protection is configured."""
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)


def auth_required():
    """Return True when this environment must not expose the admin publicly."""
    return RUNNING_ON_VERCEL or os.environ.get("SHADOWGUARD_REQUIRE_AUTH", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def auth_config_error_response():
    """Return a clear error when auth is required but not configured."""
    message = (
        "Supabase auth is required but not configured. Set SUPABASE_URL and a publishable key "
        "(SUPABASE_PUBLISHABLE_KEY or another supported fallback) in the deployment environment."
    )
    if request.path.startswith("/api/"):
        return jsonify({"status": "error", "error": message}), 503
    return (
        render_template(
            "login.html",
            auth_enabled=False,
            next_path=url_for("admin"),
            allowed_domain=SUPABASE_ALLOWED_DOMAIN,
            allowed_emails=sorted(SUPABASE_ALLOWED_EMAILS),
            error_message=message,
        ),
        503,
    )


def is_authenticated():
    """Return True when the current session is logged in."""
    return not auth_enabled() or bool(session.get("authenticated"))


def login_required_response():
    """Return an auth challenge appropriate for browser or API clients."""
    if request.path.startswith("/api/"):
        return jsonify({"status": "error", "error": "Authentication required"}), 401

    next_path = request.full_path if request.query_string else request.path
    return redirect(url_for("login", next=next_path))


def normalize_next_path(value):
    """Allow redirects only to local in-app paths."""
    candidate = (value or "").strip()
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return url_for("admin")


def supabase_headers(access_token=""):
    """Build headers for Supabase Auth API requests."""
    headers = {
        "apikey": SUPABASE_ANON_KEY,
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def is_email_allowed(email):
    """Return True when the Supabase user is allowed to access the admin."""
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return False

    if SUPABASE_ALLOWED_EMAILS and normalized_email not in SUPABASE_ALLOWED_EMAILS:
        return False

    if SUPABASE_ALLOWED_DOMAIN and not normalized_email.endswith(f"@{SUPABASE_ALLOWED_DOMAIN}"):
        return False

    return True


def supabase_sign_in(email, password):
    """Authenticate a user against Supabase Auth."""
    if not auth_enabled():
        raise ValueError("Supabase auth is not configured")

    response = requests.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        json={"email": email, "password": password},
        headers=supabase_headers(),
        timeout=10,
    )
    payload = response.json()

    if response.status_code >= 400:
        message = payload.get("msg") or payload.get("error_description") or payload.get("error") or "Supabase sign-in failed"
        raise ValueError(message)

    user = payload.get("user") or {}
    user_email = (user.get("email") or email or "").strip().lower()
    if not is_email_allowed(user_email):
        raise PermissionError("This Supabase user is not allowed to access the admin")

    return {
        "email": user_email,
        "access_token": payload.get("access_token", ""),
        "refresh_token": payload.get("refresh_token", ""),
    }


@app.before_request
def require_login():
    """Protect the admin app with a session login when configured."""
    if auth_required() and not auth_enabled():
        allowed_paths = {"/login"}
        if request.path in allowed_paths or request.path.startswith("/static/"):
            return auth_config_error_response()
        return auth_config_error_response()

    if not auth_enabled():
        return None

    allowed_paths = {"/login"}
    if request.path in allowed_paths or request.path.startswith("/static/"):
        return None

    if is_authenticated():
        return None

    return login_required_response()


def utcnow_iso():
    """Return a compact UTC timestamp for policy records."""
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def get_policy_connection():
    """Create a SQLite connection for the cloud policy store."""
    conn = sqlite3.connect(POLICY_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_policy_store():
    """Initialize local policy storage for groups, assignments, and rules."""
    conn = get_policy_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS groups (
            name TEXT PRIMARY KEY,
            description TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS machine_assignments (
            machine_name TEXT PRIMARY KEY,
            group_name TEXT,
            department TEXT DEFAULT '',
            user_name TEXT DEFAULT '',
            device_label TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        )
    """
    )
    cursor.execute(
        """
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
    """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_policies_scope ON policies(scope_type, scope_target)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_policies_domain ON policies(app_domain)"
    )
    for name, description in DEFAULT_GROUPS:
        cursor.execute(
            "INSERT OR IGNORE INTO groups (name, description, created_at) VALUES (?, ?, ?)",
            (name, description, utcnow_iso()),
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
    conn = get_policy_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, description, created_at FROM groups ORDER BY name")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def create_group(name, description=""):
    """Create a new access group."""
    cleaned_name = (name or "").strip()
    if not cleaned_name:
        raise ValueError("Group name is required")

    conn = get_policy_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO groups (name, description, created_at) VALUES (?, ?, ?)",
        (cleaned_name, (description or "").strip(), utcnow_iso()),
    )
    conn.commit()
    conn.close()
    return {"name": cleaned_name, "description": (description or "").strip()}


def get_machine_assignment(machine_name):
    """Return the current assignment for a machine, if present."""
    cleaned_machine = (machine_name or "").strip()
    if not cleaned_machine:
        return None

    conn = get_policy_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT machine_name, group_name, department, user_name, device_label, updated_at
        FROM machine_assignments
        WHERE machine_name = ?
    """,
        (cleaned_machine,),
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_machine_assignment(
    machine_name, group_name="", department="", user_name="", device_label=""
):
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
        utcnow_iso(),
    )

    conn = get_policy_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO machine_assignments (
            machine_name, group_name, department, user_name, device_label, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(machine_name) DO UPDATE SET
            group_name = excluded.group_name,
            department = excluded.department,
            user_name = excluded.user_name,
            device_label = excluded.device_label,
            updated_at = excluded.updated_at
    """,
        payload,
    )
    conn.commit()
    conn.close()
    return get_machine_assignment(cleaned_machine)


def list_policies():
    """Return configured app access policies."""
    conn = get_policy_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, scope_type, scope_target, app_domain, action, description, created_at, updated_at
        FROM policies
        ORDER BY scope_type, scope_target, app_domain, id DESC
    """
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


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
    conn = get_policy_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO policies (scope_type, scope_target, app_domain, action, description, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (
            cleaned_scope_type,
            cleaned_target,
            cleaned_domain,
            cleaned_action,
            (description or "").strip(),
            now,
            now,
        ),
    )
    policy_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return next(policy for policy in list_policies() if policy["id"] == policy_id)


def delete_policy(policy_id):
    """Delete a policy rule."""
    conn = get_policy_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM policies WHERE id = ?", (policy_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
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
        if (
            policy["scope_type"] == "machine"
            and policy["scope_target"] == cleaned_machine
        ):
            applicable.append(policy)
        elif (
            policy["scope_type"] == "group"
            and assigned_group
            and policy["scope_target"] == assigned_group
        ):
            applicable.append(policy)
        elif policy["scope_type"] == "global":
            applicable.append(policy)

    priority = {"machine": 0, "group": 1, "global": 2}
    applicable.sort(
        key=lambda policy: (
            priority[policy["scope_type"]],
            -len(policy["app_domain"]),
            -policy["id"],
        )
    )
    matched = applicable[0] if applicable else None

    return {
        "machine": cleaned_machine,
        "app_domain": cleaned_domain,
        "group_name": assigned_group,
        "assignment": assignment,
        "decision": matched["action"] if matched else "allow",
        "matched_policy": matched,
        "applicable_policies": applicable,
    }


def get_requested_machine():
    """Resolve the machine identifier from query string, body, or default config."""
    body = request.get_json(silent=True) or {}
    machine = request.args.get("machine") or body.get("machine") or DEFAULT_MACHINE
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
        raise ValueError(
            "A machine value is required when SHADOWGUARD_TARGET_AGENT_URL_TEMPLATE is used"
        )

    raise ValueError("No machine agent URL is configured")


def ensure_agent_configured():
    """Return a JSON error response when the target machine agent is missing."""
    if not (AGENT_BASE_URL or AGENT_URL_TEMPLATE):
        return (
            jsonify(
                {
                    "status": "error",
                    "error": "Set SHADOWGUARD_TARGET_AGENT_URL or SHADOWGUARD_TARGET_AGENT_URL_TEMPLATE for the cloud admin.",
                }
            ),
            500,
        )
    return None


def proxy_target(path):
    """Build the proxied target URL and machine label."""
    base_url, machine = resolve_agent_base_url()
    return f"{base_url}{path}", machine or base_url


def proxy_response_json(response, machine):
    """Normalize proxied JSON and include the resolved machine."""
    payload = response.json()
    if isinstance(payload, dict):
        payload.setdefault("machine", machine)
    return jsonify(payload), response.status_code


def request_payload():
    """Return the request payload without the local-only machine selector."""
    payload = request.get_json(silent=True) or {}
    if isinstance(payload, dict):
        payload.pop("machine", None)
    return payload


def template_context():
    """Build shared template context for the admin UI."""
    return {
        "agent_base_url": AGENT_BASE_URL,
        "agent_url_template": AGENT_URL_TEMPLATE,
        "default_machine": DEFAULT_MACHINE,
        "allowed_machines": ALLOWED_MACHINES,
        "default_groups": list_groups(),
        "auth_enabled": auth_enabled(),
        "admin_email": session.get("admin_email", ""),
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
        return jsonify({"status": "error", "error": str(exc)}), 502


@app.route("/")
@app.route("/admin")
def admin():
    """Serve the isolated admin panel."""
    return render_template("admin.html", **template_context())


@app.route("/login", methods=["GET", "POST"])
def login():
    """Show and process the admin login form."""
    if auth_required() and not auth_enabled():
        return auth_config_error_response()

    if not auth_enabled():
        return redirect(url_for("admin"))

    error_message = ""
    next_path = normalize_next_path(request.values.get("next"))

    if request.method == "POST":
        submitted_email = (request.form.get("email") or "").strip().lower()
        submitted_password = request.form.get("password") or ""

        try:
            auth_result = supabase_sign_in(submitted_email, submitted_password)
            session.clear()
            session["authenticated"] = True
            session["admin_email"] = auth_result["email"]
            session["supabase_access_token"] = auth_result["access_token"]
            session["supabase_refresh_token"] = auth_result["refresh_token"]
            return redirect(next_path)
        except PermissionError as exc:
            error_message = str(exc)
        except (ValueError, requests.RequestException) as exc:
            error_message = str(exc) or "Supabase sign-in failed"

    return render_template(
        "login.html",
        auth_enabled=True,
        next_path=next_path,
        allowed_domain=SUPABASE_ALLOWED_DOMAIN,
        allowed_emails=sorted(SUPABASE_ALLOWED_EMAILS),
        error_message=error_message,
    )


@app.route("/logout", methods=["POST"])
def logout():
    """Sign the current user out of the admin app."""
    session.clear()
    return redirect(url_for("login") if auth_enabled() else url_for("admin"))


@app.route("/api/blocked-sites")
def blocked_sites():
    return proxy_get("/agent/blocked-sites")


@app.route("/api/admin-stats")
def admin_stats():
    return proxy_get("/agent/admin-stats")


@app.route("/api/unblock-requests")
def unblock_requests():
    config_error = ensure_agent_configured()
    if config_error:
        return config_error

    try:
        status = (request.args.get("status") or "pending").strip()
        limit = (request.args.get("limit") or "25").strip()
        target_url, machine = proxy_target(
            f"/api/unblock-requests?status={status}&limit={limit}"
        )
        response = requests.get(target_url, timeout=10)
        return proxy_response_json(response, machine)
    except (requests.RequestException, ValueError) as exc:
        return jsonify({"status": "error", "error": str(exc)}), 502


@app.route("/api/blocklist-version")
def blocklist_version():
    return proxy_get("/agent/blocklist-version")


@app.route("/api/block-site", methods=["POST"])
def block_site():
    config_error = ensure_agent_configured()
    if config_error:
        return config_error

    try:
        target_url, machine = proxy_target("/agent/block-site")
        response = requests.post(target_url, json=request_payload(), timeout=10)
        return proxy_response_json(response, machine)
    except (requests.RequestException, ValueError) as exc:
        return jsonify({"status": "error", "error": str(exc)}), 502


@app.route("/api/unblock-site", methods=["POST"])
def unblock_site():
    config_error = ensure_agent_configured()
    if config_error:
        return config_error

    try:
        target_url, machine = proxy_target("/agent/unblock-site")
        response = requests.post(target_url, json=request_payload(), timeout=10)
        return proxy_response_json(response, machine)
    except (requests.RequestException, ValueError) as exc:
        return jsonify({"status": "error", "error": str(exc)}), 502


@app.route("/api/clear-all-blocks", methods=["POST"])
def clear_all_blocks():
    config_error = ensure_agent_configured()
    if config_error:
        return config_error

    try:
        target_url, machine = proxy_target("/agent/clear-all-blocks")
        response = requests.post(target_url, timeout=10)
        return proxy_response_json(response, machine)
    except (requests.RequestException, ValueError) as exc:
        return jsonify({"status": "error", "error": str(exc)}), 502


@app.route("/api/unblock-requests/<int:request_id>/<decision>", methods=["POST"])
def resolve_unblock_request(request_id, decision):
    config_error = ensure_agent_configured()
    if config_error:
        return config_error

    try:
        target_url, machine = proxy_target(
            f"/api/unblock-requests/{request_id}/{decision}"
        )
        response = requests.post(target_url, timeout=10)
        return proxy_response_json(response, machine)
    except (requests.RequestException, ValueError) as exc:
        return jsonify({"status": "error", "error": str(exc)}), 502


@app.route("/api/groups", methods=["GET", "POST"])
def groups():
    if request.method == "GET":
        return jsonify({"status": "ok", "groups": list_groups()})

    payload = request.get_json(silent=True) or {}
    try:
        group = create_group(payload.get("name"), payload.get("description", ""))
    except ValueError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400
    except Exception as exc:
        if "unique" in str(exc).lower() or "already exists" in str(exc).lower():
            return (
                jsonify({"status": "error", "error": "That group already exists"}),
                409,
            )
        raise

    return jsonify({"status": "created", "group": group}), 201


@app.route("/api/machine-assignments", methods=["GET", "POST"])
def machine_assignments():
    if request.method == "GET":
        machine = request.args.get("machine") or DEFAULT_MACHINE
        assignment = get_machine_assignment(machine)
        return jsonify({"status": "ok", "assignment": assignment})

    payload = request.get_json(silent=True) or {}
    try:
        assignment = upsert_machine_assignment(
            payload.get("machine") or get_requested_machine(),
            group_name=payload.get("group_name", ""),
            department=payload.get("department", ""),
            user_name=payload.get("user_name", ""),
            device_label=payload.get("device_label", ""),
        )
    except ValueError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400

    return jsonify({"status": "saved", "assignment": assignment})


@app.route("/api/policies", methods=["GET", "POST"])
def policies():
    if request.method == "GET":
        return jsonify({"status": "ok", "policies": list_policies()})

    payload = request.get_json(silent=True) or {}
    try:
        policy = create_policy(
            payload.get("scope_type"),
            payload.get("scope_target"),
            payload.get("app_domain"),
            payload.get("action"),
            payload.get("description", ""),
        )
    except ValueError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400

    return jsonify({"status": "created", "policy": policy}), 201


@app.route("/api/policies/<int:policy_id>", methods=["DELETE"])
def remove_policy(policy_id):
    deleted = delete_policy(policy_id)
    if not deleted:
        return jsonify({"status": "error", "error": "Policy not found"}), 404
    return jsonify({"status": "deleted", "id": policy_id})


@app.route("/api/policy-lookup")
def policy_lookup():
    machine = request.args.get("machine") or DEFAULT_MACHINE
    app_domain = request.args.get("app_domain", "")
    try:
        result = resolve_policy(machine, app_domain)
    except ValueError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400
    return jsonify({"status": "ok", **result})


init_policy_store()

if __name__ == "__main__":
    print(f"Starting cloud admin on http://0.0.0.0:{ADMIN_PORT}")
    app.run(host="0.0.0.0", port=ADMIN_PORT, debug=False)
