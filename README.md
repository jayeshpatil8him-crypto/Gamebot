# Chat Reward Telegram Bot

A Telegram bot where members join your group, chat, and earn credits for every real message.
Once they reach the minimum, they can request a withdrawal that an admin approves and pays.

## Features

- Credits for group messages (cooldown, minimum length, duplicate filter, daily cap)
- `/daily` bonus and `/refer` referral links
- `/balance`, `/top` leaderboard, `/history`
- `/withdraw <credits> <UPI id>` with admin Approve / Reject buttons (rejected = auto refund)
- Sponsored (ad) posts in the group on a schedule, managed with `/addad`
- Admin tools: `/stats /pending /addad /ads /delad /postad /addcredits /ban /unban /broadcast`
- SQLite database, no extra services needed

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Create your Telegram group, add the bot as **admin**, and get the group id
   (forward a group message to a bot like @userinfobot, or use @RawDataBot).
3. Copy the env file and fill it in:

   ```bash
   cp .env.example .env
   ```

4. Install and run:

   ```bash
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   python bot.py
   ```

   Or with Docker: `docker build -t rewardbot . && docker run -d --env-file .env -v $(pwd)/data:/app/data -e DB_PATH=/app/data/bot.db rewardbot`

5. In @BotFather, disable group privacy for the bot (`/setprivacy` → Disable), otherwise the bot cannot see group messages.

Members must press **Start** in the bot once so their account is registered and can be paid.

## Where the money comes from

Payouts only work if you earn more than you pay. Typical sources:

- Sponsored posts: sell slots for `/addad` (brands, channels, apps)
- Affiliate / referral links and CPA offers placed in ads
- Telegram's own ad revenue share, if your channel qualifies
- Paid promotions or premium memberships

Tune `CREDITS_PER_RUPEE`, `CREDITS_PER_MESSAGE` and `DAILY_CREDIT_CAP` so total credits
outstanding (shown in `/stats`) stay well below your real revenue. Always pay manually after
checking `/pending`, and be upfront in your group rules that withdrawals depend on ad income.

## Notes

- Be honest with users about earnings and payout timing. Never promise guaranteed income.
- Follow Telegram's Terms of Service and the rules of your ad networks. Do not fake ad views.
- Withdrawals are marked paid by an admin; the bot does not move money itself. Payment APIs
  (Razorpay, UPI payouts, etc.) can be added later in `bot.py` inside `admin_callback`.
