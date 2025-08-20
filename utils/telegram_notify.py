
import os
from algosat.utils.telegram_bot import TelegramBot

# Load environment variables from .env if present
try:
	from dotenv import load_dotenv
	load_dotenv()
except ImportError:
	pass  # python-dotenv is optional, but recommended for local dev

# Read sensitive values from environment variables
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
	raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in environment or .env file!")

telegram_bot = TelegramBot(bot_token=BOT_TOKEN, chat_id=CHAT_ID)

# Non-blocking async wrapper for Telegram message sending
import asyncio
def send_telegram_async(message: str):
	loop = None
	# try:
	# 	loop = asyncio.get_running_loop()
	# except RuntimeError:
	# 	loop = None
	# if loop and loop.is_running():
	# 	# If inside an event loop, use run_in_executor
	# 	loop.run_in_executor(None, telegram_bot.send_message, message)
	# else:
	# 	# If not in an event loop, just call directly (blocking)
	# 	telegram_bot.send_message(message)
	print("Sending message to Telegram...")
# Usage:
# 1. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in your environment or in a .env file at project root.
# 2. Never commit your .env file to git (add to .gitignore).
