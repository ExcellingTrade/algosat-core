from algosat.utils.telegram_bot import TelegramBot

# Use the same bot_token and chat_id as in telegram_bot.py
bot_token = "7625027938:AAFh5gQFcRdNzbIBvVfqEMj54FlzE67aYE4"
chat_id = 193841661

bot = TelegramBot(bot_token=bot_token, chat_id=chat_id)

# updates = bot.get_updates()
# print("Telegram Updates:", updates)
bot.send_message("Hello from Algorand Telegram Bot!")
# for update in updates.get("result", []):
#     print(update)
