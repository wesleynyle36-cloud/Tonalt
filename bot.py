import os
import json
import logging
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))

REG_FEE = 300
MIN_WITHDRAW = 200
PLATFORM_FEE = 20
REF_REWARD = 100

# ================= LOGGING =================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ================= FIREBASE =================

firebase_json = os.getenv("FIREBASE_SERVICE_ACCOUNT")
if not firebase_json:
    raise RuntimeError("FIREBASE_SERVICE_ACCOUNT not set")

cred = credentials.Certificate(json.loads(firebase_json))
firebase_admin.initialize_app(cred)
db = firestore.client()

# ================= HELPERS =================

def user_ref(uid: int):
    return db.collection("users").document(str(uid))


def get_user(uid: int):
    doc = user_ref(uid).get()
    if doc.exists:
        return doc.to_dict()
    return None


def create_user(uid: int, username: str, referrer: str | None):
    ref_link = f"https://t.me/{BOT_USERNAME}?start={uid}"

    data = {
        "user_id": uid,
        "username": username,
        "paid": False,
        "balance": 0,
        "earnings": 0,
        "ref_count": 0,
        "ref_link": ref_link,
        "referred_by": referrer,
        "withdraw_pending": False,
        "created_at": datetime.utcnow(),
    }

    user_ref(uid).set(data)

    # reward referrer ONCE
    if referrer:
        ref_doc = user_ref(referrer).get()
        if ref_doc.exists:
            ref_data = ref_doc.to_dict()
            if uid not in ref_data.get("rewarded_refs", []):
                user_ref(referrer).update({
                    "balance": firestore.Increment(REF_REWARD),
                    "earnings": firestore.Increment(REF_REWARD),
                    "ref_count": firestore.Increment(1),
                    "rewarded_refs": firestore.ArrayUnion([uid])
                })


def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay Registration", callback_data="pay")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("👥 Referrals", callback_data="referrals")],
        [InlineKeyboardButton("🏦 Withdraw", callback_data="withdraw")],
    ])

# ================= HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or "no_username"

    referrer = None
    if context.args:
        referrer = context.args[0]

    user = get_user(uid)
    if not user:
        create_user(uid, username, referrer)

    await update.message.reply_text(
        "👋 Welcome to TONalt\n\n"
        f"💳 Registration fee: KES {REG_FEE}\n"
        "Pay to unlock all features.",
        reply_markup=main_keyboard()
    )


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    user = get_user(uid)

    if not user:
        await q.message.reply_text("❌ User not found. Use /start")
        return

    # PAYMENT
    if q.data == "pay":
        await q.message.reply_text(
            "💳 Please complete your registration payment via Paystack.\n\n"
            "Once payment is confirmed, your account will unlock automatically."
        )

    # BLOCK ALL IF NOT PAID
    elif not user["paid"]:
        await q.message.reply_text(
            "🔒 You must complete registration payment first."
        )

    elif q.data == "balance":
        await q.message.reply_text(
            f"💰 Balance: KES {user['balance']}\n"
            f"📈 Total Earnings: KES {user['earnings']}"
        )

    elif q.data == "referrals":
        await q.message.reply_text(
            f"👥 Referrals: {user['ref_count']}\n\n"
            f"🔗 Your referral link:\n{user['ref_link']}"
        )

    elif q.data == "withdraw":
        if user["withdraw_pending"]:
            await q.message.reply_text("⏳ You already have a pending withdrawal.")
            return

        if user["balance"] < MIN_WITHDRAW:
            await q.message.reply_text(
                f"❌ Minimum withdrawal is KES {MIN_WITHDRAW}"
            )
            return

        context.user_data["withdraw_stage"] = "details"
        await q.message.reply_text(
            "🏦 Send withdrawal details in this format:\n\n"
            "Name: John Doe\n"
            "Phone: 07XXXXXXXX"
        )


async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)

    if not user:
        return

    if context.user_data.get("withdraw_stage") == "details":
        text = update.message.text

        try:
            lines = text.splitlines()
            name = lines[0].split(":", 1)[1].strip()
            phone = lines[1].split(":", 1)[1].strip()
        except Exception:
            await update.message.reply_text("❌ Format incorrect. Try again.")
            return

        amount = user["balance"] - PLATFORM_FEE

        # lock withdrawal
        user_ref(uid).update({
            "withdraw_pending": True,
            "balance": 0
        })

        db.collection("withdrawals").add({
            "user_id": uid,
            "name": name,
            "phone": phone,
            "gross": user["balance"],
            "fee": PLATFORM_FEE,
            "net": amount,
            "status": "pending",
            "created_at": datetime.utcnow()
        })

        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"🏦 WITHDRAWAL REQUEST\n\n"
            f"User: {uid}\n"
            f"Name: {name}\n"
            f"Phone: {phone}\n"
            f"Amount: KES {amount}"
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ Withdrawal request submitted.\n"
            "You’ll be notified once processed."
        )

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages))

    logging.info("🚀 TONalt bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
