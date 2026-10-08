import time
import aiosqlite
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_id INTEGER, username TEXT UNIQUE COLLATE NOCASE, invite TEXT UNIQUE,
  title TEXT, about TEXT, kind TEXT, members INTEGER DEFAULT 0,
  status TEXT DEFAULT 'pending', added_by INTEGER,
  source TEXT, views INTEGER DEFAULT 0, created_at INTEGER);
CREATE INDEX IF NOT EXISTS ix_chats_status ON chats(status);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, joined INTEGER);
"""
_db: aiosqlite.Connection | None = None


async def init():
    global _db
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    # SQLite LIKE не понимает регистр кириллицы — ищем через Python lower()
    await _db.create_function("pylower", 1, lambda v: v.lower() if isinstance(v, str) else v, deterministic=True)
    await _db.executescript(SCHEMA)
    # миграции: фото чата
    cols = {r[1] for r in await (await _db.execute("PRAGMA table_info(chats)")).fetchall()}
    for col in ("avatar_id", "photo_id", "cover_id", "age", "tags"):
        if col not in cols:
            await _db.execute(f"ALTER TABLE chats ADD COLUMN {col} TEXT")
    await _db.commit()


async def q(sql, *a):
    cur = await _db.execute(sql, a)
    return [dict(r) for r in await cur.fetchall()]


async def one(sql, *a):
    r = await q(sql, *a)
    return r[0] if r else None


async def run(sql, *a):
    cur = await _db.execute(sql, a)
    await _db.commit()
    return cur.lastrowid, cur.rowcount


# ---------- users ----------
async def touch_user(uid, name):
    await run("INSERT OR IGNORE INTO users(id,name,joined) VALUES(?,?,?)", uid, name, int(time.time()))


# ---------- chats ----------
async def find_existing(username=None, invite=None, tg_id=None):
    return await one("""SELECT * FROM chats WHERE (username IS NOT NULL AND username=? COLLATE NOCASE)
                        OR (invite IS NOT NULL AND invite=?) OR (tg_id IS NOT NULL AND tg_id=?)""",
                     username, invite, tg_id)


async def add_chat(**f):
    f.setdefault("created_at", int(time.time()))
    cols = ",".join(f)
    rid, n = await run(f"INSERT OR IGNORE INTO chats({cols}) VALUES({','.join('?' * len(f))})", *f.values())
    return rid if n else None


async def update_chat(cid, **f):
    sets = ",".join(f"{k}=?" for k in f)
    await run(f"UPDATE chats SET {sets} WHERE id=?", *f.values(), cid)


async def chat(cid):
    return await one("SELECT * FROM chats WHERE id=?", cid)


async def random_chat():
    return await one("SELECT * FROM chats WHERE status='approved' ORDER BY RANDOM() LIMIT 1")


async def delete_chat(cid):
    await run("DELETE FROM chats WHERE id=?", cid)


async def list_chats(status="approved", offset=0, limit=10, order="id DESC"):
    where, args = "status=?", [status]
    total = (await one(f"SELECT COUNT(*) n FROM chats WHERE {where}", *args))["n"]
    rows = await q(f"SELECT * FROM chats WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?", *args, limit, offset)
    return rows, total


async def search(text, offset=0, limit=10):
    like = f"%{text.lower()}%"
    where = "status='approved' AND (pylower(title) LIKE ? OR pylower(about) LIKE ? OR pylower(username) LIKE ? OR pylower(tags) LIKE ?)"
    total = (await one(f"SELECT COUNT(*) n FROM chats WHERE {where}", like, like, like, like))["n"]
    rows = await q(f"SELECT * FROM chats WHERE {where} ORDER BY members DESC, id DESC LIMIT ? OFFSET ?",
                   like, like, like, like, limit, offset)
    return rows, total


async def stats():
    r = await one("""SELECT
        (SELECT COUNT(*) FROM chats WHERE status='approved') approved,
        (SELECT COUNT(*) FROM chats WHERE status='pending') pending,
        (SELECT COUNT(*) FROM users) users,
        (SELECT COALESCE(SUM(members),0) FROM chats WHERE status='approved') reach""")
    return r


async def chats_without_avatar():
    return await q("SELECT * FROM chats WHERE username IS NOT NULL AND avatar_id IS NULL AND cover_id IS NULL")
