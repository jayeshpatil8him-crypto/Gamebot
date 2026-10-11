import html
import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from database import Database

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO
)
log = logging.getLogger("rewardbot")

db = Database(config.DB_PATH)


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def credits_to_money(credits: int) -> float:
    return round(credits / config.CREDITS_PER_RUPEE, 2)


def display_name(user) -> str:
    return html.escape(user.first_name or user.username or str(user.id))


# --------------------------------------------------------------------------
# User commands
# --------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type != "private":
        return

    referred_by = None
    if context.args and context.args[0].startswith("ref"):
        try:
            referred_by = int(context.args[0][3:])
        except ValueError:
            referred_by = None

    is_new = db.upsert_user(user.id, user.username, user.first_name, referred_by)

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("💬 Join the Chat Group", url=config.GROUP_LINK)]]
    )
    text = (
        f"👋 Welcome <b>{display_name(user)}</b>!\n\n"
        "Chat in our group and earn credits for every real message.\n\n"
        "<b>How it works</b>\n"
        f"• Join the group and chat — <b>{config.CREDITS_PER_MESSAGE}</b> credit per message\n"
        f"• Cooldown: 1 rewarded message every {config.MESSAGE_COOLDOWN_SEC}s\n"
        f"• Daily cap: {config.DAILY_CREDIT_CAP} credits from chatting\n"
        f"• Claim /daily for +{config.DAILY_BONUS} bonus credits\n"
        f"• Invite friends with /refer for +{config.REFERRAL_BONUS} credits each\n"
        f"• Withdraw at {config.MIN_WITHDRAW_CREDITS} credits "
        f"(= {config.CURRENCY} {credits_to_money(config.MIN_WITHDRAW_CREDITS)})\n\n"
        "Commands: /balance /daily /refer /top /withdraw /history /help\n\n"
        "⚠️ Spam, copy-paste or fake messages are not rewarded and can get you banned."
    )
    await update.message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )
    if is_new:
        log.info("New user %s", user.id)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - welcome and rules\n"
        "/balance - your credits and stats\n"
        "/daily - claim the daily bonus\n"
        "/refer - your invite link\n"
        "/top - leaderboard\n"
        "/withdraw <credits> <UPI id / payment details>\n"
        "/history - your recent withdrawals"
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.first_name)
    u = db.get_user(user.id)
    remaining = max(0, config.MIN_WITHDRAW_CREDITS - u["credits"])
    await update.message.reply_text(
        f"💰 <b>Your wallet</b>\n\n"
        f"Credits: <b>{u['credits']}</b> (≈ {config.CURRENCY} {credits_to_money(u['credits'])})\n"
        f"Total earned: {u['total_earned']}\n"
        f"Messages rewarded: {u['messages']}\n"
        f"Friends invited: {db.referral_count(user.id)}\n\n"
        + (
            f"You need <b>{remaining}</b> more credits to withdraw."
            if remaining
            else "✅ You can withdraw now with /withdraw"
        ),
        parse_mode=ParseMode.HTML,
    )


async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.first_name)
    if db.claim_daily(user.id, config.DAILY_BONUS):
        await update.message.reply_text(f"🎁 +{config.DAILY_BONUS} credits claimed!")
    else:
        await update.message.reply_text("You already claimed today's bonus. Come back tomorrow.")


async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.first_name)
    username = config.BOT_USERNAME or (await context.bot.get_me()).username
    link = f"https://t.me/{username}?start=ref{user.id}"
    await update.message.reply_text(
        f"🔗 Your invite link:\n{link}\n\n"
        f"You get {config.REFERRAL_BONUS} credits when a friend you invite sends their first rewarded message."
    )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.top_users(10)
    if not rows:
        await update.message.reply_text("No data yet.")
        return
    lines = ["🏆 <b>Top earners</b>\n"]
    for i, r in enumerate(rows, 1):
        name = html.escape(r["first_name"] or r["username"] or str(r["user_id"]))
        lines.append(f"{i}. {name} — {r['total_earned']}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_chat.type != "private":
        await update.message.reply_text("Please use /withdraw in a private chat with me.")
        return
    db.upsert_user(user.id, user.username, user.first_name)

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /withdraw <credits> <UPI id or payment details>\n"
            f"Example: /withdraw {config.MIN_WITHDRAW_CREDITS} name@upi"
        )
        return
    try:
        credits = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Credits must be a number.")
        return
    details = " ".join(context.args[1:])[:200]

    if credits < config.MIN_WITHDRAW_CREDITS:
        await update.message.reply_text(
            f"Minimum withdrawal is {config.MIN_WITHDRAW_CREDITS} credits."
        )
        return

    amount = credits_to_money(credits)
    wid = db.create_withdrawal(user.id, credits, amount, details)
    if wid is None:
        await update.message.reply_text("Not enough credits (or your account is restricted).")
        return

    await update.message.reply_text(
        f"✅ Withdrawal request #{wid} submitted.\n"
        f"Amount: {config.CURRENCY} {amount}\n"
        "An admin will review it shortly."
    )

    kb = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Mark paid", callback_data=f"wd:pay:{wid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"wd:rej:{wid}"),
        ]]
    )
    msg = (
        f"💸 <b>Withdrawal #{wid}</b>\n"
        f"User: {display_name(user)} (<code>{user.id}</code>)\n"
        f"Credits: {credits} → {config.CURRENCY} {amount}\n"
        f"Details: <code>{html.escape(details)}</code>"
    )
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id, msg, parse_mode=ParseMode.HTML, reply_markup=kb
            )
        except Exception as exc:  # admin may not have started the bot
            log.warning("Could not notify admin %s: %s", admin_id, exc)


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.user_withdrawals(update.effective_user.id)
    if not rows:
        await update.message.reply_text("No withdrawals yet.")
        return
    lines = [
        f"#{r['id']} — {r['credits']} credits ({config.CURRENCY} {r['amount']}) — {r['status']}"
        for r in rows
    ]
    await update.message.reply_text("\n".join(lines))


# --------------------------------------------------------------------------
# Group chat rewards
# --------------------------------------------------------------------------
async def group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or user.is_bot or not msg.text:
        return
    if config.GROUP_ID and chat.id != config.GROUP_ID:
        return
    if len(msg.text.strip()) < config.MIN_MESSAGE_CHARS:
        return
    if msg.forward_origin is not None:
        return

    # Users must have started the bot once so they can be paid later.
    if not db.get_user(user.id):
        return

    awarded, reason, ref_info = db.record_message(
        user.id,
        msg.text,
        config.CREDITS_PER_MESSAGE,
        config.MESSAGE_COOLDOWN_SEC,
        config.DAILY_CREDIT_CAP,
        config.REFERRAL_BONUS,
    )
    log.debug("user=%s awarded=%s reason=%s", user.id, awarded, reason)

    if ref_info:
        try:
            await context.bot.send_message(
                ref_info[0],
                f"🎉 Your friend started chatting! +{ref_info[1]} referral credits.",
            )
        except Exception:
            pass


async def new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greet newcomers and tell them to start the bot so credits can be tracked."""
    if config.GROUP_ID and update.effective_chat.id != config.GROUP_ID:
        return
    names = ", ".join(
        html.escape(m.first_name or "friend")
        for m in update.message.new_chat_members
        if not m.is_bot
    )
    if not names:
        return
    username = config.BOT_USERNAME or (await context.bot.get_me()).username
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("▶️ Start the bot", url=f"https://t.me/{username}?start=group")]]
    )
    await update.message.reply_text(
        f"Welcome {names}! 👋\nTap below and press Start to begin earning credits for chatting.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


# --------------------------------------------------------------------------
# Admin
# --------------------------------------------------------------------------
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Admins only.", show_alert=True)
        return
    _, action, wid_str = query.data.split(":")
    wid = int(wid_str)
    w = db.resolve_withdrawal(wid, approve=(action == "pay"))
    if not w:
        await query.answer("Already processed.", show_alert=True)
        return
    await query.answer("Done")
    status = "PAID ✅" if action == "pay" else "REJECTED ❌ (credits refunded)"
    await query.edit_message_text(
        f"{query.message.text_html}\n\n<b>Status:</b> {status}",
        parse_mode=ParseMode.HTML,
    )
    try:
        if action == "pay":
            await context.bot.send_message(
                w["user_id"],
                f"💸 Withdrawal #{wid} paid: {config.CURRENCY} {w['amount']}. Thank you!",
            )
        else:
            await context.bot.send_message(
                w["user_id"],
                f"Withdrawal #{wid} was rejected and {w['credits']} credits were returned to your wallet.",
            )
    except Exception:
        pass


def admin_only(handler):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            return
        await handler(update, context)

    return wrapper


@admin_only
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = db.global_stats()
    await update.message.reply_text(
        f"👥 Users: {s['users']}\n"
        f"🪙 Credits issued: {s['credits_issued']}\n"
        f"🏦 Credits outstanding: {s['credits_outstanding']} "
        f"(≈ {config.CURRENCY} {credits_to_money(s['credits_outstanding'])})\n"
        f"⏳ Pending withdrawals: {s['pending']}\n"
        f"💸 Paid out so far: {config.CURRENCY} {s['paid_amount']}"
    )


@admin_only
async def admin_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.pending_withdrawals()
    if not rows:
        await update.message.reply_text("No pending withdrawals.")
        return
    for r in rows:
        kb = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ Mark paid", callback_data=f"wd:pay:{r['id']}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"wd:rej:{r['id']}"),
            ]]
        )
        await update.message.reply_text(
            f"#{r['id']} user {r['user_id']}\n{r['credits']} credits → "
            f"{config.CURRENCY} {r['amount']}\nDetails: {r['details']}",
            reply_markup=kb,
        )


@admin_only
async def admin_addad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        await update.message.reply_text("Usage: /addad <ad text with link>")
        return
    ad_id = db.add_ad(text)
    await update.message.reply_text(f"Ad #{ad_id} saved.")


@admin_only
async def admin_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ads = db.list_ads()
    if not ads:
        await update.message.reply_text("No ads. Add one with /addad <text>")
        return
    await update.message.reply_text(
        "\n\n".join(f"#{a['id']}: {a['text'][:150]}" for a in ads)
    )


@admin_only
async def admin_delad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        ad_id = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /delad <id>")
        return
    ok = db.delete_ad(ad_id)
    await update.message.reply_text("Deleted." if ok else "Ad not found.")


@admin_only
async def admin_postad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await post_ad(context)
    await update.message.reply_text("Ad posted (if any ads exist).")


@admin_only
async def admin_addcredits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid, amount = int(context.args[0]), int(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /addcredits <user_id> <amount>")
        return
    db.add_credits(uid, amount)
    await update.message.reply_text("Done.")


@admin_only
async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    db.set_banned(uid, True)
    await update.message.reply_text(f"User {uid} banned.")


@admin_only
async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    db.set_banned(uid, False)
    await update.message.reply_text(f"User {uid} unbanned.")


@admin_only
async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    sent = failed = 0
    for uid in db.all_user_ids():
        try:
            await context.bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"Sent: {sent}, failed: {failed}")


# --------------------------------------------------------------------------
# Ads in the group (this is where your revenue comes from)
# --------------------------------------------------------------------------
async def post_ad(context: ContextTypes.DEFAULT_TYPE):
    if not config.GROUP_ID:
        return
    ad = db.next_ad()
    if not ad:
        return
    try:
        await context.bot.send_message(
            config.GROUP_ID,
            f"📢 <b>Sponsored</b>\n\n{html.escape(ad['text'])}",
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=False),
        )
    except Exception as exc:
        log.warning("Failed to post ad: %s", exc)


# --------------------------------------------------------------------------
def main():
    if not config.BOT_TOKEN:
        raise SystemExit("Set BOT_TOKEN in your .env file")

    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("refer", refer))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("history", history))

    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("pending", admin_pending))
    app.add_handler(CommandHandler("addad", admin_addad))
    app.add_handler(CommandHandler("ads", admin_ads))
    app.add_handler(CommandHandler("delad", admin_delad))
    app.add_handler(CommandHandler("postad", admin_postad))
    app.add_handler(CommandHandler("addcredits", admin_addcredits))
    app.add_handler(CommandHandler("ban", admin_ban))
    app.add_handler(CommandHandler("unban", admin_unban))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^wd:(pay|rej):\d+$"))

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_members))
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, group_message
        )
    )

    if config.GROUP_ID and config.AD_INTERVAL_MIN > 0:
        app.job_queue.run_repeating(
            post_ad, interval=config.AD_INTERVAL_MIN * 60, first=config.AD_INTERVAL_MIN * 60
        )

    log.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
