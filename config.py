import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMINS = {int(x) for x in os.getenv("ADMINS", "").replace(" ", "").split(",") if x}
ALLOW_CHANNELS = os.getenv("ALLOW_CHANNELS", "true").lower() == "true"
SOURCE_CHANNELS = {x.strip().lstrip("@").lower() for x in os.getenv("SOURCE_CHANNELS", "").split(",") if x.strip()}
DB_PATH = os.getenv("DB_PATH", "catalog.db")
# На хостинге (Bothost и т.п.) код пересобирается из Git при каждом обновлении,
# а сохраняется только папка DATA_DIR (/app/data). Кладём базу туда.
DATA_DIR = os.getenv("DATA_DIR")
if DATA_DIR and not os.path.isabs(DB_PATH):
    os.makedirs(DATA_DIR, exist_ok=True)
    DB_PATH = os.path.join(DATA_DIR, os.path.basename(DB_PATH))
PAGE_SIZE = 10


def is_admin(uid: int) -> bool:
    return uid in ADMINS
