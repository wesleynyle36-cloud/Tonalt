import os
import asyncio
import logging
from threading import Thread
from flask import Flask, request, jsonify
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
    ContextTypes,
)

import firebase_admin
from firebase_admin import credentials, db

# ------------------ LOAD ENV ------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
FIREBASE_DB_URL = os.getenv("FIREBASE_DB_URL")

# ------------------ FIREBASE ------------------
cred = credentials.Certificate("firebase.json")
firebase_admin.initialize_app(cred, {
    "databaseURL": FIREBASE_DB_URL
})

users_ref = db.reference("users")
withdrawals_ref = db.reference("withdrawals")

# ------------------ FLASK (WEBHOOK) ------------------
app = Flask(__name__)

@app.route("/paystack/webhook", methods=["POST"])
def paystack_webhook():
    data = request.json
    if data.get("event") == "charge.success":
        email = data["data"]["customer"]["email"]
        amount = int(data["data"]["amount"] / 100)

        users = users_ref.get() or {}
        for uid, user in users.items():
            if user.get("email") == email and not user.get("paid"):
                users_ref.child(uid).update({
                    "paid": True,
                    "balance": amount,
                    "earnings": amount
                })
    return jsonify({"status": "ok"}), 200

def run_webhook():
    app.run(host="0.0.0.0", port=5000)

Thread(target=run_webhook).start()

# ------------------ BOT LOGIC ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)

    users = users_ref.get() or {}

    if uid not in users:
        ref = context.args[0] if context.args else None
        users_ref.child(uid).set({
            "paid": False,
            "balance": 0,
            "earnings": 0,
            "referrals": 0,
            "withdraw_pending": False,
            "email": "",
            "ref_by": ref
        })

        if ref and ref in users:
            users_ref.child(ref).child("balance").set(
                users[ref].get("balance", 0) + 100
            )
            users_ref.child(ref).child("earnings").set(
                users[ref].get("earnings", 0) + 100
            )
            users_ref.child(ref).child("referrals").set(
                users[ref].get("referrals", 0) + 1
            )

    await update.message.reply_text(
        "👋 Welcome to TONalt\n\n"
        "💳 Pay KES 300 to activate your account.\n"
        "Once payment is confirmed, features unlock."
    )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💳 Pay", callback_data="pay")],
        [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard")],
        [InlineKeyboardButton("🔗 Referral Link", callback_data="ref")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
    ]
    await update.message.reply_text(
        "Choose an option:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = str(q.from_user.id)
    user = users_ref.child(uid).get() or {}

    if q.data != "pay" and not user.get("paid"):
        await q.message.reply_text("🔒 Please complete payment first.")
        return

    if q.data == "pay":
        await q.message.reply_text(
            "💳 Complete payment via Paystack.\n"
            "Use the same EMAIL you registered with."
        )

    elif q.data == "dashboard":
        await q.message.reply_text(
            f"💰 Balance: KES {user.get('balance',0)}\n"
            f"🏆 Earnings: KES {user.get('earnings',0)}\n"
            f"👥 Referrals: {user.get('referrals',0)}"
        )

    elif q.data == "ref":
        link = f"https://t.me/{BOT_USERNAME}?start={uid}"
        await q.message.reply_text(f"🔗 Your referral link:\n{link}")

    elif q.data == "withdraw":
        if user.get("withdraw_pending"):
            await q.message.reply_text("⏳ Withdrawal already pending.")
            return

        if user.get("balance", 0) < 200:
            await q.message.reply_text("❌ Minimum withdrawal is KES 200.")
            return

        users_ref.child(uid).update({"withdraw_pending": True})

        withdrawals_ref.push({
            "user_id": uid,
            "amount": user["balance"] - 20,
            "status": "pending"
        })

        users_ref.child(uid).update({"balance": 0})

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"💸 Withdrawal Request\nUser: {uid}\nAmount: KES {user['balance'] - 20}"
        )

        await q.message.reply_text(
            "✅ Withdrawal request sent.\n"
            "Platform fee: KES 20"
        )

# ------------------ MAIN ------------------
async def main():
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("menu", menu))
    app_bot.add_handler(CallbackQueryHandler(buttons))
    print("🚀 TONalt Bot Running...")
    await app_bot.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
