# Vercel Admin

This folder is a standalone Flask admin app for Vercel.

## Required environment variables

Use one of these target URL options:

- `SHADOWGUARD_TARGET_AGENT_URL=https://your-agent-host`
- `SHADOWGUARD_TARGET_AGENT_URL_TEMPLATE=https://{machine}.guard.xandcloud.icu`

Then set the machine defaults you want:

- `SHADOWGUARD_DEFAULT_MACHINE=peterpc`
- `SHADOWGUARD_ALLOWED_MACHINES=peterpc`

For persistent cloud policy storage, set:

- `DATABASE_URL=postgresql://...`

If `DATABASE_URL` is not set, the app falls back to `policy_store.db`, which is fine for local testing but not durable on Vercel.

## Local run

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## Vercel deploy

1. Create a new Vercel project from this folder or import the repo that contains it.
2. If this app lives inside a larger repo, set the Root Directory to `vercel-admin`. If this folder is the repo root, leave the Root Directory as `.`.
3. Add the environment variables above in the Vercel dashboard.
4. Deploy.

## Notes

- Vercel detects `app.py` automatically because it exports a top-level Flask `app`.
- `vercel.json` excludes local-only files like `venv/`, `__pycache__/`, and `.env` from the Python bundle.
- Policy storage supports Postgres through `DATABASE_URL`. This is the recommended production path for groups, machine assignments, and access policies.

## Machine policy enforcement

On the user machine, point the blocker at the cloud admin lookup endpoint:

- `SHADOWGUARD_POLICY_LOOKUP_URL=https://your-vercel-admin-host`
- `SHADOWGUARD_MACHINE_NAME=peterpc`

If `SHADOWGUARD_POLICY_LOOKUP_URL` is not set, the blocker falls back to `SHADOWGUARD_REMOTE_ADMIN_URL` when available.

The blocker now evaluates cloud policies with these actions:

- `allow`: explicitly allow the app even if a local block rule exists
- `block`: block the app with the normal block page
- `isolate`: block the app with an isolation page so the user can see it was isolated by policy
