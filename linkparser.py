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
