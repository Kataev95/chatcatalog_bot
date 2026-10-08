"""Массовый импорт: ссылки из постов -> проверка через getChat -> запись в каталог."""
import asyncio
import logging
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest, TelegramForbiddenError

import db
from config import ALLOW_CHANNELS
from linkparser import Found, Post

log = logging.getLogger("import")


async def resolve(bot: Bot, f: Found) -> dict | None:
    """Возвращает поля чата или None, если это не группа/канал."""
    if f.kind == "invite":
        # Бот не умеет «заглядывать» в приватные инвайты — берём подпись из поста
        return {"invite": f.key, "title": f.label or "Чат", "kind": "private_link"}
    for _ in range(3):
        try:
            ch = await bot.get_chat("@" + f.key)
            break
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except (TelegramBadRequest, TelegramForbiddenError):
            return None
    else:
        return None
    if ch.type == "private" or (ch.type == "channel" and not ALLOW_CHANNELS):
        return None
    members = 0
    try:
        members = await bot.get_chat_member_count(ch.id)
    except Exception:
        pass
    return {"tg_id": ch.id, "username": ch.username or f.key, "title": ch.title or f.label,
            "about": getattr(ch, "description", None), "kind": ch.type, "members": members,
            "avatar_id": ch.photo.big_file_id if ch.photo else None}


def post_fields(p: Post | None, cover_id: str | None = None) -> dict:
    """Поля, которые берём из поста-карточки (название, описание, возраст, теги, картинка)."""
    if not p:
        return {"cover_id": cover_id} if cover_id else {}
    d = {"title": p.title, "about": p.about, "age": p.age, "tags": p.tags, "cover_id": cover_id}
    return {k: v for k, v in d.items() if v}


async def enrich(existing: dict, extra: dict):
    """Повторная пересылка поста дополняет уже добавленный чат (название, обложка, описание…)."""
    upd = {}
    for k, v in extra.items():
        cur = existing.get(k)
        if not cur or existing.get("kind") == "private_link" or k in ("cover_id", "age", "tags"):
            if cur != v:
                upd[k] = v
    if upd:
        await db.update_chat(existing["id"], **upd)
    return bool(upd)


async def run_import(bot: Bot, found: list[Found], added_by: int, status="approved", source="import",
                     progress=None, extra: dict | None = None):
    """extra — поля из поста (для поста об одном чате): перекрывают данные getChat у инвайтов
    и дополняют публичные чаты. Возвращает (added, dup, failed, names)."""
    extra = extra or {}
    added, dup, failed, names = 0, 0, 0, []
    for i, f in enumerate(found, 1):
        exists = await db.find_existing(username=f.key if f.kind == "public" else None,
                                        invite=f.key if f.kind == "invite" else None)
        if exists:
            dup += 1
            if extra and await enrich(exists, extra):
                names.append("♻️ обновлён: " + (extra.get("title") or exists["title"] or f.key))
        else:
            data = await resolve(bot, f)
            if not data:
                failed += 1
            elif data.get("tg_id") and await db.find_existing(tg_id=data["tg_id"]):
                dup += 1
            else:
                if data["kind"] == "private_link":
                    data.update(extra)
                else:  # у публичного чата название и описание свои, из поста — то, чего нет
                    for k, v in extra.items():
                        if k in ("cover_id", "age", "tags") or not data.get(k):
                            data[k] = v
                rid = await db.add_chat(**data, status=status, added_by=added_by, source=source)
                if rid:
                    added += 1
                    names.append(data["title"] or data.get("username") or f.key)
                else:
                    dup += 1
            if f.kind == "public":
                await asyncio.sleep(0.4)  # бережём лимиты на resolveUsername
        if progress and i % 10 == 0:
            await progress(i, len(found))
    return added, dup, failed, names
