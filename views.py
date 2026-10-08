"""Вёрстка: rich-HTML сообщения и инлайн-клавиатуры с цветными кнопками (style)."""
from tgrich import esc

KIND = {"group": "💬 Чат", "supergroup": "💬 Чат", "channel": "📢 Канал", "private_link": "💬 Чат"}


def num(n) -> str:
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1000:
        return f"{n / 1000:.1f}K".replace(".0K", "K")
    return str(n)


def link(ch) -> str:
    return f"https://t.me/{ch['username']}" if ch.get("username") else (ch.get("invite") or "")


def photo_ref(ch) -> str:
    """Ссылка на фото чата для rich-сообщения; сам файл подставит tgrich через resolver."""
    return f"tg://photo?id=chat{ch['id']}" if (ch.get("cover_id") or ch.get("photo_id") or ch.get("avatar_id")) else ""


def btn(text, data=None, url=None, style=None, copy=None):
    b = {"text": text}
    if style:
        b["style"] = style  # "primary" | "success" | "danger"
    if url:
        b["url"] = url
    elif copy:
        b["copy_text"] = {"text": copy}
    else:
        b["callback_data"] = data
    return b


def kb(*rows):
    return {"inline_keyboard": [list(r) for r in rows if r]}


# ---------------- главное меню ----------------
def home(st, admin=False):
    body = (
        "<h1>🗂 Каталог чатов</h1>"
        "<p>Находи живые сообщества по интересам и добавляй свои — бесплатно.</p>"
        "<table bordered compact>"
        "<tr><th>Чатов</th><th>Охват</th><th>Пользователей</th></tr>"
        f"<tr><td align=\"center\">{st['approved']}</td><td align=\"center\">{num(st['reach'])}</td>"
        f"<td align=\"center\">{num(st['users'])}</td></tr></table>"
        "<footer>Ищи прямо отсюда: просто напиши слово, например «крипта».</footer>"
    )
    rows = [
        [btn("💬 Все чаты", "all:0", style="primary"), btn("🔥 Топ", "top:0")],
        [btn("➕ Добавить свой чат", "add", style="success")],
        [btn("🔍 Поиск", "search")],
    ]
    if admin:
        rows.append([btn(f"🛡 Админка · {st['pending']} на модерации", "adm", style="danger")])
    return body, kb(*rows)


def chat_table(title, rows, total, page, page_size, nav_prefix, back="home"):
    pages = max(1, (total + page_size - 1) // page_size)
    if not rows:
        body = f"<h2>{esc(title)}</h2><p>Пока пусто. Будь первым — добавь свой чат!</p>"
        return body, kb([btn("➕ Добавить", "add", style="success")], [btn("⬅️ Назад", back)])
    trs = "".join(
        f"<tr><td align=\"right\">{page * page_size + i + 1}</td>"
        f"<td><a href=\"{esc(link(r))}\">{esc(r['title'] or r['username'])}</a></td>"
        f"<td align=\"center\">{esc(r.get('age') or '—')}</td>"
        f"<td align=\"right\">{num(r['members']) if r['members'] else '—'}</td></tr>"
        for i, r in enumerate(rows)
    )
    refs = [photo_ref(r) for r in rows[:6] if photo_ref(r)]
    collage = ("<tg-collage>" + "".join(f"<img src=\"{x}\"/>" for x in refs) + "</tg-collage>") if len(refs) >= 2 else ""
    body = (
        f"<h2>{esc(title)}</h2>{collage}"
        f"<table striped compact><tr><th>#</th><th>Чат</th><th>Возраст</th><th>👥</th></tr>{trs}</table>"
        f"<footer>Страница {page + 1} из {pages} · всего {total}. Нажми номер, чтобы открыть карточку.</footer>"
    )
    nums = [btn(str(page * page_size + i + 1), f"card:{r['id']}") for i, r in enumerate(rows)]
    num_rows = [nums[i:i + 5] for i in range(0, len(nums), 5)]
    nav = []
    if page > 0:
        nav.append(btn("◀️", f"{nav_prefix}:{page - 1}"))
    nav.append(btn(f"{page + 1}/{pages}", "noop"))
    if page < pages - 1:
        nav.append(btn("▶️", f"{nav_prefix}:{page + 1}"))
    return body, kb(*num_rows, nav, [btn("⬅️ Назад", back)])


def card(ch, admin=False, moderation=False):
    url = link(ch)
    meta = [KIND.get(ch.get("kind"), "💬 Чат")]
    if ch.get("members"):
        meta.append(f"👥 {num(ch['members'])}")
    if ch.get("age"):
        meta.append(f"🔞 {esc(ch['age'])}")
    about = f"<blockquote expandable>{esc(ch['about'])}</blockquote>" if ch.get("about") else ""
    tags = f"<p>{esc(ch['tags'])}</p>" if ch.get("tags") else ""
    handle = f"<p><b>@{esc(ch['username'])}</b></p>" if ch.get("username") else ""
    ref = photo_ref(ch)
    pic = f"<figure><img src=\"{ref}\"/></figure>" if ref else ""
    body = (
        f"{pic}<h2>{esc(ch.get('title') or ch.get('username') or 'Чат')}</h2>"
        f"{handle}<p>{' · '.join(meta)}</p>{about}{tags}"
        "<tg-button-row align=\"center\">"
        f"<tg-button type=\"url\" style=\"success\" url=\"{esc(url)}\">Вступить</tg-button>"
        f"<tg-button type=\"copy_text\" text=\"{esc(url)}\">Скопировать ссылку</tg-button>"
        "</tg-button-row>"
    )
    if moderation:
        body += f"<footer>Заявка #{ch['id']} · от <a href=\"tg://user?id={ch['added_by']}\">пользователя</a></footer>"
        return body, kb([btn("✅ Одобрить", f"mod:ok:{ch['id']}", style="success"),
                         btn("❌ Отклонить", f"mod:no:{ch['id']}", style="danger")],
                        [btn("✏️ Название", f"ren:{ch['id']}"), btn("🖼 Обложка", f"pic:{ch['id']}")])
    rows = [[btn("↗️ Поделиться", copy=url)]]
    if admin:
        rows.append([btn("✏️ Название", f"ren:{ch['id']}"), btn("🖼 Обложка", f"pic:{ch['id']}"),
                     btn("🗑 Удалить", f"del:{ch['id']}", style="danger")])
    rows.append([btn("⬅️ Ко всем чатам", "all:0")])
    return body, kb(*rows)


def admin_panel(st):
    body = (
        "<h2>🛡 Админ-панель</h2>"
        f"<table bordered compact><tr><td>В каталоге</td><td align=\"right\">{st['approved']}</td></tr>"
        f"<tr><td>На модерации</td><td align=\"right\">{st['pending']}</td></tr>"
        f"<tr><td>Пользователей</td><td align=\"right\">{st['users']}</td></tr></table>"
        "<details><summary>Как массово добавить чаты</summary>"
        "<ol><li>Просто перешли мне посты из канала-подборки. Пост про один чат (картинка, название, ссылка, "
        "описание, возраст) добавится карточкой целиком, с картинкой. Из поста-списка я вытащу все ссылки.</li>"
        "<li>Перешлёшь уже добавленный чат ещё раз — обновлю название, описание и картинку.</li>"
        "<li>Или /import, затем вставь текст или пришли .txt со ссылками.</li>"
        "<li><code>/avatars</code> — подтянуть аватарки чатам, у которых их нет.</li><li>Сделай бота админом канала-источника и пропиши его в SOURCE_CHANNELS — новые посты будут импортироваться сами.</li></ol></details>"
        "<details><summary>Команды</summary><ul>"
        "<li><code>/del 15</code> или <code>/del @username</code> — удалить</li>"
        "</ul></details>"
    )
    return body, kb([btn(f"📝 Модерация ({st['pending']})", "pend", style="primary")],
                    [btn("📥 Массовый импорт", "imp", style="success")],
                    [btn("⬅️ Меню", "home")])


def import_report(added, dup, failed, names):
    lst = "".join(f"<li>{esc(n)}</li>" for n in names[:25])
    more = f"<p>…и ещё {len(names) - 25}</p>" if len(names) > 25 else ""
    return (
        "<h2>📥 Импорт завершён</h2>" +
        "<table bordered compact>"
        f"<tr><td>✅ Добавлено</td><td align=\"right\"><b>{added}</b></td></tr>"
        f"<tr><td>♻️ Уже были</td><td align=\"right\">{dup}</td></tr>"
        f"<tr><td>⚠️ Не найдено / не чат</td><td align=\"right\">{failed}</td></tr></table>"
        + (f"<details><summary>Что добавлено</summary><ul>{lst}</ul>{more}</details>" if names else "")
    )
