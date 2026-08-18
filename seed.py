"""Initialise the database schema and load base data from seed_data.json.

Usage:
    python seed.py                       # create tables + load customers/instalments + admin
    python seed.py --admin USER PASS     # (re)create/reset an admin user only
Environment:
    DATABASE_URL   Neon Postgres URL (falls back to local sqlite for testing)
    ADMIN_USER / ADMIN_PASS   optional admin credentials (default admin / admin123)
"""
import json
import os
import sys
from datetime import datetime

from app import create_app
from models import db, User, Customer, Instalment

HERE = os.path.dirname(os.path.abspath(__file__))


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date() if s else None


def ensure_admin(username=None, password=None):
    username = username or os.environ.get("ADMIN_USER", "admin")
    password = password or os.environ.get("ADMIN_PASS", "admin123")
    u = User.query.filter_by(username=username).first()
    if not u:
        u = User(username=username, full_name="Administrator", role="admin")
        db.session.add(u)
    u.set_password(password)
    u.role = "admin"
    db.session.commit()
    print(f"Admin user ready: {username}")


def load_base_data():
    data = json.load(open(os.path.join(HERE, "seed_data.json"), encoding="utf-8"))
    if Customer.query.first():
        print("Customers already present — skipping base-data load.")
        return
    ref_to_cust = {}
    for c in data["customers"]:
        cust = Customer(cust_ref=c["cust_ref"], account_no=c["account_no"],
                        name=c["name"], currency=c["currency"],
                        credit_limit=c.get("credit_limit"))
        db.session.add(cust)
        db.session.flush()
        ref_to_cust[c["cust_ref"]] = cust.id
    for i in data["instalments"]:
        db.session.add(Instalment(
            inst_id=i["inst_id"], customer_id=ref_to_cust[i["cust_ref"]],
            currency=i["currency"], original_amount=i["original_amount"],
            due_date=parse_date(i["due_date"]), security=i["security"],
            reference=i["reference"], description=i["reference"]))
    db.session.commit()
    print(f"Loaded {len(data['customers'])} customers and {len(data['instalments'])} instalments.")
    print(f"Base totals — EGP {data['meta']['egp_total']:,.0f} | USD {data['meta']['usd_total']:,.0f}")


def initialise(admin_user=None, admin_pass=None, load_data=True):
    """Callable from the app's first-run setup wizard. Assumes app context."""
    db.create_all()
    if load_data:
        load_base_data()
    ensure_admin(admin_user, admin_pass)


def main():
    app = create_app()
    with app.app_context():
        db.create_all()
        if len(sys.argv) >= 4 and sys.argv[1] == "--admin":
            ensure_admin(sys.argv[2], sys.argv[3])
            return
        load_base_data()
        ensure_admin()
        print("Done. Log in and change the admin password.")


if __name__ == "__main__":
    main()
