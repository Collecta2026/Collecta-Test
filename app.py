"""Scientific Gate — Credit Control System (web app, Neon Postgres backend).

Features:
  * Multi-user login (Flask-Login)
  * Dashboard (per-currency KPIs, ageing, top 10)  — EGP & USD kept separate
  * Debtors ledger with live net balances and ageing buckets
  * Weekly collections entry (transaction ref + method)
  * New customer / new instalment entry (account no., dates, references)
  * Customer contacts, phone/email, and CREDIT LIMIT (with over-limit flag)
  * Customer SEARCH by account number or name
  * 4-LEVEL reminder letters (printable) + reminder log
  * REPORT WRITER (flexible filters + CSV export; canned reports)
"""
import csv
import io
import os
import json
from functools import wraps
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv
load_dotenv()

from flask import (Flask, render_template, request, redirect, url_for, flash,
                   Response, abort)
from flask_login import (LoginManager, login_user, logout_user, login_required,
                         current_user)
from sqlalchemy import or_

from models import (db, User, Customer, Instalment, Collection, Reminder,
                    Setting, get_setting, set_setting, CallTask)
import services as svc
import emailer


def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*a, **kw)
    return wrapper


ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def write_env_value(key, value):
    """Persist a key to the .env file (used to switch DB to Neon from the UI)."""
    lines, found = [], False
    if os.path.exists(ENV_PATH):
        lines = open(ENV_PATH).read().splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
    if not found:
        lines.append(f"{key}={value}")
    open(ENV_PATH, "w").write("\n".join(lines) + "\n")


def parse_date(s):
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def parse_money(s):
    try:
        return Decimal(str(s).replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        return None


def report_download(export, title, headers, rows, base):
    """Return a CSV / Excel / PDF download from a simple (headers, rows) table."""
    import reportexport as rx
    if export == "xlsx":
        return Response(rx.xlsx_bytes(title, headers, rows), mimetype=rx.XLSX_MIME,
                        headers={"Content-Disposition": f"attachment; filename={base}.xlsx"})
    if export == "pdf":
        return Response(rx.pdf_bytes(title, headers, rows), mimetype=rx.PDF_MIME,
                        headers={"Content-Disposition": f"attachment; filename={base}.pdf"})
    buf = io.StringIO(); w = csv.writer(buf); w.writerow(headers)
    for r in rows:
        w.writerow(r)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={base}.csv"})


def _ensure_schema(db):
    """Safe, additive migrations: add new columns to existing tables if missing.
    Never drops or alters existing data."""
    from sqlalchemy import inspect, text
    try:
        insp = inspect(db.engine)
        tables = insp.get_table_names()
        if "users" in tables:
            cols = [c["name"] for c in insp.get_columns("users")]
            if "email" not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(200)"))
                db.session.commit()
        if "instalments" in tables:
            icols = [c["name"] for c in insp.get_columns("instalments")]
            if "account_type" not in icols:
                db.session.execute(text("ALTER TABLE instalments ADD COLUMN account_type VARCHAR(10)"))
                db.session.execute(text("UPDATE instalments SET account_type='MACHINE' WHERE account_type IS NULL"))
                db.session.commit()
            add_cols = [
                ("orig_fx_rate", "NUMERIC(12,4)"),
                ("state", "VARCHAR(12)"),
                ("converted_rate", "NUMERIC(12,4)"),
                ("linked_id", "INTEGER"),
                ("origin", "VARCHAR(12)"),
                ("agreement_ref", "VARCHAR(120)"),
            ]
            icols = [c["name"] for c in insp.get_columns("instalments")]
            for col, typ in add_cols:
                if col not in icols:
                    db.session.execute(text(f"ALTER TABLE instalments ADD COLUMN {col} {typ}"))
                    db.session.commit()
            # backfill sensible defaults
            db.session.execute(text("UPDATE instalments SET state='open' WHERE state IS NULL"))
            db.session.execute(text("UPDATE instalments SET origin='original' WHERE origin IS NULL"))
            db.session.commit()
        if "customers" in tables:
            ccols = [c["name"] for c in insp.get_columns("customers")]
            if "parts_credit_limit" not in ccols:
                db.session.execute(text("ALTER TABLE customers ADD COLUMN parts_credit_limit NUMERIC(16,2)"))
                db.session.commit()
    except Exception:
        db.session.rollback()


def create_app():
    # Works whether templates/static are in their folders OR flattened next to this file.
    _base = os.path.dirname(os.path.abspath(__file__))
    _tpl = 'templates' if os.path.isdir(os.path.join(_base, 'templates')) else '.'
    _stc = 'static' if os.path.isdir(os.path.join(_base, 'static')) else '.'
    app = Flask(__name__, template_folder=_tpl, static_folder=_stc, static_url_path='/static')
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")
    # Neon connection string, e.g.
    # postgresql+psycopg://user:pass@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require
    uri = os.environ.get("DATABASE_URL", "sqlite:///credit_control.db")
    # Force the installed driver (psycopg v3) for any Postgres/Neon URL form.
    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql+psycopg://", 1)
    elif uri.startswith("postgresql://") and "+psycopg" not in uri:
        uri = uri.replace("postgresql://", "postgresql+psycopg://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = uri
    engine_opts = {"pool_pre_ping": True}
    if uri.startswith("postgresql+psycopg://"):
        # Neon free tier scales to zero; recycle connections so a woken DB reconnects cleanly.
        engine_opts["pool_recycle"] = 300
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_opts
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    with app.app_context():
        try:
            db.create_all()          # ensure empty tables exist (Neon or SQLite)
            _ensure_schema(db)       # additive column migrations (safe)
            import permissions as _perms
            _perms.seed_matrix()     # seed the permission matrix on first run
        except Exception:
            pass
    login = LoginManager(app)
    login.login_view = "login"

    @login.user_loader
    def load_user(uid):
        return db.session.get(User, int(uid))

    # Jinja helpers
    @app.template_filter("money")
    def money(v, ccy=""):
        try:
            return f"{float(v):,.0f} {ccy}".strip()
        except (TypeError, ValueError):
            return "-"

    app.jinja_env.globals["today"] = date.today
    app.jinja_env.globals["BUCKETS"] = svc.BUCKETS

    @app.context_processor
    def inject_globals():
        try:
            fx = svc.get_fx()
        except Exception:
            fx = 50.5
        try:
            brand = svc.get_brand()
        except Exception:
            brand = {"product": svc.DEFAULT_PRODUCT, "org": svc.DEFAULT_ORG}
        return dict(fx_rate=fx, email_ready=_email_ready(),
                    product_name=brand["product"], org_name=brand["org"],
                    app_version=svc.VERSION, has_org_logo=svc.has_org_logo())

    def _email_ready():
        try:
            return emailer.email_configured()
        except Exception:
            return False

    def _needs_setup():
        try:
            return User.query.first() is None
        except Exception:
            return False

    @app.before_request
    def _first_run_guard():
        from flask import request as rq
        ep = (rq.endpoint or "")
        if ep in ("setup", "static", "login", "brand_org_logo") or ep.startswith("static"):
            return
        if _needs_setup():
            return redirect(url_for("setup"))

    @app.before_request
    def _permission_guard():
        """Central server-side enforcement: block routes the user's role/plan can't use."""
        import permissions as perms
        from flask import request as rq
        ep = (rq.endpoint or "")
        if ep in perms.OPEN_ENDPOINTS or ep.startswith("static"):
            return
        cap = perms.ENDPOINT_CAP.get(ep)
        if cap and current_user.is_authenticated and not perms.has_perm(current_user, cap):
            abort(403)

    def require_perm(cap):
        from functools import wraps as _wraps

        def deco(f):
            @_wraps(f)
            def w(*a, **k):
                import permissions as perms
                if not perms.has_perm(current_user, cap):
                    abort(403)
                return f(*a, **k)
            return w
        return deco

    def audit(action, target="", detail=""):
        from models import db, AuditLog
        try:
            who = (current_user.full_name or current_user.username) if current_user.is_authenticated else "system"
            db.session.add(AuditLog(actor=who, action=action, target=str(target)[:120], detail=str(detail)[:4000]))
            db.session.commit()
        except Exception:
            db.session.rollback()

    @app.context_processor
    def _inject_perms():
        import permissions as perms
        auth = current_user.is_authenticated
        pending_ct = 0
        if auth and perms.can_approve(current_user):
            try:
                from models import Approval
                pending_ct = Approval.query.filter_by(status="pending").count()
            except Exception:
                pending_ct = 0
        return dict(
            can=(lambda c: perms.has_perm(current_user, c)) if auth else (lambda c: False),
            dim_reason=(lambda c: perms.dim_reason(current_user, c)) if auth else (lambda c: "Sign in"),
            can_approve=(perms.can_approve(current_user) if auth else False),
            pending_approvals=pending_ct,
            ROLE_LABELS=perms.ROLE_LABELS, CAPABILITIES=perms.CAPABILITIES,
            subscription_plan=perms.get_plan(), PLAN_LABELS=perms.PLAN_LABELS,
        )

    # ---------------- First-run setup wizard ----------------
    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        if User.query.first() is not None:
            return redirect(url_for("login"))
        if request.method == "POST":
            import seed
            u = request.form.get("username", "admin").strip() or "admin"
            p = request.form.get("password", "").strip()
            if len(p) < 4:
                flash("Choose a password of at least 4 characters.", "danger")
                return render_template("setup.html")
            load = request.form.get("load_data") == "1"
            seed.initialise(u, p, load_data=load)
            if request.form.get("fx_rate"):
                set_setting("fx_rate", request.form["fx_rate"])
            flash("Setup complete — please sign in.", "success")
            return redirect(url_for("login"))
        db_kind = "Neon / PostgreSQL" if "postgres" in app.config["SQLALCHEMY_DATABASE_URI"] else "local SQLite (single device)"
        return render_template("setup.html", db_kind=db_kind)

    # ---------------- Auth ----------------
    def login_view():
        if request.method == "POST":
            u = User.query.filter_by(username=request.form["username"].strip()).first()
            if u and u.check_password(request.form["password"]):
                login_user(u)
                return redirect(request.args.get("next") or url_for("dashboard"))
            flash("Invalid username or password", "danger")
        return render_template("login.html")

    app.add_url_rule("/login", "login", login_view, methods=["GET", "POST"])

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    # ---------------- Dashboard ----------------
    @app.route("/")
    @login_required
    def dashboard():
        rd = parse_date(request.args.get("as_at")) or date.today()
        kpis = svc.dashboard_kpis(rd)
        kpis_type = svc.dashboard_kpis_by_type(rd)
        ageing = svc.ageing_summary(rd)
        coll = svc.collections_summary()
        top = {c: sorted([b for b in svc.customer_balances(rd) if b["currency"] == c],
                         key=lambda x: x["total"], reverse=True)[:10] for c in ("EGP", "USD")}
        eq = svc.egp_equivalent(rd)
        legal = svc.legal_summary(rd)
        return render_template("dashboard.html", kpis=kpis, ageing=ageing, coll=coll,
                               top=top, as_at=rd, eq=eq, legal=legal, kpis_type=kpis_type)

    # ---------------- Overdue customers drill-down (from dashboard) ----------------
    @app.route("/overdue/<ccy>")
    @login_required
    def overdue_customers(ccy):
        ccy = ccy.upper()
        if ccy not in ("EGP", "USD"):
            abort(404)
        rd = parse_date(request.args.get("as_at")) or date.today()
        bals = [b for b in svc.customer_balances(rd) if b["currency"] == ccy and b["overdue"] > 0]
        bals.sort(key=lambda x: x["overdue"], reverse=True)
        custs = {c.id: c for c in Customer.query.all()}
        owners = {u.id: (u.full_name or u.username) for u in User.query.all()}

        def worst_bucket(bk):
            for b in reversed(svc.OVERDUE_BUCKETS):
                if bk.get(b, 0) > 0:
                    return b
            return ""
        rows = []
        for b in bals:
            cust = custs.get(b["customer_id"])
            rows.append(dict(b, phone=(cust.phone if cust else ""),
                             contact=(cust.contact_person if cust else ""),
                             owner=(owners.get(cust.owner_id) if cust and cust.owner_id else ""),
                             worst=worst_bucket(b["buckets"])))
        export = request.args.get("export")
        if export in ("csv", "xlsx", "pdf"):
            headers = ["Cust Ref", "Customer", "Ledger Owner", "Phone", "Total Outstanding",
                       "Overdue", "Oldest (days)", "Worst Bucket"]
            data = [[r["cust_ref"], r["customer"], r["owner"], r["phone"], r["total"],
                     r["overdue"], r["oldest"], r["worst"]] for r in rows]
            data.append(["", "TOTAL", "", "", "", sum(r["overdue"] for r in rows), "", ""])
            return report_download(export, f"Overdue Customers — {ccy}", headers, data,
                                   f"overdue_customers_{ccy.lower()}")
        total_overdue = sum(r["overdue"] for r in rows)
        return render_template("overdue_customers.html", rows=rows, ccy=ccy,
                               total_overdue=total_overdue, as_at=rd)

    # ---------------- Ledger ----------------
    @app.route("/ledger")
    @login_required
    def ledger():
        rd = date.today()
        ccy = request.args.get("ccy") or ""
        status = request.args.get("status") or ""
        atype = (request.args.get("type") or "").upper()
        if atype not in ("MACHINE", "PARTS"):
            atype = ""
        rows = svc.instalment_rows(report_date=rd, currency=(ccy or None), account_type=(atype or None))
        if status:
            rows = [r for r in rows if r["status"] == status]
        rows.sort(key=lambda r: (r["currency"], -r["net"]))
        export = request.args.get("export")
        if export in ("csv", "xlsx", "pdf"):
            headers = ["Instalment ID", "Cust Ref", "Account No.", "Customer", "Ccy", "Type", "Original",
                       "Received", "Net Outstanding", "Due Date", "Days Overdue", "Bucket", "Status", "Security"]
            data = [[r["inst_id"], r["cust_ref"], r["account_no"], r["customer"], r["currency"], r["account_type"],
                     r["original"], r["received"], r["net"], r["due_date"], r["days_overdue"],
                     r["bucket"], r["status"], r["security"]] for r in rows]
            return report_download(export, "Debtors Ledger", headers, data, "debtors_ledger")
        return render_template("ledger.html", rows=rows, ccy=ccy, status=status, atype=atype)

    # ---------------- Collections ----------------
    @app.route("/collections", methods=["GET", "POST"])
    @login_required
    def collections():
        if request.method == "POST":
            inst = Instalment.query.filter_by(inst_id=request.form["inst_id"].strip()).first()
            amt = parse_money(request.form["amount"])
            if not inst or not amt or amt <= 0:
                flash("Pick a valid Instalment ID and a positive amount.", "danger")
            else:
                con_date = parse_date(request.form.get("collected_on")) or date.today()
                c = Collection(customer_id=inst.customer_id, instalment_id=inst.id,
                               txn_ref=request.form.get("txn_ref"), amount=amt,
                               currency=inst.currency, method=request.form.get("method"),
                               collected_on=con_date,
                               bucket_at_collection=svc.bucket_at(inst.due_date, con_date),
                               received_by=(current_user.full_name or current_user.username),
                               comments=request.form.get("comments"))
                db.session.add(c)
                db.session.commit()
                flash(f"Recorded {amt:,.2f} {inst.currency} against {inst.inst_id}.", "success")
            return redirect(url_for("collections"))
        recent = Collection.query.order_by(Collection.id.desc()).limit(25).all()
        insts = Instalment.query.order_by(Instalment.inst_id).all()
        return render_template("collections.html", recent=recent, insts=insts)

    # ---------------- New instalment / new customer ----------------
    @app.route("/instalment/new", methods=["GET", "POST"])
    @login_required
    def new_instalment():
        if request.method == "POST":
            f = request.form
            ref_in = f.get("cust_ref", "").strip()
            cust = Customer.query.filter_by(cust_ref=ref_in).first() if ref_in else None
            if not cust:                       # create a new customer on the fly
                if not f.get("customer") or not f.get("currency"):
                    flash("New customer needs a name and currency.", "danger")
                    return redirect(url_for("new_instalment"))
                new_ref = ref_in or svc.next_customer_ref(f["currency"])   # blank -> auto code
                cust = Customer(cust_ref=new_ref, account_no=f.get("account_no"),
                                name=f["customer"].strip(), currency=f["currency"],
                                owner_id=(int(f["owner_id"]) if f.get("owner_id") else svc.default_owner_for(f["currency"])))
                db.session.add(cust)
                db.session.flush()
            amt = parse_money(f["original_amount"])
            if Instalment.query.filter_by(inst_id=f["inst_id"].strip()).first():
                flash("That Instalment ID already exists.", "danger")
            elif not amt or amt <= 0:
                flash("Enter a positive Original Outstanding amount.", "danger")
            else:
                db.session.add(Instalment(
                    inst_id=f["inst_id"].strip(), customer_id=cust.id, currency=cust.currency,
                    original_amount=amt, due_date=parse_date(f.get("due_date")),
                    security=f.get("security"), reference=f.get("reference"),
                    date_raised=parse_date(f.get("date_raised")) or date.today(),
                    description=f.get("reference")))
                db.session.commit()
                flash(f"Added instalment {f['inst_id']} for {cust.name}.", "success")
                return redirect(url_for("ledger"))
        customers = Customer.query.order_by(Customer.cust_ref).all()
        return render_template("new_instalment.html", customers=customers,
                               users=User.query.order_by(User.username).all())

    # ---------------- Parts & Accessories sale (short-term credit) ----------------
    @app.route("/parts/new", methods=["GET", "POST"])
    @login_required
    def parts_new():
        from datetime import timedelta
        if request.method == "POST":
            f = request.form
            ref_in = f.get("cust_ref", "").strip()
            cust = Customer.query.filter_by(cust_ref=ref_in).first() if ref_in else None
            if not cust:
                flash("Choose an existing customer for a parts sale.", "danger")
                return redirect(url_for("parts_new"))
            amt = parse_money(f.get("amount"))
            if not amt or amt <= 0:
                flash("Enter a positive amount.", "danger")
                return redirect(url_for("parts_new"))
            # terms -> due date
            terms = f.get("terms", "30")
            raised = parse_date(f.get("date_raised")) or date.today()
            if terms == "custom":
                due = parse_date(f.get("due_date")) or (raised + timedelta(days=30))
            else:
                days = 60 if terms == "60" else 30
                due = raised + timedelta(days=days)
            ccy = f.get("currency") or cust.currency
            iid = svc.next_parts_inst_id(cust)
            db.session.add(Instalment(
                inst_id=iid, customer_id=cust.id, currency=ccy, account_type="PARTS",
                original_amount=amt, due_date=due, security=None,
                reference=f.get("invoice_ref"), date_raised=raised,
                description=f.get("description") or "Spare parts / accessories"))
            db.session.commit()
            audit("parts_sale_created", cust.cust_ref, f"{ccy} {amt} due {due} ({iid})")
            # parts credit-limit warning (non-blocking)
            parts_out = sum(r["net"] for r in svc.instalment_rows(currency=ccy, account_type="PARTS")
                            if r["customer_id"] == cust.id)
            if cust.parts_credit_limit and parts_out > float(cust.parts_credit_limit):
                flash(f"Recorded {iid}. NOTE: parts balance {parts_out:,.0f} {ccy} now exceeds the "
                      f"parts credit limit {float(cust.parts_credit_limit):,.0f} {ccy}.", "warning")
            else:
                flash(f"Parts sale {iid} recorded for {cust.name} ({ccy} {amt:,.0f}, due {due}).", "success")
            return redirect(url_for("customer_detail", cid=cust.id))
        customers = Customer.query.order_by(Customer.cust_ref).all()
        return render_template("parts_new.html", customers=customers)

    # ================= Upload 3: reschedule / add-machine / currency conversion =================

    # ---- (b) Add a new machine deal — contract-backed, the contract IS the authorisation ----
    @app.route("/machine/new", methods=["GET", "POST"])
    @login_required
    def machine_new():
        from datetime import timedelta
        if request.method == "POST":
            f = request.form
            cust = Customer.query.filter_by(cust_ref=f.get("cust_ref", "").strip()).first()
            if not cust:
                flash("Choose an existing customer.", "danger")
                return redirect(url_for("machine_new"))
            total = parse_money(f.get("total"))
            count = int(f.get("count") or 1)
            contract = (f.get("contract_ref") or "").strip()
            if not total or total <= 0:
                flash("Enter a positive contract value.", "danger")
                return redirect(url_for("machine_new"))
            if not contract:
                flash("A signed-contract reference is required — the contract is the authorisation.", "danger")
                return redirect(url_for("machine_new"))
            ccy = f.get("currency") or cust.currency
            first = parse_date(f.get("first_due")) or (date.today() + timedelta(days=30))
            freq = int(f.get("freq_days") or 30)
            fx = parse_money(f.get("orig_fx_rate")) if ccy == "USD" and f.get("orig_fx_rate") else None
            sched = svc.build_schedule(total, count, first, freq)
            for s in sched:
                iid = svc.next_deal_inst_id(cust, "MC")
                db.session.add(Instalment(
                    inst_id=iid, customer_id=cust.id, currency=ccy, account_type="MACHINE",
                    original_amount=s["amount"], due_date=s["due_date"],
                    security=f.get("security") or "Contract", reference=contract,
                    agreement_ref=contract, origin="machine", state="open",
                    orig_fx_rate=fx, date_raised=date.today(),
                    description=f.get("description") or "New machine deal"))
                db.session.flush()
            db.session.commit()
            audit("machine_deal_added", cust.cust_ref,
                  f"{ccy} {total} over {count} instalments, contract {contract}")
            flash(f"New machine deal booked for {cust.name}: {count} instalments, "
                  f"{ccy} {total:,.0f}, contract {contract}.", "success")
            return redirect(url_for("customer_detail", cid=cust.id))
        customers = Customer.query.order_by(Customer.cust_ref).all()
        return render_template("machine_new.html", customers=customers)

    # ---- (a) Date reschedule / new-deal terms — routed for CFO/MD approval ----
    @app.route("/reschedule/<int:cid>", methods=["GET", "POST"])
    @login_required
    def reschedule_request(cid):
        cust = db.session.get(Customer, cid) or abort(404)
        if request.method == "POST":
            from models import Approval
            f = request.form
            ids = request.form.getlist("inst_ids")
            if not ids:
                flash("Select at least one outstanding instalment to reschedule.", "danger")
                return redirect(url_for("reschedule_request", cid=cid))
            open_rows = {str(r["id"]): r for r in svc.open_instalments(cid)}
            picked = [open_rows[i] for i in ids if i in open_rows]
            ccy = picked[0]["currency"] if picked else cust.currency
            total = sum(r["net"] for r in picked)
            count = int(f.get("count") or 1)
            first = parse_date(f.get("first_due")) or date.today()
            freq = int(f.get("freq_days") or 30)
            sched = svc.build_schedule(total, count, first, freq)
            payload = dict(action="date_reschedule", customer_id=cid, currency=ccy,
                           source_ids=[r["id"] for r in picked], total=total,
                           schedule=[dict(amount=s["amount"], due_date=s["due_date"].isoformat()) for s in sched],
                           agreement_ref=(f.get("agreement_ref") or "").strip())
            ap = Approval(kind="date_reschedule", requester=(current_user.full_name or current_user.username),
                          requester_id=current_user.id, customer_id=cid,
                          summary=f"Reschedule {ccy} {total:,.0f} for {cust.name} into {count} instalments",
                          payload=json.dumps(payload), reason=(f.get("reason") or ""))
            db.session.add(ap); db.session.commit()
            audit("reschedule_requested", cust.cust_ref, ap.summary)
            _notify_approvers("reschedule", ap.summary, current_user.id)
            flash("Reschedule submitted for CFO/MD approval. No ledger change until approved.", "success")
            return redirect(url_for("customer_detail", cid=cid))
        rows = svc.open_instalments(cid)
        return render_template("reschedule.html", cust=cust, rows=rows)

    # ---- (c) USD→EGP currency conversion with FX-loss flag — routed for CFO/MD approval ----
    @app.route("/convert/<int:cid>", methods=["GET", "POST"])
    @login_required
    def convert_request(cid):
        cust = db.session.get(Customer, cid) or abort(404)
        usd_rows = svc.open_instalments(cid, currency="USD")
        if request.method == "POST":
            from models import Approval
            f = request.form
            ids = request.form.getlist("inst_ids")
            picked = [r for r in usd_rows if str(r["id"]) in ids]
            if not picked:
                flash("Select at least one USD instalment to convert.", "danger")
                return redirect(url_for("convert_request", cid=cid))
            agreed = parse_money(f.get("agreed_rate"))
            if not agreed or agreed <= 0:
                flash("Enter the agreed USD→EGP conversion rate.", "danger")
                return redirect(url_for("convert_request", cid=cid))
            agreed = float(agreed)
            # confirm-on-first-use: legacy USD instalments with no stored original rate
            legacy_rate = float(parse_money(f.get("legacy_rate"))) if f.get("legacy_rate") else None
            items = []
            for r in picked:
                orig = r["orig_fx_rate"] if r["orig_fx_rate"] is not None else legacy_rate
                items.append(dict(inst_id=r["inst_id"], net=r["net"],
                                  orig_fx_rate=(float(orig) if orig is not None else None), id=r["id"]))
            calc = svc.compute_conversion(items, agreed)
            reschedule = (f.get("mode") == "convert_reschedule")
            count = int(f.get("count") or 1) if reschedule else 1
            first = parse_date(f.get("first_due")) or date.today()
            freq = int(f.get("freq_days") or 30)
            sched = svc.build_schedule(calc["total_new_egp"], count, first, freq) if reschedule else \
                    [dict(amount=calc["total_new_egp"], due_date=first)]
            payload = dict(action="currency_conversion", customer_id=cid,
                           source_ids=[it["id"] for it in items],
                           orig_rates={str(it["id"]): it["orig_fx_rate"] for it in items},
                           agreed_rate=agreed, legacy_rate=legacy_rate,
                           total_usd=calc["total_usd"], total_new_egp=calc["total_new_egp"],
                           total_orig_egp=calc["total_orig_egp"], fx_diff=calc["fx_diff"],
                           schedule=[dict(amount=s["amount"], due_date=s["due_date"].isoformat()) for s in sched],
                           agreement_ref=(f.get("agreement_ref") or "").strip())
            loss_tag = ""
            if calc["is_loss"]:
                loss_tag = f" — FX LOSS {abs(calc['fx_diff']):,.0f} EGP"
            elif calc["is_gain"]:
                loss_tag = f" — FX gain {calc['fx_diff']:,.0f} EGP"
            ap = Approval(kind="currency_conversion", requester=(current_user.full_name or current_user.username),
                          requester_id=current_user.id, customer_id=cid,
                          summary=(f"Convert USD {calc['total_usd']:,.0f} → EGP {calc['total_new_egp']:,.0f} "
                                   f"@ {agreed:g} for {cust.name}{loss_tag}"),
                          payload=json.dumps(payload), reason=(f.get("reason") or ""))
            db.session.add(ap); db.session.commit()
            audit("conversion_requested", cust.cust_ref, ap.summary)
            _notify_approvers("currency conversion", ap.summary, current_user.id)
            flash("Currency conversion submitted for CFO/MD approval. No ledger change until approved.", "success")
            return redirect(url_for("customer_detail", cid=cid))
        # GET — live preview if an agreed rate was passed
        agreed = request.args.get("agreed_rate")
        legacy = request.args.get("legacy_rate")
        calc = None
        needs_legacy = any(r["orig_fx_rate"] is None for r in usd_rows)
        if agreed:
            try:
                a = float(agreed); lg = float(legacy) if legacy else None
                items = [dict(inst_id=r["inst_id"], net=r["net"],
                              orig_fx_rate=(r["orig_fx_rate"] if r["orig_fx_rate"] is not None else lg))
                         for r in usd_rows]
                calc = svc.compute_conversion(items, a)
            except ValueError:
                calc = None
        return render_template("convert.html", cust=cust, rows=usd_rows, calc=calc,
                               needs_legacy=needs_legacy, fx_default=svc.get_fx())

    @app.route("/reports/conversions")
    @login_required
    def conversions_report():
        rows = svc.conversion_report_rows()
        export = request.args.get("export")
        if export in ("csv", "xlsx", "pdf"):
            headers = ["Source ID", "Customer", "Cust Ref", "USD Converted", "Original Rate",
                       "Agreed Rate", "Original EGP Value", "New EGP Value", "FX Gain/(Loss)", "Agreement Ref"]
            data = [[r["inst_id"], r["customer"], r["cust_ref"], r["usd"], r["orig_rate"],
                     r["agreed_rate"], r["orig_egp"], r["new_egp"], r["fx_diff"], r["agreement_ref"]]
                    for r in rows]
            return report_download(export, "Currency Conversions", headers, data, "currency_conversions")
        return render_template("conversions_report.html", rows=rows)

    # ---- customer pickers so Reschedule / Convert are reachable from the menu ----
    @app.route("/reschedule", methods=["GET", "POST"])
    @login_required
    def reschedule_picker():
        if request.method == "POST" and request.form.get("cid"):
            return redirect(url_for("reschedule_request", cid=int(request.form["cid"])))
        customers = Customer.query.order_by(Customer.cust_ref).all()
        return render_template("pick_customer.html", customers=customers, post_to="reschedule_picker",
                               title="Reschedule instalments",
                               intro="Choose the customer whose outstanding instalments you want to reschedule.")

    @app.route("/convert", methods=["GET", "POST"])
    @login_required
    def convert_picker():
        if request.method == "POST" and request.form.get("cid"):
            return redirect(url_for("convert_request", cid=int(request.form["cid"])))
        # only customers that actually have open USD instalments
        usd_ids = {r["customer_id"] for r in svc.instalment_rows(currency="USD")
                   if r["state"] == "open" and r["net"] > 0}
        customers = [c for c in Customer.query.order_by(Customer.cust_ref).all() if c.id in usd_ids]
        return render_template("pick_customer.html", customers=customers, post_to="convert_picker",
                               title="Currency conversion (USD→EGP)",
                               intro="Choose the customer whose remaining USD balance you want to convert to EGP.")

    # ---------------- Customers: list, search, detail, edit ----------------
    @app.route("/customers")
    @login_required
    def customers():
        q = (request.args.get("q") or "").strip()
        query = Customer.query
        if q:                                   # search by account number OR name OR ref
            like = f"%{q}%"
            query = query.filter(or_(Customer.account_no.ilike(like),
                                     Customer.name.ilike(like),
                                     Customer.cust_ref.ilike(like)))
        rows = query.order_by(Customer.currency, Customer.name).all()
        bal = {c["customer_id"]: c for c in svc.customer_balances()}
        return render_template("customers.html", rows=rows, bal=bal, q=q)

    @app.route("/customer/<int:cid>", methods=["GET", "POST"])
    @login_required
    def customer_detail(cid):
        cust = db.session.get(Customer, cid) or abort(404)
        if request.method == "POST":
            f = request.form
            cust.contact_person = f.get("contact_person")
            cust.phone = f.get("phone")
            cust.email = f.get("email")
            cust.address = f.get("address")
            cust.account_no = f.get("account_no") or cust.account_no
            cust.credit_limit = parse_money(f.get("credit_limit")) if f.get("credit_limit") else None
            cust.parts_credit_limit = parse_money(f.get("parts_credit_limit")) if f.get("parts_credit_limit") else None
            if "owner_id" in f:
                cust.owner_id = int(f["owner_id"]) if f.get("owner_id") else None
            cust.notes = f.get("notes")
            db.session.commit()
            flash("Customer updated.", "success")
            return redirect(url_for("customer_detail", cid=cid))
        allrows = [r for r in svc.instalment_rows() if r["customer_id"] == cid]
        allrows.sort(key=lambda r: (r["due_date"] or date.max))

        def block(pred):
            rs = [r for r in allrows if pred(r)]
            return dict(rows=rs, total=sum(r["net"] for r in rs),
                        overdue=sum(r["net"] for r in rs if r["bucket"] in svc.OVERDUE_BUCKETS))
        machine = block(lambda r: r["account_type"] == "MACHINE")
        parts = block(lambda r: r["account_type"] == "PARTS")
        combined = block(lambda r: True)
        rows = allrows
        total = combined["total"]
        overdue = combined["overdue"]
        limit = float(cust.credit_limit) if cust.credit_limit is not None else None
        parts_limit = float(cust.parts_credit_limit) if cust.parts_credit_limit is not None else None
        over_limit = (limit is not None and machine["total"] > limit)
        parts_over = (parts_limit is not None and parts["total"] > parts_limit)
        pays = Collection.query.filter_by(customer_id=cid).order_by(Collection.id.desc()).all()
        notes = svc.customer_notes(cid)
        return render_template("customer_detail.html", cust=cust, rows=rows, total=total,
                               overdue=overdue, limit=limit, over_limit=over_limit, pays=pays,
                               machine=machine, parts=parts, combined=combined,
                               parts_limit=parts_limit, parts_over=parts_over,
                               notes=notes, users=User.query.order_by(User.username).all(),
                               legal_stages=svc.LEGAL_STAGES,
                               default_pct=svc.legal_provision_default())

    # ---------------- 4-level reminder letters ----------------
    @app.route("/reminders")
    @login_required
    def reminders():
        cands = svc.reminder_candidates()
        return render_template("reminders.html", cands=cands, levels=svc.REMINDER_LEVELS)

    @app.route("/reminder/<int:cid>")
    @login_required
    def reminder_letter(cid):
        cust = db.session.get(Customer, cid) or abort(404)
        rows = [r for r in svc.instalment_rows() if r["customer_id"] == cid
                and r["bucket"] in svc.OVERDUE_BUCKETS]
        overdue = sum(r["net"] for r in rows)
        total = sum(r["net"] for r in svc.instalment_rows() if r["customer_id"] == cid)
        oldest = max((r["days_overdue"] or 0) for r in rows) if rows else 0
        level = int(request.args.get("level") or svc.reminder_level_for_days(oldest))
        level = max(1, min(4, level))
        meta = svc.REMINDER_LEVELS[level]
        return render_template("reminder_letter.html", cust=cust, rows=rows, overdue=overdue,
                               total=total, level=level, meta=meta, oldest=oldest)

    @app.route("/reminder/<int:cid>/log", methods=["POST"])
    @login_required
    def reminder_log(cid):
        cust = db.session.get(Customer, cid) or abort(404)
        level = int(request.form.get("level", 1))
        db.session.add(Reminder(customer_id=cid, level=level, currency=cust.currency,
                                amount_overdue=parse_money(request.form.get("overdue") or "0"),
                                sent_by=(current_user.full_name or current_user.username),
                                notes=request.form.get("notes")))
        db.session.commit()
        flash(f"Level {level} reminder logged for {cust.name}.", "success")
        return redirect(url_for("reminders"))

    # ---------------- Aged analysis ----------------
    @app.route("/aged/<ccy>")
    @login_required
    def aged(ccy):
        ccy = ccy.upper()
        if ccy not in ("EGP", "USD"):
            abort(404)
        m = svc.aged_matrix(ccy)
        export = request.args.get("export")
        if export in ("csv", "xlsx", "pdf"):
            headers = ["Cust Ref", "Customer"] + m["buckets"] + ["Total"]
            data = [[c["cust_ref"], c["customer"]] + [c["buckets"].get(b, 0.0) for b in m["buckets"]] + [c["total"]]
                    for c in m["customers"]]
            data.append(["TOTAL", ""] + [m["totals"].get(b, 0.0) for b in m["buckets"]] + [m["grand"]])
            return report_download(export, f"Aged Debtors Analysis — {ccy}", headers, data, f"aged_{ccy.lower()}")
        return render_template("aged.html", m=m, ccy=ccy)

    # ---------------- Report writer ----------------
    @app.route("/reports", methods=["GET"])
    @login_required
    def reports():
        f = request.args
        ran = "run" in f
        ccy = f.get("ccy") or ""
        bucket = f.get("bucket") or ""
        status = f.get("status") or ""
        security = f.get("security") or ""
        over_only = f.get("over_limit") == "1"
        min_amt = parse_money(f.get("min_amount")) if f.get("min_amount") else None
        rows, totals = [], {}
        if ran:
            rows = svc.instalment_rows(currency=(ccy or None))
            if bucket:
                rows = [r for r in rows if r["bucket"] == bucket]
            if status:
                rows = [r for r in rows if r["status"] == status]
            if security:
                rows = [r for r in rows if (r["security"] or "") == security]
            if min_amt is not None:
                rows = [r for r in rows if r["net"] >= float(min_amt)]
            if over_only:
                lim = {c.id: float(c.credit_limit) for c in Customer.query
                       if c.credit_limit is not None}
                bal = {c["customer_id"]: c["total"] for c in svc.customer_balances()}
                keep = {cid for cid, l in lim.items() if bal.get(cid, 0) > l}
                rows = [r for r in rows if r["customer_id"] in keep]
            rows.sort(key=lambda r: (r["currency"], -r["net"]))
            for c in ("EGP", "USD"):
                totals[c] = sum(r["net"] for r in rows if r["currency"] == c)
            export = f.get("export")
            if export in ("csv", "xlsx", "pdf"):
                headers = ["Instalment ID", "Cust Ref", "Account No.", "Customer", "Ccy",
                           "Original", "Received", "Net Outstanding", "Due Date",
                           "Days Overdue", "Bucket", "Status", "Security", "Reference"]
                data = [[r["inst_id"], r["cust_ref"], r["account_no"], r["customer"],
                         r["currency"], r["original"], r["received"], r["net"],
                         r["due_date"], r["days_overdue"], r["bucket"], r["status"],
                         r["security"], r["reference"]] for r in rows]
                if export == "csv":
                    return _csv_export(rows)
                import reportexport as rx
                title = "Aged Debtors Report"
                if export == "xlsx":
                    return Response(rx.xlsx_bytes(title, headers, data), mimetype=rx.XLSX_MIME,
                                    headers={"Content-Disposition": "attachment; filename=aged_debtors.xlsx"})
                return Response(rx.pdf_bytes(title, headers, data), mimetype=rx.PDF_MIME,
                                headers={"Content-Disposition": "attachment; filename=aged_debtors.pdf"})
        securities = [s[0] for s in db.session.query(Instalment.security).distinct() if s[0]]
        return render_template("reports.html", rows=rows, totals=totals, ran=ran,
                               f=f, securities=sorted(securities))

    def _csv_export(rows):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Instalment ID", "Cust Ref", "Account No.", "Customer", "Ccy",
                    "Original", "Received", "Net Outstanding", "Due Date",
                    "Days Overdue", "Bucket", "Status", "Security", "Reference"])
        for r in rows:
            w.writerow([r["inst_id"], r["cust_ref"], r["account_no"], r["customer"],
                        r["currency"], r["original"], r["received"], r["net"],
                        r["due_date"], r["days_overdue"], r["bucket"], r["status"],
                        r["security"], r["reference"]])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=credit_report.csv"})

    # ---------------- Credit-limit report ----------------
    @app.route("/credit-limits")
    @login_required
    def credit_limits():
        bal = {c["customer_id"]: c for c in svc.customer_balances()}
        rows = []
        for cust in Customer.query.order_by(Customer.currency, Customer.name).all():
            b = bal.get(cust.id, {"total": 0.0, "overdue": 0.0})
            lim = float(cust.credit_limit) if cust.credit_limit is not None else None
            rows.append(dict(cust=cust, total=b["total"], overdue=b["overdue"], limit=lim,
                             over=(lim is not None and b["total"] > lim),
                             headroom=(None if lim is None else lim - b["total"])))
        export = request.args.get("export")
        if export in ("csv", "xlsx", "pdf"):
            headers = ["Cust Ref", "Customer", "Ccy", "Outstanding", "Overdue", "Credit Limit", "Headroom", "Over Limit?"]
            data = [[r["cust"].cust_ref, r["cust"].name, r["cust"].currency, r["total"], r["overdue"],
                     ("" if r["limit"] is None else r["limit"]),
                     ("" if r["headroom"] is None else r["headroom"]),
                     ("YES" if r["over"] else "")] for r in rows]
            return report_download(export, "Credit Limits", headers, data, "credit_limits")
        return render_template("credit_limits.html", rows=rows)

    # ---------------- Dedicated customer setup screen ----------------
    @app.route("/customer/new", methods=["GET", "POST"])
    @login_required
    def customer_new():
        if request.method == "POST":
            f = request.form
            ref = f.get("cust_ref", "").strip()
            if not f.get("name") or not f.get("currency"):
                flash("Name and currency are required.", "danger")
            elif ref and Customer.query.filter_by(cust_ref=ref).first():
                flash("That Cust Ref already exists.", "danger")
            else:
                if not ref:                      # blank -> auto-assign next unused code
                    ref = svc.next_customer_ref(f["currency"])
                db.session.add(Customer(
                    cust_ref=ref, account_no=f.get("account_no"), name=f["name"].strip(),
                    currency=f["currency"], contact_person=f.get("contact_person"),
                    phone=f.get("phone"), email=f.get("email"), address=f.get("address"),
                    credit_limit=(parse_money(f.get("credit_limit")) if f.get("credit_limit") else None),
                    owner_id=(int(f["owner_id"]) if f.get("owner_id") else svc.default_owner_for(f["currency"])),
                    notes=f.get("notes")))
                db.session.commit()
                flash(f"Customer {ref} created.", "success")
                return redirect(url_for("customers"))
        # suggest next reference per currency
        nxt = {ccy: svc.next_customer_ref(ccy) for ccy in ("EGP", "USD")}
        return render_template("customer_new.html", nxt=nxt, users=User.query.order_by(User.username).all())

    # ---------------- User administration (admin only) ----------------
    @app.route("/users")
    @login_required
    @admin_required
    def users():
        return render_template("users.html", rows=User.query.order_by(User.username).all())

    @app.route("/users/new", methods=["POST"])
    @login_required
    @admin_required
    def users_new():
        un = request.form["username"].strip()
        if not un or User.query.filter_by(username=un).first():
            flash("Username missing or already exists.", "danger")
        elif len(request.form.get("password", "")) < 4:
            flash("Password too short.", "danger")
        else:
            u = User(username=un, full_name=request.form.get("full_name"),
                     email=(request.form.get("email") or None),
                     role=request.form.get("role", "credit_control"))
            u.set_password(request.form["password"])
            db.session.add(u)
            db.session.commit()
            audit("user_created", un, f"role={u.role}, email={u.email or '-'}")
            flash(f"User {un} created.", "success")
        return redirect(url_for("users"))

    @app.route("/users/<int:uid>/update", methods=["POST"])
    @login_required
    @require_perm("users_admin")
    def users_update(uid):
        u = db.session.get(User, uid) or abort(404)
        old = f"role={u.role}, email={u.email or '-'}"
        u.full_name = request.form.get("full_name") or u.full_name
        u.email = request.form.get("email") or None
        new_role = request.form.get("role")
        # never allow removing the last admin
        if new_role and new_role != u.role:
            if u.role == "admin" and User.query.filter_by(role="admin").count() <= 1 and new_role != "admin":
                flash("You cannot change the role of the only administrator.", "danger")
                return redirect(url_for("users"))
            u.role = new_role
        db.session.commit()
        audit("user_updated", u.username, f"{old} -> role={u.role}, email={u.email or '-'}")
        flash(f"User {u.username} updated.", "success")
        return redirect(url_for("users"))

    @app.route("/users/<int:uid>/delete", methods=["POST"])
    @login_required
    @admin_required
    def users_delete(uid):
        u = db.session.get(User, uid) or abort(404)
        if u.id == current_user.id:
            flash("You cannot delete your own account.", "danger")
        else:
            db.session.delete(u)
            db.session.commit()
            flash("User deleted.", "success")
        return redirect(url_for("users"))

    @app.route("/users/<int:uid>/reset", methods=["POST"])
    @login_required
    @admin_required
    def users_reset(uid):
        u = db.session.get(User, uid) or abort(404)
        u.set_password(request.form["password"])
        db.session.commit()
        flash(f"Password reset for {u.username}.", "success")
        return redirect(url_for("users"))

    # ---------------- Settings (FX rate, email, database) ----------------
    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    @admin_required
    def settings():
        if request.method == "POST":
            section = request.form.get("section")
            if section == "fx":
                set_setting("fx_rate", request.form.get("fx_rate", "50.5"))
                flash("FX rate updated.", "success")
            elif section == "email":
                for k in ("smtp_host", "smtp_port", "smtp_user", "smtp_pass",
                          "smtp_from", "smtp_tls"):
                    set_setting(k, request.form.get(k, ""))
                flash("Email settings saved.", "success")
            elif section == "strategy":
                set_setting("call_strategy", request.form.get("call_strategy", "balanced"))
                set_setting("call_capacity", request.form.get("call_capacity", "15"))
                set_setting("call_cooldown", request.form.get("call_cooldown", "5"))
                flash("Collection strategy updated.", "success")
            elif section == "branding":
                set_setting("product_name", request.form.get("product_name") or svc.DEFAULT_PRODUCT)
                set_setting("org_name", request.form.get("org_name") or svc.DEFAULT_ORG)
                if request.form.get("remove_logo"):
                    svc.clear_org_logo()
                logo = request.files.get("org_logo")
                if logo and logo.filename:
                    data = logo.read()
                    if len(data) > 1_500_000:
                        flash("Logo image is too large (max ~1.5 MB). Branding text saved; logo not changed.", "warning")
                    elif not (logo.mimetype or "").startswith("image/"):
                        flash("That file isn't an image. Branding text saved; logo not changed.", "warning")
                    else:
                        svc.set_org_logo(data, logo.mimetype or "image/png")
                        flash("Branding and organisation logo updated.", "success")
                        return redirect(url_for("settings"))
                flash("Branding updated.", "success")
            elif section == "commission":
                svc.set_commission_rates(request.form)
                if request.form.get("owner_share") not in (None, ""):
                    set_setting("commission_owner_share", request.form.get("owner_share"))
                if request.form.get("legal_provision_default") not in (None, ""):
                    set_setting("legal_provision_default", request.form.get("legal_provision_default"))
                flash("Commission settings updated.", "success")
            elif section == "database":
                url = request.form.get("database_url", "").strip()
                if url:
                    write_env_value("DATABASE_URL", url)
                    flash("Database URL saved to .env. Restart the app to connect to Neon, "
                          "then run setup/seed once.", "warning")
            return redirect(url_for("settings"))
        vals = {k: get_setting(k, "") for k in
                ("fx_rate", "smtp_host", "smtp_port", "smtp_user", "smtp_from", "smtp_tls")}
        vals["fx_rate"] = vals["fx_rate"] or "50.5"
        vals["call_strategy"] = get_setting("call_strategy", "balanced")
        vals["call_capacity"] = get_setting("call_capacity", "15")
        vals["call_cooldown"] = get_setting("call_cooldown", "5")
        current_db = "Neon / PostgreSQL" if "postgres" in app.config["SQLALCHEMY_DATABASE_URI"] \
            else "local SQLite"
        return render_template("settings.html", v=vals, current_db=current_db,
                               email_ready=emailer.email_configured(),
                               strategies=svc.CALL_STRATEGIES,
                               comm_rates=svc.get_commission_rates(),
                               comm_order=svc.COMMISSION_ORDER,
                               owner_share=svc.get_owner_share(),
                               owner_splits=svc.owner_shares_by_bucket(),
                               brand=svc.get_brand(),
                               legal_provision_default=svc.legal_provision_default())

    # ---------------- Email a reminder letter ----------------
    @app.route("/reminder/<int:cid>/email", methods=["POST"])
    @login_required
    def reminder_email(cid):
        cust = db.session.get(Customer, cid) or abort(404)
        level = max(1, min(4, int(request.form.get("level", 1))))
        rows = [r for r in svc.instalment_rows() if r["customer_id"] == cid
                and r["bucket"] in svc.OVERDUE_BUCKETS]
        overdue = sum(r["net"] for r in rows)
        total = sum(r["net"] for r in svc.instalment_rows() if r["customer_id"] == cid)
        meta = svc.REMINDER_LEVELS[level]
        html = render_template("email_reminder.html", cust=cust, rows=rows, overdue=overdue,
                               total=total, level=level, meta=meta)
        ok, msg = emailer.send_email(cust.email, f"{meta['heading']} — account {cust.cust_ref}", html)
        if ok:
            db.session.add(Reminder(customer_id=cid, level=level, currency=cust.currency,
                                    amount_overdue=overdue,
                                    sent_by=(current_user.full_name or current_user.username),
                                    notes="emailed"))
            db.session.commit()
        flash(msg, "success" if ok else "danger")
        return redirect(url_for("reminder_letter", cid=cid, level=level))

    # ---------------- Monthly collections report (by method) ----------------
    @app.route("/reports/collections")
    @login_required
    def collections_report():
        rep = svc.collections_by_month()
        export = request.args.get("export")
        if export in ("csv", "xlsx", "pdf"):
            headers = ["Month", "Currency"] + rep["methods"] + ["Total"]
            data = []
            for ccy in ("EGP", "USD"):
                for month in sorted(rep["data"][ccy].keys()):
                    d = rep["data"][ccy][month]
                    data.append([month, ccy] + [d.get(mm, 0.0) for mm in rep["methods"]] + [d.get("_total", 0.0)])
            return report_download(export, "Monthly Collections by Method", headers, data, "monthly_collections")
        return render_template("collections_report.html", rep=rep)

    # ---------------- Ledger allocation (manager) ----------------
    @app.route("/allocations", methods=["GET", "POST"])
    @login_required
    @admin_required
    def allocations():
        if request.method == "POST":
            act = request.form.get("action")
            if act == "range":
                owner_id = int(request.form["owner_id"])
                n = svc.allocate_range(owner_id, request.form["kind"],
                                       request.form.get("frm"), request.form.get("to"))
                flash(f"Allocated {n} customer(s) to the selected controller.", "success")
            elif act == "default":
                for ccy in ("EGP", "USD"):
                    v = request.form.get(f"default_{ccy}")
                    set_setting(f"default_owner_{ccy}", v or "")
                flash("Default owners for new customers saved.", "success")
            return redirect(url_for("allocations"))
        summary = svc.allocation_summary()
        defaults = {ccy: get_setting(f"default_owner_{ccy}", "") for ccy in ("EGP", "USD")}
        return render_template("allocations.html", summary=summary,
                               users=User.query.order_by(User.username).all(),
                               defaults=defaults)

    @app.route("/reports/performance")
    @login_required
    def performance_report():
        f = request.args
        perf = svc.controller_performance(parse_date(f.get("from")), parse_date(f.get("to")))
        export = request.args.get("export")
        if export in ("csv", "xlsx", "pdf"):
            headers = ["Controller", "Ccy", "Customers", "Outstanding", "Overdue", "Collected", "Recovery %", "Commission"]
            data = []
            for who in sorted(perf):
                for ccy in ("EGP", "USD"):
                    p = perf[who][ccy]
                    if p["customers"] or p["collected"] or p["commission"]:
                        rec = "" if p.get("recovery_pct") is None else round(p["recovery_pct"], 1)
                        data.append([who, ccy, p["customers"], p["outstanding"], p["overdue"],
                                     p["collected"], rec, p["commission"]])
            return report_download(export, "Controller Performance", headers, data, "controller_performance")
        return render_template("performance.html", perf=perf, f=f, printable=f.get("print") == "1")

    # ---------------- Credit-controller call scheduler ----------------
    @app.route("/calls")
    @login_required
    def calls():
        day = parse_date(request.args.get("day")) or date.today()
        mine = request.args.get("mine") == "1"
        owner_id = current_user.id if mine else None
        todays = svc.call_list_for(day, owner_id=owner_id)
        stats = svc.call_stats()
        strat = svc.get_strategy()
        cap = int(get_setting("call_capacity", "15") or 15)
        cooldown = int(get_setting("call_cooldown", "5") or 5)
        upcoming = (db.session.query(CallTask.scheduled_for, db.func.count(CallTask.id))
                    .filter(CallTask.status == "pending")
                    .group_by(CallTask.scheduled_for)
                    .order_by(CallTask.scheduled_for).limit(10).all())
        preview = svc.collection_priority(owner_id=owner_id)[:15] if not todays else []
        return render_template("calls.html", todays=todays, stats=stats, day=day, mine=mine,
                               strategies=svc.CALL_STRATEGIES, strat=strat, cap=cap,
                               cooldown=cooldown, upcoming=upcoming, outcomes=svc.OUTCOMES,
                               preview=preview, users=User.query.order_by(User.username).all())

    @app.route("/calls/generate", methods=["POST"])
    @login_required
    def calls_generate():
        start = parse_date(request.form.get("start")) or date.today()
        days = int(request.form.get("days", 5))
        cap = int(request.form.get("capacity", 15))
        cooldown = int(request.form.get("cooldown", 5))
        owner_id = int(request.form["owner_id"]) if request.form.get("owner_id") else None
        assign = None
        if owner_id:
            u = db.session.get(User, owner_id)
            assign = (u.full_name or u.username) if u else None
        set_setting("call_capacity", cap)
        set_setting("call_cooldown", cooldown)
        n = svc.generate_call_plan(start_date=start, days=days, capacity=cap,
                                   cooldown=cooldown, assigned_to=assign, owner_id=owner_id)
        scope = f" for {assign}'s ledger" if assign else ""
        flash(f"Scheduled {n} calls across {days} working day(s) from {start}{scope}, "
              f"by the '{svc.CALL_STRATEGIES[svc.get_strategy()]['label']}' strategy.", "success")
        return redirect(url_for("calls", day=start.isoformat()))

    @app.route("/calls/<int:tid>/log", methods=["POST"])
    @login_required
    def calls_log(tid):
        who = (current_user.full_name or current_user.username)
        outcome = request.form["outcome"]
        notes = request.form.get("notes")
        t = svc.log_call_outcome(
            tid, outcome, who,
            promise_amount=parse_money(request.form.get("promise_amount")) if request.form.get("promise_amount") else None,
            promise_date=parse_date(request.form.get("promise_date")),
            notes=notes)
        if t:
            summary = f"Call outcome: {outcome.replace('_', ' ')}."
            if request.form.get("promise_date"):
                summary += f" Promised {request.form.get('promise_amount') or ''} by {request.form.get('promise_date')}."
            if notes:
                summary += f" {notes}"
            svc.add_note(t.customer_id, who, summary, kind="outcome", call_task_id=tid)
        flash("Call logged.", "success")
        return redirect(request.referrer or url_for("calls"))

    # ---------------- Customer contact notes / comments ----------------
    @app.route("/customer/<int:cid>/note", methods=["POST"])
    @login_required
    def customer_note(cid):
        db.session.get(Customer, cid) or abort(404)
        svc.add_note(cid, (current_user.full_name or current_user.username),
                     request.form.get("text"), kind="note")
        flash("Comment saved.", "success")
        return redirect(url_for("customer_detail", cid=cid))

    # ---------------- Commission report (weighted by ageing bucket) ----------------
    @app.route("/reports/commission")
    @login_required
    def commission_report():
        f = request.args
        month = f.get("month")
        if month:
            df, dt = svc.month_bounds(month)
        else:
            df = parse_date(f.get("from"))
            dt = parse_date(f.get("to"))
        ctrl = f.get("controller") or None
        data = svc.commission_report(date_from=df, date_to=dt, controller=ctrl)
        printable = f.get("print") == "1"
        cur_month = (month or date.today().strftime("%Y-%m"))
        return render_template("commission_report.html", data=data, f=f, month=cur_month,
                               controllers=svc.controllers_list(), printable=printable,
                               period=(df, dt))

    @app.route("/reports/commission/export")
    @login_required
    def commission_export():
        f = request.args
        month = f.get("month") or date.today().strftime("%Y-%m")
        df, dt = svc.month_bounds(month)
        ctrl = f.get("controller") or None
        fmt = f.get("format", "csv")
        rows = svc.commission_statement_rows(df, dt, controller=ctrl)  # rows[0] = headers
        headers, data = rows[0], rows[1:]
        title = f"Commission Statement — {month}" + (f" — {ctrl}" if ctrl else "")
        base = f"commission_{month}{('_' + ctrl) if ctrl else ''}".replace(" ", "_")
        if fmt == "xlsx":
            import reportexport as rx
            return Response(rx.xlsx_bytes(title, headers, data), mimetype=rx.XLSX_MIME,
                            headers={"Content-Disposition": f"attachment; filename={base}.xlsx"})
        if fmt == "pdf":
            import reportexport as rx
            return Response(rx.pdf_bytes(title, headers, data), mimetype=rx.PDF_MIME,
                            headers={"Content-Disposition": f"attachment; filename={base}.pdf"})
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([f"Commission statement — {svc.get_brand()['org']} — {month} ({df} to {dt})"])
        w.writerow([])
        for r in rows:
            w.writerow(r)
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={base}.csv"})

    @app.route("/commission/targets", methods=["GET", "POST"])
    @login_required
    @admin_required
    def commission_targets():
        from models import CommissionTarget
        if request.method == "POST":
            ctrl = request.form["controller"].strip()
            ccy = request.form["currency"]
            for b in svc.COMMISSION_ORDER:
                key = "t_" + b.replace(" ", "_").replace("-", "_").replace("+", "p")
                amt = parse_money(request.form.get(key)) if request.form.get(key) else Decimal("0")
                row = CommissionTarget.query.filter_by(controller=ctrl, currency=ccy, bucket=b).first()
                if not row:
                    row = CommissionTarget(controller=ctrl, currency=ccy, bucket=b)
                    db.session.add(row)
                row.target_amount = amt or 0
            db.session.commit()
            flash(f"Targets saved for {ctrl} ({ccy}).", "success")
            return redirect(url_for("commission_targets"))
        existing = svc.get_targets()
        return render_template("commission_targets.html", controllers=svc.controllers_list(),
                               order=svc.COMMISSION_ORDER, existing=existing)

    @app.route("/brand/org-logo")
    def brand_org_logo():
        logo = svc.get_org_logo()
        if not logo:
            abort(404)
        data, mime = logo
        return Response(data, mimetype=(mime or "image/png"),
                        headers={"Cache-Control": "no-cache"})

    # ---------------- Bulk import (instalments / payments) ----------------
    @app.route("/import")
    @login_required
    def import_home():
        import importer
        return render_template("import.html", stage="home", specs=importer.SPECS)

    @app.route("/import/template/<kind>")
    @login_required
    def import_template(kind):
        import importer
        if kind not in importer.SPECS:
            flash("Unknown template.", "warning"); return redirect(url_for("import_home"))
        data = importer.build_template(kind)
        fname = f"Collecta_import_template_{kind}.xlsx"
        return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename={fname}"})

    @app.route("/import/preview", methods=["POST"])
    @login_required
    def import_preview():
        import importer, json as _json
        kind = request.form.get("kind")
        if kind not in importer.SPECS:
            flash("Choose what to import.", "warning"); return redirect(url_for("import_home"))
        f = request.files.get("file")
        if not f or not f.filename:
            flash("Please choose a file to upload.", "warning"); return redirect(url_for("import_home"))
        try:
            rows = importer.read_table(f, kind)
        except Exception as e:
            flash(f"Could not read that file: {e}. Use the provided template (.xlsx) or a .csv.", "warning")
            return redirect(url_for("import_home"))
        accepted, rejected = importer.validate(kind, rows)
        before = importer.balances_by_customer()
        move, tot = importer.projected(kind, accepted, before)
        return render_template("import.html", stage="preview", kind=kind, specs=importer.SPECS,
                               accepted=accepted, rejected=rejected, move=move, totals=tot,
                               filename=f.filename, accepted_json=_json.dumps(accepted))

    @app.route("/import/commit", methods=["POST"])
    @login_required
    def import_commit():
        import importer, json as _json, tempfile, os, secrets
        kind = request.form.get("kind")
        if kind not in importer.SPECS:
            flash("Unknown import.", "warning"); return redirect(url_for("import_home"))
        try:
            accepted = _json.loads(request.form.get("accepted_json") or "[]")
        except ValueError:
            accepted = []
        if not accepted:
            flash("Nothing to import.", "warning"); return redirect(url_for("import_home"))
        # re-validate against current data for safety (e.g. duplicate ids created meanwhile)
        # keep only rows whose keys still validate
        before = importer.balances_by_customer()
        user = (current_user.full_name or current_user.username)
        result = importer.commit(kind, accepted, user)
        after = importer.balances_by_customer()
        meta = dict(user=user, when=datetime.now().strftime("%Y-%m-%d %H:%M"),
                    filename=request.form.get("filename") or "", affected_refs=sorted(result["affected_refs"]))
        audit = importer.build_audit(kind, meta, accepted, [], before, after)
        token = secrets.token_hex(8)
        path = os.path.join(tempfile.gettempdir(), f"collecta_audit_{token}.xlsx")
        with open(path, "wb") as fh:
            fh.write(audit)
        # movement table for on-screen audit
        move = []
        tot = {}
        for ref in meta["affected_refs"]:
            b = before.get(ref, {}); a = after.get(ref, {})
            ccy = a.get("currency") or b.get("currency") or ""
            old = b.get("net", 0.0); new = a.get("net", 0.0)
            move.append(dict(ref=ref, name=a.get("name") or b.get("name") or "", currency=ccy,
                             old=old, change=new - old, new=new))
            t = tot.setdefault(ccy, dict(old=0.0, change=0.0, new=0.0))
            t["old"] += old; t["change"] += (new - old); t["new"] += new
        return render_template("import.html", stage="audit", kind=kind, specs=importer.SPECS,
                               result=result, move=move, totals=tot, token=token, meta=meta,
                               n_new=len(result["new_customers"]))

    @app.route("/import/audit/<token>")
    @login_required
    def import_audit_download(token):
        import os, tempfile, re as _re
        if not _re.fullmatch(r"[0-9a-f]{16}", token or ""):
            flash("Invalid audit reference.", "warning"); return redirect(url_for("import_home"))
        path = os.path.join(tempfile.gettempdir(), f"collecta_audit_{token}.xlsx")
        if not os.path.exists(path):
            flash("That audit file is no longer available — re-run the import if you need it.", "warning")
            return redirect(url_for("import_home"))
        with open(path, "rb") as fh:
            data = fh.read()
        return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename=Collecta_import_audit.xlsx"})

    # ---------------- Legal sub-ledger & doubtful-debt provision ----------------
    @app.route("/legal")
    @login_required
    def legal_ledger():
        ll = svc.legal_ledger()
        export = request.args.get("export")
        if export in ("csv", "xlsx", "pdf"):
            headers = ["Cust Ref", "Customer", "Ccy", "Stage", "Gross Outstanding", "Overdue",
                       "Provision %", "Provision", "Net of Provision", "Legal Date"]
            data = [[r["cust"].cust_ref, r["cust"].name, r["currency"], (r["stage"] or ""),
                     r["total"], r["overdue"], r["pct"], r["provision"], r["net"],
                     (r["legal_date"].isoformat() if r["legal_date"] else "")] for r in ll["rows"]]
            for ccy in ("EGP", "USD"):
                t = ll["totals"][ccy]
                if t["n"]:
                    data.append([f"TOTAL {ccy}", "", ccy, "", t["gross"], t["overdue"], "", t["provision"], t["net"], ""])
            return report_download(export, "Legal Sub-ledger & Doubtful-debt Provision", headers, data, "legal_subledger")
        cands = svc.legal_candidates(min_days=int(request.args.get("min_days", 180)))
        return render_template("legal.html", ll=ll, cands=cands, stages=svc.LEGAL_STAGES,
                               default_pct=svc.legal_provision_default(),
                               min_days=int(request.args.get("min_days", 180)))

    @app.route("/legal/transfer", methods=["POST"])
    @login_required
    @admin_required
    def legal_transfer():
        cid = int(request.form["customer_id"])
        svc.transfer_to_legal(cid, request.form.get("reason"), request.form.get("stage"),
                              parse_money(request.form.get("provision_pct")) if request.form.get("provision_pct") else None,
                              (current_user.full_name or current_user.username))
        flash("Account transferred to the legal sub-ledger.", "success")
        return redirect(request.form.get("next") or url_for("legal_ledger"))

    @app.route("/legal/<int:cid>/update", methods=["POST"])
    @login_required
    @admin_required
    def legal_update(cid):
        svc.update_legal(cid, request.form.get("stage"),
                         parse_money(request.form.get("provision_pct")) if request.form.get("provision_pct") else None,
                         (current_user.full_name or current_user.username))
        flash("Legal case updated.", "success")
        return redirect(request.form.get("next") or url_for("legal_ledger"))

    @app.route("/legal/<int:cid>/return", methods=["POST"])
    @login_required
    @admin_required
    def legal_return(cid):
        svc.return_from_legal(cid, (current_user.full_name or current_user.username))
        flash("Account returned to active collections.", "success")
        return redirect(request.form.get("next") or url_for("legal_ledger"))

    # ---------------- Integrated operating manual / help ----------------
    @app.route("/help")
    @login_required
    def help_center():
        import manual
        return render_template("help.html", manual=manual.MANUAL,
                               categories=manual.CATEGORIES, q=request.args.get("q", ""))

    # ---------------- Access Control (roles, permissions, subscription) ----------------
    @app.route("/admin/access", methods=["GET", "POST"])
    @login_required
    @require_perm("access_control")
    def access_control():
        import permissions as perms
        from models import db, RolePermission
        if request.method == "POST":
            old_plan = perms.get_plan()
            plan = request.form.get("plan")
            if plan and plan != old_plan:
                perms.set_plan(plan)
                audit("subscription_plan_changed", plan, f"{old_plan} -> {plan}")
            appr = request.form.getlist("approver_roles")
            perms.set_approver_roles(appr)
            changes = 0
            for role, _ in perms.ROLES:
                if role == "admin":
                    continue                      # super-admin always full
                for cap in perms.CAP_KEYS:
                    allowed = request.form.get(f"perm_{role}_{cap}") == "on"
                    rp = db.session.get(RolePermission, (role, cap))
                    cur = rp.allowed if rp else False
                    if cur != allowed:
                        perms.set_permission(role, cap, allowed)
                        changes += 1
            audit("access_control_updated", "matrix", f"{changes} change(s); approvers={','.join(appr)}")
            flash("Access control updated.", "success")
            return redirect(url_for("access_control"))
        return render_template("access_control.html", roles=perms.ROLES, caps=perms.CAPABILITIES,
                               matrix=perms.get_matrix(), plan=perms.get_plan(), plans=perms.PLANS,
                               plan_labels=perms.PLAN_LABELS, approver_roles=perms.get_approver_roles(),
                               cap_min_plan=perms.CAP_MIN_PLAN)

    # ---------------- Audit log ----------------
    @app.route("/admin/audit")
    @login_required
    @require_perm("audit_log")
    def audit_log_view():
        from models import AuditLog
        rows = AuditLog.query.order_by(AuditLog.id.desc()).limit(500).all()
        return render_template("audit_log.html", rows=rows)

    # ---------------- Pending approvals queue (foundation; used by Uploads 2 & 3) ----------------
    @app.route("/approvals")
    @login_required
    @require_perm("approvals")
    def approvals_queue():
        from models import Approval
        pending = Approval.query.filter_by(status="pending").order_by(Approval.id.desc()).all()
        history = Approval.query.filter(Approval.status != "pending").order_by(Approval.id.desc()).limit(50).all()
        details = {}
        for a in pending:
            try:
                details[a.id] = json.loads(a.payload) if a.payload else {}
            except Exception:
                details[a.id] = {}
        return render_template("approvals.html", pending=pending, history=history, details=details)

    @app.route("/approvals/<int:aid>/<decision>", methods=["POST"])
    @login_required
    @require_perm("approvals")
    def approval_decide(aid, decision):
        from models import db, Approval
        ap = db.session.get(Approval, aid) or abort(404)
        if ap.status != "pending":
            flash("That request has already been decided.", "warning")
            return redirect(url_for("approvals_queue"))
        if ap.requester_id and current_user.id == ap.requester_id:
            flash("Separation of duties: you cannot approve your own request.", "danger")
            return redirect(url_for("approvals_queue"))
        if decision not in ("approve", "reject"):
            abort(400)
        ap.status = "approved" if decision == "approve" else "rejected"
        ap.approver = (current_user.full_name or current_user.username)
        ap.decided_at = datetime.now()
        db.session.commit()
        audit("approval_" + ap.status, ap.kind, ap.summary or "")
        # Apply the authorised action to the ledger (only on approval).
        if ap.status == "approved":
            try:
                _apply_approval(ap)
            except Exception as e:
                db.session.rollback()
                flash(f"Approved, but applying the change failed: {e}", "danger")
                return redirect(url_for("approvals_queue"))
        flash(f"Request {ap.status}.", "success")
        return redirect(url_for("approvals_queue"))

    def _apply_approval(ap):
        """Turn an approved reschedule/conversion into actual ledger entries."""
        from models import db, Instalment, Customer
        if not ap.payload:
            return
        p = json.loads(ap.payload)
        action = p.get("action")
        cust = db.session.get(Customer, p.get("customer_id"))
        if action == "date_reschedule":
            # close the source instalments (rescheduled), create the new EGP/USD schedule
            for iid in p.get("source_ids", []):
                src = db.session.get(Instalment, iid)
                if src:
                    src.state = "rescheduled"
            for i, s in enumerate(p.get("schedule", [])):
                nid = svc.next_deal_inst_id(cust, "RS")
                db.session.add(Instalment(
                    inst_id=nid, customer_id=cust.id, currency=p.get("currency"),
                    account_type="MACHINE", original_amount=s["amount"],
                    due_date=date.fromisoformat(s["due_date"]),
                    reference=p.get("agreement_ref"), agreement_ref=p.get("agreement_ref"),
                    origin="reschedule", state="open", date_raised=date.today(),
                    description="Rescheduled instalment"))
                db.session.flush()
            db.session.commit()
            audit("reschedule_applied", (cust.cust_ref if cust else ""), ap.summary or "")
        elif action == "currency_conversion":
            agreed = p.get("agreed_rate")
            orig_rates = p.get("orig_rates", {})
            for iid in p.get("source_ids", []):
                src = db.session.get(Instalment, iid)
                if not src:
                    continue
                # capture the original rate used (stored or the confirmed legacy rate) for the report
                if src.orig_fx_rate is None:
                    lr = orig_rates.get(str(iid)) or p.get("legacy_rate")
                    if lr:
                        src.orig_fx_rate = lr
                src.state = "converted"
                src.converted_rate = agreed
                src.agreement_ref = p.get("agreement_ref")
            # create the new EGP instalment(s)
            for s in p.get("schedule", []):
                nid = svc.next_deal_inst_id(cust, "CV")
                new_i = Instalment(
                    inst_id=nid, customer_id=cust.id, currency="EGP", account_type="MACHINE",
                    original_amount=s["amount"], due_date=date.fromisoformat(s["due_date"]),
                    reference=p.get("agreement_ref"), agreement_ref=p.get("agreement_ref"),
                    origin="conversion", state="open", date_raised=date.today(),
                    description="USD→EGP currency conversion")
                db.session.add(new_i); db.session.flush()
            db.session.commit()
            audit("conversion_applied", (cust.cust_ref if cust else ""), ap.summary or "")

    return app


def _notify_approvers(kind, summary, requester_id=None):
    """Email users whose role may approve (used from Upload 2 onward). Silent if email off."""
    try:
        import emailer, permissions as perms
        from models import User
        if not emailer.email_configured():
            return
        roles = set(perms.get_approver_roles())
        for u in User.query.all():
            if perms.role_key(u) in roles and u.email and u.id != requester_id:
                emailer.send_email(u.email, f"Collecta — approval needed: {kind}",
                                   f"<p>A request needs your authorisation in Collecta:</p><p><b>{summary}</b></p>"
                                   f"<p>Please sign in and open <b>Approvals</b> to action it.</p>")
    except Exception:
        pass


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
