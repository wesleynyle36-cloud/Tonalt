import os
import logging
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

import firebase_admin
from firebase_admin import credentials, db

# ─────────── LOAD ENV ───────────
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PAYSTACK_PAYMENT_LINK = os.getenv("PAYSTACK_PAYMENT_LINK")
FIREBASE_DB_URL = os.getenv("FIREBASE_DB_URL")

PLATFORM_FEE = 20  # flat fee

# ─────────── LOGGING ───────────
logging.basicConfig(level=logging.INFO)

# ─────────── FIREBASE INIT ───────────
cred = credentials.Certificate("firebase_key.json")
firebase_admin.initialize_app(cred, {
    "databaseURL": FIREBASE_DB_URL
})

def get_user_ref(user_id):
    return db.reference(f"users/{user_id}")

def create_user(user_id, referred_by=None):
    ref = get_user_ref(user_id)
    if not ref.get():
        ref.set({
            "paid": False,
            "balance": 0,
            "referred_by": referred_by
        })

# ─────────── /start ───────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)

    referred_by = None
    if context.args and context.args[0].startswith("REF_"):
        referred_by = context.args[0].replace("REF_", "")

    create_user(user_id, referred_by)
    user_data = get_user_ref(user_id).get()

    keyboard = [
        [InlineKeyboardButton("💳 Pay Now", callback_data="pay")],
        [InlineKeyboardButton("💰 Check Balance", callback_data="balance")],
        [InlineKeyboardButton("🏧 Withdraw", callback_data="withdraw")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if not user_data["paid"]:
        await update.message.reply_text(
            "🔒 *Access Locked*\n\n"
            "You must complete payment to access the platform.\n\n"
            "💳 Click *Pay Now* below.",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return

    referral_link = f"https://t.me/{context.bot.username}?start=REF_{user_id}"

    await update.message.reply_text(
        "✅ *Access Granted*\n\n"
        f"💰 Balance: KES {user_data['balance']}\n\n"
        f"👥 Referral link:\n{referral_link}",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# ─────────── PAY ───────────
async def pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "💳 *Complete Payment*\n\n"
        "Click the Paystack link below:\n\n"
        f"{PAYSTACK_PAYMENT_LINK}\n\n"
        "Access will unlock automatically after payment.",
        parse_mode="Markdown"
    )

# ─────────── BALANCE ───────────
async def balance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    user_data = get_user_ref(user_id).get()

    await query.message.reply_text(
        f"💰 Your balance is:\n\nKES {user_data['balance']}"
    )

# ─────────── WITHDRAW ───────────
async def withdraw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    ref = get_user_ref(user_id)
    user_data = ref.get()

    balance = user_data["balance"]

    if balance <= PLATFORM_FEE:
        await query.message.reply_text(
            "❌ Withdrawal failed\n\n"
            "Balance is too low to cover platform fee."
        )
        return

    withdraw_amount = balance - PLATFORM_FEE

    # RESET BALANCE (manual payout or Paystack later)
    ref.update({"balance": 0})

    await query.message.reply_text(
        "🏧 *Withdrawal Requested*\n\n"
        f"Amount sent: KES {withdraw_amount}\n"
        f"Platform fee: KES {PLATFORM_FEE}\n\n"
        "Payment will be processed.",
        parse_mode="Markdown"
    )

# ─────────── MAIN ───────────
def main():
    app = (
    ApplicationBuilder()
    .token(BOT_TOKEN)
    .connect_timeout(30)
    .read_timeout(30)
    .build()
)


    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(pay_callback, pattern="^pay$"))
    app.add_handler(CallbackQueryHandler(balance_callback, pattern="^balance$"))
    app.add_handler(CallbackQueryHandler(withdraw_callback, pattern="^withdraw$"))

    print("✅ Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
