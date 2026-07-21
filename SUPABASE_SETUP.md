# AnchorCV — Supabase + Stripe Setup Guide
# ==========================================
# Step-by-step instructions to configure your database, storage,
# and payment system. Complete this BEFORE deploying.

---

## STEP 1 — Create a Supabase Project

1. Go to https://supabase.com and click **New Project**
2. Choose your organization (or create one)
3. Name: `anchorcv`
4. Database Password: generate a strong one and save it
5. Region: pick closest to your users
6. Click **Create new project** and wait ~2 minutes

---

## STEP 2 — Create the `anchor_users` Table

In Supabase Dashboard → **SQL Editor** → New Query.
Paste and run this entire block:

```sql
-- Users table
CREATE TABLE IF NOT EXISTS public.anchor_users (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    first_name           TEXT NOT NULL,
    last_name            TEXT NOT NULL,
    email                TEXT NOT NULL UNIQUE,
    country              TEXT NOT NULL DEFAULT '',
    password_hash        TEXT NOT NULL,
    is_paid              BOOLEAN NOT NULL DEFAULT FALSE,
    storage_used_bytes   BIGINT NOT NULL DEFAULT 0,
    storage_quota_bytes  BIGINT NOT NULL DEFAULT 52428800,  -- 50 MB
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for fast email lookup
CREATE INDEX IF NOT EXISTS idx_anchor_users_email ON public.anchor_users (email);

-- Enable Row Level Security (important for production)
ALTER TABLE public.anchor_users ENABLE ROW LEVEL SECURITY;

-- Policy: service role can do everything (your backend uses service key)
CREATE POLICY "Service role full access" ON public.anchor_users
    FOR ALL USING (TRUE)
    WITH CHECK (TRUE);

-- Add a comment so future you knows what this is
COMMENT ON TABLE public.anchor_users IS 'AnchorCV SaaS user accounts';
```

Click **Run** → you should see "Success. No rows returned."

---

## STEP 3 — Create the `anchor_files` Table

In SQL Editor → New Query:

```sql
-- File records table (tracks what each user has saved to Storage)
CREATE TABLE IF NOT EXISTS public.anchor_files (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES public.anchor_users(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    path         TEXT NOT NULL,
    size_bytes   BIGINT NOT NULL DEFAULT 0,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Each user can only have one file per filename
    UNIQUE (user_id, filename)
);

-- Index for listing a user's files
CREATE INDEX IF NOT EXISTS idx_anchor_files_user ON public.anchor_files (user_id, created_at DESC);

ALTER TABLE public.anchor_files ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access" ON public.anchor_files
    FOR ALL USING (TRUE)
    WITH CHECK (TRUE);

COMMENT ON TABLE public.anchor_files IS 'AnchorCV cloud file registry';
```

---

## STEP 4 — Create the Storage Bucket

**Option A — Via Dashboard (recommended for first time):**

1. In Supabase Dashboard → **Storage** → **New Bucket**
2. Name: `user-files`  ← must match exactly (case-sensitive)
3. Public bucket: **OFF** (keep private — you'll use signed URLs)
4. Click **Create bucket**

**Option B — Via SQL:**

```sql
-- Create bucket (requires storage admin permissions)
INSERT INTO storage.buckets (id, name, public)
VALUES ('user-files', 'user-files', FALSE)
ON CONFLICT DO NOTHING;
```

**Storage RLS Policies (run in SQL Editor):**

```sql
-- Allow service role full access to storage objects
CREATE POLICY "Service role storage access"
ON storage.objects FOR ALL
USING (TRUE)
WITH CHECK (TRUE);
```

---

## STEP 5 — Get Your API Keys

In Supabase Dashboard → **Settings** → **API**:

| Key | Where to find it |
|-----|-----------------|
| `SUPABASE_URL` | "Project URL" field |
| `SUPABASE_SERVICE_KEY` | "service_role" key (NOT anon key — the long one) |

⚠️ **Use the service_role key** (not the anon key) because your backend needs to bypass RLS for user management.

---

## STEP 6 — Configure Streamlit Secrets

In your Streamlit Cloud dashboard → App settings → **Secrets**, add:

```toml
# Supabase
SUPABASE_URL = "https://xxxxxxxxxxxx.supabase.co"
SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

# OpenAI (hidden from users)
OPENAI_API_KEY = "sk-..."

# Stripe (optional — for payment processing)
STRIPE_SECRET_KEY = "sk_live_..."       # or sk_test_... for testing
STRIPE_PRICE_ID   = "price_..."        # your one-time price ID
APP_URL           = "https://your-app.streamlit.app"
```

For local development, create `.streamlit/secrets.toml` with the same content.
**Never commit this file to git.**

---

## STEP 7 — Install Dependencies

Add to your `requirements.txt`:

```
# Existing (already present)
streamlit
openai
pdfplumber
python-docx
plotly
reportlab
markdown2
beautifulsoup4
pillow
pytesseract
docxtpl
markdown2

# New additions
supabase>=2.0.0
gotrue>=2.0.0
stripe          # only if using Stripe
```

---

## STEP 8 — Rename Files and Deploy

```bash
# 1. Rename existing app.py → anchor_core.py
mv app.py anchor_core.py

# 2. auth_layer.py becomes the new app.py
mv auth_layer.py app.py

# 3. Your file structure should look like:
# app.py            ← auth_layer.py (new entry point)
# anchor_core.py    ← original app.py (the CV engine)
# docx_fix.py       ← DOCX builder module
# supabase_manager.py  ← (from EduBot — optional, not required)
# requirements.txt
# .streamlit/
#   secrets.toml    ← local only, never commit
```

---

## STEP 9 — Stripe Setup (Optional but Recommended)

1. Create account at https://stripe.com
2. Dashboard → **Products** → **Add product**
   - Name: `AnchorCV Premium`
   - Pricing model: **One time**
   - Price: `$9.00 USD`
3. Click **Save product**
4. Copy the **Price ID** (starts with `price_`) → paste into secrets as `STRIPE_PRICE_ID`
5. Dashboard → **Developers** → **API Keys**
   - Copy **Secret key** → paste into secrets as `STRIPE_SECRET_KEY`
6. For testing: use **Test mode** keys first (sk_test_...)

**Stripe Webhook (for reliable payment confirmation):**

```
Dashboard → Developers → Webhooks → Add endpoint
Endpoint URL: https://your-app.streamlit.app?paid=1
Events: checkout.session.completed
```

Note: The simple redirect-based payment confirmation in auth_layer.py is sufficient for most use cases. The webhook is for higher reliability at scale.

---

## STEP 10 — Verify Everything

Run this SQL to check your tables are ready:

```sql
-- Should return column names for both tables
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'anchor_users'
ORDER BY ordinal_position;

SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'anchor_files'
ORDER BY ordinal_position;

-- Check bucket exists
SELECT * FROM storage.buckets WHERE id = 'user-files';
```

Then test locally:

```bash
streamlit run app.py
```

You should see the sign-up screen with the dark navy + indigo background pattern.
Try creating an account → verify the row appears in Supabase Dashboard → Table Editor → anchor_users.

---

## QUICK REFERENCE — User Journey

```
Visit app.py (auth_layer.py)
        ↓
show_auth_screen()
  → Sign Up  → db_register_user() → anchor_users row created
  → Sign In  → db_login_user()    → credentials verified
        ↓
st.session_state["authenticated"] = True
        ↓
is_paid = False?
  → show_payment_screen()
  → Stripe Checkout URL
  → After payment → ?paid=1 redirect → db_mark_paid()
        ↓
is_paid = True → show_dashboard()
  → Open Resume Intelligence → show_app_screen() → anchor_core.main()
  → Open CV Generator        → show_app_screen() → anchor_core.main()
  → My Cloud Files           → show_files_screen()
        ↓
Generate output in anchor_core
  → [Download to Computer] — existing behavior unchanged
  → [Save to Cloud]        → storage_upload() → anchor_files row created
        ↓
Files appear in sidebar + My Cloud Files screen
Storage meter updates automatically
```

---

## TROUBLESHOOTING

| Problem | Cause | Fix |
|---------|-------|-----|
| "Database not connected" | Wrong key or URL in secrets | Double-check SUPABASE_SERVICE_KEY is the `service_role` key, not `anon` |
| "Relation anchor_users does not exist" | Table not created | Run Step 2 SQL again |
| "Bucket not found" | Storage bucket not created | Run Step 4 |
| "Row Level Security" error | Wrong key type | Use `service_role` key, not `anon` key |
| Stripe redirect not working | APP_URL wrong | Set APP_URL to exact deployed URL in secrets |
| "anchor_core not found" | File not renamed | Run `mv app.py anchor_core.py` |
