"""
Football Intelligence Telegram Bot
===================================
Hosted on Render | Powered by Gemini 2.5 Flash + Google Search

Architecture:
  - Flask web server  →  runs in the main thread (required by Render)
  - Telegram polling  →  runs in a background daemon thread
  - Gemini AI         →  centralized via ask_gemini() with Google Search grounding

Security:
  Set TELEGRAM_TOKEN_B64 and GEMINI_API_KEY_B64 below using Base64-encoded values.
  Generate them with:
      import base64
      base64.b64encode(b"your_actual_token_here").decode()
"""

# ─────────────────────────────────────────────────────────────────────────────
# IMPORTS
# ─────────────────────────────────────────────────────────────────────────────
import base64
import logging
import os
import threading
import time

import telebot
from flask import Flask, jsonify
from google import genai
from google.genai import types


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — SECURITY: Base64-Encoded Credentials
# Replace the placeholder strings with your own Base64-encoded values.
# ─────────────────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN_B64: str = "PASTE_YOUR_BASE64_ENCODED_TELEGRAM_TOKEN_HERE"
GEMINI_API_KEY_B64: str = "PASTE_YOUR_BASE64_ENCODED_GEMINI_API_KEY_HERE"


def decode_b64(encoded: str) -> str:
    """
    Decode a Base64-encoded UTF-8 string to retrieve the original secret.
    Auto-fixes missing padding (= characters) to prevent binascii errors.
    """
    encoded = encoded.strip()
    missing = len(encoded) % 4
    if missing:
        encoded += "=" * (4 - missing)
    return base64.b64decode(encoded.encode("utf-8")).decode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — INITIALIZATION
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Decode credentials at runtime (never stored as plaintext)
TELEGRAM_TOKEN: str = decode_b64(TELEGRAM_TOKEN_B64)
GEMINI_API_KEY: str = decode_b64(GEMINI_API_KEY_B64)

# ── Telegram Bot ──────────────────────────────────────────────────────────────
# parse_mode=None enforces plain-text for every send_message() call globally,
# preventing Telegram 400 Bad Request errors caused by unescaped characters.
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)

# ── Flask Web Server ──────────────────────────────────────────────────────────
# Keeps the Render dyno alive and exposes health-check endpoints.
app = Flask(__name__)

# ── Gemini AI Client ──────────────────────────────────────────────────────────
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
GEMINI_MODEL: str = "gemini-1.5-flash"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — CORE HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def send_long_message(chat_id: int, text: str) -> None:
    """
    Send a plain-text message to a Telegram chat.

    Telegram enforces a hard 4 096-character limit per message.
    This helper splits text into ≤4 000-character chunks (safe margin),
    preferring to break at the last newline inside the window.
    A short delay between chunks avoids hitting Telegram's rate limits.
    """
    MAX_CHUNK = 4_000

    if not text or not text.strip():
        bot.send_message(chat_id, "No response was generated. Please try again.")
        return

    # Fast path — message fits in a single send
    if len(text) <= MAX_CHUNK:
        bot.send_message(chat_id, text)
        return

    # Chunked path — split at newlines for readable breaks
    start: int = 0
    while start < len(text):
        end = start + MAX_CHUNK

        if end >= len(text):
            chunk = text[start:]
            start = len(text)
        else:
            # Prefer splitting at the last newline within the window
            split_at = text.rfind("\n", start, end)
            if split_at <= start:
                split_at = end          # Fall back to hard cut if no newline found
            chunk = text[start:split_at]
            start = split_at

        if chunk.strip():
            bot.send_message(chat_id, chunk)
            time.sleep(0.4)             # Polite delay between chunks


def ask_gemini(prompt: str) -> str:
    """
    Send a prompt to Gemini AI.

    Strategy:
      1. Try with Google Search grounding (real-time data).
      2. If that fails (e.g. 403 on free key), retry without grounding
         so the bot always gives some answer using Gemini's own knowledge.

    Returns a plain-text string; never raises.
    """
    # -- Attempt 1: with Google Search grounding ------------------------------
    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.5,
            ),
        )
        result: str = response.text
        if result and result.strip():
            return result.strip()
    except Exception as exc:
        logger.warning(
            "Gemini + Google Search failed (%s) — retrying without grounding.", exc
        )

    # -- Attempt 2: plain generation, no grounding ----------------------------
    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.5),
        )
        result = response.text
        if result and result.strip():
            return result.strip()
        return "The AI returned an empty response. Please try again in a moment."

    except Exception as exc:
        logger.error("Gemini fallback also failed: %s", exc, exc_info=True)
        return (
            "The AI service is temporarily unavailable.\n"
            "Please try again in a few moments.\n\n"
            f"Technical details: {exc}"
        )


def today_str() -> str:
    """Return today's date as a human-readable string for injecting into prompts."""
    return time.strftime("%A, %d %B %Y")


def now_str() -> str:
    """Return current date + UTC time for live/real-time prompts."""
    return time.strftime("%A, %d %B %Y — %H:%M UTC")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — TELEGRAM BOT COMMAND HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "help"])
def handle_start(message: telebot.types.Message) -> None:
    """Display the welcome message and full command menu."""
    menu = (
        "Football Intelligence Bot\n"
        "Powered by Gemini AI + real-time Google Search\n"
        "==========================================\n\n"
        "COMMANDS\n\n"
        "/banker      — Best single bet of the day\n"
        "/acca        — 3-leg accumulator / parlay\n"
        "/goals       — Over / Under 2.5 goals analysis\n"
        "/predict     — Deep pre-match analysis\n"
        "/predict_now — Live scores & momentum update\n"
        "/today       — Full list of today's fixtures\n"
        "/standings   — Current major league tables\n"
        "/usdt        — USDT/DZD rate at Square Port Said\n\n"
        "==========================================\n"
        "All data is sourced live via AI-powered Google Search.\n"
        "Responses may take 10–20 seconds — please be patient."
    )
    bot.send_message(message.chat.id, menu)


@bot.message_handler(commands=["banker"])
def handle_banker(message: telebot.types.Message) -> None:
    """Recommend today's single best-value football bet."""
    chat_id = message.chat.id
    bot.send_message(chat_id, "Searching for today's best single bet. Please wait...")

    prompt = (
        f"Today's date: {today_str()}.\n\n"
        "You are an expert football betting analyst. Use Google Search to find today's football matches "
        "across all major leagues (Premier League, La Liga, Serie A, Bundesliga, Ligue 1, "
        "Champions League, Europa League, and other notable competitions).\n\n"
        "Identify the SINGLE best-value bet of the day. Base your analysis on:\n"
        "  - Recent form: last 5 games for each team\n"
        "  - Head-to-head record (last 5 meetings)\n"
        "  - Confirmed injuries and suspensions\n"
        "  - Home / Away performance metrics\n"
        "  - Current odds and implied value\n\n"
        "Output strictly in this plain text format (no asterisks, no hashtags, no markdown):\n\n"
        "MATCH: [Home Team] vs [Away Team] — [Competition]\n"
        "KICK-OFF: [Time] [Timezone]\n"
        "SELECTION: [e.g., Home Win / BTTS / Over 2.5 Goals]\n"
        "ESTIMATED ODDS: [e.g., 1.75 – 1.90]\n"
        "REASONING:\n"
        "  1. [Key point]\n"
        "  2. [Key point]\n"
        "  3. [Key point]\n"
        "CONFIDENCE: [X / 10]\n"
        "RISK NOTE: [One honest sentence about the main risk factor]"
    )

    send_long_message(chat_id, ask_gemini(prompt))


@bot.message_handler(commands=["acca"])
def handle_acca(message: telebot.types.Message) -> None:
    """Build a 3-leg football accumulator / parlay."""
    chat_id = message.chat.id
    bot.send_message(chat_id, "Building your 3-leg accumulator. Please wait...")

    prompt = (
        f"Today's date: {today_str()}.\n\n"
        "You are an expert football betting analyst. Use Google Search to find today's football fixtures "
        "across all major leagues worldwide.\n\n"
        "Build a 3-leg accumulator using matches from different leagues for variety and balance. "
        "Each leg must have a strong statistical basis. Avoid high-risk or unclear picks.\n\n"
        "For each leg, use this exact plain text format:\n\n"
        "LEG [N]\n"
        "Match: [Home Team] vs [Away Team] — [Competition]\n"
        "Kick-off: [Time] [Timezone]\n"
        "Selection: [e.g., Home Win, Over 2.5 Goals, BTTS — Yes]\n"
        "Reasoning: [2 to 3 sentences explaining the pick]\n"
        "Estimated odds: [X.XX]\n\n"
        "Separate each leg with a line of dashes (--------).\n\n"
        "After all 3 legs, add:\n\n"
        "SUMMARY\n"
        "Estimated combined odds: [X.XX]\n"
        "Overall confidence: [X / 10]\n"
        "Risk warning: [One sentence]\n\n"
        "Plain text only. No markdown. No asterisks. No hashtags."
    )

    send_long_message(chat_id, ask_gemini(prompt))


@bot.message_handler(commands=["goals"])
def handle_goals(message: telebot.types.Message) -> None:
    """Analyze today's matches for Over / Under 2.5 goals potential."""
    chat_id = message.chat.id
    bot.send_message(chat_id, "Running Over/Under 2.5 goals analysis. Please wait...")

    prompt = (
        f"Today's date: {today_str()}.\n\n"
        "You are a football statistics and data analyst. Use Google Search to find today's football fixtures.\n\n"
        "Perform a detailed Over / Under 2.5 goals analysis for today's matches. Consider:\n"
        "  - Average goals per game for each team over their last 5 home / away matches\n"
        "  - Head-to-head goal averages (last 5 meetings)\n"
        "  - League average goals per game\n"
        "  - Tactical setups (attacking vs. defensive teams)\n"
        "  - Any relevant team news affecting attacking or defensive strength\n\n"
        "Output in this exact plain text format:\n\n"
        "TOP 5 OVER 2.5 PICKS\n\n"
        "[Match — Competition]\n"
        "Prediction: Over 2.5 Goals\n"
        "Probability: [X%]\n"
        "Key stat: [Most important supporting statistic]\n\n"
        "(Repeat for all 5 picks, separated by --------)\n\n"
        "TOP 3 UNDER 2.5 PICKS\n\n"
        "[Match — Competition]\n"
        "Prediction: Under 2.5 Goals\n"
        "Probability: [X%]\n"
        "Key stat: [Most important supporting statistic]\n\n"
        "(Repeat for all 3 picks, separated by --------)\n\n"
        "Plain text only. No markdown."
    )

    send_long_message(chat_id, ask_gemini(prompt))


@bot.message_handler(commands=["predict"])
def handle_predict(message: telebot.types.Message) -> None:
    """Deep pre-match analysis of today's top football fixtures."""
    chat_id = message.chat.id
    bot.send_message(
        chat_id,
        "Performing deep match analysis. This may take 15-20 seconds. Please wait..."
    )

    prompt = (
        f"Today's date: {today_str()}.\n\n"
        "You are a senior football analyst. Use Google Search to find today's top 5 football matches "
        "across major competitions (Premier League, La Liga, Serie A, Bundesliga, Ligue 1, "
        "Champions League, Europa League, and major international fixtures).\n\n"
        "For EACH of the 5 matches, write a thorough pre-match report using this structure:\n\n"
        "MATCH: [Home Team] vs [Away Team]\n"
        "COMPETITION: [Name]\n"
        "KICK-OFF: [Time] [Timezone]\n"
        "VENUE: [Stadium]\n\n"
        "FORM (last 5 games):\n"
        "  Home: [W/D/L W/D/L W/D/L W/D/L W/D/L] — [brief summary]\n"
        "  Away: [W/D/L W/D/L W/D/L W/D/L W/D/L] — [brief summary]\n\n"
        "HEAD TO HEAD: [Last 3 meetings and results]\n\n"
        "TEAM NEWS: [Key injuries, suspensions, expected returns]\n\n"
        "TACTICAL OVERVIEW: [Expected formations and playing styles]\n\n"
        "KEY PLAYER TO WATCH: [Name, Team, Why]\n\n"
        "PREDICTED SCORE: [X – Y]\n\n"
        "BEST BET: [Selection and reasoning]\n\n"
        "Separate each match report with a row of equal signs (=========).\n"
        "Plain text only. No asterisks, no hashtags, no markdown."
    )

    send_long_message(chat_id, ask_gemini(prompt))


@bot.message_handler(commands=["predict_now"])
def handle_predict_now(message: telebot.types.Message) -> None:
    """Live scores and in-match momentum update for ongoing matches."""
    chat_id = message.chat.id
    bot.send_message(chat_id, "Fetching live match data. Please wait...")

    prompt = (
        f"Current date and time: {now_str()}.\n\n"
        "Use Google Search to find ALL football matches being played RIGHT NOW at this exact moment.\n\n"
        "For each live match, provide:\n\n"
        "MATCH: [Home Team] vs [Away Team]\n"
        "SCORE: [Current score]\n"
        "MINUTE: [Match minute, e.g., 67']\n"
        "COMPETITION: [Name]\n"
        "MOMENTUM: [Which team is currently dominating and why]\n"
        "RECENT EVENTS: [Goals, red cards, penalties in the last 15 minutes]\n"
        "PREDICTION: [Most likely final result based on current momentum and score]\n\n"
        "Separate each live match with --------.\n\n"
        "If no matches are currently live, list ALL matches starting in the next 2 hours with:\n"
        "  Match, Competition, Kick-off time, and a one-line pre-match tip.\n\n"
        "Plain text only. No markdown."
    )

    send_long_message(chat_id, ask_gemini(prompt))


@bot.message_handler(commands=["today"])
def handle_today(message: telebot.types.Message) -> None:
    """Display a clean, organized list of today's football fixtures."""
    chat_id = message.chat.id
    bot.send_message(chat_id, "Fetching today's full fixture list. Please wait...")

    prompt = (
        f"Today's date: {today_str()}.\n\n"
        "Use Google Search to find ALL football matches scheduled for today across all leagues worldwide.\n\n"
        "Organize the fixtures by competition. Use this format:\n\n"
        "[COMPETITION NAME]\n"
        "  HH:MM [TZ] — [Home Team] vs [Away Team]\n"
        "  HH:MM [TZ] — [Home Team] vs [Away Team]\n\n"
        "Cover all notable competitions including but not limited to:\n"
        "  Premier League, La Liga, Serie A, Bundesliga, Ligue 1,\n"
        "  Champions League, Europa League, Conference League,\n"
        "  MLS, Liga MX, Brazilian Serie A, Argentine Primera Division,\n"
        "  Eredivisie, Primeira Liga, Super Lig, Saudi Pro League,\n"
        "  African leagues (CAF), and international fixtures.\n\n"
        "Group competitions logically (UEFA competitions first, then domestic leagues by region).\n"
        "Plain text only. No markdown."
    )

    send_long_message(chat_id, ask_gemini(prompt))


@bot.message_handler(commands=["standings"])
def handle_standings(message: telebot.types.Message) -> None:
    """Display current major football league standings."""
    chat_id = message.chat.id
    bot.send_message(chat_id, "Fetching current league standings. Please wait...")

    prompt = (
        f"Today's date: {today_str()}.\n\n"
        "Use Google Search to retrieve the most current, up-to-date league tables for:\n"
        "  1. Premier League (England)\n"
        "  2. La Liga (Spain)\n"
        "  3. Serie A (Italy)\n"
        "  4. Bundesliga (Germany)\n"
        "  5. Ligue 1 (France)\n"
        "  6. Champions League (current stage — groups or knockout bracket)\n\n"
        "For each domestic league, display the TOP 6 teams in this tabular format:\n\n"
        "Pos  Team              GP  W  D  L  GD  Pts\n"
        "1.   [Team name]       XX  X  X  X  +X  XX\n"
        "...\n\n"
        "After the table, add one line noting:\n"
        "  - Current leader and points advantage over 2nd\n"
        "  - Teams in top-4 (UEFA Champions League) spots\n"
        "  - Teams in relegation zone (bottom 3)\n\n"
        "For the Champions League, summarize the current knockout bracket or top 2 from each group.\n\n"
        "Plain text only. No markdown."
    )

    send_long_message(chat_id, ask_gemini(prompt))


@bot.message_handler(commands=["usdt"])
def handle_usdt(message: telebot.types.Message) -> None:
    """Fetch the USDT to DZD parallel market rate at Square Port Said, Algiers."""
    chat_id = message.chat.id
    bot.send_message(
        chat_id,
        "Fetching USDT/DZD parallel market rate at Square Port Said. Please wait..."
    )

    prompt = (
        f"Today's date: {today_str()}.\n\n"
        "Use Google Search to find the current USDT (Tether) to DZD (Algerian Dinar) exchange rate "
        "on the parallel / black market, specifically at Square Port Said "
        "(Place du Port Said / Hay el Mina) in Algiers, Algeria.\n\n"
        "Search in both French and Arabic sources for the most accurate local data "
        "(e.g., search terms like 'cours dollar Square Port Said aujourd\'hui', "
        "'سعر الدولار ساحة بور سعيد اليوم').\n\n"
        "Provide all of the following:\n\n"
        "SQUARE PORT SAID — USDT/DZD PARALLEL RATE\n"
        "Date: [Today's date]\n\n"
        "BUY rate (trader buys USDT from you):  [X,XXX] DZD per 1 USDT\n"
        "SELL rate (trader sells USDT to you):  [X,XXX] DZD per 1 USDT\n\n"
        "OFFICIAL BANK RATE (Bank of Algeria):  [X,XXX] DZD per 1 USDT\n"
        "Parallel market premium over official: [+X%]\n\n"
        "7-DAY TREND: [Rising / Falling / Stable] — [Brief explanation]\n\n"
        "NOTES: [Any relevant context — capital controls, economic news, "
        "or Ramadan / seasonal factors affecting the rate]\n\n"
        "DATA SOURCE: [Name the source(s) used]\n\n"
        "If exact Port Said data is unavailable, use the best available Algerian parallel market data "
        "and clearly state the alternative source. Plain text only. No markdown."
    )

    send_long_message(chat_id, ask_gemini(prompt))


@bot.message_handler(func=lambda msg: True, content_types=["text"])
def handle_unknown(message: telebot.types.Message) -> None:
    """Catch-all handler for any unrecognized text messages."""
    bot.send_message(
        message.chat.id,
        "Command not recognized.\n"
        "Type /start to see the full list of available commands."
    )


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — FLASK HEALTH-CHECK ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Root endpoint — confirms the service is live on Render."""
    return "Football Intelligence Bot is online and running!", 200


@app.route("/health")
def health_check():
    """
    Health-check endpoint used by Render's uptime monitor.
    Returns a JSON payload with service status details.
    """
    return jsonify({
        "status": "ok",
        "service": "football-intelligence-bot",
        "bot_polling": "active",
        "model": GEMINI_MODEL,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }), 200


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — BOT POLLING THREAD TARGET
# ─────────────────────────────────────────────────────────────────────────────

def run_bot_polling() -> None:
    """
    Target function for the Telegram bot background thread.

    Calls infinity_polling() inside a retry loop so that transient network
    errors (common on Render's free tier) automatically restart polling
    without crashing the process.
    """
    logger.info("Bot polling thread started.")
    while True:
        try:
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=60,
                skip_pending=True,              # Skip messages sent while bot was offline
                logger_level=logging.WARNING,   # Suppress verbose telebot debug output
            )
        except Exception as exc:
            logger.error(
                "Bot polling encountered an error: %s — restarting in 10 seconds...",
                exc,
            )
            time.sleep(10)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7 — MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    PORT: int = int(os.environ.get("PORT", 8080))

    logger.info("=" * 60)
    logger.info("Football Intelligence Bot — Starting up")
    logger.info("Gemini model : %s", GEMINI_MODEL)
    logger.info("Flask port   : %d", PORT)
    logger.info("=" * 60)

    # ── Step 1: Launch Telegram bot polling in a background daemon thread ──────
    # daemon=True ensures the thread does not block the process from exiting
    # when the main thread (Flask) shuts down.
    bot_thread = threading.Thread(
        target=run_bot_polling,
        name="TelegramBotPollingThread",
        daemon=True,
    )
    bot_thread.start()
    logger.info("Telegram bot polling thread launched (daemon=True).")

    # ── Step 2: Start Flask in the main thread ────────────────────────────────
    # Render requires the web server to bind to 0.0.0.0 and the $PORT env var.
    # use_reloader=False prevents Flask from spawning a second process (which
    # would conflict with the already-running bot thread).
    logger.info("Starting Flask web server on 0.0.0.0:%d", PORT)
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )
