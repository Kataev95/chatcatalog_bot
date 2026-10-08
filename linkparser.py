"""Достаёт ссылки на чаты из текста поста: видимые t.me, @username и скрытые ссылки (text_link)."""
import re
from dataclasses import dataclass

USERNAME = r"[A-Za-z][A-Za-z0-9_]{3,31}"
LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t|telegram)\.(?:me|dog)/"
    r"(\+[\w-]{8,}|joinchat/[\w-]{8,}|" + USERNAME + r")(?:/\d+)?",
    re.I,
)
AT_RE = re.compile(r"(?<![\w@/.])@(" + USERNAME + r")\b")
RESERVED = {
    "joinchat", "addstickers", "addemoji", "addlist", "share", "proxy", "socks", "iv",
    "boost", "setlanguage", "login", "confirmphone", "addtheme", "invoice", "premium",
    "giftcode", "contact", "nft", "bg", "msg", "msg_url", "telegram", "username",
}
STRIP = " \t-—–:|•·▪️►▶️➖➡️→*_~`\"'«»()[]"


@dataclass(frozen=True)
class Found:
    kind: str   # "public" | "invite"
    key: str    # username (lower) или полная инвайт-ссылка
    label: str  # подпись из поста (название), может быть пустой


def _u16(text: str, off: int, ln: int) -> str:
    b = text.encode("utf-16-le")
    return b[off * 2:(off + ln) * 2].decode("utf-16-le", "ignore")


def _norm(path: str):
    if path.startswith("+") or path.lower().startswith("joinchat/"):
        return Found("invite", "https://t.me/" + path, "")
    u = path.lower()
    if u in RESERVED or u.endswith("bot"):
        return None
    return Found("public", u, "")


def _line_label(line: str, raw: str) -> str:
    lbl = line.replace(raw, " ")
    lbl = LINK_RE.sub(" ", lbl)
    lbl = AT_RE.sub(" ", lbl)
    return re.sub(r"\s+", " ", lbl).strip(STRIP)[:80]


def extract(text: str | None, entities=None) -> list[Found]:
    text = text or ""
    out: dict[str, Found] = {}

    def put(f: Found | None, label: str = ""):
        if not f:
            return
        if f.key not in out or (label and not out[f.key].label):
            out[f.key] = Found(f.kind, f.key, label.strip(STRIP)[:80])

    # 1) скрытые ссылки: "Название" -> t.me/...
    for e in entities or []:
        etype = getattr(e, "type", None) or (e.get("type") if isinstance(e, dict) else None)
        url = getattr(e, "url", None) or (e.get("url") if isinstance(e, dict) else None)
        if etype == "text_link" and url:
            m = LINK_RE.search(url)
            if m:
                off = getattr(e, "offset", None) if not isinstance(e, dict) else e["offset"]
                ln = getattr(e, "length", None) if not isinstance(e, dict) else e["length"]
                put(_norm(m.group(1)), _u16(text, off, ln))

    # 2) видимые ссылки и @упоминания, подпись — остаток строки
    for line in text.splitlines():
        for m in LINK_RE.finditer(line):
            put(_norm(m.group(1)), _line_label(line, m.group(0)))
        for m in AT_RE.finditer(line):
            put(_norm(m.group(1)), _line_label(line, m.group(0)))
    return list(out.values())


# ---------------- пост-карточка одного чата ----------------
# Формат каналов-подборок:
#   💬 Амазония
#   https://t.me/+eBD7utzeApBjY2Yy
#
#   Чат для общения.
#
#   👥 Возраст пользователей: 18+
#
#   #Общение
AGE_RE = re.compile(r"возраст[^:\n]*[:\-–—]\s*([0-9]{1,2}\s*\+|[0-9]{1,2}\s*[-–—]\s*[0-9]{1,2}|без ограничений|любой)", re.I)
TAG_RE = re.compile(r"#([\w\d_]+)")
LEAD_JUNK = re.compile(r"^[\W_]+", re.U)  # эмодзи/значки в начале строки


@dataclass
class Post:
    link: Found
    title: str = ""
    about: str = ""
    age: str = ""
    tags: str = ""


def _clean_title(line: str) -> str:
    t = LINK_RE.sub(" ", line)
    t = LEAD_JUNK.sub("", t.strip())
    return re.sub(r"\s+", " ", t).strip(" \t-—–:|•·*_~`\"'«»")[:80]


def parse_post(text: str | None, entities=None) -> Post | None:
    """Если пост описывает ровно один чат — достаёт название, описание, возраст и теги."""
    found = extract(text, entities)
    if len(found) != 1:
        return None
    f = found[0]
    text = text or ""
    lines = [l.strip() for l in text.splitlines()]
    title, about, age = "", [], ""
    tags = " ".join(dict.fromkeys("#" + t for t in TAG_RE.findall(text)))
    for line in lines:
        if not line:
            continue
        m = AGE_RE.search(line)
        if m:
            age = re.sub(r"\s+", "", m.group(1)) if m.group(1)[0].isdigit() else m.group(1)
            continue
        bare = LINK_RE.sub("", line)
        bare = AT_RE.sub("", bare).strip(STRIP)
        if not bare:  # строка — только ссылка
            continue
        if TAG_RE.sub("", bare).strip(STRIP + " ,") == "":  # строка — только хэштеги
            continue
        if not title:
            title = _clean_title(line)
            if title:
                continue
        about.append(line)
    if f.label and not title:
        title = _clean_title(f.label)
    return Post(f, title=title, about="\n".join(about)[:400], age=age, tags=tags)
