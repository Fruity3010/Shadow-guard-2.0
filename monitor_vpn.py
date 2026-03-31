#!/usr/bin/env python3
"""
Background VPN Monitoring Service
Continuously monitors for VPN usage and logs to dashboard
"""

import time
import sys
import signal
from datetime import datetime
from vpn_detector import VPNDetector
import sqlite3
import json
from shadowguard_paths import runtime_path

# Configuration
CHECK_INTERVAL = 60  # Check every 60 seconds
DB_PATH = runtime_path("activity.db")
VPN_LOG_PATH = runtime_path("vpn_alerts.json")

class VPNMonitor:
    def __init__(self):
        self.detector = VPNDetector()
        self.running = True
        self.alert_cooldown = {}  # Prevent spam alerts

    def log_to_database(self, detection_result):
        """Log VPN detection to the main database"""
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()

            # Create VPN detections table if it doesn't exist
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS vpn_detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    vpn_detected BOOLEAN,
                    confidence_score INTEGER,
                    interfaces TEXT,
                    processes TEXT,
                    routing_info TEXT,
                    dns_servers TEXT
                )
            ''')

            # Insert detection
            cursor.execute('''
                INSERT INTO vpn_detections
                (vpn_detected, confidence_score, interfaces, processes, routing_info, dns_servers)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                detection_result['vpn_detected'],
                detection_result['confidence_score'],
                json.dumps(detection_result['checks']['network_interfaces']['interfaces']),
                json.dumps(detection_result['checks']['processes']['processes']),
                detection_result['checks']['routing']['info'],
                json.dumps(detection_result['checks']['dns']['servers'])
            ))

            conn.commit()
            conn.close()

        except Exception as e:
            print(f"⚠️ Error logging to database: {e}")

    def create_alert(self, detection_result):
        """Create an alert for VPN detection"""
        if not detection_result['vpn_detected']:
            return

        # Cooldown: Don't spam alerts (wait 5 minutes between alerts)
        now = time.time()
        if 'last_alert' in self.alert_cooldown:
            if now - self.alert_cooldown['last_alert'] < 300:  # 5 minutes
                return

        self.alert_cooldown['last_alert'] = now

        alert = {
            'timestamp': detection_result['timestamp'],
            'type': 'VPN_DETECTED',
            'severity': 'high',
            'confidence': detection_result['confidence_score'],
            'details': {
                'interfaces': detection_result['checks']['network_interfaces']['interfaces'],
                'processes': detection_result['checks']['processes']['processes'][:3]
            },
            'message': f"VPN detected with {detection_result['confidence_score']}% confidence"
        }

        # Save alert to file
        try:
            alerts = []
            if VPN_LOG_PATH.exists():
                with open(VPN_LOG_PATH, 'r') as f:
                    alerts = json.load(f)

            alerts.append(alert)
            alerts = alerts[-50:]  # Keep last 50 alerts

            with open(VPN_LOG_PATH, 'w') as f:
                json.dump(alerts, f, indent=2)

            print(f"🚨 ALERT: VPN detected! Confidence: {detection_result['confidence_score']}%")

        except Exception as e:
            print(f"⚠️ Error creating alert: {e}")

    def run(self):
        """Main monitoring loop"""
        print("🔍 VPN Monitor Started")
        print(f"⏱️  Checking every {CHECK_INTERVAL} seconds")
        print("⏸️  Press Ctrl+C to stop\n")

        check_count = 0

        while self.running:
            try:
                check_count += 1
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Check #{check_count}")

                # Run detection
                result = self.detector.comprehensive_check()

                # Log to database
                self.log_to_database(result)

                # Create alert if VPN detected
                if result['vpn_detected']:
                    self.create_alert(result)
                    print(f"⚠️  VPN ACTIVE - Confidence: {result['confidence_score']}%")
                else:
                    print(f"✅ No VPN detected (Score: {result['confidence_score']}%)")

                # Wait for next check
                time.sleep(CHECK_INTERVAL)

            except KeyboardInterrupt:
                print("\n🛑 Stopping VPN monitor...")
                self.running = False
                break
            except Exception as e:
                print(f"⚠️ Error during monitoring: {e}")
                time.sleep(CHECK_INTERVAL)

    def stop(self):
        """Stop the monitor"""
        self.running = False


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    print("\n🛑 Shutting down VPN monitor...")
    sys.exit(0)


if __name__ == "__main__":
    # Setup signal handler
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start monitoring
    monitor = VPNMonitor()
    monitor.run()
