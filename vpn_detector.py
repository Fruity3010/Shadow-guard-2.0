#!/usr/bin/env python3
"""
VPN Detection Module for Shadow IT Control Platform
Detects and prevents VPN usage to bypass proxy controls
"""

import subprocess
import re
import json
import socket
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple

# Known VPN interface patterns
VPN_INTERFACES = [
    'tun', 'tap', 'ppp', 'utun', 'ipsec',
    'wg', 'vpn', 'nordlynx', 'expressvpn'
]

# Known VPN provider domains (comprehensive list)
VPN_PROVIDERS = [
    # Major VPN Services
    "nordvpn.com", "expressvpn.com", "surfshark.com", "cyberghost.com",
    "privateinternetaccess.com", "ipvanish.com", "vyprvpn.com", "purevpn.com",
    "tunnelbear.com", "protonvpn.com", "windscribe.com", "hotspotshield.com",
    "hide.me", "ivpn.net", "mullvad.net", "astrill.com", "buffered.com",

    # Business VPNs (more lenient, but monitored)
    "openvpn.net", "wireguard.com", "softether.org",

    # VPN Infrastructure
    "ovpn.com", "vpngate.net", "strongvpn.com", "torguard.net",
    "privatevpn.com", "goosevpn.com", "avast.com/secureline",

    # Free VPNs (high risk)
    "hola.org", "betternet.co", "psiphon.ca", "opera.com/vpn",
    "ultrasurf.us", "hidemyass.com", "zenmate.com"
]

# Common VPN ports
VPN_PORTS = {
    1194: "OpenVPN",
    1723: "PPTP",
    500: "IPSec/IKEv2",
    4500: "IPSec NAT-T",
    51820: "WireGuard",
    1701: "L2TP",
    443: "OpenVPN (SSL)",
    8080: "Proxy/VPN",
    53: "DNS Tunnel"
}

class VPNDetector:
    def __init__(self, log_file="/tmp/vpn_detection.json"):
        self.log_file = Path(log_file)
        self.detection_log = []

    def check_network_interfaces(self) -> Tuple[bool, List[str]]:
        """
        Check for active VPN network interfaces
        Returns: (is_vpn_detected, list_of_vpn_interfaces)
        """
        vpn_interfaces = []

        try:
            # Get list of network interfaces (works on Mac/Linux)
            result = subprocess.run(
                ['ifconfig'],
                capture_output=True,
                text=True,
                timeout=5
            )

            interfaces = result.stdout

            # Check for VPN interface patterns
            for vpn_pattern in VPN_INTERFACES:
                matches = re.findall(rf'({vpn_pattern}\d*):.*flags=.*UP', interfaces, re.IGNORECASE)
                if matches:
                    vpn_interfaces.extend(matches)

            # Additional check: look for "utun" interfaces (common on macOS)
            utun_matches = re.findall(r'(utun\d+):.*flags=.*UP', interfaces)
            if utun_matches:
                # Filter out utun0 which is usually system (keep utun1+)
                vpn_utun = [u for u in utun_matches if u != 'utun0']
                vpn_interfaces.extend(vpn_utun)

        except subprocess.TimeoutExpired:
            print("⚠️ Interface check timed out")
        except Exception as e:
            print(f"⚠️ Error checking interfaces: {e}")

        return (len(vpn_interfaces) > 0, vpn_interfaces)

    def check_vpn_processes(self) -> Tuple[bool, List[str]]:
        """
        Check for running VPN processes
        Returns: (is_vpn_detected, list_of_vpn_processes)
        """
        vpn_processes = []
        vpn_keywords = [
            'openvpn', 'wireguard', 'nordvpn', 'expressvpn', 'tunnelblick',
            'viscosity', 'vpn', 'pptp', 'l2tp', 'ipsec', 'softether',
            'protonvpn', 'mullvad', 'surfshark', 'cyberghost'
        ]

        try:
            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=5
            )

            processes = result.stdout.lower()

            for keyword in vpn_keywords:
                if keyword in processes:
                    # Extract process name
                    matches = re.findall(rf'[\w\-/]*{keyword}[\w\-]*', processes)
                    vpn_processes.extend(matches[:3])  # Limit to 3 matches per keyword

        except Exception as e:
            print(f"⚠️ Error checking processes: {e}")

        # Remove duplicates
        vpn_processes = list(set(vpn_processes))

        return (len(vpn_processes) > 0, vpn_processes)

    def check_routing_table(self) -> Tuple[bool, str]:
        """
        Check routing table for VPN routes
        Returns: (is_vpn_detected, suspicious_route_info)
        """
        try:
            result = subprocess.run(
                ['netstat', '-nr'],
                capture_output=True,
                text=True,
                timeout=5
            )

            routes = result.stdout

            # Look for routes through VPN interfaces
            for vpn_pattern in VPN_INTERFACES:
                if re.search(rf'{vpn_pattern}\d*', routes):
                    return (True, f"Route detected through {vpn_pattern} interface")

            # Check for 0.0.0.0 default route through non-standard interface
            default_routes = re.findall(r'(default|0\.0\.0\.0).*?(\w+\d*)\s*$', routes, re.MULTILINE)
            for route in default_routes:
                interface = route[1]
                if any(vpn in interface.lower() for vpn in VPN_INTERFACES):
                    return (True, f"Default route through {interface}")

        except Exception as e:
            print(f"⚠️ Error checking routes: {e}")

        return (False, "")

    def check_dns_leaks(self) -> Tuple[bool, List[str]]:
        """
        Check for DNS leaks (DNS servers outside expected range)
        Returns: (is_suspicious, list_of_dns_servers)
        """
        dns_servers = []

        try:
            # Get DNS configuration (Mac)
            result = subprocess.run(
                ['scutil', '--dns'],
                capture_output=True,
                text=True,
                timeout=5
            )

            # Extract DNS server IPs
            dns_ips = re.findall(r'nameserver\[\d+\] : ([\d\.]+)', result.stdout)
            dns_servers = list(set(dns_ips))

            # Check for common VPN DNS servers (often 10.x.x.x or custom)
            suspicious_dns = [
                dns for dns in dns_servers
                if dns.startswith('10.') or dns.startswith('172.') or dns in ['1.1.1.1', '8.8.8.8', '9.9.9.9']
            ]

            return (len(suspicious_dns) > 0, dns_servers)

        except Exception as e:
            print(f"⚠️ Error checking DNS: {e}")

        return (False, dns_servers)

    def comprehensive_check(self) -> Dict:
        """
        Run all VPN detection checks
        Returns: Dictionary with detection results
        """
        print("🔍 Running VPN detection checks...")

        # Run all checks
        interface_detected, vpn_interfaces = self.check_network_interfaces()
        process_detected, vpn_processes = self.check_vpn_processes()
        route_detected, route_info = self.check_routing_table()
        dns_suspicious, dns_servers = self.check_dns_leaks()

        # Calculate confidence score
        detection_score = 0
        if interface_detected: detection_score += 40
        if process_detected: detection_score += 30
        if route_detected: detection_score += 20
        if dns_suspicious: detection_score += 10

        is_vpn_active = detection_score >= 40

        result = {
            'timestamp': datetime.now().isoformat(),
            'vpn_detected': is_vpn_active,
            'confidence_score': detection_score,
            'checks': {
                'network_interfaces': {
                    'detected': interface_detected,
                    'interfaces': vpn_interfaces
                },
                'processes': {
                    'detected': process_detected,
                    'processes': vpn_processes[:5]  # Limit output
                },
                'routing': {
                    'detected': route_detected,
                    'info': route_info
                },
                'dns': {
                    'suspicious': dns_suspicious,
                    'servers': dns_servers
                }
            }
        }

        # Log the detection
        self._log_detection(result)

        return result

    def _log_detection(self, result: Dict):
        """Log detection results to file"""
        try:
            logs = []
            if self.log_file.exists():
                with open(self.log_file, 'r') as f:
                    logs = json.load(f)

            logs.append(result)

            # Keep last 100 detections
            logs = logs[-100:]

            with open(self.log_file, 'w') as f:
                json.dump(logs, f, indent=2)

        except Exception as e:
            print(f"⚠️ Failed to log detection: {e}")

    def get_vpn_provider_blocklist(self) -> List[Dict]:
        """
        Get list of VPN provider domains to block
        Returns: List of blocklist entries
        """
        blocklist = []

        for domain in VPN_PROVIDERS:
            blocklist.append({
                'domain': domain,
                'category': 'vpn_provider',
                'methods': ['GET', 'POST', 'PUT', 'DELETE'],
                'risk_score': 90,
                'reason': 'VPN provider - Blocks proxy controls',
                'use_ai': False
            })

        return blocklist

    def print_report(self, result: Dict):
        """Print a formatted detection report"""
        print("\n" + "="*60)
        print("🔍 VPN DETECTION REPORT")
        print("="*60)

        if result['vpn_detected']:
            print("⚠️  STATUS: VPN DETECTED")
            print(f"🎯 Confidence: {result['confidence_score']}%")
        else:
            print("✅ STATUS: No VPN Detected")
            print(f"🎯 Confidence: {result['confidence_score']}%")

        print(f"⏰ Time: {result['timestamp']}")
        print("\n📋 Detection Details:")

        # Network Interfaces
        if result['checks']['network_interfaces']['detected']:
            print(f"  ⚠️  VPN Interfaces: {', '.join(result['checks']['network_interfaces']['interfaces'])}")
        else:
            print("  ✅ Network Interfaces: Clean")

        # Processes
        if result['checks']['processes']['detected']:
            print(f"  ⚠️  VPN Processes: {', '.join(result['checks']['processes']['processes'][:3])}")
        else:
            print("  ✅ VPN Processes: None found")

        # Routing
        if result['checks']['routing']['detected']:
            print(f"  ⚠️  Routing: {result['checks']['routing']['info']}")
        else:
            print("  ✅ Routing: Normal")

        # DNS
        if result['checks']['dns']['suspicious']:
            print(f"  ⚠️  DNS Servers: {', '.join(result['checks']['dns']['servers'][:3])}")
        else:
            print(f"  ✅ DNS Servers: {len(result['checks']['dns']['servers'])} configured")

        print("="*60 + "\n")


def main():
    """Test VPN detection"""
    detector = VPNDetector()
    result = detector.comprehensive_check()
    detector.print_report(result)

    # Print VPN provider blocklist summary
    blocklist = detector.get_vpn_provider_blocklist()
    print(f"📋 VPN Provider Blocklist: {len(blocklist)} domains")


if __name__ == "__main__":
    main()
