"""Database models for the Scientific Gate Credit Control System.

Currencies (EGP / USD) are kept strictly separate everywhere — balances are
never summed across currencies. Net outstanding of an instalment is computed as
original_amount minus collections applied to it (see services.ageing).
"""
from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120))
    email = db.Column(db.String(200))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="user")  # admin/credit_control/sales/maintenance/md/fm/cfo (legacy 'user'=credit_control)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def is_admin(self):
        return self.role == "admin"


class Customer(db.Model):
    __tablename__ = "customers"
    id = db.Column(db.Integer, primary_key=True)
    cust_ref = db.Column(db.String(20), unique=True, nullable=False, index=True)
    account_no = db.Column(db.String(40), index=True)          # customer account reference
    name = db.Column(db.String(200), nullable=False, index=True)
    currency = db.Column(db.String(3), nullable=False)          # 'EGP' or 'USD'
    contact_person = db.Column(db.String(120))
    phone = db.Column(db.String(40))
    email = db.Column(db.String(120))
    address = db.Column(db.Text)
    credit_limit = db.Column(db.Numeric(16, 2))                 # machine credit limit (null = not set)
    parts_credit_limit = db.Column(db.Numeric(16, 2))           # separate parts & accessories limit (null = not set)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)  # ledger owner (credit controller)
    legal_status = db.Column(db.String(12), default="active", index=True)     # active / legal
    legal_date = db.Column(db.Date)
    legal_reason = db.Column(db.String(300))
    legal_stage = db.Column(db.String(50))
    provision_pct = db.Column(db.Numeric(5, 2))     # doubtful-debt provision % when in legal
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship("User", foreign_keys=[owner_id])

    instalments = db.relationship("Instalment", backref="customer", lazy=True,
                                  cascade="all, delete-orphan")
    collections = db.relationship("Collection", backref="customer", lazy=True)
    reminders = db.relationship("Reminder", backref="customer", lazy=True)


class Instalment(db.Model):
    __tablename__ = "instalments"
    id = db.Column(db.Integer, primary_key=True)
    inst_id = db.Column(db.String(30), unique=True, nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    currency = db.Column(db.String(3), nullable=False)
    account_type = db.Column(db.String(10), default="MACHINE", index=True)  # MACHINE / PARTS
    original_amount = db.Column(db.Numeric(16, 2), nullable=False)
    due_date = db.Column(db.Date)
    security = db.Column(db.String(60))
    reference = db.Column(db.String(200))       # cheque / invoice / contract reference
    date_raised = db.Column(db.Date)
    description = db.Column(db.String(300))
    # ---- Upload 3: reschedule / add-machine / currency conversion ----
    orig_fx_rate = db.Column(db.Numeric(12, 4))     # original contract USD->EGP rate (USD instalments)
    state = db.Column(db.String(12), default="open", index=True)  # open / converted / rescheduled
    converted_rate = db.Column(db.Numeric(12, 4))   # agreed rate used when converted to EGP
    linked_id = db.Column(db.Integer)               # source/target instalment id for conversion/reschedule
    origin = db.Column(db.String(12), default="original")  # original / conversion / reschedule / machine
    agreement_ref = db.Column(db.String(120))       # hard-copy agreement / contract reference
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    payments = db.relationship("Collection", backref="instalment", lazy=True)


class Collection(db.Model):
    __tablename__ = "collections"
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    instalment_id = db.Column(db.Integer, db.ForeignKey("instalments.id"), nullable=False, index=True)
    txn_ref = db.Column(db.String(60))          # transaction reference number
    amount = db.Column(db.Numeric(16, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    method = db.Column(db.String(30))           # Cash / Cheque / Bank Transfer / Card / Other
    collected_on = db.Column(db.Date, default=date.today)
    received_by = db.Column(db.String(80))          # credit controller who collected
    comments = db.Column(db.String(300))
    bucket_at_collection = db.Column(db.String(20))  # ageing bucket when the payment was received
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Reminder(db.Model):
    __tablename__ = "reminders"
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    level = db.Column(db.Integer, nullable=False)          # 1..4
    currency = db.Column(db.String(3))
    amount_overdue = db.Column(db.Numeric(16, 2))
    sent_on = db.Column(db.Date, default=date.today)
    sent_by = db.Column(db.String(80))
    notes = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Setting(db.Model):
    """Simple key/value store for app configuration (FX rate, SMTP, etc.)."""
    __tablename__ = "settings"
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text)


class BrandAsset(db.Model):
    """Binary branding assets (e.g. the organisation logo), stored in the database
    so they persist across redeploys on hosts with an ephemeral filesystem."""
    __tablename__ = "brand_assets"
    key = db.Column(db.String(40), primary_key=True)     # e.g. "org_logo"
    mime = db.Column(db.String(60))
    data = db.Column(db.LargeBinary)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def get_setting(key, default=None):
    s = db.session.get(Setting, key)
    return s.value if s and s.value not in (None, "") else default


def set_setting(key, value):
    s = db.session.get(Setting, key)
    if not s:
        s = Setting(key=key)
        db.session.add(s)
    s.value = "" if value is None else str(value)
    db.session.commit()


class CallTask(db.Model):
    """A scheduled collection call for a credit controller, prioritised by aged debt."""
    __tablename__ = "call_tasks"
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    scheduled_for = db.Column(db.Date, nullable=False, index=True)
    priority_score = db.Column(db.Float, default=0.0)
    rank = db.Column(db.Integer)
    status = db.Column(db.String(15), default="pending", index=True)  # pending/completed/skipped
    assigned_to = db.Column(db.String(80))
    outcome = db.Column(db.String(30))   # promise_to_pay/no_answer/callback/dispute/paid/refused
    promise_amount = db.Column(db.Numeric(16, 2))
    promise_date = db.Column(db.Date)
    notes = db.Column(db.String(400))
    last_contact = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    customer = db.relationship("Customer")


class CallNote(db.Model):
    """A timestamped comment / contact note recorded by a credit controller.
    Builds a full contact history per customer (calls, notes, outcomes)."""
    __tablename__ = "call_notes"
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    call_task_id = db.Column(db.Integer, db.ForeignKey("call_tasks.id"))
    author = db.Column(db.String(80))
    kind = db.Column(db.String(20), default="note")   # note / call / outcome
    text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    customer = db.relationship("Customer")


class CommissionTarget(db.Model):
    """Optional collection target per controller, currency and ageing bucket."""
    __tablename__ = "commission_targets"
    id = db.Column(db.Integer, primary_key=True)
    controller = db.Column(db.String(80), nullable=False, index=True)
    currency = db.Column(db.String(3), nullable=False)
    bucket = db.Column(db.String(20), nullable=False)
    target_amount = db.Column(db.Numeric(16, 2), default=0)
    __table_args__ = (db.UniqueConstraint("controller", "currency", "bucket",
                                          name="uq_target_ctrl_ccy_bucket"),)


class RolePermission(db.Model):
    """Editable permission matrix: which role may use which capability."""
    __tablename__ = "role_permissions"
    role = db.Column(db.String(30), primary_key=True)
    capability = db.Column(db.String(40), primary_key=True)
    allowed = db.Column(db.Boolean, default=False)


class AuditLog(db.Model):
    """Immutable record of sensitive actions (who / when / what / old->new)."""
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    actor = db.Column(db.String(120))
    action = db.Column(db.String(60))
    target = db.Column(db.String(120))
    detail = db.Column(db.Text)


class Approval(db.Model):
    """Pending digital-authorisation requests (reschedules, gate overrides)."""
    __tablename__ = "approvals"
    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    kind = db.Column(db.String(40))                 # e.g. 'reschedule', 'sales_override'
    status = db.Column(db.String(20), default="pending")  # pending/approved/rejected
    requester = db.Column(db.String(120))
    requester_id = db.Column(db.Integer)
    approver = db.Column(db.String(120))
    decided_at = db.Column(db.DateTime)
    customer_id = db.Column(db.Integer)
    summary = db.Column(db.String(255))
    payload = db.Column(db.Text)                     # JSON detail for the action
    reason = db.Column(db.String(255))
