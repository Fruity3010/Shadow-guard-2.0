# Supabase Integration Guide

This guide explains how to connect ShadowGuard to a hosted Supabase database so the admin (deployed on Vercel) can manage block lists that the local proxy script syncs automatically.

---

## Architecture

```
Admin UI (Vercel) ──── Supabase JS SDK ────► Supabase DB
                                                  │
                                             REST API
                                                  │
                              ◄── polls every 60s ── simple_blocker.py
                                                       (on employee machine)
                                                  │
                                         overwrites blocklist.json
                                                  │
                                    picked up by 5s cache refresh
```

---

## Step 1: Create the Supabase Project

1. Go to [supabase.com](https://supabase.com) and create a new project
2. Once created, go to **Settings → API** and copy:
   - **Project URL** — looks like `https://xxxx.supabase.co`
   - **anon public key** — long JWT string

---

## Step 2: Create the Database Tables

In your Supabase project, go to **SQL Editor** and run:

```sql
-- Blocked sites table
CREATE TABLE blocklists (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  domain TEXT NOT NULL UNIQUE,
  category TEXT DEFAULT 'custom',
  methods TEXT[] DEFAULT ARRAY['GET', 'POST'],
  risk_score INTEGER DEFAULT 50,
  reason TEXT DEFAULT '',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Version tracker so the script only fetches the full list when something changed
CREATE TABLE blocklist_meta (
  id INTEGER PRIMARY KEY DEFAULT 1,
  version INTEGER DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert the initial meta row
INSERT INTO blocklist_meta (id, version) VALUES (1, 0);

-- Auto-bump version whenever blocklists table changes
CREATE OR REPLACE FUNCTION bump_blocklist_version()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE blocklist_meta
  SET version = version + 1, updated_at = NOW()
  WHERE id = 1;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER on_blocklist_change
AFTER INSERT OR UPDATE OR DELETE ON blocklists
FOR EACH ROW EXECUTE FUNCTION bump_blocklist_version();
```

---

## Step 3: Configure the Local Script

Set environment variables on each employee machine before running the proxy.

**macOS/Linux** — add to `~/.zshrc` or `~/.bashrc`:
```bash
export SUPABASE_URL="https://xxxx.supabase.co"
export SUPABASE_ANON_KEY="your-anon-key-here"
```

**Windows** — run in PowerShell (as admin):
```powershell
[System.Environment]::SetEnvironmentVariable("SUPABASE_URL", "https://xxxx.supabase.co", "Machine")
[System.Environment]::SetEnvironmentVariable("SUPABASE_ANON_KEY", "your-anon-key-here", "Machine")
```

---

## Step 4: Add the Sync Thread to `simple_blocker.py`

Add this block to `simple_blocker.py` after the imports:

```python
import os
import requests as http_requests
import threading

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")
_remote_version = -1

def sync_blocklist_from_supabase():
    """Background thread: polls Supabase every 60s and syncs blocklist.json if changed."""
    global _remote_version
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        print("⚠️  SUPABASE_URL / SUPABASE_ANON_KEY not set — remote sync disabled")
        return

    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}"
    }

    while True:
        try:
            # Cheap check: has the version changed?
            meta = http_requests.get(
                f"{SUPABASE_URL}/rest/v1/blocklist_meta?select=version&id=eq.1",
                headers=headers, timeout=5
            ).json()

            remote_version = meta[0]["version"]

            if remote_version != _remote_version:
                rows = http_requests.get(
                    f"{SUPABASE_URL}/rest/v1/blocklists?select=*",
                    headers=headers, timeout=10
                ).json()

                with open(BLOCKLIST_FILE, "w") as f:
                    json.dump(rows, f, indent=2, default=str)

                _remote_version = remote_version
                print(f"🔄 Synced {len(rows)} rules from Supabase (version {remote_version})")

        except Exception as e:
            print(f"⚠️  Supabase sync error: {e}")

        time.sleep(60)

# Start sync thread
threading.Thread(target=sync_blocklist_from_supabase, daemon=True).start()
```

---

## Step 5: Admin UI (Vercel) — Supabase SDK Calls

Install the Supabase JS client:
```bash
npm install @supabase/supabase-js
```

Initialize in your admin app:
```js
import { createClient } from '@supabase/supabase-js'

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
)
```

**Get all blocked sites:**
```js
const { data } = await supabase.from('blocklists').select('*').order('created_at', { ascending: false })
```

**Add a site:**
```js
await supabase.from('blocklists').upsert({
  domain: 'example.com',
  category: 'social_media',
  methods: ['GET', 'POST'],
  risk_score: 60,
  reason: 'Productivity risk'
})
```

**Remove a site:**
```js
await supabase.from('blocklists').delete().eq('domain', 'example.com')
```

The Supabase trigger automatically bumps the version on every insert/delete, so the local script picks up changes within 60 seconds.

---

## Environment Variables for Vercel

In your Vercel project dashboard go to **Settings → Environment Variables** and add:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://xxxx.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | your anon key |

---

## How It All Works Together

1. Admin adds/removes a domain in the Vercel UI
2. Vercel calls Supabase SDK → writes to `blocklists` table
3. Supabase trigger fires → bumps `blocklist_meta.version`
4. `simple_blocker.py` polls version every 60s → detects change → fetches full list
5. Overwrites local `blocklist.json`
6. Existing 5-second cache refresh in `load_blocklist()` picks up the new file
7. Employee's next request is evaluated against the updated rules

---

## Local Development with Postico

Since Supabase uses Postgres, you can connect Postico directly to your Supabase DB:

- **Host:** `db.xxxx.supabase.co`
- **Port:** `5432`
- **Database:** `postgres`
- **User:** `postgres`
- **Password:** your Supabase DB password (set during project creation)

This lets you view and manually edit the `blocklists` table the same way you would a local database.
