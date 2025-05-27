import logging
import requests
from algosat.common.logger import get_logger

logger = get_logger("telegram_utils")


class TelegramBot:
    """
    A utility class to interact with a Telegram bot via the Telegram API.
    """

    def __init__(self, bot_token: str, chat_id: str = None):
        """
        Initialize the Telegram bot.

        :param bot_token: Telegram bot token (obtained from BotFather).
        """
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.chat_id = chat_id  # Will be set dynamically

    def get_updates(self, offset: int = None, limit: int = 5):
        """
        Get the latest updates (messages) received by the bot and extract the chat_id.

        :param offset: (Optional) Offset for pagination (last received update ID).
        :param limit: (Optional) Number of messages to fetch (default: 5).
        :return: List of updates.
        """
        params = {
            "limit": limit,
        }
        # if offset:
        #     params["offset"] = offset

        try:
            response = requests.get(f"{self.base_url}/getUpdates", params=params, timeout=10)
            response_data = response.json()

            if response.status_code == 200 and response_data.get("ok"):
                updates = response_data.get("result", [])
                if updates:
                    logger.debug(f"Received {len(updates)} updates.")
                    # Extract the first valid chat_id from updates
                    for update in updates:
                        if "message" in update and "chat" in update["message"]:
                            self.chat_id = update["message"]["chat"]["id"]
                            logger.debug(f"Chat ID found: {self.chat_id}")
                            break  # Stop after getting first valid chat ID

                else:
                    logger.debug("No new updates found.")
                return updates
            else:
                logger.error(f"Failed to fetch updates. Response: {response.text}")
                return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching updates: {e}")
            return None

    def send_message(self, message: str):
        """
        Send a message to the Telegram bot. Fetches chat_id dynamically if not already set.

        :param message: The message to send.
        """
        if not self.chat_id:
            logger.warning("Chat ID is not set. Fetching from updates...")
            self.get_updates()

        if not self.chat_id:
            logger.error("Failed to retrieve chat ID. Cannot send message.")
            return

        try:
            pass
            # response = requests.post(
            #     f"{self.base_url}/sendMessage",
            #     json={
            #         "chat_id": self.chat_id,
            #         "text": message,
            #         "parse_mode": "HTML",
            #     },
            #     timeout=10
            # )
            # response_data = response.json()

            # if response.status_code == 200 and response_data.get("ok"):
            #     logger.info(f"Message sent successfully: {message}")
            #     return response_data
            # else:
            #     logger.error(f"Failed to send message. Response: {response.text}")
            #     return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending Telegram message: {e}")
            return None

    def send_sticker(self, message: str):
        """
        Send a message to the Telegram bot. Fetches chat_id dynamically if not already set.

        :param message: The message to send.
        """
        if not self.chat_id:
            logger.warning("Chat ID is not set. Fetching from updates...")
            self.get_updates()

        if not self.chat_id:
            logger.error("Failed to retrieve chat ID. Cannot send message.")
            return

        try:
            response = requests.post(
                f"{self.base_url}/sendSticker",
                json={
                    "chat_id": self.chat_id,
                    "sticker": message,
                    # "parse_mode": "HTML",
                },
                timeout=10
            )
            response_data = response.json()

            if response.status_code == 200 and response_data.get("ok"):
                logger.info(f"Message sent successfully: {message}")
                return response_data
            else:
                logger.error(f"Failed to send message. Response: {response.text}")
                return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending Telegram message: {e}")
            return None


if __name__ == "__main__":
    pass
    # bot_token = ""
    # chat_id = ""
    #
    # telegram_bot = TelegramBot(bot_token=bot_token, chat_id=193841661)
    #
    # # Fetch chat ID dynamically
    # updates = telegram_bot.get_updates()
    # # print(updates)
    #
    # # # Send a message if chat ID is found
    # # if telegram_bot.chat_id:
    # #     telegram_bot.send_message("Hi Suresh! Your bot is working. 🚀")
    # # else:
    # #     logger.error("Could not send message. No chat ID found.")
