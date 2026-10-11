import os

from dotenv import load_dotenv

load_dotenv()


def _int_list(value: str) -> list[int]:
    return [int(x) for x in value.replace(" ", "").split(",") if x]


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")  # without @, used for referral links

# Admin Telegram user IDs, comma separated
ADMIN_IDS = _int_list(os.getenv("ADMIN_IDS", ""))

# The reward group (numeric chat id like -1001234567890) and its invite link
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
GROUP_LINK = os.getenv("GROUP_LINK", "https://t.me/your_group")

# Earning rules
CREDITS_PER_MESSAGE = int(os.getenv("CREDITS_PER_MESSAGE", "1"))
MESSAGE_COOLDOWN_SEC = int(os.getenv("MESSAGE_COOLDOWN_SEC", "30"))
MIN_MESSAGE_CHARS = int(os.getenv("MIN_MESSAGE_CHARS", "8"))
DAILY_CREDIT_CAP = int(os.getenv("DAILY_CREDIT_CAP", "100"))
DAILY_BONUS = int(os.getenv("DAILY_BONUS", "10"))
REFERRAL_BONUS = int(os.getenv("REFERRAL_BONUS", "20"))

# Withdrawal rules
CREDITS_PER_RUPEE = int(os.getenv("CREDITS_PER_RUPEE", "100"))  # 100 credits = Rs 1
MIN_WITHDRAW_CREDITS = int(os.getenv("MIN_WITHDRAW_CREDITS", "5000"))
CURRENCY = os.getenv("CURRENCY", "Rs")

# Ads posted into the group
AD_INTERVAL_MIN = int(os.getenv("AD_INTERVAL_MIN", "60"))

DB_PATH = os.getenv("DB_PATH", "bot.db")
