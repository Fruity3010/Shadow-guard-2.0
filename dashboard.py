#!/usr/bin/env python3
"""
Network Activity Dashboard for Website Blocker
Real-time monitoring of all network requests and blocked domains
"""

import json
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, jsonify, request, redirect
from flask_cors import CORS
import threading
import time
from shadowguard_paths import runtime_path

app = Flask(__name__)
CORS(app)

# Database path
DB_PATH = runtime_path("activity.db")
LEGACY_DB_PATH = Path(__file__).parent / "activity.db"
PROXY_ACTIVITY_LOG = runtime_path("proxy_activity.json")
VPN_ALERTS_PATH = runtime_path("vpn_alerts.json")
LEGACY_BLOCKLIST_FILE = Path(__file__).parent / "blocklist.json"
DEFAULT_METHODS = ["GET", "POST"]
REMOTE_ADMIN_URL = os.environ.get("SHADOWGUARD_REMOTE_ADMIN_URL", "").strip()


def migrate_legacy_runtime_file(legacy_path, runtime_path_value):
    """Copy legacy runtime data into the configured base dir once."""
    if runtime_path_value.exists() or not legacy_path.exists():
        return

    runtime_path_value.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(legacy_path, runtime_path_value)
    except OSError:
        pass

def get_db_connection():
    """Create a SQLite connection with row access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_blocklist_meta():
    """Return version metadata for the machine blocklist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT version, updated_at FROM blocklist_meta WHERE id = 1')
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {'version': 0, 'updated_at': datetime.now().isoformat()}

    return {'version': int(row['version']), 'updated_at': row['updated_at']}

def save_blocklist(blocklist):
    """Replace the full machine blocklist and bump its version."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    cursor.execute('DELETE FROM block_rules')
    for rule in blocklist:
        normalized = normalize_block_rule(rule)
        cursor.execute('''
            INSERT OR REPLACE INTO block_rules (
                domain, category, methods, risk_score, reason, use_ai, added_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            normalized['domain'],
            normalized['category'],
            json.dumps(normalized['methods']),
            normalized['risk_score'],
            normalized['reason'],
            1 if normalized['use_ai'] else 0,
            normalized['added_at'],
            now
        ))

    cursor.execute('''
        UPDATE blocklist_meta
        SET version = version + 1, updated_at = ?
        WHERE id = 1
    ''', (now,))
    conn.commit()
    conn.close()

    return get_blocklist_meta()

def bump_blocklist_version(cursor):
    """Increment the blocklist version in the current transaction."""
    cursor.execute('''
        UPDATE blocklist_meta
        SET version = version + 1, updated_at = ?
        WHERE id = 1
    ''', (datetime.now().isoformat(),))

def domain_equivalents(domain):
    """Return equivalent hostname forms for matching unblock requests to rules."""
    normalized = normalize_domain(domain)
    if not normalized:
        return set()

    variants = {normalized}
    if normalized.startswith('www.'):
        variants.add(normalized[4:])
    else:
        variants.add(f'www.{normalized}')
    return {value for value in variants if value}

def domains_match_for_unblock(requested_domain, rule_domain):
    """Return True when a request domain should remove the matching block rule."""
    requested_variants = domain_equivalents(requested_domain)
    rule_variants = domain_equivalents(rule_domain)

    for requested in requested_variants:
        for rule in rule_variants:
            if requested == rule:
                return True
            if requested.endswith(f'.{rule}') or rule.endswith(f'.{requested}'):
                return True
    return False

def remove_matching_block_rules(cursor, requested_domain):
    """Remove all block rules that match the requested hostname or its variants."""
    cursor.execute('SELECT domain FROM block_rules')
    existing_domains = [row['domain'] for row in cursor.fetchall()]
    removable = [domain for domain in existing_domains if domains_match_for_unblock(requested_domain, domain)]

    for domain in removable:
        cursor.execute('DELETE FROM block_rules WHERE domain = ?', (domain,))

    return removable

def remove_block_rule(domain):
    """Remove a single block rule and bump the machine policy version."""
    normalized_domain = normalize_domain(domain)
    if not normalized_domain:
        raise ValueError('A domain is required')

    conn = get_db_connection()
    cursor = conn.cursor()
    removed_domains = remove_matching_block_rules(cursor, normalized_domain)
    changed = bool(removed_domains)
    if changed:
        bump_blocklist_version(cursor)
    conn.commit()
    conn.close()

    return {
        'domain': normalized_domain,
        'changed': changed,
        'removed_domains': removed_domains,
        'version': get_blocklist_meta()['version']
    }

def create_unblock_request(domain, reason="", requested_by="agent"):
    """Store an unblock request from a local agent or automation."""
    normalized_domain = normalize_domain(domain)
    if not normalized_domain:
        raise ValueError('A domain is required')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id FROM unblock_requests
        WHERE domain = ? AND status = 'pending'
        ORDER BY timestamp DESC
        LIMIT 1
    ''', (normalized_domain,))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return {'id': existing['id'], 'domain': normalized_domain, 'status': 'pending', 'duplicate': True}

    cursor.execute('''
        INSERT INTO unblock_requests (domain, reason, requested_by, status)
        VALUES (?, ?, ?, 'pending')
    ''', (normalized_domain, (reason or '').strip(), (requested_by or 'agent').strip() or 'agent'))
    request_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {'id': request_id, 'domain': normalized_domain, 'status': 'pending', 'duplicate': False}

def get_unblock_requests(status='pending', limit=25):
    """Return unblock requests for dashboard display."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, timestamp, domain, reason, requested_by, status, reviewed_at
        FROM unblock_requests
        WHERE status = ?
        ORDER BY timestamp DESC
        LIMIT ?
    ''', (status, limit))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def resolve_unblock_request(request_id, decision):
    """Approve or reject an unblock request."""
    if decision not in {'approved', 'rejected'}:
        raise ValueError('Decision must be approved or rejected')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, domain, status
        FROM unblock_requests
        WHERE id = ?
    ''', (request_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError('Unblock request not found')

    if row['status'] != 'pending':
        cursor.execute('''
            SELECT id, timestamp, domain, reason, requested_by, status, reviewed_at
            FROM unblock_requests
            WHERE id = ?
        ''', (request_id,))
        result = dict(cursor.fetchone())
        conn.close()
        return result

    reviewed_at = datetime.now().isoformat()
    removed_domains = []

    if decision == 'approved':
        removed_domains = remove_matching_block_rules(cursor, row['domain'])
        if removed_domains:
            bump_blocklist_version(cursor)

    cursor.execute('''
        UPDATE unblock_requests
        SET status = ?, reviewed_at = ?
        WHERE id = ?
    ''', (decision, reviewed_at, request_id))
    conn.commit()

    cursor.execute('''
        SELECT id, timestamp, domain, reason, requested_by, status, reviewed_at
        FROM unblock_requests
        WHERE id = ?
    ''', (request_id,))
    result = dict(cursor.fetchone())
    result['removed_domains'] = removed_domains
    conn.close()
    return result

def get_blocklist():
    """Return the current machine blocklist from SQLite."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT domain, category, methods, risk_score, reason, use_ai, added_at, updated_at
        FROM block_rules
        ORDER BY domain
    ''')
    rows = cursor.fetchall()
    conn.close()

    blocklist = []
    for row in rows:
        blocklist.append({
            'domain': row['domain'],
            'category': row['category'],
            'methods': json.loads(row['methods']) if row['methods'] else DEFAULT_METHODS.copy(),
            'risk_score': row['risk_score'],
            'reason': row['reason'] or '',
            'use_ai': bool(row['use_ai']),
            'added_at': row['added_at'],
            'updated_at': row['updated_at']
        })

    return blocklist

def normalize_domain(domain):
    """Normalize user-supplied domains into a matchable hostname fragment."""
    normalized = (domain or '').strip().lower()
    normalized = normalized.replace('http://', '').replace('https://', '')
    normalized = normalized.split('/')[0].strip()
    return normalized

def normalize_methods(methods):
    """Normalize blocked HTTP methods."""
    if not isinstance(methods, list):
        return DEFAULT_METHODS.copy()

    cleaned = []
    for method in methods:
        if isinstance(method, str):
            upper_method = method.strip().upper()
            if upper_method and upper_method not in cleaned:
                cleaned.append(upper_method)

    return cleaned or DEFAULT_METHODS.copy()

def normalize_block_rule(data):
    """Normalize and validate a block rule payload."""
    domain = normalize_domain(data.get('domain'))
    if not domain:
        raise ValueError('A domain is required')

    try:
        risk_score = int(data.get('risk_score', 50))
    except (TypeError, ValueError):
        risk_score = 50

    risk_score = max(1, min(risk_score, 100))

    return {
        'domain': domain,
        'category': (data.get('category') or 'custom').strip() or 'custom',
        'methods': normalize_methods(data.get('methods', DEFAULT_METHODS)),
        'risk_score': risk_score,
        'reason': (data.get('reason') or '').strip(),
        'use_ai': bool(data.get('use_ai', False)),
        'added_at': data.get('added_at') or datetime.now().isoformat()
    }

def migrate_legacy_blocklist():
    """Import existing JSON rules into SQLite the first time the agent starts."""
    if not LEGACY_BLOCKLIST_FILE.exists():
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) AS count FROM block_rules')
    existing_count = cursor.fetchone()['count']
    conn.close()

    if existing_count:
        return

    try:
        with open(LEGACY_BLOCKLIST_FILE, 'r', encoding='utf-8') as f:
            rules = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    if isinstance(rules, list) and rules:
        save_blocklist(rules)

def init_database():
    """Initialize the SQLite database for logging"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create tables if they don't exist
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            domain TEXT NOT NULL,
            path TEXT,
            method TEXT,
            status TEXT,
            blocked BOOLEAN DEFAULT 0,
            response_time REAL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blocked_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            domain TEXT NOT NULL,
            user_ip TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS block_rules (
            domain TEXT PRIMARY KEY,
            category TEXT DEFAULT 'custom',
            methods TEXT NOT NULL,
            risk_score INTEGER DEFAULT 50,
            reason TEXT DEFAULT '',
            use_ai INTEGER DEFAULT 0,
            added_at TEXT,
            updated_at TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blocklist_meta (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS unblock_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            domain TEXT NOT NULL,
            reason TEXT DEFAULT '',
            requested_by TEXT DEFAULT 'agent',
            status TEXT DEFAULT 'pending',
            reviewed_at TEXT
        )
    ''')

    cursor.execute('''
        INSERT OR IGNORE INTO blocklist_meta (id, version, updated_at)
        VALUES (1, 0, ?)
    ''', (datetime.now().isoformat(),))
    
    # Create indexes for better performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_timestamp ON requests(timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_domain ON requests(domain)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_blocked_timestamp ON blocked_attempts(timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_unblock_requests_status ON unblock_requests(status)')
    
    conn.commit()
    conn.close()
    migrate_legacy_blocklist()

def import_json_logs():
    """Import logs from the JSON file created by the proxy"""
    json_file = PROXY_ACTIVITY_LOG
    if not json_file.exists():
        return 0
    
    imported_count = 0
    try:
        with open(json_file, 'r') as f:
            logs = json.load(f)
        
        if not logs:
            return 0
        
        # Import each log with timestamp handling
        for log in logs:
            try:
                # Convert timestamp string to datetime if needed
                timestamp = log.get('timestamp')
                if timestamp and isinstance(timestamp, str):
                    # Use the timestamp from the log
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO requests (timestamp, domain, path, method, status, blocked, response_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        timestamp,
                        log.get('domain', 'unknown'),
                        log.get('path', '/'),
                        log.get('method', 'GET'),
                        log.get('status', '200'),
                        1 if log.get('blocked', False) else 0,
                        log.get('response_time', 0)
                    ))
                    
                    if log.get('blocked', False):
                        cursor.execute('''
                            INSERT INTO blocked_attempts (timestamp, domain, user_ip)
                            VALUES (?, ?, ?)
                        ''', (timestamp, log.get('domain', 'unknown'), "127.0.0.1"))
                    
                    conn.commit()
                    conn.close()
                    imported_count += 1
                else:
                    # Fall back to regular log_request if no timestamp
                    log_request(
                        domain=log.get('domain'),
                        path=log.get('path', '/'),
                        method=log.get('method', 'GET'),
                        blocked=log.get('blocked', False),
                        status=log.get('status', '200'),
                        response_time=log.get('response_time', 0)
                    )
                    imported_count += 1
            except Exception as e:
                print(f"Error importing log entry: {e}")
                continue
        
        # Clear the file after successful import
        if imported_count > 0:
            with open(json_file, 'w') as f:
                json.dump([], f)
            print(f"Imported {imported_count} log entries from JSON file")
        
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON file: {e}")
    except Exception as e:
        print(f"Error importing JSON logs: {e}")
    
    return imported_count

def log_request(domain, path="/", method="GET", blocked=False, status="200", response_time=0):
    """Log a network request to the database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO requests (domain, path, method, status, blocked, response_time)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (domain, path, method, status, blocked, response_time))
        
        if blocked:
            cursor.execute('''
                INSERT INTO blocked_attempts (domain, user_ip)
                VALUES (?, ?)
            ''', (domain, "127.0.0.1"))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error logging request: {e}")

def get_statistics():
    """Get comprehensive statistics from the database and JSON file"""
    # First, import any logs from the JSON file
    import_json_logs()
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    stats = {}
    
    # Total requests
    cursor.execute('SELECT COUNT(*) as total FROM requests')
    stats['total_requests'] = cursor.fetchone()['total']
    
    # Blocked requests
    cursor.execute('SELECT COUNT(*) as blocked FROM requests WHERE blocked = 1')
    stats['blocked_requests'] = cursor.fetchone()['blocked']
    
    # Allowed requests
    stats['allowed_requests'] = stats['total_requests'] - stats['blocked_requests']
    
    # Block rate
    stats['block_rate'] = round((stats['blocked_requests'] / max(stats['total_requests'], 1)) * 100, 2)
    
    # Top requested domains
    cursor.execute('''
        SELECT domain, COUNT(*) as count 
        FROM requests 
        WHERE blocked = 0
        GROUP BY domain 
        ORDER BY count DESC 
        LIMIT 10
    ''')
    stats['top_allowed_domains'] = [dict(row) for row in cursor.fetchall()]
    
    # Top blocked domains
    cursor.execute('''
        SELECT domain, COUNT(*) as count 
        FROM requests 
        WHERE blocked = 1
        GROUP BY domain 
        ORDER BY count DESC 
        LIMIT 10
    ''')
    stats['top_blocked_domains'] = [dict(row) for row in cursor.fetchall()]
    
    # Recent activity (last 100 requests)
    cursor.execute('''
        SELECT timestamp, domain, method, status, blocked 
        FROM requests 
        ORDER BY timestamp DESC 
        LIMIT 100
    ''')
    stats['recent_activity'] = [dict(row) for row in cursor.fetchall()]
    
    # Statistics for the last hour in 5-minute intervals
    cursor.execute('''
        SELECT 
            strftime('%Y-%m-%d %H:%M', datetime(strftime('%s', timestamp) - (strftime('%s', timestamp) % 300), 'unixepoch')) as hour,
            COUNT(*) as total,
            SUM(blocked) as blocked
        FROM requests 
        WHERE timestamp > datetime('now', '-1 hour')
        GROUP BY hour
        ORDER BY hour
    ''')
    stats['hourly_stats'] = [dict(row) for row in cursor.fetchall()]
    
    # If we have less than 3 data points, get the last 10 minutes by minute
    if len(stats['hourly_stats']) < 3:
        cursor.execute('''
            SELECT 
                strftime('%Y-%m-%d %H:%M', timestamp) as hour,
                COUNT(*) as total,
                SUM(blocked) as blocked
            FROM requests 
            WHERE timestamp > datetime('now', '-10 minutes')
            GROUP BY strftime('%Y-%m-%d %H:%M', timestamp)
            ORDER BY hour
        ''')
        minute_stats = [dict(row) for row in cursor.fetchall()]
        if len(minute_stats) > 0:
            stats['hourly_stats'] = minute_stats
    
    # Most blocked domain attempts today
    cursor.execute('''
        SELECT domain, COUNT(*) as attempts
        FROM blocked_attempts
        WHERE DATE(timestamp) = DATE('now')
        GROUP BY domain
        ORDER BY attempts DESC
        LIMIT 5
    ''')
    stats['today_most_blocked'] = [dict(row) for row in cursor.fetchall()]

    cursor.execute('''
        SELECT COUNT(*)
        FROM unblock_requests
        WHERE status = 'pending'
    ''')
    stats['pending_unblock_requests'] = cursor.fetchone()[0]
    
    conn.close()
    return stats

@app.route('/')
def dashboard():
    """Serve the main dashboard page"""
    return render_template('dashboard_v2.html', remote_admin_url=REMOTE_ADMIN_URL)

@app.route('/admin')
def admin():
    """Redirect users to the isolated cloud admin when configured."""
    if REMOTE_ADMIN_URL:
        return redirect(REMOTE_ADMIN_URL)

    return jsonify({
        'status': 'unavailable',
        'message': 'Admin is no longer hosted on the user machine. Set SHADOWGUARD_REMOTE_ADMIN_URL to the cloud admin.'
    }), 404

@app.route('/api/stats')
def api_stats():
    """API endpoint for statistics"""
    return jsonify(get_statistics())

@app.route('/api/log', methods=['POST'])
def api_log():
    """API endpoint for logging requests (called by the proxy)"""
    from flask import request
    data = request.json
    log_request(
        domain=data.get('domain'),
        path=data.get('path', '/'),
        method=data.get('method', 'GET'),
        blocked=data.get('blocked', False),
        status=data.get('status', '200'),
        response_time=data.get('response_time', 0)
    )
    return jsonify({'status': 'logged'})

@app.route('/api/clear', methods=['POST'])
def api_clear():
    """Clear all statistics"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM requests')
    cursor.execute('DELETE FROM blocked_attempts')
    conn.commit()
    conn.close()
    return jsonify({'status': 'cleared'})

def get_agent_stats_payload():
    """Build machine-agent stats for the remote admin."""
    blocklist = get_blocklist()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM requests
        WHERE DATE(timestamp) = DATE('now')
    ''')
    requests_today = cursor.fetchone()[0]
    cursor.execute('''
        SELECT COUNT(*) FROM unblock_requests
        WHERE status = 'pending'
    ''')
    pending_unblock_requests = cursor.fetchone()[0]
    conn.close()

    return {
        'total_blocked': len([b for b in blocklist if b.get('domain')]),
        'active_rules': len(blocklist),
        'ai_enabled': any(b.get('use_ai') for b in blocklist),
        'requests_today': requests_today,
        'blocklist_version': get_blocklist_meta()['version'],
        'machine_name': os.environ.get('COMPUTERNAME') or os.environ.get('HOSTNAME') or 'unknown-machine',
        'pending_unblock_requests': pending_unblock_requests
    }

@app.route('/api/unblock-requests', methods=['GET', 'POST'])
def api_unblock_requests():
    """Create or list emergency unblock requests for the local dashboard."""
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        try:
            result = create_unblock_request(
                data.get('domain'),
                reason=data.get('reason', ''),
                requested_by=data.get('requested_by', 'user')
            )
        except ValueError as exc:
            return jsonify({'status': 'error', 'error': str(exc)}), 400

        return jsonify({
            'status': 'queued',
            'request': result
        }), 201 if not result.get('duplicate') else 200

    status = (request.args.get('status') or 'pending').strip().lower()
    try:
        limit = int(request.args.get('limit', 25))
    except (TypeError, ValueError):
        limit = 25
    limit = max(1, min(limit, 100))

    if status not in {'pending', 'approved', 'rejected'}:
        return jsonify({'status': 'error', 'error': 'Invalid status'}), 400

    return jsonify({
        'status': 'ok',
        'requests': get_unblock_requests(status=status, limit=limit)
    })

@app.route('/api/unblock-requests/<int:request_id>/<decision>', methods=['POST'])
def api_resolve_unblock_request(request_id, decision):
    """Approve or reject an emergency unblock request from the dashboard."""
    normalized_decision = (decision or '').strip().lower()
    if normalized_decision not in {'approve', 'reject'}:
        return jsonify({'status': 'error', 'error': 'Decision must be approve or reject'}), 400

    try:
        result = resolve_unblock_request(
            request_id,
            'approved' if normalized_decision == 'approve' else 'rejected'
        )
    except ValueError as exc:
        return jsonify({'status': 'error', 'error': str(exc)}), 404

    return jsonify({
        'status': result['status'],
        'request': result,
        'version': get_blocklist_meta()['version']
    })

# Machine agent endpoints used by the local blocker and remote admin
@app.route('/agent/blocked-sites')
def agent_get_blocked_sites():
    """Return the current blocklist for the local machine."""
    return jsonify(get_blocklist())

@app.route('/agent/blocklist-version')
def agent_get_blocklist_version():
    """Expose a lightweight version marker for the local machine blocklist."""
    return jsonify(get_blocklist_meta())

@app.route('/agent/block-site', methods=['POST'])
def agent_block_site():
    """Add a site to the machine blocklist."""
    data = request.get_json(silent=True) or {}

    try:
        new_block = normalize_block_rule(data)
    except ValueError as exc:
        return jsonify({'status': 'error', 'error': str(exc)}), 400

    blocklist = [b for b in get_blocklist() if b.get('domain') != new_block['domain']]
    blocklist.append(new_block)
    meta = save_blocklist(blocklist)

    return jsonify({
        'status': 'blocked',
        'domain': new_block['domain'],
        'version': meta['version']
    })

@app.route('/agent/unblock-site', methods=['POST'])
def agent_unblock_site():
    """Remove a site from the machine blocklist."""
    data = request.get_json(silent=True) or {}
    domain = normalize_domain(data.get('domain'))
    if not domain:
        return jsonify({'status': 'error', 'error': 'A domain is required'}), 400

    blocklist = [b for b in get_blocklist() if b.get('domain') != domain]
    meta = save_blocklist(blocklist)

    return jsonify({
        'status': 'unblocked',
        'domain': domain,
        'version': meta['version']
    })

@app.route('/agent/request-unblock', methods=['POST'])
def agent_request_unblock():
    """Allow the local agent to ask for an emergency unblock review."""
    data = request.get_json(silent=True) or {}

    try:
        result = create_unblock_request(
            data.get('domain'),
            reason=data.get('reason', ''),
            requested_by=data.get('requested_by', 'agent')
        )
    except ValueError as exc:
        return jsonify({'status': 'error', 'error': str(exc)}), 400

    return jsonify({
        'status': 'queued',
        'request': result
    }), 201 if not result.get('duplicate') else 200

@app.route('/agent/clear-all-blocks', methods=['POST'])
def agent_clear_all_blocks():
    """Clear all blocking rules on the local machine."""
    meta = save_blocklist([])
    return jsonify({'status': 'cleared', 'version': meta['version']})

@app.route('/agent/admin-stats')
def agent_admin_stats():
    """Get local machine statistics for the remote admin."""
    return jsonify(get_agent_stats_payload())

# VPN Detection API endpoints
@app.route('/api/vpn-status')
def vpn_status():
    """Get current VPN detection status"""
    from vpn_detector import VPNDetector

    try:
        detector = VPNDetector()
        result = detector.comprehensive_check()
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'error': str(e),
            'vpn_detected': False,
            'confidence_score': 0
        })

@app.route('/api/vpn-history')
def vpn_history():
    """Get VPN detection history from database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM vpn_detections
            ORDER BY timestamp DESC
            LIMIT 50
        ''')

        history = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return jsonify(history)
    except Exception as e:
        return jsonify({'error': str(e), 'history': []})

@app.route('/api/vpn-alerts')
def vpn_alerts():
    """Get VPN alerts"""
    if VPN_ALERTS_PATH.exists():
        try:
            with open(VPN_ALERTS_PATH, 'r') as f:
                alerts = json.load(f)
            return jsonify(alerts)
        except Exception as e:
            return jsonify({'error': str(e), 'alerts': []})

    return jsonify([])

@app.route('/api/vpn-add-to-blocklist', methods=['POST'])
def vpn_add_to_blocklist():
    """Add VPN provider domains to blocklist"""
    from vpn_detector import VPNDetector

    try:
        detector = VPNDetector()
        vpn_blocklist = detector.get_vpn_provider_blocklist()

        # Load existing blocklist
        blocklist = get_blocklist()

        # Get existing domains
        existing_domains = {b['domain'] for b in blocklist}

        # Add VPN domains that aren't already in the list
        added_count = 0
        for vpn_entry in vpn_blocklist:
            if vpn_entry['domain'] not in existing_domains:
                blocklist.append(vpn_entry)
                added_count += 1

        meta = save_blocklist(blocklist)

        return jsonify({
            'status': 'success',
            'added': added_count,
            'total_vpn_domains': len(vpn_blocklist),
            'version': meta['version']
        })

    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)})

@app.route('/api/vpn-stats')
def vpn_stats():
    """Get VPN detection statistics"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Total VPN detections
        cursor.execute('SELECT COUNT(*) FROM vpn_detections WHERE vpn_detected = 1')
        total_row = cursor.fetchone()
        total_detections = total_row[0] if total_row else 0

        # Today's detections
        cursor.execute('''
            SELECT COUNT(*) FROM vpn_detections
            WHERE vpn_detected = 1 AND DATE(timestamp) = DATE('now')
        ''')
        today_row = cursor.fetchone()
        today_detections = today_row[0] if today_row else 0

        # Last detection time
        cursor.execute('''
            SELECT timestamp FROM vpn_detections
            WHERE vpn_detected = 1
            ORDER BY timestamp DESC
            LIMIT 1
        ''')
        last_detection = cursor.fetchone()
        last_detection_time = last_detection[0] if last_detection else None

        # Current status (from latest check)
        cursor.execute('''
            SELECT vpn_detected, confidence_score FROM vpn_detections
            ORDER BY timestamp DESC
            LIMIT 1
        ''')
        current = cursor.fetchone()
        current_status = {
            'vpn_active': bool(current[0]) if current else False,
            'confidence': current[1] if current else 0
        } if current else {'vpn_active': False, 'confidence': 0}

        conn.close()

        return jsonify({
            'total_detections': total_detections,
            'today_detections': today_detections,
            'last_detection_time': last_detection_time,
            'current_status': current_status
        })

    except Exception as e:
        return jsonify({
            'error': str(e),
            'total_detections': 0,
            'today_detections': 0,
            'current_status': {'vpn_active': False, 'confidence': 0}
        })

def cleanup_old_data():
    """Clean up data older than 7 days"""
    while True:
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM requests 
                WHERE timestamp < datetime('now', '-7 days')
            ''')
            cursor.execute('''
                DELETE FROM blocked_attempts 
                WHERE timestamp < datetime('now', '-7 days')
            ''')
            conn.commit()
            conn.close()
            print("Cleaned up old data")
        except Exception as e:
            print(f"Error cleaning up data: {e}")
        
        # Run cleanup once per day
        time.sleep(86400)

migrate_legacy_runtime_file(LEGACY_DB_PATH, DB_PATH)
init_database()
get_blocklist_meta()

if __name__ == '__main__':
    # Start cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_old_data, daemon=True)
    cleanup_thread.start()
    
    # Run the dashboard
    print("Starting dashboard on http://localhost:5555")
    app.run(host='0.0.0.0', port=5555, debug=False)
