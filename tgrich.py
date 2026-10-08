"""Тонкий клиент для Rich Messages (Bot API 10.1+): sendRichMessage / editMessageText(rich_message).

Фото: в HTML пишем <img src="tg://photo?id=chat15"/>. Перед отправкой Rich находит такие ссылки
и через resolver получает файл: готовый file_id (переиспользуем) или байты (загружаем multipart).
После первой загрузки file_id из ответа сохраняется через on_uploaded — дальше фото не грузится заново.
Если API не принял rich-сообщение, бот автоматически шлёт обычный HTML (без картинок)."""
import html
import json
import logging
import re
from typing import Awaitable, Callable

import httpx

log = logging.getLogger("rich")
MEDIA_RE = re.compile(r'tg://photo\?id=([A-Za-z0-9_-]{1,64})')

# resolver(media_id) -> ("file_id", "AgAC...") | ("bytes", b"...") | None
Resolver = Callable[[str], Awaitable[tuple[str, object] | None]]
Uploaded = Callable[[str, str], Awaitable[None]]


class TgError(Exception):
    pass


def to_legacy(body: str) -> str:
    """Rich HTML -> обычный Telegram HTML (запасной вариант)."""
    s = body
    s = re.sub(r"<figure>.*?</figure>", "", s, flags=re.S)
    s = re.sub(r"<tg-collage>.*?</tg-collage>|<tg-slideshow>.*?</tg-slideshow>", "", s, flags=re.S)
    s = re.sub(r"<img[^>]*/?>", "", s)
    s = re.sub(r"<h[1-3][^>]*>(.*?)</h[1-3]>", r"<b>\1</b>\n", s, flags=re.S)
    s = re.sub(r"<h[4-6][^>]*>(.*?)</h[4-6]>", r"<u>\1</u>\n", s, flags=re.S)
    s = re.sub(r'<tg-button type="url"[^>]*url="([^"]+)"[^>]*>(.*?)</tg-button>', r'<a href="\1">\2</a>  ', s, flags=re.S)
    s = re.sub(r"<tg-button[^>]*>.*?</tg-button>", "", s, flags=re.S)
    s = re.sub(r"</?tg-button-row[^>]*>", "\n", s)
    s = re.sub(r"<tr[^>]*>", "", s)
    s = re.sub(r"</tr>", "\n", s)
    s = re.sub(r"</t[dh]>[ \t]*<t[dh][^>]*>", " · ", s)
    s = re.sub(r"</?(table|caption|t[dh]|tbody|thead)[^>]*>", "", s)
    s = re.sub(r"<li[^>]*>", "• ", s)
    s = re.sub(r"</li>", "\n", s)
    s = re.sub(r"</?(ul|ol|p|footer|details|aside)[^>]*>", "\n", s)
    s = re.sub(r"<summary>(.*?)</summary>", r"<b>\1</b>\n", s, flags=re.S)
    s = re.sub(r"<hr\s*/?>", "\n──────────\n", s)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()[:4000]


def _find_photo_ids(obj, out: list):
    """Собирает file_id крупнейших фото из ответа (rich_message.blocks...) в порядке появления."""
    if isinstance(obj, dict):
        if obj.get("type") == "photo" and isinstance(obj.get("photo"), list) and obj["photo"]:
            out.append(obj["photo"][-1]["file_id"])
            return
        for v in obj.values():
            _find_photo_ids(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _find_photo_ids(v, out)


class Rich:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.http = httpx.AsyncClient(timeout=60)
        self.enabled = True  # выключится сам, если API не знает sendRichMessage
        self.resolver: Resolver | None = None
        self.on_uploaded: Uploaded | None = None

    async def call(self, method: str, files=None, **params):
        params = {k: v for k, v in params.items() if v is not None}
        if files:  # multipart: все не-файловые поля — строки/JSON
            data = {k: v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for k, v in params.items()}
            r = await self.http.post(self.base + method, data=data, files=files)
        else:
            r = await self.http.post(self.base + method, json=params)
        d = r.json()
        if not d.get("ok"):
            raise TgError(d.get("description", "error"))
        return d["result"]

    async def _media(self, body: str):
        """Возвращает (body, media[], files{}, uploaded_ids[]) для rich_message."""
        media, files, uploaded = [], {}, []
        for mid in dict.fromkeys(MEDIA_RE.findall(body)):
            got = await self.resolver(mid) if self.resolver else None
            if not got:  # фото недоступно — убираем картинку из вёрстки
                body = re.sub(r'<img src="tg://photo\?id=' + mid + r'"\s*/>', "", body)
                continue
            kind, val = got
            if kind == "file_id":
                media.append({"id": mid, "media": {"type": "photo", "media": val}})
            else:
                files[mid] = (f"{mid}.jpg", val, "image/jpeg")
                media.append({"id": mid, "media": {"type": "photo", "media": f"attach://{mid}"}})
                uploaded.append(mid)
        body = re.sub(r"<figure>\s*</figure>|<tg-collage>\s*</tg-collage>", "", body)
        return body, media, files, uploaded

    async def _cache(self, result, body: str, uploaded: list):
        if not uploaded or not self.on_uploaded or not isinstance(result, dict):
            return
        order = list(dict.fromkeys(MEDIA_RE.findall(body)))
        ids: list = []
        _find_photo_ids(result.get("rich_message"), ids)
        if len(ids) != len(order):
            return  # не можем однозначно сопоставить — в следующий раз загрузим заново
        for mid, fid in zip(order, ids):
            if mid in uploaded:
                await self.on_uploaded(mid, fid)

    async def _rich(self, method: str, body: str, **params):
        body, media, files, uploaded = await self._media(body)
        rm = {"html": body}
        if media:
            rm["media"] = media
        res = await self.call(method, files=files or None, rich_message=rm, **params)
        await self._cache(res, body, uploaded)
        return res

    async def send(self, chat_id, body: str, kb=None, **extra):
        if self.enabled:
            try:
                return await self._rich("sendRichMessage", body, chat_id=chat_id, reply_markup=kb, **extra)
            except TgError as e:
                log.warning("rich send failed: %s", e)
                if "not found" in str(e).lower() and "method" in str(e).lower():
                    self.enabled = False
        return await self.call("sendMessage", chat_id=chat_id, text=to_legacy(body), parse_mode="HTML",
                               reply_markup=kb, link_preview_options={"is_disabled": True}, **extra)

    async def edit(self, chat_id, message_id, body: str, kb=None):
        try:
            if self.enabled:
                try:
                    return await self._rich("editMessageText", body, chat_id=chat_id,
                                            message_id=message_id, reply_markup=kb)
                except TgError as e:
                    if "not modified" in str(e).lower():
                        return None
                    log.warning("rich edit failed: %s", e)
            return await self.call("editMessageText", chat_id=chat_id, message_id=message_id,
                                   text=to_legacy(body), parse_mode="HTML", reply_markup=kb,
                                   link_preview_options={"is_disabled": True})
        except TgError as e:
            if "not modified" in str(e).lower():
                return None
            # сообщение нельзя изменить (старое/удалено) — отправим новое
            return await self.send(chat_id, body, kb)


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)
