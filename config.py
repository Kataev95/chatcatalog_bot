import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMINS = {int(x) for x in os.getenv("ADMINS", "").replace(" ", "").split(",") if x}
ALLOW_CHANNELS = os.getenv("ALLOW_CHANNELS", "true").lower() == "true"
SOURCE_CHANNELS = {x.strip().lstrip("@").lower() for x in os.getenv("SOURCE_CHANNELS", "").split(",") if x.strip()}
DB_PATH = os.getenv("DB_PATH", "catalog.db")
PAGE_SIZE = 10


def is_admin(uid: int) -> bool:
    return uid in ADMINS
