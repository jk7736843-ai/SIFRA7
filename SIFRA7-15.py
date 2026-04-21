    # ============================================================
#  SIFRA7 OTP BOT — CLEAN REWRITE
# ============================================================

import asyncio
import logging
import re
import sqlite3
import os
import requests
import io
from datetime import datetime, timedelta

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ============================================================
#  CONFIG
# ============================================================

BOT_TOKEN     = "8733720348:AAEKrQLveSyGBtAZz17WebNRFEz2XDQ8Udc"
ADMIN_ID      = 6572004742
ADMIN_ID2     = 5931349587
GROUP_CHAT_ID = -1003318768422
GROUP_LINK    = "https://t.me/+NhG-CwXI-q0wN2Rk"
SUPPORT_LINK  = "https://t.me/Sifra7"
BOT_USERNAME  = "Sifra7_bot"

# ── API Sources ───────────────────────────────────────────────
# Format A: /crapi/had/viewstats (uses dt1/dt2, returns num/dt/message)
APIS_A = [
    {"url": "http://147.135.212.197/crapi/had/viewstats", "token": "R1JXQjRSQlVFbpFJQlZXfXZuckJmiZeIg5BUeXyKU4qCYVFDenFy"},  # API 1
    {"url": "http://147.135.212.197/crapi/time/viewstats",                                            "token": "RlBSNEVBhomCZVFTQ1FsQoduiliBVFhJW42HU3uFkYZ-YlJGRoc="},  # API 2
    {"url": "http://51.77.216.195/crapi/konek/viewstats",                                            "token": "SFVRNEVBUlZ7UXGGeVR3XYiSgl1liFZzgHSAeVNrhkmHildzSGQ="},  # API 3
    {"url": "",                                            "token": ""},  # API 4
]

# Format B: /crapi/reseller/mdr.php (uses fromdate/todate, returns number/datetime/message)
APIS_B = [
    {"url": "http://137.74.1.203/crapi/reseller/mdr.php", "token": "QVdTR0NWfkJGUFRI"},  # API 5
]

NUMBER_EXPIRY = 3600  # 1 hour
POLL_INTERVAL = 10    # seconds

# ============================================================
#  LOGGING
# ============================================================

class ColorLog(logging.Formatter):
    G = "\033[32m"; Y = "\033[33m"; R = "\033[31m"; M = "\033[35m"; RESET = "\033[0m"
    FORMATS = {
        logging.DEBUG:    G + "%(asctime)s [DEBUG] %(message)s" + RESET,
        logging.INFO:     G + "%(asctime)s [INFO]  %(message)s" + RESET,
        logging.WARNING:  Y + "%(asctime)s [WARN]  %(message)s" + RESET,
        logging.ERROR:    R + "%(asctime)s [ERROR] %(message)s" + RESET,
        logging.CRITICAL: M + "%(asctime)s [CRIT]  %(message)s" + RESET,
    }
    def format(self, record):
        return logging.Formatter(
            self.FORMATS.get(record.levelno), datefmt="%Y-%m-%d %H:%M:%S"
        ).format(record)

handler = logging.StreamHandler()
handler.setFormatter(ColorLog())
logging.basicConfig(handlers=[handler], level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
#  DATABASE
# ============================================================

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sifra7.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id   INTEGER PRIMARY KEY,
            username  TEXT,
            full_name TEXT,
            is_banned INTEGER DEFAULT 0,
            joined_at TEXT DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS numbers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            number      TEXT UNIQUE NOT NULL,
            country     TEXT NOT NULL,
            service     TEXT NOT NULL,
            status      TEXT DEFAULT 'available',
            assigned_to INTEGER DEFAULT NULL,
            assigned_at TEXT DEFAULT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS otps (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            number      TEXT,
            country     TEXT,
            service     TEXT,
            otp_code    TEXT,
            raw_sms     TEXT,
            user_id     INTEGER,
            received_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

# ── User helpers ──────────────────────────────────────────────

def get_or_create_user(user_id, username, full_name):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    u = c.fetchone()
    if not u:
        c.execute(
            "INSERT INTO users (user_id, username, full_name) VALUES (?,?,?)",
            (user_id, username, full_name)
        )
        conn.commit()
        c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        u = c.fetchone()
    conn.close()
    return dict(u)

def get_all_users():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def ban_user(user_id):
    conn = get_conn()
    conn.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (user_id,))
    conn.commit(); conn.close()

def unban_user(user_id):
    conn = get_conn()
    conn.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (user_id,))
    conn.commit(); conn.close()

# ── Number helpers ────────────────────────────────────────────

def add_number(number, country, service):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO numbers (number, country, service) VALUES (?,?,?)",
            (number, country, service)
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()

def get_countries_with_count():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT country, COUNT(*) as cnt
        FROM numbers WHERE status='available'
        GROUP BY country ORDER BY country
    """)
    rows = c.fetchall()
    conn.close()
    return [(r["country"], r["cnt"]) for r in rows]

def get_services_by_country(country):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT service FROM numbers WHERE status='available' AND country=?",
        (country,)
    )
    rows = c.fetchall()
    conn.close()
    return [r["service"] for r in rows]

user_seen_numbers = {}

def assign_number(user_id, country, service):
    import random as _random
    conn = get_conn()
    c = conn.cursor()
    seen = user_seen_numbers.get(user_id, set())
    c.execute(
        "SELECT id, number FROM numbers WHERE status='available' AND country=? AND service=?",
        (country, service)
    )
    all_rows = c.fetchall()
    unseen = [r for r in all_rows if r["number"] not in seen]
    if not unseen:
        user_seen_numbers[user_id] = set()
        unseen = all_rows
    if not unseen:
        conn.close()
        return None
    row = _random.choice(unseen)
    conn.execute(
        "UPDATE numbers SET status='assigned', assigned_to=?, assigned_at=datetime('now') WHERE id=?",
        (user_id, row["id"])
    )
    conn.commit()
    conn.close()
    if user_id not in user_seen_numbers:
        user_seen_numbers[user_id] = set()
    user_seen_numbers[user_id].add(row["number"])
    return row["number"]

def get_assigned_number(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM numbers WHERE assigned_to=? AND status='assigned'", (user_id,))
    r = c.fetchone()
    conn.close()
    return dict(r) if r else None

def mark_number_used(number):
    conn = get_conn()
    conn.execute("UPDATE numbers SET status='used', assigned_to=NULL WHERE number=?", (number,))
    conn.commit(); conn.close()

def release_expired_numbers():
    conn = get_conn()
    conn.execute(
        """UPDATE numbers SET status='available', assigned_to=NULL, assigned_at=NULL
           WHERE status='assigned' AND assigned_at IS NOT NULL
           AND (strftime('%s','now') - strftime('%s', assigned_at)) > ?""",
        (NUMBER_EXPIRY,)
    )
    conn.commit(); conn.close()

def get_stock_count():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM numbers WHERE status='available'")
    r = c.fetchone()
    conn.close()
    return r["cnt"]

def get_number_by_value(number):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM numbers WHERE number=?", (number,))
    r = c.fetchone()
    conn.close()
    return dict(r) if r else None

def delete_numbers_by_country(country):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM numbers WHERE country=?", (country,))
    count = c.fetchone()["cnt"]
    conn.execute("DELETE FROM numbers WHERE country=?", (country,))
    conn.commit(); conn.close()
    return count

def save_otp(number, country, service, otp_code, user_id, raw_sms):
    conn = get_conn()
    conn.execute(
        "INSERT INTO otps (number, country, service, otp_code, user_id, raw_sms) VALUES (?,?,?,?,?,?)",
        (number, country, service, otp_code, user_id, raw_sms)
    )
    conn.commit(); conn.close()

def get_otp_stats():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM otps")
    total = c.fetchone()["cnt"]
    c.execute("SELECT COUNT(*) as cnt FROM otps WHERE date(received_at)=date('now')")
    today = c.fetchone()["cnt"]
    conn.close()
    return total, today

# ============================================================
#  HELPERS & CONSTANTS
# ============================================================

def is_admin(user_id):
    return user_id in (ADMIN_ID, ADMIN_ID2)

COUNTRY_CODES_BY_PREFIX = {
    "1": ("USA", "🇺🇸"), "52": ("Mexico", "🇲🇽"), "55": ("Brazil", "🇧🇷"),
    "57": ("Colombia", "🇨🇴"), "51": ("Peru", "🇵🇪"), "54": ("Argentina", "🇦🇷"),
    "56": ("Chile", "🇨🇱"), "58": ("Venezuela", "🇻🇪"), "593": ("Ecuador", "🇪🇨"),
    "591": ("Bolivia", "🇧🇴"), "595": ("Paraguay", "🇵🇾"), "598": ("Uruguay", "🇺🇾"),
    "592": ("Guyana", "🇬🇾"), "597": ("Suriname", "🇸🇷"), "53": ("Cuba", "🇨🇺"),
    "509": ("Haiti", "🇭🇹"), "502": ("Guatemala", "🇬🇹"), "504": ("Honduras", "🇭🇳"),
    "503": ("El Salvador", "🇸🇻"), "505": ("Nicaragua", "🇳🇮"), "506": ("Costa Rica", "🇨🇷"),
    "507": ("Panama", "🇵🇦"), "7": ("Russia", "🇷🇺"), "33": ("France", "🇫🇷"),
    "34": ("Spain", "🇪🇸"), "39": ("Italy", "🇮🇹"), "44": ("UK", "🇬🇧"),
    "49": ("Germany", "🇩🇪"), "31": ("Netherlands", "🇳🇱"), "32": ("Belgium", "🇧🇪"),
    "41": ("Switzerland", "🇨🇭"), "43": ("Austria", "🇦🇹"), "46": ("Sweden", "🇸🇪"),
    "47": ("Norway", "🇳🇴"), "45": ("Denmark", "🇩🇰"), "358": ("Finland", "🇫🇮"),
    "48": ("Poland", "🇵🇱"), "420": ("Czech Republic", "🇨🇿"), "36": ("Hungary", "🇭🇺"),
    "40": ("Romania", "🇷🇴"), "359": ("Bulgaria", "🇧🇬"), "30": ("Greece", "🇬🇷"),
    "351": ("Portugal", "🇵🇹"), "380": ("Ukraine", "🇺🇦"), "375": ("Belarus", "🇧🇾"),
    "90": ("Turkey", "🇹🇷"), "353": ("Ireland", "🇮🇪"), "370": ("Lithuania", "🇱🇹"),
    "371": ("Latvia", "🇱🇻"), "372": ("Estonia", "🇪🇪"), "381": ("Serbia", "🇷🇸"),
    "385": ("Croatia", "🇭🇷"), "386": ("Slovenia", "🇸🇮"), "387": ("Bosnia", "🇧🇦"),
    "382": ("Montenegro", "🇲🇪"), "355": ("Albania", "🇦🇱"), "373": ("Moldova", "🇲🇩"),
    "374": ("Armenia", "🇦🇲"), "994": ("Azerbaijan", "🇦🇿"), "995": ("Georgia", "🇬🇪"),
    "91": ("India", "🇮🇳"), "92": ("Pakistan", "🇵🇰"), "880": ("Bangladesh", "🇧🇩"),
    "94": ("Sri Lanka", "🇱🇰"), "977": ("Nepal", "🇳🇵"), "93": ("Afghanistan", "🇦🇫"),
    "86": ("China", "🇨🇳"), "81": ("Japan", "🇯🇵"), "82": ("South Korea", "🇰🇷"),
    "84": ("Vietnam", "🇻🇳"), "66": ("Thailand", "🇹🇭"), "60": ("Malaysia", "🇲🇾"),
    "62": ("Indonesia", "🇮🇩"), "63": ("Philippines", "🇵🇭"), "65": ("Singapore", "🇸🇬"),
    "95": ("Myanmar", "🇲🇲"), "855": ("Cambodia", "🇰🇭"), "856": ("Laos", "🇱🇦"),
    "98": ("Iran", "🇮🇷"), "61": ("Australia", "🇦🇺"), "64": ("New Zealand", "🇳🇿"),
    "996": ("Kyrgyzstan", "🇰🇬"), "998": ("Uzbekistan", "🇺🇿"), "992": ("Tajikistan", "🇹🇯"),
    "993": ("Turkmenistan", "🇹🇲"), "963": ("Syria", "🇸🇾"), "964": ("Iraq", "🇮🇶"),
    "966": ("Saudi Arabia", "🇸🇦"), "971": ("UAE", "🇦🇪"), "972": ("Israel", "🇮🇱"),
    "974": ("Qatar", "🇶🇦"), "965": ("Kuwait", "🇰🇼"), "968": ("Oman", "🇴🇲"),
    "967": ("Yemen", "🇾🇪"), "962": ("Jordan", "🇯🇴"), "961": ("Lebanon", "🇱🇧"),
    "973": ("Bahrain", "🇧🇭"), "970": ("Palestine", "🇵🇸"),
    "20": ("Egypt", "🇪🇬"), "27": ("South Africa", "🇿🇦"), "212": ("Morocco", "🇲🇦"),
    "213": ("Algeria", "🇩🇿"), "216": ("Tunisia", "🇹🇳"), "218": ("Libya", "🇱🇾"),
    "221": ("Senegal", "🇸🇳"), "222": ("Mauritania", "🇲🇷"), "223": ("Mali", "🇲🇱"),
    "224": ("Guinea", "🇬🇳"), "225": ("Ivory Coast", "🇨🇮"), "226": ("Burkina Faso", "🇧🇫"),
    "227": ("Niger", "🇳🇪"), "228": ("Togo", "🇹🇬"), "229": ("Benin", "🇧🇯"),
    "230": ("Mauritius", "🇲🇺"), "231": ("Liberia", "🇱🇷"), "232": ("Sierra Leone", "🇸🇱"),
    "233": ("Ghana", "🇬🇭"), "234": ("Nigeria", "🇳🇬"), "235": ("Chad", "🇹🇩"),
    "237": ("Cameroon", "🇨🇲"), "238": ("Cape Verde", "🇨🇻"), "241": ("Gabon", "🇬🇦"),
    "242": ("Congo", "🇨🇬"), "243": ("DR Congo", "🇨🇩"), "244": ("Angola", "🇦🇴"),
    "249": ("Sudan", "🇸🇩"), "250": ("Rwanda", "🇷🇼"), "251": ("Ethiopia", "🇪🇹"),
    "252": ("Somalia", "🇸🇴"), "253": ("Djibouti", "🇩🇯"), "254": ("Kenya", "🇰🇪"),
    "255": ("Tanzania", "🇹🇿"), "256": ("Uganda", "🇺🇬"), "257": ("Burundi", "🇧🇮"),
    "258": ("Mozambique", "🇲🇿"), "260": ("Zambia", "🇿🇲"), "261": ("Madagascar", "🇲🇬"),
    "263": ("Zimbabwe", "🇿🇼"), "264": ("Namibia", "🇳🇦"), "265": ("Malawi", "🇲🇼"),
    "266": ("Lesotho", "🇱🇸"), "267": ("Botswana", "🇧🇼"), "211": ("South Sudan", "🇸🇸"),
    "220": ("Gambia", "🇬🇲"),
}

COUNTRY_INFO = {
    "nigeria": ("🇳🇬", "NG"), "ghana": ("🇬🇭", "GH"), "kenya": ("🇰🇪", "KE"),
    "south africa": ("🇿🇦", "ZA"), "ethiopia": ("🇪🇹", "ET"), "tanzania": ("🇹🇿", "TZ"),
    "uganda": ("🇺🇬", "UG"), "senegal": ("🇸🇳", "SN"), "cameroon": ("🇨🇲", "CM"),
    "ivory coast": ("🇨🇮", "CI"), "mali": ("🇲🇱", "ML"), "burkina faso": ("🇧🇫", "BF"),
    "guinea": ("🇬🇳", "GN"), "togo": ("🇹🇬", "TG"), "benin": ("🇧🇯", "BJ"),
    "niger": ("🇳🇪", "NE"), "rwanda": ("🇷🇼", "RW"), "zambia": ("🇿🇲", "ZM"),
    "zimbabwe": ("🇿🇼", "ZW"), "angola": ("🇦🇴", "AO"), "congo": ("🇨🇬", "CG"),
    "dr congo": ("🇨🇩", "CD"), "mozambique": ("🇲🇿", "MZ"), "madagascar": ("🇲🇬", "MG"),
    "malawi": ("🇲🇼", "MW"), "namibia": ("🇳🇦", "NA"), "botswana": ("🇧🇼", "BW"),
    "liberia": ("🇱🇷", "LR"), "sierra leone": ("🇸🇱", "SL"), "gambia": ("🇬🇲", "GM"),
    "gabon": ("🇬🇦", "GA"), "chad": ("🇹🇩", "TD"), "sudan": ("🇸🇩", "SD"),
    "south sudan": ("🇸🇸", "SS"), "somalia": ("🇸🇴", "SO"), "djibouti": ("🇩🇯", "DJ"),
    "burundi": ("🇧🇮", "BI"), "lesotho": ("🇱🇸", "LS"), "mauritius": ("🇲🇺", "MU"),
    "cape verde": ("🇨🇻", "CV"), "egypt": ("🇪🇬", "EG"), "morocco": ("🇲🇦", "MA"),
    "tunisia": ("🇹🇳", "TN"), "algeria": ("🇩🇿", "DZ"), "libya": ("🇱🇾", "LY"),
    "syria": ("🇸🇾", "SY"), "iraq": ("🇮🇶", "IQ"), "saudi arabia": ("🇸🇦", "SA"),
    "uae": ("🇦🇪", "AE"), "qatar": ("🇶🇦", "QA"), "kuwait": ("🇰🇼", "KW"),
    "bahrain": ("🇧🇭", "BH"), "oman": ("🇴🇲", "OM"), "yemen": ("🇾🇪", "YE"),
    "jordan": ("🇯🇴", "JO"), "lebanon": ("🇱🇧", "LB"), "israel": ("🇮🇱", "IL"),
    "palestine": ("🇵🇸", "PS"), "iran": ("🇮🇷", "IR"), "usa": ("🇺🇸", "US"),
    "canada": ("🇨🇦", "CA"), "uk": ("🇬🇧", "GB"), "germany": ("🇩🇪", "DE"),
    "france": ("🇫🇷", "FR"), "italy": ("🇮🇹", "IT"), "spain": ("🇪🇸", "ES"),
    "portugal": ("🇵🇹", "PT"), "netherlands": ("🇳🇱", "NL"), "belgium": ("🇧🇪", "BE"),
    "switzerland": ("🇨🇭", "CH"), "austria": ("🇦🇹", "AT"), "sweden": ("🇸🇪", "SE"),
    "norway": ("🇳🇴", "NO"), "denmark": ("🇩🇰", "DK"), "finland": ("🇫🇮", "FI"),
    "poland": ("🇵🇱", "PL"), "czech republic": ("🇨🇿", "CZ"), "hungary": ("🇭🇺", "HU"),
    "romania": ("🇷🇴", "RO"), "bulgaria": ("🇧🇬", "BG"), "greece": ("🇬🇷", "GR"),
    "croatia": ("🇭🇷", "HR"), "serbia": ("🇷🇸", "RS"), "ukraine": ("🇺🇦", "UA"),
    "russia": ("🇷🇺", "RU"), "turkey": ("🇹🇷", "TR"), "belarus": ("🇧🇾", "BY"),
    "moldova": ("🇲🇩", "MD"), "lithuania": ("🇱🇹", "LT"), "latvia": ("🇱🇻", "LV"),
    "estonia": ("🇪🇪", "EE"), "albania": ("🇦🇱", "AL"), "bosnia": ("🇧🇦", "BA"),
    "slovenia": ("🇸🇮", "SI"), "montenegro": ("🇲🇪", "ME"), "ireland": ("🇮🇪", "IE"),
    "georgia": ("🇬🇪", "GE"), "armenia": ("🇦🇲", "AM"), "azerbaijan": ("🇦🇿", "AZ"),
    "india": ("🇮🇳", "IN"), "pakistan": ("🇵🇰", "PK"), "bangladesh": ("🇧🇩", "BD"),
    "sri lanka": ("🇱🇰", "LK"), "nepal": ("🇳🇵", "NP"), "afghanistan": ("🇦🇫", "AF"),
    "china": ("🇨🇳", "CN"), "japan": ("🇯🇵", "JP"), "south korea": ("🇰🇷", "KR"),
    "vietnam": ("🇻🇳", "VN"), "thailand": ("🇹🇭", "TH"), "malaysia": ("🇲🇾", "MY"),
    "indonesia": ("🇮🇩", "ID"), "philippines": ("🇵🇭", "PH"), "singapore": ("🇸🇬", "SG"),
    "myanmar": ("🇲🇲", "MM"), "cambodia": ("🇰🇭", "KH"), "uzbekistan": ("🇺🇿", "UZ"),
    "kazakhstan": ("🇰🇿", "KZ"), "kyrgyzstan": ("🇰🇬", "KG"), "tajikistan": ("🇹🇯", "TJ"),
    "brazil": ("🇧🇷", "BR"), "colombia": ("🇨🇴", "CO"), "mexico": ("🇲🇽", "MX"),
    "argentina": ("🇦🇷", "AR"), "chile": ("🇨🇱", "CL"), "peru": ("🇵🇪", "PE"),
    "venezuela": ("🇻🇪", "VE"), "ecuador": ("🇪🇨", "EC"), "bolivia": ("🇧🇴", "BO"),
    "cuba": ("🇨🇺", "CU"), "haiti": ("🇭🇹", "HT"), "guatemala": ("🇬🇹", "GT"),
    "australia": ("🇦🇺", "AU"), "new zealand": ("🇳🇿", "NZ"),
}

SERVICE_ICONS = {
    "WHATSAPP": "📱", "FACEBOOK": "📘", "INSTAGRAM": "📸", "TELEGRAM": "✈️",
    "GOOGLE": "🔍", "TWITTER": "🐦", "TIKTOK": "🎵", "SNAPCHAT": "👻",
    "AMAZON": "📦", "PAYPAL": "💳", "MICROSOFT": "🪟", "APPLE": "🍎",
    "NETFLIX": "🎬", "DISCORD": "🎮", "UBER": "🚗", "LINKEDIN": "💼",
}

SERVICE_ABBR = {
    "WHATSAPP": "WS", "FACEBOOK": "FB", "INSTAGRAM": "IG", "TELEGRAM": "TG",
    "GOOGLE": "GG", "TWITTER": "TW", "TIKTOK": "TT", "SNAPCHAT": "SC",
    "AMAZON": "AM", "PAYPAL": "PP", "MICROSOFT": "MS", "APPLE": "AP",
    "NETFLIX": "NF", "DISCORD": "DC", "UBER": "UB", "LINKEDIN": "LI",
}

def get_country_info(country: str):
    return COUNTRY_INFO.get(country.strip().lower(), ("🌍", country[:2].upper()))

def get_country_from_number(num: str):
    clean = re.sub(r"\D", "", str(num))
    for length in (3, 2, 1):
        prefix = clean[:length]
        if prefix in COUNTRY_CODES_BY_PREFIX:
            name, flag = COUNTRY_CODES_BY_PREFIX[prefix]
            iso = COUNTRY_INFO.get(name.strip().lower(), (flag, name[:2].upper()))[1]
            return name, flag, iso
    return "Unknown", "🌍", "??"

def detect_service(cli: str, message: str) -> str:
    text = (cli + " " + message).lower()
    for service, keywords in {
        "WHATSAPP": ["whatsapp"], "FACEBOOK": ["facebook", "fb"],
        "INSTAGRAM": ["instagram"], "TELEGRAM": ["telegram"],
        "GOOGLE": ["google"], "TWITTER": ["twitter", "x.com"],
        "TIKTOK": ["tiktok"], "SNAPCHAT": ["snapchat"],
        "AMAZON": ["amazon"], "PAYPAL": ["paypal"],
        "MICROSOFT": ["microsoft"], "APPLE": ["apple"],
        "NETFLIX": ["netflix"], "DISCORD": ["discord"],
        "UBER": ["uber"], "LINKEDIN": ["linkedin"],
    }.items():
        for kw in keywords:
            if kw in text:
                return service
    return cli.upper() if cli else "SMS"

def mask_number(number: str) -> str:
    number = str(number).strip()
    if len(number) <= 7:
        return number
    return number[:4] + "-SIFRA-" + number[-4:]

def extract_otp(text: str):
    dashed = re.search(r'\b(\d{3,4})-(\d{3,4})\b', text)
    if dashed:
        return dashed.group(1) + dashed.group(2)
    patterns = [
        r"code[:\s]+(\d{4,9})", r"OTP[:\s]+(\d{4,9})",
        r"password[:\s]+(\d{4,9})", r"verification[:\s]+(\d{4,9})",
        r"is[:\s]+(\d{4,9})", r"\b(\d{4,9})\b",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None

def main_menu(user_id):
    keyboard = [["🏢 Numbers", "📊 Status", "📦 Stock"]]
    if is_admin(user_id):
        keyboard.append(["⚙️ Admin Panel"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Numbers",    callback_data="adm_add"),
         InlineKeyboardButton("❌ Delete Numbers", callback_data="adm_del")],
        [InlineKeyboardButton("👥 All Users",      callback_data="adm_users"),
         InlineKeyboardButton("📊 Analytics",      callback_data="adm_stats")],
        [InlineKeyboardButton("🚫 Ban User",       callback_data="adm_ban"),
         InlineKeyboardButton("✅ Unban User",     callback_data="adm_unban")],
        [InlineKeyboardButton("📢 Broadcast",      callback_data="adm_broadcast")],
        [InlineKeyboardButton("⏱ Set Expiry",      callback_data="adm_set_expiry")],
    ])

def number_buttons(country, service):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 View OTP Group",  url=GROUP_LINK),
         InlineKeyboardButton("🔴 Change Number",   callback_data=f"change:{country}:{service}")],
        [InlineKeyboardButton("🔴 Change Country",  callback_data="countries")],
    ])

# ============================================================
#  POLLING — Friend's method (requests + in-memory set)
# ============================================================

_processed  = set()
_error_count = 0

def fetch_sms_a(api: dict) -> list:
    """Fetch from Format A API (dt1/dt2, num/dt/message)."""
    if not api.get("url") or not api.get("token"):
        return []
    try:
        end   = datetime.now()
        start = end - timedelta(hours=1)
        params = {
            "token":   api["token"],
            "dt1":     start.strftime("%Y-%m-%d %H:%M:%S"),
            "dt2":     end.strftime("%Y-%m-%d %H:%M:%S"),
            "records": 100
        }
        resp = requests.get(api["url"], params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if str(data.get("status", "")).lower() == "success":
                # Normalize to common format
                result = []
                for sms in data.get("data", []):
                    result.append({
                        "dt":      str(sms.get("dt") or ""),
                        "num":     str(sms.get("num") or "").strip(),
                        "message": str(sms.get("message") or "").strip(),
                        "cli":     str(sms.get("cli") or "").strip(),
                    })
                return result
        return []
    except Exception as e:
        logger.error(f"[API-A] {api['url'][:30]} error: {e}")
        return []

def fetch_sms_b(api: dict) -> list:
    """Fetch from Format B API (fromdate/todate, number/datetime/message)."""
    if not api.get("url") or not api.get("token"):
        return []
    try:
        end   = datetime.now()
        start = end - timedelta(hours=1)
        params = {
            "token":        api["token"],
            "fromdate":     start.strftime("%Y-%m-%d %H:%M:%S"),
            "todate":       end.strftime("%Y-%m-%d %H:%M:%S"),
            "searchnumber": "",
            "searchcli":    "",
            "records":      100
        }
        resp = requests.get(api["url"], params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if str(data.get("status", "")).lower() == "success":
                # Normalize to common format
                result = []
                for sms in data.get("data", []):
                    result.append({
                        "dt":      str(sms.get("datetime") or ""),
                        "num":     str(sms.get("number") or "").strip(),
                        "message": str(sms.get("message") or "").strip(),
                        "cli":     str(sms.get("cli") or "").strip(),
                    })
                return result
        return []
    except Exception as e:
        logger.error(f"[API-B] {api['url'][:30]} error: {e}")
        return []

def fetch_all_sms() -> list:
    """Fetch from all APIs and combine results."""
    all_sms = []
    for api in APIS_A:
        all_sms.extend(fetch_sms_a(api))
    for api in APIS_B:
        all_sms.extend(fetch_sms_b(api))
    return all_sms

async def process_and_forward(bot, sms: dict):
    dt  = str(sms.get("dt") or "")
    num = str(sms.get("num") or "").strip()
    msg = str(sms.get("message") or "").strip()
    cli = str(sms.get("cli") or "").strip()

    if not num or not msg:
        return

    otp              = extract_otp(msg)
    country_name, country_flag, iso_code = get_country_from_number(num)
    service          = detect_service(cli, msg)
    svc_icon         = SERVICE_ICONS.get(service.upper(), "📨")
    svc_abbr         = SERVICE_ABBR.get(service.upper(), service[:2].upper())
    masked           = mask_number(num)
    number_row       = get_number_by_value(num)

    assigned_user_id = None
    country          = country_name
    svc              = service

    if number_row and number_row["status"] == "assigned":
        assigned_user_id = number_row["assigned_to"]
        country          = number_row["country"] or country_name
        svc              = number_row["service"] or service
        save_otp(num, country, svc, otp, assigned_user_id, msg)
        mark_number_used(num)
        user_seen_numbers.pop(assigned_user_id, None)
    elif number_row:
        country = number_row["country"] or country_name
        svc     = number_row["service"] or service
        save_otp(num, country, svc, otp, None, msg)

    # ── Private message (always sent if number is assigned) ──
    if assigned_user_id:
        if otp:
            user_msg = (
                f"🔔 <b>OTP Received!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{country_flag} <b>{country}</b>  |  {svc_icon} <b>{svc}</b>\n"
                f"📞 <code>+{num}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🔑 <b>Your Code:</b> <code>{otp}</code>\n\n"
                f"📩 <i>{msg}</i>"
            )
        else:
            user_msg = (
                f"📨 <b>SMS Received!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{country_flag} <b>{country}</b>  |  {svc_icon} <b>{svc}</b>\n"
                f"📞 <code>+{num}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📩 <i>{msg}</i>"
            )
        try:
            await bot.send_message(chat_id=assigned_user_id, text=user_msg, parse_mode="HTML")
            logger.info(f"✅ Sent to user {assigned_user_id}: {num} → {otp}")
        except Exception as e:
            logger.error(f"Failed to send to user {assigned_user_id}: {e}")

    # ── Group message (only if OTP code found) ───────────────
    if otp:
        group_msg = (
            f"{country_flag} <b>{iso_code}</b>  •  {svc_icon} <b>{svc_abbr}</b>  •  <b>+{masked}</b>"
        )
        group_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("‼️ Bot Pnl",     url=f"https://t.me/{BOT_USERNAME}"),
             InlineKeyboardButton("♻️ All Support", url=SUPPORT_LINK)],
            [InlineKeyboardButton(f"{otp}",         url=f"https://t.me/{BOT_USERNAME}")],
        ])
        try:
            await bot.send_message(
                chat_id=GROUP_CHAT_ID, text=group_msg,
                parse_mode="HTML", reply_markup=group_keyboard
            )
            logger.info(f"✅ Sent to group: {num} → {otp}")
        except Exception as e:
            logger.error(f"Failed to send to group: {e}")

async def start_polling(bot):
    global _processed, _error_count
    logger.info("🚀 Polling started (friend's method)")

    # Preload — mark all existing as seen so we start fresh
    existing = fetch_all_sms()
    for sms in existing:
        dt  = str(sms.get("dt") or "")
        num = str(sms.get("num") or "").strip()
        msg = str(sms.get("message") or "")
        _processed.add(f"{dt}_{num}_{hash(msg)}")
    logger.info(f"Preloaded {len(existing)} existing SMS")

    while True:
        try:
            if _error_count > 10:
                logger.warning("Too many errors — pausing 60s")
                await asyncio.sleep(60)
                _error_count = 0
                continue

            messages  = fetch_all_sms()
            new_count = 0

            for sms in messages:
                if not isinstance(sms, dict):
                    continue
                dt  = str(sms.get("dt") or "")
                num = str(sms.get("num") or "").strip()
                msg = str(sms.get("message") or "").strip()

                if not num or not msg:
                    continue

                key = f"{dt}_{num}_{hash(msg)}"
                if key in _processed:
                    continue

                _processed.add(key)
                await process_and_forward(bot, sms)
                new_count += 1

            if len(_processed) > 1000:
                _processed = set(list(_processed)[-500:])

            if new_count > 0:
                logger.info(f"✅ Forwarded {new_count} new SMS")
            else:
                logger.info("⏭ No new SMS")

            release_expired_numbers()
            _error_count = 0

        except Exception as e:
            _error_count += 1
            logger.error(f"Polling error ({_error_count}): {e}")

        await asyncio.sleep(POLL_INTERVAL)

# ============================================================
#  USER HANDLERS
# ============================================================

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    db_user = get_or_create_user(user.id, user.username or "", user.full_name or "")
    if db_user["is_banned"]:
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    await update.message.reply_text(
        f"⚡ Welcome, <b>{user.first_name}</b>!\n\n"
        f"🔑 <b>Sifra7 OTP Bot</b>\n\n"
        f"📲 Tap <b>Numbers</b> to get a virtual number\n"
        f"📨 Receive OTP codes instantly!",
        parse_mode="HTML",
        reply_markup=main_menu(user.id)
    )

async def cmd_numbers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    countries = get_countries_with_count()
    if not countries:
        await update.message.reply_text("😔 No numbers available right now. Try again later.")
        return
    buttons = [
        [InlineKeyboardButton(
            f"{get_country_info(c)[0]} {c}",
            callback_data=f"country:{c}"
        )]
        for c, n in countries
    ]
    await update.message.reply_text(
        "🌍 <b>Select a Country:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id  = update.effective_user.id
    assigned = get_assigned_number(user_id)
    if assigned:
        flag, code = get_country_info(assigned["country"])
        info = (
            f"{flag} <b>{assigned['country']}</b>\n\n"
            f"📞 <code>+{assigned['number']}</code>\n"
            f"🔧 {assigned['service']}"
        )
    else:
        info = "📵 No number assigned yet"
    await update.message.reply_text(
        f"📊 <b>Your Status</b>\n\n{info}",
        parse_mode="HTML"
    )

async def cmd_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    count = get_stock_count()
    await update.message.reply_text(
        f"📦 <b>Stock</b>\n\n✅ Available Numbers: <b>{count}</b>",
        parse_mode="HTML"
    )

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Access denied.")
        return
    await show_admin_panel(update.message, ctx)

async def show_admin_panel(message, ctx):
    total    = len(get_all_users())
    stock    = get_stock_count()
    t, today = get_otp_stats()
    await message.reply_text(
        f"⚙️ <b>Admin Panel</b>\n\n"
        f"👥 Users: <b>{total}</b>\n"
        f"📦 Stock: <b>{stock}</b>\n"
        f"🔑 OTPs Today: <b>{today}</b> | Total: <b>{t}</b>\n"
        f"⏱ Expiry: <b>{NUMBER_EXPIRY//3600}h</b>",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )

# ── Admin callbacks ───────────────────────────────────────────

async def handle_admin_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data  = query.data
    await query.answer()

    if data == "adm_add":
        ctx.user_data["adm_state"] = "add_file"
        await query.edit_message_text(
            "➕ <b>Add Numbers</b>\n\nUpload a <b>.txt file</b> with one number per line.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="adm_cancel")
            ]])
        )

    elif data == "adm_del":
        ctx.user_data["adm_state"] = "del_country"
        await query.edit_message_text(
            "❌ <b>Delete Numbers</b>\n\nSend the country name:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="adm_cancel")
            ]])
        )

    elif data == "adm_users":
        users = get_all_users()
        lines = []
        for u in users[:30]:
            n = u["full_name"] or u["username"] or "Unknown"
            s = "🚫" if u["is_banned"] else "✅"
            lines.append(f"{s} <code>{u['user_id']}</code> | {n}")
        text = f"👥 <b>{len(users)} Users</b>\n\n" + "\n".join(lines)
        if len(users) > 30:
            text += f"\n\n...and {len(users)-30} more"
        await query.edit_message_text(text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="adm_back")
            ]]))

    elif data == "adm_stats":
        t, today = get_otp_stats()
        stock    = get_stock_count()
        await query.edit_message_text(
            f"📊 <b>Analytics</b>\n\n"
            f"🔑 OTPs Today: <b>{today}</b>\n"
            f"🔑 Total OTPs: <b>{t}</b>\n"
            f"📦 Stock: <b>{stock}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="adm_back")
            ]])
        )

    elif data == "adm_ban":
        ctx.user_data["adm_state"] = "ban"
        await query.edit_message_text("🚫 Send the user ID to ban:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="adm_cancel")
            ]]))

    elif data == "adm_unban":
        ctx.user_data["adm_state"] = "unban"
        await query.edit_message_text("✅ Send the user ID to unban:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="adm_cancel")
            ]]))

    elif data == "adm_broadcast":
        ctx.user_data["adm_state"] = "broadcast"
        await query.edit_message_text("📢 Send your broadcast message:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="adm_cancel")
            ]]))

    elif data == "adm_set_expiry":
        ctx.user_data["adm_state"] = "set_expiry"
        await query.edit_message_text(
            f"⏱ Current expiry: <b>{NUMBER_EXPIRY//3600}h</b>\n\nSend new expiry in hours (e.g. 1):",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="adm_cancel")
            ]]))

    elif data == "adm_back":
        await show_admin_panel(query.message, ctx)

    elif data == "adm_cancel":
        ctx.user_data.pop("adm_state", None)
        await show_admin_panel(query.message, ctx)

# ── Admin text handler ────────────────────────────────────────

async def handle_admin_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    text  = update.message.text
    state = ctx.user_data.get("adm_state")
    global NUMBER_EXPIRY

    if state == "add_country":
        ctx.user_data["add_country"] = text.strip()
        ctx.user_data["adm_state"]   = "add_service"
        await update.message.reply_text("🔧 What service? (e.g. FACEBOOK, WHATSAPP)")
        return True

    elif state == "add_service":
        service = text.strip().upper()
        country = ctx.user_data.get("add_country")
        numbers = ctx.user_data.get("add_numbers", [])
        added = skipped = 0
        for num in numbers:
            num = num.strip()
            if not num:
                continue
            if add_number(num, country, service):
                added += 1
            else:
                skipped += 1
        ctx.user_data.pop("adm_state", None)
        ctx.user_data.pop("add_country", None)
        ctx.user_data.pop("add_numbers", None)
        await update.message.reply_text(
            f"✅ Added <b>{added}</b> numbers\n"
            f"🌍 {country} | 🔧 {service}\n"
            f"⚠️ Skipped: <b>{skipped}</b>",
            parse_mode="HTML"
        )
        return True

    elif state == "del_country":
        country = text.strip()
        count   = delete_numbers_by_country(country)
        ctx.user_data.pop("adm_state", None)
        await update.message.reply_text(
            f"✅ Deleted <b>{count}</b> numbers for <b>{country}</b>",
            parse_mode="HTML"
        )
        return True

    elif state == "ban":
        try:
            target = int(text.strip())
            ban_user(target)
            ctx.user_data.pop("adm_state", None)
            await update.message.reply_text(f"🚫 User <code>{target}</code> banned.", parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID.")
        return True

    elif state == "unban":
        try:
            target = int(text.strip())
            unban_user(target)
            ctx.user_data.pop("adm_state", None)
            await update.message.reply_text(f"✅ User <code>{target}</code> unbanned.", parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID.")
        return True

    elif state == "broadcast":
        users   = get_all_users()
        success = 0
        for u in users:
            if not u["is_banned"]:
                try:
                    await ctx.bot.send_message(u["user_id"], text)
                    success += 1
                except Exception:
                    pass
        ctx.user_data.pop("adm_state", None)
        await update.message.reply_text(f"📢 Sent to {success}/{len(users)} users.")
        return True

    elif state == "set_expiry":
        try:
            hours = float(text.strip())
            NUMBER_EXPIRY = int(hours * 3600)
            ctx.user_data.pop("adm_state", None)
            await update.message.reply_text(f"✅ Expiry set to <b>{hours}h</b>", parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ Invalid. Send a number like: 1")
        return True

    return False

# ── Document handler ──────────────────────────────────────────

async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return
    if ctx.user_data.get("adm_state") != "add_file":
        return
    doc  = update.message.document
    file = await ctx.bot.get_file(doc.file_id)
    buf  = io.BytesIO()
    await file.download_to_memory(buf)
    buf.seek(0)
    text = buf.read().decode("utf-8", errors="ignore")
    nums = [line.strip() for line in text.splitlines() if line.strip()]
    if not nums:
        await update.message.reply_text("❌ No numbers found in file.")
        return
    ctx.user_data["add_numbers"] = nums
    ctx.user_data["adm_state"]   = "add_country"
    await update.message.reply_text(
        f"📂 Got <b>{len(nums)}</b> numbers!\n\n🌍 What country are these from?",
        parse_mode="HTML"
    )

# ── Callback handler ──────────────────────────────────────────

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    data    = query.data
    user_id = update.effective_user.id
    await query.answer()

    if data.startswith("adm_"):
        await handle_admin_cb(update, ctx)
        return

    elif data == "countries":
        countries = get_countries_with_count()
        if not countries:
            await query.edit_message_text("😔 No numbers available right now.")
            return
        buttons = [
            [InlineKeyboardButton(
                f"{get_country_info(c)[0]} {c}",
                callback_data=f"country:{c}"
            )]
            for c, n in countries
        ]
        await query.edit_message_text(
            "🌍 <b>Select a Country:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif data.startswith("country:"):
        country  = data.split(":", 1)[1]
        services = get_services_by_country(country)
        if not services:
            await query.edit_message_text(f"😔 No numbers for {country} right now.")
            return
        flag, code = get_country_info(country)
        buttons = [
            [InlineKeyboardButton(
                f"{SERVICE_ICONS.get(s, '📨')} {s}",
                callback_data=f"service:{country}:{s}"
            )]
            for s in services
        ]
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="countries")])
        await query.edit_message_text(
            f"{flag} <b>{country}</b> — Select Service:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif data.startswith("service:"):
        _, country, service = data.split(":", 2)
        number = assign_number(user_id, country, service)
        if not number:
            await query.edit_message_text(
                f"😔 No numbers available for <b>{service}</b> in <b>{country}</b>.",
                parse_mode="HTML"
            )
            return
        flag, code = get_country_info(country)
        await query.edit_message_text(
            f"✨ <b>New Number Assigned!</b>\n\n"
            f"🌍 Country: <b>{country}</b> {flag}\n"
            f"📞 Number: <code>+{number}</code>\n"
            f"🔧 Service: <b>{service}</b>\n\n"
            f"⏳ <i>Please wait for your OTP to arrive.</i>",
            parse_mode="HTML",
            reply_markup=number_buttons(country, service)
        )

    elif data.startswith("change:"):
        _, country, service = data.split(":", 2)
        number = assign_number(user_id, country, service)
        if not number:
            await query.answer("😔 No more numbers available.", show_alert=True)
            return
        flag, code = get_country_info(country)
        await query.edit_message_text(
            f"✨ <b>New Number Assigned!</b>\n\n"
            f"🌍 Country: <b>{country}</b> {flag}\n"
            f"📞 Number: <code>+{number}</code>\n"
            f"🔧 Service: <b>{service}</b>\n\n"
            f"⏳ <i>Please wait for your OTP to arrive.</i>",
            parse_mode="HTML",
            reply_markup=number_buttons(country, service)
        )

# ── Main menu handler ─────────────────────────────────────────

async def handle_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    text    = update.message.text
    db_user = get_or_create_user(user.id, user.username or "", user.full_name or "")

    if db_user["is_banned"]:
        await update.message.reply_text("🚫 You are banned.")
        return

    if is_admin(user.id) and ctx.user_data.get("adm_state"):
        handled = await handle_admin_text(update, ctx)
        if handled:
            return

    if text == "🏢 Numbers":
        await cmd_numbers(update, ctx)
    elif text == "📊 Status":
        await cmd_status(update, ctx)
    elif text == "📦 Stock":
        await cmd_stock(update, ctx)
    elif text == "⚙️ Admin Panel" and is_admin(user.id):
        await show_admin_panel(update.message, ctx)
    else:
        await update.message.reply_text(
            "❓ Use the menu below.",
            reply_markup=main_menu(user.id)
        )

# ============================================================
#  ENTRY POINT
# ============================================================

async def post_init(app: Application):
    asyncio.create_task(start_polling(app.bot))

def main():
    init_db()
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))
    logger.info("✅ Sifra7 Bot is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
