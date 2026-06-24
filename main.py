import os
import base64
import threading
from flask import Flask

import telebot
from google import genai
from google.genai import types

# ============================================================
# BASE64 ENCODED SECRETS
# ============================================================

TELEGRAM_TOKEN_B64 = "ODg5NjY4NjgwMzpBQUYxVVBadTc1bXUxaWFLbmZRMzJCRmlVMkdtcUNlc3NDOA=="
GEMINI_API_KEY_B64 = "QVEuQWI4Uk42SW9nNlpwbzduQWVrV0xJdWVyU2lSM1JvMHJpdjRIa3FERE1yd1pSQ2gzYkE="

def decode_b64(value: str) -> str:
    return base64.b64decode(value).decode("utf-8")

TELEGRAM_TOKEN = decode_b64(TELEGRAM_TOKEN_B64)
GEMINI_API_KEY = decode_b64(GEMINI_API_KEY_B64)

# ============================================================
# GOOGLE GENAI CLIENT
# ============================================================

client = genai.Client(api_key=GEMINI_API_KEY)

# ============================================================
# TELEGRAM BOT
# ============================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ============================================================
# FLASK WEB SERVER (RENDER KEEP-ALIVE)
# ============================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "World Cup Predictor Bot is running!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ============================================================
# BOT COMMANDS
# ============================================================

@bot.message_handler(commands=["start"])
def start_command(message):
    bot.reply_to(
        message,
        (
            "⚽ Welcome to the World Cup Match Predictor!\n\n"
            "Use /predict to get today's World Cup predictions."
        ),
    )

@bot.message_handler(commands=["predict"])
def predict_command(message):
    try:
        bot.reply_to(
            message,
            "🔍 Searching for today's World Cup matches and generating predictions..."
        )

        prompt = """
Search the web for today's FIFA World Cup football matches.

For each match:
1. Identify the teams.
2. Analyze recent form.
3. Analyze injuries and suspensions.
4. Analyze head-to-head history.
5. Analyze tactical strengths and weaknesses.
6. Estimate likely score.
7. Estimate win/draw probabilities.
8. Give a detailed prediction and betting-style insight.

Return the answer in a clean Telegram-friendly format.
"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        google_search=types.GoogleSearch()
                    )
                ]
            ),
        )

        answer = response.text

        # Telegram message limit
        if len(answer) > 4000:
            for i in range(0, len(answer), 4000):
                bot.send_message(message.chat.id, answer[i:i + 4000])
        else:
            bot.send_message(message.chat.id, answer)

    except Exception as e:
        bot.reply_to(
            message,
            f"❌ Error: {str(e)}"
        )

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    print("Bot started...")

    bot.infinity_polling(
        timeout=60,
        long_polling_timeout=60
    )
