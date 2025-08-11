from algosat.utils.telegram_bot import TelegramBot

# Singleton pattern for TelegramBot
# You can move bot_token and chat_id to a config file or environment variables if needed
BOT_TOKEN = "7625027938:AAFh5gQFcRdNzbIBvVfqEMj54FlzE67aYE4"
CHAT_ID = 7715212804
# 193841661


telegram_bot = TelegramBot(bot_token=BOT_TOKEN, chat_id=CHAT_ID)

# Non-blocking async wrapper for Telegram message sending
import asyncio
def send_telegram_async(message: str):
	loop = None
	try:
		loop = asyncio.get_running_loop()
	except RuntimeError:
		loop = None
	if loop and loop.is_running():
		# If inside an event loop, use run_in_executor
		loop.run_in_executor(None, telegram_bot.send_message, message)
	else:
		# If not in an event loop, just call directly (blocking)
		telegram_bot.send_message(message)
