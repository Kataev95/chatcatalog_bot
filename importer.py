"""Массовый импорт: ссылки из постов -> проверка через getChat -> запись в каталог."""
import asyncio
import logging
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest, TelegramForbiddenError

import db
from config import ALLOW_CHANNELS
from linkparser import Found

log = logging.getLogger("import")


async def resolve(bot: Bot, f: Found) -> dict | None:
    """Возвращает поля чата или None, если это не группа/канал."""
    if f.kind == "invite":
        # Бот не умеет «заглядывать» в приватные инвайты — берём подпись из поста
        return {"invite": f.key, "title": f.label or "Приватный чат", "kind": "private_link"}
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


async def run_import(bot: Bot, found: list[Found], added_by: int, category_id=None,
                     status="approved", source="import", progress=None):
    added, dup, failed, names = 0, 0, 0, []
    for i, f in enumerate(found, 1):
        exists = await db.find_existing(username=f.key if f.kind == "public" else None,
                                        invite=f.key if f.kind == "invite" else None)
        if exists:
            dup += 1
        else:
            data = await resolve(bot, f)
            if not data:
                failed += 1
            elif data.get("tg_id") and await db.find_existing(tg_id=data["tg_id"]):
                dup += 1
            else:
                rid = await db.add_chat(**data, category_id=category_id, status=status,
                                        added_by=added_by, source=source)
                if rid:
                    added += 1
                    names.append(data["title"] or data.get("username") or f.key)
                else:
                    dup += 1
            await asyncio.sleep(0.4)  # бережём лимиты на resolveUsername
        if progress and i % 10 == 0:
            await progress(i, len(found))
    return added, dup, failed, names
