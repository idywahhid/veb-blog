"""
database.py — SQLite CRUD
"""
import os
import re
import sqlite3
from dataclasses import dataclass
from typing import Optional
from flask import g
from config import cfg

_IMG_SRC_RE = re.compile(r'src="[^"]*/uploads/([^"]+)"')

# Ruxsat etilgan ustun nomi va ta'rif juftliklari (SQL injection xavfini yo'q qilish uchun)
_ALLOWED_MIGRATIONS: list[tuple[str, str]] = [
    ("is_draft",   "INTEGER DEFAULT 0"),
    ("created_at", "TEXT DEFAULT (datetime('now'))"),
    ("updated_at", "TEXT DEFAULT (datetime('now'))"),
    ("author",     "TEXT DEFAULT 'admin'"),
    ("img_desc",   "TEXT"),
    ("location",   "TEXT"),
    ("views",      "INTEGER DEFAULT 0"),
    ("meta_description", "TEXT"),
    ("meta_keywords",    "TEXT"),
    ("publish_at",        "TEXT"),
]
_ALLOWED_COLUMNS = {col for col, _ in _ALLOWED_MIGRATIONS}

_ALLOWED_MSG_MIGRATIONS: list[tuple[str, str]] = [
    ("reply",      "TEXT DEFAULT NULL"),
    ("replied_at", "TEXT DEFAULT NULL"),
]
_ALLOWED_MSG_COLUMNS = {col for col, _ in _ALLOWED_MSG_MIGRATIONS}

_BOT_UA_RE    = re.compile(r"bot|spider|crawl|slurp|facebookexternalhit|preview", re.I)
_MOBILE_UA_RE = re.compile(r"iphone|android.*mobile|mobile safari|windows phone", re.I)
_TABLET_UA_RE = re.compile(r"ipad|android(?!.*mobile)|tablet", re.I)


def get_db() -> sqlite3.Connection:
    """So'rov davomida bitta ulanishni qayta ishlatadi (Flask `g` orqali)."""
    if "db" not in g:
        g.db = sqlite3.connect(cfg.DB_PATH)
        g.db.row_factory = sqlite3.Row
        # Foreign key qo'llab-quvvatlashni yoqish
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    """Jadvallarni yaratadi va migratsiyalarni qo'llaydi."""
    conn = sqlite3.connect(cfg.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                slug        TEXT    UNIQUE NOT NULL,
                title       TEXT    NOT NULL,
                content     TEXT    NOT NULL DEFAULT '',
                author      TEXT    DEFAULT 'admin',
                date        TEXT    NOT NULL,
                image       TEXT,
                img_desc    TEXT,
                location    TEXT,
                is_draft    INTEGER DEFAULT 0,
                created_at  TEXT    DEFAULT (datetime('now')),
                updated_at  TEXT    DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                platform    TEXT    DEFAULT '',
                username    TEXT    DEFAULT '',
                subject     TEXT    DEFAULT '',
                body        TEXT    NOT NULL,
                is_read     INTEGER DEFAULT 0,
                created_at  TEXT    DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS tags (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                slug TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS article_tags (
                article_id INTEGER NOT NULL,
                tag_id     INTEGER NOT NULL,
                PRIMARY KEY (article_id, tag_id),
                FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS admin_profile (
                id           INTEGER PRIMARY KEY CHECK (id = 1),
                display_name TEXT DEFAULT 'Admin',
                username     TEXT DEFAULT 'admin',
                avatar       TEXT,
                cover_image  TEXT,
                bio          TEXT
            );
            CREATE TABLE IF NOT EXISTS article_autosave (
                slug_key   TEXT PRIMARY KEY,
                title      TEXT,
                content    TEXT,
                tags       TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS message_tags (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                slug TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS message_tag_map (
                message_id INTEGER NOT NULL,
                tag_id     INTEGER NOT NULL,
                PRIMARY KEY (message_id, tag_id),
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES message_tags(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS reply_templates (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT NOT NULL,
                body       TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS error_logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                path       TEXT NOT NULL,
                referrer   TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS image_albums (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT UNIQUE NOT NULL,
                slug       TEXT UNIQUE NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS image_meta (
                filename   TEXT PRIMARY KEY,
                album_id   INTEGER,
                FOREIGN KEY (album_id) REFERENCES image_albums(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS feedback (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT,
                description TEXT NOT NULL,
                file_path   TEXT,
                page_slug   TEXT,
                status      TEXT DEFAULT 'new',
                created_at  TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS feedback_page_settings (
                page_slug TEXT PRIMARY KEY,
                enabled   INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS feedback_rate_limit (
                ip           TEXT PRIMARY KEY,
                window_ends  REAL NOT NULL,
                count        INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS page_visits (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                path       TEXT NOT NULL,
                referrer   TEXT,
                device     TEXT DEFAULT 'desktop',
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_page_visits_created ON page_visits(created_at);
            """)

            # Feedback widget uchun sahifalarni oldindan urug'lash (seed)
            for _slug in ("home", "blog", "article", "about", "kontakt", "javoblar", "cofe"):
                conn.execute(
                    "INSERT OR IGNORE INTO feedback_page_settings (page_slug, enabled) VALUES (?, 1)",
                    (_slug,),
                )
            conn.commit()

            # Migration: articles jadvaliga yetishmayotgan ustunlarni qo'shish.
            existing = {r[1] for r in conn.execute("PRAGMA table_info(articles)").fetchall()}
            for col, defn in _ALLOWED_MIGRATIONS:
                if col not in existing:
                    if col not in _ALLOWED_COLUMNS:
                        continue
                    conn.execute(f"ALTER TABLE articles ADD COLUMN {col} {defn}")

            # Migration: messages jadvaliga reply ustunlarini qo'shish.
            existing_msg = {r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()}
            for col, defn in _ALLOWED_MSG_MIGRATIONS:
                if col not in existing_msg:
                    if col not in _ALLOWED_MSG_COLUMNS:
                        continue
                    conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {defn}")

            # admin_profile uchun yagona qatorni kafolatlash
            conn.execute(
                "INSERT OR IGNORE INTO admin_profile (id, display_name, username) "
                "VALUES (1, 'Admin', ?)", (cfg.ADMIN_USERNAME,)
            )
    finally:
        conn.close()


@dataclass
class Article:
    id:         int
    slug:       str
    title:      str
    content:    str
    author:     str
    date:       str
    image:      Optional[str] = None
    img_desc:   Optional[str] = None
    location:   Optional[str] = None
    is_draft:   int = 0
    created_at: str = ""
    updated_at: str = ""
    views:      int = 0
    meta_description: Optional[str] = None
    meta_keywords:     Optional[str] = None
    publish_at:        Optional[str] = None

    @staticmethod
    def from_row(row) -> "Article":
        r = dict(row)
        return Article(
            id=r["id"], slug=r["slug"], title=r["title"],
            content=r.get("content", ""), author=r.get("author") or "admin",
            date=r["date"], image=r.get("image"),
            img_desc=r.get("img_desc"), location=r.get("location"),
            is_draft=r.get("is_draft", 0),
            created_at=r.get("created_at", ""),
            updated_at=r.get("updated_at", ""),
            views=r.get("views", 0) or 0,
            meta_description=r.get("meta_description"),
            meta_keywords=r.get("meta_keywords"),
            publish_at=r.get("publish_at"),
        )


@dataclass
class ContactMessage:
    id:          int
    name:        str
    body:        str
    platform:    Optional[str] = None
    username:    Optional[str] = None
    subject:     Optional[str] = None
    is_read:     int = 0
    created_at:  str = ""
    reply:       Optional[str] = None
    replied_at:  Optional[str] = None

    @staticmethod
    def from_row(row) -> "ContactMessage":
        r = dict(row)
        return ContactMessage(
            id=r["id"], name=r["name"], body=r["body"],
            platform=r.get("platform") or None,
            username=r.get("username") or None,
            subject=r.get("subject") or None,
            is_read=r.get("is_read", 0),
            created_at=r.get("created_at", ""),
            reply=r.get("reply") or None,
            replied_at=r.get("replied_at") or None,
        )


# ── Articles ───────────────────────────────────────────────────────────────────

def get_all_articles(include_drafts: bool = False) -> dict:
    conn = get_db()
    if include_drafts:
        rows = conn.execute("SELECT * FROM articles ORDER BY date DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM articles WHERE is_draft=0 ORDER BY date DESC"
        ).fetchall()
    return {r["slug"]: Article.from_row(r) for r in rows}


def get_article_by_slug(slug: str) -> Optional[Article]:
    conn = get_db()
    row = conn.execute("SELECT * FROM articles WHERE slug=?", (slug,)).fetchone()
    return Article.from_row(row) if row else None


def add_article(slug, title, content, author, date, image=None, img_desc=None, location=None,
                 is_draft=0, meta_description=None, meta_keywords=None, publish_at=None):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO articles (slug,title,content,author,date,image,img_desc,location,is_draft,"
        "meta_description,meta_keywords,publish_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (slug, title, content, author, date, image, img_desc, location, is_draft,
         meta_description, meta_keywords, publish_at),
    )
    conn.commit()
    return cur.lastrowid


def update_article(slug, title, content, author, date, image=None, img_desc=None, location=None,
                    is_draft=0, meta_description=None, meta_keywords=None, publish_at=None):
    conn = get_db()
    conn.execute(
        "UPDATE articles SET title=?,content=?,author=?,date=?,image=?,img_desc=?,"
        "location=?,is_draft=?,meta_description=?,meta_keywords=?,publish_at=?,"
        "updated_at=datetime('now') WHERE slug=?",
        (title, content, author, date, image, img_desc, location, is_draft,
         meta_description, meta_keywords, publish_at, slug),
    )
    conn.commit()


def delete_article(slug: str) -> None:
    conn = get_db()
    conn.execute("DELETE FROM articles WHERE slug=?", (slug,))
    conn.commit()


def delete_articles(slugs: list[str]) -> None:
    conn = get_db()
    conn.executemany("DELETE FROM articles WHERE slug=?", [(s,) for s in slugs])
    conn.commit()


def set_articles_draft_status(slugs: list[str], is_draft: int) -> None:
    conn = get_db()
    conn.executemany(
        "UPDATE articles SET is_draft=?, updated_at=datetime('now') WHERE slug=?",
        [(is_draft, s) for s in slugs],
    )
    conn.commit()


def auto_publish_scheduled() -> None:
    """publish_at vaqti kelgan draftlarni avtomatik nashr qiladi."""
    conn = get_db()
    conn.execute(
        "UPDATE articles SET is_draft=0 WHERE is_draft=1 "
        "AND publish_at IS NOT NULL AND publish_at != '' AND publish_at <= datetime('now')"
    )
    conn.commit()


# ── Autosave (qoralamalarni tasodifiy yo'qotmaslik uchun) ───────────────────

def save_autosave(slug_key: str, title: str, content: str) -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO article_autosave (slug_key,title,content,updated_at) "
        "VALUES (?,?,?,datetime('now')) "
        "ON CONFLICT(slug_key) DO UPDATE SET title=excluded.title, content=excluded.content, "
        "updated_at=excluded.updated_at",
        (slug_key, title, content),
    )
    conn.commit()


def get_autosave(slug_key: str) -> Optional[dict]:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM article_autosave WHERE slug_key=?", (slug_key,)
    ).fetchone()
    return dict(row) if row else None


def delete_autosave(slug_key: str) -> None:
    conn = get_db()
    conn.execute("DELETE FROM article_autosave WHERE slug_key=?", (slug_key,))
    conn.commit()


# ── Messages ───────────────────────────────────────────────────────────────────

def get_all_messages() -> list:
    conn = get_db()
    rows = conn.execute("SELECT * FROM messages ORDER BY created_at DESC").fetchall()
    return [ContactMessage.from_row(r) for r in rows]


def get_message_by_id(msg_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
    return ContactMessage.from_row(row) if row else None


def add_message(name, body, platform=None, username=None, subject=None):
    conn = get_db()
    conn.execute(
        "INSERT INTO messages (name,body,platform,username,subject) VALUES (?,?,?,?,?)",
        (name, body, platform or "", username or "", subject or ""),
    )
    conn.commit()


def mark_message_read(msg_id: int) -> None:
    conn = get_db()
    conn.execute("UPDATE messages SET is_read=1 WHERE id=?", (msg_id,))
    conn.commit()


def mark_all_messages_read() -> None:
    conn = get_db()
    conn.execute("UPDATE messages SET is_read=1")
    conn.commit()


def delete_message(msg_id: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM messages WHERE id=?", (msg_id,))
    conn.commit()


def get_unread_count() -> int:
    conn = get_db()
    return conn.execute("SELECT COUNT(*) FROM messages WHERE is_read=0").fetchone()[0]

def get_replied_messages() -> list:
    """Faqat cofe sahifasidan kelgan va admin javob bergan xabarlarni qaytaradi (javoblar sahifasi uchun)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM messages WHERE reply IS NOT NULL AND reply != '' "
        "AND subject = 'cofe sahifasidan' ORDER BY replied_at DESC"
    ).fetchall()
    return [ContactMessage.from_row(r) for r in rows]


def reply_message(msg_id: int, reply: str) -> None:
    conn = get_db()
    conn.execute(
        "UPDATE messages SET reply=?, replied_at=datetime('now'), is_read=1 WHERE id=?",
        (reply, msg_id),
    )
    conn.commit()


# ── Statistika (ko'rishlar) ──────────────────────────────────────────────────

def increment_views(slug: str) -> None:
    conn = get_db()
    conn.execute("UPDATE articles SET views = COALESCE(views,0) + 1 WHERE slug=?", (slug,))
    conn.commit()


def get_top_articles(limit: int = 5) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM articles ORDER BY views DESC, date DESC LIMIT ?", (limit,)
    ).fetchall()
    return [Article.from_row(r) for r in rows]


def get_monthly_article_counts(months: int = 6) -> list:
    """Oxirgi N oy bo'yicha nechta maqola qo'shilganini qaytaradi: [(label, count), ...]"""
    conn = get_db()
    rows = conn.execute(
        "SELECT strftime('%Y-%m', created_at) AS ym, COUNT(*) AS cnt "
        "FROM articles GROUP BY ym ORDER BY ym DESC LIMIT ?", (months,)
    ).fetchall()
    return list(reversed([(r["ym"] or "—", r["cnt"]) for r in rows]))


def get_total_views() -> int:
    conn = get_db()
    row = conn.execute("SELECT COALESCE(SUM(views),0) AS s FROM articles").fetchone()
    return row["s"] or 0


# ── Feedback rate-limit (worker'lar orasida umumiy, SQLite orqali) ──────────

def is_feedback_rate_limited(ip: str, window_seconds: float, max_per_window: int) -> bool:
    """
    Faqat tekshiradi, hech narsa yozmaydi. gunicorn'ning barcha workerlari
    bitta articles.db faylini ishlatgani uchun limit ular orasida umumiy bo'ladi.
    """
    import time as _time
    now = _time.time()
    conn = get_db()
    row = conn.execute(
        "SELECT window_ends, count FROM feedback_rate_limit WHERE ip=?", (ip,)
    ).fetchone()
    if row is None or now >= row["window_ends"]:
        return False
    return row["count"] >= max_per_window


def record_feedback_attempt(ip: str, window_seconds: float) -> None:
    """Urinishni hisoblaydi; kerak bo'lsa yangi oyna ochadi."""
    import time as _time
    now = _time.time()
    conn = get_db()
    row = conn.execute(
        "SELECT window_ends, count FROM feedback_rate_limit WHERE ip=?", (ip,)
    ).fetchone()
    if row is None or now >= row["window_ends"]:
        window_ends = now + window_seconds
        conn.execute(
            "INSERT INTO feedback_rate_limit (ip, window_ends, count) VALUES (?, ?, 1) "
            "ON CONFLICT(ip) DO UPDATE SET window_ends=excluded.window_ends, count=1",
            (ip, window_ends),
        )
    else:
        conn.execute(
            "UPDATE feedback_rate_limit SET count = count + 1 WHERE ip=?", (ip,)
        )
    conn.commit()


# ── Settings (key-value, parol/SMTP kabi sozlamalar uchun) ──────────────────

def get_setting(key: str, default=None):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def get_settings_dict(keys: list[str]) -> dict:
    conn = get_db()
    qmarks = ",".join("?" * len(keys))
    rows = conn.execute(f"SELECT key, value FROM settings WHERE key IN ({qmarks})", keys).fetchall()
    return {r["key"]: r["value"] for r in rows}


# ── Admin profili ─────────────────────────────────────────────────────────────

def get_used_image_filenames() -> set:
    """Maqolalarda, profilda va tarkib (content) ichida ishlatilgan barcha fayl nomlari."""
    conn = get_db()
    used = set()
    rows = conn.execute("SELECT image, content FROM articles").fetchall()
    for r in rows:
        if r["image"]:
            used.add(r["image"])
        content = r["content"] or ""
        for m in _IMG_SRC_RE.findall(content):
            used.add(os.path.basename(m))
    profile = get_profile()
    if profile.get("avatar"):
        used.add(profile["avatar"])
    if profile.get("cover_image"):
        used.add(profile["cover_image"])
    return used


def get_profile() -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM admin_profile WHERE id=1").fetchone()
    return dict(row) if row else {}


def update_profile(display_name=None, username=None, avatar=None, cover_image=None, bio=None) -> None:
    conn = get_db()
    current = get_profile()
    conn.execute(
        "UPDATE admin_profile SET display_name=?, username=?, avatar=?, cover_image=?, bio=? WHERE id=1",
        (
            display_name if display_name is not None else current.get("display_name"),
            username if username is not None else current.get("username"),
            avatar if avatar is not None else current.get("avatar"),
            cover_image if cover_image is not None else current.get("cover_image"),
            bio if bio is not None else current.get("bio"),
        ),
    )
    conn.commit()


# ── Xabar teglari ─────────────────────────────────────────────────────────────

def get_all_message_tags() -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT t.*, COUNT(m.message_id) AS msg_count "
        "FROM message_tags t LEFT JOIN message_tag_map m ON m.tag_id = t.id "
        "GROUP BY t.id ORDER BY t.name COLLATE NOCASE"
    ).fetchall()
    return [dict(r) for r in rows]


def get_or_create_message_tag(name: str, slug: str) -> int:
    conn = get_db()
    row = conn.execute("SELECT id FROM message_tags WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO message_tags (name, slug) VALUES (?, ?)", (name, slug))
    conn.commit()
    return cur.lastrowid


def delete_message_tag(tag_id: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM message_tags WHERE id=?", (tag_id,))
    conn.commit()


def set_message_tags(message_id: int, tag_ids: list[int]) -> None:
    conn = get_db()
    conn.execute("DELETE FROM message_tag_map WHERE message_id=?", (message_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO message_tag_map (message_id, tag_id) VALUES (?, ?)",
        [(message_id, tid) for tid in tag_ids],
    )
    conn.commit()


def add_message_tag(message_id: int, tag_id: int) -> None:
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO message_tag_map (message_id, tag_id) VALUES (?, ?)",
        (message_id, tag_id),
    )
    conn.commit()


def remove_message_tag(message_id: int, tag_id: int) -> None:
    conn = get_db()
    conn.execute(
        "DELETE FROM message_tag_map WHERE message_id=? AND tag_id=?",
        (message_id, tag_id),
    )
    conn.commit()


def get_tags_for_message(message_id: int) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT t.* FROM message_tags t "
        "JOIN message_tag_map m ON m.tag_id = t.id "
        "WHERE m.message_id = ? ORDER BY t.name COLLATE NOCASE",
        (message_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_tags_for_all_messages() -> dict:
    """Barcha xabarlar uchun {message_id: [tag, ...]} lug'ati (N+1 so'rovlardan qochish uchun)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT m.message_id, t.* FROM message_tags t "
        "JOIN message_tag_map m ON m.tag_id = t.id"
    ).fetchall()
    result: dict = {}
    for r in rows:
        result.setdefault(r["message_id"], []).append(dict(r))
    return result


# ── Tezkor javob shablonlari ─────────────────────────────────────────────────

def get_all_reply_templates() -> list:
    conn = get_db()
    rows = conn.execute("SELECT * FROM reply_templates ORDER BY title COLLATE NOCASE").fetchall()
    return [dict(r) for r in rows]


def get_reply_template(template_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM reply_templates WHERE id=?", (template_id,)).fetchone()
    return dict(row) if row else None


def add_reply_template(title: str, body: str) -> int:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO reply_templates (title, body) VALUES (?, ?)", (title, body)
    )
    conn.commit()
    return cur.lastrowid


def delete_reply_template(template_id: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM reply_templates WHERE id=?", (template_id,))
    conn.commit()


# ── 404 statistikasi ─────────────────────────────────────────────────────────

def log_404(path: str, referrer: str = None) -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO error_logs (path, referrer) VALUES (?, ?)", (path, referrer)
    )
    conn.commit()


def get_404_stats(limit: int = 20) -> list:
    """Eng ko'p uchragan buzilgan havolalarni (path, count, last_seen) qaytaradi."""
    conn = get_db()
    rows = conn.execute(
        "SELECT path, COUNT(*) AS cnt, MAX(created_at) AS last_seen "
        "FROM error_logs GROUP BY path ORDER BY cnt DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_404_count() -> int:
    conn = get_db()
    return conn.execute("SELECT COUNT(*) FROM error_logs").fetchone()[0]


def clear_404_logs() -> None:
    conn = get_db()
    conn.execute("DELETE FROM error_logs")
    conn.commit()


# ── Rasm albomlari ────────────────────────────────────────────────────────────

def get_all_albums() -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT a.*, COUNT(im.filename) AS image_count "
        "FROM image_albums a LEFT JOIN image_meta im ON im.album_id = a.id "
        "GROUP BY a.id ORDER BY a.name COLLATE NOCASE"
    ).fetchall()
    return [dict(r) for r in rows]


def get_or_create_album(name: str, slug: str) -> int:
    conn = get_db()
    row = conn.execute("SELECT id FROM image_albums WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO image_albums (name, slug) VALUES (?, ?)", (name, slug))
    conn.commit()
    return cur.lastrowid


def delete_album(album_id: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM image_albums WHERE id=?", (album_id,))
    conn.commit()


def set_image_album(filename: str, album_id) -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO image_meta (filename, album_id) VALUES (?, ?) "
        "ON CONFLICT(filename) DO UPDATE SET album_id=excluded.album_id",
        (filename, album_id),
    )
    conn.commit()


def get_image_albums_map() -> dict:
    """Barcha rasmlar uchun {filename: album_id} lug'ati."""
    conn = get_db()
    rows = conn.execute("SELECT filename, album_id FROM image_meta").fetchall()
    return {r["filename"]: r["album_id"] for r in rows}


# ── Feedback (xatolik/fikr-mulohaza) ──────────────────────────────────────────

def add_feedback(name, description: str, file_path, page_slug) -> int:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO feedback (name, description, file_path, page_slug) VALUES (?, ?, ?, ?)",
        (name or None, description, file_path, page_slug),
    )
    conn.commit()
    return cur.lastrowid


def get_all_feedback() -> list:
    conn = get_db()
    rows = conn.execute("SELECT * FROM feedback ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_feedback_count(status: str = None) -> int:
    conn = get_db()
    if status:
        return conn.execute("SELECT COUNT(*) FROM feedback WHERE status=?", (status,)).fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]


def mark_feedback_seen(feedback_id: int) -> None:
    conn = get_db()
    conn.execute("UPDATE feedback SET status='seen' WHERE id=?", (feedback_id,))
    conn.commit()


def delete_feedback(feedback_id: int):
    """Feedback yozuvini o'chiradi va biriktirilgan fayl nomini qaytaradi (bor bo'lsa)."""
    conn = get_db()
    row = conn.execute("SELECT file_path FROM feedback WHERE id=?", (feedback_id,)).fetchone()
    conn.execute("DELETE FROM feedback WHERE id=?", (feedback_id,))
    conn.commit()
    return row["file_path"] if row else None


def get_feedback_page_settings() -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM feedback_page_settings ORDER BY page_slug"
    ).fetchall()
    return [dict(r) for r in rows]


def is_feedback_enabled(page_slug: str) -> bool:
    conn = get_db()
    row = conn.execute(
        "SELECT enabled FROM feedback_page_settings WHERE page_slug=?", (page_slug,)
    ).fetchone()
    return bool(row["enabled"]) if row else True


def set_feedback_page_enabled(page_slug: str, enabled: bool) -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO feedback_page_settings (page_slug, enabled) VALUES (?, ?) "
        "ON CONFLICT(page_slug) DO UPDATE SET enabled=excluded.enabled",
        (page_slug, 1 if enabled else 0),
    )
    conn.commit()


# ── Analitika (tashrif statistikasi) ─────────────────────────────────────────

def _classify_device(user_agent: str) -> str:
    ua = user_agent or ""
    if _BOT_UA_RE.search(ua):
        return "bot"
    if _TABLET_UA_RE.search(ua):
        return "tablet"
    if _MOBILE_UA_RE.search(ua):
        return "mobile"
    return "desktop"


def log_visit(path: str, referrer: str = None, user_agent: str = None) -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO page_visits (path, referrer, device) VALUES (?, ?, ?)",
        (path[:300], (referrer or "")[:300] or None, _classify_device(user_agent)),
    )
    conn.commit()


def get_visits_summary() -> dict:
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM page_visits").fetchone()[0]
    today = conn.execute(
        "SELECT COUNT(*) FROM page_visits WHERE date(created_at)=date('now')"
    ).fetchone()[0]
    week = conn.execute(
        "SELECT COUNT(*) FROM page_visits WHERE created_at >= datetime('now','-7 days')"
    ).fetchone()[0]
    return {"total": total, "today": today, "week": week}


def get_daily_visits(days: int = 14) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT date(created_at) AS d, COUNT(*) AS cnt FROM page_visits "
        "WHERE created_at >= datetime('now', ?) GROUP BY d ORDER BY d",
        (f"-{days} days",),
    ).fetchall()
    by_day = {r["d"]: r["cnt"] for r in rows}
    from datetime import date as _d, timedelta as _td
    today = _d.today()
    out = []
    for i in range(days - 1, -1, -1):
        d = today - _td(days=i)
        key = d.isoformat()
        out.append((key[5:], by_day.get(key, 0)))
    return out


def get_top_pages(limit: int = 10) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT path, COUNT(*) AS cnt FROM page_visits GROUP BY path ORDER BY cnt DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_referrer_stats(limit: int = 8) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT COALESCE(NULLIF(referrer,''),'to''g''ridan-to''g''ri') AS ref, COUNT(*) AS cnt "
        "FROM page_visits GROUP BY ref ORDER BY cnt DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_device_stats() -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT device, COUNT(*) AS cnt FROM page_visits GROUP BY device ORDER BY cnt DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def clear_visit_logs() -> None:
    conn = get_db()
    conn.execute("DELETE FROM page_visits")
    conn.commit()


# ── SEO markazi ───────────────────────────────────────────────────────────────

def get_seo_audit() -> list:
    """Har bir maqola uchun SEO to'liqligini tekshiradi (meta tavsif/kalit so'z bormi)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT slug, title, meta_description, meta_keywords, is_draft "
        "FROM articles ORDER BY updated_at DESC"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["has_description"] = bool(d["meta_description"])
        d["has_keywords"] = bool(d["meta_keywords"])
        out.append(d)
    return out


def update_article_meta(slug: str, meta_description: str = None, meta_keywords: str = None) -> None:
    conn = get_db()
    conn.execute(
        "UPDATE articles SET meta_description=?, meta_keywords=?, updated_at=datetime('now') WHERE slug=?",
        (meta_description or None, meta_keywords or None, slug),
    )
    conn.commit()
