import os, sqlite3, secrets, json, time
import requests
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(APP_DIR, "data", "app.db"))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1")

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT UNIQUE NOT NULL,
          username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL,
          phone TEXT DEFAULT '', password_hash TEXT NOT NULL,
          is_admin INTEGER DEFAULT 0, is_banned INTEGER DEFAULT 0,
          balance REAL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS plans(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
          duration_hours INTEGER NOT NULL, price REAL NOT NULL,
          active INTEGER DEFAULT 1, is_trial INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS subscriptions(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          plan_id INTEGER NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(plan_id) REFERENCES plans(id)
        );
        CREATE TABLE IF NOT EXISTS deposits(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          amount REAL NOT NULL, method TEXT NOT NULL, reference TEXT DEFAULT '',
          status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
          reviewed_at TEXT DEFAULT '', FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS payment_methods(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
          instructions TEXT NOT NULL, active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS deployments(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          subscription_id INTEGER, provider TEXT NOT NULL, repo TEXT DEFAULT '',
          status TEXT NOT NULL DEFAULT 'pending', logs TEXT DEFAULT '',
          railway_project_id TEXT DEFAULT '', railway_service_id TEXT DEFAULT '',
          railway_environment_id TEXT DEFAULT '', railway_deployment_id TEXT DEFAULT '',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id),
          FOREIGN KEY(subscription_id) REFERENCES subscriptions(id)
        );
        CREATE TABLE IF NOT EXISTS notifications(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          title TEXT NOT NULL, message TEXT NOT NULL, kind TEXT DEFAULT 'info',
          created_at TEXT NOT NULL, read_at TEXT DEFAULT '',
          FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS support_tickets(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          subject TEXT NOT NULL, message TEXT NOT NULL, status TEXT DEFAULT 'open',
          reply TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS audit_logs(
          id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER,
          action TEXT NOT NULL, detail TEXT DEFAULT '', created_at TEXT NOT NULL
        );
        """)
        # Backward-compatible migrations for databases created by the earlier ZIP.
        for column, definition in [
            ("warning_sent_at", "TEXT DEFAULT ''"),
        ]:
            try: con.execute(f"ALTER TABLE subscriptions ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError: pass
        for column, definition in [
            ("railway_project_id", "TEXT DEFAULT ''"),
            ("railway_service_id", "TEXT DEFAULT ''"),
            ("railway_environment_id", "TEXT DEFAULT ''"),
            ("railway_deployment_id", "TEXT DEFAULT ''"),
        ]:
            try: con.execute(f"ALTER TABLE deployments ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError: pass
        if con.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0:
            plans = [
              ("Free Trial", 2, 0, 1, 1), ("Day 1", 24, 5, 1, 0),
              ("Day 2", 48, 10, 1, 0), ("Day 3", 72, 15, 1, 0),
              ("Day 5", 120, 25, 1, 0), ("Day 10", 240, 50, 1, 0),
              ("Day 15", 360, 75, 1, 0), ("Day 20", 480, 100, 1, 0),
              ("Day 25", 600, 125, 1, 0)]
            con.executemany("INSERT INTO plans(name,duration_hours,price,active,is_trial) VALUES(?,?,?,?,?)", plans)
        if con.execute("SELECT COUNT(*) FROM payment_methods").fetchone()[0] == 0:
            con.executemany("INSERT INTO payment_methods(name,instructions,active) VALUES(?,?,1)", [
                ("bKash", "অ্যাডমিনের দেওয়া bKash নম্বরে Send Money করে TrxID দিন।"),
                ("Nagad", "অ্যাডমিনের দেওয়া Nagad নম্বরে Send Money করে TrxID দিন।"),
                ("USDT", "অ্যাডমিনের দেওয়া wallet address-এ পাঠিয়ে transaction hash দিন।")])

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def audit(actor, action, detail="", con=None):
    values = (actor, action, detail[:1000], now_iso())
    if con is not None:
        con.execute("INSERT INTO audit_logs(actor_id,action,detail,created_at) VALUES(?,?,?,?)", values)
    else:
        with db() as own_con:
            own_con.execute("INSERT INTO audit_logs(actor_id,action,detail,created_at) VALUES(?,?,?,?)", values)

def current_user():
    uid = session.get("user_id")
    if not uid: return None
    with db() as con:
        user = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user or user["is_banned"]:
        session.clear()
        return None
    return user

@app.context_processor
def inject_globals():
    return {"me": current_user(), "year": datetime.now().year}

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("আগে লগইন করুন।", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped

def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or not user["is_admin"]:
            flash("এই পেজটি শুধু অ্যাডমিনের জন্য।", "danger")
            return redirect(url_for("dashboard"))
        return fn(*args, **kwargs)
    return wrapped

@app.route("/")
def index():
    with db() as con:
        plans = con.execute("SELECT * FROM plans WHERE active=1 ORDER BY duration_hours").fetchall()
    return render_template("index.html", plans=plans)

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        email = request.form.get("email","").strip().lower()
        phone = request.form.get("phone","").strip()
        password = request.form.get("password","")
        if len(username) < 3 or len(password) < 10 or "@" not in email:
            flash("সঠিক ইউজারনেম/ইমেইল দিন। পাসওয়ার্ড কমপক্ষে ১০ অক্ষরের হতে হবে।", "danger")
            return render_template("auth.html", mode="register")
        try:
            with db() as con:
                account_id = "CN" + secrets.token_hex(5).upper()
                con.execute("INSERT INTO users(account_id,username,email,phone,password_hash,created_at) VALUES(?,?,?,?,?,?)",
                            (account_id, username, email, phone, generate_password_hash(password), now_iso()))
                uid = con.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
            session["user_id"] = uid
            audit(uid, "register", "Account created")
            return redirect(url_for("dashboard"))
        except sqlite3.IntegrityError:
            flash("এই ইউজারনেম বা ইমেইল আগে থেকেই ব্যবহৃত হয়েছে।", "danger")
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        identity = request.form.get("identity","").strip().lower()
        password = request.form.get("password","")
        with db() as con:
            user = con.execute("SELECT * FROM users WHERE lower(email)=? OR lower(username)=?", (identity, identity)).fetchone()
        if user and check_password_hash(user["password_hash"], password) and not user["is_banned"]:
            session.clear()
            session["user_id"] = user["id"]
            audit(user["id"], "login")
            return redirect(url_for("admin") if user["is_admin"] else url_for("dashboard"))
        flash("লগইন তথ্য সঠিক নয় অথবা অ্যাকাউন্ট নিষ্ক্রিয়।", "danger")
    return render_template("auth.html", mode="login")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    with db() as con:
        plans = con.execute("SELECT * FROM plans WHERE active=1 ORDER BY duration_hours").fetchall()
        subs = con.execute("""SELECT s.*,p.name plan_name FROM subscriptions s JOIN plans p ON p.id=s.plan_id
                              WHERE s.user_id=? ORDER BY s.id DESC LIMIT 8""", (user["id"],)).fetchall()
        bots = con.execute("SELECT * FROM deployments WHERE user_id=? ORDER BY id DESC LIMIT 8", (user["id"],)).fetchall()
        deposits = con.execute("SELECT * FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 5", (user["id"],)).fetchall()
        notifications = con.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 10", (user["id"],)).fetchall()
    return render_template("dashboard.html", user=user, plans=plans, subs=subs, bots=bots, deposits=deposits, notifications=notifications)

@app.route("/plans/<int:plan_id>/buy", methods=["POST"])
@login_required
def buy_plan(plan_id):
    user = current_user()
    with db() as con:
        plan = con.execute("SELECT * FROM plans WHERE id=? AND active=1", (plan_id,)).fetchone()
        fresh = con.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        if not plan:
            flash("প্ল্যানটি এখন সক্রিয় নয়।", "danger")
        elif plan["price"] > fresh["balance"]:
            flash("পর্যাপ্ত ব্যালেন্স নেই। আগে ডিপোজিট করুন।", "warning")
        else:
            starts = datetime.now(timezone.utc)
            ends = starts + timedelta(hours=plan["duration_hours"])
            con.execute("UPDATE users SET balance=balance-? WHERE id=?", (plan["price"], user["id"]))
            con.execute("INSERT INTO subscriptions(user_id,plan_id,starts_at,ends_at,status) VALUES(?,?,?,?,?)",
                        (user["id"], plan_id, starts.isoformat(), ends.isoformat(), "active"))
            new_sub_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            audit(user["id"], "plan_purchase", f"{plan['name']} / {plan['price']}", con=con)
            # If this user has a previously stopped Railway bot, try to redeploy it on the new plan.
            stopped = con.execute("SELECT * FROM deployments WHERE user_id=? AND provider='railway' AND status='stopped' AND railway_service_id<>'' AND railway_environment_id<>'' ORDER BY id DESC", (user["id"],)).fetchall()
            restarted = 0
            for bot in stopped:
                try:
                    new_deployment_id = railway_start(bot["railway_service_id"], bot["railway_environment_id"])
                    if new_deployment_id:
                        con.execute("UPDATE deployments SET subscription_id=?,railway_deployment_id=?,status='running',logs=?,updated_at=? WHERE id=?",
                                    (new_sub_id, new_deployment_id, "✅ নতুন প্ল্যান কেনার পর Railway বট সফলভাবে চালু হয়েছে।", now_iso(), bot["id"]))
                        notify_user(user["id"], "🚀 বট সফলভাবে চালু হয়েছে", f"আপনার হোস্টিং বট #{bot['id']} নতুন প্ল্যানের অধীনে সফলভাবে চালু হয়েছে।", "success", con=con)
                        restarted += 1
                except Exception as exc:
                    con.execute("UPDATE deployments SET logs=?,updated_at=? WHERE id=?", (f"নতুন প্ল্যানে বট চালু করা যায়নি: {str(exc)[:700]}", now_iso(), bot["id"]))
                    notify_user(user["id"], "⚠️ বট চালু করা যায়নি", f"আপনার বট #{bot['id']} পুনরায় চালু করা যায়নি। সাপোর্টে যোগাযোগ করুন।", "danger", con=con)
            flash("প্ল্যান সফলভাবে সক্রিয় হয়েছে।" + (f" {restarted}টি বন্ধ বট পুনরায় চালু হয়েছে।" if restarted else ""), "success")
    return redirect(url_for("dashboard"))

@app.route("/deposit", methods=["GET","POST"])
@login_required
def deposit():
    user = current_user()
    with db() as con:
        methods = con.execute("SELECT * FROM payment_methods WHERE active=1").fetchall()
        if request.method == "POST":
            try: amount = float(request.form.get("amount","0"))
            except ValueError: amount = 0
            method = request.form.get("method","")
            reference = request.form.get("reference","").strip()
            if amount < 10 or amount > 1000000 or not reference or method not in [m["name"] for m in methods]:
                flash("সঠিক পেমেন্ট মেথড, পরিমাণ এবং Transaction ID দিন।", "danger")
            else:
                con.execute("INSERT INTO deposits(user_id,amount,method,reference,status,created_at) VALUES(?,?,?,?,?,?)",
                            (user["id"], amount, method, reference, "pending", now_iso()))
                audit(user["id"], "deposit_request", f"{amount} {method}")
                flash("ডিপোজিট রিকোয়েস্ট জমা হয়েছে। যাচাই শেষে ব্যালেন্স যোগ হবে।", "success")
                return redirect(url_for("dashboard"))
    return render_template("deposit.html", methods=methods)

@app.route("/hosting", methods=["GET","POST"])
@login_required
def hosting():
    user = current_user()
    with db() as con:
        subs = con.execute("""SELECT s.*,p.name plan_name FROM subscriptions s JOIN plans p ON p.id=s.plan_id
            WHERE s.user_id=? AND s.status='active' AND s.ends_at>? ORDER BY s.ends_at DESC""",
            (user["id"], now_iso())).fetchall()
        if request.method == "POST":
            sub_id = request.form.get("subscription_id", type=int)
            provider = request.form.get("provider","")
            repo = request.form.get("repo","").strip()
            sub = con.execute("SELECT * FROM subscriptions WHERE id=? AND user_id=? AND status='active' AND ends_at>?",
                              (sub_id, user["id"], now_iso())).fetchone()
            if not sub or provider not in ("railway","vercel") or not repo:
                flash("সক্রিয় প্ল্যান নির্বাচন করুন এবং GitHub repository দিন।", "danger")
            else:
                # Safe scaffold: records a deployment request. Provider OAuth/API integration must be configured.
                con.execute("""INSERT INTO deployments(user_id,subscription_id,provider,repo,status,logs,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?)""", (user["id"], sub_id, provider, repo, "pending",
                    "ডিপ্লয়মেন্ট রিকোয়েস্ট তৈরি হয়েছে। Provider OAuth/API credentials কনফিগার করা হলে deploy job চালু হবে।",
                    now_iso(), now_iso()))
                did = con.execute("SELECT last_insert_rowid()").fetchone()[0]
                audit(user["id"], "deployment_requested", f"id={did}, provider={provider}, repo={repo}")
                flash("ডিপ্লয়মেন্ট রিকোয়েস্ট তৈরি হয়েছে। এই starter build-এ provider API credentials সেট না করা পর্যন্ত আসল deploy হবে না।", "warning")
                return redirect(url_for("bot_detail", bot_id=did))
    return render_template("hosting.html", subs=subs)

@app.route("/bots/<int:bot_id>")
@login_required
def bot_detail(bot_id):
    user = current_user()
    with db() as con:
        bot = con.execute("SELECT * FROM deployments WHERE id=? AND user_id=?", (bot_id,user["id"])).fetchone()
    if not bot: return redirect(url_for("dashboard"))
    return render_template("bot_detail.html", bot=bot)

@app.route("/admin/bots/<int:bot_id>/railway", methods=["POST"])
@admin_required
def save_railway_ids(bot_id):
    project_id = request.form.get("railway_project_id", "").strip()
    service_id = request.form.get("railway_service_id", "").strip()
    environment_id = request.form.get("railway_environment_id", "").strip()
    deployment_id = request.form.get("railway_deployment_id", "").strip()
    if not service_id or not environment_id or not deployment_id:
        flash("Railway Service ID, Environment ID ও Deployment ID দিতে হবে।", "danger")
    else:
        with db() as con:
            bot = con.execute("SELECT * FROM deployments WHERE id=?", (bot_id,)).fetchone()
            if bot and bot["provider"] == "railway":
                con.execute("UPDATE deployments SET railway_project_id=?,railway_service_id=?,railway_environment_id=?,railway_deployment_id=?,status='running',logs=?,updated_at=? WHERE id=?",
                            (project_id, service_id, environment_id, deployment_id, "Railway service IDs সংরক্ষিত; expiry worker বট বন্ধ/পুনরায় চালুর জন্য প্রস্তুত।", now_iso(), bot_id))
                audit(current_user()["id"], "railway_ids_saved", f"deployment_id={bot_id}", con=con)
                flash("Railway ID সংরক্ষিত হয়েছে। RAILWAY_TOKEN সেট থাকলে নির্ধারিত সময়ে বট বন্ধ করার চেষ্টা হবে।", "success")
            else:
                flash("Railway deployment পাওয়া যায়নি।", "danger")
    return redirect(url_for("admin") + "#bots")

@app.route("/support", methods=["GET","POST"])
@login_required
def support():
    user = current_user()
    with db() as con:
        if request.method == "POST":
            subject = request.form.get("subject","").strip()
            message = request.form.get("message","").strip()
            if subject and message:
                con.execute("INSERT INTO support_tickets(user_id,subject,message,created_at,updated_at) VALUES(?,?,?,?,?)",
                            (user["id"], subject[:120], message[:4000], now_iso(), now_iso()))
                audit(user["id"], "support_ticket", subject, con=con)
                flash("সাপোর্ট টিকিট পাঠানো হয়েছে।", "success")
                return redirect(url_for("support"))
            flash("বিষয় ও বার্তা পূরণ করুন।", "danger")
        tickets = con.execute("SELECT * FROM support_tickets WHERE user_id=? ORDER BY id DESC", (user["id"],)).fetchall()
    return render_template("support.html", tickets=tickets)

@app.route("/admin")
@admin_required
def admin():
    with db() as con:
        stats = {
          "users": con.execute("SELECT COUNT(*) FROM users").fetchone()[0],
          "bots": con.execute("SELECT COUNT(*) FROM deployments").fetchone()[0],
          "failed": con.execute("SELECT COUNT(*) FROM deployments WHERE status='failed'").fetchone()[0],
          "pending": con.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'").fetchone()[0],
          "deposits": con.execute("SELECT COALESCE(SUM(amount),0) FROM deposits WHERE status='approved'").fetchone()[0],
          "active": con.execute("SELECT COUNT(*) FROM subscriptions WHERE status='active' AND ends_at>?", (now_iso(),)).fetchone()[0],
          "expired": con.execute("SELECT COUNT(*) FROM subscriptions WHERE status='expired' OR ends_at<=?", (now_iso(),)).fetchone()[0],
        }
        users = con.execute("SELECT id,account_id,username,email,phone,balance,is_admin,is_banned,created_at FROM users ORDER BY id DESC LIMIT 50").fetchall()
        deposits = con.execute("""SELECT d.*,u.account_id,u.username FROM deposits d JOIN users u ON u.id=d.user_id
                                  ORDER BY d.id DESC LIMIT 50""").fetchall()
        bots = con.execute("""SELECT b.*,u.account_id,u.username FROM deployments b JOIN users u ON u.id=b.user_id
                              ORDER BY b.id DESC LIMIT 50""").fetchall()
        plans = con.execute("SELECT * FROM plans ORDER BY duration_hours").fetchall()
        methods = con.execute("SELECT * FROM payment_methods ORDER BY id").fetchall()
        tickets = con.execute("""SELECT t.*,u.account_id,u.username FROM support_tickets t JOIN users u ON u.id=t.user_id
                                 ORDER BY t.id DESC LIMIT 30""").fetchall()
        logs = con.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 50").fetchall()
    return render_template("admin.html", stats=stats, users=users, deposits=deposits, bots=bots, plans=plans, methods=methods, tickets=tickets, logs=logs)

@app.route("/admin/deposits/<int:deposit_id>/<action>", methods=["POST"])
@admin_required
def review_deposit(deposit_id, action):
    if action not in ("approve","reject"): return redirect(url_for("admin"))
    admin_user = current_user()
    with db() as con:
        dep = con.execute("SELECT * FROM deposits WHERE id=?", (deposit_id,)).fetchone()
        if dep and dep["status"] == "pending":
            if action == "approve":
                con.execute("UPDATE users SET balance=balance+? WHERE id=?", (dep["amount"], dep["user_id"]))
                con.execute("UPDATE deposits SET status='approved',reviewed_at=? WHERE id=?", (now_iso(), deposit_id))
            else:
                con.execute("UPDATE deposits SET status='rejected',reviewed_at=? WHERE id=?", (now_iso(), deposit_id))
            audit(admin_user["id"], "deposit_"+action, str(deposit_id))
    flash("ডিপোজিট আপডেট করা হয়েছে।", "success")
    return redirect(url_for("admin"))

@app.route("/admin/users/<int:user_id>/<action>", methods=["POST"])
@admin_required
def user_action(user_id, action):
    admin_user = current_user()
    with db() as con:
        target = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if target and not target["is_admin"]:
            if action in ("ban","unban"):
                con.execute("UPDATE users SET is_banned=? WHERE id=?", (1 if action=="ban" else 0, user_id))
            elif action == "add_balance":
                amount = float(request.form.get("amount","0"))
                if 0 < amount <= 1000000:
                    con.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount,user_id))
            elif action == "remove_balance":
                amount = float(request.form.get("amount","0"))
                if 0 < amount <= target["balance"]:
                    con.execute("UPDATE users SET balance=balance-? WHERE id=?", (amount,user_id))
            audit(admin_user["id"], "user_"+action, f"user_id={user_id}")
    return redirect(url_for("admin"))

@app.route("/admin/plans/save", methods=["POST"])
@admin_required
def save_plan():
    name=request.form.get("name","").strip()
    try:
        hours=int(request.form.get("duration_hours","0")); price=float(request.form.get("price","-1"))
        plan_id=request.form.get("plan_id", type=int)
        active=1 if request.form.get("active")=="on" else 0
        if not name or hours < 1 or price < 0: raise ValueError()
        with db() as con:
            if plan_id:
                con.execute("UPDATE plans SET name=?,duration_hours=?,price=?,active=? WHERE id=?",(name,hours,price,active,plan_id))
            else:
                con.execute("INSERT INTO plans(name,duration_hours,price,active,is_trial) VALUES(?,?,?,?,0)",(name,hours,price,active))
        flash("প্ল্যান সংরক্ষণ করা হয়েছে।","success")
    except (ValueError, TypeError):
        flash("প্ল্যানের তথ্য সঠিক নয়।","danger")
    return redirect(url_for("admin")+"#plans")

@app.route("/admin/methods/save", methods=["POST"])
@admin_required
def save_method():
    method_id=request.form.get("method_id", type=int)
    name=request.form.get("name","").strip(); instructions=request.form.get("instructions","").strip()
    active=1 if request.form.get("active")=="on" else 0
    if name and instructions:
        with db() as con:
            if method_id: con.execute("UPDATE payment_methods SET name=?,instructions=?,active=? WHERE id=?",(name,instructions,active,method_id))
            else: con.execute("INSERT INTO payment_methods(name,instructions,active) VALUES(?,?,?)",(name,instructions,active))
        flash("পেমেন্ট মেথড সংরক্ষণ করা হয়েছে।","success")
    return redirect(url_for("admin")+"#payments")

@app.route("/admin/methods/<int:method_id>/delete", methods=["POST"])
@admin_required
def delete_method(method_id):
    with db() as con: con.execute("DELETE FROM payment_methods WHERE id=?",(method_id,))
    return redirect(url_for("admin")+"#payments")

@app.route("/admin/tickets/<int:ticket_id>/reply", methods=["POST"])
@admin_required
def reply_ticket(ticket_id):
    reply=request.form.get("reply","").strip()
    with db() as con:
        con.execute("UPDATE support_tickets SET reply=?,status='answered',updated_at=? WHERE id=?",(reply,now_iso(),ticket_id))
    audit(current_user()["id"],"support_reply",str(ticket_id))
    return redirect(url_for("admin")+"#support")

@app.route("/health")
def health():
    return jsonify({"status":"ok"})

RAILWAY_API_URL = "https://backboard.railway.com/graphql/v2"


def railway_graphql(query, variables):
    token = os.environ.get("RAILWAY_TOKEN", "").strip()
    if not token:
        raise RuntimeError("RAILWAY_TOKEN environment variable is not configured")
    response = requests.post(RAILWAY_API_URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": query, "variables": variables}, timeout=25)
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError("Railway API: " + "; ".join(e.get("message", "Unknown error") for e in payload["errors"]))
    return payload.get("data", {})


def railway_stop(deployment_id):
    data = railway_graphql("mutation StopDeployment($id: String!) { deploymentStop(id: $id) }", {"id": deployment_id})
    if data.get("deploymentStop") is False:
        raise RuntimeError("Railway did not confirm deploymentStop")
    return True


def railway_start(service_id, environment_id):
    data = railway_graphql("mutation StartService($serviceId: String!, $environmentId: String!) { serviceInstanceDeployV2(serviceId: $serviceId, environmentId: $environmentId) }",
                           {"serviceId": service_id, "environmentId": environment_id})
    deployment_id = data.get("serviceInstanceDeployV2")
    if not deployment_id:
        raise RuntimeError("Railway did not return a new deployment ID")
    return str(deployment_id)


def notify_user(user_id, title, message, kind="info", con=None):
    values = (user_id, title[:160], message[:1500], kind, now_iso())
    if con is not None:
        con.execute("INSERT INTO notifications(user_id,title,message,kind,created_at) VALUES(?,?,?,?,?)", values)
    else:
        with db() as own_con:
            own_con.execute("INSERT INTO notifications(user_id,title,message,kind,created_at) VALUES(?,?,?,?,?)", values)


def send_admin_telegram(text_message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "").strip()
    if not token or not chat_id:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": text_message}, timeout=10).raise_for_status()
    except Exception:
        pass


def process_expirations():
    """Warn 24h before expiry, then stop configured Railway deployments at expiry.
    Safe to call repeatedly from a dedicated worker; DB flags prevent duplicate warnings.
    """
    current = datetime.now(timezone.utc)
    current_text = current.isoformat(timespec="seconds")
    warning_limit = (current + timedelta(hours=24)).isoformat(timespec="seconds")
    # Claim 24h warning in DB first so concurrent worker retries don't spam users.
    with db() as con:
        due_warnings = con.execute("SELECT s.id,s.user_id,s.ends_at,p.name FROM subscriptions s JOIN plans p ON p.id=s.plan_id WHERE s.status='active' AND s.warning_sent_at='' AND s.ends_at>? AND s.ends_at<=?", (current_text, warning_limit)).fetchall()
        for sub in due_warnings:
            con.execute("UPDATE subscriptions SET warning_sent_at=? WHERE id=? AND warning_sent_at=''", (current_text, sub["id"]))
            notify_user(sub["user_id"], "⏰ হোস্টিং মেয়াদ শেষ হতে ২৪ ঘণ্টা বাকি", f"আপনার {sub['name']} হোস্টিং প্ল্যানের মেয়াদ {sub['ends_at']} সময়ে শেষ হবে। বট চালু রাখতে সময়মতো নতুন প্ল্যান কিনুন।", "warning", con=con)
        expiring = con.execute("SELECT * FROM subscriptions WHERE status IN ('active','expired_unstopped') AND ends_at<=? ORDER BY id", (current_text,)).fetchall()

    for sub in expiring:
        with db() as con:
            bots = con.execute("SELECT * FROM deployments WHERE subscription_id=? AND provider='railway' AND status NOT IN ('failed','pending','expired')", (sub["id"],)).fetchall()
        failures = []
        stopped_ids = []
        for bot in bots:
            if bot["status"] == "stopped":
                continue
            if not bot["railway_deployment_id"]:
                failures.append(f"bot #{bot['id']}: Railway Deployment ID missing")
                continue
            try:
                railway_stop(bot["railway_deployment_id"])
                with db() as con:
                    con.execute("UPDATE deployments SET status='stopped',logs=?,updated_at=? WHERE id=?",
                                ("🛑 মেয়াদ শেষ হওয়ায় Railway API দিয়ে বট বন্ধ করা হয়েছে।", now_iso(), bot["id"]))
                stopped_ids.append(bot["id"])
            except Exception as exc:
                failures.append(f"bot #{bot['id']}: {str(exc)[:250]}")
                with db() as con:
                    con.execute("UPDATE deployments SET status='stop_failed',logs=?,updated_at=? WHERE id=?",
                                (f"মেয়াদ শেষে Railway stop ব্যর্থ: {str(exc)[:700]}", now_iso(), bot["id"]))
        with db() as con:
            current_sub = con.execute("SELECT status FROM subscriptions WHERE id=?", (sub["id"],)).fetchone()
            if failures:
                first_attempt = current_sub and current_sub["status"] != "expired_unstopped"
                con.execute("UPDATE subscriptions SET status='expired_unstopped' WHERE id=?", (sub["id"],))
                if first_attempt:
                    notify_user(sub["user_id"], "⚠️ বট বন্ধ করার জন্য সহায়তা দরকার", "আপনার হোস্টিং মেয়াদ শেষ হয়েছে, কিন্তু Railway থেকে বট বন্ধ করার নিশ্চিতকরণ পাওয়া যায়নি। অ্যাডমিনকে জানানো হয়েছে; অনুগ্রহ করে সাপোর্টে যোগাযোগ করুন।", "danger", con=con)
                    send_admin_telegram(f"⚠️ Expiry stop failed | subscription #{sub['id']} | " + "; ".join(failures))
                audit(None, "subscription_stop_failed", f"subscription_id={sub['id']} | " + "; ".join(failures), con=con)
            else:
                con.execute("UPDATE subscriptions SET status='expired' WHERE id=?", (sub["id"],))
                # Notify once when transitioning to expired; retries don't duplicate this message.
                if current_sub and current_sub["status"] != "expired":
                    notify_user(sub["user_id"], "🛑 হোস্টিং বট বন্ধ হয়েছে", ("আপনার হোস্টিংয়ের নির্ধারিত সময় শেষ হয়েছে। সংশ্লিষ্ট Railway বট সফলভাবে বন্ধ করা হয়েছে। আবার চালু করতে নতুন প্ল্যান কিনুন." if bots else "আপনার হোস্টিং প্ল্যানের মেয়াদ শেষ হয়েছে। এই প্ল্যানের সঙ্গে কোনো সক্রিয় Railway deployment যুক্ত ছিল না। আবার চালু করতে নতুন প্ল্যান কিনুন."), "success", con=con)
                    send_admin_telegram(f"🛑 Hosting expired and Railway bot stopped | subscription #{sub['id']} | stopped bots: {stopped_ids}")
                audit(None, "subscription_expired", f"subscription_id={sub['id']} | stopped={stopped_ids}", con=con)


def expire_subscriptions():
    # Kept as a compatibility wrapper; actual work is performed by the worker.
    process_expirations()

# Initialize schema for both local execution and Gunicorn/Railway imports.
init_db()
# First startup only: create an admin from environment variables.
admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
admin_password = os.environ.get("ADMIN_PASSWORD", "")
if admin_email and admin_password:
    with db() as con:
        existing = con.execute("SELECT id FROM users WHERE email=?", (admin_email,)).fetchone()
        if not existing:
            con.execute("INSERT INTO users(account_id,username,email,password_hash,is_admin,created_at) VALUES(?,?,?,?,1,?)",
                        ("ADMIN" + secrets.token_hex(4).upper(), "admin", admin_email, generate_password_hash(admin_password), now_iso()))
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
