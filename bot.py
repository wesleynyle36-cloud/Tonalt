import os
import json
import firebase_admin
from firebase_admin import credentials, db
from pyrogram import Client

# ===== TELEGRAM CONFIG =====
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

# ===== FIREBASE CONFIG =====
firebase_key = json.loads(os.environ["FIREBASE_KEY"])

cred = credentials.Certificate(firebase_key)
firebase_admin.initialize_app(cred, {
    "databaseURL": "https://telegram-bot-ae675-default-rtdb.asia-southeast1.firebasedatabase.app"
})

# ===== TELEGRAM BOT =====
app = Client(
    "tonalt_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

@app.on_message()
def all_messages(client, message):
    print("Message received:", message.text)
    message.reply_text("👋 I received your message!")

    ref = db.reference("test")
    ref.set({
        "status": "firebase connected",
        "user": message.from_user.id
    })

print("🚀 Bot is running...")
app.run()
