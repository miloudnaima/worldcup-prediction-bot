```python
import os
import telebot
from google import genai
from google.genai import types

# Securely reading keys from Koyeb environment variables
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
ai_client = genai.Client(api_key=GEMINI_KEY)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Welcome to the Deep Match Predictor! Send /predict to analyze today's World Cup games.")

@bot.message_handler(commands=['predict'])
def get_bets(message):
    bot.reply_to(message, "Analyzing today's World Cup games and breaking news... Give me a moment! ⚽")
    
    prompt = (
        "Look up today's World Cup football matches using Google Search. "
        "Check for breaking news, player injuries, and team forms. "
        "Give me a deep, detailed analysis of the top 3 best predictions for today. "
        "Be specific and explain your reasoning clearly."
    )
    
    try:
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )
        )
        bot.send_message(message.chat.id, response.text, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"Error: {str(e)}")

if __name__ == "__main__":
    print("Bot is up and running...")
    bot.infinity_polling()
