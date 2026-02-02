import os
import re
import requests
import asyncio
from dotenv import load_dotenv

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

import firebase_admin
from firebase_admin import credentials, db

# ---------------- LOAD ENV ----------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
FIREBASE_DB_URL = os.getenv("FIREBASE_DB_URL")

REG_FEE = 300
MIN_WITHDRAW = 200
PLATFORM_FEE = 20
REF_REWARD = 100

# ---------------- FIREBASE ----------------
cred = credentials.Certificate("firebase_key.json")
firebase_admin.initialize_app(cred, {
    "databaseURL": FIREBASE_DB_URL
})

users_ref = db.reference("users")
withdrawals_ref = db.reference("withdrawals")

# ---------------- HELPERS ----------------
def is_valid_email(email: str) -> bool:
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def paystack_verify(email: str):
    url = "https://api.paystack.co/transaction"
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"
    }
    params = {"perPage": 50}

    r = requests.get(url, headers=headers, params=params)
    if r.status_code != 200:
        return False

    data = r.json().get("data", [])
    for tx in data:
        if (
            tx["status"] == "success"
            and tx["customer"]["email"].lower() == email.lower()
            and int(tx["amount"] / 100) >= REG_FEE
        ):
            return True
    return False

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay", callback_data="pay")],
        [InlineKeyboardButton("✅ Check Payment", callback_data="check")],
        [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard")],
        [InlineKeyboardButton("🔗 Referral Link", callback_data="ref")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
    ])

# ---------------- BOT HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)

    users = users_ref.get() or {}

    if uid not in users:
        ref_by = context.args[0] if context.args else None
        users_ref.child(uid).set({
            "paid": False,
            "email": "",
            "balance": 0,
            "earnings": 0,
            "referrals": 0,
            "ref_by": ref_by,
            "withdraw_pending": False
        })

        if ref_by and ref_by in users:
            users_ref.child(ref_by).update({
                "balance": users[ref_by].get("balance", 0) + REF_REWARD,
                "earnings": users[ref_by].get("earnings", 0) + REF_REWARD,
                "referrals": users[ref_by].get("referrals", 0) + 1
            })

    await update.message.reply_text(
        "👋 Welcome to TONalt\n\n"
        "💳 Registration fee: KES 300\n"
        "🔓 Pay to unlock all features",
        reply_markup=main_menu()
    )

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = str(q.from_user.id)
    user = users_ref.child(uid).get()

    if q.data == "pay":
        if user.get("email"):
            await q.message.reply_text(
                "💳 Pay via Paystack:\n"
                "https://paystack.com/pay/tonalt\n\n"
                "Use the SAME email you registered."
            )
        else:
            context.user_data["awaiting_email"] = True
            await q.message.reply_text(
                "📧 Enter the EMAIL you will use on Paystack\n"
                "Example: john@gmail.com"
            )

    elif q.data == "check":
        if not user.get("email"):
            await q.message.reply_text("❌ No email saved yet.")
            return

        if user.get("paid"):
            await q.message.reply_text("✅ Payment already confirmed.")
            return

        if paystack_verify(user["email"]):
            users_ref.child(uid).update({
                "paid": True,
                "balance": REG_FEE,
                "earnings": REG_FEE
            })
            await q.message.reply_text("🎉 Payment confirmed! Bot unlocked.")
        else:
            await q.message.reply_text("❌ Payment not found yet.")

    elif q.data != "pay" and not user.get("paid"):
        await q.message.reply_text("🔒 Please complete payment first.")

    elif q.data == "dashboard":
        await q.message.reply_text(
            f"💰 Balance: KES {user['balance']}\n"
            f"🏆 Earnings: KES {user['earnings']}\n"
            f"👥 Referrals: {user['referrals']}"
        )

    elif q.data == "ref":
        link = f"https://t.me/{BOT_USERNAME}?start={uid}"
        await q.message.reply_text(f"🔗 Your referral link:\n{link}")

    elif q.data == "withdraw":
        if user["withdraw_pending"]:
            await q.message.reply_text("⏳ Withdrawal already pending.")
            return

        if user["balance"] < MIN_WITHDRAW:
            await q.message.reply_text(
                f"❌ Minimum withdrawal is KES {MIN_WITHDRAW}"
            )
            return

        context.user_data["awaiting_withdraw"] = True
        await q.message.reply_text(
            "✍️ Send withdrawal details in this format:\n\n"
            "Name: John Doe\n"
            "Phone: 0712345678"
        )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    text = update.message.text.strip()

    if context.user_data.get("awaiting_email"):
        if not is_valid_email(text):
            await update.message.reply_text("❌ Invalid email. Try again.")
            return

        users_ref.child(uid).update({"email": text})
        context.user_data["awaiting_email"] = False

        await update.message.reply_text(
            "✅ Email saved.\n"
            "Now complete payment via Paystack.",
            reply_markup=main_menu()
        )

    elif context.user_data.get("awaiting_withdraw"):
        user = users_ref.child(uid).get()
        payout = user["balance"] - PLATFORM_FEE

        users_ref.child(uid).update({
            "balance": 0,
            "withdraw_pending": True
        })

        withdrawals_ref.push({
            "user_id": uid,
            "details": text,
            "amount": payout,
            "status": "pending"
        })

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"💸 WITHDRAWAL REQUEST\n\n"
                f"User: {uid}\n"
                f"Amount: KES {payout}\n"
                f"Details:\n{text}"
            )
        )

        context.user_data["awaiting_withdraw"] = False
        await update.message.reply_text("✅ Withdrawal request sent.")

# ---------------- MAIN ----------------
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("🚀 TONalt bot running...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
