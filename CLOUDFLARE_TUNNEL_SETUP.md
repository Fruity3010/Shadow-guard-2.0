# Cloudflare Tunnel Setup

This guide uses one supported setup path: run the included Windows script and let it create the machine tunnel, DNS route, config file, and Windows service for you.

## What this gives you

Each machine gets a stable public hostname such as:

- `https://laptop-hr01.guard.example.com`
- `https://pc-finance-02.guard.example.com`

The cloud admin can then target machines with:

```text
SHADOWGUARD_TARGET_AGENT_URL_TEMPLATE=https://{machine}.guard.example.com
```

## Before the user runs anything

These are the only one-time items that must already be true:

1. Your domain is already onboarded to Cloudflare.
2. The subdomain suffix you want to use is decided, for example `guard.example.com`.
3. The local ShadowGuard machine agent is running on port `5555`.

If the domain is not yet on Cloudflare, an admin must first update the registrar nameservers to the Cloudflare nameservers for that domain. That is the only infrastructure-side manual step.

## One setup command for the user

Run this from the project root in an elevated PowerShell window:

```powershell
.\setup_cloudflared_windows.ps1 `
  -MachineName "laptop-hr01" `
  -HostnameSuffix "guard.example.com" `
  -CreateTunnel `
  -RouteDns `
  -InstallService
```

That is the only supported machine setup flow.

## What the script does automatically

The script will:

- install `cloudflared` if it is missing
- open the Cloudflare login flow when tunnel creation requires authentication
- create the named tunnel
- create the DNS route for `laptop-hr01.guard.example.com`
- write the tunnel config under `.\.shadowguard\cloudflared\config.yml`
- reuse or copy the tunnel credential JSON into that same runtime directory
- install `cloudflared` as a Windows service
- start the service if possible

By default all generated Cloudflare runtime files are stored under:

```text
.\.shadowguard\cloudflared
```

If you want a different location, set `SHADOWGUARD_BASE_DIR` or pass `-BaseDir`.

## What the user will see

During setup, the script may open a browser window for the Cloudflare login and tunnel authorization step. That Cloudflare sign-in is expected, but the user does not need to manually create the tunnel, write YAML, or run separate `cloudflared` commands.

## Example result

After the script finishes, this machine should be reachable at:

```text
https://laptop-hr01.guard.example.com
```

The generated config will look like this:

```yaml
tunnel: <TUNNEL_ID>
credentials-file: <BASE_DIR>\cloudflared\<TUNNEL_ID>.json

ingress:
  - hostname: laptop-hr01.guard.example.com
    service: http://127.0.0.1:5555
  - service: http_status:404
```

## Verify the machine setup

After setup, check these items:

1. The service exists:
```powershell
Get-Service cloudflared
```

2. The runtime files exist:
```powershell
Get-ChildItem .\.shadowguard\cloudflared
```

3. The machine endpoint responds:
```powershell
Invoke-WebRequest "https://laptop-hr01.guard.example.com/agent/blocked-sites"
```

If the agent is healthy, you should get a response from the local ShadowGuard machine API through Cloudflare.

## Cloud admin configuration

On the cloud admin host, set:

```powershell
$env:SHADOWGUARD_TARGET_AGENT_URL_TEMPLATE="https://{machine}.guard.example.com"
$env:SHADOWGUARD_DEFAULT_MACHINE="laptop-hr01"
$env:SHADOWGUARD_ALLOWED_MACHINES="laptop-hr01,pc-finance-02"
```

## Machine environment

On the user machine, point the local dashboard to the cloud admin:

```powershell
$env:SHADOWGUARD_REMOTE_ADMIN_URL="https://admin.guard.example.com"
```

## Naming rule

If your hostname suffix is `guard.example.com`, then:

- `laptop-hr01` becomes `https://laptop-hr01.guard.example.com`
- `pc-finance-02` becomes `https://pc-finance-02.guard.example.com`

The cloud admin swaps `{machine}` in:

```text
https://{machine}.guard.example.com
```

## Notes for operators

- Use one machine name per endpoint and keep it stable.
- Re-run the same script command if you need to rebuild the config or service.
- If credentials were originally created under the legacy `%USERPROFILE%\.cloudflared` path, the script will copy them into the project runtime directory automatically.
- This guide intentionally does not document the manual `cloudflared tunnel create`, `route dns`, or handwritten YAML flow. The script is the standard path.

## Outcome

- The blocker still runs locally on the user machine.
- The machine agent still listens locally on port `5555`.
- Cloudflare gives each machine a stable hostname.
- The cloud admin can securely send block and unblock actions to the selected machine.
