"""Integrated operating manual content for Collecta.

Each section is self-contained: a title, the menu path, the live route it maps to
(so Help can jump straight into that function), a summary, step-by-step
instructions, and tips. The /help page renders a searchable contents sheet from
this structure.
"""

# Each section: id, cat, title, path (menu breadcrumb), route (endpoint or None),
# args (for url_for), summary, steps[], tips[], keywords[]
MANUAL = [
    # ---------------- Getting started ----------------
    dict(id="setup", cat="Getting Started", title="First-time setup",
         path="(opens automatically on first launch)", route=None, args={},
         summary="The very first time Collecta runs, it shows a setup screen to create "
                 "your administrator account and load the opening debtor ledger.",
         steps=["Launch the app (double-click the Windows launcher, or open the server URL).",
                "On the setup screen choose an admin username and password.",
                "Set the USD to EGP rate (you can change it later).",
                "Leave 'Load the base debtor ledger' ticked and click Complete setup.",
                "Sign in with the admin account you just created."],
         tips=["Change the admin password after first sign-in.",
               "The opening ledger loads to EGP 10,538,790 and USD 274,629."],
         keywords=["setup", "install", "first run", "admin", "start"]),
    dict(id="login", cat="Getting Started", title="Signing in, users and roles",
         path="Login screen / Admin > Users", route="users", args={},
         summary="Everyone signs in with their own username. Admins manage the system; "
                 "standard users are the credit controllers.",
         steps=["Enter your username and password on the login screen.",
                "Admins can add colleagues under Admin > Users & Controllers.",
                "Give each person a role: 'admin' (full access) or 'user' (controller)."],
         tips=["Each controller should sign in as themselves so collections and calls are "
               "attributed correctly."],
         keywords=["login", "sign in", "users", "password", "role", "admin", "controller"]),
    dict(id="navigation", cat="Getting Started", title="Finding your way around the menus",
         path="Top navigation bar", route="dashboard", args={},
         summary="The top menu is grouped by function: Ledger, Customers, Collections, "
                 "Allocation, Reports and Admin, plus a quick search box.",
         steps=["Dashboard - the headline numbers.",
                "Ledger - the debtor ledger, ageing and adding instalments.",
                "Customers - the customer list, search, new customers and credit limits.",
                "Collections - recording receipts, reminder letters and the call scheduler.",
                "Allocation - assigning customers to controllers and setting targets.",
                "Reports - all reporting including commission and performance.",
                "Admin - users, ledger allocation and settings (admins only)."],
         tips=["The search box (top right) jumps to any customer by account number or name.",
               "EGP and USD are always shown separately and never added together."],
         keywords=["menu", "navigate", "navigation", "layout"]),

    # ---------------- Dashboard ----------------
    dict(id="dashboard", cat="Dashboard", title="The dashboard",
         path="Dashboard", route="dashboard", args={},
         summary="A one-glance view of the book: outstanding and overdue per currency, an "
                 "ageing summary, top-10 customers, and a combined EGP-equivalent memo.",
         steps=["Open Dashboard from the menu.",
                "Read EGP and USD blocks separately - each shows total outstanding, overdue, "
                "overdue %, and customer counts.",
                "Use the 'As at' date box to re-age the whole book to any date.",
                "The EGP-equivalent card converts USD at your FX rate for a single headline "
                "number (a memo only)."],
         tips=["Top-10 lists link straight to each customer's page."],
         keywords=["dashboard", "kpi", "overview", "overdue", "summary", "egp equivalent"]),

    # ---------------- Ledger ----------------
    dict(id="ledger", cat="Ledger", title="The debtors ledger",
         path="Ledger > Debtors Ledger", route="ledger", args={},
         summary="Every instalment with its live net balance, ageing bucket and status.",
         steps=["Open Ledger > Debtors Ledger.",
                "Filter by currency and by status (overdue, current, settled, no date).",
                "Each row shows original amount, received, net outstanding, due date, days "
                "overdue, bucket and security."],
         tips=["Net outstanding updates automatically as collections are recorded.",
               "Click a customer reference to open that customer's page."],
         keywords=["ledger", "instalments", "balance", "net", "outstanding"]),
    dict(id="ageing", cat="Ledger", title="Aged debtors analysis",
         path="Ledger > Aged Analysis (EGP / USD)", route="aged", args={"ccy": "EGP"},
         summary="The aged trial balance: customers down the rows, ageing buckets across the "
                 "columns, with a total line - one schedule per currency.",
         steps=["Open Ledger > Aged Analysis - EGP (or USD).",
                "Read each customer's balance split across Current, 1-30, 31-60, 61-90, "
                "91-180, 181-365 and 365+ days.",
                "The bottom line totals every bucket for the whole ledger."],
         tips=["The overdue tail (91+ days) is shaded so problem debt stands out."],
         keywords=["ageing", "aged", "buckets", "analysis", "trial balance"]),
    dict(id="new_instalment", cat="Ledger", title="Adding a new instalment",
         path="Ledger > + Add Instalment", route="new_instalment", args={},
         summary="Record a new instalment for an existing customer, or create a brand-new "
                 "customer on the fly.",
         steps=["Open Ledger > + Add Instalment.",
                "Enter the Instalment ID, Customer Ref, amount, due date, security and a "
                "reference (cheque/invoice/contract number).",
                "For a new customer, type a new Customer Ref plus their name and currency - "
                "the customer is created automatically and allocated to its owner.",
                "Save - it appears immediately in the ledger and ageing."],
         tips=["Give new customers a new reference such as EGP049 or USD015."],
         keywords=["new instalment", "add", "instalment", "due date", "reference"]),
    dict(id="import", cat="Ledger", title="Bulk import (instalments & payments)",
         path="Ledger > Bulk Import", route="import_home", args={},
         summary="Bring in many instalments or receipts at once from a spreadsheet: download a "
                 "template, paste your rows, upload, review, confirm, and get an audit report.",
         steps=["Open Ledger > Bulk Import.",
                "Download the Instalments (or Payments) template and open it in Excel.",
                "Paste your rows under the headers in the same order (see the Instructions tab), "
                "then delete the grey example rows and save.",
                "Upload the file and review: accepted rows, rejected rows with reasons, and the "
                "projected balance change. Nothing is saved yet.",
                "Click Confirm to save, then download the audit report showing accepted rows, "
                "rejected rows, and each customer's old and new balance."],
         tips=["Leave Customer Ref blank for a new customer and Collecta assigns the next "
               "unused code automatically; to add several instalments for the same new "
               "customer, give them the same Customer Name (or the same ref).",
               "Enter only activity after the opening date (29 Jul 2026) so nothing is "
               "double-counted; for a full catch-up import instalments first, then payments."],
         keywords=["import", "bulk", "upload", "excel", "spreadsheet", "template", "csv",
                   "mass", "batch", "audit", "paste"]),
    dict(id="legal", cat="Ledger", title="Legal sub-ledger & doubtful-debt provision",
         path="Ledger > Legal Sub-ledger", route="legal_ledger", args={},
         summary="Uncollected accounts can be transferred to a separate legal sub-ledger for "
                 "review with the legal team. Legal accounts are excluded from routine "
                 "chasing and carry a doubtful-debt provision.",
         steps=["Open Ledger > Legal Sub-ledger.",
                "Review the 'Candidates for legal transfer' list (long-overdue active "
                "accounts) - adjust the day threshold if needed.",
                "To transfer, choose a stage (referred, demand letter, litigation, etc.), a "
                "provision %, add a reason, and click Transfer. You can also do this from the "
                "customer's own page.",
                "The legal ledger shows gross legal debt, overdue, the doubtful-debt "
                "provision and net-of-provision, per currency.",
                "Update the stage/provision as a case progresses, or Return an account to "
                "active collections.",
                "Set the default provision % in Admin > Settings > Commission."],
         tips=["Transferring an account stops calls and reminder letters for it - it is now "
               "handled by the legal team.",
               "Provision is the allowance against debt judged unlikely to be collected; net "
               "= outstanding minus provision.",
               "Only admins/managers can transfer accounts; everyone can review the ledger."],
         keywords=["legal", "sub-ledger", "provision", "doubtful debt", "write off",
                   "litigation", "transfer", "uncollectible", "allowance"]),

    # ---------------- Customers ----------------
    dict(id="customers", cat="Customers", title="Customer list and search",
         path="Customers > All Customers / Search", route="customers", args={},
         summary="Browse or search every customer by account number, name or reference.",
         steps=["Open Customers > All Customers / Search (or use the top search box).",
                "Type an account number, a name, or a reference and press Search.",
                "Click a customer to open their full page."],
         tips=["Over-limit customers are highlighted in red."],
         keywords=["customers", "search", "find", "account number", "name"]),
    dict(id="customer_new", cat="Customers", title="Setting up a new customer",
         path="Customers > + Add Customer", route="customer_new", args={},
         summary="A dedicated screen to create a customer with all their details.",
         steps=["Open Customers > + Add Customer.",
                "Pick the currency; a suggested reference is filled in for you.",
                "Enter account number, name, contact person, phone, email, credit limit.",
                "Choose the ledger owner (controller), or leave blank to use the currency "
                "default.",
                "Save."],
         tips=["Phone and email are used by reminder letters and emails."],
         keywords=["new customer", "setup", "add customer", "contact", "credit limit"]),
    dict(id="customer_detail", cat="Customers", title="Customer page: contacts, limit, owner, history",
         path="Customers > (open a customer)", route=None, args={},
         summary="One page per customer: contact details, credit limit, ledger owner, their "
                 "instalments, payments, and a full contact-history/comments trail.",
         steps=["Open any customer from the list, search, or a report link.",
                "Edit contact person, phone, email, address, credit limit and ledger owner, "
                "then Save.",
                "Add a comment in 'Contact history & comments' - every call outcome is logged "
                "here automatically too.",
                "Use 'Reminder letter' to generate a chase letter for this customer."],
         tips=["The contact history is your audit trail of who was contacted and when."],
         keywords=["customer", "contact", "phone", "email", "notes", "comments", "history",
                   "credit limit", "owner"]),
    dict(id="credit_limits", cat="Customers", title="Credit limits",
         path="Customers > Credit Limits", route="credit_limits", args={},
         summary="See every customer's outstanding against their credit limit, with "
                 "over-limit accounts flagged.",
         steps=["Open Customers > Credit Limits.",
                "Review outstanding, overdue, limit and headroom per customer.",
                "Set or change a limit on the customer's own page."],
         tips=["Customers over their limit are flagged so you can put them on stop."],
         keywords=["credit limit", "over limit", "headroom", "exposure"]),

    dict(id="parts_accounts", cat="Customers", title="Machine vs Parts & Accessories accounts",
         path="Ledger > + New Parts Sale", route="parts_new", args={},
         summary="Every customer now has two separate credit accounts: the long-term Machine "
                 "instalment plan, and a short-term Parts & Accessories account for spare parts sold "
                 "on 30/60-day credit. The two are aged and reported separately and never mixed, but "
                 "the customer page also shows a combined total. Each is kept separate by currency.",
         steps=["To record a parts sale, open Ledger > + New Parts Sale.",
                "Pick the customer, enter the amount and currency, and choose Net 30, Net 60 or a custom due date.",
                "Parts sales are a single payment by the due date and need no guarantee.",
                "On the customer page, the Machine account and the Parts & Accessories account are shown "
                "separately, each with its own outstanding, overdue and credit limit, plus a combined total.",
                "The dashboard and ledger can be viewed Machine-only, Parts-only, or combined.",
                "Parts can also be loaded in bulk: use the Instalments import template and put PARTS in the "
                "Account Type column (blank or MACHINE for machine instalments)."],
         tips=["Parts have their own separate credit limit, independent of the machine limit.",
               "Existing instalments are all treated as Machine automatically — nothing changes for them.",
               "EGP and USD are always kept separate, and Machine and Parts are never summed in ageing."],
         keywords=["parts", "accessories", "spare parts", "net 30", "net 60", "sub-account",
                   "machine", "two accounts", "parts credit limit"]),

    dict(id="machine_deal", cat="Ledger", title="Adding a new machine deal (contract-backed)",
         path="Ledger > + New Machine Deal", route="machine_new", args={},
         summary="Books a new machine instalment plan against a signed contract. The contract is the "
                 "authorisation, so no separate approval step is needed — but a contract reference is "
                 "required and stored on every instalment for the audit trail.",
         steps=["Open Ledger > + New Machine Deal.",
                "Pick the customer, currency, total contract value and number of instalments.",
                "For USD deals, record the original contract FX rate so any future conversion can measure a gain or loss.",
                "Enter the signed-contract reference (required) and submit — the value is split evenly across the instalments."],
         tips=["The contract is the authorisation; the reference is recorded on every instalment.",
               "EGP and USD deals stay in their own currency — nothing is converted here."],
         keywords=["machine", "new deal", "contract", "instalment plan", "add machine"]),

    dict(id="reschedule", cat="Ledger", title="Rescheduling a customer (with approval)",
         path="Customer page > Reschedule", route="reschedule_request", args={"cid": 0},
         summary="Re-spreads a customer's outstanding instalments over new dates/terms. The request is held "
                 "for CFO or MD approval and nothing changes on the ledger until it is approved. It should be "
                 "backed by a short written agreement, whose reference is recorded.",
         steps=["On the customer page, click Reschedule.",
                "Tick the outstanding instalments to reschedule (same currency only).",
                "Set the new number of instalments, first due date and frequency, and the agreement reference.",
                "Submit — the request appears in Approvals for the CFO/MD.",
                "On approval, the old instalments are closed as 'rescheduled' and the new schedule is created for the same total."],
         tips=["The outstanding value is preserved — only the dates/number of instalments change.",
               "You cannot approve your own request (separation of duties)."],
         keywords=["reschedule", "re-spread", "new terms", "approval", "cfo", "md"]),

    dict(id="currency_conversion", cat="Ledger", title="Currency conversion USD→EGP (with FX-loss flag)",
         path="Customer page > Convert USD→EGP", route="convert_request", args={"cid": 0},
         summary="Converts the remaining USD outstanding to EGP at an agreed rate. The system compares the "
                 "agreed rate to each instalment's original contract rate and flags any exchange gain or loss, "
                 "showing the difference and the total deal value to both the controller and the authorising "
                 "manager. Held for CFO/MD approval; backed by a short written agreement.",
         steps=["On the customer page, click Convert USD→EGP.",
                "Enter the agreed conversion rate and click Preview FX impact — the gain or loss is shown.",
                "If an instalment has no stored original rate (legacy), enter the rate that applied when the contract was created.",
                "Choose Convert only (one EGP instalment) or Convert & reschedule (a new EGP schedule).",
                "Record the written-agreement reference and submit for CFO/MD approval.",
                "On approval, the USD instalment is closed as 'converted' (not a cash receipt, so USD outstanding drops "
                "without overstating collections) and a linked EGP instalment is created."],
         tips=["A conversion is never treated as a payment — collections and commission are not overstated.",
               "Every conversion is listed in Reports > Currency Conversions with the rates and FX gain/loss.",
               "Only the remaining outstanding is ever converted; settled history is untouched."],
         keywords=["currency", "conversion", "usd", "egp", "fx", "exchange loss", "rate", "convert"]),

    # ---------------- Collections & chasing ----------------
    dict(id="collections", cat="Collections", title="Recording a collection",
         path="Collections > Record Collection", route="collections", args={},
         summary="Log each receipt against the instalment it pays, with a transaction "
                 "reference and payment method.",
         steps=["Open Collections > Record Collection.",
                "Pick the Instalment ID being paid, enter the amount, transaction reference "
                "and method (cash, cheque, bank transfer, card, other).",
                "Save - the ledger, ageing and dashboard update immediately."],
         tips=["Record collections under your own login so commission is attributed to you.",
               "Collecta snapshots the ageing bucket at the moment of collection - this "
               "drives the weighted commission."],
         keywords=["collection", "payment", "receipt", "transaction", "method", "record"]),
    dict(id="reminders", cat="Collections", title="Reminder letters (4 levels)",
         path="Collections > Reminder Letters", route="reminders", args={},
         summary="Escalating chase letters, from a gentle reminder (Level 1) to a final "
                 "demand (Level 4), chosen automatically by how overdue the account is.",
         steps=["Open Collections > Reminder Letters to see who is due chasing.",
                "Click a customer to open the letter at the suggested level.",
                "Print it, or email it straight to the customer (if email is configured).",
                "Use 'Mark as sent' to log it against the customer's history."],
         tips=["Levels: L1 1-30 days, L2 31-60, L3 61-90, L4 over 90 days (final demand)."],
         keywords=["reminder", "letter", "chase", "dunning", "final demand", "email"]),
    dict(id="calls", cat="Collections", title="The call scheduler",
         path="Collections > Call Scheduler", route="calls", args={},
         summary="Builds a prioritised daily call list from aged debt, tuned by your "
                 "collection strategy, and records call outcomes with automatic follow-ups.",
         steps=["Open Collections > Call Scheduler.",
                "Click 'Generate plan' - choose start date, working days, calls per day, and "
                "optionally a single controller's ledger.",
                "Work the day's list top-down (it is ranked by priority score).",
                "For each call click 'Log', choose the outcome (promise to pay, no answer, "
                "dispute, refused, paid) and add notes.",
                "Collecta schedules the right follow-up automatically."],
         tips=["Use 'My calls' to see only the customers you own.",
               "Priority combines amount, age, security and escalation level - set the "
               "strategy in Admin > Settings."],
         keywords=["call", "scheduler", "phone", "priority", "follow up", "promise to pay"]),

    # ---------------- Allocation ----------------
    dict(id="allocations", cat="Allocation", title="Allocating ledgers to controllers",
         path="Allocation > Ledger Allocation", route="allocations", args={},
         summary="A manager allocates ranges of customers to controllers, who become the "
                 "ledger owner. New customers are included automatically.",
         steps=["Open Allocation > Ledger Allocation.",
                "Allocate a range: choose a controller and a Customer Ref range (e.g. "
                "EGP001 to EGP024) or an account-number range.",
                "Set a default owner per currency so new customers are allocated on creation.",
                "Review the allocation summary showing each owner's ledger size."],
         tips=["You can also set or change an owner on any customer's own page.",
               "Performance and commission follow the ledger owner."],
         keywords=["allocation", "allocate", "ledger owner", "assign", "range"]),
    dict(id="targets", cat="Allocation", title="Collection targets",
         path="Allocation > Collection Targets", route="commission_targets", args={},
         summary="Optional targets per controller, currency and ageing bucket, used to show "
                 "achievement in the commission report.",
         steps=["Open Allocation > Collection Targets.",
                "Choose a controller and currency, enter a target for each bucket, and Save."],
         tips=["Targets are optional - the commission report works without them."],
         keywords=["target", "goal", "collection target", "achievement"]),

    # ---------------- Reports ----------------
    dict(id="reports", cat="Reports", title="Report writer",
         path="Reports > Report Writer", route="reports", args={},
         summary="Build a filtered aged-debtors report by currency, bucket, status, security "
                 "or amount, and export it to CSV.",
         steps=["Open Reports > Report Writer.",
                "Choose your filters and click Run report.",
                "Click 'Export CSV' to download the result."],
         tips=["Currencies are totalled separately in every report."],
         keywords=["report", "report writer", "filter", "export", "csv", "aged"]),
    dict(id="collections_report", cat="Reports", title="Monthly collections",
         path="Reports > Monthly Collections", route="collections_report", args={},
         summary="Collections broken down by month and payment method, per currency.",
         steps=["Open Reports > Monthly Collections.",
                "Read each month's totals by method (cash, cheque, bank transfer, card, other)."],
         tips=["Useful for reconciling receipts to the bank by method."],
         keywords=["monthly", "collections", "method", "cash", "cheque", "bank"]),
    dict(id="commission", cat="Reports", title="Commission by controller",
         path="Reports > Commission by Controller", route="commission_report", args={},
         summary="Each controller's commission, weighted by ageing bucket and split between "
                 "the ledger owner and whoever recorded the collection. Exports a month-end "
                 "statement.",
         steps=["Open Reports > Commission by Controller.",
                "Pick the month (or a controller) and click Run month.",
                "Read each controller's commission as ledger owner and as collector, with a "
                "total per currency.",
                "Click 'Download month-end statement (CSV)' to hand to payroll.",
                "Set commission rates and the owner/collector split per bucket in "
                "Admin > Settings."],
         tips=["If a controller collects from their own ledger, they earn the full "
               "commission (owner share + collector share)."],
         keywords=["commission", "statement", "split", "owner", "collector", "payroll",
                   "month end"]),
    dict(id="performance", cat="Reports", title="Controller performance",
         path="Reports > Controller Performance", route="performance_report", args={},
         summary="Per ledger owner: ledger size, collections in the period, recovery rate "
                 "and commission - separately for EGP and USD.",
         steps=["Open Reports > Controller Performance.",
                "Choose a date range and Run.",
                "Compare controllers on outstanding, overdue, collected, recovery % and "
                "commission."],
         tips=["Recovery % = collected divided by (collected + current overdue)."],
         keywords=["performance", "recovery", "controller", "kpi"]),

    # ---------------- Admin ----------------
    dict(id="users_admin", cat="Admin", title="Users and controllers",
         path="Admin > Users & Controllers", route="users", args={},
         summary="Add, remove and reset users; set who is an admin and who is a controller.",
         steps=["Open Admin > Users & Controllers.",
                "Add a user with a username, name, password and role.",
                "Reset a password or delete a user from the list."],
         tips=["Controllers must be users so they can own ledgers and be paid commission."],
         keywords=["users", "controllers", "add user", "password", "role"]),
    dict(id="settings", cat="Admin", title="Settings: FX, email, commission, strategy, branding, database",
         path="Admin > Settings", route="settings", args={},
         summary="All configuration in one place.",
         steps=["FX: set the USD to EGP rate for the EGP-equivalent memo.",
                "Email (SMTP): enter your mail server so reminders can be emailed.",
                "Commission: set the rate and the owner/collector split for each ageing bucket.",
                "Collection strategy: choose how the call scheduler prioritises (balanced, "
                "maximise cash, reduce oldest, risk-based) and the calls-per-day.",
                "Branding: set the product name and organisation name (white-label).",
                "Database: paste a server/Neon connection string to switch to shared multi-user "
                "mode, then restart."],
         tips=["The organisation name appears on letters, emails and statements."],
         keywords=["settings", "fx", "email", "smtp", "commission", "strategy", "branding",
                   "database", "config"]),

    # ---------------- Concepts ----------------
    dict(id="concepts", cat="Reference", title="Key concepts: ageing, currencies, ownership",
         path="Reference", route=None, args={},
         summary="The rules Collecta follows throughout.",
         steps=["Overdue means strictly past the due date - an instalment due today is "
                "'Current', not overdue.",
                "EGP and USD are always reported separately and never added together.",
                "The ledger owner is the controller a customer is allocated to; performance "
                "and commission follow the owner.",
                "Commission is weighted by ageing bucket (older debt earns more) and split "
                "between owner and collector."],
         tips=["A combined EGP-equivalent figure is shown only as a memo, using the FX rate."],
         keywords=["concepts", "ageing", "overdue", "currency", "ownership", "rules"]),

    # ---------------- Governance (Phase 3) ----------------
    dict(id="roles", cat="Governance", title="Roles & what each department can do",
         path="Admin > Users & Roles", route="users", args={},
         summary="Every user is given a role, and the role decides which functions they can use. "
                 "Menus always show every option to everyone; anything a user isn't authorised for "
                 "appears dimmed (greyed) with a small padlock, so people can see what the system does "
                 "without being able to act on it. The block is also enforced on the server.",
         steps=["Roles: Administrator (full access, cannot be locked out), CFO, Finance Manager, "
                "Managing Director (view & report only, no data entry), Credit Control, "
                "Account Manager (reconciliation — read & export only, allocates cash and reconciles "
                "the debtors ledger in the general accounts; deliberately cannot post or edit in Collecta), "
                "Sales, Maintenance.",
                "Hover a menu heading to see its items; dimmed items with a padlock aren't available to you.",
                "An administrator sets who can do what on Admin > Access Control.",
                "Add an email for each user so they receive approval-request notifications."],
         tips=["Existing 'user' accounts automatically behave as Credit Control after the upgrade.",
               "Give each person their own login so collections, calls and approvals are attributed correctly."],
         keywords=["roles", "permissions", "department", "sales", "maintenance", "md", "cfo",
                   "finance manager", "dimmed", "authorise", "access"]),
    dict(id="access_control", cat="Governance", title="Access Control (the permission matrix)",
         path="Admin > Access Control", route="access_control", args={},
         summary="The administrator's control panel for the whole governance model: the role/function "
                 "matrix, the subscription plan, and who may give digital authorisations.",
         steps=["Tick a box to let a role use a function; untick to remove it. The Administrator column "
                "is always on - that is the built-in override so an admin can never be locked out.",
                "Set the Subscription plan (Core / Professional / Enterprise). Premium functions outside "
                "the current plan are dimmed for everyone except the administrator.",
                "Choose which roles may approve digital authorisations (default: Finance Manager, CFO, "
                "Managing Director).",
                "Click Save access control. Every change is written to the Audit Log."],
         tips=["This screen means you adjust permissions and plan without any change to the program code.",
               "If you ever lock yourself out of a function, sign in as the administrator and re-enable it here."],
         keywords=["access control", "matrix", "permissions", "subscription", "plan", "approver",
                   "back door", "override", "admin"]),
    dict(id="subscription", cat="Governance", title="Subscription tiers",
         path="Admin > Access Control", route="access_control", args={},
         summary="Collecta is licensed in three tiers. Higher tiers unlock more advanced functions; "
                 "anything above the current tier is shown but dimmed.",
         steps=["Core: ledger, collections, reminders, customers, credit limits, dashboard, standard reports, "
                "guarantees register.",
                "Professional: adds the roles/permissions matrix, reschedule-with-approval, audit log, "
                "bulk import, and multi-format branded exports.",
                "Enterprise: adds the digital-approval workflow with email alerts, sales/maintenance "
                "clearance gates, guarantee coverage checks and the MD view-only role."],
         tips=["Your organisation is set to Enterprise, so all functions are available."],
         keywords=["subscription", "tier", "plan", "core", "professional", "enterprise", "licence", "billing"]),
    dict(id="approvals", cat="Governance", title="Digital authorisations (Approvals)",
         path="Approvals", route="approvals_queue", args={},
         summary="Certain sensitive actions require a second, authorised person to approve them before they "
                 "take effect - a digital sign-off that sits in front of the audit record.",
         steps=["When a controller requests something that needs sign-off (e.g. rescheduling an instalment), "
                "it is held as Pending and does not take effect yet.",
                "Authorised approvers (by default FM, CFO, MD) get an email and see it in the Approvals queue.",
                "The approver signs in and clicks Approve or Reject. You can never approve your own request.",
                "The decision, and the action it authorises, are recorded in the Audit Log."],
         tips=["The reschedule and sales/maintenance functions that raise these requests arrive in the next "
               "two update stages; this screen is the queue they feed into."],
         keywords=["approval", "authorise", "digital", "sign off", "reschedule", "cfo", "fm", "md",
                   "separation of duties", "pending"]),
    dict(id="audit", cat="Governance", title="Audit log",
         path="Admin > Audit Log", route="audit_log_view", args={},
         summary="A permanent, read-only record of sensitive actions - who did what, when, and the "
                 "before/after detail.",
         steps=["Open Admin > Audit Log to review recent activity.",
                "Entries include permission and plan changes, user changes, and approval decisions "
                "(with reschedule and override actions added in the next stages).",
                "The log cannot be edited from within the application."],
         tips=["This underpins the forensic standard of the system - nothing sensitive changes silently."],
         keywords=["audit", "log", "trail", "history", "forensic", "who", "changes"]),
]

CATEGORIES = ["Getting Started", "Dashboard", "Ledger", "Customers", "Collections",
              "Allocation", "Reports", "Governance", "Admin", "Reference"]
