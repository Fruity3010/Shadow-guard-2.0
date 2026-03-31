# Vercel Admin

This folder is a standalone Flask admin app for Vercel.

## Required environment variables

Use one of these target URL options:

- `SHADOWGUARD_TARGET_AGENT_URL=https://your-agent-host`
- `SHADOWGUARD_TARGET_AGENT_URL_TEMPLATE=https://{machine}.guard.xandcloud.icu`

Then set the machine defaults you want:

- `SHADOWGUARD_DEFAULT_MACHINE=peterpc`
- `SHADOWGUARD_ALLOWED_MACHINES=peterpc`

## Admin authentication

The Vercel admin now uses Supabase Auth for sign-in. To enable it, add:

- `SUPABASE_URL=https://xxxx.supabase.co`
- `SUPABASE_ANON_KEY=your-supabase-anon-key`
- `SHADOWGUARD_ADMIN_SESSION_SECRET=generate-a-long-random-secret`

The app also accepts these fallback names if you already use Supabase's newer naming in Vercel:

- `NEXT_PUBLIC_SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`

Optional access restrictions:

- `SHADOWGUARD_SUPABASE_ALLOWED_EMAILS=alice@company.com,bob@company.com`
- `SHADOWGUARD_SUPABASE_ALLOWED_DOMAIN=company.com`

Notes:

- If `SUPABASE_URL` and `SUPABASE_ANON_KEY` are set, the app requires a Supabase login for both the UI and API routes.
- On Vercel, the admin now fails closed. If Supabase auth vars are missing, the app returns a configuration error instead of exposing the admin publicly.
- A deployed Vercel app only sees variables configured in the Vercel project settings. A local `.env` file does not secure the deployed site by itself.
- If you set `SHADOWGUARD_SUPABASE_ALLOWED_EMAILS`, only those exact users can sign in.
- If you set `SHADOWGUARD_SUPABASE_ALLOWED_DOMAIN`, only users from that email domain can sign in.
- You can use both restrictions together if you want a domain rule plus an explicit allowlist.
- You should set `SHADOWGUARD_ADMIN_SESSION_SECRET` in Vercel so session cookies stay stable across deployments.

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
- On Vercel, session cookies are marked secure automatically.
