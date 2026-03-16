# 🛡️ VPN Prevention & Detection

## Overview
ShadowGuard now includes comprehensive VPN detection and prevention to stop users from bypassing proxy controls.

---

## 🚀 Quick Start

### Enable VPN Prevention:
```bash
sudo ./setup_blocker_with_vpn.sh
```

This will:
- Block 30+ VPN provider domains
- Monitor network interfaces for VPN connections
- Check for running VPN processes
- Log all VPN detection attempts
- Display warning page to users using VPNs

---

## 🔍 How VPN Detection Works

### Multi-Layer Detection

**1. Network Interface Detection (40% confidence)**
- Monitors for VPN interfaces: `tun0`, `tap0`, `utun1+`, `wg0`, `ppp0`
- Detects WireGuard, OpenVPN, PPTP, L2TP interfaces
- Checks interface status (UP/DOWN)

**2. Process Detection (30% confidence)**
- Scans running processes for VPN keywords
- Detects: NordVPN, ExpressVPN, Tunnelblick, Viscosity, OpenVPN
- Monitors system processes every 60 seconds

**3. Routing Table Analysis (20% confidence)**
- Checks if traffic is routed through VPN interfaces
- Detects changes to default gateway
- Identifies suspicious routing configurations

**4. DNS Leak Detection (10% confidence)**
- Monitors DNS server configurations
- Detects common VPN DNS servers (10.x.x.x, 1.1.1.1, 8.8.8.8)
- Identifies custom DNS from VPN providers

### Confidence Scoring
- **0-39%**: No VPN detected
- **40-69%**: VPN likely active (moderate confidence)
- **70-100%**: VPN definitely active (high confidence)

---

## 🚫 VPN Provider Blocking

### Blocked Domains (30+ providers)

**Major Commercial VPNs:**
- NordVPN (nordvpn.com)
- ExpressVPN (expressvpn.com)
- Surfshark (surfshark.com)
- CyberGhost (cyberghost.com)
- Private Internet Access (privateinternetaccess.com)
- IPVanish (ipvanish.com)
- VyprVPN (vyprvpn.com)
- PureVPN (purevpn.com)
- TunnelBear (tunnelbear.com)
- ProtonVPN (protonvpn.com)
- Windscribe (windscribe.com)
- Hotspot Shield (hotspotshield.com)

**Free VPNs (High Risk):**
- Hola (hola.org)
- Betternet (betternet.co)
- Psiphon (psiphon.ca)
- Opera VPN (opera.com/vpn)
- UltraSurf (ultrasurf.us)
- HideMyAss (hidemyass.com)
- ZenMate (zenmate.com)

**VPN Infrastructure:**
- OpenVPN (openvpn.net)
- WireGuard (wireguard.com)
- SoftEther (softether.org)

---

## 📊 Dashboard Integration

### New API Endpoints

**1. Get Current VPN Status**
```
GET http://localhost:5555/api/vpn-status
```
Response:
```json
{
  "timestamp": "2025-01-08T11:23:45",
  "vpn_detected": true,
  "confidence_score": 70,
  "checks": {
    "network_interfaces": {
      "detected": true,
      "interfaces": ["utun3", "utun4"]
    },
    "processes": {
      "detected": true,
      "processes": ["/usr/local/bin/openvpn", "nordvpn"]
    },
    "routing": {
      "detected": true,
      "info": "Route detected through utun interface"
    },
    "dns": {
      "suspicious": false,
      "servers": ["192.168.1.1"]
    }
  }
}
```

**2. Get VPN Detection History**
```
GET http://localhost:5555/api/vpn-history
```

**3. Get VPN Alerts**
```
GET http://localhost:5555/api/vpn-alerts
```

**4. Add VPN Providers to Blocklist**
```
POST http://localhost:5555/api/vpn-add-to-blocklist
```

**5. Get VPN Statistics**
```
GET http://localhost:5555/api/vpn-stats
```
Response:
```json
{
  "total_detections": 15,
  "today_detections": 3,
  "last_detection_time": "2025-01-08T10:30:00",
  "current_status": {
    "vpn_active": true,
    "confidence": 70
  }
}
```

---

## ⚙️ Configuration

### Monitoring Frequency
Edit `monitor_vpn.py`:
```python
CHECK_INTERVAL = 60  # Check every 60 seconds (default)
# Change to 30 for more frequent checks
# Change to 300 (5 minutes) for less frequent checks
```

### Whitelist Corporate VPNs
Edit `vpn_detector.py` to exclude corporate VPN interfaces:
```python
# Skip corporate VPN interfaces
if interface in ['utun0', 'cisco-anyconnect']:
    continue
```

### Adjust Confidence Thresholds
Edit `vpn_detector.py`:
```python
# Current scoring
if interface_detected: detection_score += 40
if process_detected: detection_score += 30
if route_detected: detection_score += 20
if dns_suspicious: detection_score += 10

# Require higher confidence (70+) to trigger alerts
is_vpn_active = detection_score >= 70  # Change from 40 to 70
```

---

## 🎯 Enforcement Modes

### Mode 1: Monitoring Only (Default)
- Detects VPNs
- Logs activity
- Shows warnings
- No blocking

### Mode 2: VPN Provider Blocking
```bash
# Already enabled with setup_blocker_with_vpn.sh
# Blocks access to VPN provider websites
```

### Mode 3: Strict Mode (Block All Traffic)
Add to `simple_blocker.py`:
```python
from vpn_detector import VPNDetector

def request(flow: http.HTTPFlow) -> None:
    # Check for active VPN
    detector = VPNDetector()
    result = detector.comprehensive_check()

    if result['vpn_detected'] and result['confidence_score'] >= 70:
        # Block ALL traffic if VPN is active
        html = VPN_WARNING_TEMPLATE
        flow.response = http.Response.make(200, html.encode('utf-8'))
        return

    # ... rest of blocking logic
```

---

## 📝 Usage Examples

### Test VPN Detection
```bash
# Run detection manually
python3 vpn_detector.py
```

Output:
```
🔍 Running VPN detection checks...

============================================================
🔍 VPN DETECTION REPORT
============================================================
⚠️  STATUS: VPN DETECTED
🎯 Confidence: 70%
⏰ Time: 2025-01-08T11:23:45

📋 Detection Details:
  ⚠️  VPN Interfaces: utun3, utun4
  ⚠️  VPN Processes: /usr/local/bin/openvpn, nordvpn-daemon
  ⚠️  Routing: Route detected through utun interface
  ✅ DNS Servers: 2 configured
============================================================

📋 VPN Provider Blocklist: 30 domains
```

### Monitor VPN Activity
```bash
# Run background monitor
python3 monitor_vpn.py
```

Output:
```
🔍 VPN Monitor Started
⏱️  Checking every 60 seconds
⏸️  Press Ctrl+C to stop

[11:23:45] Check #1
✅ No VPN detected (Score: 10%)
[11:24:45] Check #2
⚠️  VPN ACTIVE - Confidence: 70%
🚨 ALERT: VPN detected! Confidence: 70%
```

### Check VPN Status via API
```bash
curl http://localhost:5555/api/vpn-status | jq
```

### Add VPN Blocklist
```bash
curl -X POST http://localhost:5555/api/vpn-add-to-blocklist
```

---

## 🔒 Security Benefits

### Prevents Bypass
- Users cannot access VPN provider websites
- Active VPN connections are detected and logged
- Audit trail of all VPN attempts

### Data Loss Prevention
- Blocks unauthorized tunneling
- Prevents data exfiltration via VPN
- Maintains visibility of all traffic

### Compliance
- Full logging for regulatory requirements
- Real-time alerts for policy violations
- Historical detection data

---

## 📈 Monitoring & Alerts

### Database Schema

**VPN Detections Table:**
```sql
CREATE TABLE vpn_detections (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    vpn_detected BOOLEAN,
    confidence_score INTEGER,
    interfaces TEXT,
    processes TEXT,
    routing_info TEXT,
    dns_servers TEXT
);
```

### Alert System

**Alert Cooldown:** 5 minutes between alerts (prevents spam)

**Alert JSON Format:**
```json
{
  "timestamp": "2025-01-08T11:23:45",
  "type": "VPN_DETECTED",
  "severity": "high",
  "confidence": 70,
  "details": {
    "interfaces": ["utun3"],
    "processes": ["openvpn"]
  },
  "message": "VPN detected with 70% confidence"
}
```

---

## 🚨 User Experience

### What Users See

**When accessing VPN provider site:**
```
🛑 BLOCKED
nordvpn.com
VPN provider - Blocks proxy controls
```

**When VPN is detected:**
```
🛑 VPN Detected
Unauthorized VPN usage detected on this network

Confidence: 70%

⚠️ Policy Violation
• VPN usage is prohibited on this network
• VPN services bypass security controls
• This activity is being logged and reported
• Continued use may result in access suspension

Detected VPN Indicators:
Interfaces: utun3, utun4
Processes: openvpn

✅ What You Should Do
1. Disconnect your VPN immediately
2. Contact IT if you need secure remote access
3. Refresh this page after disconnecting

[🔄 I've Disconnected - Check Again]
[📧 Contact IT Support]
```

---

## 🛠️ Troubleshooting

### False Positives

**Issue:** Corporate VPN detected as unauthorized

**Solution:** Whitelist corporate VPN interfaces
```python
# In vpn_detector.py
WHITELISTED_INTERFACES = ['utun0', 'cisco-vpn']

if interface in WHITELISTED_INTERFACES:
    continue
```

### Detection Not Working

**Issue:** VPN not being detected

**Solution 1:** Lower confidence threshold
```python
is_vpn_active = detection_score >= 30  # Instead of 40
```

**Solution 2:** Check monitor is running
```bash
ps aux | grep monitor_vpn
# Should show running process
```

**Solution 3:** Check logs
```bash
tail -f /tmp/vpn_monitor.log
tail -f /tmp/vpn_detection.json
```

### Performance Issues

**Issue:** Too many checks slowing down system

**Solution:** Increase check interval
```python
CHECK_INTERVAL = 300  # Check every 5 minutes instead of 60 seconds
```

---

## 📋 File Structure

```
shadowGuard/
├── vpn_detector.py              # Core VPN detection logic
├── monitor_vpn.py               # Background monitoring service
├── setup_blocker_with_vpn.sh   # Setup script with VPN prevention
├── templates/
│   └── vpn_warning.html         # Warning page for VPN users
├── vpn_alerts.json              # VPN alert log (auto-generated)
├── /tmp/vpn_detection.json      # Detection results (auto-generated)
└── activity.db                  # Contains vpn_detections table
```

---

## 🎓 Best Practices

### 1. Start with Monitoring
Begin with detection-only mode to understand usage patterns before enforcing blocks.

### 2. Whitelist Corporate VPNs
Always whitelist authorized VPN solutions (Cisco AnyConnect, Zscaler, etc.)

### 3. Educate Users
Provide clear communication about VPN policies and approved alternatives.

### 4. Review Logs Regularly
Check `vpn_alerts.json` and dashboard for patterns.

### 5. Adjust Thresholds
Fine-tune confidence scores based on your environment and false positive rate.

---

## 🔄 Updates & Maintenance

### Add New VPN Provider
Edit `vpn_detector.py`:
```python
VPN_PROVIDERS = [
    "nordvpn.com",
    "new-vpn-provider.com",  # Add here
    # ...
]
```

Then update blocklist:
```bash
curl -X POST http://localhost:5555/api/vpn-add-to-blocklist
```

### View Detection Statistics
```bash
# Total detections
sqlite3 activity.db "SELECT COUNT(*) FROM vpn_detections WHERE vpn_detected=1;"

# Today's detections
sqlite3 activity.db "SELECT COUNT(*) FROM vpn_detections WHERE vpn_detected=1 AND DATE(timestamp)=DATE('now');"

# Top detected interfaces
sqlite3 activity.db "SELECT interfaces, COUNT(*) as count FROM vpn_detections WHERE vpn_detected=1 GROUP BY interfaces ORDER BY count DESC LIMIT 5;"
```

---

## 📞 Support

For questions or issues:
1. Check `/tmp/vpn_monitor.log` for errors
2. Review `/tmp/vpn_detection.json` for detection results
3. Test manually: `python3 vpn_detector.py`
4. Check API: `curl http://localhost:5555/api/vpn-status`

---

**Built for enterprise Shadow IT control and VPN bypass prevention**
