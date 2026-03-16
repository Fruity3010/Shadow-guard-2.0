#!/usr/bin/env python3
"""
Network Activity Dashboard for Website Blocker
Real-time monitoring of all network requests and blocked domains
"""

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, jsonify
from flask_cors import CORS
import threading
import time

app = Flask(__name__)
CORS(app)

# Database path
DB_PATH = Path(__file__).parent / "activity.db"

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
    
    # Create indexes for better performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_timestamp ON requests(timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_domain ON requests(domain)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_blocked_timestamp ON blocked_attempts(timestamp)')
    
    conn.commit()
    conn.close()

def import_json_logs():
    """Import logs from the JSON file created by the proxy"""
    json_file = Path(tempfile.gettempdir()) / "proxy_activity.json"
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
    
    conn.close()
    return stats

@app.route('/')
def dashboard():
    """Serve the main dashboard page"""
    # Use the enhanced dashboard v2
    return render_template('dashboard_v2.html')

@app.route('/admin')
def admin():
    """Serve the admin control panel"""
    return render_template('admin.html')

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

# Admin API endpoints
@app.route('/api/blocked-sites')
def get_blocked_sites():
    """Get list of currently blocked sites"""
    blocklist_file = Path(__file__).parent / 'blocklist.json'
    if blocklist_file.exists():
        with open(blocklist_file, 'r') as f:
            return jsonify(json.load(f))
    return jsonify([])

@app.route('/api/block-site', methods=['POST'])
def block_site():
    """Add a site to the blocklist"""
    from flask import request
    data = request.json
    blocklist_file = Path(__file__).parent / 'blocklist.json'
    
    # Load existing blocklist
    if blocklist_file.exists():
        with open(blocklist_file, 'r') as f:
            blocklist = json.load(f)
    else:
        blocklist = []
    
    # Add new site
    new_block = {
        'domain': data.get('domain'),
        'category': data.get('category', 'custom'),
        'methods': data.get('methods', ['GET', 'POST']),
        'risk_score': data.get('risk_score', 50),
        'reason': data.get('reason', ''),
        'use_ai': data.get('use_ai', False),
        'added_at': datetime.now().isoformat()
    }
    
    # Remove duplicates
    blocklist = [b for b in blocklist if b['domain'] != new_block['domain']]
    blocklist.append(new_block)
    
    # Save blocklist
    with open(blocklist_file, 'w') as f:
        json.dump(blocklist, f, indent=2)
    
    return jsonify({'status': 'blocked', 'domain': new_block['domain']})

@app.route('/api/unblock-site', methods=['POST'])
def unblock_site():
    """Remove a site from the blocklist"""
    from flask import request
    data = request.json
    domain = data.get('domain')
    blocklist_file = Path(__file__).parent / 'blocklist.json'
    
    if blocklist_file.exists():
        with open(blocklist_file, 'r') as f:
            blocklist = json.load(f)
        
        blocklist = [b for b in blocklist if b['domain'] != domain]
        
        with open(blocklist_file, 'w') as f:
            json.dump(blocklist, f, indent=2)
    
    return jsonify({'status': 'unblocked', 'domain': domain})

@app.route('/api/clear-all-blocks', methods=['POST'])
def clear_all_blocks():
    """Clear all blocking rules"""
    blocklist_file = Path(__file__).parent / 'blocklist.json'
    with open(blocklist_file, 'w') as f:
        json.dump([], f)
    return jsonify({'status': 'cleared'})

@app.route('/api/admin-stats')
def admin_stats():
    """Get admin panel statistics"""
    blocklist_file = Path(__file__).parent / 'blocklist.json'
    blocklist = []
    if blocklist_file.exists():
        with open(blocklist_file, 'r') as f:
            blocklist = json.load(f)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get today's request count
    cursor.execute('''
        SELECT COUNT(*) FROM requests 
        WHERE DATE(timestamp) = DATE('now')
    ''')
    requests_today = cursor.fetchone()[0]
    
    conn.close()
    
    return jsonify({
        'total_blocked': len([b for b in blocklist if b.get('domain')]),
        'active_rules': len(blocklist),
        'ai_enabled': any(b.get('use_ai') for b in blocklist),
        'requests_today': requests_today
    })

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
    alerts_file = Path(__file__).parent / 'vpn_alerts.json'

    if alerts_file.exists():
        try:
            with open(alerts_file, 'r') as f:
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
        blocklist_file = Path(__file__).parent / 'blocklist.json'
        if blocklist_file.exists():
            with open(blocklist_file, 'r') as f:
                blocklist = json.load(f)
        else:
            blocklist = []

        # Get existing domains
        existing_domains = {b['domain'] for b in blocklist}

        # Add VPN domains that aren't already in the list
        added_count = 0
        for vpn_entry in vpn_blocklist:
            if vpn_entry['domain'] not in existing_domains:
                blocklist.append(vpn_entry)
                added_count += 1

        # Save updated blocklist
        with open(blocklist_file, 'w') as f:
            json.dump(blocklist, f, indent=2)

        return jsonify({
            'status': 'success',
            'added': added_count,
            'total_vpn_domains': len(vpn_blocklist)
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
        total_detections = cursor.fetchone()[0] if cursor.fetchone() else 0

        # Today's detections
        cursor.execute('''
            SELECT COUNT(*) FROM vpn_detections
            WHERE vpn_detected = 1 AND DATE(timestamp) = DATE('now')
        ''')
        today_detections = cursor.fetchone()[0] if cursor.fetchone() else 0

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

if __name__ == '__main__':
    # Initialize database
    init_database()
    
    # Start cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_old_data, daemon=True)
    cleanup_thread.start()
    
    # Run the dashboard
    print("🚀 Starting dashboard on http://localhost:5555")
    app.run(host='0.0.0.0', port=5555, debug=True)