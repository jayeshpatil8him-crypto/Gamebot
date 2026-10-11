import hashlib
import sqlite3
import threading
import time
from datetime import datetime, timezone


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Database:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self._create_tables()

    def _create_tables(self) -> None:
        with self.lock, self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    credits INTEGER NOT NULL DEFAULT 0,
                    total_earned INTEGER NOT NULL DEFAULT 0,
                    messages INTEGER NOT NULL DEFAULT 0,
                    day TEXT,
                    earned_today INTEGER NOT NULL DEFAULT 0,
                    last_msg_at REAL NOT NULL DEFAULT 0,
                    last_hash TEXT,
                    last_daily TEXT,
                    referred_by INTEGER,
                    referral_paid INTEGER NOT NULL DEFAULT 0,
                    banned INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS withdrawals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    credits INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    details TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    processed_at REAL
                );
                CREATE TABLE IF NOT EXISTS ads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            )

    # ---------- users ----------
    def upsert_user(self, user_id: int, username: str | None, first_name: str | None,
                    referred_by: int | None = None) -> bool:
        """Create the user if missing. Returns True when the user is new."""
        with self.lock, self.conn:
            row = self.conn.execute(
                "SELECT user_id FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row:
                self.conn.execute(
                    "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
                    (username, first_name, user_id),
                )
                return False
            if referred_by == user_id:
                referred_by = None
            self.conn.execute(
                "INSERT INTO users (user_id, username, first_name, referred_by, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (user_id, username, first_name, referred_by, time.time()),
            )
            return True

    def get_user(self, user_id: int):
        with self.lock:
            return self.conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()

    def set_banned(self, user_id: int, banned: bool) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE users SET banned = ? WHERE user_id = ?", (int(banned), user_id)
            )

    def all_user_ids(self) -> list[int]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT user_id FROM users WHERE banned = 0"
            ).fetchall()
        return [r["user_id"] for r in rows]

    # ---------- earning ----------
    def record_message(self, user_id: int, text: str, reward: int, cooldown: int,
                       daily_cap: int, referral_bonus: int):
        """
        Try to credit a group message.
        Returns (awarded, reason, referrer_bonus_info)
        reason is one of: ok, cooldown, duplicate, cap, banned, unknown
        referrer_bonus_info is (referrer_id, bonus) when a referral just got paid.
        """
        now = time.time()
        today = _today()
        digest = hashlib.md5(text.strip().lower().encode()).hexdigest()
        with self.lock, self.conn:
            u = self.conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if not u:
                return 0, "unknown", None
            if u["banned"]:
                return 0, "banned", None
            earned_today = u["earned_today"] if u["day"] == today else 0
            if now - u["last_msg_at"] < cooldown:
                return 0, "cooldown", None
            if u["last_hash"] == digest:
                return 0, "duplicate", None
            if earned_today >= daily_cap:
                return 0, "cap", None
            award = min(reward, daily_cap - earned_today)
            self.conn.execute(
                "UPDATE users SET credits = credits + ?, total_earned = total_earned + ?,"
                " messages = messages + 1, day = ?, earned_today = ?, last_msg_at = ?,"
                " last_hash = ? WHERE user_id = ?",
                (award, award, today, earned_today + award, now, digest, user_id),
            )
            ref_info = None
            if u["referred_by"] and not u["referral_paid"]:
                ref = self.conn.execute(
                    "SELECT user_id FROM users WHERE user_id = ?", (u["referred_by"],)
                ).fetchone()
                self.conn.execute(
                    "UPDATE users SET referral_paid = 1 WHERE user_id = ?", (user_id,)
                )
                if ref:
                    self.conn.execute(
                        "UPDATE users SET credits = credits + ?, total_earned = total_earned + ?"
                        " WHERE user_id = ?",
                        (referral_bonus, referral_bonus, ref["user_id"]),
                    )
                    ref_info = (ref["user_id"], referral_bonus)
            return award, "ok", ref_info

    def claim_daily(self, user_id: int, bonus: int) -> bool:
        today = _today()
        with self.lock, self.conn:
            u = self.conn.execute(
                "SELECT last_daily, banned FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if not u or u["banned"] or u["last_daily"] == today:
                return False
            self.conn.execute(
                "UPDATE users SET credits = credits + ?, total_earned = total_earned + ?,"
                " last_daily = ? WHERE user_id = ?",
                (bonus, bonus, today, user_id),
            )
            return True

    def add_credits(self, user_id: int, amount: int) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE users SET credits = MAX(0, credits + ?) WHERE user_id = ?",
                (amount, user_id),
            )

    def top_users(self, limit: int = 10):
        with self.lock:
            return self.conn.execute(
                "SELECT user_id, username, first_name, total_earned FROM users"
                " WHERE banned = 0 ORDER BY total_earned DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def referral_count(self, user_id: int) -> int:
        with self.lock:
            return self.conn.execute(
                "SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,)
            ).fetchone()[0]

    # ---------- withdrawals ----------
    def create_withdrawal(self, user_id: int, credits: int, amount: float, details: str):
        """Atomically deduct credits and create a pending request. Returns id or None."""
        with self.lock, self.conn:
            u = self.conn.execute(
                "SELECT credits, banned FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if not u or u["banned"] or u["credits"] < credits:
                return None
            self.conn.execute(
                "UPDATE users SET credits = credits - ? WHERE user_id = ?",
                (credits, user_id),
            )
            cur = self.conn.execute(
                "INSERT INTO withdrawals (user_id, credits, amount, details, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (user_id, credits, amount, details, time.time()),
            )
            return cur.lastrowid

    def get_withdrawal(self, wid: int):
        with self.lock:
            return self.conn.execute(
                "SELECT * FROM withdrawals WHERE id = ?", (wid,)
            ).fetchone()

    def pending_withdrawals(self):
        with self.lock:
            return self.conn.execute(
                "SELECT * FROM withdrawals WHERE status = 'pending' ORDER BY id"
            ).fetchall()

    def user_withdrawals(self, user_id: int, limit: int = 5):
        with self.lock:
            return self.conn.execute(
                "SELECT * FROM withdrawals WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()

    def resolve_withdrawal(self, wid: int, approve: bool):
        """Mark a pending withdrawal paid/rejected. Rejected ones are refunded."""
        with self.lock, self.conn:
            w = self.conn.execute(
                "SELECT * FROM withdrawals WHERE id = ? AND status = 'pending'", (wid,)
            ).fetchone()
            if not w:
                return None
            status = "paid" if approve else "rejected"
            self.conn.execute(
                "UPDATE withdrawals SET status = ?, processed_at = ? WHERE id = ?",
                (status, time.time(), wid),
            )
            if not approve:
                self.conn.execute(
                    "UPDATE users SET credits = credits + ? WHERE user_id = ?",
                    (w["credits"], w["user_id"]),
                )
            return w

    # ---------- ads ----------
    def add_ad(self, text: str) -> int:
        with self.lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO ads (text, created_at) VALUES (?, ?)", (text, time.time())
            )
            return cur.lastrowid

    def list_ads(self):
        with self.lock:
            return self.conn.execute("SELECT * FROM ads ORDER BY id").fetchall()

    def delete_ad(self, ad_id: int) -> bool:
        with self.lock, self.conn:
            cur = self.conn.execute("DELETE FROM ads WHERE id = ?", (ad_id,))
            return cur.rowcount > 0

    def next_ad(self):
        """Round-robin over active ads."""
        with self.lock, self.conn:
            ads = self.conn.execute(
                "SELECT * FROM ads WHERE active = 1 ORDER BY id"
            ).fetchall()
            if not ads:
                return None
            row = self.conn.execute(
                "SELECT value FROM settings WHERE key = 'last_ad_id'"
            ).fetchone()
            last = int(row["value"]) if row else 0
            nxt = next((a for a in ads if a["id"] > last), ads[0])
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES ('last_ad_id', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(nxt["id"]),),
            )
            return nxt

    # ---------- stats ----------
    def global_stats(self) -> dict:
        with self.lock:
            c = self.conn
            return {
                "users": c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "credits_issued": c.execute(
                    "SELECT COALESCE(SUM(total_earned),0) FROM users"
                ).fetchone()[0],
                "credits_outstanding": c.execute(
                    "SELECT COALESCE(SUM(credits),0) FROM users"
                ).fetchone()[0],
                "pending": c.execute(
                    "SELECT COUNT(*) FROM withdrawals WHERE status='pending'"
                ).fetchone()[0],
                "paid_amount": c.execute(
                    "SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE status='paid'"
                ).fetchone()[0],
            }
