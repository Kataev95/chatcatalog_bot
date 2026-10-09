"""Вёрстка: rich-HTML сообщения и инлайн-клавиатуры с цветными кнопками (style)."""
import time
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


def pinned(ch) -> bool:
    return int(ch.get("pinned_until") or 0) > time.time()


def rating(ch) -> str:
    s = int(ch.get("likes") or 0) - int(ch.get("dislikes") or 0)
    return f"{s:+d}" if s else "0"


def days_word(n):
    n = int(n)
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} дня"
    return f"{n} дней"


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
        f"<p>💬 В каталоге <b>{st['approved']}</b> чатов</p>"
        "<footer>Ищи прямо отсюда: просто напиши слово, например «крипта».</footer>"
    )
    rows = [
        [btn("💬 Все чаты", "all:0", style="primary"), btn("🔥 Топ", "top:0"),
         btn("🎲 Рандом", "rnd")],
        [btn("➕ Добавить свой чат", "add", style="success")],
        [btn("🛍 Магазин услуг · Улучшения чата", "shop", style="primary")],
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
        f"<td>{'📌 ' if pinned(r) else ''}<a href=\"{esc(link(r))}\">{esc(r['title'] or r['username'])}</a></td>"
        f"<td align=\"center\">{esc(r.get('age') or '—')}</td>"
        f"<td align=\"right\">{rating(r)}</td></tr>"
        for i, r in enumerate(rows)
    )
    refs = [photo_ref(r) for r in rows[:6] if photo_ref(r)]
    collage = ("<tg-collage>" + "".join(f"<img src=\"{x}\"/>" for x in refs) + "</tg-collage>") if len(refs) >= 2 else ""
    body = (
        f"<h2>{esc(title)}</h2>{collage}"
        f"<table striped compact><tr><th>#</th><th>Чат</th><th>Возраст</th><th>👍</th></tr>{trs}</table>"
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


def card(ch, admin=False, moderation=False, random=False, my_vote=0):
    url = link(ch)
    meta = [KIND.get(ch.get("kind"), "💬 Чат")]
    if ch.get("members"):
        meta.append(f"👥 {num(ch['members'])}")
    if ch.get("age"):
        meta.append(f"🔞 {esc(ch['age'])}")
    if pinned(ch):
        meta.append("📌 В топе")
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
    likes, dislikes = int(ch.get("likes") or 0), int(ch.get("dislikes") or 0)
    rows = [
        [btn(f"👍 {likes}", f"vote:1:{ch['id']}", style="success" if my_vote == 1 else None),
         btn(f"👎 {dislikes}", f"vote:-1:{ch['id']}", style="danger" if my_vote == -1 else None)],
        [btn("↗️ Поделиться", copy=url), btn("🚀 Поднять в топ", f"pinm:{ch['id']}")],
    ] if ch.get("status") == "approved" else [[btn("↗️ Поделиться", copy=url)]]
    if random:
        rows.append([btn("🎲 Ещё случайный", "rnd", style="primary")])
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
                    [btn("📊 Статистика", "stats"), btn("🛍 Заказы", "orders")],
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


# ---------------- закрепление за звёзды ----------------
def pin_menu(ch, plans):
    now = "<p>📌 Сейчас чат уже в топе — новое закрепление продлит срок.</p>" if pinned(ch) else ""
    body = (
        f"<h2>🚀 Поднять «{esc(ch['title'] or 'чат')}» в топ</h2>"
        "<p>Чат закрепится первым в «Все чаты» и «Топ» с отметкой 📌. Оплата — Telegram Stars ⭐.</p>"
        f"{now}"
    )
    rows = [[btn(f"📌 {days_word(d)} — {s} ⭐", f"pinb:{ch['id']}:{d}", style="primary")] for d, s in plans]
    rows.append([btn("⬅️ Назад", f"card:{ch['id']}")])
    return body, kb(*rows)


# ---------------- статистика ----------------
def stats_view(s):
    def lst(items, fmt):
        return "<ol>" + "".join(f"<li>{fmt(x)}</li>" for x in items) + "</ol>" if items else "<p>—</p>"

    import shop
    pays = lst(s["last_pay"], lambda p: (f"#{p['id']} · {p['stars']} ⭐ · " + (
        esc(shop.title(p['service'], p.get('qty') or 1)) if p.get('service') else
        f"📌 {days_word(p['days'])} · {esc(p['title'] or 'удалён')}") + (' · возврат' if p['refunded'] else '')))
    body = (
        "<h2>📊 Статистика</h2>"
        "<table bordered compact><tr><th></th><th>24 ч</th><th>7 дней</th><th>Всего</th></tr>"
        f"<tr><td>Новые пользователи</td><td align=\"center\">{s['new1']}</td><td align=\"center\">{s['new7']}</td>"
        f"<td align=\"center\">{s['users']}</td></tr>"
        f"<tr><td>Активные</td><td align=\"center\">{s['active1']}</td><td align=\"center\">{s['active7']}</td><td align=\"center\">—</td></tr>"
        f"<tr><td>Открытия карточек</td><td align=\"center\">{s['views1']}</td><td align=\"center\">{s['views7']}</td>"
        f"<td align=\"center\">{s['views_all']}</td></tr></table>"
        f"<p>💬 Чатов: <b>{s['approved']}</b> · 📝 на модерации: {s['pending']} · 📌 в топе: {s['pinned']}</p>"
        f"<p>👍 {s['likes']} · 👎 {s['dislikes']} · ⭐ заработано: <b>{s['stars']}</b> (за 7 дней {s['stars7']})</p>"
        f"<p>🛍 Услуги: {s['shop_stars']} ⭐ · открытых заказов: {s['orders_open']}</p>"
        "<details><summary>🔥 Самые просматриваемые за 7 дней</summary>"
        + lst(s["top_views"], lambda x: f"{esc(x['title'] or '—')} — {x['n']}") + "</details>"
        "<details><summary>❤️ Лучший рейтинг</summary>"
        + lst(s["top_likes"], lambda x: f"{esc(x['title'] or '—')} — 👍 {x['likes']} · 👎 {x['dislikes']}") + "</details>"
        "<details><summary>⭐ Последние оплаты</summary>" + pays +
        "<p>Возврат звёзд: <code>/refund номер</code></p></details>"
    )
    return body, kb([btn("🔄 Обновить", "stats")], [btn("🛡 Админка", "adm")])


# ---------------- магазин услуг ----------------
def shop_menu():
    import shop
    trs = "".join(
        f"<tr><td>{s['emoji']} <b>{esc(s['name'])}</b>{' 🔥' if s.get('hit') else ''}<br/>"
        f"<i>{esc(s['short'])}</i></td>"
        f"<td align=\"right\"><b>{s['price']} ⭐</b>{'<br/>за 1 ' + s['unit'] if s.get('unit') else ''}</td></tr>"
        for s in shop.SERVICES.values()
    )
    body = (
        "<h1>🛍 Магазин услуг</h1>"
        "<p><b>Улучшения чата</b> — сделаем ваш чат живее, ярче и заметнее.</p>"
        f"<table striped><tr><th>Услуга</th><th>Цена</th></tr>{trs}</table>"
        "<footer>Оплата — Telegram Stars ⭐ прямо в боте. Нажми услугу, чтобы узнать подробности.</footer>"
    )
    keys = list(shop.SERVICES)
    rows = [[btn(f"{shop.SERVICES[k]['emoji']} {shop.SERVICES[k]['name']}", f"svc:{k}",
                 style="primary" if shop.SERVICES[k].get("hit") else None)] for k in keys]
    rows.append([btn("🚀 Поднять свой чат в топ", "pinhelp")])
    rows.append([btn("⬅️ Меню", "home")])
    return body, kb(*rows)


def service_card(key):
    import shop
    s = shop.SERVICES[key]
    perks = "".join(f"<li>{esc(p)}</li>" for p in s.get("perks", []))
    ex = s.get("examples") or []
    ex_row = ("<tg-button-row align=\"center\">" + "".join(
        f"<tg-button type=\"url\" url=\"{esc(u)}\">{esc(t)}</tg-button>" for t, u in ex) + "</tg-button-row>") if ex else ""
    price = f"{s['price']} ⭐" + (f" за 1 {s['unit']}" if s.get("unit") else "")
    body = (
        f"<h2>{s['emoji']} {esc(s['name'])}</h2>"
        f"<p>{esc(s['about'])}</p>"
        + (f"<ul>{perks}</ul>" if perks else "")
        + ex_row
        + f"<h3>💰 Цена: {price}</h3>"
        "<footer>После оплаты бот передаст заказ администратору, он свяжется с вами.</footer>"
    )
    if s.get("qty"):
        rows = [[btn(f"🛒 {q} {s['unit']} — {s['price'] * q} ⭐", f"svcb:{key}:{q}", style="success")]
                for q in s["qty"]]
    else:
        rows = [[btn(f"🛒 Купить за {s['price']} ⭐", f"svcb:{key}:1", style="success")]]
    rows += [[btn(t, url=u) for t, u in ex]] if ex else []
    rows.append([btn("⬅️ Все услуги", "shop")])
    return body, kb(*rows)


def orders_view(rows):
    import shop
    if not rows:
        items = "<p>🎉 Открытых заказов нет.</p>"
    else:
        items = "<ol>" + "".join(
            f"<li>#{o['id']} · {esc(shop.title(o['service'], o['qty']))} · {o['stars']} ⭐ · "
            f"<a href=\"tg://user?id={o['user_id']}\">{esc(o.get('name') or o['user_id'])}</a>"
            f"{' · 📝 ' + esc((o.get('brief') or '')[:80]) if o.get('brief') else ''}</li>"
            for o in rows) + "</ol>"
    body = ("<h2>🛍 Заказы услуг</h2>" + items +
            "<footer>Выполнил заказ — <code>/done номер</code>, бот уведомит покупателя. "
            "Возврат — <code>/refund номер</code>.</footer>")
    return body, kb([btn("🔄 Обновить", "orders")], [btn("🛡 Админка", "adm")])
