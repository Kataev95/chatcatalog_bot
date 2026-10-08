"""Выгрузка ВСЕХ ссылок на чаты из истории канала-подборки (через ваш аккаунт, Telethon).
Бот не может читать старые посты чужого канала, а аккаунт пользователя — может.

pip install telethon
API_ID/API_HASH взять на https://my.telegram.org -> API development tools

python export_channel.py @channel_name [@second_channel ...]
Результат: links.txt -> отправьте его боту после команды /import (можно с категорией: /import Крипта)
"""
import asyncio
import os
import sys

from telethon import TelegramClient
from telethon.tl.types import MessageEntityTextUrl

from linkparser import extract

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")


async def main(channels):
    seen = {}
    async with TelegramClient("export_session", API_ID, API_HASH) as client:
        for ch in channels:
            n = 0
            async for msg in client.iter_messages(ch):
                text = msg.message or ""
                ents = [{"type": "text_link", "offset": e.offset, "length": e.length, "url": e.url}
                        for e in (msg.entities or []) if isinstance(e, MessageEntityTextUrl)]
                for f in extract(text, ents):
                    if f.key not in seen:
                        seen[f.key] = f
                        n += 1
            print(f"{ch}: новых ссылок {n}")
    with open("links.txt", "w", encoding="utf-8") as out:
        for f in seen.values():
            url = f.key if f.kind == "invite" else f"https://t.me/{f.key}"
            out.write(f"{f.label} {url}\n".lstrip())
    print(f"Готово: {len(seen)} ссылок -> links.txt")


if __name__ == "__main__":
    if not API_ID or len(sys.argv) < 2:
        sys.exit("Задайте API_ID/API_HASH в окружении и передайте каналы: python export_channel.py @chan")
    asyncio.run(main(sys.argv[1:]))
