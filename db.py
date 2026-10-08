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
CREATE TABLE IF NOT EXISTS votes(user_id INTEGER, chat_id INTEGER, v INTEGER, PRIMARY KEY(user_id, chat_id));
CREATE TABLE IF NOT EXISTS card_views(chat_id INTEGER, user_id INTEGER, ts INTEGER);
CREATE INDEX IF NOT EXISTS ix_views_ts ON card_views(ts);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chat_id INTEGER,
  days INTEGER, stars INTEGER, charge_id TEXT, ts INTEGER, refunded INTEGER DEFAULT 0);
"""
NOW = "CAST(strftime('%s','now') AS INTEGER)"
PINNED = f"(COALESCE(pinned_until,0) > {NOW})"
ORDER_ALL = f"{PINNED} DESC, id DESC"
ORDER_TOP = f"{PINNED} DESC, (likes - dislikes) DESC, likes DESC, views DESC, id DESC"
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
    for col in ("likes", "dislikes", "pinned_until"):
        if col not in cols:
            await _db.execute(f"ALTER TABLE chats ADD COLUMN {col} INTEGER DEFAULT 0")
    ucols = {r[1] for r in await (await _db.execute("PRAGMA table_info(users)")).fetchall()}
    if "last_seen" not in ucols:
        await _db.execute("ALTER TABLE users ADD COLUMN last_seen INTEGER")
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
    now = int(time.time())
    await run("""INSERT INTO users(id,name,joined,last_seen) VALUES(?,?,?,?)
                 ON CONFLICT(id) DO UPDATE SET name=excluded.name, last_seen=excluded.last_seen""",
              uid, name, now, now)


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
    await run("DELETE FROM votes WHERE chat_id=?", cid)


# ---------- лайки ----------
async def my_vote(uid, cid):
    r = await one("SELECT v FROM votes WHERE user_id=? AND chat_id=?", uid, cid)
    return r["v"] if r else 0


async def vote(uid, cid, v):
    """Повторное нажатие той же кнопки снимает голос. Возвращает новый голос пользователя."""
    new = 0 if await my_vote(uid, cid) == v else v
    if new:
        await run("INSERT OR REPLACE INTO votes(user_id,chat_id,v) VALUES(?,?,?)", uid, cid, new)
    else:
        await run("DELETE FROM votes WHERE user_id=? AND chat_id=?", uid, cid)
    await run("""UPDATE chats SET likes=(SELECT COUNT(*) FROM votes WHERE chat_id=? AND v=1),
                 dislikes=(SELECT COUNT(*) FROM votes WHERE chat_id=? AND v=-1) WHERE id=?""", cid, cid, cid)
    return new


# ---------- просмотры ----------
async def log_view(cid, uid):
    await run("INSERT INTO card_views(chat_id,user_id,ts) VALUES(?,?,?)", cid, uid, int(time.time()))
    await run("UPDATE chats SET views=COALESCE(views,0)+1 WHERE id=?", cid)


# ---------- закрепление ----------
async def pin(cid, uid, days, stars, charge_id):
    ch = await chat(cid)
    now = int(time.time())
    until = max(now, int((ch or {}).get("pinned_until") or 0)) + days * 86400
    await update_chat(cid, pinned_until=until)
    await run("INSERT INTO payments(user_id,chat_id,days,stars,charge_id,ts) VALUES(?,?,?,?,?,?)",
              uid, cid, days, stars, charge_id, now)
    return until


async def payment(pid):
    return await one("SELECT * FROM payments WHERE id=?", pid)


async def mark_refunded(pid):
    p = await payment(pid)
    await run("UPDATE payments SET refunded=1 WHERE id=?", pid)
    if p:
        await run("UPDATE chats SET pinned_until=MAX(0, COALESCE(pinned_until,0) - ?) WHERE id=?",
                  p["days"] * 86400, p["chat_id"])


# ---------- статистика ----------
async def full_stats():
    now = int(time.time())
    d1, d7 = now - 86400, now - 7 * 86400
    s = await one(f"""SELECT
        (SELECT COUNT(*) FROM chats WHERE status='approved') approved,
        (SELECT COUNT(*) FROM chats WHERE status='pending') pending,
        (SELECT COUNT(*) FROM users) users,
        (SELECT COUNT(*) FROM users WHERE joined>=?) new1,
        (SELECT COUNT(*) FROM users WHERE joined>=?) new7,
        (SELECT COUNT(*) FROM users WHERE last_seen>=?) active1,
        (SELECT COUNT(*) FROM users WHERE last_seen>=?) active7,
        (SELECT COUNT(*) FROM card_views WHERE ts>=?) views1,
        (SELECT COUNT(*) FROM card_views WHERE ts>=?) views7,
        (SELECT COUNT(*) FROM card_views) views_all,
        (SELECT COUNT(*) FROM votes WHERE v=1) likes,
        (SELECT COUNT(*) FROM votes WHERE v=-1) dislikes,
        (SELECT COUNT(*) FROM chats WHERE {PINNED}) pinned,
        (SELECT COALESCE(SUM(stars),0) FROM payments WHERE refunded=0) stars,
        (SELECT COALESCE(SUM(stars),0) FROM payments WHERE refunded=0 AND ts>=?) stars7""",
        d1, d7, d1, d7, d1, d7, d7)
    s["top_views"] = await q("""SELECT c.id, c.title, COUNT(*) n FROM card_views v JOIN chats c ON c.id=v.chat_id
                                WHERE v.ts>=? GROUP BY c.id ORDER BY n DESC LIMIT 5""", d7)
    s["top_likes"] = await q("""SELECT id, title, likes, dislikes FROM chats WHERE status='approved' AND likes>0
                                ORDER BY (likes-dislikes) DESC, likes DESC LIMIT 5""")
    s["last_pay"] = await q("""SELECT p.id, p.stars, p.days, p.user_id, p.refunded, c.title FROM payments p
                               LEFT JOIN chats c ON c.id=p.chat_id ORDER BY p.id DESC LIMIT 5""")
    return s


async def list_chats(status="approved", offset=0, limit=10, order=ORDER_ALL):
    where, args = "status=?", [status]
    total = (await one(f"SELECT COUNT(*) n FROM chats WHERE {where}", *args))["n"]
    rows = await q(f"SELECT * FROM chats WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?", *args, limit, offset)
    return rows, total


async def search(text, offset=0, limit=10):
    like = f"%{text.lower()}%"
    where = "status='approved' AND (pylower(title) LIKE ? OR pylower(about) LIKE ? OR pylower(username) LIKE ? OR pylower(tags) LIKE ?)"
    total = (await one(f"SELECT COUNT(*) n FROM chats WHERE {where}", like, like, like, like))["n"]
    rows = await q(f"SELECT * FROM chats WHERE {where} ORDER BY {ORDER_TOP} LIMIT ? OFFSET ?",
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
