"""Каталог чатов — Telegram-бот с Rich Messages (Bot API 10.3).

Запуск:  pip install -r requirements.txt  &&  cp .env.example .env  &&  python bot.py
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BotCommand, MenuButtonCommands, CallbackQuery, InlineQuery, InlineQueryResultArticle,
                           InputTextMessageContent, KeyboardButton, KeyboardButtonRequestChat,
                           Message, ReplyKeyboardMarkup, ReplyKeyboardRemove)

import db
import views
from config import ADMINS, ALLOW_CHANNELS, BOT_TOKEN, PAGE_SIZE, SOURCE_CHANNELS, is_admin
from importer import post_fields, resolve, run_import
from linkparser import Found, Post, extract, parse_post
from tgrich import Rich, esc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
rich = Rich(BOT_TOKEN)
dp = Dispatcher()
r = Router()
r.message.filter(F.chat.type == "private")
ch_router = Router()  # посты каналов-источников


class Add(StatesGroup):
    link = State()
    about = State()
    photo = State()


class Pic(StatesGroup):
    waiting = State()


class Ren(StatesGroup):
    waiting = State()


class Imp(StatesGroup):
    waiting = State()


class Srch(StatesGroup):
    waiting = State()


CANCEL = "❌ Отмена"


# ============================ фото ============================
async def media_resolver(mid: str):
    """tg://photo?id=chat15 -> file_id (обложка/кэш) или байты аватарки для загрузки."""
    if not mid.startswith("chat") or not mid[4:].isdigit():
        return None
    ch = await db.chat(int(mid[4:]))
    if not ch:
        return None
    if ch.get("cover_id"):
        return "file_id", ch["cover_id"]
    if ch.get("photo_id"):
        return "file_id", ch["photo_id"]
    for attempt in range(2):
        if ch.get("avatar_id"):
            try:
                buf = await bot.download(ch["avatar_id"])
                return "bytes", buf.read()
            except Exception as e:
                logging.info("avatar download %s: %s", mid, e)
        if attempt or not ch.get("username"):
            break
        try:  # file_id аватарки устарел — берём свежий
            info = await bot.get_chat("@" + ch["username"])
            new = info.photo.big_file_id if info.photo else None
            await db.update_chat(ch["id"], avatar_id=new)
            ch["avatar_id"] = new
        except Exception:
            break
    return None


async def media_uploaded(mid: str, file_id: str):
    await db.update_chat(int(mid[4:]), photo_id=file_id)


rich.resolver = media_resolver
rich.on_uploaded = media_uploaded


# ============================ helpers ============================
async def show(cq: CallbackQuery, view):
    body, kb = view
    await rich.edit(cq.message.chat.id, cq.message.message_id, body, kb)


async def home_view(uid):
    return views.home(await db.stats(), is_admin(uid))


async def drop_draft(state: FSMContext):
    data = await state.get_data()
    if data.get("chat_id"):
        ch = await db.chat(data["chat_id"])
        if ch and ch["status"] == "draft":
            await db.delete_chat(ch["id"])


def add_keyboard():
    rows = [[KeyboardButton(text="📲 Выбрать мой чат", request_chat=KeyboardButtonRequestChat(
        request_id=1, chat_is_channel=False, request_title=True, request_username=True))]]
    if ALLOW_CHANNELS:
        rows.append([KeyboardButton(text="📢 Выбрать мой канал", request_chat=KeyboardButtonRequestChat(
            request_id=2, chat_is_channel=True, request_title=True, request_username=True))])
    rows.append([KeyboardButton(text=CANCEL)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


# ============================ общие команды ============================
@r.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext, command: CommandObject):
    await drop_draft(state)
    await state.clear()
    await db.touch_user(m.from_user.id, m.from_user.full_name)
    if command.args == "add":
        return await start_add(m.chat.id, state)
    await clear_old_keyboard(m.chat.id)
    await rich.send(m.chat.id, *await home_view(m.from_user.id))


async def clear_old_keyboard(chat_id: int):
    """Убирает нижнюю клавиатуру, оставшуюся от прежней версии бота."""
    try:
        tmp = await bot.send_message(chat_id, "⌛", reply_markup=ReplyKeyboardRemove())
        await tmp.delete()
    except Exception:
        pass


@r.message(Command("cancel"))
@r.message(F.text == CANCEL)
async def cmd_cancel(m: Message, state: FSMContext):
    await drop_draft(state)
    await state.clear()
    await m.answer("Отменено.", reply_markup=ReplyKeyboardRemove())
    await rich.send(m.chat.id, *await home_view(m.from_user.id))


@r.message(Command("help"))
async def cmd_help(m: Message):
    await rich.send(m.chat.id,
                    "<h2>ℹ️ Как пользоваться</h2><ul>"
                    "<li>Напиши слово — найду подходящие чаты.</li>"
                    "<li>Пришли ссылку t.me/… или @username — предложу добавить чат.</li>"
                    "<li>В любом чате набери <code>@" + esc((await bot.me()).username) + " запрос</code> — поиск инлайн.</li>"
                    "</ul>", views.kb([views.btn("⬅️ Меню", "home")]))


# ============================ добавление чата ============================
async def start_add(chat_id, state: FSMContext):
    await state.set_state(Add.link)
    await bot.send_message(chat_id, "<b>➕ Добавление чата</b>\n\nПришли ссылку (<code>t.me/…</code>, "
                                    "<code>@username</code> или инвайт <code>t.me/+…</code>) "
                                    "либо выбери свой чат кнопкой ниже.", reply_markup=add_keyboard())


async def process_add(m: Message, state: FSMContext, f: Found, tg_id=None, post: Post | None = None,
                      cover_id: str | None = None):
    existing = await db.find_existing(username=f.key if f.kind == "public" else None,
                                      invite=f.key if f.kind == "invite" else None, tg_id=tg_id)
    if existing and existing["status"] in ("draft", "rejected"):
        await db.delete_chat(existing["id"])
        existing = None
    if existing:
        await state.clear()
        await m.answer("Этот чат уже есть в каталоге 👇" if existing["status"] == "approved"
                       else "Этот чат уже ждёт модерации ⏳", reply_markup=ReplyKeyboardRemove())
        if existing["status"] == "approved":
            await rich.send(m.chat.id, *views.card(await db.chat(existing["id"]), is_admin(m.from_user.id)))
        return
    wait = await m.answer("🔎 Проверяю…", reply_markup=ReplyKeyboardRemove())
    data = await resolve(bot, f)
    await wait.delete()
    if not data:
        await m.answer("Не нашёл такой публичный чат. Проверь ссылку и пришли ещё раз (или /cancel).",
                       reply_markup=add_keyboard())
        return
    extra = post_fields(post, cover_id)
    if data["kind"] == "private_link":
        data.update(extra)
    else:
        for k, v in extra.items():
            if k in ("cover_id", "age", "tags") or not data.get(k):
                data[k] = v
    cid = await db.add_chat(**data, status="draft", added_by=m.from_user.id, source="user")
    await state.update_data(chat_id=cid)
    if post and post.title and (post.about or data.get("about")):
        # прислали готовый пост-карточку — описание уже есть
        return await (finish_add(m.from_user.id, m.chat.id, state) if cover_id or data.get("avatar_id")
                      else ask_photo(m.chat.id, state))
    await state.set_state(Add.about)
    if data["kind"] == "private_link" and not (post and post.title):
        hint = ("Это приватная ссылка, название я не вижу. Первой строкой напиши <b>название</b>, "
                "дальше — описание (о чём чат, возраст).")
    else:
        hint = f"Нашёл: <b>{esc(data['title'])}</b>. Напиши описание до 300 символов: о чём чат, возраст участников."
    await rich.send(m.chat.id, f"<h3>✍️ Описание</h3><p>{hint}</p>", views.kb([views.btn("Пропустить", "skip")]))


@r.message(Add.link, F.chat_shared)
async def add_shared(m: Message, state: FSMContext):
    sh = m.chat_shared
    if sh.username:
        return await process_add(m, state, Found("public", sh.username.lower(), sh.title or ""), tg_id=sh.chat_id)
    await m.answer(f"У «{esc(sh.title or 'чата')}» нет публичной ссылки. Пришли инвайт-ссылку "
                   "<code>t.me/+…</code> (Настройки чата → Пригласительные ссылки).")


@r.message(Add.link, F.text | F.caption)
async def add_link(m: Message, state: FSMContext):
    text, ents = message_text(m)
    found = extract(text, ents)
    if not found:
        return await m.answer("Не вижу ссылку. Пример: <code>https://t.me/durov_chat</code> или <code>@durov_chat</code>")
    await process_add(m, state, found[0], post=parse_post(text, ents), cover_id=photo_of(m))


@r.message(Add.about, F.text)
async def add_about(m: Message, state: FSMContext):
    cid = (await state.get_data())["chat_id"]
    ch = await db.chat(cid)
    text = m.text.strip()
    if ch["kind"] == "private_link" and ch["title"] in ("Чат", "Приватный чат", None, ""):
        title, _, rest = text.partition("\n")
        await db.update_chat(cid, title=title.strip()[:80], about=rest.strip()[:300] or None)
    else:
        await db.update_chat(cid, about=text[:300])
    p = parse_post(text + "\n" + (views.link(ch) or ""))
    if p and p.age:
        await db.update_chat(cid, age=p.age)
    await ask_photo(m.chat.id, state)


@r.callback_query(Add.about, F.data == "skip")
async def add_skip(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    await ask_photo(cq.message.chat.id, state)


async def ask_photo(chat_id, state: FSMContext):
    await state.set_state(Add.photo)
    ch = await db.chat((await state.get_data())["chat_id"])
    if ch.get("cover_id"):
        return await finish_add(ch["added_by"], chat_id, state)
    if ch.get("avatar_id"):
        body = ("<h3>🖼 Обложка</h3><figure><img src=\"" + views.photo_ref(ch) + "\"/>"
                "<figcaption>Сейчас — аватарка чата</figcaption></figure>"
                "<p>Пришли своё фото (баннер, скриншот), если хочешь заменить.</p>")
        kb = views.kb([views.btn("✅ Оставить аватарку", "photo_keep", style="success")])
    else:
        body = "<h3>🖼 Обложка</h3><p>Пришли картинку для карточки чата — так она заметнее в каталоге.</p>"
        kb = views.kb([views.btn("Без фото", "photo_keep")])
    await rich.send(chat_id, body, kb)


@r.message(Add.photo, F.photo)
async def add_photo(m: Message, state: FSMContext):
    await db.update_chat((await state.get_data())["chat_id"], cover_id=m.photo[-1].file_id)
    await finish_add(m.from_user.id, m.chat.id, state)


@r.message(Add.photo)
async def add_photo_wrong(m: Message):
    await m.answer("Нужна именно фотография (не файлом). Или нажми кнопку выше.")


@r.callback_query(Add.photo, F.data == "photo_keep")
async def add_photo_keep(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    await finish_add(cq.from_user.id, cq.message.chat.id, state)


# ---------- смена обложки админом ----------
@r.message(Pic.waiting, F.photo)
async def pic_set(m: Message, state: FSMContext):
    cid = (await state.get_data())["pic_chat"]
    await state.clear()
    await db.update_chat(cid, cover_id=m.photo[-1].file_id)
    await rich.send(m.chat.id, *views.card(await db.chat(cid), admin=True))


@r.message(Pic.waiting, F.text == "-")
async def pic_reset(m: Message, state: FSMContext):
    cid = (await state.get_data())["pic_chat"]
    await state.clear()
    await db.update_chat(cid, cover_id=None)
    await rich.send(m.chat.id, *views.card(await db.chat(cid), admin=True))


@r.message(Ren.waiting, F.text)
async def ren_set(m: Message, state: FSMContext):
    cid = (await state.get_data())["ren_chat"]
    await state.clear()
    await db.update_chat(cid, title=m.text.strip()[:80])
    ch = await db.chat(cid)
    await rich.send(m.chat.id, *views.card(ch, admin=True, moderation=ch["status"] == "pending"))


async def finish_add(uid, chat_id, state: FSMContext):
    cid = (await state.get_data())["chat_id"]
    await state.clear()
    if is_admin(uid):
        await db.update_chat(cid, status="approved")
        await rich.send(chat_id, "<h3>✅ Добавлено в каталог</h3>")
        return await rich.send(chat_id, *views.card(await db.chat(cid), admin=True))
    await db.update_chat(cid, status="pending")
    await rich.send(chat_id, "<h3>⏳ Заявка отправлена</h3><p>Как только модератор её одобрит, я напишу.</p>",
                    views.kb([views.btn("⬅️ Меню", "home")]))
    ch = await db.chat(cid)
    for a in ADMINS:
        try:
            await rich.send(a, "<p>🆕 <b>Новая заявка</b></p>")
            await rich.send(a, *views.card(ch, moderation=True))
        except Exception as e:
            logging.warning("admin notify %s: %s", a, e)


# ============================ импорт (админ) ============================
async def start_import(chat_id, admin_id, found, source="import", extra=None):
    msg = await rich.send(chat_id, f"<p>⏳ Нашёл ссылок: <b>{len(found)}</b>. Проверяю…</p>")
    mid = msg["message_id"]

    async def progress(i, n):
        await rich.edit(chat_id, mid, f"<p>⏳ Проверено {i} из {n}…</p>")

    added, dup, failed, names = await run_import(bot, found, admin_id, source=source,
                                                 progress=progress, extra=extra)
    await rich.edit(chat_id, mid, views.import_report(added, dup, failed, names),
                    views.kb([views.btn("💬 Все чаты", "all:0"), views.btn("🛡 Админка", "adm")]))


async def import_single(chat_id, admin_id, post: Post, cover_id, source):
    """Пост про один чат -> сразу карточка в каталоге (или обновление уже добавленной)."""
    added, dup, failed, names = await run_import(bot, [post.link], admin_id, source=source,
                                                 extra=post_fields(post, cover_id))
    f = post.link
    ch = await db.find_existing(username=f.key if f.kind == "public" else None,
                                invite=f.key if f.kind == "invite" else None)
    if not ch:
        return await rich.send(chat_id, "<p>⚠️ Чат по ссылке не нашёлся (или это не группа).</p>")
    head = "✅ Добавлено" if added else ("♻️ Обновлено" if names else "Уже в каталоге")
    await rich.send(chat_id, f"<p><b>{head}</b></p>")
    await rich.send(chat_id, *views.card(await db.chat(ch["id"]), admin=True))


def message_text(m: Message):
    return (m.text or m.caption or ""), (m.entities or m.caption_entities or [])


def photo_of(m: Message):
    return m.photo[-1].file_id if m.photo else None


async def import_message(m: Message, admin_id: int, source: str):
    """Общая логика для пересылки/режима импорта: один чат — карточка, много — пакетный импорт."""
    text, ents = message_text(m)
    if m.document and (m.document.file_name or "").lower().endswith((".txt", ".csv")):
        buf = await bot.download(m.document)
        text, ents = buf.read().decode("utf-8", "ignore"), []
    post = parse_post(text, ents)
    if post:
        return asyncio.create_task(import_single(m.chat.id, admin_id, post, photo_of(m), source))
    found = extract(text, ents)
    if not found:
        return await m.answer("Ссылок на чаты не нашёл 🤷")
    asyncio.create_task(start_import(m.chat.id, admin_id, found, source=source))


@r.message(Command("import"))
async def cmd_import(m: Message, state: FSMContext, command: CommandObject):
    if not is_admin(m.from_user.id):
        return
    await state.set_state(Imp.waiting)
    await rich.send(m.chat.id, "<h3>📥 Режим импорта</h3>"
                               "<ul><li>Пересылай посты из каналов-подборок</li><li>Вставляй текст со ссылками</li>"
                               "<li>Или пришли .txt-файл</li></ul><footer>Выход — /cancel</footer>")


@r.message(Imp.waiting, lambda m: not (m.text or "").startswith("/"))
async def import_any(m: Message, state: FSMContext):
    await import_message(m, m.from_user.id, "import")


@r.message(F.forward_origin, F.from_user.id.in_(ADMINS))
async def admin_forward(m: Message):
    """Админ просто пересылает посты — бот сам разбирает карточку чата или список ссылок."""
    await import_message(m, m.from_user.id, "forward")


@r.message(F.forward_origin)
async def user_forward(m: Message, state: FSMContext):
    """Обычный пользователь переслал пост с чатом — оформляем как заявку."""
    text, ents = message_text(m)
    found = extract(text, ents)
    if not found:
        return await m.answer("В пересланном посте ссылок на чаты нет.")
    await drop_draft(state)
    await state.set_state(Add.link)
    await process_add(m, state, found[0], post=parse_post(text, ents), cover_id=photo_of(m))


@ch_router.channel_post()
async def source_channel_post(m: Message):
    if not m.chat.username or m.chat.username.lower() not in SOURCE_CHANNELS:
        return
    text, ents = message_text(m)
    post = parse_post(text, ents)
    found = [post.link] if post else extract(text, ents)
    if not found:
        return
    added, dup, failed, names = await run_import(bot, found, 0, source=f"@{m.chat.username}",
                                                 extra=post_fields(post, photo_of(m)) if post else None)
    if added:
        for a in ADMINS:
            await rich.send(a, views.import_report(added, dup, failed, names) +
                            f"<footer>Автоимпорт из @{esc(m.chat.username)}</footer>")


# ============================ админ-команды ============================
@r.message(Command("admin"))
async def cmd_admin(m: Message):
    if is_admin(m.from_user.id):
        await rich.send(m.chat.id, *views.admin_panel(await db.stats()))


@r.message(Command("del"))
async def cmd_del(m: Message, command: CommandObject):
    if not is_admin(m.from_user.id) or not command.args:
        return
    arg = command.args.strip()
    ch = await db.chat(int(arg)) if arg.isdigit() else await db.find_existing(username=arg.lstrip("@").split("/")[-1])
    if not ch:
        return await m.answer("Не нашёл.")
    await db.delete_chat(ch["id"])
    await m.answer(f"🗑 Удалено: {esc(ch['title'])}")


@r.message(Command("avatars"))
async def cmd_avatars(m: Message):
    """Подтянуть аватарки чатам, добавленным до появления фото (или без них)."""
    if not is_admin(m.from_user.id):
        return
    rows = await db.chats_without_avatar()
    msg = await m.answer(f"🖼 Проверяю аватарки: {len(rows)} чатов…")
    got = 0
    for ch in rows:
        try:
            info = await bot.get_chat("@" + ch["username"])
            if info.photo:
                await db.update_chat(ch["id"], avatar_id=info.photo.big_file_id, photo_id=None)
                got += 1
        except Exception:
            pass
        await asyncio.sleep(0.4)
    await msg.edit_text(f"🖼 Готово: аватарки нашлись у {got} из {len(rows)}.")


# ============================ поиск / ссылки в свободном тексте ============================
async def do_search(m: Message, state: FSMContext, query: str):
    await state.set_state(None)
    await state.update_data(q=query)
    rows, total = await db.search(query, 0, PAGE_SIZE)
    await rich.send(m.chat.id, *views.chat_table(f"🔍 «{query}»", rows, total, 0, PAGE_SIZE, "s", back="home"))


@r.message(Srch.waiting, F.text)
async def search_state(m: Message, state: FSMContext):
    await do_search(m, state, m.text.strip()[:64])


@r.message((F.text & ~F.text.startswith("/")) | (F.photo & F.caption))
async def free_text(m: Message, state: FSMContext):
    text, ents = message_text(m)
    found = extract(text, ents)
    if found:  # прислали ссылку или пост — сразу предлагаем добавить
        if is_admin(m.from_user.id) and m.photo:
            return await import_message(m, m.from_user.id, "admin")
        await state.set_state(Add.link)
        return await process_add(m, state, found[0], post=parse_post(text, ents), cover_id=photo_of(m))
    if not m.text:
        return
    await do_search(m, state, m.text.strip()[:64])


# ============================ callbacks ============================
@r.callback_query(F.data == "noop")
async def cb_noop(cq: CallbackQuery):
    await cq.answer()


@r.callback_query(F.data == "home")
async def cb_home(cq: CallbackQuery, state: FSMContext):
    await drop_draft(state)
    await state.clear()
    await show(cq, await home_view(cq.from_user.id))
    await cq.answer()


@r.callback_query(F.data.startswith("all:"))
async def cb_all(cq: CallbackQuery):
    page = int(cq.data.split(":")[1])
    rows, total = await db.list_chats(offset=page * PAGE_SIZE, limit=PAGE_SIZE)
    await show(cq, views.chat_table("💬 Все чаты · новые сверху", rows, total, page, PAGE_SIZE, "all"))
    await cq.answer()


@r.callback_query(F.data.startswith("top:"))
async def cb_top(cq: CallbackQuery):
    page = int(cq.data.split(":")[1])
    rows, total = await db.list_chats(offset=page * PAGE_SIZE, limit=PAGE_SIZE, order="members DESC, id DESC")
    await show(cq, views.chat_table("🔥 Топ по участникам", rows, total, page, PAGE_SIZE, "top"))
    await cq.answer()


@r.callback_query(F.data == "rnd")
async def cb_random(cq: CallbackQuery):
    ch = await db.random_chat()
    if not ch:
        return await cq.answer("В каталоге пока нет чатов", show_alert=True)
    await rich.send(cq.message.chat.id, *views.card(ch, admin=is_admin(cq.from_user.id), random=True))
    await cq.answer("🎲")


@r.callback_query(F.data.startswith("s:"))
async def cb_search_page(cq: CallbackQuery, state: FSMContext):
    page = int(cq.data.split(":")[1])
    q = (await state.get_data()).get("q", "")
    rows, total = await db.search(q, page * PAGE_SIZE, PAGE_SIZE)
    await show(cq, views.chat_table(f"🔍 «{q}»", rows, total, page, PAGE_SIZE, "s", back="home"))
    await cq.answer()


@r.callback_query(F.data.startswith("card:"))
async def cb_card(cq: CallbackQuery):
    ch = await db.chat(int(cq.data.split(":")[1]))
    if not ch:
        return await cq.answer("Чат удалён", show_alert=True)
    await rich.send(cq.message.chat.id, *views.card(ch, admin=is_admin(cq.from_user.id)))
    await cq.answer()


@r.callback_query(F.data == "add")
async def cb_add(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    await start_add(cq.message.chat.id, state)


@r.callback_query(F.data == "search")
async def cb_search(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Srch.waiting)
    await cq.answer()
    await cq.message.answer("🔍 Напиши, что ищешь: тему, город, язык…")


# ---------- админские callbacks ----------
async def next_pending(cq: CallbackQuery, prefix: str = ""):
    rows, total = await db.list_chats(status="pending", limit=1, order="id ASC")
    if not rows:
        return await show(cq, (prefix + "<p>🎉 Очередь модерации пуста.</p>",
                               views.kb([views.btn("🛡 Админка", "adm")])))
    body, kb = views.card(await db.chat(rows[0]["id"]), moderation=True)
    await show(cq, (prefix + f"<p>📝 В очереди: {total}</p>" + body, kb))


@r.callback_query(F.data.in_({"adm", "pend", "imp"}) | F.data.regexp(r"^(mod|del|delok|ren|pic):"))
async def cb_admin(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return await cq.answer("Только для админов", show_alert=True)
    d = cq.data
    if d == "adm":
        await show(cq, views.admin_panel(await db.stats()))
    elif d == "pend":
        await next_pending(cq)
    elif d == "imp":
        await state.set_state(Imp.waiting)
        await cq.message.answer("📥 Режим импорта: пересылай посты, вставляй текст или пришли .txt. Выход — /cancel")
    elif d.startswith("mod:"):
        _, action, cid = d.split(":")
        ch = await db.chat(int(cid))
        if not ch or ch["status"] != "pending":
            await cq.answer("Уже обработано")
            return await next_pending(cq)
        ok = action == "ok"
        await db.update_chat(ch["id"], status="approved" if ok else "rejected")
        try:
            if ok:
                await rich.send(ch["added_by"], "<h3>🎉 Ваш чат добавлен в каталог!</h3>")
                await rich.send(ch["added_by"], *views.card(await db.chat(ch["id"])))
            else:
                await rich.send(ch["added_by"], f"<p>😔 Заявка «{esc(ch['title'])}» отклонена модератором.</p>")
        except Exception:
            pass
        await next_pending(cq, f"<p>{'✅ Одобрено' if ok else '❌ Отклонено'}: {esc(ch['title'])}</p>")
    elif d.startswith("delok:"):
        ch = await db.chat(int(d.split(":")[1]))
        if ch:
            await db.delete_chat(ch["id"])
        await show(cq, (f"<p>🗑 Удалено: {esc(ch['title'] if ch else '')}</p>",
                        views.kb([views.btn("💬 Все чаты", "all:0")])))
    elif d.startswith("del:"):
        cid = d.split(":")[1]
        await rich.edit(cq.message.chat.id, cq.message.message_id, "<h3>Удалить чат из каталога?</h3>",
                        views.kb([views.btn("🗑 Да, удалить", f"delok:{cid}", style="danger"),
                                  views.btn("Отмена", f"card:{cid}")]))
    elif d.startswith("pic:"):
        await state.set_state(Pic.waiting)
        await state.update_data(pic_chat=int(d.split(":")[1]))
        await cq.message.answer("🖼 Пришли новое фото для карточки. Отправь «-», чтобы вернуть аватарку чата.")
    elif d.startswith("ren:"):
        await state.set_state(Ren.waiting)
        await state.update_data(ren_chat=int(d.split(":")[1]))
        await cq.message.answer("✏️ Пришли новое название чата.")
    await cq.answer()


# ============================ inline-поиск ============================
@dp.inline_query()
async def inline(iq: InlineQuery):
    q = iq.query.strip()
    rows = (await db.search(q, 0, 20))[0] if q else (await db.list_chats(limit=20))[0]
    results = []
    for ch in rows:
        url = views.link(ch)
        desc = " · ".join(x for x in [views.KIND.get(ch["kind"], ""), f"👥 {views.num(ch['members'])}" if ch["members"] else "",
                                       (ch["about"] or "")[:60]] if x)
        results.append(InlineQueryResultArticle(
            id=str(ch["id"]), title=ch["title"] or url, description=desc, url=url,
            input_message_content=InputTextMessageContent(
                message_text=f"<b>{esc(ch['title'])}</b>\n{esc((ch['about'] or '')[:300])}\n\n👉 {esc(url)}",
                parse_mode="HTML")))
    await iq.answer(results, cache_time=30, is_personal=False)


# ============================ run ============================
async def main():
    await db.init()
    dp.include_router(r)
    dp.include_router(ch_router)
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="help", description="Как пользоваться"),
        BotCommand(command="cancel", description="Отменить действие"),
    ])
    # сброс того, что осталось от прежнего бота: кнопка меню Mini App, старые апдейты/вебхук
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Bot started. Admins: %s", ADMINS)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
