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
# INITIALIZE APIS
# ============================================================
client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

@app.route("/")
def home():
    return "Pro Football Betting Bot is active!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ============================================================
# CORE ENGINE
# ============================================================
def ask_gemini(prompt_text):
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt_text,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        ),
    )
    return response.text

# ============================================================
# BOT COMMANDS (NO PARSE_MODE = NO CRASHES)
# ============================================================
@bot.message_handler(commands=["start"])
def start_command(message):
    menu = (
        "⚽ Elite Football Analytics Bot\n\n"
        "Commands:\n"
        "/banker /acca /goals /predict\n"
        "/predict_now /today /standings /usdt /milan"
    )
    bot.reply_to(message, menu)

def send_long_message(chat_id, text):
    # Sends long messages by chunking them without parse_mode
    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            bot.send_message(chat_id, text[i:i + 4000])
    else:
        bot.send_message(chat_id, text)

@bot.message_handler(commands=["banker", "acca", "goals", "predict_now", "today", "standings", "usdt", "milan", "predict"])
def handle_commands(message):
    bot.reply_to(message, "Processing your request...")
    try:
        # Simple mapping of commands to prompts
        prompts = {
            "/banker": "Identify the SINGLE highest-confidence 'banker' bet for today's football. Give reason and confidence/10.",
            "/acca": "Create a 3-leg football accumulator for today. Keep it short.",
            "/goals": "Identify Over/Under 2.5 goal opportunities for today's football. Keep it short.",
            "/predict_now": "Give a 1-paragraph live update on major football matches happening now.",
            "/today": "List today's major football kick-off times and teams. No analysis.",
            "/standings": "Provide current standings for major football leagues/tournaments.",
            "/usdt": "What is the parallel market USDT/DZD rate in Algeria (Square Port Said)?",
            "/milan": "Latest AC Milan news and next match info.",
            "/predict": "Analyze today's top 3 football matches with win percentages and tactical insights."
        }
        answer = ask_gemini(prompts.get(message.text.split()[0], "Provide a football update."))
        send_long_message(message.chat.id, answer)
    except Exception as e:
        bot.reply_to(message, f"Error: {str(e)}")

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
