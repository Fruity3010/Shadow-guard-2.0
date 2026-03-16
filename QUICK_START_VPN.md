# 🚀 Quick Start: VPN Prevention

## Installation (30 seconds)

```bash
cd /Users/edwardcampbell/Desktop/shadowGuard
sudo ./setup_blocker_with_vpn.sh
```

That's it! The system will:
1. Install dependencies
2. Add 30+ VPN provider domains to blocklist
3. Start proxy server on port 8888
4. Start dashboard on http://localhost:5555
5. Start VPN monitoring (checks every 60 seconds)
6. Configure Mac network settings

## What You Get

### ✅ VPN Provider Blocking
Users cannot access:
- NordVPN, ExpressVPN, Surfshark, CyberGhost
- ProtonVPN, IPVanish, TunnelBear, etc.
- 30+ commercial and free VPN sites

### ✅ Active VPN Detection
System monitors for:
- VPN network interfaces (tun, tap, utun, wg)
- VPN processes (OpenVPN, WireGuard, etc.)
- VPN routing changes
- VPN DNS servers

### ✅ Real-time Alerts
- Logs all VPN detection attempts
- Creates alerts when VPN detected
- Shows warning page to users
- Full audit trail in dashboard

## Test It

### 1. Check VPN Status
```bash
curl http://localhost:5555/api/vpn-status | jq
```

### 2. Run Manual Detection
```bash
python3 vpn_detector.py
```

### 3. View Dashboard
Open browser: http://localhost:5555

### 4. Test VPN Blocking
Try accessing: https://nordvpn.com
(Should show blocked page)

## API Endpoints

```bash
# Get current VPN status
curl http://localhost:5555/api/vpn-status

# Get VPN detection history
curl http://localhost:5555/api/vpn-history

# Get VPN alerts
curl http://localhost:5555/api/vpn-alerts

# Get VPN statistics
curl http://localhost:5555/api/vpn-stats

# Add VPN providers to blocklist
curl -X POST http://localhost:5555/api/vpn-add-to-blocklist
```

## View Logs

```bash
# VPN monitor logs
tail -f /tmp/vpn_monitor.log

# Dashboard logs
tail -f /tmp/dashboard.log

# VPN detection results
cat /tmp/vpn_detection.json | jq

# VPN alerts
cat vpn_alerts.json | jq
```

## Stop the System

Press `Ctrl+C` in the terminal where setup script is running.

This will:
- Stop proxy server
- Stop dashboard
- Stop VPN monitor
- Restore network settings

## Configuration

### Change Detection Frequency
Edit `monitor_vpn.py`:
```python
CHECK_INTERVAL = 60  # Seconds between checks
```

### Add More VPN Providers
Edit `vpn_detector.py`:
```python
VPN_PROVIDERS = [
    "nordvpn.com",
    "your-vpn-provider.com",  # Add here
    # ...
]
```

Then restart or run:
```bash
curl -X POST http://localhost:5555/api/vpn-add-to-blocklist
```

### Whitelist Corporate VPN
Edit `vpn_detector.py`:
```python
# In check_network_interfaces() method
WHITELISTED_INTERFACES = ['utun0', 'cisco-anyconnect']

if interface in WHITELISTED_INTERFACES:
    continue  # Skip this interface
```

## Troubleshooting

### VPN not being detected?
```bash
# Check if monitor is running
ps aux | grep monitor_vpn

# Lower the confidence threshold
# Edit vpn_detector.py line 177:
is_vpn_active = detection_score >= 30  # Instead of 40
```

### Too many false positives?
```bash
# Increase confidence threshold
# Edit vpn_detector.py line 177:
is_vpn_active = detection_score >= 70  # Instead of 40
```

### Check detection manually
```bash
# Run detector
python3 vpn_detector.py

# Check network interfaces
ifconfig | grep -E "tun|tap|utun|wg"

# Check VPN processes
ps aux | grep -iE "vpn|openvpn|wireguard|nord"
```

## Files Created

```
vpn_detector.py              # Detection logic
monitor_vpn.py               # Background monitor
setup_blocker_with_vpn.sh    # Setup script
templates/vpn_warning.html   # Warning page
vpn_alerts.json             # Alerts (auto-generated)
/tmp/vpn_detection.json     # Detection log
/tmp/vpn_monitor.log        # Monitor log
activity.db                  # Database with vpn_detections table
```

## What Users See

### When accessing VPN site:
```
🛑 BLOCKED
nordvpn.com
VPN provider - Blocks proxy controls
```

### When VPN is detected:
```
🛑 VPN Detected
Confidence: 70%

⚠️ Policy Violation
• VPN usage is prohibited
• Bypasses security controls
• Activity is being logged

Detected: utun3, openvpn process

[🔄 I've Disconnected - Check Again]
```

## Next Steps

📖 Read full documentation: [VPN_PREVENTION.md](VPN_PREVENTION.md)

🎯 Customize blocklist, thresholds, and alerts

📊 Monitor dashboard for VPN attempts

🔧 Adjust detection sensitivity for your environment

---

**Need Help?**
- Check logs: `/tmp/vpn_monitor.log`
- Test manually: `python3 vpn_detector.py`
- View API: `curl http://localhost:5555/api/vpn-status`
