# NIKAN EARN - Reply Keyboard Real Bot (Fixed Version)
# Python 3.10+ / aiogram 3.x

import asyncio
import os
import re
import sqlite3
import uuid
from html import escape
from urllib.parse import quote_plus, urlparse, parse_qsl, urlencode, urlunparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, MenuButtonWebApp, WebAppInfo
)

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from urllib.parse import parse_qsl
import hashlib
import hmac
import json

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

# =========================
# CONFIG
# =========================
# TODO: Replace with your valid token from @BotFather
BOT_TOKEN = "................."
ADMIN_ID = 2037461288
OWNER_ID = ADMIN_ID

PAYMENT_GATEWAY_URL = "https://ttkpay.up.railway.app"
BINANCE_DEPOSIT_ADDRESS = "0xade76b7f023c3ded14850293ea26e477edbdd048"
USDT_RATE_BDT = Decimal("125")

DB_NAME = "nikan.db"
DB_BACKUP_NAME = "nikan_backup.db"
DEFAULT_HISTORY_CHANNEL_LINK = "https://t.me/+a_WJfoQpjvtiOTNl"

# =========================
# PLANS
# =========================
PLANS = {
    "VIP1": 300, "VIP2": 500, "VIP3": 1000, "VIP4": 2000,
    "VIP5": 3000, "VIP6": 5000, "VIP7": 7500, "VIP8": 10000,
    "VIP9": 15000, "VIP10": 20000, "VIP11": 30000, "VIP12": 50000,
}
PLAN_DAYS = 4
DEMO_DAILY_RATE = Decimal("0.34")

# Initialize Bot and Dispatcher cleanly
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

PROCESSED_CALLBACKS = {}

def callback_once(key: str, ttl: int = 5) -> bool:
    now = datetime.now().timestamp()
    for k in list(PROCESSED_CALLBACKS.keys()):
        if now - PROCESSED_CALLBACKS[k] > ttl:
            del PROCESSED_CALLBACKS[k]
    if key in PROCESSED_CALLBACKS:
        return False
    PROCESSED_CALLBACKS[key] = now
    return True

# =========================
# DATABASE
# =========================
def db():
    con = sqlite3.connect(DB_NAME, timeout=10, isolation_level=None)
    con.execute("PRAGMA busy_timeout=10000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def now_iso():
    return datetime.now(timezone.utc).isoformat()

def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        name TEXT,
        username TEXT,
        main_balance REAL DEFAULT 0,
        deposit_balance REAL DEFAULT 0,
        bonus_balance REAL DEFAULT 0,
        referral_balance REAL DEFAULT 0,
        total_earnings REAL DEFAULT 0,
        created_at TEXT,
        referrer_id INTEGER DEFAULT 0
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        method TEXT,
        amount REAL,
        txid TEXT,
        order_no TEXT,
        status TEXT DEFAULT 'Pending',
        reason TEXT DEFAULT '',
        created_at TEXT,
        updated_at TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        method TEXT,
        account TEXT,
        amount REAL,
        status TEXT DEFAULT 'Pending',
        reason TEXT DEFAULT '',
        created_at TEXT,
        updated_at TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        plan TEXT,
        amount REAL,
        activated_at TEXT,
        expires_at TEXT,
        last_claim_date TEXT DEFAULT '',
        active INTEGER DEFAULT 1
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS earnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        plan_id INTEGER,
        amount REAL,
        claim_date TEXT,
        created_at TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bonuses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        type TEXT,
        created_at TEXT
    )""")

    cur.execute("CREATE TABLE IF NOT EXISTS plan_catalog (name TEXT PRIMARY KEY, amount REAL NOT NULL, emoji TEXT DEFAULT '💎', days INTEGER DEFAULT 4, enabled INTEGER DEFAULT 1, daily_rate REAL DEFAULT 0.34)")
    pc_cols={r[1] for r in cur.execute("PRAGMA table_info(plan_catalog)").fetchall()}
    if "daily_rate" not in pc_cols: cur.execute("ALTER TABLE plan_catalog ADD COLUMN daily_rate REAL DEFAULT 0.34")
    plan_cols={r[1] for r in cur.execute("PRAGMA table_info(plans)").fetchall()}
    if "daily_rate" not in plan_cols: cur.execute("ALTER TABLE plans ADD COLUMN daily_rate REAL DEFAULT 0.34")
    for _name,_amount in PLANS.items():
        cur.execute("INSERT OR IGNORE INTO plan_catalog(name,amount,emoji,days,enabled,daily_rate) VALUES(?,?,?,?,1,?)",(_name,_amount,'💎',PLAN_DAYS,float(DEMO_DAILY_RATE)))
    cur.execute("UPDATE plan_catalog SET daily_rate=COALESCE(daily_rate,?)",(float(DEMO_DAILY_RATE),))
    cur.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, role TEXT DEFAULT 'admin', added_at TEXT)")
    cur.execute("INSERT OR IGNORE INTO admins(user_id,role,added_at) VALUES(?,?,?)", (ADMIN_ID, 'owner', now_iso()))
    cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    
    defaults = {
        'bot_enabled':'1','fund_enabled':'1','withdraw_enabled':'1',
        'dep_bkash_enabled':'1','dep_nagad_enabled':'1',
        'wth_bkash_enabled':'1','wth_nagad_enabled':'1','wth_rocket_enabled':'1','wth_upay_enabled':'1',
        'bkash_number':'','nagad_number':'','dep_bkash_gateway':'','dep_nagad_gateway':'',
        'min_dep':'50','max_dep':'10000','min_wth':'100','max_wth':'25000','daily_dep_limit':'3',
        'force_join_enabled':'0','force_join_chat':'','force_join_link':'',
        'history_channel_enabled':'0','history_channel_chat':'','history_channel_link':DEFAULT_HISTORY_CHANNEL_LINK,
        'auto_db_backup':'1','auto_db_restore':'1'
    }
    for k, v in defaults.items():
        cur.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)', (k, v))


    # Dynamic payment methods / message templates / performance indexes
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payment_methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            kind TEXT DEFAULT 'deposit',
            enabled INTEGER DEFAULT 1,
            logo TEXT DEFAULT '💳',
            number TEXT DEFAULT '',
            gateway TEXT DEFAULT '',
            manual_enabled INTEGER DEFAULT 0,
            gateway_enabled INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS message_templates (
            key TEXT PRIMARY KEY,
            content TEXT DEFAULT '',
            parse_mode TEXT DEFAULT 'HTML',
            media_type TEXT DEFAULT '',
            media_id TEXT DEFAULT '',
            updated_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_commands (
            command TEXT PRIMARY KEY,
            title TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            position TEXT DEFAULT 'bottom',
            message_key TEXT DEFAULT '',
            updated_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS force_join_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat TEXT UNIQUE NOT NULL,
            link TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0
        )
    """)
    pm_cols={r[1] for r in cur.execute("PRAGMA table_info(payment_methods)").fetchall()}
    if "gateway_enabled" not in pm_cols:
        cur.execute("ALTER TABLE payment_methods ADD COLUMN gateway_enabled INTEGER DEFAULT 0")
        cur.execute("UPDATE payment_methods SET gateway_enabled=CASE WHEN TRIM(COALESCE(gateway,''))<>'' THEN 1 ELSE 0 END")
    else:
        # Keep an explicitly configured ON/OFF state; only initialize missing/NULL values.
        cur.execute("UPDATE payment_methods SET gateway_enabled=CASE WHEN gateway_enabled IS NULL THEN CASE WHEN TRIM(COALESCE(gateway,''))<>'' THEN 1 ELSE 0 END ELSE gateway_enabled END")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_method_name_kind ON payment_methods(name,kind)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_deposits_status ON deposits(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_deposits_order ON deposits(order_no)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_withdrawals_status ON withdrawals(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_withdrawals_user ON withdrawals(user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_referrer ON users(referrer_id)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS balance_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            field TEXT NOT NULL,
            operation TEXT NOT NULL,
            amount REAL NOT NULL,
            balance_before REAL DEFAULT 0,
            balance_after REAL DEFAULT 0,
            admin_id INTEGER,
            reference TEXT UNIQUE,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_balance_ledger_user ON balance_ledger(user_id)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payment_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            payment_method TEXT NOT NULL,
            gateway_url TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            transaction_id TEXT DEFAULT '',
            submitted_at TEXT DEFAULT '',
            message_id INTEGER DEFAULT 0
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_payment_sessions_user_status ON payment_sessions(user_id,status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_payment_sessions_status ON payment_sessions(status)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            actor_id INTEGER DEFAULT 0,
            user_id INTEGER DEFAULT 0,
            reference TEXT DEFAULT '',
            details TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events(created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_user ON audit_events(user_id)")

    # Safe legacy TxID migration before creating the database-level unique index.
    dup_groups = cur.execute("""
        SELECT lower(trim(txid)) AS tx, MIN(id) AS keep_id
        FROM deposits
        WHERE txid IS NOT NULL AND trim(txid) <> ''
        GROUP BY lower(trim(txid))
        HAVING COUNT(*) > 1
    """).fetchall()
    for tx, keep_id in dup_groups:
        old_rows = cur.execute("SELECT id,txid FROM deposits WHERE lower(trim(txid))=? AND id<>?", (tx,keep_id)).fetchall()
        for did, old_txid in old_rows:
            cur.execute("UPDATE deposits SET txid=? WHERE id=?", (f"DUPLICATE-LEGACY-{did}-{old_txid}", did))
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_deposits_txid_unique
        ON deposits(lower(trim(txid)))
        WHERE txid IS NOT NULL AND trim(txid) <> ''
    """)

    payment_defaults = [
        ("bKash", "deposit", "💳", 1),
        ("Nagad", "deposit", "💠", 2),
        ("Binance", "deposit", "🟡", 3),
        ("bKash", "withdraw", "💳", 1),
        ("Nagad", "withdraw", "💠", 2),
        ("Rocket", "withdraw", "🚀", 3),
    ]
    for name, kind, logo, order in payment_defaults:
        cur.execute("""
            INSERT OR IGNORE INTO payment_methods
            (name,kind,enabled,logo,sort_order,created_at,gateway_enabled)
            VALUES(?,?,1,?,?,?,0)
        """, (name, kind, logo, order, now_iso()))

    extra_defaults = {
        "referral_enabled":"0",
        "referral_bonus":"0",
        "bonus_enabled":"1",
        "bonus_amount":"5",
        "bonus_expiry_days":"1",
        "welcome_message":"<b>🚀 NIKAN EARN</b>\n\n<b>স্বাগতম! নিচের মেনু থেকে একটি অপশন নির্বাচন করুন।</b>",
        "deposit_approved_message":"<b>🎉 Deposit Successful!</b>\n\n<b>আপনার {amount}৳ Deposit সফলভাবে সম্পন্ন হয়েছে। ✅</b>\n<b>📝 Transaction ID: {txid}</b>\n<b>🆔 Order Number: {order}</b>",
        "deposit_rejected_message":"<b>❌ Deposit Rejected</b>\n\n<b>আপনার {amount}৳ ডিপোজিট রিকোয়েস্টটি বাতিল করা হয়েছে।</b>\n<b>📝 কারণ: {reason}</b>",
        "withdraw_approved_message":"<b>🎊 Withdraw Completed!</b>\n\n<b>💰 Amount: {amount}৳</b>\n<b>🟢 আপনার পেমেন্ট রিকোয়েস্ট সফলভাবে সম্পন্ন হয়েছে।</b>",
        "withdraw_rejected_message":"<b>🚫 Withdraw Rejected</b>\n\n<b>💰 Amount: {amount}৳</b>\n<b>📝 কারণ: {reason}</b>\n<b>💰 ব্যালেন্স ফেরত দেওয়া হয়েছে।</b>",
        "invalid_number_message":"<b>❌ Invalid.. Please enter a valid number.</b>",
        "cancelled_message":"<b>❌ cancelled.</b>",
        "referral_message":"<b>🎉 আপনি একজন নতুন সদস্য রেফার করে {amount}৳ Referral Bonus পেয়েছেন।</b>",
        "demo_notice":"<b>✨ নিয়ম মেনে কাজ করুন এবং আপনার আয়ের হিসাব নিয়মিত দেখুন।</b>",
        "daily_demo_warning":"<b>✨ নিয়ম মেনে কাজ করুন এবং আপনার আয়ের হিসাব নিয়মিত দেখুন।</b>",
    }
    for k, v in extra_defaults.items():
        cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))

    cols = {r[1] for r in cur.execute('PRAGMA table_info(users)').fetchall()}
    for col, typ, default in [
        ('task_balance', 'REAL', '0'),
        ('referral_count', 'INTEGER', '0'),
        ('completed_tasks', 'INTEGER', '0'),
        ('banned', 'INTEGER', '0'),
        ('suspended', 'INTEGER', '0'),
        ('referrer_id', 'INTEGER', '0')
    ]:
        if col not in cols:
            cur.execute(f'ALTER TABLE users ADD COLUMN {col} {typ} DEFAULT {default}')

    con.commit()
    con.close()

def backup_database():
    """Create a consistent SQLite backup without touching the live DB."""
    if not os.path.exists(DB_NAME):
        return False
    src = None
    dst = None
    try:
        src = sqlite3.connect(DB_NAME, timeout=30)
        dst = sqlite3.connect(DB_BACKUP_NAME, timeout=30)
        src.backup(dst)
        dst.commit()
        return True
    except Exception:
        return False
    finally:
        try:
            if src: src.close()
        except Exception: pass
        try:
            if dst: dst.close()
        except Exception: pass

def restore_database_if_missing():
    """Restore the last consistent backup only when the main DB is missing."""
    if os.path.exists(DB_NAME) or not os.path.exists(DB_BACKUP_NAME):
        return False
    try:
        src = sqlite3.connect(DB_BACKUP_NAME, timeout=30)
        dst = sqlite3.connect(DB_NAME, timeout=30)
        src.backup(dst)
        dst.commit()
        src.close(); dst.close()
        return True
    except Exception:
        try:
            src.close()
        except Exception: pass
        try:
            dst.close()
        except Exception: pass
        return False

def audit_event(event_type: str, actor_id: int = 0, user_id: int = 0, reference: str = '', details: str = ''):
    """Persist every important event. Channel delivery is best-effort and never blocks bot logic."""
    con = db()
    con.execute("INSERT INTO audit_events(event_type,actor_id,user_id,reference,details,created_at) VALUES(?,?,?,?,?,?)",
                (event_type, actor_id or 0, user_id or 0, reference or '', details or '', now_iso()))
    con.commit(); con.close()

async def send_history_event(event_type: str, actor_id: int = 0, user_id: int = 0, reference: str = '', details: str = ''):
    try:
        audit_event(event_type, actor_id, user_id, reference, details)
    except Exception:
        pass
    if getset('history_channel_enabled','0') != '1':
        return
    chat = (getset('history_channel_chat','') or '').strip()
    if not chat:
        return
    text = (
        f"<b>📜 NIKAN EARN HISTORY</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>🧾 Event:</b> <code>{escape(str(event_type))}</code>\n"
        f"<b>👤 User ID:</b> <code>{user_id or '—'}</code>\n"
        f"<b>🛡 Actor/Admin:</b> <code>{actor_id or '—'}</code>\n"
        f"<b>🔖 Reference:</b> <code>{escape(str(reference or '—'))}</code>\n"
        f"<b>🕒 Time (UTC):</b> <code>{now_iso()}</code>\n"
        f"<b>📱 Device:</b> <code>Telegram Bot API does not expose device model</code>\n\n"
        f"<b>📝 Details:</b>\n{escape(details or '—')}"
    )
    try:
        await bot.send_message(chat, text)
    except Exception:
        pass

async def periodic_database_backup():
    while True:
        try:
            if getset('auto_db_backup','1') == '1':
                backup_database()
        except Exception:
            pass
        await asyncio.sleep(60)

def plan_meta(name):
    con=db(); row=con.execute("SELECT amount,days,emoji,COALESCE(daily_rate,?) FROM plan_catalog WHERE name=? AND enabled=1",(float(DEMO_DAILY_RATE),name)).fetchone(); con.close()
    if row: return Decimal(str(row[0])),int(row[1]),row[2],Decimal(str(row[3]))
    return Decimal(str(PLANS.get(name,0))),PLAN_DAYS,'💎',DEMO_DAILY_RATE

def get_plans():
    con=db(); rows=con.execute("SELECT name,amount FROM plan_catalog WHERE enabled=1 ORDER BY rowid").fetchall(); con.close()
    return {name:amount for name,amount in rows} or dict(PLANS)

def getset(k, default=""):
    con = db()
    r = con.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
    con.close()
    return r[0] if r else default

def setset(k, v):
    con = db()
    con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
    con.commit()
    con.close()


def get_setting_bool(key: str, default=False) -> bool:
    return getset(key, "1" if default else "0") == "1"

def set_template(key: str, content: str, media_type="", media_id=""):
    con = db()
    con.execute("""
        INSERT INTO message_templates(key,content,media_type,media_id,updated_at)
        VALUES(?,?,?,?,?)
        ON CONFLICT(key) DO UPDATE SET
            content=excluded.content, media_type=excluded.media_type,
            media_id=excluded.media_id, updated_at=excluded.updated_at
    """, (key, content, media_type, media_id, now_iso()))
    con.commit()
    con.close()

def get_template(key: str, default=""):
    con = db()
    row = con.execute("SELECT content,media_type,media_id FROM message_templates WHERE key=?", (key,)).fetchone()
    con.close()
    return row if row else (getset(key, default), "", "")

def render_template(key: str, default: str, **kwargs):
    content, _, _ = get_template(key, default)
    try:
        return content.format(**kwargs)
    except Exception:
        return content

async def send_template(chat_id: int, key: str, default: str, **kwargs):
    content, media_type, media_id = get_template(key, default)
    try:
        content = content.format(**kwargs)
    except Exception:
        pass
    if media_type == "photo" and media_id:
        return await bot.send_photo(chat_id, media_id, caption=content or None)
    if media_type == "video" and media_id:
        return await bot.send_video(chat_id, media_id, caption=content or None)
    if media_type == "document" and media_id:
        return await bot.send_document(chat_id, media_id, caption=content or None)
    if media_type == "animation" and media_id:
        return await bot.send_animation(chat_id, media_id, caption=content or None)
    return await bot.send_message(chat_id, content or "")

def payment_methods(kind: str):
    con = db()
    rows = con.execute("""
        SELECT name,logo,number,gateway,manual_enabled
        FROM payment_methods
        WHERE kind=? AND enabled=1 ORDER BY sort_order,id
    """, (kind,)).fetchall()
    con.close()
    return rows

def get_payment_method(name: str, kind: str):
    con = db()
    row = con.execute("""
        SELECT name,logo,number,gateway,manual_enabled
        FROM payment_methods WHERE name=? AND kind=? AND enabled=1
    """, (name, kind)).fetchone()
    con.close()
    return row

def get_payment_method_config(name: str, kind: str, require_enabled: bool = True):
    con = db()
    sql = """SELECT name,logo,number,gateway,manual_enabled,COALESCE(gateway_enabled,0),enabled
             FROM payment_methods WHERE name=? AND kind=?"""
    row = con.execute(sql, (name, kind)).fetchone()
    con.close()
    if not row:
        return None
    if require_enabled and not int(row[6]):
        return None
    return row

def build_payment_url(template: str, amount, user_id: int, method: str, order_id: str = "", session_id: str = "") -> str:
    """Build a gateway URL safely. Supports placeholders AND old fixed query links.
    Known query keys are overwritten with the current deposit amount/user/method/session.
    """
    url = (template or "").strip()
    if not url:
        return ""
    values = {
        "amount": str(amount),
        "user_id": str(user_id),
        "method": method,
        "order": order_id or session_id,
        "session_id": session_id or order_id,
    }
    # First support the documented placeholder style.
    try:
        url = url.format(**values)
    except Exception:
        # Leave unknown placeholders untouched rather than breaking the gateway.
        for key, val in values.items():
            url = url.replace("{" + key + "}", str(val))

    # Then support legacy links such as:
    # https://ttkpay.up.railway.app/?amount=&user_id=2037461288&method=bKash
    # The current user's amount/ID/method must always be used.
    try:
        parsed = urlparse(url)
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        known = {k.lower() for k, _ in pairs}
        out=[]
        replaced=set()
        for k,v in pairs:
            lk=k.lower()
            if lk in values:
                out.append((k, values[lk]))
                replaced.add(lk)
            else:
                out.append((k,v))
        for key in ("amount","user_id","method","order","session_id"):
            if key not in replaced and key in known:
                continue
        # If the legacy URL did not contain a key, append only the essential current values.
        for key in ("amount","user_id","method"):
            if key not in known:
                out.append((key, values[key]))
        return urlunparse(parsed._replace(query=urlencode(out, doseq=True)))
    except Exception:
        return url

def atomic_status_change(table: str, pk_field: str, pk, new_status: str, allowed=("Pending","Processing")):
    # DB-level guard: only one admin can transition a request.
    placeholders = ",".join("?" for _ in allowed)
    con = db()
    cur = con.cursor()
    cur.execute(
        f"UPDATE {table} SET status=?, updated_at=? WHERE {pk_field}=? AND status IN ({placeholders})",
        (new_status, now_iso(), pk, *allowed)
    )
    changed = cur.rowcount == 1
    if changed:
        con.commit()
    else:
        con.rollback()
    con.close()
    return changed

def copyable_admin_text(value):
    return f"<code>{value}</code>"

def get_user(message: Message, referrer_id: int = 0):
    u = message.from_user
    ref_to_save = referrer_id if (referrer_id and referrer_id != u.id) else 0
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (u.id,))
    row = cur.fetchone()

    if not row:
        cur.execute("""
            INSERT INTO users(user_id,name,username,created_at,referrer_id)
            VALUES(?,?,?,?,?)
        """, (u.id, u.full_name, u.username or "", now_iso(), ref_to_save))
        
        if ref_to_save:
            cur.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id=?", (ref_to_save,))
            # Referral signup bonus: controlled by Referral ON + Bonus ON + Bonus Amount.
            try:
                if getset("referral_enabled","0") == "1" and getset("bonus_enabled","0") == "1":
                    bonus = Decimal(getset("bonus_amount","0") or "0")
                    if bonus > 0:
                        ref_balance = cur.execute("SELECT referral_balance FROM users WHERE user_id=?", (ref_to_save,)).fetchone()
                        if ref_balance is not None:
                            cur.execute("UPDATE users SET referral_balance=referral_balance+?, main_balance=main_balance+?, total_earnings=total_earnings+? WHERE user_id=?",
                                        (float(bonus), float(bonus), float(bonus), ref_to_save))
                            cur.execute("INSERT INTO bonuses(user_id,amount,type,created_at) VALUES(?,?,?,?)",
                                        (ref_to_save,float(bonus),"referral_signup",now_iso()))
            except Exception:
                pass
        con.commit()
        cur.execute("SELECT * FROM users WHERE user_id=?", (u.id,))
        row = cur.fetchone()
    else:
        # If an older account was created before a referral parameter arrived, attach the
        # first valid referrer exactly once and award the configured signup bonus.
        existing_ref = cur.execute("SELECT COALESCE(referrer_id,0) FROM users WHERE user_id=?", (u.id,)).fetchone()
        if ref_to_save and ref_to_save != u.id and (not existing_ref or not existing_ref[0]):
            cur.execute("UPDATE users SET referrer_id=? WHERE user_id=? AND COALESCE(referrer_id,0)=0", (ref_to_save, u.id))
            if cur.rowcount == 1:
                cur.execute("UPDATE users SET referral_count=referral_count+1 WHERE user_id=?", (ref_to_save,))
                try:
                    if getset("referral_enabled","0") == "1" and getset("bonus_enabled","0") == "1":
                        bonus = Decimal(getset("bonus_amount","0") or "0")
                        if bonus > 0:
                            cur.execute("UPDATE users SET referral_balance=referral_balance+?, main_balance=main_balance+?, total_earnings=total_earnings+? WHERE user_id=?", (float(bonus),float(bonus),float(bonus),ref_to_save))
                            cur.execute("INSERT INTO bonuses(user_id,amount,type,created_at) VALUES(?,?,?,?)", (ref_to_save,float(bonus),"referral_signup",now_iso()))
                except Exception:
                    pass
        cur.execute("""
            UPDATE users SET name=?, username=? WHERE user_id=?
        """, (u.full_name, u.username or "", u.id))
        con.commit()

    con.close()
    return row

def user_row(uid: int):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()
    con.close()
    return row

def money(x):
    return f"{Decimal(str(x)):.2f}".rstrip("0").rstrip(".")

def order_no():
    return "RC" + datetime.now().strftime("%Y%m%d%H%M%S%f")[:21]

def role(uid):
    con = db()
    r = con.execute("SELECT role FROM admins WHERE user_id=?", (uid,)).fetchone()
    con.close()
    return r[0] if r else None

def admin_ok(uid):
    try:
        return int(uid) == int(ADMIN_ID) or role(uid) is not None
    except Exception:
        return False

def super_ok(uid):
    try:
        return int(uid) == int(OWNER_ID)
    except Exception:
        return False

def main_keyboard(user_id: int):
    keyboard_rows = [
        [KeyboardButton(text="🔐 ফান্ড ডিপোজিট"), KeyboardButton(text="👤 একাউন্ট")],
        [KeyboardButton(text="💸 Withdraw"), KeyboardButton(text="👥 Referral")],
        [KeyboardButton(text="📊 Daily Earnings"), KeyboardButton(text="🎁 Bonus Center")],
        [KeyboardButton(text="💎 Available Plans"), KeyboardButton(text="🧾 Transaction History")],
        [KeyboardButton(text="🆘 Help & Support")],
    ]
    if admin_ok(user_id):
        keyboard_rows.append([KeyboardButton(text="🔧 Admin Panel")])

    return ReplyKeyboardMarkup(
        keyboard=keyboard_rows,
        resize_keyboard=True,
        input_field_placeholder="একটি অপশন নির্বাচন করুন"
    )

def cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Cancel")]],
        resize_keyboard=True
    )

# =========================
# FORCE JOIN CHECKER
# =========================
async def check_force_join(user_id: int) -> bool:
    if getset("force_join_enabled") != "1":
        return True
    con=db()
    rows=con.execute("SELECT chat FROM force_join_channels WHERE enabled=1 ORDER BY sort_order,id").fetchall()
    con.close()
    if not rows:
        chat=getset("force_join_chat")
        rows=[(chat,)] if chat else []
    if not rows: return True
    for (chat,) in rows:
        try:
            member=await bot.get_chat_member(chat_id=chat,user_id=user_id)
            if member.status not in ("member","administrator","creator"):
                return False
        except Exception:
            return False
    return True

async def force_join_prompt(message: Message):
    con=db()
    rows=con.execute("SELECT link FROM force_join_channels WHERE enabled=1 ORDER BY sort_order,id").fetchall()
    con.close()
    if not rows:
        rows=[(getset("force_join_link") or "https://t.me/",)]
    buttons=[[InlineKeyboardButton(text=f"📢 Join Channel {i+1}",url=link)] for i,(link,) in enumerate(rows)]
    buttons.append([InlineKeyboardButton(text="✅ Check Joined",callback_data="check_force_join")])
    await message.answer(
        "<b>🔒 Channel Join Required</b>\n\n"
        "<b>বট ব্যবহার করতে হলে নিচের প্রয়োজনীয় চ্যানেলগুলোতে জয়েন করুন। তারপর Check Joined চাপুন।</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

# =========================
# STATES
# =========================
class DepositState(StatesGroup):
    method = State()
    amount = State()
    txid = State()

class WithdrawState(StatesGroup):
    method = State()
    account = State()
    amount = State()

class UserControlState(StatesGroup):
    amount = State()
    message = State()
    plan_name = State()
    plan_duration = State()
    plan_extend = State()

class AdvancedAdminState(StatesGroup):
    generic_value = State()
    user_id = State()
    user_action = State()
    user_value = State()
    broadcast = State()
    user_broadcast_id = State()
    user_broadcast_text = State()
    gateway_url = State()
    number = State()
    force_chat = State()
    force_link = State()
    add_admin = State()
    remove_admin = State()
    reject_reason = State()
    plan_uid = State()
    plan_name = State()
    payment_method = State()
    message_edit = State()
    transaction_edit = State()
    command_edit = State()
    history_channel = State()

# =========================
# SAFE USER / PAYMENT / PLAN HELPERS
# =========================
def utc_dt(value):
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)

def expire_user_plans(uid: int, con=None):
    own = con is None
    con = con or db()
    now = now_iso()
    con.execute("UPDATE plans SET active=0 WHERE user_id=? AND active=1 AND expires_at<=?", (uid, now))
    if own:
        con.commit(); con.close()

def expire_all_plans(con=None):
    own = con is None
    con = con or db()
    con.execute("UPDATE plans SET active=0 WHERE active=1 AND expires_at<=?", (now_iso(),))
    if own:
        con.commit(); con.close()

def normalize_txid(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip()).lower()

def new_session_id():
    return "PS-" + uuid.uuid4().hex.upper()

def active_payment_session(uid: int):
    con=db()
    row=con.execute("""SELECT session_id,user_id,amount,payment_method,gateway_url,status,created_at,expires_at,transaction_id,submitted_at,message_id\n                       FROM payment_sessions WHERE user_id=? AND status='ACTIVE' ORDER BY id DESC LIMIT 1""",(uid,)).fetchone()
    con.close()
    return row

def create_payment_session(uid:int, amount:Decimal, method:str, gateway_url:str, message_id:int=0):
    con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
    try:
        cur.execute("UPDATE payment_sessions SET status='CANCELLED' WHERE user_id=? AND status='ACTIVE'",(uid,))
        sid=new_session_id(); created=now_iso(); expires=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()
        cur.execute("""INSERT INTO payment_sessions(session_id,user_id,amount,payment_method,gateway_url,status,created_at,expires_at,message_id)\n                       VALUES(?,?,?,?,?,?,?,?,?)""",(sid,uid,float(amount),method,gateway_url or '',"ACTIVE",created,expires,message_id))
        con.commit(); return sid,expires
    except Exception:
        con.rollback(); raise
    finally:
        con.close()

def session_row(sid:str):
    con=db(); row=con.execute("SELECT id,session_id,user_id,amount,payment_method,gateway_url,status,created_at,expires_at,transaction_id,submitted_at,message_id FROM payment_sessions WHERE session_id=?",(sid,)).fetchone(); con.close(); return row

def set_session_message_id(sid:str, message_id:int):
    con=db(); con.execute("UPDATE payment_sessions SET message_id=? WHERE session_id=?",(message_id,sid)); con.commit(); con.close()

def balance_operation(uid:int, field:str, amount:Decimal, op:str, admin_id:int, reference=None):
    allowed={"main_balance","deposit_balance","bonus_balance","referral_balance","task_balance"}
    if field not in allowed: raise ValueError("Invalid balance field")
    if amount <= 0: raise ValueError("Amount must be positive")
    reference = reference or f"ADMIN-{admin_id}-{uuid.uuid4().hex}"
    con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
    try:
        row=cur.execute(f"SELECT {field} FROM users WHERE user_id=?",(uid,)).fetchone()
        if not row: raise ValueError("User not found")
        before=Decimal(str(row[0] or 0))
        if op=="remove" and before < amount: raise ValueError("Insufficient balance")
        after=before+amount if op=="add" else before-amount
        cur.execute(f"UPDATE users SET {field}=? WHERE user_id=?",(float(after),uid))
        if cur.rowcount!=1: raise ValueError("Balance update failed")
        cur.execute("""INSERT INTO balance_ledger(user_id,field,operation,amount,balance_before,balance_after,admin_id,reference,created_at)\n                       VALUES(?,?,?,?,?,?,?,?,?)""",(uid,field,op,float(amount),float(before),float(after),admin_id,reference,now_iso()))
        con.commit(); return before,after
    except Exception:
        con.rollback(); raise
    finally: con.close()

def user_control_text(uid:int):
    con=db(); cur=con.cursor()
    r=cur.execute("SELECT * FROM users WHERE user_id=?",(uid,)).fetchone()
    if not r: con.close(); return None,None
    # Existing users schema: user_id,name,username,main,deposit,bonus,referral,total,created,referrer,task,refcount,completed,banned,suspended
    total_dep=cur.execute("SELECT COALESCE(SUM(amount),0) FROM deposits WHERE user_id=? AND status IN ('Approved','Success')",(uid,)).fetchone()[0]
    plans=[]
    for pid,name,amount,activated,expires,last_claim,active in cur.execute("SELECT id,plan,amount,activated_at,expires_at,last_claim_date,active FROM plans WHERE user_id=? AND active=1 ORDER BY id DESC",(uid,)).fetchall():
        exp=utc_dt(expires)
        if exp>datetime.now(timezone.utc):
            remaining=max(0, int((exp-datetime.now(timezone.utc)).total_seconds()//86400))
            plans.append(f"💎 {name} — {money(amount)}৳ — {remaining} day(s) left")
    con.close()
    active_plans="\n".join(plans) if plans else "<b>কোনো active plan নেই।</b>"
    text=(f"<b>👤 USER CONTROL PANEL</b>\n━━━━━━━━━━━━━━━━━━\n"
          f"<b>👤 Name:</b> <code>{escape(str(r[1] or 'Not Set'))}</code>\n<b>🔗 Username:</b> <code>@{escape(str(r[2])) if r[2] else 'Not Set'}</code>\n<b>🆔 Telegram ID:</b> <code>{uid}</code>\n\n"
          f"<b>💰 BALANCE INFORMATION</b>\n━━━━━━━━━━━━━━━━━━\n"
          f"💰 মোট ব্যালেন্স: <code>{money(r[3])}৳</code>\n📥 ডিপোজিট ব্যালেন্স: <code>{money(r[4])}৳</code>\n🏦 টোটাল ডিপোজিট: <code>{money(total_dep)}৳</code>\n"
          f"💵 রেফার ইনকাম: <code>{money(r[6])}৳</code>\n🎁 বোনাস ব্যালেন্স: <code>{money(r[5])}৳</code>\n👨‍💻 টাস্ক ব্যালেন্স: <code>{money(r[10] if len(r)>10 else 0)}৳</code>\n\n"
          f"🎯 মোট রেফার: <code>{r[11] if len(r)>11 else 0} জন</code>\n📅 Join Time: <code>{escape(str(r[8] or 'Not Set'))}</code>\n\n"
          f"👑 <b>Active VIP/Plans</b>\n{active_plans}\n\n"
          f"🚫 Ban Status: <code>{'BANNED' if r[13] else 'ACTIVE'}</code>\n⏸ Suspend Status: <code>{'SUSPENDED' if r[14] else 'ACTIVE'}</code>")
    return text,r

def user_control_kb(uid:int,r):
    banned=bool(r[13]); suspended=bool(r[14])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Balance",callback_data=f"x:uc:amount:{uid}:main_balance:add"),InlineKeyboardButton(text="➖ Remove Balance",callback_data=f"x:uc:amount:{uid}:main_balance:remove")],
        [InlineKeyboardButton(text="💵 Referral Commission",callback_data=f"x:uc:field:{uid}:referral_balance")],
        [InlineKeyboardButton(text="🎁 Bonus Balance",callback_data=f"x:uc:field:{uid}:bonus_balance"),InlineKeyboardButton(text="📥 Deposit Balance",callback_data=f"x:uc:field:{uid}:deposit_balance")],
        [InlineKeyboardButton(text="👨‍💻 Task Balance",callback_data=f"x:uc:field:{uid}:task_balance"),InlineKeyboardButton(text="🎯 Referral Count",callback_data=f"x:uc:refcount:{uid}")],
        [InlineKeyboardButton(text="💬 User Message Personal",callback_data=f"x:uc:message:{uid}")],
        [InlineKeyboardButton(text="🚫 Unban" if banned else "🚫 Ban",callback_data=f"x:uc:ban:{uid}:{0 if banned else 1}"),InlineKeyboardButton(text="▶️ Unsuspend" if suspended else "⏸ Suspend",callback_data=f"x:uc:sus:{uid}:{0 if suspended else 1}")],
        [InlineKeyboardButton(text="👑 Plan Control",callback_data=f"x:uc:plans:{uid}")],
        [InlineKeyboardButton(text="🔄 Refresh",callback_data=f"x:uc:refresh:{uid}"),InlineKeyboardButton(text="⬅️ Back",callback_data="x:user")]
    ])

async def show_user_control(target_message,uid:int,edit=False):
    con=db(); expire_user_plans(uid,con); con.commit(); con.close()
    text,r=user_control_text(uid)
    if not r: return False
    kb=user_control_kb(uid,r)
    if edit:
        try: await target_message.edit_text(text,reply_markup=kb)
        except TelegramBadRequest: pass
    else:
        await target_message.answer(text,reply_markup=kb)
    return True

# =========================
# USER COMMANDS & HANDLERS
# =========================
@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    
    args = message.text.split()
    ref_id = 0
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            ref_id = int(args[1].split("_")[1])
        except ValueError:
            ref_id = 0

    existing = user_row(uid)
    was_new = existing is None
    user = get_user(message, referrer_id=ref_id)
    if was_new and ref_id and ref_id != uid:
        bonus = Decimal(getset("bonus_amount","0") or "0") if getset("referral_enabled","0") == "1" and getset("bonus_enabled","0") == "1" else Decimal("0")
        ref_row=user_row(ref_id)
        ref_name=(ref_row[1] if ref_row else "Unknown")
        ref_username=(ref_row[2] if ref_row else "")
        await send_history_event("REFERRAL_SIGNUP", actor_id=uid, user_id=uid, reference=f"REF-{uid}",
                                 details=f"New user: {message.from_user.full_name} (@{message.from_user.username or '—'}); User ID: {uid}; Referrer: {ref_name} (@{ref_username or '—'}), ID {ref_id}; Referral time: {now_iso()}; Referral bonus paid to referrer: {money(bonus)}৳; Recipient: {ref_id}; Device model: unavailable from Telegram Bot API")
        if bonus > 0:
            try:
                await send_template(ref_id,"referral_message","<b>🎉 আপনি একজন নতুন সদস্য রেফার করে {amount}৳ Referral Bonus পেয়েছেন।</b>",amount=money(bonus))
            except Exception:
                pass

    if not await check_force_join(uid):
        await force_join_prompt(message)
        return

    await message.answer(
        getset("welcome_message", "<b>🚀 NIKAN EARN</b>\n\n<b>স্বাগতম! নিচের মেনু থেকে একটি অপশন নির্বাচন করুন।</b>"),
        reply_markup=main_keyboard(uid)
    )

@dp.callback_query(F.data == "check_force_join")
async def verify_force_join(call: CallbackQuery):
    uid = call.from_user.id
    if await check_force_join(uid):
        await call.message.delete()
        await call.message.answer(
            "<b>✅ ভেরিফিকেশন সফল হয়েছে!</b>\n\n<b>নিচের মেনু থেকে আপনার পছন্দমতো অপশন বেছে নিন।</b>",
            reply_markup=main_keyboard(uid)
        )
    else:
        await call.answer("❌ আপনি এখনো চ্যানেলে জয়েন করেননি! দয়া করে জয়েন করুন।", show_alert=True)
        return
    await call.answer()

@dp.message(Command("menu"))
async def menu(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    if not await check_force_join(uid):
        await force_join_prompt(message)
        return
    await message.answer("<b>🏠 Main Menu</b>\n<b>নিচের মেনু থেকে একটি অপশন নির্বাচন করুন।</b>", reply_markup=main_keyboard(uid))

@dp.message(Command("help"))
async def help_command(message: Message):
    await show_help(message)

@dp.message(F.text == "❌ Cancel")
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    await message.answer("<b>❌ বর্তমান প্রক্রিয়াটি বাতিল করা হয়েছে।</b>", reply_markup=main_keyboard(uid))

# =========================
# DEPOSIT
# =========================
@dp.message(F.text == "🔐 ফান্ড ডিপোজিট")
async def deposit_menu(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    if not await check_force_join(uid):
        await force_join_prompt(message)
        return
    if getset("fund_enabled") != "1":
        await message.answer("<b>⛔ বর্তমানে ডিপোজিট সিস্টেম সাময়িকভাবে বন্ধ আছে।</b>")
        return
    methods = payment_methods("deposit")
    buttons = []
    for name, logo, number, gateway, manual in methods:
        if name.lower() == "binance":
            cb = "dep_binance"
        else:
            cfg = get_payment_method_config(name, "deposit")
            if not cfg:
                continue
            # A local method is visible only when at least one deposit route is ON.
            if not (int(cfg[5]) and bool(cfg[3])) and not int(cfg[4]):
                continue
            cb = f"dep_method:{name}"
        buttons.append(InlineKeyboardButton(text=f"{logo} {name}", callback_data=cb))
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    if not rows:
        await message.answer("<b>⛔ কোনো Deposit Method বর্তমানে চালু নেই।</b>")
        return
    await message.answer(
        "<b>🔐 ফান্ড ডিপোজিট</b>\n━━━━━━━━━━━━━━━━━━\n"
        "<b>নিচের অপশন থেকে একটি Payment Method নির্বাচন করুন।</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )

@dp.callback_query(F.data.startswith("dep_method:"))
async def dep_dynamic_method(call: CallbackQuery, state: FSMContext):
    if not callback_once(f"dep_dynamic:{call.from_user.id}:{call.data}", ttl=3):
        return await call.answer()
    method = call.data.split(":", 1)[1]
    cfg = get_payment_method_config(method, "deposit")
    if not cfg:
        return await call.answer("এই payment method বর্তমানে বন্ধ আছে।", show_alert=True)
    number = cfg[2] or "Not set"
    gateway = cfg[3] or ""
    manual = bool(cfg[4])
    gateway_on = bool(cfg[5] and gateway)
    if not gateway_on and not manual:
        return await call.answer("❌ এই Method-এর Manual ও Payment Gateway দুটোই বন্ধ।", show_alert=True)
    await state.update_data(method=method)
    await state.set_state(DepositState.amount)
    lines=[
        f"<b>{cfg[1]} {method} Deposit</b>",
        "",
        "<b>📊 ডিপোজিট লিমিট সেটিংস অনুযায়ী প্রযোজ্য হবে।</b>",
        f"<b>💰 সর্বনিম্ন: {getset('min_dep','50')}৳</b>",
        f"<b>💰 সর্বোচ্চ: {getset('max_dep','10000')}৳</b>",
        ""
    ]
    if gateway_on:
        lines.append("<b>🌐 Payment Gateway: 🟢 ON</b>")
    if manual:
        lines.append(f"<b>📲 Manual Deposit: 🟢 ON</b>\n<b>💳 Number: <code>{escape(str(number))}</code></b>")
    lines += ["", "<b>👉 কত টাকা ডিপোজিট করতে চান? সংখ্যায় লিখুন।</b>"]
    await call.message.answer("\n".join(lines))
    await call.answer()

@dp.callback_query(F.data.in_(["dep_bkash", "dep_nagad"]))
async def dep_local_method(call: CallbackQuery, state: FSMContext):
    if not callback_once(f"dep_meth:{call.from_user.id}:{call.data}"):
        await call.answer()
        return
    method = "bKash" if call.data == "dep_bkash" else "Nagad"
    await state.update_data(method=method)
    await state.set_state(DepositState.amount)
    await call.message.answer(
        f"<b>💳 {method} Deposit</b>\n\n"
        "<b>📊 ডিপোজিট লিমিট: 0/3</b>\n"
        "<b>💰 সর্বনিম্ন: 50৳</b>\n"
        "<b>💰 সর্বোচ্চ: 10,000৳</b>\n\n"
        "<b>👉 কত টাকা ডিপোজিট করতে চান? সংখ্যায় লিখুন।</b>",
        reply_markup=cancel_keyboard()
    )
    await call.answer()

@dp.callback_query(F.data == "dep_binance")
async def dep_binance(call: CallbackQuery, state: FSMContext):
    if not callback_once(f"dep_binance:{call.from_user.id}"):
        await call.answer()
        return
    await state.update_data(method="Binance")
    await state.set_state(DepositState.amount)
    await call.message.answer(
        "<b>🟡 Binance — USDT Deposit</b>\n\n"
        "<b>💵 সর্বনিম্ন: $1</b>\n"
        "<b>💵 সর্বোচ্চ: $50</b>\n\n"
        "<b>👉 কত USDT ডিপোজিট করবেন? লিখুন।</b>",
        reply_markup=cancel_keyboard()
    )
    await call.answer()

@dp.message(DepositState.amount)
async def dep_amount_router(message: Message, state: FSMContext):
    data = await state.get_data()
    method = data.get("method")
    if method == "Binance":
        await dep_binance_amount(message, state)
    else:
        await dep_local_amount(message, state)

async def dep_local_amount(message: Message, state: FSMContext):
    try:
        amount = Decimal(message.text.strip())
    except (InvalidOperation, AttributeError):
        await message.answer(getset("invalid_number_message", "<b>❌ সঠিক পরিমাণ লিখুন।</b>")); return
    min_dep=Decimal(getset("min_dep","50")); max_dep=Decimal(getset("max_dep","10000"))
    if amount<=0 or amount<min_dep or amount>max_dep:
        await message.answer(f"<b>⚠️ ডিপোজিটের পরিমাণ {money(min_dep)}৳ থেকে {money(max_dep)}৳ এর মধ্যে হতে হবে।</b>"); return
    data=await state.get_data(); method=data.get("method"); cfg=get_payment_method_config(method,"deposit")
    if not cfg:
        await state.clear(); return await message.answer("<b>⛔ এই Deposit Method বর্তমানে বন্ধ আছে।</b>",reply_markup=main_keyboard(message.from_user.id))
    number=str(cfg[2] or "")
    gateway=str(cfg[3] or "")
    manual=bool(cfg[4]); gateway_on=bool(cfg[5])
    if not gateway_on and not manual:
        await state.clear(); return await message.answer("<b>⛔ এই Method-এর Manual Deposit এবং Payment Gateway দুটোই বর্তমানে OFF।</b>",reply_markup=main_keyboard(message.from_user.id))
    # Create one persistent session. The session remains active until TxID submission/cancel/expiry.
    sid,expires=create_payment_session(message.from_user.id,amount,method,gateway if gateway_on else "")
    payment_url=build_payment_url(gateway,amount,message.from_user.id,method,sid,sid) if gateway_on and gateway else ""
    rows=[]
    if payment_url:
        rows.append([InlineKeyboardButton(text=f"🌐 {cfg[1]} Payment",url=payment_url)])
    if manual and number:
        rows.append([InlineKeyboardButton(text=f"📲 Manual {method}: {number}",callback_data=f"manualinfo:{sid}")])
    rows.append([InlineKeyboardButton(text="🧾 আমি পেমেন্ট করেছি",callback_data=f"paydone:{sid}")])
    rows.append([InlineKeyboardButton(text="❌ Cancel",callback_data=f"paycancel:{sid}")])
    await state.clear()
    pay_lines=[
        f"<b>💳 {method} PAYMENT</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"<b>💰 ডিপোজিট এমাউন্ট: {money(amount)}৳</b>",
        ""
    ]
    if gateway_on and payment_url:
        pay_lines += ["<b>🌐 Payment Gateway চালু আছে।</b>","<b>Payment Gateway-তে গিয়ে আপনার পেমেন্ট সম্পন্ন করুন।</b>",""]
    if manual and number:
        pay_lines += [f"<b>📲 Manual Deposit Number:</b> <code>{escape(number)}</code>","<b>উক্ত নম্বরে Send Money করার পর নিচের ‘আমি পেমেন্ট করেছি’ চাপুন।</b>",""]
    pay_lines += ["<b>পেমেন্ট সম্পন্ন হওয়ার পর 🧾 আমি পেমেন্ট করেছি চাপুন।</b>",f"<b>🆔 Session: <code>{sid}</code></b>"]
    msg=await message.answer("\n".join(pay_lines),reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    set_session_message_id(sid,msg.message_id)


async def dep_binance_amount(message: Message, state: FSMContext):
    try:
        amount = Decimal(message.text.strip())
    except (InvalidOperation, AttributeError):
        await message.answer("<b>❌ সঠিক USDT পরিমাণ লিখুন।</b>")
        return

    if amount < 1 or amount > 50:
        await message.answer("<b>⚠️ USDT পরিমাণ $1 থেকে $50 এর মধ্যে হতে হবে।</b>")
        return

    await state.update_data(usdt=amount)
    await state.set_state(DepositState.txid)

    bdt = amount * USDT_RATE_BDT
    await message.answer(
        "<b>🟡 USDT — BEP20 ডিপোজিট</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"<b>💱 ডিপোজিট রেট: 1 USDT = {money(USDT_RATE_BDT)}৳</b>\n"
        f"<b>💰 আপনার পরিমাণ: {money(amount)} USDT</b>\n"
        f"<b>💵 ব্যালেন্সে যোগ হবে: {money(bdt)}৳</b>\n\n"
        "<b>📌 BEP20 / BSC নেটওয়ার্ক ব্যবহার করে নিচের ঠিকানায় USDT পাঠান:</b>\n\n"
        f"<code>{BINANCE_DEPOSIT_ADDRESS}</code>\n\n"
        "<b>📝 পেমেন্ট করার পর TxID / Transaction Hash পাঠান।</b>",
        reply_markup=cancel_keyboard()
    )

@dp.message(DepositState.txid)
async def dep_binance_txid(message: Message, state: FSMContext):
    txid=normalize_txid(message.text)
    data=await state.get_data()
    sid=data.get("payment_session_id")
    # Local/gateway session accepts a normalized transaction/reference ID.
    if sid:
        if len(txid)<3 or len(txid)>128 or not re.fullmatch(r"[a-z0-9._:/-]+",txid):
            return await message.answer("<b>❌ Transaction ID-এর format সঠিক নয়।</b>")
        con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
        try:
            sess=cur.execute("SELECT id,user_id,amount,payment_method,status,expires_at FROM payment_sessions WHERE session_id=?",(sid,)).fetchone()
            if not sess or int(sess[1])!=message.from_user.id or sess[4]!="ACTIVE":
                con.rollback(); con.close(); await state.clear(); return await message.answer("<b>❌ এই সেশনটি বর্তমানে উপলব্ধ নেই।</b>",reply_markup=main_keyboard(message.from_user.id))
            if datetime.now(timezone.utc)>=utc_dt(sess[5]):
                cur.execute("UPDATE payment_sessions SET status='EXPIRED' WHERE session_id=? AND status='ACTIVE'",(sid,)); con.commit(); con.close(); await state.clear(); return await message.answer("<b>❌ এই সেশনের মেয়াদ শেষ হয়ে গেছে। নতুন Deposit Request তৈরি করুন।</b>",reply_markup=main_keyboard(message.from_user.id))
            old=cur.execute("SELECT id FROM deposits WHERE lower(trim(txid))=? LIMIT 1",(txid,)).fetchone()
            if old:
                cur.execute("UPDATE payment_sessions SET status='CANCELLED',transaction_id=?,submitted_at=? WHERE session_id=? AND status='ACTIVE'",(txid,now_iso(),sid)); con.commit(); con.close(); await state.clear()
                return await message.answer("<b>❌ এই Transaction ID ইতিমধ্যে ব্যবহার করা হয়েছে।</b>\n<b>বর্তমান Deposit Session বাতিল করা হয়েছে।</b>",reply_markup=main_keyboard(message.from_user.id))
            created=now_iso()
            cur.execute("INSERT INTO deposits(user_id,method,amount,txid,order_no,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(message.from_user.id,sess[3],sess[2],txid,sid,"Pending",created,created))
            cur.execute("UPDATE payment_sessions SET status='PENDING',transaction_id=?,submitted_at=? WHERE session_id=? AND status='ACTIVE'",(txid,created,sid))
            if cur.rowcount!=1: raise ValueError("session closed")
            con.commit()
        except sqlite3.IntegrityError:
            con.rollback(); con.close(); await state.clear(); return await message.answer("<b>❌ এই Transaction ID ইতিমধ্যে ব্যবহার করা হয়েছে।</b>\n<b>বর্তমান Deposit Session বাতিল করা হয়েছে।</b>",reply_markup=main_keyboard(message.from_user.id))
        except ValueError:
            con.rollback(); con.close(); await state.clear(); return await message.answer("<b>❌ এই সেশনটি বর্তমানে উপলব্ধ নেই।</b>",reply_markup=main_keyboard(message.from_user.id))
        except Exception:
            con.rollback(); con.close(); raise
        finally:
            try: con.close()
            except Exception: pass
        await state.clear(); await message.answer("<b>⏳ আপনার Transaction ID যাচাইয়ের জন্য পাঠানো হয়েছে।</b>\n<b>সঠিক তথ্য থাকলে খুব দ্রুত আপনার ডিপোজিট ব্যালেন্সে যোগ হয়ে যাবে। অনুগ্রহ করে অপেক্ষা করুন...</b>",reply_markup=main_keyboard(message.from_user.id))
        await send_admin_deposit(message.from_user,sess[3],Decimal(str(sess[2])),txid,sid); return
    # Binance direct flow remains compatible with the existing amount -> TxID FSM.
    if not re.fullmatch(r"0x[a-fA-F0-9]{64}",txid):
        return await message.answer("<b>❌ TxID সঠিক নয়।</b>\n<b>0x দিয়ে শুরু হওয়া 64-hex-character Transaction Hash পাঠান।</b>")
    usdt=Decimal(str(data.get("usdt",0))); bdt=usdt*USDT_RATE_BDT; sid=new_session_id(); created=now_iso(); expires=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()
    con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
    try:
        old=cur.execute("SELECT id FROM deposits WHERE lower(trim(txid))=? LIMIT 1",(txid,)).fetchone()
        if old:
            con.rollback(); con.close(); await state.clear(); return await message.answer("<b>❌ এই Transaction ID ইতিমধ্যে ব্যবহার করা হয়েছে।</b>",reply_markup=main_keyboard(message.from_user.id))
        cur.execute("INSERT INTO payment_sessions(session_id,user_id,amount,payment_method,gateway_url,status,created_at,expires_at,transaction_id,submitted_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(sid,message.from_user.id,float(bdt),"Binance","","PENDING",created,expires,txid,created))
        cur.execute("INSERT INTO deposits(user_id,method,amount,txid,order_no,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(message.from_user.id,"Binance",float(bdt),txid,sid,"Pending",created,created)); con.commit()
    except sqlite3.IntegrityError:
        con.rollback(); con.close(); await state.clear(); return await message.answer("<b>❌ এই Transaction ID ইতিমধ্যে ব্যবহার করা হয়েছে।</b>",reply_markup=main_keyboard(message.from_user.id))
    finally:
        try: con.close()
        except Exception: pass
    await state.clear(); await message.answer("<b>⏳ আপনার Transaction ID যাচাইয়ের জন্য পাঠানো হয়েছে।</b>\n<b>সঠিক তথ্য থাকলে খুব দ্রুত আপনার ডিপোজিট ব্যালেন্সে যোগ হয়ে যাবে। অনুগ্রহ করে অপেক্ষা করুন...</b>",reply_markup=main_keyboard(message.from_user.id)); await send_admin_deposit(message.from_user,"Binance",bdt,txid,sid)

# Payment session callbacks
@dp.callback_query(F.data.startswith("manualinfo:"))
async def manual_payment_info(call: CallbackQuery):
    sid=call.data.split(":",1)[1]
    row=session_row(sid)
    if not row or int(row[2])!=call.from_user.id or row[6]!="ACTIVE":
        return await call.answer("❌ এই সেশনটি বর্তমানে উপলব্ধ নেই।",show_alert=True)
    cfg=get_payment_method_config(row[4],"deposit")
    if not cfg or not int(cfg[4]):
        return await call.answer("❌ Manual Deposit বর্তমানে OFF।",show_alert=True)
    number=str(cfg[2] or "Not set")
    await call.answer(f"📲 {row[4]} Manual Number: {number}",show_alert=True)

@dp.callback_query(F.data.startswith("paydone:"))
async def payment_done(call: CallbackQuery,state:FSMContext):
    if not callback_once(f"paydone:{call.from_user.id}:{call.data}",ttl=5): return await call.answer()
    sid=call.data.split(":",1)[1]; row=session_row(sid)
    if not row or int(row[2])!=call.from_user.id: return await call.answer("❌ এই সেশনটি আপনার নয়।",show_alert=True)
    status=row[6]; exp=utc_dt(row[8])
    if status=="ACTIVE" and datetime.now(timezone.utc)>=exp:
        con=db(); con.execute("UPDATE payment_sessions SET status='EXPIRED' WHERE session_id=? AND status='ACTIVE'",(sid,)); con.commit(); con.close(); status="EXPIRED"
    if status!="ACTIVE": return await call.answer("❌ এই সেশনটি বর্তমানে উপলব্ধ নেই।",show_alert=True)
    await state.update_data(payment_session_id=sid)
    await state.set_state(DepositState.txid)
    await call.message.answer("<b>🧾 আপনার Transaction ID পাঠান।</b>\n<b>একই Transaction ID দ্বিতীয়বার ব্যবহার করা যাবে না।</b>",reply_markup=cancel_keyboard())
    await call.answer()

@dp.callback_query(F.data.startswith("paycancel:"))
async def payment_cancel(call: CallbackQuery,state:FSMContext):
    if not callback_once(f"paycancel:{call.from_user.id}:{call.data}",ttl=5): return await call.answer()
    sid=call.data.split(":",1)[1]; con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
    row=cur.execute("SELECT user_id,status FROM payment_sessions WHERE session_id=?",(sid,)).fetchone()
    if not row or int(row[0])!=call.from_user.id:
        con.rollback(); con.close(); return await call.answer("❌ Invalid session.",show_alert=True)
    changed=cur.execute("UPDATE payment_sessions SET status='CANCELLED' WHERE session_id=? AND status='ACTIVE'",(sid,)).rowcount==1
    if changed: con.commit()
    else: con.rollback()
    con.close(); await state.clear()
    if changed:
        try: await call.message.edit_reply_markup(reply_markup=None)
        except Exception: pass
        await call.message.answer("<b>❌ বর্তমান Deposit Session বাতিল করা হয়েছে।</b>",reply_markup=main_keyboard(call.from_user.id))
        await call.answer()
    else: await call.answer("❌ এই সেশনটি বর্তমানে উপলব্ধ নেই।",show_alert=True)


async def get_admin_ids(permission=None):
    con = db()
    rows = con.execute("SELECT user_id,role FROM admins").fetchall()
    con.close()
    ids = {ADMIN_ID}
    for uid, r in rows:
        if permission is None or r in ("owner","full",permission):
            ids.add(uid)
    return list(ids)

async def send_admin_deposit(user, method, amount, txid, oid):
    admins = await get_admin_ids("dep")
    username = f"@{user.username}" if user.username else "—"
    text = (
        "<b>📥 NEW DEPOSIT REQUEST</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"<b>👤 নাম:</b> <code>{user.full_name}</code>\n"
        f"<b>🔗 Username:</b> <code>{username}</code>\n"
        f"<b>🆔 User ID:</b> <code>{user.id}</code>\n"
        f"<b>💳 Method:</b> <code>{method}</code>\n"
        f"<b>💰 Amount:</b> <code>{money(amount)}৳</code>\n"
        f"<b>📝 TxID:</b> <code>{txid or 'Manual/Not supplied'}</code>\n"
        f"<b>🆔 Order No:</b> <code>{oid}</code>\n"
        "<b>📌 Status: Pending</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Processing", callback_data=f"adm_dep_proc:{oid}")],
        [InlineKeyboardButton(text="✅ Approve", callback_data=f"adm_dep_ok:{oid}"),
         InlineKeyboardButton(text="❌ Reject", callback_data=f"adm_dep_no:{oid}")]
    ])
    for aid in admins:
        try:
            await bot.send_message(aid, text, reply_markup=kb)
        except Exception:
            pass

# =========================
# ACCOUNT & WITHDRAW
# =========================
@dp.message(F.text == "👤 একাউন্ট")
async def account(message: Message):
    uid = message.from_user.id
    if not await check_force_join(uid):
        await force_join_prompt(message)
        return
    row = get_user(message)
    expire_user_plans(uid)
    uid, name, username, main, deposit, bonus, referral, total, created, referrer_id = row[:10]

    con = db()
    cur = con.cursor()
    cur.execute("""
        SELECT plan, expires_at FROM plans
        WHERE user_id=? AND active=1 ORDER BY expires_at
    """, (uid,))
    active = cur.fetchall()
    con.close()

    vip1, vip2 = "সক্রিয় নয়", "সক্রিয় নয়"
    now = datetime.now(timezone.utc)

    for plan, expires in active:
        try:
            days = max(0, (datetime.fromisoformat(expires) - now).days)
        except Exception:
            days = 0
        if plan == "VIP1":
            vip1 = f"{days} দিন"
        if plan == "VIP2":
            vip2 = f"{days} দিন"

    await message.answer(
        "<b>👤 আমার অ্যাকাউন্টের তথ্য</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>👤 ব্যবহারকারীর নাম: {name}</b>\n"
        f"<b>🔗 ইউজারনেম: @{username if username else 'নেই'}</b>\n"
        f"<b>🆔 ইউজার আইডি: {uid}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>💰 BALANCE DETAILS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>💵 মোট ব্যালেন্স: {money(main)}৳</b>\n"
        f"<b>📥 ডিপোজিট ব্যালেন্স: {money(deposit)}৳</b>\n"
        f"<b>🎁 ডিপোজিট বোনাস: {money(bonus)}৳</b>\n"
        f"<b>🫂 রেফার ব্যালেন্স: {money(referral)}৳</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>👑 ACCOUNT STATUS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>⏳ Plan এর মেয়াদ:</b>\n"
        f"<b>• VIP 1 — {vip1}</b>\n"
        f"<b>• VIP 2 — {vip2}</b>\n"
        "<b>🚫 নিষিদ্ধ: না</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>✨ আপনার অ্যাকাউন্টের সকল তথ্য এখানে দেখানো হয়েছে।</b>"
    )

@dp.message(F.text == "💸 Withdraw")
async def withdraw_menu(message: Message, state: FSMContext):
    await state.clear()
    uid=message.from_user.id
    if not await check_force_join(uid):
        await force_join_prompt(message); return
    if getset("withdraw_enabled")!="1":
        await message.answer("<b>⛔ বর্তমানে Withdraw System সাময়িকভাবে বন্ধ আছে।</b>"); return
    methods=payment_methods("withdraw")
    buttons=[InlineKeyboardButton(text=f"{logo} {name}",callback_data=f"wd_method:{name}") for name,logo,number,gateway,manual in methods]
    rows=[buttons[i:i+2] for i in range(0,len(buttons),2)]
    if not rows:
        return await message.answer("<b>⛔ কোনো Withdraw Method বর্তমানে চালু নেই।</b>")
    await message.answer("<b>💸 Withdraw</b>\n\n<b>একটি Payment Method নির্বাচন করুন।</b>",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data.startswith("wd_method:"))
async def wd_dynamic_method(call: CallbackQuery,state:FSMContext):
    if not callback_once(f"wd_dynamic:{call.from_user.id}:{call.data}",ttl=3):
        return await call.answer()
    method=call.data.split(":",1)[1]
    cfg=get_payment_method(method,"withdraw")
    if not cfg: return await call.answer("এই method বন্ধ আছে।",show_alert=True)
    await state.update_data(method=method)
    await state.set_state(WithdrawState.account)
    await call.message.answer(
        f"<b>{cfg[1]} {method}</b>\n\n<b>আপনার সঠিক ১১ ডিজিটের নম্বর/অ্যাকাউন্ট লিখুন।</b>",
        reply_markup=cancel_keyboard())
    await call.answer()

@dp.callback_query(F.data.in_(["wd_bkash", "wd_nagad"]))
async def wd_method(call: CallbackQuery, state: FSMContext):
    if not callback_once(f"wd_meth:{call.from_user.id}:{call.data}"):
        await call.answer()
        return
    method = "bKash" if call.data == "wd_bkash" else "Nagad"
    await state.update_data(method=method)
    await state.set_state(WithdrawState.account)
    await call.message.answer(
        f"<b>📲 {method}</b>\n\n"
        "<b>আপনার সঠিক ১১ ডিজিটের নম্বরটি লিখুন।</b>\n"
        "<b>উদাহরণ: 017XXXXXXXX</b>",
        reply_markup=cancel_keyboard()
    )
    await call.answer()

@dp.message(WithdrawState.account)
async def wd_account(message: Message, state: FSMContext):
    account_no = message.text.strip()
    if not re.fullmatch(r"01[3-9]\d{8}", account_no):
        await message.answer("<b>❌ সঠিক ১১ ডিজিটের মোবাইল নম্বর দিন।</b>")
        return

    await state.update_data(account=account_no)
    await state.set_state(WithdrawState.amount)

    row = get_user(message)
    balance = Decimal(str(row[3]))

    await message.answer(
        f"<b>💰 আপনার বর্তমান ব্যালেন্স: {money(balance)}৳</b>\n\n"
        "<b>📌 উইথড্র সীমা:</b>\n"
        "<b>• সর্বনিম্ন: 100৳</b>\n"
        "<b>• সর্বোচ্চ: 25,000৳</b>\n\n"
        f"<b>📲 নম্বর: {account_no}</b>\n\n"
        "<b>👉 কত টাকা উইথড্র করতে চান? সংখ্যায় লিখুন।</b>",
        reply_markup=cancel_keyboard()
    )

@dp.message(WithdrawState.amount)
async def wd_amount(message: Message, state: FSMContext):
    try:
        amount = Decimal(message.text.strip())
    except (InvalidOperation, AttributeError):
        await message.answer("<b>❌ সঠিক পরিমাণ লিখুন।</b>")
        return

    row = get_user(message)
    balance = Decimal(str(row[3]))

    if amount < 100 or amount > 25000 or amount > balance:
        await message.answer(
            "<b>⚠️ উইথড্র পরিমাণ সঠিক নয়!</b>\n"
            "<b>💰 উইথড্র করার সীমা:</b>\n"
            "<b>• সর্বনিম্ন — 100৳</b>\n"
            "<b>• সর্বোচ্চ — 25,000৳</b>\n"
            f"<b>আপনার বর্তমান ব্যালেন্স {money(balance)}৳</b>\n\n"
            "<b>👉 অনুগ্রহ করে সঠিক পরিমাণ লিখে আবার চেষ্টা করুন।</b>",
            reply_markup=cancel_keyboard()
        )
        return

    data = await state.get_data()
    method, account_no = data["method"], data["account"]

    con = db()
    cur = con.cursor()
    cur.execute(
        "UPDATE users SET main_balance=main_balance-? WHERE user_id=? AND main_balance>=?",
        (float(amount), message.from_user.id, float(amount))
    )
    if cur.rowcount != 1:
        con.rollback()
        con.close()
        await message.answer("<b>❌ ব্যালেন্স পরিবর্তিত হয়েছে। আবার চেষ্টা করুন।</b>")
        return

    cur.execute("""
        INSERT INTO withdrawals(user_id,method,account,amount,status,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?)
    """, (message.from_user.id, method, account_no, float(amount), "Pending", now_iso(), now_iso()))
    wid = cur.lastrowid
    con.commit()
    con.close()
    await send_history_event("WITHDRAW_REQUEST", actor_id=message.from_user.id, user_id=message.from_user.id, reference=str(wid), details=f"Method: {method}; Account: {account_no}; Amount: {money(amount)}৳")

    await state.clear()
    uid = message.from_user.id
    await message.answer(
        f"<b>✅ আপনার 💸 {money(amount)}৳ উইথড্র রিকোয়েস্ট সফলভাবে জমা হয়েছে!</b>\n\n"
        "<b>⏳ প্রসেসিং সময়: Admin review</b>\n"
        "<b>অনুমোদন সম্পন্ন হওয়া পর্যন্ত অপেক্ষা করুন।</b>",
        reply_markup=main_keyboard(uid)
    )

    await send_admin_withdraw(message.from_user, wid, method, account_no, amount)

async def send_admin_withdraw(user, wid, method, account_no, amount):
    username=f"@{user.username}" if user.username else "—"
    text=(
        "<b>📤 NEW WITHDRAW REQUEST</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"<b>👤 নাম:</b> <code>{user.full_name}</code>\n"
        f"<b>🔗 Username:</b> <code>{username}</code>\n"
        f"<b>🆔 User ID:</b> <code>{user.id}</code>\n"
        f"<b>💳 Method:</b> <code>{method}</code>\n"
        f"<b>📲 Account:</b> <code>{account_no}</code>\n"
        f"<b>💰 Amount:</b> <code>{money(amount)}৳</code>\n"
        f"<b>🆔 Request ID:</b> <code>{wid}</code>\n"
        "<b>📌 Status: Pending</b>"
    )
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Processing", callback_data=f"adm_wd_proc:{wid}")],
        [InlineKeyboardButton(text="✅ Approve", callback_data=f"adm_wd_ok:{wid}"),
         InlineKeyboardButton(text="❌ Reject", callback_data=f"adm_wd_no:{wid}")]
    ])
    for aid in await get_admin_ids("wth"):
        try: await bot.send_message(aid,text,reply_markup=kb)
        except Exception: pass

@dp.callback_query(F.data.startswith("adm_wd_proc:"))
async def admin_wd_processing(call: CallbackQuery):
    if not admin_ok(call.from_user.id) or (role(call.from_user.id) not in (None,"owner","full","wth") and call.from_user.id != OWNER_ID):
        return await call.answer("❌ এই অপশনের অনুমতি নেই।", show_alert=True)
    try: wid=int(call.data.split(":",1)[1])
    except ValueError: return await call.answer("❌ Invalid request.", show_alert=True)
    if not atomic_status_change("withdrawals","id",wid,"Processing",("Pending",)):
        return await call.answer("❌ এই রিকোয়েস্টটি অলরেডি প্রসেস করা হয়েছে।", show_alert=True)
    try: await call.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    await call.answer("⚙️ Processing")

# =========================
# REFERRAL, EARNINGS & BONUSES
# =========================
@dp.message(F.text == "👥 Referral")
async def referral(message: Message):
    uid=message.from_user.id
    if not await check_force_join(uid): return await force_join_prompt(message)
    con=db(); row=con.execute("SELECT referral_balance,referral_count FROM users WHERE user_id=?",(uid,)).fetchone(); con.close()
    refbal,refcount=(row if row else (0,0))
    me=await bot.get_me(); link=f"https://t.me/{me.username}?start=ref_{uid}"
    if get_setting_bool("referral_enabled"):
        info=f"<b>🎁 Referral Bonus: {money(getset('referral_bonus','0'))}৳</b>\n"
    else:
        info="<b>ℹ️ Referral Bonus বর্তমানে বন্ধ আছে।</b>\n"
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Share করুন",switch_inline_query=link)],
        [InlineKeyboardButton(text="📋 Rules",callback_data="ref_rules")]
    ])
    await message.answer(
        "<b>👥 Referral Center</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"<b>🔗 Referral Link:</b>\n<code>{link}</code>\n\n"
        f"<b>👥 মোট referrals: {refcount}</b>\n<b>💰 Referral earnings: {money(refbal)}৳</b>\n"
        + info,reply_markup=kb)

@dp.callback_query(F.data == "ref_rules")
async def ref_rules(call: CallbackQuery):
    if not callback_once(f"ref_rules:{call.from_user.id}"):
        await call.answer()
        return
    await call.message.answer(
        "<b>📋 Referral Rules</b>\n\n"
        "<b>রেফার করা ব্যক্তি ডিপোজিট করলে নির্ধারিত নিয়মে Referral Balance-এ কমিশন যোগ হতে পারে।</b>"
    )
    await call.answer()

@dp.message(F.text == "📊 Daily Earnings")
async def daily_earnings(message: Message):
    uid=message.from_user.id
    if not await check_force_join(uid): return await force_join_prompt(message)
    con=db(); expire_user_plans(uid,con); con.commit()
    rows=con.execute("SELECT id,plan,amount,activated_at,expires_at,last_claim_date,COALESCE(daily_rate,?) FROM plans WHERE user_id=? AND active=1 ORDER BY id DESC",(float(DEMO_DAILY_RATE),uid)).fetchall(); con.close()
    now=datetime.now(timezone.utc); lines=["<b>📊 Daily Earnings</b>","━━━━━━━━━━━━━━━━━━"]; valid=[]
    for pid,plan,amount,activated,expires,last_claim,rate in rows:
        exp=utc_dt(expires)
        if now>=exp: continue
        daily=Decimal(str(amount))*Decimal(str(rate)); valid.append((pid,plan,amount,daily,last_claim))
        lines.append(f"<b>💎 {plan} — {money(amount)}৳</b>\n<b>📅 Expires: {exp.strftime('%Y-%m-%d %H:%M UTC')}</b>\n<b>💰 Daily Earnings: {money(daily)}৳</b>\n")
    if not valid:
        lines.append("<b>❌ কোনো active plan নেই।</b>"); return await message.answer("\n".join(lines))
    lines.append("<b>🕗 Claim window: 08:00–24:00 UTC</b>")
    await message.answer("\n".join(lines),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🧮 Today Earnings Claim",callback_data="claim_today")]]))

@dp.callback_query(F.data == "claim_today")
async def claim_today(call: CallbackQuery):
    if not callback_once(f"claim_today:{call.from_user.id}:{datetime.now(timezone.utc).date().isoformat()}",ttl=10): return await call.answer("⚠️ ইতিমধ্যে process হয়েছে।",show_alert=True)
    uid=call.from_user.id; now=datetime.now(timezone.utc)
    if now.hour<8: return await call.answer("⏳ Claim window সকাল ৮টা থেকে শুরু হবে।",show_alert=True)
    today=now.date().isoformat(); con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
    try:
        cur.execute("UPDATE plans SET active=0 WHERE user_id=? AND active=1 AND expires_at<=?",(uid,now_iso()))
        rows=cur.execute("SELECT id,plan,amount,last_claim_date,expires_at,COALESCE(daily_rate,?) FROM plans WHERE user_id=? AND active=1",(float(DEMO_DAILY_RATE),uid)).fetchall()
        total=Decimal("0"); claimed=[]
        for pid,plan,amount,last_claim,expires,rate in rows:
            if utc_dt(expires)<=now or last_claim==today: continue
            earning=Decimal(str(amount))*Decimal(str(rate)); total+=earning; claimed.append((pid,plan,earning))
            changed=cur.execute("UPDATE plans SET last_claim_date=? WHERE id=? AND active=1 AND (last_claim_date IS NULL OR last_claim_date<>?)",(today,pid,today)).rowcount
            if changed!=1: continue
            cur.execute("INSERT INTO earnings(user_id,plan_id,amount,claim_date,created_at) VALUES(?,?,?,?,?)",(uid,pid,float(earning),today,now_iso()))
        if total>0: cur.execute("UPDATE users SET main_balance=main_balance+?,total_earnings=total_earnings+? WHERE user_id=?",(float(total),float(total),uid))
        con.commit()
    except Exception:
        con.rollback(); con.close(); raise
    con.close()
    if total<=0: return await call.answer("⚠️ আজকের earnings claim করা হয়েছে অথবা কোনো active plan নেই।",show_alert=True)
    await call.message.answer(f"<b>🎉 Today Earnings Claim Successful</b>\n━━━━━━━━━━━━━━━━━━\n<b>💰 মোট যোগ হয়েছে: {money(total)}৳</b>\n<b>📦 Plans claimed: {len(claimed)}</b>")
    await call.answer("✅ Claim সম্পন্ন হয়েছে।")

@dp.message(F.text == "🎁 Bonus Center")
async def bonus_center(message: Message):
    uid=message.from_user.id
    if not await check_force_join(uid): return await force_join_prompt(message)
    if not get_setting_bool("bonus_enabled",True):
        return await message.answer("<b>🎁 Bonus Center</b>\n\n<b>বর্তমানে কোনো Bonus চালু নেই।</b>")
    con=db(); row=con.execute("SELECT bonus_balance FROM users WHERE user_id=?",(uid,)).fetchone(); con.close()
    bal=row[0] if row else 0
    amount=getset("bonus_amount","5"); expiry=getset("bonus_expiry_days","1")
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎁 Daily Free {amount}৳ Claim",callback_data="bonus_claim")],
        [InlineKeyboardButton(text="📜 Bonus History",callback_data="bonus_history")]
    ])
    await message.answer(
        "<b>🎁 Bonus Center</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"<b>💰 Available Bonus: {money(bal)}৳</b>\n"
        f"<b>🎁 Active Reward: {amount}৳</b>\n"
        f"<b>⏳ Bonus Validity: {expiry} day(s)</b>",
        reply_markup=kb)

@dp.callback_query(F.data == "bonus_claim")
async def bonus_claim(call: CallbackQuery):
    if not callback_once(f"bonus_claim:{call.from_user.id}",ttl=3):
        return await call.answer("Already processing…",show_alert=True)
    if not get_setting_bool("bonus_enabled",True):
        return await call.answer("Bonus বর্তমানে বন্ধ।",show_alert=True)
    uid=call.from_user.id
    amount=Decimal(getset("bonus_amount","5"))
    if amount<=0: return await call.answer("কোনো Bonus চালু নেই।",show_alert=True)
    con=db(); cur=con.cursor()
    days=int(getset("bonus_expiry_days","1") or 1)
    cur.execute("""SELECT 1 FROM bonuses WHERE user_id=? AND type='daily'
                   AND datetime(created_at)>=datetime('now',?)""",(uid,f"-{days} day"))
    if cur.fetchone():
        con.close(); return await call.answer("⚠️ Bonus ইতিমধ্যে নেওয়া হয়েছে।",show_alert=True)
    cur.execute("UPDATE users SET bonus_balance=bonus_balance+? WHERE user_id=?",(float(amount),uid))
    cur.execute("INSERT INTO bonuses(user_id,amount,type,created_at) VALUES(?,?,?,?)",(uid,float(amount),"daily",now_iso()))
    con.commit(); con.close()
    await send_history_event("BONUS_CLAIM", actor_id=uid, user_id=uid, reference=f"BONUS-{uid}", details=f"Daily bonus claimed: {money(amount)}৳")
    await call.message.answer(f"<b>🎁 {money(amount)}৳ Bonus আপনার Bonus Balance-এ যোগ হয়েছে।</b>")
    await call.answer("✅ Bonus claimed!")

@dp.callback_query(F.data == "bonus_history")
async def bonus_history(call: CallbackQuery):
    if not callback_once(f"bonus_history:{call.from_user.id}"):
        await call.answer()
        return
    con = db()
    cur = con.cursor()
    cur.execute("""
        SELECT amount,type,created_at FROM bonuses
        WHERE user_id=? ORDER BY id DESC LIMIT 5
    """, (call.from_user.id,))
    rows = cur.fetchall()
    con.close()

    if not rows:
        text = "<b>📜 Bonus History</b>\n\n<b>কোনো bonus history পাওয়া যায়নি।</b>"
    else:
        text = "<b>📜 Bonus History</b>\n━━━━━━━━━━━━━━━━━━\n"
        for amount, typ, created in rows:
            text += f"<b>🎁 +{money(amount)}৳ — {typ}</b>\n<b>📅 {created[:10]}</b>\n\n"

    await call.message.answer(text)
    await call.answer()

# =========================
# PLANS & PURCHASES
# =========================
def plan_keyboard():
    names=list(get_plans().keys()); buttons=[]
    for i in range(0,len(names),3): buttons.append([InlineKeyboardButton(text=f"💎 {p}",callback_data=f"plan:{p}") for p in names[i:i+3]])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(F.text == "💎 Available Plans")
async def available_plans(message: Message):
    uid=message.from_user.id
    if not await check_force_join(uid): return await force_join_prompt(message)
    expire_user_plans(uid)
    plans=get_plans()
    await message.answer("<b>💎 Available Plans</b>\n━━━━━━━━━━━━━━━━━━\n<b>একটি Plan নির্বাচন করুন।</b>\n<b>📅 প্রতিটি Plan-এর মেয়াদ 4 দিন।</b>",reply_markup=plan_keyboard())

@dp.callback_query(F.data.startswith("plan:"))
async def plan_details(call: CallbackQuery):
    if not callback_once(f"plan_det:{call.from_user.id}:{call.data}"): return await call.answer()
    plan=call.data.split(":",1)[1]; amount,days,emoji,rate=plan_meta(plan)
    if amount<=0: return await call.answer("Plan পাওয়া যায়নি।",show_alert=True)
    daily=amount*rate; total=daily*days
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💸 Plan Buy",callback_data=f"buy:{plan}")],[InlineKeyboardButton(text="⬅️ Plans",callback_data="plans_back")]])
    await call.message.answer(f"<b>💼 {plan} Plan Details</b>\n━━━━━━━━━━━━━━━━━━\n<b>💰 Amount: {money(amount)}৳</b>\n<b>📅 Duration: {days} days</b>\n<b>💰 Daily Earnings: {money(daily)}৳</b>\n<b>📈 Total Earnings: {money(total)}৳</b>",reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data == "plans_back")
async def plans_back(call: CallbackQuery):
    if not callback_once(f"plans_back:{call.from_user.id}"): return await call.answer()
    await call.message.edit_text("<b>💎 Available Plans</b>\n<b>একটি Plan নির্বাচন করুন।</b>",reply_markup=plan_keyboard()); await call.answer()

@dp.callback_query(F.data.startswith("buy:"))
async def buy_plan(call: CallbackQuery):
    uid=call.from_user.id; plan=call.data.split(":",1)[1]
    if not callback_once(f"buy_plan:{uid}:{plan}",ttl=10): return await call.answer("⚠️ এই purchase ইতিমধ্যে process হচ্ছে।",show_alert=True)
    con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
    try:
        expire_user_plans(uid,con)
        row=cur.execute("SELECT amount,days,emoji,COALESCE(daily_rate,?) FROM plan_catalog WHERE name=? AND enabled=1",(float(DEMO_DAILY_RATE),plan)).fetchone()
        if not row:
            fallback=PLANS.get(plan)
            if fallback is None: raise ValueError("Plan পাওয়া যায়নি")
            price=Decimal(str(fallback)); days=PLAN_DAYS; rate=DEMO_DAILY_RATE
        else: price=Decimal(str(row[0])); days=int(row[1]); rate=Decimal(str(row[3]))
        active_count=cur.execute("SELECT COUNT(*) FROM plans WHERE user_id=? AND plan=? AND active=1",(uid,plan)).fetchone()[0]
        if active_count>=2:
            con.rollback(); con.close(); return await call.message.answer(f"<b>⚠️ {plan} Plan-এর সর্বোচ্চ ২টি active instance অনুমোদিত।</b>")
        u=cur.execute("SELECT main_balance,deposit_balance FROM users WHERE user_id=?",(uid,)).fetchone()
        if not u: raise ValueError("User not found")
        main=Decimal(str(u[0] or 0)); deposit=Decimal(str(u[1] or 0)); available=main+deposit
        if available<price:
            con.rollback(); con.close(); need=price-available
            return await call.message.answer(f"<b>❌ আপনার ডিপোজিট ও মেইন ব্যালেন্সে পর্যাপ্ত টাকা নেই।</b>\n\n💰 Plan Price: {money(price)}৳\n💳 Available Balance: {money(available)}৳\n📉 প্রয়োজন আরও: {money(need)}৳")
        # Existing project priority: Main first, then Deposit. This keeps the old spending rule.
        from_main=min(main,price); from_deposit=price-from_main
        cur.execute("UPDATE users SET main_balance=main_balance-?,deposit_balance=deposit_balance-? WHERE user_id=? AND main_balance>=? AND deposit_balance>=?",(float(from_main),float(from_deposit),uid,float(from_main),float(from_deposit)))
        if cur.rowcount!=1: raise ValueError("Balance changed; please retry")
        activated=datetime.now(timezone.utc); expires=activated+timedelta(days=days)
        cur.execute("INSERT INTO plans(user_id,plan,amount,activated_at,expires_at,last_claim_date,active,daily_rate) VALUES(?,?,?,?,?,'',1,?)",(uid,plan,float(price),activated.isoformat(),expires.isoformat(),float(rate)))
        pid=cur.lastrowid
        cur.execute("INSERT INTO balance_ledger(user_id,field,operation,amount,balance_before,balance_after,admin_id,reference,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(uid,"plan_purchase","remove",float(price),float(available),float(available-price),uid,f"PLAN-{pid}",now_iso()))
        con.commit()
    except Exception as e:
        con.rollback(); con.close()
        if str(e)=="Plan পাওয়া যায়নি": return await call.answer("❌ Plan পাওয়া যায়নি।",show_alert=True)
        if str(e)=="User not found": return await call.answer("❌ User account পাওয়া যায়নি।",show_alert=True)
        return await call.answer("❌ Purchase সম্পন্ন করা যায়নি। আবার চেষ্টা করুন।",show_alert=True)
    con.close()
    await send_history_event("PLAN_PURCHASE", actor_id=uid, user_id=uid, reference=f"PLAN-{pid}", details=f"Plan: {plan}; Price: {money(price)}৳; Duration: {days} days; Daily: {money(price*rate)}৳")
    daily=price*rate
    await call.message.answer(f"<b>✅ Plan Successfully Activated!</b>\n━━━━━━━━━━━━━━━━━━\n💎 Plan: <b>{plan}</b>\n💰 Price: <b>{money(price)}৳</b>\n📅 Duration: <b>{days} Days</b>\n⏰ Started: <b>{activated.strftime('%Y-%m-%d %H:%M UTC')}</b>\n⏳ Expires: <b>{expires.strftime('%Y-%m-%d %H:%M UTC')}</b>\n💰 Daily Earnings: <b>{money(daily)}৳</b>")
    await call.answer("✅ Plan activated!")

# =========================
# HISTORY & HELP
# =========================
@dp.message(F.text == "🧾 Transaction History")
async def transaction_history(message: Message):
    uid = message.from_user.id
    if not await check_force_join(uid):
        await force_join_prompt(message)
        return
    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT method,amount,status,order_no,created_at FROM deposits
        WHERE user_id=? ORDER BY id DESC LIMIT 7
    """, (uid,))
    deps = cur.fetchall()

    cur.execute("""
        SELECT method,amount,status,created_at FROM withdrawals
        WHERE user_id=? ORDER BY id DESC LIMIT 7
    """, (uid,))
    wds = cur.fetchall()

    cur.execute("""
        SELECT amount,claim_date,created_at FROM earnings
        WHERE user_id=? ORDER BY id DESC LIMIT 7
    """, (uid,))
    earns = cur.fetchall()
    con.close()

    text = "<b>🧾 Transaction History</b>\n━━━━━━━━━━━━━━━━━━\n\n<b>📥 Deposit History</b>\n"
    if deps:
        for method, amount, status, oid, created in deps:
            text += f"<b>• {method} — {money(amount)}৳ — {status}</b>\n  <b>🆔 {oid}</b>\n"
    else:
        text += "<b>• কোনো রেকর্ড নেই</b>\n"

    text += "\n<b>📤 Withdraw History</b>\n"
    if wds:
        for method, amount, status, created in wds:
            text += f"<b>• {method} — {money(amount)}৳ — {status}</b>\n"
    else:
        text += "<b>• কোনো রেকর্ড নেই</b>\n"

    text += "\n<b>📊 Earnings History</b>\n"
    if earns:
        for amount, claim_date, created in earns:
            text += f"<b>• +{money(amount)}৳ — {claim_date}</b>\n"
    else:
        text += "<b>• কোনো রেকর্ড নেই</b>\n"

    await message.answer(text)

async def show_help(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Support Center", url="https://t.me/Nikan_Support01")],
        [InlineKeyboardButton(text="📢 Official Channel", url="https://t.me/NIKAN_EARN")],
        [InlineKeyboardButton(text="📋 Rules", callback_data="help_rules")]
    ])
    await message.answer(
        "<b>🆘 Help & Support</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "<b>Account Problem</b>\n"
        "<b>Deposit Problem</b>\n"
        "<b>Withdraw Problem</b>",
        reply_markup=kb
    )

@dp.message(F.text == "🆘 Help & Support")
async def help_menu(message: Message):
    await show_help(message)

@dp.callback_query(F.data == "help_rules")
async def help_rules(call: CallbackQuery):
    if not callback_once(f"help_rules:{call.from_user.id}"):
        await call.answer()
        return
    await call.message.answer(
        "<b>🌐 About NIKAN</b>\n\n"
        "<b>NIKAN একটি online earning service demo interface।</b>"
    )
    await call.answer()

# =========================
# ADMIN CALLBACKS & PANEL
# =========================
@dp.callback_query(F.data.startswith("adm_dep_proc:"))
async def admin_dep_processing(call: CallbackQuery):
    if not admin_ok(call.from_user.id) or (role(call.from_user.id) not in (None,"owner","full","dep") and call.from_user.id != OWNER_ID):
        return await call.answer("❌ এই অপশনের অনুমতি নেই।", show_alert=True)
    oid = call.data.split(":",1)[1]
    con=db(); dep=con.execute("SELECT id,status FROM deposits WHERE order_no=?",(oid,)).fetchone(); con.close()
    if not dep:
        return await call.answer("❌ Deposit Request পাওয়া যায়নি।",show_alert=True)
    did,status=dep
    changed=True if status=="Processing" else atomic_status_change("deposits","order_no",oid,"Processing",("Pending",))
    if not changed:
        return await call.answer("❌ এই রিকোয়েস্টটি Processing করা যায়নি।", show_alert=True)
    await send_history_event("DEPOSIT_PROCESSING", actor_id=call.from_user.id, reference=oid, details=f"Deposit moved to Processing")
    try:
        await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Processing",callback_data=f"adm_dep_proc:{oid}")],
            [InlineKeyboardButton(text="✅ Approve",callback_data=f"adm_dep_ok:{oid}"), InlineKeyboardButton(text="❌ Reject",callback_data=f"adm_dep_no:{oid}")]
        ]))
    except Exception:
        pass
    await call.answer("⚙️ Processing")

def deposit_decision(oid:str, decision:str, admin_id:int, reason:str=""):
    con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
    try:
        row=cur.execute("SELECT id,user_id,amount,txid,status,order_no FROM deposits WHERE order_no=?",(str(oid),)).fetchone()
        if not row:
            try:
                row=cur.execute("SELECT id,user_id,amount,txid,status,order_no FROM deposits WHERE id=?",(int(oid),)).fetchone()
            except (TypeError, ValueError):
                row=None
        if not row: raise ValueError("Request not found")
        did,uid,amount,txid,status,real_oid=row
        oid=str(real_oid)
        if decision not in ("approve","reject"): raise ValueError("invalid decision")
        # Pending/Processing can be decided; a rejected request may be corrected to Approved.
        if decision == "approve":
            if status == "Approved": raise ValueError("already processed")
            if status not in ("Pending","Processing","Rejected"): raise ValueError("already processed")
        else:
            if status not in ("Pending","Processing"): raise ValueError("already processed")
        new_status="Approved" if decision=="approve" else "Rejected"
        cur.execute("UPDATE deposits SET status=?,reason=?,updated_at=? WHERE id=?",(new_status,reason or '',now_iso(),did))
        if cur.rowcount!=1: raise ValueError("already processed")
        cur.execute("UPDATE payment_sessions SET status=? WHERE session_id=? AND status IN ('PENDING','ACTIVE','REJECTED')",(new_status.upper(),oid))
        bonus = Decimal("0")
        if decision=="approve":
            # Credit deposit exactly once: only an unapproved -> Approved transition can reach here.
            if status != "Approved":
                cur.execute("UPDATE users SET deposit_balance=deposit_balance+? WHERE user_id=?",(amount,uid))
                cur.execute("""INSERT INTO balance_ledger(user_id,field,operation,amount,balance_before,balance_after,admin_id,reference,created_at)
                             SELECT user_id,'deposit_balance','add',?,deposit_balance-?,deposit_balance,?,?,? FROM users WHERE user_id=?""",
                            (amount,amount,admin_id,f"DEP-{oid}",now_iso(),uid))
                ref=cur.execute("SELECT referrer_id FROM users WHERE user_id=?",(uid,)).fetchone()
                if ref and ref[0] and get_setting_bool("referral_enabled") and Decimal(getset("referral_bonus","0"))>0:
                    bonus=Decimal(getset("referral_bonus","0"))
                    ref_id=int(ref[0])
                    # Deposit referral commission is also idempotent by reference.
                    try:
                        cur.execute("""INSERT INTO balance_ledger(user_id,field,operation,amount,balance_before,balance_after,admin_id,reference,created_at)
                                     SELECT user_id,'referral_balance','add',?,referral_balance,referral_balance+?, ?, ?, ? FROM users WHERE user_id=?""",
                                    (float(bonus),float(bonus),admin_id,f"REFDEP-{oid}",now_iso(),ref_id))
                        cur.execute("UPDATE users SET referral_balance=referral_balance+?,main_balance=main_balance+?,total_earnings=total_earnings+? WHERE user_id=?",
                                    (float(bonus),float(bonus),float(bonus),ref_id))
                    except sqlite3.IntegrityError:
                        bonus=Decimal("0")
        con.commit(); return uid,amount,txid,bonus,status,new_status
    except Exception:
        con.rollback(); raise
    finally: con.close()

@dp.callback_query(F.data.startswith("adm_dep_ok:"))
async def admin_dep_approve(call: CallbackQuery):
    if not admin_ok(call.from_user.id) or (role(call.from_user.id) not in (None,"owner","full","dep") and call.from_user.id!=OWNER_ID): return await call.answer("❌ এই অপশনের অনুমতি নেই।",show_alert=True)
    oid=call.data.split(":",1)[1]
    try: uid,amount,txid,ref_bonus,old_status,new_status=deposit_decision(oid,"approve",call.from_user.id)
    except ValueError as e:
        msg = str(e)
        if "already processed" in msg:
            return await call.answer("❌ এই রিকোয়েস্টটি ইতিমধ্যে Approved হয়েছে।",show_alert=True)
        if "Request not found" in msg:
            return await call.answer("❌ Deposit Request পাওয়া যায়নি।",show_alert=True)
        return await call.answer(f"❌ {escape(msg)}",show_alert=True)
    except Exception: return await call.answer("❌ Database operation failed.",show_alert=True)
    try: await send_template(uid,"deposit_approved_message","<b>🎉 Deposit Successful!</b>\n<b>আপনার {amount}৳ Deposit সফল হয়েছে।</b>",amount=money(amount),txid=txid or "Manual",order=oid)
    except Exception: pass
    await send_history_event("DEPOSIT_APPROVED", actor_id=call.from_user.id, user_id=uid, reference=oid, details=f"Amount: {money(amount)}৳; TxID: {txid or 'Manual'}; Referral bonus: {money(ref_bonus)}৳")
    try: await call.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    await call.answer("✅ Deposit approved.")

@dp.callback_query(F.data.startswith("adm_dep_no:"))
async def admin_dep_reject(call: CallbackQuery):
    if not admin_ok(call.from_user.id) or (role(call.from_user.id) not in (None,"owner","full","dep") and call.from_user.id!=OWNER_ID): return await call.answer("❌ এই অপশনের অনুমতি নেই।",show_alert=True)
    oid=call.data.split(":",1)[1]
    con=db(); row=con.execute("SELECT status FROM deposits WHERE order_no=?",(oid,)).fetchone(); con.close()
    if not row or row[0] not in ("Pending","Processing"):
        return await call.answer("❌ এই রিকোয়েস্টটি বর্তমানে Reject করা যাবে না।",show_alert=True)
    await state.update_data(kind="deposit",rid=oid)
    await state.set_state(AdvancedAdminState.reject_reason)
    await call.message.answer("<b>❌ Deposit Reject Reason লিখুন।</b>")
    await call.answer()

@dp.callback_query(F.data.startswith("adm_wd_ok:"))
async def admin_wd_approve(call: CallbackQuery):
    if not admin_ok(call.from_user.id) or (role(call.from_user.id) not in (None,"owner","full","wth") and call.from_user.id != OWNER_ID):
        return await call.answer("❌ এই অপশনের অনুমতি নেই।", show_alert=True)
    try:
        wid=int(call.data.split(":",1)[1])
    except ValueError:
        return await call.answer("❌ Invalid request.", show_alert=True)
    con=db()
    row=con.execute("SELECT user_id,method,account,amount,status FROM withdrawals WHERE id=?", (wid,)).fetchone()
    con.close()
    if not row:
        return await call.answer("❌ Request পাওয়া যায়নি।", show_alert=True)
    uid, method, account_no, amount, status=row
    if not atomic_status_change("withdrawals","id",wid,"Approved",("Pending","Processing")):
        return await call.answer("❌ এই রিকোয়েস্টটি অলরেডি প্রসেস করা হয়েছে।", show_alert=True)
    try:
        await send_template(uid, "withdraw_approved_message",
            "<b>🎊 Withdraw Completed!</b>\n\n<b>💰 Amount: {amount}৳</b>\n<b>🟢 আপনার পেমেন্ট রিকোয়েস্ট সফলভাবে সম্পন্ন হয়েছে।</b>",
            amount=money(amount))
    except Exception:
        pass
    try: await call.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    await call.answer("✅ Withdraw approved.")

@dp.callback_query(F.data.startswith("adm_wd_no:"))
async def admin_wd_reject(call: CallbackQuery):
    if not admin_ok(call.from_user.id) or (role(call.from_user.id) not in (None,"owner","full","wth") and call.from_user.id != OWNER_ID):
        return await call.answer("❌ এই অপশনের অনুমতি নেই।", show_alert=True)
    try:
        wid=int(call.data.split(":",1)[1])
    except ValueError:
        return await call.answer("❌ Invalid request.", show_alert=True)
    con=db()
    row=con.execute("SELECT user_id,amount,status FROM withdrawals WHERE id=?", (wid,)).fetchone()
    con.close()
    if not row:
        return await call.answer("❌ Request পাওয়া যায়নি।", show_alert=True)
    uid, amount, status=row
    if not atomic_status_change("withdrawals","id",wid,"Rejected",("Pending","Processing")):
        return await call.answer("❌ এই রিকোয়েস্টটি অলরেডি প্রসেস করা হয়েছে।", show_alert=True)
    con=db()
    con.execute("UPDATE withdrawals SET reason=?,updated_at=? WHERE id=?", ("Withdrawal request rejected by admin.",now_iso(),wid))
    con.execute("UPDATE users SET main_balance=main_balance+? WHERE user_id=?", (amount,uid))
    con.commit(); con.close()
    try:
        await send_template(uid, "withdraw_rejected_message",
            "<b>🚫 Withdraw Rejected</b>\n\n<b>💰 Amount: {amount}৳</b>\n<b>📝 কারণ: {reason}</b>\n<b>💰 ব্যালেন্স ফেরত দেওয়া হয়েছে।</b>",
            amount=money(amount), reason="Withdrawal request rejected by admin.")
    except Exception: pass
    try: await call.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    await call.answer("❌ Withdraw rejected.")

@dp.callback_query(F.data == "cancel_inline")
async def inline_cancel(call: CallbackQuery, state: FSMContext):
    if not callback_once(f"cancel_inline:{call.from_user.id}"):
        await call.answer()
        return
    await state.clear()
    uid = call.from_user.id
    await call.message.answer("<b>❌ বাতিল করা হয়েছে।</b>", reply_markup=main_keyboard(uid))
    await call.answer()

# =========================
# ADMIN TRANSACTION / USER INFO VIEW
# =========================
def _admin_status_label(status: str) -> str:
    return {
        "Pending": "⏳ Pending",
        "Processing": "⚙️ Processing",
        "Approved": "✅ Successful",
        "Success": "✅ Successful",
        "Rejected": "❌ Failed",
        "Failed": "❌ Failed",
    }.get(status, status or "—")

def _admin_user_snapshot(con, uid: int):
    r = con.execute("""
        SELECT user_id,name,username,main_balance,deposit_balance,bonus_balance,
               referral_balance,total_earnings,created_at,referrer_id,task_balance,
               referral_count,completed_tasks,banned,suspended
        FROM users WHERE user_id=?
    """, (uid,)).fetchone()
    return r

def _transaction_admin_text(kind: str, row, user):
    if kind == "deposit":
        did, uid, method, amount, txid, order_no, status, created_at, updated_at = row
        acc_line = f"📝 TxID: <code>{escape(str(txid or '—'))}</code>\n"
        req_line = f"🆔 Order: <code>{escape(str(order_no or '—'))}</code>\n"
        req_line += f"🔢 Deposit ID: <code>{did}</code>\n"
    else:
        wid, uid, method, account, amount, status, created_at, updated_at = row
        acc_line = f"📲 Account: <code>{escape(str(account or '—'))}</code>\n"
        req_line = f"🔢 Withdraw ID: <code>{wid}</code>\n"
    if user:
        (u_id,name,username,main,deposit,bonus,referral,total,joined,referrer,task,ref_count,completed,banned,suspended)=user
        username_text=f"@{username}" if username else "—"
        user_info=(
            "<b>👤 USER INFORMATION</b>\n"
            f"👤 Name: <code>{escape(str(name or '—'))}</code>\n"
            f"🔗 Username: <code>{escape(str(username_text))}</code>\n"
            f"🆔 User ID: <code>{u_id}</code>\n"
            f"💰 Main Balance: <code>{money(main)}৳</code>\n"
            f"📥 Deposit Balance: <code>{money(deposit)}৳</code>\n"
            f"🎁 Bonus Balance: <code>{money(bonus)}৳</code>\n"
            f"👥 Referral Balance: <code>{money(referral)}৳</code>\n"
            f"🧩 Task Balance: <code>{money(task)}৳</code>\n"
            f"👥 Referral Count: <code>{ref_count}</code>\n"
            f"🏆 Completed Tasks: <code>{completed}</code>\n"
            f"📊 Total Earnings: <code>{money(total)}৳</code>\n"
            f"👤 Referrer ID: <code>{referrer or 0}</code>\n"
            f"🚫 Banned: <code>{'YES' if banned else 'NO'}</code> | ⏸ Suspended: <code>{'YES' if suspended else 'NO'}</code>\n"
            f"🗓 Joined: <code>{joined or '—'}</code>\n"
        )
    else:
        user_info=(
            "<b>👤 USER INFORMATION</b>\n"
            f"🆔 User ID: <code>{uid}</code>\n"
            "⚠️ User record পাওয়া যায়নি।\n"
        )
    if kind == "deposit":
        tx_info=(
            "<b>📥 DEPOSIT</b>\n"
            f"💳 Method: <code>{escape(str(method or '—'))}</code>\n"
            f"💰 Amount: <code>{money(amount)}৳</code>\n"
            f"📌 Status: <code>{_admin_status_label(status)}</code>\n"
            f"{acc_line}{req_line}"
            f"🕒 Created: <code>{created_at or '—'}</code>\n"
            f"🔄 Updated: <code>{updated_at or '—'}</code>"
        )
    else:
        tx_info=(
            "<b>📤 WITHDRAW</b>\n"
            f"💳 Method: <code>{escape(str(method or '—'))}</code>\n"
            f"💰 Amount: <code>{money(amount)}৳</code>\n"
            f"📌 Status: <code>{_admin_status_label(status)}</code>\n"
            f"{acc_line}{req_line}"
            f"🕒 Created: <code>{created_at or '—'}</code>\n"
            f"🔄 Updated: <code>{updated_at or '—'}</code>"
        )
    return tx_info + "\n\n" + user_info

def _transaction_kb(kind: str, status: str, page: int, total_pages: int, row_id: int):
    buttons=[]
    if kind == "deposit" and status in ("Pending","Processing"):
        order=row_id
        buttons.append([InlineKeyboardButton(text="⚙️ Processing",callback_data=f"x:dproc:{order}")])
        # row_id here is deposit numeric id; approval/reject uses order, handled separately by the caller.
    return buttons

async def _show_transactions(call: CallbackQuery, kind: str, status_filter: str="ALL", page: int=0):
    if kind not in ("deposit","withdraw"):
        return await call.answer("❌ Invalid transaction type.", show_alert=True)
    if page < 0: page=0
    con=db()
    status_sql=""
    params=[]
    if status_filter != "ALL":
        status_sql=" AND t.status=?"
        params.append(status_filter)
    if kind == "deposit":
        count=con.execute(f"SELECT COUNT(*) FROM deposits t WHERE 1=1{status_sql}",tuple(params)).fetchone()[0]
        rows=con.execute(f"""
            SELECT t.id,t.user_id,t.method,t.amount,t.txid,t.order_no,t.status,t.created_at,t.updated_at
            FROM deposits t WHERE 1=1{status_sql}
            ORDER BY t.id DESC LIMIT 4 OFFSET ?
        """,tuple(params+[page*4])).fetchall()
    else:
        count=con.execute(f"SELECT COUNT(*) FROM withdrawals t WHERE 1=1{status_sql}",tuple(params)).fetchone()[0]
        rows=con.execute(f"""
            SELECT t.id,t.user_id,t.method,t.account,t.amount,t.status,t.created_at,t.updated_at
            FROM withdrawals t WHERE 1=1{status_sql}
            ORDER BY t.id DESC LIMIT 4 OFFSET ?
        """,tuple(params+[page*4])).fetchall()
    total_pages=max(1,(count+3)//4)
    snapshots={r[1]:_admin_user_snapshot(con,r[1]) for r in rows}
    con.close()
    title="📥 ALL DEPOSITS" if kind=="deposit" else "📤 ALL WITHDRAWS"
    filter_name="All" if status_filter=="ALL" else _admin_status_label(status_filter)
    text=f"<b>{title}</b>\n━━━━━━━━━━━━━━━━━━\n<b>Filter:</b> {filter_name}\n<b>Page:</b> {page+1}/{total_pages}\n<b>Total:</b> {count}\n"
    kb_rows=[]
    for r in rows:
        if kind=="deposit":
            did,uid,m,a,t,o,s,created,updated=r
            text += "\n━━━━━━━━━━━━━━━━━━\n" + _transaction_admin_text(kind,r,snapshots.get(uid))
            if s in ("Pending","Processing"):
                kb_rows.append([InlineKeyboardButton(text=f"⚙️ #{did} Processing",callback_data=f"x:dproc:{did}")])
                kb_rows.append([InlineKeyboardButton(text=f"✅ #{did} Approve",callback_data=f"x:dok:{o}"),InlineKeyboardButton(text=f"❌ #{did} Reject",callback_data=f"x:dno:{o}")])
            elif s == "Rejected":
                kb_rows.append([InlineKeyboardButton(text=f"♻️ #{did} Approve After Reject",callback_data=f"x:dok:{o}")])
        else:
            wid,uid,m,acc,a,s,created,updated=r
            text += "\n━━━━━━━━━━━━━━━━━━\n" + _transaction_admin_text(kind,r,snapshots.get(uid))
            if s in ("Pending","Processing"):
                kb_rows.append([InlineKeyboardButton(text=f"⚙️ #{wid} Processing",callback_data=f"x:wproc:{wid}")])
                kb_rows.append([InlineKeyboardButton(text=f"✅ #{wid} Approve",callback_data=f"x:wok:{wid}"),InlineKeyboardButton(text=f"❌ #{wid} Reject",callback_data=f"x:wno:{wid}")])
    if not rows:
        text += "\n\n<b>কোনো রেকর্ড পাওয়া যায়নি।</b>"
    filter_buttons=[]
    for label,val in (("📋 All","ALL"),("⏳ Pending","Pending"),("⚙️ Processing","Processing"),("✅ Successful","Approved"),("❌ Failed","Rejected")):
        filter_buttons.append(InlineKeyboardButton(text=label,callback_data=f"x:tr:{kind}:{val}:0"))
    kb_rows.append(filter_buttons[:2]); kb_rows.append(filter_buttons[2:4]); kb_rows.append([filter_buttons[4]])
    nav=[]
    if page>0: nav.append(InlineKeyboardButton(text="⬅️ Previous",callback_data=f"x:tr:{kind}:{status_filter}:{page-1}"))
    if page+1<total_pages: nav.append(InlineKeyboardButton(text="Next ➡️",callback_data=f"x:tr:{kind}:{status_filter}:{page+1}"))
    if nav: kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton(text="📥 Deposits" if kind=="withdraw" else "📤 Withdraws",callback_data=f"x:tr:{'deposit' if kind=='withdraw' else 'withdraw'}:ALL:0")])
    kb_rows.append([InlineKeyboardButton(text="⬅️ Admin Panel",callback_data="x:open")])
    await call.message.edit_text(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await call.answer()

# =========================
# ADVANCED ADMIN PANEL
# =========================
def admin_kb(uid):
    rows = [
        [InlineKeyboardButton(text="📊 Dashboard", callback_data="x:dash")],
        [InlineKeyboardButton(text="⚙️ Bot Controls", callback_data="x:controls"), InlineKeyboardButton(text="💳 Payment Controls", callback_data="x:pay")],
        [InlineKeyboardButton(text="📈 Limits", callback_data="x:limits"), InlineKeyboardButton(text="📣 Force Join", callback_data="x:force")],
        [InlineKeyboardButton(text="👤 User Control", callback_data="x:user"), InlineKeyboardButton(text="📥 Deposits", callback_data="x:deps")],
        [InlineKeyboardButton(text="💸 Withdraws", callback_data="x:wds"), InlineKeyboardButton(text="📋 All Transactions", callback_data="x:transactions")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="x:broadcast"), InlineKeyboardButton(text="✉️ User Broadcast", callback_data="x:ubroadcast")],
        [InlineKeyboardButton(text="💳 Payment Methods", callback_data="x:methods"), InlineKeyboardButton(text="📝 MESSAGE / CONTENT CONTROL", callback_data="x:messages")],
        [InlineKeyboardButton(text="🎁 Bonus / Referral", callback_data="x:rewards")],
        [InlineKeyboardButton(text="📜 History / Database", callback_data="x:historydb")],
        [InlineKeyboardButton(text="⌨️ Commands", callback_data="x:commands")]
    ]
    if super_ok(uid):
        rows.append([InlineKeyboardButton(text="👑 Admin Management", callback_data="x:admins")])
    rows.append([InlineKeyboardButton(text="⬅️ Main Menu", callback_data="x:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.message(F.text == "🔧 Admin Panel")
async def advanced_admin_button(message: Message):
    if not admin_ok(message.from_user.id):
        await message.answer("<b>❌ আপনার Admin access নেই।</b>")
        return
    await message.answer("<b>🔐 ADMIN CONTROL PANEL</b>\n━━━━━━━━━━━━━━━━━━\n<b>সম্পূর্ণ dynamic control interface</b>", reply_markup=admin_kb(message.from_user.id))

@dp.callback_query(F.data.startswith("x:"))
async def admin_callbacks_router(call: CallbackQuery, state: FSMContext):
    if not admin_ok(call.from_user.id):
        await call.answer("❌ আপনার Admin access নেই।", show_alert=True)
        return
    
    data = call.data
    await send_history_event("ADMIN_ACTION", actor_id=call.from_user.id, reference=data, details=f"Admin callback: {data}")
    # Role-scoped admin access for request operations.
    if data.startswith(("x:d","adm_dep")) and role(call.from_user.id) not in (None,"owner","full","dep") and call.from_user.id != OWNER_ID:
        return await call.answer("❌ আপনার Deposit permission নেই।", show_alert=True)
    if data.startswith(("x:w","adm_wd")) and role(call.from_user.id) not in (None,"owner","full","wth") and call.from_user.id != OWNER_ID:
        return await call.answer("❌ আপনার Withdraw permission নেই।", show_alert=True)
    if data == "x:open":
        await call.message.edit_text("<b>🔐 ADMIN CONTROL PANEL</b>\n━━━━━━━━━━━━━━━━━━\n<b>সম্পূর্ণ dynamic control interface</b>", reply_markup=admin_kb(call.from_user.id))
        await call.answer()
    elif data == "x:close":
        await call.message.delete()
        await call.answer()
    elif data == "x:dash":
        con = db()
        cur = con.cursor()
        users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        vip = cur.execute("SELECT COUNT(DISTINCT user_id) FROM plans").fetchone()[0] if cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='plans'").fetchone() else 0
        fund = cur.execute("SELECT COALESCE(SUM(amount),0) FROM deposits WHERE status IN ('Approved','Success')").fetchone()[0]
        wth = cur.execute("SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE status IN ('Approved','Success')").fetchone()[0]
        con.close()
        await call.message.edit_text(
            f"<b>📊 LIVE ADMIN DASHBOARD</b>\n━━━━━━━━━━━━━━━━━━\n<b>👥 Total Users: {users}</b>\n<b>💎 VIP Buyers: {vip}</b>\n<b>💰 Total Fund: {money(fund)}৳</b>\n<b>💸 Total Withdraw: {money(wth)}৳</b>\n\n<b>🤖 Bot: {'🟢 ON' if getset('bot_enabled')=='1' else '🔴 OFF'}</b>",
            reply_markup=admin_kb(call.from_user.id)
        )
        await call.answer()
    elif data == "x:controls":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f'🤖 Bot: {"🟢 ON" if getset("bot_enabled")=="1" else "🔴 OFF"}', callback_data="x:t:bot_enabled")],
            [InlineKeyboardButton(text=f'💰 Fund: {"🟢 ON" if getset("fund_enabled")=="1" else "🔴 OFF"}', callback_data="x:t:fund_enabled")],
            [InlineKeyboardButton(text=f'💸 Withdraw: {"🟢 ON" if getset("withdraw_enabled")=="1" else "🔴 OFF"}', callback_data="x:t:withdraw_enabled")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="x:open")]
        ])
        await call.message.edit_text("<b>⚙️ BOT / MASTER CONTROLS</b>", reply_markup=kb)
        await call.answer()
    elif data.startswith("x:t:"):
        key = data.split(":")[-1]
        newval = "0" if getset(key) == "1" else "1"
        setset(key, newval)
        # Keep the legacy Deposit ON/OFF buttons synchronized with the dynamic method table.
        if key in ("dep_bkash_enabled","dep_nagad_enabled"):
            method = "bKash" if key == "dep_bkash_enabled" else "Nagad"
            con=db(); con.execute("UPDATE payment_methods SET enabled=? WHERE name=? AND kind='deposit'",(int(newval),method)); con.commit(); con.close()
        await call.answer("Updated")
        await x_controls_helper(call)
    elif data == "x:pay":
        await x_pay_helper(call)
    elif data == "x:allw":
        keys = ["wth_bkash_enabled", "wth_nagad_enabled", "wth_rocket_enabled", "wth_upay_enabled"]
        new = "0" if all(getset(k) == "1" for k in keys) else "1"
        for k in keys:
            setset(k, new)
        await x_pay_helper(call)
    elif data.startswith("x:num:"):
        await state.update_data(method=data.split(":")[-1])
        await state.set_state(AdvancedAdminState.number)
        await call.message.answer("<b>📲 নতুন ১১ ডিজিটের নম্বর পাঠান।</b>")
        await call.answer()
    elif data.startswith("x:gw:"):
        await state.update_data(method=data.split(":")[-1])
        await state.set_state(AdvancedAdminState.gateway_url)
        await call.message.answer("<b>🔗 Payment Gateway URL পাঠান (https://...)।</b>")
        await call.answer()
    elif data.startswith("x:rm:"):
        m = data.split(":")[-1]
        setset("dep_bkash_gateway" if m == "bKash" else "dep_nagad_gateway", "")
        await call.answer("Gateway removed", show_alert=True)
        await x_pay_helper(call)
    elif data == "x:historydb":
        con=db(); count=con.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]; con.close()
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"📜 History Channel: {'🟢 ON' if getset('history_channel_enabled','0')=='1' else '🔴 OFF'}",callback_data="x:historytoggle")],
            [InlineKeyboardButton(text="🔗 Set History Channel",callback_data="x:historyset")],
            [InlineKeyboardButton(text="📋 View Local History",callback_data="x:historyview:0")],
            [InlineKeyboardButton(text="💾 Backup Database Now",callback_data="x:dbbackup")],
            [InlineKeyboardButton(text=f"♻️ Auto Restore: {'🟢 ON' if getset('auto_db_restore','1')=='1' else '🔴 OFF'}",callback_data="x:restoretoggle")],
            [InlineKeyboardButton(text="♻️ Restore Latest Backup",callback_data="x:dbrestore")],
            [InlineKeyboardButton(text="🗑 Delete ALL User History",callback_data="x:historydelete")],
            [InlineKeyboardButton(text="🗑 Delete ALL User Database",callback_data="x:delall")],
            [InlineKeyboardButton(text="⬅️ Back",callback_data="x:open")]
        ])
        await call.message.edit_text(f"<b>📜 HISTORY / DATABASE CONTROL</b>\n━━━━━━━━━━━━━━━━━━\n<b>Local history records:</b> <code>{count}</code>\n<b>Channel:</b> <code>{escape(getset('history_channel_chat','Not set') or 'Not set')}</code>\n<b>Channel link:</b> <code>{escape(getset('history_channel_link',DEFAULT_HISTORY_CHANNEL_LINK))}</code>\n\n<b>⚠️ Delete/Restore operations are Owner-only.</b>",reply_markup=kb); await call.answer()
    elif data == "x:historytoggle":
        if not super_ok(call.from_user.id): return await call.answer("❌ Owner only",show_alert=True)
        new='0' if getset('history_channel_enabled','0')=='1' else '1'; setset('history_channel_enabled',new)
        await call.answer("History channel " + ("ON" if new=='1' else "OFF"));
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer("<b>✅ History channel setting updated.</b>",reply_markup=admin_kb(call.from_user.id))
    elif data == "x:historyset":
        if not super_ok(call.from_user.id): return await call.answer("❌ Owner only",show_alert=True)
        await state.set_state(AdvancedAdminState.history_channel)
        await call.message.answer(f"<b>🔗 History Channel সেট করুন</b>\n\n<b>Private channel-এর invite link শুধু link হিসেবে ব্যবহার করা যায়; Bot API-তে message পাঠাতে Channel Chat ID (-100...) অথবা public @username দরকার।</b>\n\n<b>তোমার দেওয়া link:</b> <code>{DEFAULT_HISTORY_CHANNEL_LINK}</code>\n\n<b>এখন Channel Chat ID বা @username পাঠাও:</b>")
        await call.answer()
    elif data == "x:historyview":
        try: page=max(0,int(data.split(":")[-1]))
        except Exception: page=0
        con=db(); rows=con.execute("SELECT id,event_type,actor_id,user_id,reference,details,created_at FROM audit_events ORDER BY id DESC LIMIT 15 OFFSET ?",(page*15,)).fetchall(); total=con.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]; con.close()
        text="<b>📜 LOCAL HISTORY</b>\n━━━━━━━━━━━━━━━━━━\n"
        for eid,etype,actor,user,ref,details,created in rows:
            text += f"\n<b>#{eid} {escape(etype)}</b>\n👤 <code>{user}</code> | 🛡 <code>{actor}</code> | 🕒 <code>{created}</code>\n🔖 <code>{escape(ref or '—')}</code>\n{escape(details or '—')}\n"
        kbrows=[]
        if page>0: kbrows.append([InlineKeyboardButton(text="⬅️ Previous",callback_data=f"x:historyview:{page-1}")])
        if (page+1)*15<total: kbrows.append([InlineKeyboardButton(text="Next ➡️",callback_data=f"x:historyview:{page+1}")])
        kbrows.append([InlineKeyboardButton(text="⬅️ History / DB",callback_data="x:historydb")])
        await call.message.edit_text(text or "<b>কোনো history নেই।</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=kbrows)); await call.answer()
    elif data == "x:dbbackup":
        if not super_ok(call.from_user.id): return await call.answer("❌ Owner only",show_alert=True)
        ok=backup_database(); await send_history_event("DATABASE_BACKUP",actor_id=call.from_user.id,details="Manual database backup created")
        await call.answer("✅ Backup created" if ok else "❌ Backup failed",show_alert=True)
    elif data == "x:restoretoggle":
        if not super_ok(call.from_user.id): return await call.answer("❌ Owner only",show_alert=True)
        new='0' if getset('auto_db_restore','1')=='1' else '1'; setset('auto_db_restore',new)
        await call.answer("Auto restore " + ("ON" if new=='1' else "OFF"),show_alert=True)
        await x_open_historydb_refresh(call)
    elif data == "x:dbrestore":
        if not super_ok(call.from_user.id): return await call.answer("❌ Owner only",show_alert=True)
        ok=restore_database_if_missing() if not os.path.exists(DB_NAME) else False
        if not ok and os.path.exists(DB_BACKUP_NAME):
            # Explicit restore: replace live DB only after closing this connection scope.
            try:
                src=sqlite3.connect(DB_BACKUP_NAME,timeout=30); dst=sqlite3.connect(DB_NAME,timeout=30); src.backup(dst); dst.commit(); src.close(); dst.close(); ok=True
            except Exception: ok=False
        await send_history_event("DATABASE_RESTORE",actor_id=call.from_user.id,details="Latest database backup restored" if ok else "Restore failed")
        await call.answer("♻️ Backup restored" if ok else "❌ Restore failed",show_alert=True)
    elif data == "x:historydelete":
        if not super_ok(call.from_user.id): return await call.answer("❌ Owner only",show_alert=True)
        con=db(); con.execute("DELETE FROM audit_events"); con.commit(); con.close()
        await call.answer("🗑 All user history deleted",show_alert=True)
        await x_open_historydb_refresh(call)
    elif data == "x:commands":
        con=db(); rows=con.execute("SELECT command,title,enabled,position FROM bot_commands ORDER BY command").fetchall(); con.close()
        text="<b>⌨️ COMMAND MANAGER</b>\n━━━━━━━━━━━━━━━━━━\n"+("\n".join(f"<code>/{c}</code> — {t} — {'🟢' if e else '🔴'} — {pos}" for c,t,e,pos in rows) if rows else "কোনো custom command নেই।")
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Add / Edit",callback_data="x:addcommand"), InlineKeyboardButton(text="➖ Remove",callback_data="x:rmcommand")],
            [InlineKeyboardButton(text="🔄 Sync Bot Commands",callback_data="x:synccommands")],
            [InlineKeyboardButton(text="⬅️ Back",callback_data="x:open")]
        ])
        await call.message.edit_text(text,reply_markup=kb); await call.answer()
    elif data == "x:addcommand":
        await state.set_state(AdvancedAdminState.command_edit)
        await call.message.answer("<b>Format:</b>\n<code>command | title | message | top/bottom</code>\n<b>উদাহরণ:</b> <code>rules | 📜 Rules | এখানে নিয়মগুলো লিখুন | bottom</code>")
        await call.answer()
    elif data == "x:rmcommand":
        await state.update_data(command_action="remove")
        await state.set_state(AdvancedAdminState.command_edit)
        await call.message.answer("<b>যে command remove করবেন লিখুন:</b> <code>rules</code>")
        await call.answer()
    elif data == "x:synccommands":
        await sync_bot_commands()
        await call.answer("✅ Commands synced")
    elif data == "x:rewards":
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"👥 Referral: {'🟢 ON' if getset('referral_enabled')=='1' else '🔴 OFF'}",callback_data="x:t:referral_enabled")],
            [InlineKeyboardButton(text=f"💰 Referral Amount: {getset('referral_bonus','0')}৳",callback_data="x:v:referral_bonus")],
            [InlineKeyboardButton(text=f"🎁 Bonus: {'🟢 ON' if getset('bonus_enabled')=='1' else '🔴 OFF'}",callback_data="x:t:bonus_enabled")],
            [InlineKeyboardButton(text=f"🎁 Bonus Amount: {getset('bonus_amount','5')}৳",callback_data="x:v:bonus_amount")],
            [InlineKeyboardButton(text=f"⏳ Bonus Expiry: {getset('bonus_expiry_days','1')} day(s)",callback_data="x:v:bonus_expiry_days")],
            [InlineKeyboardButton(text="⬅️ Back",callback_data="x:open")]
        ])
        await call.message.edit_text("<b>🎁 BONUS / REFERRAL CONTROL</b>\n━━━━━━━━━━━━━━━━━━\n<b>Referral ON + Bonus ON থাকলে নতুন referred user-এর জন্য Bonus Amount দেওয়া হবে। Referral Amount থাকলে approved deposit-এর পর সেটিও referral commission হিসেবে যোগ হবে।</b>",reply_markup=kb); await call.answer()
    elif data == "x:methods":
        con=db()
        rows=con.execute("SELECT id,name,kind,enabled,logo,number,gateway,manual_enabled,COALESCE(gateway_enabled,0) FROM payment_methods ORDER BY kind,sort_order,id").fetchall()
        con.close()
        text="<b>💳 PAYMENT METHODS</b>\n━━━━━━━━━━━━━━━━━━\n"
        kbrows=[]
        for mid,name,kind,en,logo,num,gw,manual,gw_on in rows:
            if kind=="deposit":
                text += (f"<b>{logo} {name}</b> — {'🟢 Method ON' if en else '🔴 Method OFF'}\n"
                         f"<b>🌐 Gateway:</b> {'🟢 ON' if gw_on else '🔴 OFF'} | <b>📲 Manual:</b> {'🟢 ON' if manual else '🔴 OFF'}\n"
                         f"<b>🔗 Link:</b> <code>{escape(gw or 'Not set')}</code>\n"
                         f"<b>📱 Number:</b> <code>{escape(num or 'Not set')}</code>\n\n")
                kbrows.append([
                    InlineKeyboardButton(text=f"{name} 🌐 {'ON' if gw_on else 'OFF'}",callback_data=f"x:pmgw:{name}"),
                    InlineKeyboardButton(text=f"{name} 📲 {'ON' if manual else 'OFF'}",callback_data=f"x:pmm:{name}")
                ])
                kbrows.append([
                    InlineKeyboardButton(text=f"🔗 {name} Gateway",callback_data=f"x:pmgwedit:{name}"),
                    InlineKeyboardButton(text=f"📱 {name} Number",callback_data=f"x:pmnumedit:{name}")
                ])
            else:
                text += f"<b>{logo} {name}</b> — {'🟢 ON' if en else '🔴 OFF'} — {kind}\n"
        kbrows += [
            [InlineKeyboardButton(text="➕ Add Method",callback_data="x:addmethod")],
            [InlineKeyboardButton(text="➖ Remove Method",callback_data="x:rmmethod"), InlineKeyboardButton(text="🔄 Method ON/OFF",callback_data="x:togglemethod")],
            [InlineKeyboardButton(text="🔗 Legacy Edit Format",callback_data="x:editmethod")],
            [InlineKeyboardButton(text="⬅️ Back",callback_data="x:open")]
        ]
        await call.message.edit_text(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=kbrows)); await call.answer()
    elif data.startswith("x:pmgw:"):
        name=data.split(":",2)[2]
        con=db(); row=con.execute("SELECT COALESCE(gateway_enabled,0) FROM payment_methods WHERE name=? AND kind='deposit'",(name,)).fetchone()
        if not row:
            con.close(); return await call.answer("❌ Method পাওয়া যায়নি।",show_alert=True)
        newval=0 if int(row[0]) else 1
        if newval:
            gw=con.execute("SELECT gateway FROM payment_methods WHERE name=? AND kind='deposit'",(name,)).fetchone()
            if not gw or not (gw[0] or '').strip():
                con.rollback(); con.close(); return await call.answer("❌ আগে Gateway Link সেট করুন।",show_alert=True)
        con.execute("UPDATE payment_methods SET gateway_enabled=? WHERE name=? AND kind='deposit'",(newval,name)); con.commit(); con.close()
        await x_methods_refresh(call); return
    elif data.startswith("x:pmm:"):
        name=data.split(":",2)[2]
        con=db(); row=con.execute("SELECT manual_enabled FROM payment_methods WHERE name=? AND kind='deposit'",(name,)).fetchone()
        if not row:
            con.close(); return await call.answer("❌ Method পাওয়া যায়নি।",show_alert=True)
        newval=0 if int(row[0]) else 1
        if newval:
            num=con.execute("SELECT number FROM payment_methods WHERE name=? AND kind='deposit'",(name,)).fetchone()
            if not num or not (num[0] or '').strip():
                con.rollback(); con.close(); return await call.answer("❌ আগে Manual Deposit Number সেট করুন।",show_alert=True)
        con.execute("UPDATE payment_methods SET manual_enabled=? WHERE name=? AND kind='deposit'",(newval,name)); con.commit(); con.close()
        await x_methods_refresh(call); return
    elif data.startswith("x:pmgwedit:"):
        name=data.split(":",2)[2]
        await state.update_data(pm_name=name,pm_edit_kind="gateway")
        await state.set_state(AdvancedAdminState.payment_method)
        await call.message.answer(
            f"<b>🔗 {escape(name)} Payment Gateway Link</b>\n\n"
            "<b>পুরোনো fixed link দিলেও কাজ করবে:</b>\n"
            "<code>https://ttkpay.up.railway.app/?amount=&user_id=2037461288&method=bKash</code>\n\n"
            "<b>Placeholder ব্যবহার করলেও কাজ করবে:</b>\n"
            "<code>{amount}</code> <code>{user_id}</code> <code>{method}</code> <code>{order}</code> <code>{session_id}</code>\n\n"
            "<b>নতুন gateway URL পাঠান:</b>")
        await call.answer()
    elif data.startswith("x:pmnumedit:"):
        name=data.split(":",2)[2]
        await state.update_data(pm_name=name,pm_edit_kind="number")
        await state.set_state(AdvancedAdminState.payment_method)
        await call.message.answer(f"<b>📱 {escape(name)} Manual Deposit Number</b>\n<b>১১ ডিজিটের bKash/Nagad নম্বর পাঠান।</b>")
        await call.answer()
    elif data == "x:addmethod":
        await state.set_state(AdvancedAdminState.payment_method)
        await call.message.answer("<b>➕ Format:</b>\n<code>Name | deposit/withdraw | Emoji | Number | Gateway</code>\n<b>Gateway example:</b> <code>https://ttkpay.up.railway.app/?amount={amount}&user_id={user_id}&method={method}</code>\n<b>Supported:</b> <code>{amount}</code> <code>{user_id}</code> <code>{method}</code> <code>{order}</code> <code>{session_id}</code>")
        await call.answer()
    elif data == "x:rmmethod":
        await state.update_data(method_action="remove")
        await state.set_state(AdvancedAdminState.payment_method)
        await call.message.answer("<b>➖ যে Method Remove করবেন তার নাম লিখুন।</b>")
        await call.answer()
    elif data == "x:togglemethod":
        await state.update_data(method_action="toggle")
        await state.set_state(AdvancedAdminState.payment_method)
        await call.message.answer("<b>🔄 Method ON/OFF করতে নাম লিখুন:</b>")
        await call.answer()
    elif data == "x:editmethod":
        await state.update_data(method_action="edit")
        await state.set_state(AdvancedAdminState.payment_method)
        await call.message.answer(
            "<b>🔗 PAYMENT LINK / METHOD EDIT</b>\n\n"
            "<b>Format:</b> <code>Name | Number | Gateway | on/off</code>\n\n"
            "<b>Gateway placeholders:</b>\n"
            "<code>{amount}</code> = Deposit Amount\n"
            "<code>{user_id}</code> = Telegram User ID\n"
            "<code>{method}</code> = bKash / Nagad / Method Name\n"
            "<code>{order}</code> = Payment Session ID\n"
            "<code>{session_id}</code> = Payment Session ID\n\n"
            "<b>Example bKash:</b> <code>https://ttkpay.up.railway.app/?amount={amount}&user_id={user_id}&method={method}&order={order}&session_id={session_id}</code>\n"
            "<b>Example fixed link:</b> <code>https://ttkpay.up.railway.app/?amount=&user_id=&method=bKash</code>",
            )
        await call.answer()
    elif data == "x:messages":
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👋 Welcome Message",callback_data="x:msg:welcome_message")],
            [InlineKeyboardButton(text="📊 Earnings Message",callback_data="x:msg:daily_demo_warning")],
            [InlineKeyboardButton(text="💳 Deposit Success",callback_data="x:msg:deposit_approved_message")],
            [InlineKeyboardButton(text="❌ Deposit Reject",callback_data="x:msg:deposit_rejected_message")],
            [InlineKeyboardButton(text="💸 Withdraw Success",callback_data="x:msg:withdraw_approved_message")],
            [InlineKeyboardButton(text="❌ Withdraw Reject",callback_data="x:msg:withdraw_rejected_message")],
            [InlineKeyboardButton(text="👥 Referral Bonus",callback_data="x:msg:referral_message")],
            [InlineKeyboardButton(text="⚠️ Invalid / Cancel",callback_data="x:msg:invalid_number_message")],
            [InlineKeyboardButton(text="⬅️ Back",callback_data="x:open")]
        ])
        await call.message.edit_text(
            "<b>📝 MESSAGE / CONTENT CONTROL</b>\n━━━━━━━━━━━━━━━━━━\n"
            "<b>স্ক্রিনশটের মতো প্রতিটি Message/Content আলাদাভাবে Edit করা যাবে।</b>\n\n"
            "<b>Supported:</b> <code>{amount}</code> <code>{txid}</code> <code>{order}</code> <code>{reason}</code>",
            reply_markup=kb)
        await call.answer()
    elif data.startswith("x:msg:"):
        key=data.split(":",2)[2]
        current=getset(key,"")
        await state.update_data(message_key=key)
        await state.set_state(AdvancedAdminState.message_edit)
        await call.message.answer(f"<b>📝 বর্তমান:</b>\n{current}\n\n<b>নতুন মেসেজ পাঠান।</b>")
        await call.answer()
    elif data == "x:limits":
        await x_limits_helper(call)
    elif data.startswith("x:v:"):
        await state.update_data(key=data.split(":")[-1])
        await state.set_state(AdvancedAdminState.generic_value)
        await call.message.answer("<b>✏️ নতুন সংখ্যাটি পাঠান।</b>")
        await call.answer()
    elif data == "x:force":
        await x_force_helper(call)
    elif data == "x:tforce":
        setset("force_join_enabled", "0" if getset("force_join_enabled") == "1" else "1")
        await x_force_helper(call)
    elif data == "x:fjset":
        await state.set_state(AdvancedAdminState.force_chat)
        await call.message.answer("<b>📣 Channel username বা chat ID পাঠান। যেমন @NIKAN_EARN</b>")
        await call.answer()
    elif data == "x:fjrm":
        setset("force_join_enabled", "0")
        setset("force_join_chat", "")
        setset("force_join_link", "")
        con=db(); con.execute("DELETE FROM force_join_channels"); con.commit(); con.close()
        await x_force_helper(call)
    elif data == "x:user":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔎 Search User by ID", callback_data="x:usearch")],
            [InlineKeyboardButton(text="➕ New Plan Add", callback_data="x:newplan")],
            [InlineKeyboardButton(text="➖ Plan Remove", callback_data="x:planremove")],
            [InlineKeyboardButton(text="🧾 Transaction Edit", callback_data="x:txedit")],
            [InlineKeyboardButton(text="🗑 Delete ALL Users", callback_data="x:delall")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="x:open")]
        ])
        await call.message.edit_text("<b>👤 USER CONTROL PANEL</b>", reply_markup=kb)
        await call.answer()
    elif data == "x:usearch":
        await state.set_state(AdvancedAdminState.user_id)
        await call.message.answer("<b>🆔 User Telegram ID পাঠান।</b>")
        await call.answer()
    elif data.startswith("x:uc:"):
        parts=data.split(":")
        action=parts[2] if len(parts)>2 else ""
        if action=="confirm":
            d=await state.get_data()
            try:
                uid=int(d['uid']); amount=Decimal(d['pending_amount'])
                if d['field']=='referral_count':
                    con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE"); current=cur.execute("SELECT referral_count FROM users WHERE user_id=?",(uid,)).fetchone()
                    if not current: raise ValueError("User not found")
                    curval=int(current[0] or 0); newval=curval+int(amount) if d['op']=='add' else curval-int(amount)
                    if newval<0: raise ValueError("Referral count cannot be negative")
                    cur.execute("UPDATE users SET referral_count=? WHERE user_id=?",(newval,uid)); cur.execute("INSERT INTO balance_ledger(user_id,field,operation,amount,balance_before,balance_after,admin_id,reference,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(uid,'referral_count',d['op'],float(amount),float(curval),float(newval),call.from_user.id,f"REFCOUNT-{call.from_user.id}-{uuid.uuid4().hex}",now_iso())); con.commit(); con.close()
                else:
                    before,after=balance_operation(uid,d['field'],amount,d['op'],call.from_user.id)
                await state.clear(); await call.answer("✅ Updated",show_alert=True); await show_user_control(call.message,uid,edit=False)
            except ValueError as e:
                await state.clear(); await call.answer(f"❌ {e}",show_alert=True)
            except Exception:
                await state.clear(); await call.answer("❌ Database operation failed.",show_alert=True)
        elif action=="cancel":
            await state.clear(); await call.message.edit_text("<b>❌ Action cancelled.</b>",reply_markup=admin_kb(call.from_user.id)); await call.answer()
        elif action=="field":
            uid=int(parts[3]); field=parts[4]; labels={"referral_balance":"Referral Commission","bonus_balance":"Bonus Balance","deposit_balance":"Deposit Balance","task_balance":"Task Balance"}
            kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Add",callback_data=f"x:uc:amount:{uid}:{field}:add"),InlineKeyboardButton(text="➖ Remove",callback_data=f"x:uc:amount:{uid}:{field}:remove")],[InlineKeyboardButton(text="⬅️ Back",callback_data=f"x:uc:refresh:{uid}")]])
            await call.message.edit_text(f"<b>💰 {labels.get(field,field)}</b>\n<b>একটি action নির্বাচন করুন।</b>",reply_markup=kb); await call.answer()
        elif action=="amount":
            uid=int(parts[3]); field=parts[4]; op=parts[5]
            await state.update_data(uid=uid,field=field,op=op); await state.set_state(UserControlState.amount)
            await call.message.answer(f"<b>{'➕ Add' if op=='add' else '➖ Remove'} {field}</b>\n<b>Amount লিখুন:</b>",reply_markup=cancel_keyboard()); await call.answer()
        elif action=="refcount":
            uid=int(parts[3]); kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Add Referral",callback_data=f"x:uc:amount:{uid}:referral_count:add"),InlineKeyboardButton(text="➖ Remove Referral",callback_data=f"x:uc:amount:{uid}:referral_count:remove")],[InlineKeyboardButton(text="⬅️ Back",callback_data=f"x:uc:refresh:{uid}")]])
            await call.message.edit_text("<b>🎯 Referral Count</b>\n<b>Add বা Remove নির্বাচন করুন।</b>",reply_markup=kb); await call.answer()
        elif action=="message":
            uid=int(parts[3]); await state.update_data(uid=uid); await state.set_state(UserControlState.message); await call.message.answer("<b>💬 Selected User-এর জন্য message লিখুন:</b>",reply_markup=cancel_keyboard()); await call.answer()
        elif action=="msgconfirm":
            d=await state.get_data(); uid=int(d['uid']); txt=d.get('pending_message','')
            if not txt: return await call.answer("❌ Message পাওয়া যায়নি।",show_alert=True)
            try:
                await bot.send_message(uid,txt)
                await state.clear(); await call.answer("✅ Message sent successfully",show_alert=True); await call.message.answer("<b>✅ Message sent successfully.</b>",reply_markup=main_keyboard(call.from_user.id))
            except (TelegramForbiddenError,TelegramBadRequest):
                await state.clear(); await call.answer("❌ User cannot receive messages",show_alert=True)
            except Exception:
                await state.clear(); await call.answer("❌ User cannot receive messages",show_alert=True)
        elif action in ("ban","sus"):
            uid=int(parts[3]); val=int(parts[4])
            if uid==OWNER_ID or uid==ADMIN_ID or role(uid) is not None: return await call.answer("❌ Admin/Owner modify করা যাবে না।",show_alert=True)
            field="banned" if action=="ban" else "suspended"; con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
            try:
                changed=cur.execute(f"UPDATE users SET {field}=? WHERE user_id=? AND {field}<>?",(val,uid,val)).rowcount
                if changed: con.commit()
                else: con.rollback()
            finally: con.close()
            await state.clear(); await call.answer("✅ Updated" if changed else "⚠️ Already in this status",show_alert=True); await show_user_control(call.message,uid)
        elif action=="refresh":
            uid=int(parts[3]); await call.answer("🔄 Refreshed"); await show_user_control(call.message,uid,edit=True)
        elif action=="plans":
            uid=int(parts[3]); expire_user_plans(uid); con=db(); rows=con.execute("SELECT id,plan,amount,expires_at FROM plans WHERE user_id=? AND active=1 ORDER BY id DESC",(uid,)).fetchall(); con.close()
            lines=["<b>👑 PLAN CONTROL</b>","━━━━━━━━━━━━━━━━━━"]+[f"💎 {p} — {money(a)}৳ — expires {utc_dt(e).strftime('%Y-%m-%d %H:%M UTC')}" for pid,p,a,e in rows]
            names=list(get_plans().keys()); kbrows=[[InlineKeyboardButton(text=f"➕ Activate {p}",callback_data=f"x:uc:pactivate:{uid}:{p}")] for p in names]
            for pid,p,a,e in rows: kbrows.append([InlineKeyboardButton(text=f"➖ Remove {p} #{pid}",callback_data=f"x:uc:premove:{uid}:{pid}"),InlineKeyboardButton(text=f"🔄 Extend #{pid}",callback_data=f"x:uc:pextend:{uid}:{pid}")])
            kbrows.append([InlineKeyboardButton(text="⬅️ User",callback_data=f"x:uc:refresh:{uid}")]); await call.message.edit_text("\n".join(lines) if rows else "<b>👑 PLAN CONTROL</b>\n\nকোনো active plan নেই।",reply_markup=InlineKeyboardMarkup(inline_keyboard=kbrows)); await call.answer()
        elif action=="pactivate":
            uid=int(parts[3]); plan=parts[4]; await state.update_data(uid=uid,plan=plan); await state.set_state(UserControlState.plan_name); await call.message.answer(f"<b>👑 {plan} activate</b>\n<b>Duration কত দিন হবে?</b>\n<b>ডিফল্ট 4 দিন হলে 4 লিখুন।</b>",reply_markup=cancel_keyboard()); await call.answer()
        elif action=="premove":
            uid=int(parts[3]); pid=int(parts[4]); con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE"); changed=cur.execute("UPDATE plans SET active=0 WHERE id=? AND user_id=? AND active=1",(pid,uid)).rowcount==1; con.commit() if changed else con.rollback(); con.close(); await call.answer("✅ Plan removed" if changed else "❌ Plan already inactive",show_alert=True); await show_user_control(call.message,uid)
        elif action=="pextend":
            uid=int(parts[3]); pid=int(parts[4]); await state.update_data(uid=uid,pid=pid); await state.set_state(UserControlState.plan_extend); await call.message.answer("<b>⏳ কত দিন extend করবেন?</b>",reply_markup=cancel_keyboard()); await call.answer()
        return
    elif data.startswith("x:ban:"):
        _, _, uid, val = data.split(":")
        uid, val = int(uid), int(val)
        if uid == OWNER_ID:
            return await call.answer("Owner cannot be banned.", show_alert=True)
        con = db()
        con.execute("UPDATE users SET banned=? WHERE user_id=?", (val, uid))
        con.commit()
        con.close()
        await call.answer("Updated")
        await call.message.answer(f"<b>✅ Ban status: {'ON' if val else 'OFF'}</b>")
    elif data.startswith("x:sus:"):
        _, _, uid, val = data.split(":")
        uid, val = int(uid), int(val)
        if uid == OWNER_ID:
            return await call.answer("Owner cannot be suspended.", show_alert=True)
        con = db()
        con.execute("UPDATE users SET suspended=? WHERE user_id=?", (val, uid))
        con.commit()
        con.close()
        await call.answer("Updated")
        await call.message.answer(f"<b>✅ Suspend status: {'ON' if val else 'OFF'}</b>")
    elif data.startswith("x:edit:"):
        _, _, uid, field = data.split(":")
        await state.update_data(uid=int(uid), field=field)
        await state.set_state(AdvancedAdminState.user_value)
        await call.message.answer(f"<b>✏️ {field} এর নতুন মান পাঠান।</b>")
        await call.answer()
    elif data.startswith("x:bmain:"):
        uid = int(data.split(":")[-1])
        await state.update_data(uid=uid, field="bonus_balance")
        await state.set_state(AdvancedAdminState.user_value)
        await call.message.answer("<b>🎁 Bonus Balance থেকে কত টাকা Main Balance-এ transfer করবেন?</b>")
        await call.answer()
    elif data == "x:newplan":
        if not super_ok(call.from_user.id): return await call.answer("❌ শুধু Owner নতুন Plan তৈরি করতে পারবেন।",show_alert=True)
        await state.set_state(UserControlState.plan_name); await state.update_data(mode="newplan_name")
        await call.message.answer("<b>➕ New Plan</b>\n<b>Format:</b> <code>PlanName | Price | Days | DailyRate</code>\n<b>উদাহরণ:</b> <code>VIP13 | 60000 | 4 | 0.34</code>")
        await call.answer()
    elif data == "x:planremove":
        if not super_ok(call.from_user.id): return await call.answer("❌ শুধু Owner Plan remove করতে পারবেন।",show_alert=True)
        con=db(); rows=con.execute("SELECT name,amount,days,enabled FROM plan_catalog ORDER BY rowid").fetchall(); con.close()
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"➖ {n} — {money(a)}৳",callback_data=f"x:prem:{n}")] for n,a,d,e in rows]+[[InlineKeyboardButton(text="⬅️ Back",callback_data="x:user")]])
        await call.message.edit_text("<b>➖ PLAN REMOVE</b>\n\nএকটি Plan select করুন।",reply_markup=kb); await call.answer()
    elif data.startswith("x:prem:"):
        if not super_ok(call.from_user.id): return await call.answer("❌ Owner only",show_alert=True)
        plan=data.split(":",2)[2]
        con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE"); cur.execute("UPDATE plan_catalog SET enabled=0 WHERE name=? AND enabled=1",(plan,)); changed=cur.rowcount==1; con.commit() if changed else con.rollback(); con.close(); await call.answer("✅ Plan removed" if changed else "❌ Plan not found",show_alert=True); await call.message.edit_text("<b>✅ Plan availability updated.</b>",reply_markup=admin_kb(call.from_user.id))
    elif data == "x:plan":
        await state.set_state(AdvancedAdminState.plan_uid)
        await call.message.answer("<b>🆔 User ID পাঠান।</b>")
        await call.answer()
    elif data.startswith("x:padd:"):
        _, _, uid, p = data.split(":")
        uid=int(uid)
        price,days,_,_=plan_meta(p); con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
        try:
            exp=datetime.now(timezone.utc)+timedelta(days=days)
            cur.execute("INSERT INTO plans(user_id,plan,amount,activated_at,expires_at,last_claim_date,active,daily_rate) VALUES(?,?,?,?,?,'',1,?)",(uid,p,float(price),now_iso(),exp.isoformat(),float(_))); con.commit()
        except Exception:
            con.rollback(); con.close(); return await call.answer("❌ Plan activate failed",show_alert=True)
        con.close(); await state.clear(); await call.message.answer(f"<b>✅ {p} added to {uid} for {days} days.</b>"); await call.answer("Added")
    elif data == "x:ubroadcast":
        await state.set_state(AdvancedAdminState.user_broadcast_id)
        await call.message.answer("<b>🆔 User ID পাঠান।</b>")
        await call.answer()
    elif data == "x:broadcast":
        await state.set_state(AdvancedAdminState.broadcast)
        await call.message.answer("<b>📢 Broadcast message লিখুন।</b>")
        await call.answer()
    elif data == "x:bccancel":
        await state.clear()
        await call.message.edit_text("<b>❌ Broadcast cancelled.</b>")
        await call.answer()
    elif data == "x:bcok":
        d=await state.get_data()
        source_chat=d.get("source_chat_id"); source_msg=d.get("source_message_id")
        await state.clear()
        if not source_chat or not source_msg:
            return await call.answer("Broadcast source পাওয়া যায়নি।",show_alert=True)
        con=db()
        ids=[r[0] for r in con.execute("SELECT user_id FROM users WHERE banned=0 AND suspended=0")]
        con.close()
        sent=fail=0
        sem=asyncio.Semaphore(15)
        async def send_one(uid):
            nonlocal sent,fail
            async with sem:
                try:
                    await bot.copy_message(chat_id=uid,from_chat_id=source_chat,message_id=source_msg)
                    sent+=1
                except Exception:
                    fail+=1
        await asyncio.gather(*(send_one(uid) for uid in ids))
        await call.message.edit_text(f"<b>📢 Broadcast finished.</b>\n<b>✅ Sent: {sent}</b>\n<b>❌ Failed: {fail}</b>")
        await call.answer()
    elif data == "x:transactions":
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📥 All Deposits",callback_data="x:tr:deposit:ALL:0")],
            [InlineKeyboardButton(text="📤 All Withdraws",callback_data="x:tr:withdraw:ALL:0")],
            [InlineKeyboardButton(text="⬅️ Back",callback_data="x:open")]
        ])
        await call.message.edit_text("<b>📋 ALL DEPOSIT / WITHDRAW CONTROL</b>\n━━━━━━━━━━━━━━━━━━\n<b>Pending / Processing / Successful / Failed সহ সম্পূর্ণ Transaction History ও User Information এখানে দেখা যাবে।</b>",reply_markup=kb)
        await call.answer()
    elif data.startswith("x:tr:"):
        parts=data.split(":")
        if len(parts)!=5:
            return await call.answer("❌ Invalid transaction filter.",show_alert=True)
        kind,status,page=parts[2],parts[3],int(parts[4])
        await _show_transactions(call,kind,status,page)
    elif data == "x:deps":
        con = db()
        rows = con.execute("SELECT id,user_id,method,amount,txid,order_no,status FROM deposits WHERE status IN ('Pending','Processing') ORDER BY id DESC LIMIT 10").fetchall()
        con.close()
        if not rows:
            return await call.message.answer("<b>📥 No pending deposits.</b>")
        for did, uid, m, a, t, o, s in rows:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Processing", callback_data=f"x:dproc:{did}")],
                [InlineKeyboardButton(text="✅ Approve", callback_data=f"x:dok:{o}"), InlineKeyboardButton(text="❌ Reject", callback_data=f"x:dno:{o}")]
            ])
            await call.message.answer(f"<b>📥 #{did}</b>\n<b>👤 {uid}</b>\n<b>💳 {m}</b>\n<b>💰 {money(a)}৳</b>\n<b>📝 {t}</b>\n<b>🆔 {o}</b>", reply_markup=kb)
        await call.answer()
    elif data.startswith("x:dproc:"):
        try:
            did = int(data.split(":")[-1])
        except ValueError:
            return await call.answer("❌ Invalid deposit ID.",show_alert=True)
        con=db(); dep=con.execute("SELECT order_no,status FROM deposits WHERE id=?",(did,)).fetchone(); con.close()
        if not dep:
            return await call.answer("❌ Deposit Request পাওয়া যায়নি।",show_alert=True)
        order,status=dep
        if status == "Processing":
            changed=True
        else:
            changed=atomic_status_change("deposits","id",did,"Processing",("Pending",))
        if not changed:
            return await call.answer("❌ এই রিকোয়েস্টটি Processing করা যায়নি।",show_alert=True)
        await send_history_event("DEPOSIT_PROCESSING", actor_id=call.from_user.id, reference=str(order), details="Deposit moved to Processing")
        try:
            await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Processing",callback_data=f"x:dproc:{did}")],
                [InlineKeyboardButton(text="✅ Approve",callback_data=f"x:dok:{order}"), InlineKeyboardButton(text="❌ Reject",callback_data=f"x:dno:{order}")]
            ]))
        except Exception:
            pass
        await call.answer("⚙️ Processing")
    elif data.startswith("x:dok:"):
        oid=data.split(":",1)[1]
        try:
            uid,a,t,ref_bonus,old_status,new_status=deposit_decision(oid,"approve",call.from_user.id)
        except ValueError as e:
            msg=str(e)
            if "already processed" in msg:
                return await call.answer("❌ এই রিকোয়েস্টটি ইতিমধ্যে Approved হয়েছে।",show_alert=True)
            if "Request not found" in msg:
                return await call.answer("❌ Deposit Request পাওয়া যায়নি।",show_alert=True)
            return await call.answer(f"❌ {escape(msg)}",show_alert=True)
        except Exception as e:
            return await call.answer("❌ Database operation failed.",show_alert=True)
        try: await send_template(uid,"deposit_approved_message","<b>🎉 Deposit Successful!</b>\n<b>আপনার {amount}৳ Deposit সফল হয়েছে।</b>",amount=money(a),txid=t or "Manual",order=oid)
        except Exception: pass
        await send_history_event("DEPOSIT_APPROVED", actor_id=call.from_user.id, user_id=uid, reference=oid, details=f"Amount: {money(a)}৳; TxID: {t or 'Manual'}; Referral bonus: {money(ref_bonus)}৳")
        try: await call.message.edit_reply_markup(reply_markup=None)
        except Exception: pass
        await call.answer("✅ Approved")
    elif data.startswith("x:dno:"):
        oid=data.split(":",1)[1]
        con=db(); row=con.execute("SELECT status FROM deposits WHERE order_no=?",(oid,)).fetchone(); con.close()
        if not row or row[0] not in ("Pending","Processing"):
            return await call.answer("❌ এই রিকোয়েস্টটি বর্তমানে Reject করা যাবে না।",show_alert=True)
        await state.update_data(kind="deposit",rid=oid)
        await state.set_state(AdvancedAdminState.reject_reason)
        await call.message.answer("<b>❌ Deposit Reject Reason লিখুন।</b>")
        await call.answer()
    elif data == "x:wds":
        con = db()
        rows = con.execute("SELECT id,user_id,method,account,amount,status FROM withdrawals WHERE status IN ('Pending','Processing') ORDER BY id DESC LIMIT 10").fetchall()
        con.close()
        if not rows:
            return await call.message.answer("<b>📤 No pending withdrawals.</b>")
        for wid, uid, m, acc, a, s in rows:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Processing", callback_data=f"x:wproc:{wid}")],
                [InlineKeyboardButton(text="✅ Approve", callback_data=f"x:wok:{wid}"), InlineKeyboardButton(text="❌ Reject", callback_data=f"x:wno:{wid}")]
            ])
            await call.message.answer(f"<b>📤 #{wid}</b>\n<b>👤 {uid}</b>\n<b>💳 {m}</b>\n<b>📲 {acc}</b>\n<b>💰 {money(a)}৳</b>", reply_markup=kb)
        await call.answer()
    elif data.startswith("x:wproc:"):
        wid = int(data.split(":")[-1])
        con = db()
        con.execute("UPDATE withdrawals SET status='Processing',updated_at=? WHERE id=?", (now_iso(), wid))
        con.commit()
        con.close()
        await call.answer("Processing")
    elif data.startswith("x:wok:"):
        wid=int(data.split(":",1)[1])
        con=db(); r=con.execute("SELECT user_id,method,account,amount,status FROM withdrawals WHERE id=?",(wid,)).fetchone(); con.close()
        if not r: return await call.answer("❌ Not found",show_alert=True)
        uid,m,acc,a,s=r
        if not atomic_status_change("withdrawals","id",wid,"Approved",("Pending","Processing")):
            return await call.answer("❌ এই রিকোয়েস্টটি অলরেডি প্রসেস করা হয়েছে।",show_alert=True)
        try: await send_template(uid,"withdraw_approved_message","<b>🎊 Withdraw Completed!</b>\n<b>💰 Amount: {amount}৳</b>",amount=money(a))
        except Exception: pass
        try: await call.message.edit_reply_markup(reply_markup=None)
        except Exception: pass
        await call.answer("✅ Approved")
    elif data.startswith("x:wno:"):
        wid=int(data.split(":",1)[1])
        con=db(); r=con.execute("SELECT user_id,amount,status FROM withdrawals WHERE id=?",(wid,)).fetchone(); con.close()
        if not r: return await call.answer("❌ Not found",show_alert=True)
        uid,a,s=r
        if not atomic_status_change("withdrawals","id",wid,"Rejected",("Pending","Processing")):
            return await call.answer("❌ এই রিকোয়েস্টটি অলরেডি প্রসেস করা হয়েছে।",show_alert=True)
        con=db(); con.execute("UPDATE users SET main_balance=main_balance+? WHERE user_id=?",(a,uid)); con.commit(); con.close()
        await state.update_data(kind="withdraw",rid=wid)
        await state.set_state(AdvancedAdminState.reject_reason)
        await call.message.answer("<b>❌ Withdraw Reject Reason লিখুন।</b>")
        await call.answer()
    elif data == "x:admins":
        if not super_ok(call.from_user.id):
            await call.message.answer("<b>শুধুমাত্র সুপার এডমিন এটি দেখতে পারবে!</b>")
            return await call.answer()
        con = db()
        rows = con.execute("SELECT user_id,role FROM admins ORDER BY user_id").fetchall()
        con.close()
        text = "<b>👑 ADMIN MANAGEMENT</b>\n━━━━━━━━━━━━━━━━━━\n" + ("\n".join(f"<b>🆔 {u} — {r}</b>" for u, r in rows) or "None")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Add Admin", callback_data="x:addadmin"), InlineKeyboardButton(text="➖ Remove Admin", callback_data="x:rmadmin")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="x:open")]
        ])
        await call.message.edit_text(text, reply_markup=kb)
        await call.answer()
    elif data == "x:addadmin":
        if not super_ok(call.from_user.id):
            return await call.answer("Owner only", show_alert=True)
        await state.set_state(AdvancedAdminState.add_admin)
        await call.message.answer("<b>📝 এডমিন আইডি এবং রোল লিখে পাঠান:</b>\n\n<b>ফরম্যাট:</b>\n<code>User_ID | Role</code>\n\n<b>উপলব্ধ রোলস:</b>\n- <code>wth</code> (শুধু উইথড্র)\n- <code>dep</code> (শুধু ডিপোজিট)\n- <code>full</code> (সব এক্সেস)\n- <code>remove</code> (এডমিন বাদ দিতে)")
        await call.answer()
    elif data == "x:rmadmin":
        if not super_ok(call.from_user.id):
            return await call.answer("Owner only", show_alert=True)
        await state.set_state(AdvancedAdminState.remove_admin)
        await call.message.answer("<b>➖ Remove করতে চাওয়া Admin-এর User Telegram ID পাঠান।</b>")
        await call.answer()

async def x_open_historydb_refresh(call: CallbackQuery):
    con=db(); count=con.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]; con.close()
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📜 History Channel: {'🟢 ON' if getset('history_channel_enabled','0')=='1' else '🔴 OFF'}",callback_data="x:historytoggle")],
        [InlineKeyboardButton(text="🔗 Set History Channel",callback_data="x:historyset")],
        [InlineKeyboardButton(text="📋 View Local History",callback_data="x:historyview:0")],
        [InlineKeyboardButton(text="💾 Backup Database Now",callback_data="x:dbbackup")],
        [InlineKeyboardButton(text=f"♻️ Auto Restore: {'🟢 ON' if getset('auto_db_restore','1')=='1' else '🔴 OFF'}",callback_data="x:restoretoggle")],
        [InlineKeyboardButton(text="♻️ Restore Latest Backup",callback_data="x:dbrestore")],
        [InlineKeyboardButton(text="🗑 Delete ALL User History",callback_data="x:historydelete")],
        [InlineKeyboardButton(text="🗑 Delete ALL User Database",callback_data="x:delall")],
        [InlineKeyboardButton(text="⬅️ Back",callback_data="x:open")]
    ])
    await call.message.edit_text(f"<b>📜 HISTORY / DATABASE CONTROL</b>\n━━━━━━━━━━━━━━━━━━\n<b>Local history records:</b> <code>{count}</code>\n<b>Channel:</b> <code>{escape(getset('history_channel_chat','Not set') or 'Not set')}</code>",reply_markup=kb)

async def x_controls_helper(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f'🤖 Bot: {"🟢 ON" if getset("bot_enabled")=="1" else "🔴 OFF"}', callback_data="x:t:bot_enabled")],
        [InlineKeyboardButton(text=f'💰 Fund: {"🟢 ON" if getset("fund_enabled")=="1" else "🔴 OFF"}', callback_data="x:t:fund_enabled")],
        [InlineKeyboardButton(text=f'💸 Withdraw: {"🟢 ON" if getset("withdraw_enabled")=="1" else "🔴 OFF"}', callback_data="x:t:withdraw_enabled")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="x:open")]
    ])
    await call.message.edit_text("<b>⚙️ BOT / MASTER CONTROLS</b>", reply_markup=kb)

async def x_pay_helper(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f'Dep bKash: {"🟢 ON" if getset("dep_bkash_enabled")=="1" else "🔴 OFF"}', callback_data="x:t:dep_bkash_enabled"), InlineKeyboardButton(text=f'Dep Nagad: {"🟢 ON" if getset("dep_nagad_enabled")=="1" else "🔴 OFF"}', callback_data="x:t:dep_nagad_enabled")],
        [InlineKeyboardButton(text=f'Wth bKash: {"🟢 ON" if getset("wth_bkash_enabled")=="1" else "🔴 OFF"}', callback_data="x:t:wth_bkash_enabled"), InlineKeyboardButton(text=f'Wth Nagad: {"🟢 ON" if getset("wth_nagad_enabled")=="1" else "🔴 OFF"}', callback_data="x:t:wth_nagad_enabled")],
        [InlineKeyboardButton(text="⚙️ Deposit Gateway / Manual Control", callback_data="x:methods")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="x:open")]
    ])
    await call.message.edit_text("<b>💳 PAYMENT CONTROLS</b>", reply_markup=kb)

async def x_methods_refresh(call: CallbackQuery):
    con=db()
    rows=con.execute("SELECT name,kind,enabled,logo,number,gateway,manual_enabled,COALESCE(gateway_enabled,0) FROM payment_methods ORDER BY kind,sort_order,id").fetchall()
    con.close()
    text="<b>💳 PAYMENT METHODS</b>\n━━━━━━━━━━━━━━━━━━\n"
    kbrows=[]
    for name,kind,en,logo,num,gw,manual,gw_on in rows:
        if kind!="deposit":
            text += f"<b>{logo} {name}</b> — {'🟢 ON' if en else '🔴 OFF'} — {kind}\n"
            continue
        text += (f"<b>{logo} {name}</b> — {'🟢 Method ON' if en else '🔴 Method OFF'}\n"
                 f"<b>🌐 Gateway:</b> {'🟢 ON' if gw_on else '🔴 OFF'} | <b>📲 Manual:</b> {'🟢 ON' if manual else '🔴 OFF'}\n"
                 f"<b>🔗 Link:</b> <code>{escape(gw or 'Not set')}</code>\n"
                 f"<b>📱 Number:</b> <code>{escape(num or 'Not set')}</code>\n\n")
        kbrows.append([InlineKeyboardButton(text=f"{name} 🌐 {'ON' if gw_on else 'OFF'}",callback_data=f"x:pmgw:{name}"),InlineKeyboardButton(text=f"{name} 📲 {'ON' if manual else 'OFF'}",callback_data=f"x:pmm:{name}")])
        kbrows.append([InlineKeyboardButton(text=f"🔗 {name} Gateway",callback_data=f"x:pmgwedit:{name}"),InlineKeyboardButton(text=f"📱 {name} Number",callback_data=f"x:pmnumedit:{name}")])
    kbrows += [[InlineKeyboardButton(text="➕ Add Method",callback_data="x:addmethod")],[InlineKeyboardButton(text="➖ Remove Method",callback_data="x:rmmethod"),InlineKeyboardButton(text="🔄 Method ON/OFF",callback_data="x:togglemethod")],[InlineKeyboardButton(text="⬅️ Back",callback_data="x:open")]]
    await call.message.edit_text(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=kbrows))
    await call.answer("✅ Updated")

async def x_limits_helper(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f'Min Dep {getset("min_dep")}৳', callback_data="x:v:min_dep"), InlineKeyboardButton(text=f'Max Dep {getset("max_dep")}৳', callback_data="x:v:max_dep")],
        [InlineKeyboardButton(text=f'Min Wth {getset("min_wth")}৳', callback_data="x:v:min_wth"), InlineKeyboardButton(text=f'Max Wth {getset("max_wth")}৳', callback_data="x:v:max_wth")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="x:open")]
    ])
    await call.message.edit_text("<b>📈 LIMIT CONFIGURATION</b>", reply_markup=kb)

async def x_force_helper(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f'📣 Force Join: {"🟢 ON" if getset("force_join_enabled")=="1" else "🔴 OFF"}', callback_data="x:tforce")],
        [InlineKeyboardButton(text="➕ Set Channel", callback_data="x:fjset"), InlineKeyboardButton(text="🗑 Remove", callback_data="x:fjrm")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="x:open")]
    ])
    await call.message.edit_text(
        f'<b>📣 FORCE JOIN</b>\n<b>Chat: {getset("force_join_chat") or "Not set"}</b>',
        reply_markup=kb
    )

@dp.message(AdvancedAdminState.history_channel)
async def x_history_channel(message: Message, state: FSMContext):
    if not super_ok(message.from_user.id): return await state.clear()
    chat=(message.text or '').strip()
    # Easiest private-channel setup: forward any message from that channel to the bot.
    if not chat and getattr(message, 'forward_origin', None):
        origin=getattr(message, 'forward_origin', None)
        origin_chat=getattr(origin, 'chat', None)
        origin_id=getattr(origin_chat, 'id', None)
        if origin_id:
            chat=str(origin_id)
    if not (re.fullmatch(r"-100\d+",chat) or re.fullmatch(r"@[A-Za-z0-9_]{5,32}",chat)):
        return await message.answer("<b>❌ Private channel-এর জন্য -100... Chat ID বা @username দিন। অথবা Channel থেকে যেকোনো একটি message এখানে Forward করুন।</b>")
    setset('history_channel_chat',chat); setset('history_channel_enabled','1'); setset('history_channel_link',DEFAULT_HISTORY_CHANNEL_LINK)
    await state.clear(); await message.answer(f"<b>✅ History Channel saved:</b> <code>{escape(chat)}</code>\n<b>🟢 History logging ON.</b>",reply_markup=main_keyboard(message.from_user.id))
    await send_history_event("HISTORY_CHANNEL_CONFIGURED",actor_id=message.from_user.id,details=f"History destination set to {chat}")

@dp.message(AdvancedAdminState.number)
async def x_num(message: Message, state: FSMContext):
    if not admin_ok(message.from_user.id):
        return
    n = message.text.strip()
    if not re.fullmatch(r"01[3-9]\d{8}", n):
        return await message.answer("<b>❌ সঠিক ১১ ডিজিটের নম্বর দিন।</b>")
    m = (await state.get_data())["method"]
    setset("bkash_number" if m == "bKash" else "nagad_number", n)
    con=db(); con.execute("UPDATE payment_methods SET number=?,manual_enabled=1 WHERE name=? AND kind='deposit'",(n,m)); con.commit(); con.close()
    await state.clear()
    await send_history_event("MANUAL_PAYMENT_NUMBER_CHANGED",actor_id=message.from_user.id,details=f"Method: {m}; Number changed")
    uid = message.from_user.id
    await message.answer(f"<b>✅ {m} number updated: {n}</b>", reply_markup=main_keyboard(uid))

@dp.message(AdvancedAdminState.gateway_url)
async def x_gw(message: Message, state: FSMContext):
    if not admin_ok(message.from_user.id):
        return
    url = message.text.strip()
    if not re.match(r"^https?://", url):
        return await message.answer("<b>❌ Valid http/https URL দিন।</b>")
    m = (await state.get_data())["method"]
    setset("dep_bkash_gateway" if m == "bKash" else "dep_nagad_gateway", url)
    con=db(); con.execute("UPDATE payment_methods SET gateway=?,gateway_enabled=1 WHERE name=? AND kind='deposit'",(url,m)); con.commit(); con.close()
    await state.clear()
    await send_history_event("PAYMENT_GATEWAY_CHANGED",actor_id=message.from_user.id,details=f"Method: {m}; Gateway: {url}")
    uid = message.from_user.id
    await message.answer(f"<b>✅ {m} gateway saved.</b>", reply_markup=main_keyboard(uid))

@dp.message(AdvancedAdminState.generic_value)
async def x_value(message: Message, state: FSMContext):
    if not admin_ok(message.from_user.id):
        return
    try:
        v = Decimal(message.text.strip())
        assert v >= 0
    except Exception:
        return await message.answer("<b>❌ Valid positive number দিন।</b>")
    k = (await state.get_data())["key"]
    setset(k, money(v))
    await send_history_event("ADMIN_SETTING_CHANGED",actor_id=message.from_user.id,details=f"{k} = {money(v)}")
    await state.clear()
    uid = message.from_user.id
    await message.answer(f"<b>✅ {k} = {money(v)} সেট হয়েছে।</b>", reply_markup=main_keyboard(uid))

@dp.message(AdvancedAdminState.force_chat)
async def x_fjchat(message: Message, state: FSMContext):
    if not admin_ok(message.from_user.id):
        return
    await state.update_data(chat=message.text.strip())
    await state.set_state(AdvancedAdminState.force_link)
    await message.answer("<b>🔗 Join link পাঠান।</b>")

@dp.message(AdvancedAdminState.force_link)
async def x_fjlink(message: Message, state: FSMContext):
    if not admin_ok(message.from_user.id):
        return
    link = message.text.strip()
    if not re.match(r"^https?://", link):
        return await message.answer("<b>❌ Valid URL দিন।</b>")
    d = await state.get_data()
    setset("force_join_chat", d["chat"])
    setset("force_join_link", link)
    setset("force_join_enabled", "1")
    con=db()
    con.execute("INSERT OR REPLACE INTO force_join_channels(chat,link,enabled,sort_order) VALUES(?,?,1,COALESCE((SELECT MAX(sort_order)+1 FROM force_join_channels),0))",(d["chat"],link))
    con.commit(); con.close()
    await state.clear()
    uid = message.from_user.id
    await message.answer("<b>✅ Force Join set ও ON হয়েছে।</b>", reply_markup=main_keyboard(uid))

@dp.message(AdvancedAdminState.user_id)
async def x_userid(message: Message, state: FSMContext):
    if not admin_ok(message.from_user.id): return
    try: uid=int((message.text or '').strip())
    except ValueError: return await message.answer("<b>❌ Numeric User ID দিন।</b>")
    if uid<=0: return await message.answer("<b>❌ Valid User ID দিন।</b>")
    if not user_row(uid): await state.clear(); return await message.answer("<b>❌ User পাওয়া যায়নি।</b>",reply_markup=main_keyboard(message.from_user.id))
    await state.clear(); await show_user_control(message,uid)

@dp.message(UserControlState.amount)
async def uc_amount(message: Message,state:FSMContext):
    if not admin_ok(message.from_user.id): return await state.clear()
    d=await state.get_data()
    try: amount=Decimal((message.text or '').strip())
    except Exception: return await message.answer("<b>❌ সঠিক positive amount দিন।</b>")
    if amount<=0: return await message.answer("<b>❌ Amount অবশ্যই 0-এর বেশি হতে হবে।</b>")
    if d.get('field')=='referral_count':
        if amount != amount.to_integral_value(): return await message.answer("<b>❌ Referral count অবশ্যই whole number হতে হবে।</b>")
        r=user_row(int(d['uid'])); current=int(r[11] or 0) if r else 0
        if d.get('op')=='remove' and current<int(amount): return await message.answer("<b>❌ Referral count এত কমানো যাবে না।</b>")
    elif d.get('op')=='remove':
        r=user_row(int(d['uid'])); field=d['field']; idx={'main_balance':3,'deposit_balance':4,'bonus_balance':5,'referral_balance':6,'task_balance':10}.get(field)
        if not r or idx is None or Decimal(str(r[idx] or 0))<amount: return await message.answer("<b>❌ পর্যাপ্ত balance নেই।</b>")
    await state.update_data(pending_amount=str(amount))
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Confirm",callback_data="x:uc:confirm")],[InlineKeyboardButton(text="❌ Cancel",callback_data="x:uc:cancel")]])
    await message.answer(f"<b>⚠️ Confirmation</b>\n\n<b>Action:</b> {d['op']}\n<b>Field:</b> {d['field']}\n<b>User:</b> <code>{d['uid']}</code>\n<b>Amount:</b> {money(amount)}৳\n\nConfirm করবেন?",reply_markup=kb)

@dp.message(UserControlState.message)
async def uc_message(message: Message,state:FSMContext):
    if not admin_ok(message.from_user.id): return await state.clear()
    d=await state.get_data(); uid=int(d['uid']); text_msg=message.text or ''
    if not text_msg.strip(): return await message.answer("<b>❌ Empty message পাঠানো যাবে না।</b>")
    await state.update_data(pending_message=text_msg)
    await message.answer("<b>⚠️ Message confirmation</b>\n\n"+text_msg,reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Send",callback_data="x:uc:msgconfirm")],[InlineKeyboardButton(text="❌ Cancel",callback_data="x:uc:cancel")]]))

@dp.message(UserControlState.plan_name)
async def uc_plan_duration(message: Message,state:FSMContext):
    if not admin_ok(message.from_user.id): return await state.clear()
    d=await state.get_data(); raw=(message.text or '').strip()
    if d.get('mode')=='newplan_name':
        parts=[x.strip() for x in raw.split('|')]
        if len(parts)!=4: return await message.answer("<b>❌ Format: PlanName | Price | Days | DailyRate</b>")
        name=parts[0].upper()
        try: price=Decimal(parts[1]); days=int(parts[2]); rate=Decimal(parts[3])
        except Exception: return await message.answer("<b>❌ Price/Days/DailyRate invalid.</b>")
        if not re.fullmatch(r"VIP[0-9A-Z_-]{1,20}",name) or price<=0 or days<=0 or rate<0: return await message.answer("<b>❌ Plan data invalid.</b>")
        con=db(); exists=con.execute("SELECT 1 FROM plan_catalog WHERE name=?",(name,)).fetchone(); con.close()
        if exists: return await message.answer("<b>❌ এই Plan already exists।</b>")
        con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
        try:
            cur.execute("INSERT INTO plan_catalog(name,amount,emoji,days,enabled,daily_rate) VALUES(?,?,?,?,1,?)",(name,float(price),'💎',days,float(rate))); con.commit()
        except Exception:
            con.rollback(); con.close(); return await state.clear() or await message.answer("<b>❌ Plan create failed.</b>")
        con.close(); await state.clear(); await message.answer(f"<b>✅ {name} created successfully.</b>\n💰 Price: {money(price)}৳\n📅 Days: {days}\n📊 Daily Rate: {rate}",reply_markup=main_keyboard(message.from_user.id)); return
    try: days=int(raw)
    except Exception: return await message.answer("<b>❌ Duration দিন হিসেবে integer দিন।</b>")
    if days<=0 or days>3650: return await message.answer("<b>❌ Duration 1-3650 দিনের মধ্যে দিন।</b>")
    uid=int(d['uid']); plan=d['plan']; con=db(); cur=con.cursor(); cur.execute('BEGIN IMMEDIATE')
    try:
        row=cur.execute("SELECT amount,COALESCE(daily_rate,?) FROM plan_catalog WHERE name=? AND enabled=1",(float(DEMO_DAILY_RATE),plan)).fetchone()
        if not row: raise ValueError
        start_dt=datetime.now(timezone.utc); exp=start_dt+timedelta(days=days)
        cur.execute("INSERT INTO plans(user_id,plan,amount,activated_at,expires_at,last_claim_date,active,daily_rate) VALUES(?,?,?,?,?,'',1,?)",(uid,plan,float(row[0]),start_dt.isoformat(),exp.isoformat(),float(row[1]))); con.commit()
    except Exception:
        con.rollback(); con.close(); await state.clear(); return await message.answer("<b>❌ Plan activate করা যায়নি।</b>")
    con.close(); await state.clear(); await message.answer(f"<b>✅ {plan} User {uid}-এ {days} দিনের জন্য activate হয়েছে।</b>",reply_markup=main_keyboard(message.from_user.id))

@dp.message(UserControlState.plan_extend)
async def uc_plan_extend(message: Message,state:FSMContext):
    if not admin_ok(message.from_user.id): return await state.clear()
    d=await state.get_data()
    try: days=int((message.text or '').strip())
    except Exception: return await message.answer("<b>❌ Positive whole number দিন।</b>")
    if days<=0 or days>3650: return await message.answer("<b>❌ 1-3650 দিনের মধ্যে দিন।</b>")
    con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
    row=cur.execute("SELECT expires_at FROM plans WHERE id=? AND user_id=? AND active=1",(int(d['pid']),int(d['uid']))).fetchone()
    if not row: con.rollback(); con.close(); await state.clear(); return await message.answer("<b>❌ Active plan পাওয়া যায়নি।</b>")
    base=max(utc_dt(row[0]),datetime.now(timezone.utc)); exp=base+timedelta(days=days); cur.execute("UPDATE plans SET expires_at=? WHERE id=? AND user_id=? AND active=1",(exp.isoformat(),int(d['pid']),int(d['uid']))); con.commit(); con.close(); await state.clear(); await message.answer("<b>✅ Plan duration extended.</b>",reply_markup=main_keyboard(message.from_user.id))

@dp.message(AdvancedAdminState.user_value)
async def x_edit_value(message: Message, state: FSMContext):
    if not admin_ok(message.from_user.id):
        return
    d = await state.get_data()
    field, uid = d["field"], d["uid"]
    try:
        v = Decimal(message.text.strip())
        assert v >= 0
    except Exception:
        return await message.answer("<b>❌ Valid positive number দিন।</b>")

    con = db()
    con.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (float(v), uid))
    con.commit()
    con.close()
    await state.clear()
    uid_msg = message.from_user.id
    await message.answer(f"<b>✅ Updated successfully.</b>", reply_markup=main_keyboard(uid_msg))

@dp.message(AdvancedAdminState.plan_uid)
async def x_plan_uid(message: Message, state: FSMContext):
    if not admin_ok(message.from_user.id):
        return
    try:
        uid = int(message.text.strip())
    except ValueError:
        return await message.answer("<b>❌ Numeric ID দিন।</b>")
    if not user_row(uid):
        return await message.answer("<b>❌ User not found.</b>")
    await state.update_data(uid=uid)
    await state.set_state(AdvancedAdminState.plan_name)
    names = list(get_plans())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=p, callback_data=f"x:padd:{uid}:{p}") for p in names[i:i+3]]
        for i in range(0, len(names), 3)
    ])
    await message.answer("<b>💎 Plan নির্বাচন করুন।</b>", reply_markup=kb)

@dp.message(AdvancedAdminState.user_broadcast_id)
async def x_ubid(message: Message, state: FSMContext):
    if not admin_ok(message.from_user.id):
        return
    try:
        uid = int(message.text.strip())
    except ValueError:
        return await message.answer("<b>❌ Numeric ID দিন।</b>")
    if not user_row(uid):
        return await message.answer("<b>❌ User not found.</b>")
    await state.update_data(uid=uid)
    await state.set_state(AdvancedAdminState.user_broadcast_text)
    await message.answer("<b>✉️ Message লিখুন।</b>")

@dp.message(AdvancedAdminState.user_broadcast_text)
async def x_ubtext(message: Message, state: FSMContext):
    if not admin_ok(message.from_user.id):
        return
    d = await state.get_data()
    uid = d["uid"]
    try:
        await bot.send_message(uid, message.text or "")
        out = "<b>✅ Message পাঠানো হয়েছে।</b>"
    except Exception as e:
        out = f"<b>❌ পাঠানো যায়নি: {type(e).__name__}</b>"
    await state.clear()
    uid_msg = message.from_user.id
    await message.answer(out, reply_markup=main_keyboard(uid_msg))

@dp.message(AdvancedAdminState.broadcast)
async def x_bc_preview(message: Message, state: FSMContext):
    if not admin_ok(message.from_user.id): return
    await state.update_data(source_chat_id=message.chat.id, source_message_id=message.message_id)
    kb=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Confirm Broadcast",callback_data="x:bcok"),
        InlineKeyboardButton(text="❌ Cancel",callback_data="x:bccancel")
    ]])
    await message.answer("<b>📢 BROADCAST READY</b>\n\n<b>এই মেসেজটি যেমন আছে—Text, Photo, Video, Document, Caption, Button সহ—সেভাবেই পাঠানো হবে।</b>",reply_markup=kb)

@dp.message(AdvancedAdminState.reject_reason)
async def x_reject_reason(message: Message, state: FSMContext):
    if not admin_ok(message.from_user.id):
        return await state.clear()
    d = await state.get_data()
    kind, rid = d.get("kind"), d.get("rid")
    reason = (message.text or "").strip() or "Rejected by admin."
    try:
        if kind == "deposit":
            uid, amount, txid, ref_bonus, old_status, new_status = deposit_decision(str(rid), "reject", message.from_user.id, reason)
            await send_template(uid,"deposit_rejected_message","<b>❌ Deposit Failed! Reason: {reason}</b>",amount=money(amount),reason=reason)
            await send_history_event("DEPOSIT_REJECTED", actor_id=message.from_user.id, user_id=uid, reference=str(rid), details=f"Amount: {money(amount)}৳; Reason: {reason}")
        else:
            wid=int(rid)
            con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
            row=cur.execute("SELECT user_id,amount,status FROM withdrawals WHERE id=?",(wid,)).fetchone()
            if not row: raise ValueError("Request not found")
            uid,amount,status=row
            if status not in ("Pending","Processing"): raise ValueError("already processed")
            cur.execute("UPDATE withdrawals SET status='Rejected',reason=?,updated_at=? WHERE id=? AND status IN ('Pending','Processing')",(reason,now_iso(),wid))
            if cur.rowcount!=1: raise ValueError("already processed")
            cur.execute("UPDATE users SET main_balance=main_balance+? WHERE user_id=?",(amount,uid))
            con.commit(); con.close()
            await send_template(uid,"withdraw_rejected_message","<b>🚫 WITHDRAW CANCELLED. Reason: {reason}</b>",amount=money(amount),reason=reason)
            await send_history_event("WITHDRAW_REJECTED", actor_id=message.from_user.id, user_id=uid, reference=str(wid), details=f"Amount: {money(amount)}৳; Reason: {reason}")
        await state.clear()
        await message.answer("<b>✅ Status updated successfully.</b>", reply_markup=main_keyboard(message.from_user.id))
    except ValueError as e:
        await state.clear()
        await message.answer(f"<b>❌ {escape(str(e))}</b>", reply_markup=main_keyboard(message.from_user.id))
    except Exception:
        await state.clear()
        await message.answer("<b>❌ Database operation failed.</b>", reply_markup=main_keyboard(message.from_user.id))

@dp.message(AdvancedAdminState.add_admin)
async def x_do_addadmin(message: Message, state: FSMContext):
    if not super_ok(message.from_user.id): return
    parts=[x.strip() for x in (message.text or "").split("|")]
    if len(parts)!=2:
        return await message.answer("<b>❌ Format: User_ID | Role</b>")
    try: uid=int(parts[0])
    except ValueError:
        return await message.answer("<b>❌ Numeric User ID দিন।</b>")
    r=parts[1].lower()
    if r=="remove":
        if uid==OWNER_ID: return await message.answer("<b>❌ Owner-কে remove করা যাবে না।</b>")
        con=db(); con.execute("DELETE FROM admins WHERE user_id=?",(uid,)); con.commit(); con.close()
    elif r in ("wth","dep","full"):
        con=db(); con.execute("INSERT OR REPLACE INTO admins(user_id,role,added_at) VALUES(?,?,?)",(uid,r,now_iso())); con.commit(); con.close()
    else:
        return await message.answer("<b>❌ Role শুধু wth / dep / full / remove হতে পারে।</b>")
    await state.clear()
    await message.answer(f"<b>✅ Admin role updated:</b> <code>{uid}</code> → <code>{r}</code>",reply_markup=main_keyboard(message.from_user.id))

@dp.message(AdvancedAdminState.remove_admin)
async def x_do_rmadmin(message: Message, state: FSMContext):
    if not super_ok(message.from_user.id):
        return
    try:
        uid = int(message.text.strip())
    except ValueError:
        return await message.answer("❌ Numeric ID দিন।")
    if uid == OWNER_ID:
        return await message.answer("<b>❌ Owner-কে সরাতে পারবেন না।</b>")
    con = db()
    con.execute("DELETE FROM admins WHERE user_id=?", (uid,))
    con.commit()
    con.close()
    await state.clear()
    uid_msg = message.from_user.id
    await message.answer(f"<b>✅ Admin {uid} removed.</b>", reply_markup=main_keyboard(uid_msg))


@dp.message(AdvancedAdminState.payment_method)
async def x_payment_method_input(message: Message, state: FSMContext):
    if not admin_ok(message.from_user.id): return
    d=await state.get_data()
    action=d.get("method_action","add")
    pm_name=d.get("pm_name")
    pm_edit_kind=d.get("pm_edit_kind")
    # Dedicated per-method controls: gateway link and manual number are independent.
    if pm_name and pm_edit_kind in ("gateway","number"):
        value=(message.text or "").strip()
        con=db()
        try:
            if pm_edit_kind=="gateway":
                if not re.match(r"^https?://",value):
                    con.close(); return await message.answer("<b>❌ Valid http/https Payment Gateway URL দিন।</b>")
                con.execute("UPDATE payment_methods SET gateway=?,gateway_enabled=1 WHERE name=? AND kind='deposit'",(value,pm_name))
            else:
                if not re.fullmatch(r"01[3-9]\d{8}",value):
                    con.close(); return await message.answer("<b>❌ সঠিক ১১ ডিজিটের bKash/Nagad নম্বর দিন।</b>")
                con.execute("UPDATE payment_methods SET number=?,manual_enabled=1 WHERE name=? AND kind='deposit'",(value,pm_name))
            con.commit()
        finally:
            con.close()
        await state.clear()
        await message.answer(f"<b>✅ {escape(pm_name)} {'Gateway' if pm_edit_kind=='gateway' else 'Manual Number'} saved এবং ON করা হয়েছে।</b>",reply_markup=main_keyboard(message.from_user.id))
        return
    parts=[x.strip() for x in (message.text or "").split("|")]
    con=db()
    try:
        if action=="remove":
            name=(message.text or "").strip()
            con.execute("UPDATE payment_methods SET enabled=0 WHERE name=?", (name,))
        elif action=="toggle":
            name=(message.text or "").strip()
            row=con.execute("SELECT enabled FROM payment_methods WHERE name=?",(name,)).fetchone()
            if not row: raise ValueError
            con.execute("UPDATE payment_methods SET enabled=? WHERE name=?",(0 if row[0] else 1,name))
        elif action=="edit":
            if len(parts)<4: raise ValueError
            name,number,gateway,en=parts[:4]
            gateway="" if gateway=="-" else gateway
            enabled_val=1 if en.lower() in ("on","1","yes") else 0
            con.execute("UPDATE payment_methods SET number=?,gateway=?,enabled=?,gateway_enabled=? WHERE name=?",
                        (number,gateway,enabled_val,1 if gateway else 0,name))
        else:
            if len(parts)<2: raise ValueError
            name,kind=parts[0],parts[1].lower()
            logo=parts[2] if len(parts)>2 and parts[2] else "💳"
            number=parts[3] if len(parts)>3 and parts[3] else ""
            gateway=parts[4] if len(parts)>4 and parts[4] and parts[4]!="-" else ""
            if kind not in ("deposit","withdraw"): raise ValueError
            max_order=con.execute("SELECT COALESCE(MAX(sort_order),0) FROM payment_methods WHERE kind=?",(kind,)).fetchone()[0]
            con.execute("""INSERT INTO payment_methods(name,kind,enabled,logo,number,gateway,manual_enabled,gateway_enabled,sort_order,created_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",(name,kind,1,logo,number,gateway,1 if number else 0,1 if gateway else 0,max_order+1,now_iso()))
        con.commit()
    except (ValueError,sqlite3.IntegrityError):
        con.rollback(); con.close()
        return await message.answer("<b>❌ Format ভুল বা Method আগে থেকেই আছে।</b>")
    con.close(); await state.clear()
    await message.answer("<b>✅ Payment Method settings updated.</b>",reply_markup=main_keyboard(message.from_user.id))

@dp.message(AdvancedAdminState.message_edit)
async def x_message_edit(message: Message, state: FSMContext):
    if not admin_ok(message.from_user.id): return
    d=await state.get_data(); key=d.get("message_key")
    content=message.html_text if message.text else (message.caption or "")
    media_type=""; media_id=""
    if message.photo:
        media_type="photo"; media_id=message.photo[-1].file_id
    elif message.video:
        media_type="video"; media_id=message.video.file_id
    elif message.document:
        media_type="document"; media_id=message.document.file_id
    elif message.animation:
        media_type="animation"; media_id=message.animation.file_id
    if not content and not media_id:
        return await message.answer("<b>❌ Text/Caption/Photo সহ একটি মেসেজ দিন।</b>")
    setset(key,content)
    set_template(key,content,media_type,media_id)
    await send_history_event("MESSAGE_TEMPLATE_CHANGED",actor_id=message.from_user.id,details=f"Template: {key}")
    if key == "daily_demo_warning":
        # Keep the existing earnings message key in sync so the old earning flow is not changed.
        setset("demo_notice",content)
        set_template("demo_notice",content,media_type,media_id)
    await state.clear()
    await message.answer("<b>✅ Message template saved.</b>",reply_markup=main_keyboard(message.from_user.id))

@dp.callback_query(F.data == "x:txedit")
async def x_txedit(call: CallbackQuery,state:FSMContext):
    await state.set_state(AdvancedAdminState.transaction_edit)
    await call.message.answer("<b>🧾 Format:</b>\n<code>deposit | ORDER_NO | status | amount</code>\n<code>withdraw | ID | status | amount</code>\n\nStatus: Pending / Processing / Approved / Rejected")
    await call.answer()

@dp.message(AdvancedAdminState.transaction_edit)
async def x_transaction_edit(message: Message,state:FSMContext):
    if not admin_ok(message.from_user.id): return
    p=[x.strip() for x in (message.text or "").split("|")]
    if len(p)<3:
        return await message.answer("<b>❌ Format সঠিক নয়।</b>")
    kind,key,status=p[:3]; amount=p[3] if len(p)>3 else None
    if status not in ("Pending","Processing","Approved","Rejected"):
        return await message.answer("<b>❌ Invalid status.</b>")
    con=db(); cur=con.cursor()
    try:
        if kind.lower()=="deposit":
            row=cur.execute("SELECT id,user_id,status,amount FROM deposits WHERE order_no=?",(key,)).fetchone()
            if not row: raise ValueError
            did,uid,old,old_amount=row
            new_amount=float(Decimal(amount)) if amount else old_amount
            cur.execute("UPDATE deposits SET status=?,amount=?,updated_at=? WHERE id=?",(status,new_amount,now_iso(),did))
            # Repair balance when changing the financial outcome.
            if old!="Approved" and status=="Approved":
                cur.execute("UPDATE users SET deposit_balance=deposit_balance+? WHERE user_id=?",(new_amount,uid))
            elif old=="Approved" and status!="Approved":
                cur.execute("UPDATE users SET deposit_balance=MAX(0,deposit_balance-?) WHERE user_id=?",(old_amount,uid))
        elif kind.lower()=="withdraw":
            row=cur.execute("SELECT id,user_id,status,amount FROM withdrawals WHERE id=?",(int(key),)).fetchone()
            if not row: raise ValueError
            wid,uid,old,old_amount=row
            new_amount=float(Decimal(amount)) if amount else old_amount
            cur.execute("UPDATE withdrawals SET status=?,amount=?,updated_at=? WHERE id=?",(status,new_amount,now_iso(),wid))
            if old!="Rejected" and status=="Rejected":
                cur.execute("UPDATE users SET main_balance=main_balance+? WHERE user_id=?",(new_amount,uid))
            elif old=="Rejected" and status not in ("Rejected","Pending","Processing"):
                cur.execute("UPDATE users SET main_balance=main_balance-? WHERE user_id=? AND main_balance>=?",(new_amount,uid,new_amount))
            # Approved withdrawals were already deducted at request creation.
        else: raise ValueError
        con.commit()
    except Exception:
        con.rollback(); con.close(); await state.clear()
        return await message.answer("<b>❌ Transaction update failed.</b>",reply_markup=main_keyboard(message.from_user.id))
    con.close(); await state.clear()
    await message.answer("<b>✅ Transaction history/status updated successfully.</b>",reply_markup=main_keyboard(message.from_user.id))

@dp.callback_query(F.data == "x:delall")
async def x_delete_all_users(call: CallbackQuery):
    if not super_ok(call.from_user.id):
        return await call.answer("❌ Owner only.",show_alert=True)
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ YES, DELETE ALL USER DATA",callback_data="x:delall_confirm")],
        [InlineKeyboardButton(text="Cancel",callback_data="x:open")]
    ])
    await call.message.answer("<b>⚠️ সতর্কতা</b>\nসব user, deposit, withdraw, plans, earnings, bonus data মুছে যাবে। এটি ফিরিয়ে আনা যাবে না।",reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data == "x:delall_confirm")
async def x_delete_all_users_confirm(call: CallbackQuery):
    if not super_ok(call.from_user.id):
        return await call.answer("❌ Owner only.",show_alert=True)
    if getset('auto_db_backup','1') == '1': backup_database()
    con=db()
    for table in ("users","deposits","withdrawals","plans","earnings","bonuses","balance_ledger","payment_sessions"):
        con.execute(f"DELETE FROM {table}")
    con.commit(); con.close()
    await send_history_event("ALL_USER_DATABASE_DELETED",actor_id=call.from_user.id,details="All user/financial records deleted; latest backup preserved for restore")
    await call.message.edit_text("<b>✅ All user database records deleted.</b>\n<b>💾 Latest backup রাখা হয়েছে। চাইলে Restore Latest Backup দিয়ে ফিরিয়ে আনতে পারবেন।</b>")
    await call.answer("Deleted")


async def sync_bot_commands():
    con=db()
    rows=con.execute("SELECT command,title,enabled FROM bot_commands WHERE enabled=1 ORDER BY command").fetchall()
    con.close()
    commands=[
        BotCommand(command="start",description="🚀 Start Bot"),
        BotCommand(command="menu",description="🏠 Main Menu"),
        BotCommand(command="help",description="🆘 Help Center")
    ]
    commands += [BotCommand(command=c,description=(t or c)[:256]) for c,t,e in rows if c not in ("start","menu","help")]
    try: await bot.set_my_commands(commands)
    except Exception: pass

@dp.message(AdvancedAdminState.command_edit)
async def x_command_edit(message: Message,state:FSMContext):
    if not admin_ok(message.from_user.id): return
    d=await state.get_data(); action=d.get("command_action","add")
    raw=(message.text or "").strip()
    con=db()
    try:
        if action=="remove":
            cmd=raw.lstrip("/")
            con.execute("DELETE FROM bot_commands WHERE command=?",(cmd,))
        else:
            p=[x.strip() for x in raw.split("|",3)]
            if len(p)!=4: raise ValueError
            cmd,title,textmsg,pos=p
            cmd=cmd.lstrip("/").lower()
            if not re.fullmatch(r"[a-z0-9_]{1,32}",cmd): raise ValueError
            if pos not in ("top","bottom","left","right","up","down"): pos="bottom"
            con.execute("""INSERT INTO bot_commands(command,title,enabled,position,message_key,updated_at)
                           VALUES(?,?,1,?,?,?) ON CONFLICT(command) DO UPDATE SET title=excluded.title,
                           enabled=1,position=excluded.position,message_key=excluded.message_key,updated_at=excluded.updated_at""",
                        (cmd,title,pos,textmsg,now_iso()))
            # message_key column is used as the actual response text for custom commands.
        con.commit()
    except Exception:
        con.rollback(); con.close(); await state.clear()
        return await message.answer("<b>❌ Command format ভুল।</b>",reply_markup=main_keyboard(message.from_user.id))
    con.close(); await state.clear(); await sync_bot_commands()
    await message.answer("<b>✅ Command updated.</b>",reply_markup=main_keyboard(message.from_user.id))

@dp.message()
async def dynamic_command_handler(message: Message):
    if not message.text or not message.text.startswith("/"): return
    cmd=message.text.split()[0].split("@")[0].lstrip("/").lower()
    con=db(); row=con.execute("SELECT message_key,enabled FROM bot_commands WHERE command=?",(cmd,)).fetchone(); con.close()
    if row and row[1]:
        await message.answer(row[0] or "<b>Command configured.</b>")

# =========================
# TELEGRAM WEB MINI APP
# =========================
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("PORT", os.getenv("WEB_PORT", "8080")))
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://ttkpypayamentgatway-production.up.railway.app").rstrip("/")
WEBAPP_MAX_AGE = 86400
app = FastAPI(title="NIKAN EARN Web Mini App")

WEB_APP_HTML = r'''<!doctype html>
<html lang="bn"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><title>𝗡𝗶𝗸𝗮𝗻 𝗘𝗮𝗿𝗻</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--bg:#07101d;--card:#0d1a2b;--card2:#12233a;--text:#f7fbff;--muted:#8ea2ba;--accent:#5ee7b7;--accent2:#6ea8ff;--danger:#ff6b7a;--border:rgba(255,255,255,.09)}*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:radial-gradient(circle at 20% 0%,#17345a 0,#07101d 45%,#050b14 100%);color:var(--text);min-height:100vh}.wrap{max-width:760px;margin:auto;padding:16px 14px 100px}.hero{padding:20px 4px 12px;animation:up .45s ease}.hero h1{font-size:28px;margin:0 0 5px}.hero p{color:var(--muted);margin:0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.card{background:linear-gradient(145deg,rgba(18,35,58,.94),rgba(9,21,35,.94));border:1px solid var(--border);border-radius:20px;padding:15px;box-shadow:0 10px 35px rgba(0,0,0,.2);animation:up .4s ease}.balance{grid-column:1/-1}.label{color:var(--muted);font-size:13px}.value{font-size:25px;font-weight:800;margin-top:4px}.btn{border:0;border-radius:14px;padding:13px 14px;color:var(--text);background:var(--card2);width:100%;font-weight:750;margin-top:8px;min-height:46px}.btn.primary{background:linear-gradient(135deg,#55dcae,#5d9bff);color:#06111d}.btn.danger{background:rgba(255,107,122,.14);color:#ff9aa5}.btn:active{transform:scale(.98)}input,select{width:100%;padding:13px;border-radius:13px;border:1px solid var(--border);background:#081422;color:var(--text);font-size:16px;margin-top:8px}.section{margin-top:14px}.section h2{font-size:18px}.plan{display:flex;justify-content:space-between;gap:10px;align-items:center}.small{font-size:12px;color:var(--muted)}.nav{position:fixed;left:50%;bottom:10px;transform:translateX(-50%);width:min(94%,720px);background:rgba(8,18,31,.94);backdrop-filter:blur(14px);border:1px solid var(--border);border-radius:18px;padding:8px;display:grid;grid-template-columns:repeat(5,1fr);gap:5px;z-index:5}.nav button{background:transparent;border:0;color:var(--muted);padding:9px 4px;border-radius:12px;font-size:11px}.nav button.active{background:rgba(94,231,183,.12);color:var(--accent)}.toast{position:fixed;top:14px;left:50%;transform:translate(-50%,-20px);opacity:0;background:#12233a;border:1px solid var(--border);padding:11px 15px;border-radius:12px;z-index:10;transition:.25s}.toast.show{opacity:1;transform:translate(-50%,0)}.hidden{display:none!important}.row{display:flex;justify-content:space-between;gap:10px;align-items:center}.badge{padding:5px 9px;border-radius:99px;background:rgba(94,231,183,.1);color:var(--accent);font-size:11px}@keyframes up{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}@media(max-width:430px){.grid{grid-template-columns:1fr}.balance{grid-column:auto}.hero h1{font-size:25px}}
</style></head><body><div id="toast" class="toast"></div><main class="wrap">
<div class="hero"><h1>𝗡𝗶𝗸𝗮𝗻 𝗘𝗮𝗿𝗻</h1><p id="hello">লোড হচ্ছে…</p></div>
<section id="force" class="card hidden"></section>
<section id="home" class="page"><div class="grid"><div class="card balance"><div class="label">💰 Main Balance</div><div class="value" id="main">0৳</div><div class="small" id="total">Total Earnings: 0৳</div></div><div class="card"><div class="label">📥 Deposit</div><div class="value" id="dep">0৳</div></div><div class="card"><div class="label">🎁 Bonus</div><div class="value" id="bonus">0৳</div></div><div class="card"><div class="label">👥 Referral</div><div class="value" id="ref">0৳</div></div><div class="card"><div class="label">👨‍💻 Task</div><div class="value" id="task">0৳</div></div></div><div class="section grid"><button class="btn primary" onclick="go('plans')">💎 Available Plans</button><button class="btn" onclick="go('deposit')">🔐 Deposit</button><button class="btn" onclick="go('withdraw')">💸 Withdraw</button><button class="btn" onclick="claim()">📊 Claim Earnings</button></div></section>
<section id="plans" class="page hidden"><div class="card"><h2>💎 Available Plans</h2><div id="plansList"></div></div></section>
<section id="deposit" class="page hidden"><div class="card"><h2>🔐 Deposit</h2><select id="depMethod"></select><input id="depAmount" type="number" min="1" placeholder="Amount (৳)"><button class="btn primary" onclick="createDeposit()">Continue Payment</button><div id="depSession" class="section"></div></div></section>
<section id="withdraw" class="page hidden"><div class="card"><h2>💸 Withdraw</h2><select id="wdMethod"></select><input id="wdAccount" inputmode="numeric" placeholder="01XXXXXXXXX"><input id="wdAmount" type="number" min="1" placeholder="Amount (৳)"><button class="btn primary" onclick="createWithdraw()">Submit Withdraw</button></div></section>
<section id="referral" class="page hidden"><div class="card"><h2>👥 Referral</h2><div class="value" id="refCount">0</div><div class="small">Total Referrals</div><input id="refLink" readonly><button class="btn primary" onclick="copyRef()">Copy Referral Link</button></div></section>
<section id="history" class="page hidden"><div class="card"><h2>🧾 Transaction History</h2><div id="historyList">লোড হচ্ছে…</div></div></section>
<section id="admin" class="page hidden"><div class="card"><h2>🔧 Admin Overview</h2><div id="adminText">Loading…</div></div></section>
</main><nav class="nav"><button data-p="home" onclick="go('home')">🏠<br>Home</button><button data-p="deposit" onclick="go('deposit')">💳<br>Deposit</button><button data-p="plans" onclick="go('plans')">💎<br>Plans</button><button data-p="referral" onclick="go('referral')">👥<br>Referral</button><button data-p="history" onclick="go('history')">🧾<br>History</button></nav>
<script>
const tg=window.Telegram?.WebApp; tg?.ready(); tg?.expand(); const initData=tg?.initData||''; let me=null;
const $=id=>document.getElementById(id); const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
function toast(s){$('toast').textContent=s;$('toast').classList.add('show');setTimeout(()=>$('toast').classList.remove('show'),2200)}
async function api(path,opt={}){opt.headers={'Content-Type':'application/json','X-Telegram-Init-Data':initData,...(opt.headers||{})};const r=await fetch(path,opt);const j=await r.json().catch(()=>({error:'Server response error'}));if(!r.ok)throw Error(j.error||'Request failed');return j}
function go(p){document.querySelectorAll('.page').forEach(x=>x.classList.add('hidden'));$(p)?.classList.remove('hidden');document.querySelectorAll('.nav button').forEach(x=>x.classList.toggle('active',x.dataset.p===p));if(p==='plans')loadPlans();if(p==='deposit')loadMethods();if(p==='withdraw')loadMethods();if(p==='history')loadHistory();if(p==='referral')loadReferral();if(p==='admin')loadAdmin()}
function renderMe(){if(!me)return;$('hello').textContent=`স্বাগতম, ${me.name||'User'} • ID ${me.user_id}`;$('main').textContent=me.main_balance+'৳';$('dep').textContent=me.deposit_balance+'৳';$('bonus').textContent=me.bonus_balance+'৳';$('ref').textContent=me.referral_balance+'৳';$('task').textContent=me.task_balance+'৳';$('total').textContent='Total Earnings: '+me.total_earnings+'৳'}
async function load(){try{const j=await api('/api/me');if(j.force_join?.required){$('force').classList.remove('hidden');$('force').innerHTML='<h3>🔒 Channel Join Required</h3>'+j.force_join.channels.map(c=>`<a class="btn" style="display:block;text-decoration:none;text-align:center" href="${esc(c.link)}" target="_blank">📢 ${esc(c.name||'Join Channel')}</a>`).join('')+'<button class="btn primary" onclick="verifyJoin()">✅ I Joined — Verify</button>'}me=j.user;renderMe();await loadPlans();}catch(e){toast(e.message)}}
async function verifyJoin(){try{const j=await api('/api/force-join');if(!j.required){$('force').classList.add('hidden');toast('✅ Verified')}else toast('❌ Join required')}}
async function loadPlans(){try{const j=await api('/api/plans');$('plansList').innerHTML=j.plans.map(p=>`<div class="card plan" style="margin-top:9px"><div><b>💎 ${esc(p.name)}</b><div class="small">${p.amount}৳ • ${p.days} days • Daily ${p.daily}৳</div></div><button class="btn primary" style="width:auto;margin:0" onclick="buyPlan('${encodeURIComponent(p.name)}')">Buy</button></div>`).join('')}catch(e){toast(e.message)}}
async function buyPlan(p){try{const j=await api('/api/plans/buy',{method:'POST',body:JSON.stringify({plan:decodeURIComponent(p)})});toast(j.message||'Activated');await load()}catch(e){toast(e.message)}}
async function loadMethods(){try{const j=await api('/api/methods');$('depMethod').innerHTML=j.deposit.map(x=>`<option value="${esc(x.name)}">${esc(x.logo)} ${esc(x.name)}</option>`).join('');$('wdMethod').innerHTML=j.withdraw.map(x=>`<option value="${esc(x.name)}">${esc(x.logo)} ${esc(x.name)}</option>`).join('')}catch(e){toast(e.message)}}
async function createDeposit(){try{const amount=Number($('depAmount').value),method=$('depMethod').value;if(!amount||amount<=0)throw Error('সঠিক amount দিন');const j=await api('/api/deposit/session',{method:'POST',body:JSON.stringify({amount,method})});$('depSession').innerHTML=`<div class="card"><b>💳 ${esc(j.method)} — ${j.amount}৳</b>${j.gateway_url?`<a class="btn primary" href="${esc(j.gateway_url)}" target="_blank">🌐 Payment Gateway</a>`:''}${j.manual_number?`<p class="small">📲 Manual: <b>${esc(j.manual_number)}</b></p>`:''}<input id="txid" placeholder="Transaction ID"><button class="btn primary" onclick="submitTx('${esc(j.session_id)}')">🧾 আমি পেমেন্ট করেছি</button><button class="btn danger" onclick="cancelTx('${esc(j.session_id)}')">❌ Cancel</button></div>`}catch(e){toast(e.message)}}
async function submitTx(sid){try{const tx=$('txid').value.trim();const j=await api('/api/deposit/submit',{method:'POST',body:JSON.stringify({session_id:sid,transaction_id:tx})});$('depSession').innerHTML='';toast(j.message);await load()}catch(e){toast(e.message)}}
async function cancelTx(sid){try{const j=await api('/api/deposit/cancel',{method:'POST',body:JSON.stringify({session_id:sid})});$('depSession').innerHTML='';toast(j.message)}catch(e){toast(e.message)}}
async function createWithdraw(){try{const j=await api('/api/withdraw',{method:'POST',body:JSON.stringify({method:$('wdMethod').value,account:$('wdAccount').value.trim(),amount:Number($('wdAmount').value)})});toast(j.message);await load()}catch(e){toast(e.message)}}
async function claim(){try{const j=await api('/api/claim',{method:'POST'});toast(j.message);await load()}catch(e){toast(e.message)}}
async function loadReferral(){try{const j=await api('/api/referral');$('refCount').textContent=j.referral_count;$('refLink').value=j.link}catch(e){toast(e.message)}}
async function copyRef(){const v=$('refLink').value;try{await navigator.clipboard.writeText(v);toast('✅ Copied')}catch{toast(v)}}
async function loadHistory(){try{const j=await api('/api/history');$('historyList').innerHTML=j.items.length?j.items.map(x=>`<div class="card" style="margin-top:8px"><div class="row"><b>${esc(x.type)}</b><span class="badge">${esc(x.status||'')}</span></div><div class="small">${esc(x.amount||'')} ${x.method?esc(x.method):''}<br>${esc(x.date||'')}</div></div>`).join(''):'কোনো history নেই।'}catch(e){toast(e.message)}}
async function loadAdmin(){try{const j=await api('/api/admin/overview');$('adminText').innerHTML=`Users: <b>${j.users}</b><br>Pending Deposits: <b>${j.pending_deposits}</b><br>Pending Withdrawals: <b>${j.pending_withdrawals}</b>`}catch(e){toast(e.message)}}
load();go('home');
</script></body></html>'''
def _web_validate_init_data(init_data: str):
    if not init_data or not BOT_TOKEN:
        raise ValueError("Telegram WebApp authorization missing")
    pairs=dict(parse_qsl(init_data, keep_blank_values=True))
    received=pairs.pop("hash",None)
    if not received: raise ValueError("Invalid Telegram WebApp data")
    auth_date=int(pairs.get("auth_date","0") or 0)
    if auth_date and datetime.now(timezone.utc).timestamp()-auth_date>WEBAPP_MAX_AGE: raise ValueError("Telegram WebApp session expired")
    data_check="\n".join(f"{k}={v}" for k,v in sorted(pairs.items()))
    secret=hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected=hmac.new(secret,data_check.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,received): raise ValueError("Telegram WebApp authorization failed")
    user=json.loads(pairs.get("user","{}"))
    uid=int(user.get("id",0))
    if not uid: raise ValueError("Telegram user missing")
    return uid,user

def _web_uid(request: Request):
    init=request.headers.get("X-Telegram-Init-Data","")
    return _web_validate_init_data(init)

def _web_force_join(uid:int):
    if getset("force_join_enabled","0")!="1": return {"required":False,"channels":[]}
    con=db(); rows=con.execute("SELECT chat,link FROM force_join_channels WHERE enabled=1 ORDER BY sort_order,id").fetchall(); con.close()
    if not rows:
        c=getset("force_join_chat",""); l=getset("force_join_link",""); rows=[(c,l)] if c and l else []
    # Telegram membership is checked asynchronously by the bot API in /api/force-join.
    return {"required":bool(rows),"channels":[{"name":r[0],"link":r[1]} for r in rows]}

def _web_user(uid):
    con=db(); r=con.execute("SELECT user_id,name,username,main_balance,deposit_balance,bonus_balance,referral_balance,total_earnings,task_balance,referral_count,banned,suspended FROM users WHERE user_id=?",(uid,)).fetchone(); con.close()
    if not r: raise ValueError("User account not found")
    return {"user_id":r[0],"name":r[1] or "","username":r[2] or "","main_balance":money(r[3]),"deposit_balance":money(r[4]),"bonus_balance":money(r[5]),"referral_balance":money(r[6]),"total_earnings":money(r[7]),"task_balance":money(r[8]),"referral_count":r[9],"banned":bool(r[10]),"suspended":bool(r[11])}

def _web_error(e): return JSONResponse({"error":str(e)},status_code=400)

@app.get("/health")
async def web_health(): return {"ok":True,"service":"NIKAN EARN Web Mini App"}

@app.get("/miniapp/",response_class=HTMLResponse)
async def miniapp_page(): return HTMLResponse(WEB_APP_HTML)

@app.get("/api/me")
async def api_me(request:Request):
    try:
        uid,_=_web_uid(request); return {"user":_web_user(uid),"force_join":_web_force_join(uid)}
    except Exception as e: return _web_error(e)

@app.get("/api/force-join")
async def api_force_join(request:Request):
    try:
        uid,_=_web_uid(request); ok=await check_force_join(uid); f=_web_force_join(uid); f["required"]=not ok; return f
    except Exception as e: return _web_error(e)

@app.get("/api/plans")
async def api_plans(request:Request):
    try:
        uid,_=_web_uid(request); expire_user_plans(uid); out=[]
        for n,a in get_plans().items():
            price,days,emoji,rate=plan_meta(n); out.append({"name":n,"amount":money(price),"days":days,"daily":money(price*rate),"emoji":emoji})
        return {"plans":out}
    except Exception as e:return _web_error(e)

@app.post("/api/plans/buy")
async def api_buy_plan(request:Request):
    try:
        uid,_=_web_uid(request); body=await request.json(); plan=str(body.get("plan","")).strip()
        if not plan: raise ValueError("Plan পাওয়া যায়নি")
        con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
        try:
            cur.execute("UPDATE plans SET active=0 WHERE user_id=? AND active=1 AND expires_at<=?",(uid,now_iso()))
            row=cur.execute("SELECT amount,days,COALESCE(daily_rate,?) FROM plan_catalog WHERE name=? AND enabled=1",(float(DEMO_DAILY_RATE),plan)).fetchone()
            if not row: raise ValueError("Plan পাওয়া যায়নি")
            price=Decimal(str(row[0])); days=int(row[1]); rate=Decimal(str(row[2]))
            if cur.execute("SELECT COUNT(*) FROM plans WHERE user_id=? AND plan=? AND active=1",(uid,plan)).fetchone()[0]>=2: raise ValueError("এই Plan-এর সর্বোচ্চ ২টি active instance অনুমোদিত")
            u=cur.execute("SELECT main_balance,deposit_balance,banned,suspended FROM users WHERE user_id=?",(uid,)).fetchone()
            if not u: raise ValueError("User account পাওয়া যায়নি")
            if u[2] or u[3]: raise ValueError("Account বর্তমানে restricted")
            main=Decimal(str(u[0] or 0)); dep=Decimal(str(u[1] or 0)); avail=main+dep
            if avail<price: raise ValueError(f"আপনার ডিপোজিট ও মেইন ব্যালেন্সে পর্যাপ্ত টাকা নেই। প্রয়োজন আরও {money(price-avail)}৳")
            fm=min(main,price); fd=price-fm
            if cur.execute("UPDATE users SET main_balance=main_balance-?,deposit_balance=deposit_balance-? WHERE user_id=? AND main_balance>=? AND deposit_balance>=?",(float(fm),float(fd),uid,float(fm),float(fd))).rowcount!=1: raise ValueError("Balance changed; please retry")
            activated=datetime.now(timezone.utc); expires=activated+timedelta(days=days)
            cur.execute("INSERT INTO plans(user_id,plan,amount,activated_at,expires_at,last_claim_date,active,daily_rate) VALUES(?,?,?,?,?,'',1,?)",(uid,plan,float(price),activated.isoformat(),expires.isoformat(),float(rate)))
            pid=cur.lastrowid
            cur.execute("INSERT INTO balance_ledger(user_id,field,operation,amount,balance_before,balance_after,admin_id,reference,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(uid,"plan_purchase","remove",float(price),float(avail),float(avail-price),uid,f"WEB-PLAN-{pid}",now_iso()))
            con.commit()
        except: con.rollback(); raise
        finally: con.close()
        await send_history_event("PLAN_PURCHASE",actor_id=uid,user_id=uid,reference=f"WEB-PLAN-{pid}",details=f"Plan: {plan}; Price: {money(price)}৳; Duration: {days} days")
        return {"ok":True,"message":f"✅ {plan} Plan successfully activated!","user":_web_user(uid)}
    except Exception as e:return _web_error(e)

@app.get("/api/methods")
async def api_methods(request:Request):
    try:
        _web_uid(request); return {"deposit":[{"name":r[0],"logo":r[1]} for r in payment_methods("deposit")],"withdraw":[{"name":r[0],"logo":r[1]} for r in payment_methods("withdraw")]}
    except Exception as e:return _web_error(e)

@app.post("/api/deposit/session")
async def api_deposit_session(request:Request):
    try:
        uid,_=_web_uid(request); b=await request.json(); method=str(b.get("method","")).strip(); amount=Decimal(str(b.get("amount",0)))
        mn=Decimal(getset("min_dep","50")); mx=Decimal(getset("max_dep","10000")); cfg=get_payment_method_config(method,"deposit")
        if amount<mn or amount>mx: raise ValueError(f"Deposit {money(mn)}৳ থেকে {money(mx)}৳ এর মধ্যে হতে হবে")
        if not cfg: raise ValueError("এই Deposit Method বর্তমানে বন্ধ আছে")
        gateway_on=bool(cfg[5] and cfg[3]); manual=bool(cfg[4])
        if not gateway_on and not manual: raise ValueError("Manual ও Gateway দুটোই OFF")
        sid,expires=create_payment_session(uid,amount,method,cfg[3] if gateway_on else "")
        url=build_payment_url(cfg[3],amount,uid,method,sid,sid) if gateway_on else ""
        return {"session_id":sid,"amount":money(amount),"method":method,"gateway_url":url,"manual_number":cfg[2] if manual else "","expires_at":expires}
    except Exception as e:return _web_error(e)

@app.post("/api/deposit/submit")
async def api_deposit_submit(request:Request):
    try:
        uid,_=_web_uid(request); b=await request.json(); sid=str(b.get("session_id","")).strip(); tx=normalize_txid(str(b.get("transaction_id","") or ""))
        if len(tx)<3 or len(tx)>128 or not re.fullmatch(r"[a-z0-9._:/-]+",tx): raise ValueError("Transaction ID-এর format সঠিক নয়")
        con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
        try:
            sess=cur.execute("SELECT id,amount,payment_method,status,expires_at FROM payment_sessions WHERE session_id=? AND user_id=?",(sid,uid)).fetchone()
            if not sess or sess[3]!="ACTIVE": raise ValueError("এই সেশনটি বর্তমানে উপলব্ধ নেই")
            if datetime.now(timezone.utc)>=utc_dt(sess[4]): cur.execute("UPDATE payment_sessions SET status='EXPIRED' WHERE id=? AND status='ACTIVE'",(sess[0],)); raise ValueError("এই সেশনের মেয়াদ শেষ হয়ে গেছে")
            if cur.execute("SELECT id FROM deposits WHERE lower(trim(txid))=? LIMIT 1",(tx,)).fetchone():
                cur.execute("UPDATE payment_sessions SET status='CANCELLED',transaction_id=?,submitted_at=? WHERE id=?",(tx,now_iso(),sess[0])); con.commit(); raise ValueError("এই Transaction ID আগে ব্যবহার করা হয়েছে")
            order=order_no(); cur.execute("INSERT INTO deposits(user_id,method,amount,txid,order_no,status,reason,created_at,updated_at) VALUES(?,?,?,?,?,'Pending','',?,?)",(uid,sess[2],float(sess[1]),tx,order,now_iso(),now_iso())); did=cur.lastrowid
            cur.execute("UPDATE payment_sessions SET status='PENDING',transaction_id=?,submitted_at=? WHERE id=? AND status='ACTIVE'",(tx,now_iso(),sess[0]));
            if cur.rowcount!=1: raise ValueError("এই সেশনটি বর্তমানে উপলব্ধ নেই")
            con.commit()
        except: con.rollback(); raise
        finally: con.close()
        await send_history_event("DEPOSIT_PENDING",actor_id=uid,user_id=uid,reference=order,details=f"Web Mini App deposit; Method: {sess[2]}; Amount: {money(sess[1])}৳; TxID: {tx}")
        return {"ok":True,"message":"✅ Deposit request sent for verification","request_id":did}
    except Exception as e:return _web_error(e)

@app.post("/api/deposit/cancel")
async def api_deposit_cancel(request:Request):
    try:
        uid,_=_web_uid(request); b=await request.json(); sid=str(b.get("session_id","")).strip(); con=db(); cur=con.cursor(); cur.execute("UPDATE payment_sessions SET status='CANCELLED' WHERE session_id=? AND user_id=? AND status='ACTIVE'",(sid,uid)); ok=cur.rowcount==1; con.commit(); con.close(); return {"ok":ok,"message":"✅ Session cancelled" if ok else "❌ এই সেশনটি বর্তমানে উপলব্ধ নেই"}
    except Exception as e:return _web_error(e)

@app.post("/api/withdraw")
async def api_withdraw(request:Request):
    try:
        uid,_=_web_uid(request); b=await request.json(); method=str(b.get("method","")).strip(); account=str(b.get("account","")).strip(); amount=Decimal(str(b.get("amount",0)))
        if getset("withdraw_enabled","1")!="1": raise ValueError("Withdraw system বন্ধ আছে")
        if not re.fullmatch(r"01[3-9]\d{8}",account): raise ValueError("সঠিক ১১ ডিজিটের মোবাইল নম্বর দিন")
        mn=Decimal(getset("min_wth","100")); mx=Decimal(getset("max_wth","25000")); cfg=get_payment_method(method,"withdraw")
        if not cfg: raise ValueError("Withdraw method বন্ধ আছে")
        con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
        try:
            if amount<mn or amount>mx: raise ValueError(f"Withdraw {money(mn)}৳ থেকে {money(mx)}৳")
            if cur.execute("UPDATE users SET main_balance=main_balance-? WHERE user_id=? AND main_balance>=?",(float(amount),uid,float(amount))).rowcount!=1: raise ValueError("পর্যাপ্ত main balance নেই")
            cur.execute("INSERT INTO withdrawals(user_id,method,account,amount,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(uid,method,account,float(amount),"Pending",now_iso(),now_iso())); wid=cur.lastrowid; con.commit()
        except: con.rollback(); raise
        finally: con.close()
        await send_history_event("WITHDRAW_REQUEST",actor_id=uid,user_id=uid,reference=str(wid),details=f"Web Mini App; Method: {method}; Amount: {money(amount)}৳")
        return {"ok":True,"message":"✅ Withdraw request submitted","request_id":wid,"user":_web_user(uid)}
    except Exception as e:return _web_error(e)

@app.post("/api/claim")
async def api_claim(request:Request):
    try:
        uid,_=_web_uid(request); now=datetime.now(timezone.utc); today=now.date().isoformat()
        if now.hour<8: raise ValueError("Claim window সকাল ৮টা থেকে শুরু হবে")
        con=db(); cur=con.cursor(); cur.execute("BEGIN IMMEDIATE")
        try:
            cur.execute("UPDATE plans SET active=0 WHERE user_id=? AND active=1 AND expires_at<=?",(uid,now_iso())); rows=cur.execute("SELECT id,amount,last_claim_date,expires_at,COALESCE(daily_rate,?) FROM plans WHERE user_id=? AND active=1",(float(DEMO_DAILY_RATE),uid)).fetchall(); total=Decimal('0')
            for pid,amount,last,exp,rate in rows:
                if utc_dt(exp)<=now or last==today: continue
                earning=Decimal(str(amount))*Decimal(str(rate)); changed=cur.execute("UPDATE plans SET last_claim_date=? WHERE id=? AND active=1 AND (last_claim_date IS NULL OR last_claim_date<>?)",(today,pid,today)).rowcount
                if changed==1: total+=earning; cur.execute("INSERT INTO earnings(user_id,plan_id,amount,claim_date,created_at) VALUES(?,?,?,?,?)",(uid,pid,float(earning),today,now_iso()))
            if total>0: cur.execute("UPDATE users SET main_balance=main_balance+?,total_earnings=total_earnings+? WHERE user_id=?",(float(total),float(total),uid))
            con.commit()
        except: con.rollback(); raise
        finally: con.close()
        if total<=0: raise ValueError("আজকের earnings claim করা হয়েছে অথবা কোনো active plan নেই")
        await send_history_event("BONUS_EARNINGS_CLAIM",actor_id=uid,user_id=uid,reference=f"WEB-CLAIM-{uid}-{today}",details=f"Claimed {money(total)}৳")
        return {"ok":True,"message":f"🎉 {money(total)}৳ আজকের earnings যোগ হয়েছে","user":_web_user(uid)}
    except Exception as e:return _web_error(e)

@app.get("/api/referral")
async def api_referral(request:Request):
    try:
        uid,_=_web_uid(request); u=_web_user(uid); return {"referral_count":u["referral_count"],"link":f"https://t.me/{(await bot.get_me()).username}?start=ref_{uid}"}
    except Exception as e:return _web_error(e)

@app.get("/api/history")
async def api_history(request:Request):
    try:
        uid,_=_web_uid(request); con=db(); out=[]
        for r in con.execute("SELECT method,amount,status,created_at,order_no FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 15",(uid,)).fetchall(): out.append({"type":"Deposit","method":r[0],"amount":money(r[1])+"৳","status":r[2],"date":r[3],"ref":r[4]})
        for r in con.execute("SELECT method,amount,status,created_at,id FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 15",(uid,)).fetchall(): out.append({"type":"Withdraw","method":r[0],"amount":money(r[1])+"৳","status":r[2],"date":r[3],"ref":r[4]})
        for r in con.execute("SELECT plan,amount,activated_at FROM plans WHERE user_id=? ORDER BY id DESC LIMIT 15",(uid,)).fetchall(): out.append({"type":"Plan Purchase","method":r[0],"amount":money(r[1])+"৳","status":"Active/Expired","date":r[2],"ref":""})
        con.close(); out.sort(key=lambda x:x["date"] or "",reverse=True); return {"items":out[:30]}
    except Exception as e:return _web_error(e)

@app.get("/api/admin/overview")
async def api_admin_overview(request:Request):
    try:
        uid,_=_web_uid(request)
        if not admin_ok(uid): raise ValueError("Admin access denied")
        con=db(); a=con.execute("SELECT COUNT(*) FROM users").fetchone()[0]; d=con.execute("SELECT COUNT(*) FROM deposits WHERE status='Pending'").fetchone()[0]; w=con.execute("SELECT COUNT(*) FROM withdrawals WHERE status='Pending'").fetchone()[0]; con.close(); return {"users":a,"pending_deposits":d,"pending_withdrawals":w}
    except Exception as e:return _web_error(e)

# =========================
# MAIN ENTRY POINT
# =========================
def backup_restore_enabled_from_file():
    if not os.path.exists(DB_BACKUP_NAME):
        return True
    try:
        con=sqlite3.connect(DB_BACKUP_NAME,timeout=10)
        row=con.execute("SELECT value FROM settings WHERE key='auto_db_restore'").fetchone()
        con.close()
        return (row is None) or str(row[0]) == '1'
    except Exception:
        return True

async def main():
    restored = False
    if not os.path.exists(DB_NAME) and os.path.exists(DB_BACKUP_NAME) and backup_restore_enabled_from_file():
        restored = restore_database_if_missing()
    init_db()
    if restored:
        print("Database restored from backup.")
    if getset('auto_db_backup','1') == '1':
        backup_database()
    expire_all_plans()
    asyncio.create_task(periodic_database_backup())
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="🚀 Open", web_app=WebAppInfo(url=f"{MINI_APP_URL}/miniapp/")))
    except Exception as e:
        print(f"Web App menu button setup skipped: {e}")
    
    commands = [
        BotCommand(command="start", description="🚀 Start Bot — বট শুরু করুন"),
        BotCommand(command="menu", description="🏠 Main Menu — প্রধান মেনু"),
        BotCommand(command="help", description="🆘 Help Center — সাহায্য কেন্দ্র")
    ]
    await bot.set_my_commands(commands)
    
    print(f"Bot + Web Mini App starting on {WEB_HOST}:{WEB_PORT}")
    import uvicorn
    web_config = uvicorn.Config(app, host=WEB_HOST, port=WEB_PORT, log_level="info")
    web_server = uvicorn.Server(web_config)
    await asyncio.gather(dp.start_polling(bot), web_server.serve())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped!")
