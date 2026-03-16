# Shadow IT Control Platform

## 🎯 Three Versions Available

### 1. Basic Blocker (`./setup_blocker.sh`)
**Use when:** You want simple, fast blocking of known sites
- ✅ Blocks social media (Facebook, Twitter, Instagram, Reddit, YouTube, TikTok)
- ✅ Custom blocked.html page
- ✅ Real-time dashboard
- ✅ No external API calls
- ✅ Zero latency impact

**Run:** `sudo ./setup_blocker.sh`

### 2. Basic Blocker + VPN Prevention (`./setup_blocker_with_vpn.sh`) ⭐ NEW
**Use when:** Users try to bypass controls with VPNs
- 🛡️ Everything from Basic Blocker PLUS:
- 🚫 Blocks 30+ VPN provider domains (NordVPN, ExpressVPN, etc.)
- 🔍 Real-time VPN detection (checks every 60s)
- 📊 VPN activity monitoring and alerts
- ⚠️ Custom warning page for VPN users
- 📈 VPN detection dashboard and API endpoints
- 🎯 Multi-layer detection (interfaces, processes, routing, DNS)

**Run:** `sudo ./setup_blocker_with_vpn.sh`

### 3. AI-Powered Blocker (`./setup_ai_blocker.sh`)
**Use when:** You need intelligent Shadow IT discovery and control
- 🤖 AI analyzes EVERY website in real-time
- 🤖 Risk scoring (1-100) for each site
- 🤖 Suggests bank-approved alternatives
- 🤖 Smart categorization (file sharing, AI tools, etc.)
- 🤖 Context-aware blocking with explanations
- 🤖 One-click access requests with business justification

**Run:** `sudo ./setup_ai_blocker.sh`

## 🔑 Key Differences

| Feature | Basic Blocker | Basic + VPN Prevention | AI Blocker |
|---------|--------------|----------------------|------------|
| **Intelligence** | Static list | Static list | AI-powered analysis |
| **VPN Detection** | ❌ | ✅ Multi-layer | ❌ (can be added) |
| **VPN Blocking** | ❌ | ✅ 30+ providers | ❌ |
| **Risk Assessment** | Predefined | Predefined | Real-time scoring |
| **Alternatives** | None | None | Suggests approved tools |
| **API Calls** | None | None | OpenAI API |
| **Performance** | ~1ms | ~1ms + 60s VPN checks | ~100-200ms |
| **Cost** | Free | Free | OpenAI API costs |
| **Best For** | Known threats | Preventing bypass | Unknown Shadow IT |

## 🚀 Quick Start

### For Basic Blocking:
```bash
# Blocks social media sites with custom page
sudo ./setup_blocker.sh
```

### For VPN Prevention (Recommended):
```bash
# Blocks sites + prevents VPN bypass
sudo ./setup_blocker_with_vpn.sh
```

### For AI-Powered Shadow IT Control:
```bash
# Intelligent risk assessment for all sites
sudo ./setup_ai_blocker.sh
```

## 📊 Dashboard
Both versions include a real-time dashboard at http://localhost:5555 showing:
- Total requests and blocked count
- Traffic timeline chart
- Top blocked/allowed domains
- Real-time activity feed
- Statistics and analytics

## 🏦 Bank/Enterprise Use Case

### Problem Solved:
- **Discovery**: Automatically finds ALL Shadow IT (not just known sites)
- **Intelligence**: AI assesses risk of unknown services
- **Guidance**: Suggests approved alternatives
- **Compliance**: Full audit trail with risk scores
- **Productivity**: Users get alternatives, not just "blocked"

### Example Scenarios:

**Employee tries Dropbox (AI Blocker):**
- AI detects: File sharing service
- Risk score: 85/100
- Shows risks: "No DLP, uncontrolled sharing"
- Suggests: "Use SharePoint or Box Enterprise"
- Action: Can request temporary access

**Employee visits Facebook (Basic Blocker):**
- Matches blocklist
- Shows: Custom blocked page
- Action: Blocked immediately

## 🔧 Technical Architecture

### Basic Version:
```
[User] → [Proxy] → [Blocklist Check] → [Allow/Block]
            ↓
       [Dashboard]
```

### AI Version:
```
[User] → [Proxy] → [OpenAI API] → [Risk Score] → [Decision]
            ↓           ↓              ↓
       [Dashboard]  [Categorize]  [Alternatives]
```

### VPN Prevention Version:
```
[User] → [Proxy] → [Blocklist + VPN Check] → [Allow/Block/Warn]
            ↓              ↓
       [Dashboard]    [VPN Monitor] (every 60s)
                           ↓
                    [Alert System]
```

## 🛡️ VPN Prevention Features (NEW)

### Why Block VPNs?
VPNs allow users to bypass proxy controls, creating security blind spots:
- ❌ No visibility into encrypted tunnel traffic
- ❌ Data exfiltration through VPN tunnels
- ❌ Unauthorized cloud services access
- ❌ Compliance violations

### How It Works
**4-Layer Detection System:**
1. **Network Interface** (40% confidence) - Detects `tun0`, `utun`, `wg0` interfaces
2. **Process Detection** (30% confidence) - Scans for VPN processes (OpenVPN, NordVPN, etc.)
3. **Routing Analysis** (20% confidence) - Checks if traffic routes through VPN
4. **DNS Leak Detection** (10% confidence) - Identifies VPN DNS servers

**Confidence Scoring:**
- 40%+ = VPN likely active → Trigger warning
- 70%+ = VPN definitely active → High confidence

### VPN Providers Blocked (30+)
- Commercial: NordVPN, ExpressVPN, Surfshark, CyberGhost, PIA, IPVanish, etc.
- Free: Hola, Betternet, Psiphon, Opera VPN, UltraSurf
- Infrastructure: OpenVPN.net, WireGuard.com

### VPN Dashboard
Access at `http://localhost:5555/api/vpn-status`

**New API Endpoints:**
- `/api/vpn-status` - Current VPN detection status
- `/api/vpn-history` - Historical detections
- `/api/vpn-alerts` - VPN alerts log
- `/api/vpn-stats` - Detection statistics
- `/api/vpn-add-to-blocklist` - Add VPN providers to blocklist

📖 **Full documentation:** [VPN_PREVENTION.md](VPN_PREVENTION.md)

## 💡 When to Use Which?

### Use Basic Blocker for:
- Home/personal use
- Blocking known distractions
- Zero-cost solution
- Maximum performance
- Simple compliance needs

### Use Basic + VPN Prevention for:
- **Enterprise networks** (⭐ Recommended)
- Preventing proxy bypass
- Users attempting VPN access
- Compliance requirements
- Complete network visibility

### Use AI Blocker for:
- Enterprise Shadow IT control
- Discovering unknown risks
- Regulatory compliance
- Educational blocking (shows why)
- Providing alternatives to users

## 🔐 Security Features
- HTTPS interception with certificates
- Real-time monitoring
- Audit logging
- Risk scoring
- Compliance reporting
- Access request workflow

## 📈 Performance Impact
- **Basic**: <1ms per request (negligible)
- **AI**: 100-200ms for unknown sites (cached after first check)
- **Bandwidth**: No impact on allowed sites
- **CPU**: Minimal (<5% on average)

## 🛠️ Configuration
Edit these files to customize:
- `BLOCKED` list in `simple_blocker.py` (Basic)
- `SHADOW_IT_CATEGORIES` in `ai_risk_analyzer.py` (AI)
- `bank_approved_tools.json` for alternatives

## 📝 License
MIT - Use freely for any purpose

---
**Built for the "Taming the Shadows" Challenge** - Enabling business agility while protecting against Shadow IT risks.