import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

API_PORT = int(os.getenv("API_PORT", 8080))
