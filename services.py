"""Business logic: net balances, ageing buckets, KPIs, reminder levels.

The ageing convention matches the Excel system exactly:
  * Overdue = strictly past the due date (an instalment due today is 'Current').
  * Buckets: Current, 1-30, 31-60, 61-90, 91-180, 181-365, 365+ Days, No Due Date.
Currencies are never mixed.
"""
from datetime import date
from decimal import Decimal
from sqlalchemy import func
from models import db, Customer, Instalment, Collection

BUCKETS = ["Current", "1-30 Days", "31-60 Days", "61-90 Days",
           "91-180 Days", "181-365 Days", "365+ Days", "No Due Date"]
OVERDUE_BUCKETS = ["1-30 Days", "31-60 Days", "61-90 Days",
                   "91-180 Days", "181-365 Days", "365+ Days"]


def bucket_for(days_overdue):
    if days_overdue is None:
        return "No Due Date"
    if days_overdue <= 0:
        return "Current"
    if days_overdue <= 30:
        return "1-30 Days"
    if days_overdue <= 60:
        return "31-60 Days"
    if days_overdue <= 90:
        return "61-90 Days"
    if days_overdue <= 180:
        return "91-180 Days"
    if days_overdue <= 365:
        return "181-365 Days"
    return "365+ Days"


def _received_map():
    """instalment_id -> total collected (Decimal)."""
    rows = db.session.query(Collection.instalment_id,
                            func.coalesce(func.sum(Collection.amount), 0)) \
        .group_by(Collection.instalment_id).all()
    return {iid: Decimal(str(total)) for iid, total in rows}


def instalment_rows(report_date=None, currency=None, account_type=None):
    """Return enriched instalment dicts with net, days_overdue, bucket, status."""
    report_date = report_date or date.today()
    rec = _received_map()
    q = db.session.query(Instalment, Customer).join(Customer, Instalment.customer_id == Customer.id)
    if currency:
        q = q.filter(Instalment.currency == currency)
    if account_type:
        q = q.filter(Instalment.account_type == account_type)
    out = []
    for inst, cust in q.all():
        received = rec.get(inst.id, Decimal("0"))
        state = (inst.state or "open")
        if state in ("converted", "rescheduled"):
            # Closed by conversion/reschedule — outstanding is zero and it is NOT a cash receipt.
            net = Decimal("0")
            dov = (report_date - inst.due_date).days if inst.due_date else None
            bucket = "Converted" if state == "converted" else "Rescheduled"
            status = state.upper()
        else:
            net = (inst.original_amount or Decimal("0")) - received
            if net < 0:
                net = Decimal("0")
            dov = (report_date - inst.due_date).days if inst.due_date else None
            if net <= 0:
                bucket, status = "Settled", "SETTLED"
            elif inst.due_date is None:
                bucket, status = "No Due Date", "NO DATE"
            else:
                bucket = bucket_for(dov)
                status = "OVERDUE" if dov > 0 else "CURRENT"
        out.append(dict(
            inst_id=inst.inst_id, cust_ref=cust.cust_ref, account_no=cust.account_no,
            customer=cust.name, currency=inst.currency,
            account_type=(inst.account_type or "MACHINE"),
            original=float(inst.original_amount or 0), received=float(received),
            net=float(net), due_date=inst.due_date, days_overdue=dov,
            bucket=bucket, status=status, security=inst.security,
            reference=inst.reference, customer_id=cust.id,
            state=state, origin=(inst.origin or "original"),
            orig_fx_rate=(float(inst.orig_fx_rate) if inst.orig_fx_rate is not None else None),
            id=inst.id,
            legal=(cust.legal_status == "legal"),
        ))
    return out


ACCOUNT_TYPES = ["MACHINE", "PARTS"]
ACCOUNT_TYPE_LABELS = {"MACHINE": "Machine", "PARTS": "Parts & Accessories"}


def dashboard_kpis_by_type(report_date=None):
    """Per currency, split into Machine and Parts, each with its own totals, plus a combined line.
    EGP and USD are always kept separate."""
    rows = instalment_rows(report_date=report_date)
    out = {}
    for ccy in ("EGP", "USD"):
        sub = [r for r in rows if r["currency"] == ccy]
        block = {}
        for atype in ("MACHINE", "PARTS", "ALL"):
            s = sub if atype == "ALL" else [r for r in sub if r["account_type"] == atype]
            total = sum(r["net"] for r in s)
            overdue = sum(r["net"] for r in s if r["bucket"] in OVERDUE_BUCKETS)
            custs = {r["customer_id"] for r in s if r["net"] > 0}
            block[atype] = dict(total=total, overdue=overdue,
                                overdue_pct=(overdue / total * 100 if total else 0),
                                customers=len(custs))
        out[ccy] = block
    return out


def next_parts_inst_id(customer):
    """Next Parts invoice/instalment id for a customer, e.g. SP-EGP012-03."""
    from models import Instalment
    prefix = f"SP-{customer.cust_ref}-"
    nums = []
    for i in Instalment.query.filter_by(customer_id=customer.id, account_type="PARTS").all():
        if (i.inst_id or "").startswith(prefix):
            tail = i.inst_id[len(prefix):]
            if tail.isdigit():
                nums.append(int(tail))
    n = (max(nums) + 1) if nums else 1
    return f"{prefix}{n:02d}"


# ---------------- Upload 3: reschedule / add-machine / currency conversion ----------------
def next_deal_inst_id(customer, tag):
    """Next id for an instalment created by a deal action. tag e.g. 'CV' (conversion),
    'RS' (reschedule), 'MC' (machine). Produces CV-EGP012-01 etc."""
    from models import Instalment
    prefix = f"{tag}-{customer.cust_ref}-"
    nums = []
    for i in Instalment.query.filter_by(customer_id=customer.id).all():
        if (i.inst_id or "").startswith(prefix):
            t = i.inst_id[len(prefix):]
            if t.isdigit():
                nums.append(int(t))
    n = (max(nums) + 1) if nums else 1
    return f"{prefix}{n:02d}"


def open_instalments(customer_id, currency=None, account_type=None):
    """Open (not converted/rescheduled/settled) instalment rows with net > 0 for a customer."""
    rows = [r for r in instalment_rows()
            if r["customer_id"] == customer_id and r["state"] == "open" and r["net"] > 0]
    if currency:
        rows = [r for r in rows if r["currency"] == currency]
    if account_type:
        rows = [r for r in rows if r["account_type"] == account_type]
    rows.sort(key=lambda r: (r["due_date"] or date.max))
    return rows


def compute_conversion(items, agreed_rate):
    """FX conversion maths for the warning banner. items: dicts with net (USD outstanding),
    orig_fx_rate, inst_id. Compares agreed rate to each instalment's original contract rate.
    Returns per-line and totals: original EGP value, new EGP value, FX gain/loss, total deal value."""
    agreed = Decimal(str(agreed_rate))
    rows = []
    tot_usd = Decimal("0"); tot_orig = Decimal("0"); tot_new = Decimal("0"); have_orig = False
    for it in items:
        usd = Decimal(str(it["net"]))
        orig = Decimal(str(it["orig_fx_rate"])) if it.get("orig_fx_rate") else None
        orig_egp = (usd * orig) if orig is not None else None
        new_egp = (usd * agreed)
        diff = (new_egp - orig_egp) if orig_egp is not None else None
        rows.append(dict(inst_id=it["inst_id"], net_usd=float(usd),
                         orig_rate=(float(orig) if orig is not None else None),
                         orig_egp=(float(orig_egp) if orig_egp is not None else None),
                         new_egp=float(new_egp),
                         fx_diff=(float(diff) if diff is not None else None)))
        tot_usd += usd; tot_new += new_egp
        if orig_egp is not None:
            tot_orig += orig_egp; have_orig = True
    fx_diff = float(tot_new - tot_orig) if have_orig else None
    return dict(rows=rows, agreed_rate=float(agreed),
                total_usd=float(tot_usd),
                total_orig_egp=(float(tot_orig) if have_orig else None),
                total_new_egp=float(tot_new),
                fx_diff=fx_diff,
                is_loss=(fx_diff is not None and fx_diff < -0.005),
                is_gain=(fx_diff is not None and fx_diff > 0.005))


def build_schedule(total, count, first_date, freq_days=30):
    """Split a total into `count` equal instalments (last absorbs rounding), dated from
    first_date every freq_days. Returns list of dict(amount, due_date)."""
    from datetime import timedelta
    total = Decimal(str(total)); count = max(1, int(count))
    base = (total / count).quantize(Decimal("0.01"))
    amounts = [base] * (count - 1)
    amounts.append(total - base * (count - 1))
    out = []; d = first_date
    for a in amounts:
        out.append(dict(amount=float(a), due_date=d))
        d = d + timedelta(days=int(freq_days))
    return out


def clearance_threshold_days():
    from models import get_setting
    try:
        return int(get_setting("clearance_overdue_days", "190"))
    except Exception:
        return 190


def customer_max_overdue(customer_id, report_date=None):
    """Highest days-overdue across a customer's open instalments (0 if none overdue)."""
    rows = [r for r in instalment_rows(report_date=report_date)
            if r["customer_id"] == customer_id and r["state"] == "open" and r["net"] > 0]
    days = [r["days_overdue"] for r in rows if r["days_overdue"] and r["days_overdue"] > 0]
    return max(days) if days else 0


def clearance_status(customer, report_date=None):
    """NO-GO if the customer is in legal OR more than the configured days overdue.
    Returns dict(ok, reasons, max_overdue, threshold)."""
    threshold = clearance_threshold_days()
    reasons = []
    if getattr(customer, "legal_status", "") == "legal":
        reasons.append("Account is in legal")
    mx = customer_max_overdue(customer.id, report_date)
    if mx > threshold:
        reasons.append(f"Overdue {mx} days (over {threshold}-day limit)")
    return dict(ok=(len(reasons) == 0), reasons=reasons, max_overdue=mx, threshold=threshold)


# ---- Guarantees ----
GUARANTEE_STATUSES = ["held", "due", "cleared", "bounced", "returned"]
INSTRUMENTS = {"CHEQUE": "Cheque", "PN": "Promissory Note"}


def guarantees_for(customer_id):
    from models import Guarantee
    return Guarantee.query.filter_by(customer_id=customer_id).order_by(Guarantee.due_date).all()


def guaranteed_instalment_ids():
    """Set of instalment ids that have at least one live guarantee (not bounced/returned)."""
    from models import Guarantee
    ids = set()
    for g in Guarantee.query.filter(Guarantee.status.in_(["held", "due", "cleared"])).all():
        if g.instalment_id:
            ids.add(g.instalment_id)
    return ids


def unguaranteed_exposure(report_date=None, currency=None):
    """Open MACHINE instalments with no live guarantee instrument, grouped for the report.
    Parts are excluded by design (they carry no guarantee)."""
    gids = guaranteed_instalment_ids()
    rows = [r for r in instalment_rows(report_date=report_date, currency=currency,
                                       account_type="MACHINE")
            if r["state"] == "open" and r["net"] > 0 and r["id"] not in gids]
    rows.sort(key=lambda r: (r["currency"], -r["net"]))
    return rows


def propose_allocation(customer_id, account_type, currency, amount):
    """Oldest-due-date-first allocation within one account and currency.
    Legal-customer instalments are skipped in the auto-suggestion (0), but still listed so the
    controller can deliberately allocate to them on override. Ties broken by instalment ID;
    instalments with no due date come last. Any surplus becomes unallocated credit on account."""
    amount = Decimal(str(amount))
    rows = [r for r in instalment_rows()
            if r["customer_id"] == customer_id and r["account_type"] == account_type
            and r["currency"] == currency and r["state"] == "open" and r["net"] > 0]
    rows.sort(key=lambda r: (r["due_date"] or date.max, r["inst_id"]))
    remaining = amount
    out = []
    for r in rows:
        net = Decimal(str(r["net"]))
        if r["legal"]:
            sugg = Decimal("0")           # skip legal/disputed in the auto-suggest
        else:
            sugg = min(remaining, net) if remaining > 0 else Decimal("0")
            remaining -= sugg
        out.append(dict(id=r["id"], inst_id=r["inst_id"], due_date=r["due_date"],
                        bucket=r["bucket"], net=float(net), suggested=float(sugg),
                        legal=r["legal"]))
    allocated = sum(Decimal(str(o["suggested"])) for o in out)
    surplus = float(amount - allocated)
    return dict(rows=out, amount=float(amount), allocated=float(allocated),
                surplus=(surplus if surplus > 0.005 else 0.0))


def get_account_credit(customer_id, account_type, currency):
    from models import AccountCredit
    c = AccountCredit.query.filter_by(customer_id=customer_id, account_type=account_type,
                                      currency=currency).first()
    return float(c.balance) if (c and c.balance) else 0.0


def account_credits_for(customer_id):
    """All non-zero unallocated credits for a customer, for display on the customer page."""
    from models import AccountCredit
    out = []
    for c in AccountCredit.query.filter_by(customer_id=customer_id).all():
        if c.balance and float(c.balance) > 0:
            out.append(dict(account_type=c.account_type, currency=c.currency, balance=float(c.balance)))
    return out


def adjust_account_credit(customer_id, account_type, currency, delta):
    from models import db, AccountCredit
    c = AccountCredit.query.filter_by(customer_id=customer_id, account_type=account_type,
                                      currency=currency).first()
    if not c:
        c = AccountCredit(customer_id=customer_id, account_type=account_type,
                          currency=currency, balance=Decimal("0"))
        db.session.add(c); db.session.flush()
    c.balance = (c.balance or Decimal("0")) + Decimal(str(delta))
    if c.balance < 0:
        c.balance = Decimal("0")
    db.session.commit()
    return float(c.balance)


def ageing_impact(pairs):
    """pairs: list of (bucket, amount). Returns {bucket: total} in ageing order."""
    order = ["Current", "1-30 Days", "31-60 Days", "61-90 Days", "91-180 Days",
             "181-365 Days", "365+ Days", "No Due Date"]
    d = {}
    for bucket, amt in pairs:
        d[bucket] = d.get(bucket, 0) + amt
    return [(b, d[b]) for b in order if b in d] + [(b, v) for b, v in d.items() if b not in order]


def conversion_report_rows():
    """All currency conversions (source USD instalments closed as converted), for the report."""
    from models import Instalment, Customer
    out = []
    q = (db.session.query(Instalment, Customer)
         .join(Customer, Instalment.customer_id == Customer.id)
         .filter(Instalment.state == "converted"))
    for inst, cust in q.all():
        usd = float(inst.original_amount or 0)
        orig = float(inst.orig_fx_rate) if inst.orig_fx_rate is not None else None
        rate = float(inst.converted_rate) if inst.converted_rate is not None else None
        orig_egp = (usd * orig) if orig is not None else None
        new_egp = (usd * rate) if rate is not None else None
        diff = (new_egp - orig_egp) if (orig_egp is not None and new_egp is not None) else None
        out.append(dict(inst_id=inst.inst_id, customer=cust.name, cust_ref=cust.cust_ref,
                        usd=usd, orig_rate=orig, agreed_rate=rate,
                        orig_egp=orig_egp, new_egp=new_egp, fx_diff=diff,
                        agreement_ref=inst.agreement_ref, linked_id=inst.linked_id,
                        when=inst.created_at))
    out.sort(key=lambda r: (r["when"] or date.min), reverse=True)
    return out


def customer_balances(report_date=None):
    """Per-customer roll-up: total net, overdue, bucket split, oldest days."""
    rows = instalment_rows(report_date=report_date)
    agg = {}
    for r in rows:
        c = agg.setdefault(r["customer_id"], dict(
            customer_id=r["customer_id"], cust_ref=r["cust_ref"], account_no=r["account_no"],
            customer=r["customer"], currency=r["currency"], total=0.0, overdue=0.0,
            oldest=0, legal=r.get("legal", False), buckets={b: 0.0 for b in BUCKETS}))
        c["total"] += r["net"]
        c["buckets"][r["bucket"]] = c["buckets"].get(r["bucket"], 0.0) + r["net"]
        if r["bucket"] in OVERDUE_BUCKETS:
            c["overdue"] += r["net"]
            if r["days_overdue"] and r["days_overdue"] > c["oldest"]:
                c["oldest"] = r["days_overdue"]
    return list(agg.values())


def dashboard_kpis(report_date=None):
    """KPIs per currency (never combined)."""
    rows = instalment_rows(report_date=report_date)
    k = {}
    for ccy in ("EGP", "USD"):
        sub = [r for r in rows if r["currency"] == ccy]
        total = sum(r["net"] for r in sub)
        overdue = sum(r["net"] for r in sub if r["bucket"] in OVERDUE_BUCKETS)
        custs = {r["customer_id"] for r in sub if r["net"] > 0}
        cust_overdue = {r["customer_id"] for r in sub if r["bucket"] in OVERDUE_BUCKETS}
        k[ccy] = dict(total=total, overdue=overdue,
                      overdue_pct=(overdue / total * 100 if total else 0),
                      customers=len(custs), customers_overdue=len(cust_overdue))
    return k


def aged_matrix(currency, report_date=None):
    """Customer x bucket matrix for one currency, sorted by total desc, with totals."""
    custs = [c for c in customer_balances(report_date=report_date) if c["currency"] == currency]
    custs.sort(key=lambda c: c["total"], reverse=True)
    show_buckets = [b for b in BUCKETS if b != "No Due Date"] + \
                   (["No Due Date"] if any(c["buckets"].get("No Due Date") for c in custs) else [])
    totals = {b: sum(c["buckets"].get(b, 0.0) for c in custs) for b in show_buckets}
    grand = sum(c["total"] for c in custs)
    overdue = sum(c["overdue"] for c in custs)
    return dict(customers=custs, buckets=show_buckets, totals=totals,
                grand=grand, overdue=overdue)


def ageing_summary(report_date=None):
    """Bucket totals per currency for the dashboard."""
    rows = instalment_rows(report_date=report_date)
    out = {}
    for ccy in ("EGP", "USD"):
        sub = [r for r in rows if r["currency"] == ccy]
        out[ccy] = {b: sum(r["net"] for r in sub if r["bucket"] == b) for b in BUCKETS}
        out[ccy]["_total"] = sum(r["net"] for r in sub)
    return out


def collections_summary():
    rows = db.session.query(Collection.currency,
                            func.coalesce(func.sum(Collection.amount), 0),
                            func.count(Collection.id)).group_by(Collection.currency).all()
    m = {"EGP": dict(amount=0.0, count=0), "USD": dict(amount=0.0, count=0)}
    for ccy, amt, cnt in rows:
        if ccy in m:
            m[ccy] = dict(amount=float(amt), count=cnt)
    return m


# ---------------- Reminder-letter logic (4 levels) ----------------
REMINDER_LEVELS = {
    1: dict(name="Reminder (Level 1)", tone="courtesy",
            trigger="1–30 days overdue",
            heading="Payment Reminder",
            body=("We note that the following amount on your account is now overdue. "
                  "This may simply be an oversight. We would be grateful if you could "
                  "arrange settlement at your earliest convenience.")),
    2: dict(name="Second Reminder (Level 2)", tone="firm",
            trigger="31–60 days overdue",
            heading="Second Payment Reminder",
            body=("Our records show the amount below remains outstanding despite our "
                  "earlier reminder. Please arrange payment within 7 days to keep your "
                  "account in good standing.")),
    3: dict(name="Urgent Notice (Level 3)", tone="urgent",
            trigger="61–90 days overdue",
            heading="Urgent — Overdue Account",
            body=("The amount below is now significantly overdue. Immediate payment is "
                  "required. Should we not receive payment or hear from you within 7 days, "
                  "your account may be placed on stop and further supplies suspended.")),
    4: dict(name="Final Demand (Level 4)", tone="final",
            trigger="over 90 days overdue",
            heading="FINAL DEMAND",
            body=("This is our final demand for payment of the overdue amount below. "
                  "Unless payment is received in full within 7 days, we will refer the "
                  "matter for recovery/legal action without further notice, and any "
                  "additional costs may be added to your account.")),
}


def reminder_level_for_days(oldest_days):
    """Map the oldest overdue age to a reminder level (0 = nothing due)."""
    if not oldest_days or oldest_days <= 0:
        return 0
    if oldest_days <= 30:
        return 1
    if oldest_days <= 60:
        return 2
    if oldest_days <= 90:
        return 3
    return 4


def reminder_candidates(report_date=None):
    """Customers with overdue balances and their suggested reminder level."""
    out = []
    for c in customer_balances(report_date=report_date):
        if c.get("legal"):
            continue
        lvl = reminder_level_for_days(c["oldest"])
        if lvl > 0 and c["overdue"] > 0:
            c = dict(c)
            c["level"] = lvl
            c["level_name"] = REMINDER_LEVELS[lvl]["name"]
            out.append(c)
    out.sort(key=lambda c: (-c["level"], -c["overdue"]))
    return out


# ---------------- FX & EGP-equivalent ----------------
def get_fx():
    """USD -> EGP rate (editable in Settings). Default 50.5."""
    from models import get_setting
    try:
        return float(get_setting("fx_rate", "50.5"))
    except (TypeError, ValueError):
        return 50.5


def egp_equivalent(report_date=None):
    """Combined book value expressed in EGP using the current FX rate.
    Currencies remain separate in every report; this is a memo total only."""
    k = dashboard_kpis(report_date)
    fx = get_fx()
    return dict(fx=fx,
                total=k["EGP"]["total"] + k["USD"]["total"] * fx,
                overdue=k["EGP"]["overdue"] + k["USD"]["overdue"] * fx)


# ---------------- Monthly collections by method ----------------
def collections_by_month():
    """Return per-currency {month: {method: amount, _total: amount}} plus method list."""
    from models import Collection
    rows = Collection.query.all()
    methods = ["Cash", "Cheque", "Bank Transfer", "Card", "Other"]
    out = {"EGP": {}, "USD": {}}
    for c in rows:
        ccy = c.currency if c.currency in out else "EGP"
        m = (c.collected_on.strftime("%Y-%m") if c.collected_on else "unknown")
        meth = c.method if c.method in methods else "Other"
        bucket = out[ccy].setdefault(m, {mm: 0.0 for mm in methods})
        bucket[meth] += float(c.amount or 0)
    # add totals per month
    totals = {"EGP": {mm: 0.0 for mm in methods}, "USD": {mm: 0.0 for mm in methods}}
    for ccy in out:
        for m, d in out[ccy].items():
            d["_total"] = sum(d[mm] for mm in methods)
            for mm in methods:
                totals[ccy][mm] += d[mm]
        totals[ccy]["_total"] = sum(totals[ccy][mm] for mm in methods)
    return dict(data=out, methods=methods, totals=totals)


# ==================== Credit-controller call scheduler ====================
# Prioritises which overdue customers to call, driven by aged debt: a
# transparent score combining amount, age, security and escalation, tuned by a
# selectable collection strategy. Currencies are ranked on an EGP-equivalent
# basis (using the FX rate) purely so one call list can span both books.

from datetime import timedelta, datetime

CALL_STRATEGIES = {
    "balanced": dict(label="Balanced", amount=.35, age=.30, security=.15, escalation=.15, promise=.05),
    "cash":     dict(label="Maximise cash recovery", amount=.55, age=.20, security=.10, escalation=.10, promise=.05),
    "oldest":   dict(label="Reduce oldest debt", amount=.25, age=.50, security=.10, escalation=.10, promise=.05),
    "risk":     dict(label="Risk-based (unsecured first)", amount=.20, age=.30, security=.35, escalation=.10, promise=.05),
}
OUTCOMES = ["promise_to_pay", "no_answer", "callback", "dispute", "paid", "refused"]


def get_call_setting(key, default):
    from models import get_setting
    return get_setting(key, default)


def get_strategy():
    s = get_call_setting("call_strategy", "balanced")
    return s if s in CALL_STRATEGIES else "balanced"


def _last_contact_map():
    """customer_id -> most recent contact date (completed call or sent reminder)."""
    from models import CallTask, Reminder
    m = {}
    for t in CallTask.query.filter(CallTask.last_contact.isnot(None)).all():
        d = t.last_contact
        if d and (t.customer_id not in m or d > m[t.customer_id]):
            m[t.customer_id] = d
    for r in Reminder.query.all():
        if r.sent_on and (r.customer_id not in m or r.sent_on > m[r.customer_id]):
            m[r.customer_id] = r.sent_on
    return m


def _broken_promises():
    """customer_ids who promised to pay by a date now passed."""
    from models import CallTask
    today = date.today()
    out = set()
    for t in CallTask.query.filter(CallTask.outcome == "promise_to_pay").all():
        if t.promise_date and t.promise_date < today:
            out.add(t.customer_id)
    return out


def _over_limit_customers(report_date=None):
    """customer_ids whose machine or parts outstanding exceeds their credit limit."""
    from models import Customer
    rows = instalment_rows(report_date=report_date)
    machine = {}
    parts = {}
    for r in rows:
        if r["state"] != "open" or r["net"] <= 0:
            continue
        if r["account_type"] == "PARTS":
            parts[r["customer_id"]] = parts.get(r["customer_id"], 0) + r["net"]
        else:
            machine[r["customer_id"]] = machine.get(r["customer_id"], 0) + r["net"]
    out = set()
    for c in Customer.query.all():
        if c.credit_limit and machine.get(c.id, 0) > float(c.credit_limit):
            out.add(c.id)
        if c.parts_credit_limit and parts.get(c.id, 0) > float(c.parts_credit_limit):
            out.add(c.id)
    return out


def _guarantee_due_soon(within_days=14):
    """customer_ids with a live cheque/PN due within N days or already past due."""
    from models import Guarantee
    today = date.today()
    horizon = today + timedelta(days=within_days)
    out = set()
    for g in Guarantee.query.filter(Guarantee.status.in_(["held", "due"])).all():
        if g.due_date and g.due_date <= horizon:
            out.add(g.customer_id)
    return out


def _broken_reschedule(report_date=None):
    """customer_ids with a rescheduled instalment that is now overdue (missed new terms)."""
    rows = instalment_rows(report_date=report_date)
    out = set()
    for r in rows:
        if (r.get("origin") == "reschedule" and r["state"] == "open"
                and r["net"] > 0 and r["days_overdue"] and r["days_overdue"] > 0):
            out.add(r["customer_id"])
    return out


def collection_priority(report_date=None, strategy=None, owner_id=None):
    """Score every customer with overdue debt. Returns list sorted by score desc.
    If owner_id is given, only that ledger owner's customers are considered."""
    report_date = report_date or date.today()
    w = CALL_STRATEGIES[strategy or get_strategy()]
    fx = get_fx()
    rows = instalment_rows(report_date=report_date)

    from models import Customer
    owner_of = {c.id: c.owner_id for c in Customer.query.all()}

    agg = {}
    for r in rows:
        if r["bucket"] not in OVERDUE_BUCKETS:
            continue
        if r.get("legal"):          # legal accounts are handled by the legal team, not chased
            continue
        if owner_id is not None and owner_of.get(r["customer_id"]) != owner_id:
            continue
        a = agg.setdefault(r["customer_id"], dict(
            customer_id=r["customer_id"], cust_ref=r["cust_ref"], customer=r["customer"],
            account_no=r["account_no"], currency=r["currency"], phone=None,
            overdue=0.0, unsecured=0.0, oldest=0))
        a["overdue"] += r["net"]
        if (r["security"] or "").lower().startswith("unsec"):
            a["unsecured"] += r["net"]
        if r["days_overdue"] and r["days_overdue"] > a["oldest"]:
            a["oldest"] = r["days_overdue"]

    if not agg:
        return []
    last = _last_contact_map()
    broken = _broken_promises()
    over_limit = _over_limit_customers(report_date)
    guar_due = _guarantee_due_soon()
    broken_resched = _broken_reschedule(report_date)
    threshold = clearance_threshold_days()
    # phone numbers
    from models import Customer
    phones = {c.id: c.phone for c in Customer.query.all()}

    def egp_eq(a):
        return a["overdue"] * (fx if a["currency"] == "USD" else 1)

    max_amt = max(egp_eq(a) for a in agg.values()) or 1
    out = []
    for a in agg.values():
        amt_f = egp_eq(a) / max_amt                     # 0..1
        age_f = min(a["oldest"] / 365.0, 1.0)           # 0..1
        sec_f = (a["unsecured"] / a["overdue"]) if a["overdue"] else 0
        lvl = reminder_level_for_days(a["oldest"])      # 1..4
        esc_f = lvl / 4.0
        prom_f = 1.0 if a["customer_id"] in broken else 0.0
        score = 100 * (w["amount"] * amt_f + w["age"] * age_f + w["security"] * sec_f
                       + w["escalation"] * esc_f + w["promise"] * prom_f)
        # --- transparent signal bonuses (Upload 4 aware) with reason chips ---
        cid = a["customer_id"]
        reasons = []
        if a["oldest"] >= 1:
            reasons.append(f"{a['oldest']}d overdue")
        approaching_legal = (not a.get("legal")) and threshold - 30 <= a["oldest"] < threshold
        if cid in broken:
            score += 10; reasons.append("broken promise")
        if cid in broken_resched:
            score += 10; reasons.append("broken reschedule")
        if approaching_legal:
            score += 10; reasons.append(f"nearing legal ({threshold}d)")
        if cid in guar_due:
            score += 12; reasons.append("cheque/PN due")
        if cid in over_limit:
            score += 8; reasons.append("over limit")
        lc = last.get(cid)
        if lc:
            dsc = (report_date - lc).days
            if dsc >= 30:
                score += 5; reasons.append(f"no contact {dsc}d")
        else:
            reasons.append("never contacted")
        a = dict(a)
        a.update(phone=phones.get(cid), score=round(score, 1), level=lvl,
                 unsecured_pct=round(100 * sec_f), broken_promise=bool(prom_f),
                 over_limit=(cid in over_limit), guarantee_due=(cid in guar_due),
                 broken_reschedule=(cid in broken_resched), approaching_legal=approaching_legal,
                 reasons=reasons, last_contact=lc)
        out.append(a)
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def _business_days(start, n):
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:   # Mon-Fri
            days.append(d)
        d += timedelta(days=1)
    return days


def generate_call_plan(start_date=None, days=5, capacity=15, cooldown=5, assigned_to=None,
                       strategy=None, replace_pending=True, owner_id=None):
    """Create prioritised CallTask rows across working days. Returns count created.
    If owner_id is set, the plan covers only that controller's allocated ledger."""
    from models import db, CallTask
    start_date = start_date or date.today()
    today = date.today()
    if replace_pending:
        dq = CallTask.query.filter(CallTask.status == "pending",
                                   CallTask.scheduled_for >= start_date)
        if owner_id is not None:
            from models import Customer
            ids = [c.id for c in Customer.query.filter_by(owner_id=owner_id).all()]
            dq = dq.filter(CallTask.customer_id.in_(ids or [-1]))
        dq.delete(synchronize_session=False)
        db.session.commit()

    pending_future = {t.customer_id for t in CallTask.query.filter(
        CallTask.status == "pending", CallTask.scheduled_for >= start_date).all()}

    pri = collection_priority(strategy=strategy, owner_id=owner_id)
    eligible = []
    for p in pri:
        if p["customer_id"] in pending_future:
            continue
        lc = p["last_contact"]
        if lc and (today - lc).days < cooldown:
            continue
        eligible.append(p)

    slots = _business_days(start_date, days)
    created = 0
    idx = 0
    for day in slots:
        for rank in range(1, capacity + 1):
            if idx >= len(eligible):
                break
            p = eligible[idx]; idx += 1
            db.session.add(CallTask(customer_id=p["customer_id"], scheduled_for=day,
                                    priority_score=p["score"], rank=rank, status="pending",
                                    assigned_to=assigned_to))
            created += 1
        if idx >= len(eligible):
            break
    db.session.commit()
    return created


def controller_scorecard(start=None, end=None):
    """Per-controller activity & effectiveness over a date window.
    Activity: calls assigned vs completed (coverage). Effectiveness: promises obtained,
    promises kept, cash collected in the window. Normalised so it can gate commission later."""
    from models import CallTask, Collection, User
    end = end or date.today()
    start = start or (end - timedelta(days=30))

    # map a controller display name -> user
    users = User.query.all()
    name_of = {}
    for u in users:
        name_of[u.username] = u
        if u.full_name:
            name_of[u.full_name] = u

    stats = {}

    def row(key):
        return stats.setdefault(key, dict(controller=key, assigned=0, completed=0,
                                          contacted=0, promises=0, promises_kept=0,
                                          collected=0.0, collected_ccy={}))

    # calls assigned/completed in window
    for t in CallTask.query.filter(CallTask.scheduled_for >= start,
                                   CallTask.scheduled_for <= end).all():
        who = t.assigned_to or "(unassigned)"
        r = row(who)
        r["assigned"] += 1
        if t.status == "completed":
            r["completed"] += 1
        if t.outcome and t.outcome not in ("no_answer",):
            r["contacted"] += 1
        if t.outcome == "promise_to_pay":
            r["promises"] += 1
            # kept if a collection from that customer landed on/after the promise and >= promised amount-ish
            if t.promise_date:
                paid = Collection.query.filter(Collection.customer_id == t.customer_id,
                                               Collection.collected_on >= t.created_at.date()
                                               if t.created_at else start).all()
                if paid:
                    r["promises_kept"] += 1

    # cash collected in window, attributed to the receiver
    for c in Collection.query.filter(Collection.collected_on >= start,
                                     Collection.collected_on <= end).all():
        who = c.received_by or "(unknown)"
        r = row(who)
        r["collected"] += float(c.amount or 0)
        cur = c.currency or "EGP"
        r["collected_ccy"][cur] = r["collected_ccy"].get(cur, 0) + float(c.amount or 0)

    out = []
    for key, r in stats.items():
        cov = (r["completed"] / r["assigned"] * 100) if r["assigned"] else 0
        keep = (r["promises_kept"] / r["promises"] * 100) if r["promises"] else 0
        r["coverage_pct"] = round(cov)
        r["promise_keep_pct"] = round(keep)
        out.append(r)
    out.sort(key=lambda x: (x["coverage_pct"], x["collected"]), reverse=True)
    return dict(rows=out, start=start, end=end)


def call_list_for(day, assigned_to=None, owner_id=None):
    """Pending calls scheduled for a day, enriched with current overdue + score, ordered.
    owner_id restricts to a controller's allocated ledger."""
    from models import CallTask, Customer
    q = CallTask.query.filter(CallTask.scheduled_for == day, CallTask.status == "pending")
    if assigned_to:
        q = q.filter(CallTask.assigned_to == assigned_to)
    tasks = q.all()
    if owner_id is not None:
        owned = {c.id for c in Customer.query.filter_by(owner_id=owner_id).all()}
        tasks = [t for t in tasks if t.customer_id in owned]
    pri = {p["customer_id"]: p for p in collection_priority()}
    out = []
    for t in tasks:
        p = pri.get(t.customer_id, {})
        out.append(dict(task=t, cust=t.customer, overdue=p.get("overdue", 0),
                        currency=p.get("currency", t.customer.currency), score=t.priority_score,
                        level=p.get("level", 0), oldest=p.get("oldest", 0),
                        phone=t.customer.phone, broken=p.get("broken_promise", False),
                        reasons=p.get("reasons", []), over_limit=p.get("over_limit", False),
                        guarantee_due=p.get("guarantee_due", False),
                        approaching_legal=p.get("approaching_legal", False)))
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def log_call_outcome(task_id, outcome, user, promise_amount=None, promise_date=None, notes=None):
    """Record a call result and auto-schedule the appropriate follow-up."""
    from models import db, CallTask
    t = db.session.get(CallTask, task_id)
    if not t:
        return None
    today = date.today()
    t.status = "completed"
    t.outcome = outcome
    t.completed_at = datetime.utcnow()
    t.last_contact = today
    t.assigned_to = t.assigned_to or user
    t.notes = notes
    follow = None
    if outcome == "promise_to_pay":
        t.promise_amount = promise_amount
        t.promise_date = promise_date
        follow = (promise_date + timedelta(days=1)) if promise_date else today + timedelta(days=7)
    elif outcome in ("no_answer", "callback"):
        follow = today + timedelta(days=2)
    elif outcome == "dispute":
        follow = today + timedelta(days=3)
    elif outcome == "refused":
        follow = today + timedelta(days=7)
    # 'paid' -> no follow-up
    if follow:
        while follow.weekday() >= 5:
            follow += timedelta(days=1)
        db.session.add(CallTask(customer_id=t.customer_id, scheduled_for=follow,
                                priority_score=t.priority_score, status="pending",
                                assigned_to=t.assigned_to, notes=f"Follow-up: {outcome}"))
    db.session.commit()
    return t


def call_stats():
    from models import CallTask
    today = date.today()
    pending = CallTask.query.filter(CallTask.status == "pending").count()
    due_today = CallTask.query.filter(CallTask.status == "pending",
                                      CallTask.scheduled_for <= today).count()
    completed = CallTask.query.filter(CallTask.status == "completed").count()
    promises = CallTask.query.filter(CallTask.outcome == "promise_to_pay").count()
    return dict(pending=pending, due_today=due_today, completed=completed, promises=promises)


# ==================== Contact notes / comments trail ====================
def bucket_at(due_date, on_date):
    """Ageing bucket of an instalment on a given date (used to snapshot at collection)."""
    if not due_date:
        return "No Due Date"
    return bucket_for((on_date - due_date).days)


def add_note(customer_id, author, text, kind="note", call_task_id=None):
    from models import db, CallNote
    if not text:
        return None
    n = CallNote(customer_id=customer_id, author=author, text=text, kind=kind,
                 call_task_id=call_task_id)
    db.session.add(n)
    db.session.commit()
    return n


def customer_notes(customer_id, limit=100):
    from models import CallNote
    return (CallNote.query.filter_by(customer_id=customer_id)
            .order_by(CallNote.created_at.desc()).limit(limit).all())


# ==================== Commission (weighted by ageing bucket) ====================
# Controllers earn commission on collections, weighted by the ageing bucket the
# money was collected from (older debt is harder, so it carries a higher rate).
# Rates are editable in Settings; targets are optional (per controller/currency/bucket).

COMMISSION_ORDER = ["Current", "1-30 Days", "31-60 Days", "61-90 Days",
                    "91-180 Days", "181-365 Days", "365+ Days", "No Due Date"]
DEFAULT_COMMISSION = {"Current": 0.5, "1-30 Days": 1.0, "31-60 Days": 1.5,
                      "61-90 Days": 2.0, "91-180 Days": 3.0, "181-365 Days": 4.0,
                      "365+ Days": 5.0, "No Due Date": 1.0}


def _bkt_suffix(b):
    return b.lower().replace(" ", "_").replace("-", "_").replace("+", "plus")


def _bucket_key(b):
    return "comm_rate_" + _bkt_suffix(b)


def _owner_key(b):
    return "comm_owner_" + _bkt_suffix(b)


def get_commission_rates():
    from models import get_setting
    out = {}
    for b in COMMISSION_ORDER:
        v = get_setting(_bucket_key(b), None)
        try:
            out[b] = float(v) if v not in (None, "") else DEFAULT_COMMISSION[b]
        except (TypeError, ValueError):
            out[b] = DEFAULT_COMMISSION[b]
    return out


def set_commission_rates(form):
    from models import set_setting
    for b in COMMISSION_ORDER:
        key = _bucket_key(b)
        if key in form:
            set_setting(key, form.get(key) or DEFAULT_COMMISSION[b])
        okey = _owner_key(b)
        if okey in form and form.get(okey) not in (None, ""):
            set_setting(okey, form.get(okey))


def get_targets():
    """(controller, currency, bucket) -> target amount."""
    from models import CommissionTarget
    return {(t.controller, t.currency, t.bucket): float(t.target_amount or 0)
            for t in CommissionTarget.query.all()}


def get_owner_share(bucket=None):
    """Percent of commission going to the ledger owner; the rest goes to whoever
    recorded the collection. Can be set per ageing bucket, else the global default
    (70) applies."""
    from models import get_setting
    try:
        g = float(get_setting("commission_owner_share", "70"))
    except (TypeError, ValueError):
        g = 70.0
    g = max(0.0, min(100.0, g))
    if bucket is None:
        return g
    v = get_setting(_owner_key(bucket))
    if v not in (None, ""):
        try:
            return max(0.0, min(100.0, float(v)))
        except (TypeError, ValueError):
            return g
    return g


def owner_shares_by_bucket():
    return {b: get_owner_share(b) for b in COMMISSION_ORDER}


def _new_role_block(rates):
    return dict(buckets={b: dict(collected=0.0, rate=rates.get(b, 0), commission=0.0,
                                 target=0.0) for b in COMMISSION_ORDER},
                collected=0.0, commission=0.0, target=0.0, weighted_ach=None)


def commission_report(date_from=None, date_to=None, controller=None, group_by="owner"):
    """Per-controller commission, weighted by ageing bucket, SPLIT between the
    ledger owner and the person who recorded the collection. Each controller's
    total = their owner-share (collections from their ledger) + their collector-
    share (collections they recorded). Currencies never combined."""
    from models import Collection, Customer
    rates = get_commission_rates()
    targets = get_targets()
    names = owner_name_map()
    owner_of = {c.id: c.owner_id for c in Customer.query.all()}

    q = Collection.query
    if date_from:
        q = q.filter(Collection.collected_on >= date_from)
    if date_to:
        q = q.filter(Collection.collected_on <= date_to)

    rep = {}   # name -> ccy -> {'owner':block, 'collector':block, 'total_commission'}

    def block(name, ccy):
        r = rep.setdefault(name, {})
        cc = r.setdefault(ccy, dict(owner=_new_role_block(rates),
                                    collector=_new_role_block(rates),
                                    total_commission=0.0))
        return cc

    for c in q.all():
        ccy = c.currency if c.currency in ("EGP", "USD") else "EGP"
        bucket = c.bucket_at_collection or "No Due Date"
        amt = float(c.amount or 0)
        rate = rates.get(bucket, 0)
        comm = amt * rate / 100.0
        owner_share = get_owner_share(bucket) / 100.0
        collector_share = 1.0 - owner_share
        oid = owner_of.get(c.customer_id)
        owner_name = names.get(oid, "(unallocated)") if oid else "(unallocated)"
        collector_name = c.received_by or "(unattributed)"
        # owner share
        cc = block(owner_name, ccy)
        cc["owner"]["buckets"][bucket]["collected"] += amt
        cc["owner"]["buckets"][bucket]["commission"] += comm * owner_share
        cc["owner"]["collected"] += amt
        cc["owner"]["commission"] += comm * owner_share
        cc["total_commission"] += comm * owner_share
        # collector share
        cc2 = block(collector_name, ccy)
        cc2["collector"]["buckets"][bucket]["collected"] += amt
        cc2["collector"]["buckets"][bucket]["commission"] += comm * collector_share
        cc2["collector"]["collected"] += amt
        cc2["collector"]["commission"] += comm * collector_share
        cc2["total_commission"] += comm * collector_share

    # targets + achievement on the OWNER ledger
    for who, byccy in rep.items():
        for ccy, cc in byccy.items():
            ob = cc["owner"]
            tgt_total = 0.0
            ach_num = 0.0
            wsum = 0.0
            for b in COMMISSION_ORDER:
                t = targets.get((who, ccy, b), 0.0)
                ob["buckets"][b]["target"] = t
                tgt_total += t
                if t > 0:
                    ach_num += min(ob["buckets"][b]["collected"] / t, 2.0) * ob["buckets"][b]["rate"]
                    wsum += ob["buckets"][b]["rate"]
            ob["target"] = tgt_total
            ob["weighted_ach"] = (ach_num / wsum * 100) if wsum else None

    if controller:
        rep = {controller: rep.get(controller, {})}
    return dict(report=rep, rates=rates, order=COMMISSION_ORDER,
                owner_share=get_owner_share(), collector_share=100.0 - get_owner_share(),
                splits=owner_shares_by_bucket())


def controllers_list():
    """Distinct collectors seen on collections, plus all users."""
    from models import Collection, User
    a = {c.received_by for c in Collection.query.distinct(Collection.received_by).all() if c.received_by}
    b = {(u.full_name or u.username) for u in User.query.all()}
    return sorted(a | b)


# ==================== Ledger ownership / customer allocation ====================
# A manager allocates a range of customers to a credit controller, who becomes
# the "ledger owner". New customers are allocated too (explicitly at creation, or
# via a per-currency default owner). Performance and commission follow the owner.

def owner_name_map():
    """user_id -> display name."""
    from models import User
    return {u.id: (u.full_name or u.username) for u in User.query.all()}


def default_owner_for(currency):
    from models import get_setting
    v = get_setting(f"default_owner_{currency}")
    try:
        return int(v) if v else None
    except (TypeError, ValueError):
        return None


def _acct_num(x):
    digits = "".join(ch for ch in (x or "") if ch.isdigit())
    return int(digits) if digits else None


def allocate_range(owner_id, kind, frm, to):
    """Assign customers in a Cust Ref range ('ref') or account-number range ('account')."""
    from models import db, Customer
    frm = (frm or "").strip()
    to = (to or "").strip()
    changed = 0
    custs = Customer.query.all()
    if kind == "ref":
        lo, hi = frm.upper(), to.upper()
        for c in custs:
            r = (c.cust_ref or "").upper()
            if r and lo <= r <= hi:
                c.owner_id = owner_id; changed += 1
    else:
        lo, hi = _acct_num(frm), _acct_num(to)
        if lo is None or hi is None:
            return 0
        if lo > hi:
            lo, hi = hi, lo
        for c in custs:
            n = _acct_num(c.account_no)
            if n is not None and lo <= n <= hi:
                c.owner_id = owner_id; changed += 1
    db.session.commit()
    return changed


def allocation_summary(report_date=None):
    """Per-owner ledger: customers, outstanding, overdue (both currencies separate)."""
    names = owner_name_map()
    bals = customer_balances(report_date=report_date)
    from models import Customer
    owners = {c.id: c.owner_id for c in Customer.query.all()}
    out = {}
    for b in bals:
        oid = owners.get(b["customer_id"])
        key = names.get(oid, "(unallocated)") if oid else "(unallocated)"
        o = out.setdefault(key, dict(owner_id=oid, EGP=dict(n=0, total=0.0, overdue=0.0),
                                     USD=dict(n=0, total=0.0, overdue=0.0)))
        ccy = b["currency"]
        o[ccy]["n"] += 1
        o[ccy]["total"] += b["total"]
        o[ccy]["overdue"] += b["overdue"]
    return out


def controller_performance(date_from=None, date_to=None, report_date=None):
    """Per ledger owner: ledger size (outstanding/overdue), collections in the
    period from OWNED customers, recovery rate and commission. Per currency."""
    from models import Collection, Customer
    names = owner_name_map()
    owner_of = {c.id: c.owner_id for c in Customer.query.all()}
    comm = commission_report(date_from, date_to, group_by="owner")["report"]

    # ledger balances per owner
    perf = {}
    for b in customer_balances(report_date=report_date):
        oid = owner_of.get(b["customer_id"])
        who = names.get(oid, "(unallocated)") if oid else "(unallocated)"
        p = perf.setdefault(who, {"EGP": dict(customers=0, outstanding=0.0, overdue=0.0,
                                              collected=0.0, commission=0.0),
                                  "USD": dict(customers=0, outstanding=0.0, overdue=0.0,
                                              collected=0.0, commission=0.0)})
        ccy = b["currency"]
        p[ccy]["customers"] += 1
        p[ccy]["outstanding"] += b["total"]
        p[ccy]["overdue"] += b["overdue"]
    # collections/commission in period (owner-ledger collections + total commission incl. split)
    for who, byccy in comm.items():
        perf.setdefault(who, {"EGP": dict(customers=0, outstanding=0.0, overdue=0.0, collected=0.0, commission=0.0),
                              "USD": dict(customers=0, outstanding=0.0, overdue=0.0, collected=0.0, commission=0.0)})
        for ccy, cc in byccy.items():
            perf[who][ccy]["collected"] += cc["owner"]["collected"]
            perf[who][ccy]["commission"] += cc["total_commission"]
    # recovery rate = collected / (collected + current overdue)
    for who, byccy in perf.items():
        for ccy, p in byccy.items():
            denom = p["collected"] + p["overdue"]
            p["recovery_pct"] = (p["collected"] / denom * 100) if denom else None
    return perf


# ==================== Branding (white-label) & month helpers ====================
DEFAULT_PRODUCT = "Collecta"
DEFAULT_ORG = "Scientific Gate"
VERSION = "1.0"


def get_brand():
    from models import get_setting
    return dict(product=get_setting("product_name", DEFAULT_PRODUCT) or DEFAULT_PRODUCT,
                org=get_setting("org_name", DEFAULT_ORG) or DEFAULT_ORG)


def month_bounds(month_str=None):
    """Return (first_day, last_day) for 'YYYY-MM' (defaults to current month)."""
    import calendar
    today = date.today()
    if month_str:
        try:
            y, m = [int(x) for x in month_str.split("-")[:2]]
        except (ValueError, AttributeError):
            y, m = today.year, today.month
    else:
        y, m = today.year, today.month
    last = calendar.monthrange(y, m)[1]
    return date(y, m, 1), date(y, m, last)


def commission_statement_rows(date_from=None, date_to=None, controller=None):
    """Flat rows for a month-end commission statement CSV export."""
    data = commission_report(date_from, date_to, controller=controller)
    rows = [["Controller", "Currency", "Role", "Ageing Bucket", "Collected",
             "Rate %", "Owner Share %", "Commission"]]
    for who, byccy in sorted(data["report"].items()):
        for ccy, cc in byccy.items():
            for role in ("owner", "collector"):
                blk = cc[role]
                if not blk["collected"]:
                    continue
                for b in data["order"]:
                    r = blk["buckets"][b]
                    if r["collected"]:
                        rows.append([who, ccy, role, b, f"{r['collected']:.2f}",
                                     f"{r['rate']:.2f}",
                                     (f"{data['splits'][b]:.0f}" if role == "owner" else ""),
                                     f"{r['commission']:.2f}"])
                rows.append([who, ccy, role.upper() + " SUBTOTAL", "",
                             f"{blk['collected']:.2f}", "", "", f"{blk['commission']:.2f}"])
            rows.append([who, ccy, "TOTAL COMMISSION", "", "", "", "",
                         f"{cc['total_commission']:.2f}"])
    return rows


# ==================== Legal sub-ledger & doubtful-debt provision ====================
# Uncollected accounts can be transferred to a separate LEGAL sub-ledger for review
# with the legal team. Legal accounts drop out of routine chasing (calls/reminders)
# and carry a doubtful-debt provision (a % of the outstanding deemed unrecoverable).

LEGAL_STAGES = ["Referred to legal", "Demand letter issued", "Litigation filed",
                "Judgment obtained", "Enforcement", "Settlement agreed", "Written off"]


def legal_provision_default():
    from models import get_setting
    try:
        return float(get_setting("legal_provision_default", "100"))
    except (TypeError, ValueError):
        return 100.0


def transfer_to_legal(cid, reason, stage, provision_pct, user):
    from models import db, Customer
    c = db.session.get(Customer, cid)
    if not c:
        return None
    c.legal_status = "legal"
    c.legal_date = date.today()
    c.legal_reason = reason
    c.legal_stage = stage or "Referred to legal"
    c.provision_pct = provision_pct if provision_pct is not None else legal_provision_default()
    db.session.commit()
    add_note(cid, user, f"Transferred to LEGAL sub-ledger — stage: {c.legal_stage}, "
                        f"provision {float(c.provision_pct):.0f}%. {reason or ''}".strip(),
             kind="legal")
    return c


def update_legal(cid, stage, provision_pct, user):
    from models import db, Customer
    c = db.session.get(Customer, cid)
    if not c or c.legal_status != "legal":
        return None
    if stage:
        c.legal_stage = stage
    if provision_pct is not None:
        c.provision_pct = provision_pct
    db.session.commit()
    add_note(cid, user, f"Legal case updated — stage: {c.legal_stage}, "
                        f"provision {float(c.provision_pct or 0):.0f}%.", kind="legal")
    return c


def return_from_legal(cid, user):
    from models import db, Customer
    c = db.session.get(Customer, cid)
    if not c:
        return None
    c.legal_status = "active"
    db.session.commit()
    add_note(cid, user, "Returned from legal sub-ledger to active collections.", kind="legal")
    return c


def _empty_legal_tot():
    return dict(n=0, gross=0.0, overdue=0.0, provision=0.0, net=0.0)


def legal_ledger(report_date=None):
    """Accounts in the legal sub-ledger with doubtful-debt provision. Per currency."""
    from models import Customer
    legal = {c.id: c for c in Customer.query.filter_by(legal_status="legal").all()}
    default_pct = legal_provision_default()
    rows = []
    totals = {"EGP": _empty_legal_tot(), "USD": _empty_legal_tot()}
    for b in customer_balances(report_date=report_date):
        if b["customer_id"] not in legal:
            continue
        c = legal[b["customer_id"]]
        pct = float(c.provision_pct) if c.provision_pct is not None else default_pct
        provision = b["total"] * pct / 100.0
        ccy = b["currency"]
        rows.append(dict(cust=c, currency=ccy, total=b["total"], overdue=b["overdue"],
                         oldest=b["oldest"], pct=pct, provision=provision,
                         net=b["total"] - provision,
                         stage=c.legal_stage, legal_date=c.legal_date, reason=c.legal_reason))
        t = totals[ccy]
        t["n"] += 1
        t["gross"] += b["total"]
        t["overdue"] += b["overdue"]
        t["provision"] += provision
        t["net"] += b["total"] - provision
    rows.sort(key=lambda x: x["total"], reverse=True)
    return dict(rows=rows, totals=totals)


def legal_summary(report_date=None):
    return legal_ledger(report_date=report_date)["totals"]


def legal_candidates(report_date=None, min_days=180):
    """Heavily overdue accounts not yet in legal — suggested for transfer."""
    from models import Customer
    active = {c.id for c in Customer.query.filter(Customer.legal_status != "legal").all()}
    out = []
    for b in customer_balances(report_date=report_date):
        if b["customer_id"] in active and b["overdue"] > 0 and b["oldest"] >= min_days:
            out.append(b)
    out.sort(key=lambda x: -x["overdue"])
    return out


def next_customer_ref(currency, reserved=None):
    """Next unused customer reference for a currency, e.g. EGP049 / USD015.
    Uses (highest existing number + 1); `reserved` avoids clashes within a batch."""
    import re as _re
    from models import Customer
    prefix = (currency or "EGP").upper()
    reserved = {r.upper() for r in (reserved or set())}
    taken = set(reserved)
    nums = []
    for c in Customer.query.all():
        r = (c.cust_ref or "").upper()
        if r:
            taken.add(r)
        m = _re.match(rf"^{_re.escape(prefix)}0*(\d+)$", r)
        if m and (c.currency or "").upper() == prefix:
            nums.append(int(m.group(1)))
    n = (max(nums) + 1) if nums else 1
    while f"{prefix}{n:03d}" in taken:
        n += 1
    return f"{prefix}{n:03d}"


# ---------------- Organisation logo (white-label branding asset) ----------------
def set_org_logo(data, mime):
    from models import db, BrandAsset
    a = db.session.get(BrandAsset, "org_logo")
    if not a:
        a = BrandAsset(key="org_logo"); db.session.add(a)
    a.mime = mime or "image/png"; a.data = data
    db.session.commit()


def get_org_logo():
    from models import db, BrandAsset
    a = db.session.get(BrandAsset, "org_logo")
    return (a.data, a.mime) if (a and a.data) else None


def has_org_logo():
    from models import db, BrandAsset
    try:
        a = db.session.get(BrandAsset, "org_logo")
        return bool(a and a.data)
    except Exception:
        return False


def clear_org_logo():
    from models import db, BrandAsset
    a = db.session.get(BrandAsset, "org_logo")
    if a:
        db.session.delete(a); db.session.commit()
