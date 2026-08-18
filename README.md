# Collecta — Credit Control & Collections

_White-label product (default brand **Collecta**); this deployment is configured for **Scientific Gate**. Change the product/organisation name under Admin → Settings → Branding._

A multi-user web version of the Excel credit-control workbook, backed by
**Neon** (serverless Postgres). Built with Flask + SQLAlchemy.

EGP and USD are reported **separately** throughout — balances are never summed
across currencies. The opening ledger is seeded from the base data
(**EGP 10,538,790 / USD 274,629** as at 29 Jul 2026).

## Features
- **Multi-user login** (Flask-Login; roles admin/user).
- **Dashboard** — per-currency KPIs, ageing summary, top-10 customers.
- **Debtors ledger** — live net balances and ageing buckets.
- **Collections** — record receipts with **transaction reference** and method.
- **New instalment / new customer** — with **account number, due date, reference, date raised**.
- **Customer accounts** — contact person, phone, email, address, **credit limit**.
- **Customer search** — by **account number or name** (also Cust Ref).
- **4-level reminder letters** — printable, escalate by oldest overdue age (L1 1–30d → L4 final demand 90+), with a "mark as sent" log.
- **Credit limits** — set per customer; over-limit customers are flagged everywhere.
- **Report writer** — filter by currency / bucket / status / security / amount / over-limit, with **CSV export**.

## Architecture
- Neon provides the **Postgres database**. The Flask app runs on any host that
  can reach Neon (Render, Railway, Fly.io, an EC2/VM, etc.). Set `DATABASE_URL`
  to your Neon connection string and the app uses it automatically.
- Tables are created by SQLAlchemy (`db.create_all()` in `seed.py`); `schema.sql`
  is provided for reference.

## Easiest install (Windows, no prerequisites)
Use the Windows installation pack: unzip it and double-click
**"Install and Run (Windows).bat"**. On first run it automatically installs
Python if the PC doesn't have it (per-user, no admin rights), sets up the app,
and opens the browser at http://127.0.0.1:8000. See "READ ME FIRST" in the pack.

The steps below are for manual/technical setup or non-Windows hosts.

## Create the Neon database
1. Sign up at neon.tech and create a project → you get a database (e.g. `neondb`).
2. Copy the connection string from **Dashboard → Connection Details**. Choose the
   **psycopg** variant, e.g.
   `postgresql://user:pass@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require`.
3. Put it in your environment as `DATABASE_URL`. The app auto-rewrites a
   `postgres://` prefix to `postgresql+psycopg://`; if you paste it yourself use
   the `postgresql+psycopg://…` form. Keep `?sslmode=require`.

## 2. Configure & seed
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then edit DATABASE_URL, SECRET_KEY, ADMIN_USER/PASS
export $(grep -v '^#' .env | xargs)                  # or use python-dotenv/your host's env UI
python seed.py                                        # creates tables, loads base data, makes admin
```
`seed.py` prints the base totals (EGP 10,538,790 / USD 274,629) so you can confirm
the load tied. To add/reset an admin later: `python seed.py --admin <user> <pass>`.

## 3. Run
Local:
```bash
python app.py            # http://localhost:5000  (log in with your admin user)
```
Production (gunicorn):
```bash
gunicorn app:app         # or: gunicorn wsgi:app
```

## 4. Deploy (example: Render or Railway)
1. Push this folder to a Git repo.
2. Create a new **Web Service**, build `pip install -r requirements.txt`,
   start command `gunicorn app:app`.
3. Add environment variables: `DATABASE_URL` (your Neon string), `SECRET_KEY`,
   `ADMIN_USER`, `ADMIN_PASS`.
4. Run the seed once (a one-off job/shell): `python seed.py`.
5. Open the service URL and log in.

## Notes
- **Local testing without Neon:** if `DATABASE_URL` is unset the app falls back to
  a local SQLite file — handy for a trial run, not for multi-user production.
- **Ageing is dynamic:** it re-ages against today's date automatically; the
  dashboard also has an "as at" date box for point-in-time views.
- **Add users:** currently via `seed.py --admin`. Adding a small admin "Users"
  screen is straightforward if you want self-service.
- Customer names are stored in Arabic (as in the source) and rendered
  right-to-left; everything else is English.

## Files
```
app.py            Flask app + all routes
models.py         SQLAlchemy models (users, customers, instalments, collections, reminders)
services.py       ageing/bucket logic, KPIs, reminder-level rules (matches the Excel exactly)
seed.py           schema creation + base-data load + admin user
seed_data.json    62 customers + 533 instalments extracted from the base report
templates/        Jinja2 + Bootstrap UI
schema.sql        reference DDL
requirements.txt / Procfile / wsgi.py / .env.example
```
