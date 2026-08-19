"""Roles, capabilities, subscription tiers and the access-control helpers.

- Menus always show every item; unauthorised ones are dimmed (see templates).
- Every capability is enforced server-side via require_perm / can().
- The 'admin' role is a protected super-admin: it bypasses both the permission
  matrix AND the subscription gate, so an administrator can never be locked out
  and can always adjust roles / plan from Admin > Access Control (the "back door").
"""

# ---- roles (key, label) ----
ROLES = [
    ("admin", "Administrator (super-user)"),
    ("cfo", "CFO"),
    ("fm", "Finance Manager"),
    ("md", "Managing Director"),
    ("credit_control", "Credit Control"),
    ("account_manager", "Account Manager (reconciliation)"),
    ("sales", "Sales"),
    ("maintenance", "Maintenance"),
]
ROLE_LABELS = dict(ROLES)

# ---- subscription plans (ascending) ----
PLANS = ["core", "professional", "enterprise"]
PLAN_LABELS = {"core": "Core", "professional": "Professional", "enterprise": "Enterprise"}

# ---- capabilities: key, label, menu-group, min-plan ----
CAPABILITIES = [
    ("dashboard",        "View dashboard",              "General",   "core"),
    ("ledger",           "View ledger & ageing",        "Ledger",    "core"),
    ("collections",      "Record collections",          "Collections", "core"),
    ("reminders",        "Reminder letters",            "Collections", "core"),
    ("calls",            "Call scheduler",              "Collections", "core"),
    ("customers",        "View & search customers",     "Customers", "core"),
    ("customer_edit",    "Add / edit customers",        "Customers", "core"),
    ("credit_limits",    "Credit limits",               "Ledger",    "core"),
    ("guarantees",       "Guarantees register",         "Customers", "core"),
    ("parts_sales",      "Parts & accessories sales",   "Customers", "professional"),
    ("reports",          "Reports",                     "Reports",   "core"),
    ("exports",          "Download CSV / Excel / PDF",  "Reports",   "professional"),
    ("bulk_import",      "Bulk import",                 "Ledger",    "professional"),
    ("allocation",       "Ledger allocation",           "Admin",     "professional"),
    ("legal",            "Legal sub-ledger",            "Ledger",    "professional"),
    ("reschedule",       "Reschedule instalments",      "Ledger",    "professional"),
    ("fx_convert",       "Currency conversion (USD→EGP)", "Ledger",  "professional"),
    ("audit_log",        "View audit log",              "Admin",     "professional"),
    ("access_control",   "Access control (roles & plan)", "Admin",   "professional"),
    ("approvals",        "Approve authorisations",      "Admin",     "enterprise"),
    ("sales_clearance",  "Sales credit clearance",      "Customers", "enterprise"),
    ("maintenance_notes", "Maintenance notes & holds",  "Customers", "enterprise"),
    ("users_admin",      "Manage users",                "Admin",     "core"),
    ("settings",         "System settings",             "Admin",     "core"),
]
CAP_LABELS = {c[0]: c[1] for c in CAPABILITIES}
CAP_MIN_PLAN = {c[0]: c[3] for c in CAPABILITIES}
CAP_KEYS = [c[0] for c in CAPABILITIES]

# ---- default matrix (role -> set of capabilities) ----
_VIEW = {"dashboard", "ledger", "customers", "reports", "exports"}
DEFAULT_MATRIX = {
    "admin": set(CAP_KEYS),
    "cfo": _VIEW | {"approvals", "audit_log", "legal", "sales_clearance"},
    "fm": _VIEW | {"approvals", "audit_log"},
    "md": _VIEW | {"approvals", "audit_log"},
    "credit_control": {"dashboard", "ledger", "collections", "reminders", "calls",
                       "customers", "customer_edit", "credit_limits", "guarantees",
                       "reports", "exports", "bulk_import", "legal", "reschedule",
                       "sales_clearance", "parts_sales", "fx_convert", "guarantees"},
    # Account Manager sits in the general accounts: allocates cash and reconciles the
    # Collecta debtors ledger to the GL. Deliberately read + export only inside Collecta,
    # so they never reconcile their own postings (segregation of duties). No posting,
    # no editing, no approving.
    "account_manager": _VIEW | {"audit_log"},
    "sales": {"dashboard", "customers", "sales_clearance"},
    "maintenance": {"dashboard", "customers", "maintenance_notes"},
}
# capabilities that may approve digital authorisations, by default
DEFAULT_APPROVER_ROLES = ["fm", "cfo", "md", "admin"]


def role_key(user):
    """Map legacy 'user' role to credit_control; leave others as-is."""
    r = (getattr(user, "role", "") or "").lower()
    return "credit_control" if r == "user" else r


# ---- persistence (matrix stored in DB, seeded from defaults) ----
def seed_matrix():
    """Backfill the permission matrix additively.

    Adds a RolePermission row for any (role, capability) pair that doesn't yet
    exist, using the default value. Never touches rows that already exist, so an
    admin's customisations in Access Control are always preserved. This also means
    new roles and new capabilities shipped in later uploads (e.g. the Account
    Manager role, or Parts sales) light up correctly on databases that were seeded
    by an earlier version — mirroring the safe, additive schema migration.
    """
    from models import db, RolePermission
    existing = {(rp.role, rp.capability) for rp in RolePermission.query.all()}
    added = False
    for role, _ in ROLES:
        allowed = DEFAULT_MATRIX.get(role, set())
        for cap in CAP_KEYS:
            if (role, cap) not in existing:
                db.session.add(RolePermission(role=role, capability=cap, allowed=(cap in allowed)))
                added = True
    if added:
        db.session.commit()


def get_matrix():
    from models import RolePermission
    m = {role: set() for role, _ in ROLES}
    for rp in RolePermission.query.all():
        if rp.allowed and rp.role in m:
            m[rp.role].add(rp.capability)
    return m


def set_permission(role, capability, allowed):
    from models import db, RolePermission
    rp = db.session.get(RolePermission, (role, capability))
    if not rp:
        rp = RolePermission(role=role, capability=capability)
        db.session.add(rp)
    rp.allowed = bool(allowed)
    db.session.commit()


# ---- subscription plan (tenant-wide, admin-overridable back door) ----
def get_plan():
    from models import get_setting
    p = (get_setting("subscription_plan", "enterprise") or "enterprise").lower()
    return p if p in PLANS else "enterprise"


def set_plan(plan):
    from models import set_setting
    if plan in PLANS:
        set_setting("subscription_plan", plan)


def feature_enabled(capability):
    """Is this capability included in the current subscription plan?"""
    need = CAP_MIN_PLAN.get(capability, "core")
    return PLANS.index(get_plan()) >= PLANS.index(need)


def get_approver_roles():
    from models import get_setting
    raw = get_setting("approver_roles", "")
    if raw:
        return [r for r in raw.split(",") if r]
    return list(DEFAULT_APPROVER_ROLES)


def set_approver_roles(roles):
    from models import set_setting
    set_setting("approver_roles", ",".join([r for r in roles if r]))


# ---- the core checks ----
def has_perm(user, capability):
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if role_key(user) == "admin":
        return True                       # super-admin back door
    if not feature_enabled(capability):
        return False                      # not in this subscription plan
    return capability in get_matrix().get(role_key(user), set())


def can_approve(user):
    if role_key(user) == "admin":
        return True
    return role_key(user) in get_approver_roles() and has_perm(user, "approvals")


def dim_reason(user, capability):
    """Why a menu item is dimmed: '' = allowed, else a tooltip string."""
    if has_perm(user, capability):
        return ""
    if role_key(user) != "admin" and not feature_enabled(capability):
        return "Requires the %s plan" % PLAN_LABELS[CAP_MIN_PLAN.get(capability, "core")]
    return "Not authorised for your role"


# ---- endpoint -> capability (central server-side enforcement) ----
ENDPOINT_CAP = {
    "dashboard": "dashboard",
    "ledger": "ledger", "aged": "ledger", "overdue_customers": "ledger",
    "credit_limits": "credit_limits",
    "collections": "collections",
    "new_instalment": "customer_edit",
    "parts_new": "parts_sales", "parts_import": "parts_sales", "parts_import_preview": "parts_sales", "parts_import_commit": "parts_sales",
    "reschedule_request": "reschedule", "machine_new": "customer_edit",
    "convert_request": "fx_convert", "convert_preview": "fx_convert", "conversions_report": "reports",
    "reschedule_picker": "reschedule", "convert_picker": "fx_convert",
    "guarantees_register": "guarantees", "guarantee_new": "guarantees", "guarantee_update": "guarantees",
    "unguaranteed_report": "reports", "clearance_override": "sales_clearance",
    "controller_scorecard": "reports",
    "customers": "customers", "customer_detail": "customers", "customer_note": "customers",
    "customer_new": "customer_edit",
    "reminders": "reminders", "reminder_letter": "reminders", "reminder_log": "reminders",
    "reminder_email": "reminders",
    "calls": "calls", "calls_generate": "calls", "calls_log": "calls",
    "reports": "reports", "collections_report": "reports", "performance_report": "reports",
    "commission_report": "reports", "commission_targets": "reports",
    "commission_export": "exports",
    "import_home": "bulk_import", "import_template": "bulk_import", "import_preview": "bulk_import",
    "import_commit": "bulk_import", "import_audit_download": "bulk_import",
    "allocations": "allocation",
    "legal_ledger": "legal", "legal_transfer": "legal", "legal_update": "legal", "legal_return": "legal",
    "users": "users_admin", "users_new": "users_admin", "users_delete": "users_admin", "users_reset": "users_admin", "users_update": "users_admin",
    "settings": "settings",
    "access_control": "access_control", "access_save": "access_control",
    "audit_log_view": "audit_log",
    "approvals_queue": "approvals", "approval_decide": "approvals",
}
# endpoints anyone signed-in (or the framework) may reach
OPEN_ENDPOINTS = {"login", "logout", "setup", "brand_org_logo", "help_center", "static", None, ""}
