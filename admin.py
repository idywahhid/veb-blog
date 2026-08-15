"""
admin.py — Admin panel Blueprint
"""
import io
import os
import shutil
import uuid
import zipfile
from functools import wraps

from flask import (Blueprint, current_app, flash, redirect,
                   render_template, request, session, url_for, jsonify,
                   send_file)
from werkzeug.utils import secure_filename
from datetime import date as dt_date, datetime

import database
import auth as auth_module
import notifications
from config import cfg

try:
    from PIL import Image, ImageOps
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "uploads")
BACKUP_FOLDER = os.path.join(os.path.dirname(__file__), "backups")
ALLOWED_EXT   = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_IMAGE_DIM  = 1920             # Rasm eni/bo'yi shu qiymatdan oshsa kichraytiriladi
JPEG_QUALITY   = 85
PER_PAGE       = 20               # Ro'yxatlar uchun sahifadagi elementlar soni

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)


def _optimize_image(filepath: str) -> None:
    """Yuklangan rasmni siqadi/kichraytiradi (mavjud bo'lsa Pillow yordamida)."""
    if not _PIL_OK:
        return
    try:
        img = Image.open(filepath)
        img = ImageOps.exif_transpose(img)  # noto'g'ri orientatsiyani tuzatish
        fmt = (img.format or "").upper()

        if img.width > MAX_IMAGE_DIM or img.height > MAX_IMAGE_DIM:
            img.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM), Image.LANCZOS)

        if fmt in ("JPEG", "JPG"):
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(filepath, "JPEG", quality=JPEG_QUALITY, optimize=True)
        elif fmt == "PNG":
            img.save(filepath, "PNG", optimize=True)
        elif fmt == "WEBP":
            img.save(filepath, "WEBP", quality=JPEG_QUALITY)
        else:
            img.save(filepath)
    except Exception:
        # Rasm ochilmasa/buzilgan bo'lsa — original faylni saqlab qolamiz
        pass


def _paginate(items: list, page: int, per_page: int = PER_PAGE):
    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    return items[start:start + per_page], page, pages, total

# Kirill (o'zbek/rus) harflarni lotinga o'girish jadvali — slug generatsiyasi uchun
_CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "i", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}


def slugify(text: str) -> str:
    """Sarlavhadan URL-uchun mos slug yasaydi (kirill harflarni lotinga o'giradi)."""
    text = text.lower().strip()
    text = "".join(_CYRILLIC_TO_LATIN.get(ch, ch) for ch in text)
    out = []
    for ch in text:
        if ch.isalnum() and ch.isascii():
            out.append(ch)
        else:
            out.append("-")
    slug = "-".join(p for p in "".join(out).split("-") if p)
    return slug[:100]  # Slug uzunligini cheklash


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated


def _get_ip() -> str:
    return request.headers.get(
        "X-Forwarded-For", request.remote_addr or "unknown"
    ).split(",")[0].strip()


def _allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


# ── Login / Logout ─────────────────────────────────────────────────────────────

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin.dashboard"))

    if request.method == "POST":
        ip       = _get_ip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # Brute-force tekshiruvi
        if current_app.is_login_locked(ip):
            flash("Juda ko'p urinish. Iltimos, bir oz kuting.", "danger")
            return render_template("admin/login.html"), 429

        # Foydalanuvchi nomi tekshiruvi
        username_ok = (username == cfg.ADMIN_USERNAME)

        # Parol tekshiruvi — hash usuli (avval DB sozlamasi, keyin .env)
        db_hash = database.get_setting("ADMIN_PASSWORD_HASH")
        effective_hash = db_hash or cfg.ADMIN_PASSWORD_HASH
        if effective_hash:
            password_ok = auth_module.verify_password(password, effective_hash)
        else:
            # Hash bo'lmasa, oddiy parol bilan solishtirish (faqat sozlash uchun)
            # ISHLAB CHIQARISH MUHITIDA BU USULNI ISHLATMANG!
            import hmac as _hmac
            password_ok = _hmac.compare_digest(password, cfg.ADMIN_PASSWORD)

        if username_ok and password_ok:
            current_app.reset_login_attempts(ip)
            csrf_tok = session.get("csrf_token")
            session.clear()
            session.permanent = True
            session["admin_logged_in"] = True
            session["admin_username"]  = username
            if csrf_tok:
                session["csrf_token"] = csrf_tok
            return redirect(url_for("admin.dashboard"))
        else:
            current_app.record_failed_login(ip)
            flash("Username yoki parol noto'g'ri.", "danger")

    return render_template("admin/login.html")


@admin_bp.post("/logout")
@login_required
def logout():
    """
    Logout — POST so'rov orqali (CSRF himoyasi bilan).
    GET orqali logout qilish CSRF hujumiga ochiq bo'ladi.
    """
    session.clear()
    return redirect(url_for("admin.login"))


# ── Dashboard ──────────────────────────────────────────────────────────────────

@admin_bp.before_request
def _auto_publish():
    database.auto_publish_scheduled()


_ACTIVE_MAP = {
    "admin.dashboard":     "dashboard",
    "admin.articles_list": "articles",
    "admin.article_new":   "articles",
    "admin.article_edit":  "articles",
    "admin.gallery":       "gallery",
    "admin.config_page":   "config",
    "admin.feedback_list": "feedback",
    "admin.analytics":     "analytics",
    "admin.seo":           "seo",
    "admin.guide":         "guide",
    "admin.profile":       "profile",
}


@admin_bp.context_processor
def _inject_sidebar_context():
    """Chap panel (_sidebar.html) uchun barcha admin sahifalarida bir xil
    active-holat va o'qilmagan xabarlar sonini avtomatik taqdim etadi."""
    try:
        new_count = database.get_feedback_count("new")
    except Exception:
        new_count = 0
    try:
        seo_missing_count = sum(1 for a in database.get_seo_audit() if not a["has_description"])
    except Exception:
        seo_missing_count = 0
    return {
        "active": _ACTIVE_MAP.get(request.endpoint, ""),
        "new_count": new_count,
        "seo_missing_count": seo_missing_count,
    }


@admin_bp.get("/")
@login_required
def dashboard():
    articles     = list(database.get_all_articles(include_drafts=True).values())
    username     = session.get("admin_username", "admin")
    profile      = database.get_profile()
    top_articles = database.get_top_articles(5)
    monthly      = database.get_monthly_article_counts(6)
    total_views  = database.get_total_views()
    new_feedback = database.get_feedback_count("new")
    return render_template(
        "admin/dashboard.html",
        articles=articles, username=username,
        profile=profile, top_articles=top_articles,
        monthly=monthly, total_views=total_views,
        new_feedback=new_feedback, active="dashboard",
    )


# ── Maqolalar ──────────────────────────────────────────────────────────────────

@admin_bp.get("/articles")
@login_required
def articles_list():
    q      = request.args.get("q", "").strip().lower()
    status = request.args.get("status", "").strip()  # "draft" | "published" | ""

    articles = list(database.get_all_articles(include_drafts=True).values())

    if q:
        articles = [a for a in articles if q in a.title.lower() or q in (a.content or "").lower()]
    if status == "draft":
        articles = [a for a in articles if a.is_draft]
    elif status == "published":
        articles = [a for a in articles if not a.is_draft]

    page = request.args.get("page", "1")
    page = int(page) if page.isdigit() else 1
    page_items, page, total_pages, total = _paginate(articles, page)

    return render_template("admin/articles_list.html", articles=page_items,
                            q=q, status=status,
                            page=page, total_pages=total_pages, total=total,
                            active="articles")


@admin_bp.post("/articles/bulk")
@login_required
def articles_bulk():
    slugs  = request.form.getlist("slugs")
    action = request.form.get("action", "")
    if not slugs:
        flash("Hech qanday maqola tanlanmadi.", "danger")
    elif action == "delete":
        for s in slugs:
            a = database.get_article_by_slug(s)
            if a and a.image:
                fpath = os.path.join(UPLOAD_FOLDER, a.image)
                if os.path.isfile(fpath):
                    os.remove(fpath)
        database.delete_articles(slugs)
        flash(f"{len(slugs)} ta maqola o'chirildi.", "info")
    elif action == "publish":
        database.set_articles_draft_status(slugs, 0)
        flash(f"{len(slugs)} ta maqola nashr qilindi.", "success")
    elif action == "draft":
        database.set_articles_draft_status(slugs, 1)
        flash(f"{len(slugs)} ta maqola qoralamaga o'tkazildi.", "info")
    else:
        flash("Noma'lum amal.", "danger")
    return redirect(url_for("admin.articles_list"))


@admin_bp.route("/articles/new", methods=["GET", "POST"])
@login_required
def article_new():
    if request.method == "POST":
        return _save_article(None)
    autosave = database.get_autosave("new")
    return render_template("admin/article_editor.html", article=None,
                            autosave=autosave)


@admin_bp.route("/articles/<slug>/edit", methods=["GET", "POST"])
@login_required
def article_edit(slug: str):
    article = database.get_article_by_slug(slug)
    if not article:
        flash("Maqola topilmadi.", "danger")
        return redirect(url_for("admin.articles_list"))
    if request.method == "POST":
        return _save_article(slug)
    autosave = database.get_autosave(slug)
    return render_template("admin/article_editor.html", article=article,
                            autosave=autosave)


@admin_bp.route("/articles/<slug>/save", methods=["POST"])
@login_required
def article_save(slug: str):
    return _save_article(slug)


def _save_article(slug):
    title    = request.form.get("title", "").strip()
    content  = request.form.get("content", "").strip()
    author   = (request.form.get("author", cfg.ADMIN_USERNAME).strip()
                or cfg.ADMIN_USERNAME)
    date_val = request.form.get("date", str(dt_date.today()))
    location = request.form.get("location", "").strip() or None
    img_desc = request.form.get("img_desc", "").strip() or None
    is_draft = 1 if request.form.get("is_draft") else 0
    meta_description = request.form.get("meta_description", "").strip()[:300] or None
    meta_keywords     = request.form.get("meta_keywords", "").strip()[:300] or None
    publish_at        = request.form.get("publish_at", "").strip() or None
    if publish_at:
        # Agar kelajakdagi vaqt ko'rsatilgan bo'lsa, avtomatik qoralama qilib qo'yamiz
        is_draft = 1

    # Uzunlik tekshiruvlari
    if not title:
        flash("Sarlavha majburiy.", "danger")
        article = database.get_article_by_slug(slug) if slug else None
        return render_template("admin/article_editor.html", article=article)
    if len(title) > 500:
        flash("Sarlavha 500 ta belgidan oshmasligi kerak.", "danger")
        article = database.get_article_by_slug(slug) if slug else None
        return render_template("admin/article_editor.html", article=article)

    # Slug yaratish
    new_slug = slug
    if not new_slug:
        new_slug = slugify(title) or str(uuid.uuid4())[:8]
        existing = database.get_article_by_slug(new_slug)
        if existing:
            new_slug = f"{new_slug}-{str(uuid.uuid4())[:4]}"

    # Rasm yuklash
    image = None
    if slug:
        old = database.get_article_by_slug(slug)
        image = old.image if old else None

    file = request.files.get("image")
    if file and file.filename:
        if not _allowed(file.filename):
            flash("Ruxsat etilmagan fayl formati.", "danger")
            article = database.get_article_by_slug(slug) if slug else None
            return render_template("admin/article_editor.html", article=article)

        # Fayl hajmini tekshirish
        file.seek(0, 2)  # Faylning oxiriga o'tish
        file_size = file.tell()
        file.seek(0)
        if file_size > MAX_IMAGE_SIZE:
            flash("Rasm hajmi 5 MB dan oshmasligi kerak.", "danger")
            article = database.get_article_by_slug(slug) if slug else None
            return render_template("admin/article_editor.html", article=article)

        ext      = secure_filename(file.filename).rsplit(".", 1)[1].lower()
        filename = f"{new_slug}-{uuid.uuid4().hex[:6]}.{ext}"
        fpath    = os.path.join(UPLOAD_FOLDER, filename)
        file.save(fpath)
        _optimize_image(fpath)
        image = filename

    if slug:
        database.update_article(slug, title, content, author, date_val,
                                image, img_desc, location, is_draft,
                                meta_description, meta_keywords, publish_at)
        saved_article = database.get_article_by_slug(new_slug)
        flash("Maqola yangilandi!", "success")
    else:
        new_id = database.add_article(new_slug, title, content, author, date_val,
                             image, img_desc, location, is_draft,
                             meta_description, meta_keywords, publish_at)
        saved_article = database.get_article_by_slug(new_slug)
        flash("Maqola qo'shildi!", "success")
        database.delete_autosave("new")

    if slug:
        database.delete_autosave(slug)

    return redirect(url_for("admin.dashboard"))


@admin_bp.post("/articles/<slug>/duplicate")
@login_required
def article_duplicate(slug: str):
    """Mavjud maqoladan nusxa (klon) yaratadi — rasm faylga ishora qilinadi, nusxalanmaydi."""
    article = database.get_article_by_slug(slug)
    if not article:
        flash("Maqola topilmadi.", "danger")
        return redirect(url_for("admin.articles_list"))

    new_title = f"{article.title} (nusxa)"
    new_slug = slugify(new_title) or str(uuid.uuid4())[:8]
    while database.get_article_by_slug(new_slug):
        new_slug = f"{new_slug}-{uuid.uuid4().hex[:4]}"

    new_id = database.add_article(
        new_slug, new_title, article.content, article.author,
        str(dt_date.today()), article.image, article.img_desc, article.location,
        is_draft=1, meta_description=article.meta_description,
        meta_keywords=article.meta_keywords, publish_at=None,
    )
    flash("Maqoladan nusxa yaratildi (qoralama sifatida).", "success")
    return redirect(url_for("admin.article_edit", slug=new_slug))


@admin_bp.route("/articles/preview", methods=["POST"])
@login_required
def article_preview():
    """Saqlamasdan turib maqolani ommaviy shablon ko'rinishida ko'rsatadi."""
    class _PreviewArticle:
        pass

    p = _PreviewArticle()
    p.title    = request.form.get("title", "").strip() or "(sarlavhasiz)"
    p.content  = request.form.get("content", "")
    p.author   = request.form.get("author", "").strip() or cfg.ADMIN_USERNAME
    p.date     = request.form.get("date", str(dt_date.today()))
    p.location = request.form.get("location", "").strip() or None
    p.img_desc = request.form.get("img_desc", "").strip() or None
    p.image    = request.form.get("existing_image", "").strip() or None
    p.views    = 0
    p.slug     = "preview"
    p.meta_description = None
    p.meta_keywords = None

    return render_template("article.html", article=p, prev_article=None,
                            next_article=None, is_preview=True)


@admin_bp.post("/articles/<slug>/delete")
@login_required
def article_delete(slug: str):
    article = database.get_article_by_slug(slug)
    if article and article.image:
        fpath = os.path.join(UPLOAD_FOLDER, article.image)
        if os.path.isfile(fpath):
            os.remove(fpath)
    database.delete_article(slug)
    database.delete_autosave(slug)
    flash("Maqola o'chirildi.", "info")
    return redirect(url_for("admin.dashboard"))


# ── Rasm yuklash (Quill uchun) ─────────────────────────────────────────────────

@admin_bp.post("/upload-image")
@login_required
def upload_image():
    file = request.files.get("image")
    if not file or not file.filename:
        return jsonify({"error": "Fayl tanlanmadi"}), 400
    if not _allowed(file.filename):
        return jsonify({"error": "Ruxsat etilmagan format"}), 400

    # Fayl hajmini tekshirish
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)
    if file_size > MAX_IMAGE_SIZE:
        return jsonify({"error": "Fayl hajmi 5 MB dan oshmasligi kerak"}), 413

    ext      = secure_filename(file.filename).rsplit(".", 1)[1].lower()
    filename = f"img-{uuid.uuid4().hex[:10]}.{ext}"
    fpath    = os.path.join(UPLOAD_FOLDER, filename)
    file.save(fpath)
    _optimize_image(fpath)
    url = url_for("static", filename=f"uploads/{filename}")
    return jsonify({"ok": True, "url": url})


# ── Qoralamani avtomatik saqlash (autosave) ─────────────────────────────────

@admin_bp.post("/articles/autosave")
@login_required
def article_autosave():
    slug_key = request.form.get("slug_key", "new").strip() or "new"
    title    = request.form.get("title", "")
    content  = request.form.get("content", "")
    database.save_autosave(slug_key, title, content)
    return jsonify({"ok": True, "saved_at": datetime.now().strftime("%H:%M:%S")})


# ── Xabarlar ───────────────────────────────────────────────────────────────────

# ── Rasm galereyasi ──────────────────────────────────────────────────────────

@admin_bp.get("/gallery")
@login_required
def gallery():
    q = request.args.get("q", "").strip().lower()
    album_filter = request.args.get("album", "").strip()  # album id yoki "none"
    used = database.get_used_image_filenames()
    albums = database.get_all_albums()
    album_map = database.get_image_albums_map()
    album_by_id = {str(a["id"]): a for a in albums}

    files = []
    for fname in sorted(os.listdir(UPLOAD_FOLDER), reverse=True):
        if q and q not in fname.lower():
            continue
        fpath = os.path.join(UPLOAD_FOLDER, fname)
        if os.path.isfile(fpath) and _allowed(fname):
            album_id = album_map.get(fname)
            if album_filter == "none" and album_id:
                continue
            if album_filter and album_filter != "none" and str(album_id) != album_filter:
                continue
            files.append({
                "name": fname,
                "url": url_for("static", filename=f"uploads/{fname}"),
                "size_kb": round(os.path.getsize(fpath) / 1024, 1),
                "in_use": fname in used,
                "album": album_by_id.get(str(album_id)) if album_id else None,
            })

    page = request.args.get("page", "1")
    page = int(page) if page.isdigit() else 1
    page_items, page, total_pages, total = _paginate(files, page, per_page=24)

    orphan_count = sum(1 for f in files if not f["in_use"])
    return render_template("admin/gallery.html", files=page_items, q=q,
                            page=page, total_pages=total_pages, total=total,
                            orphan_count=orphan_count, albums=albums,
                            selected_album=album_filter, active="gallery")


@admin_bp.post("/gallery/albums/add")
@login_required
def album_add():
    name = request.form.get("name", "").strip()
    if name:
        database.get_or_create_album(name, slugify(name))
        flash("Albom yaratildi.", "success")
    return redirect(url_for("admin.gallery"))


@admin_bp.post("/gallery/albums/<int:album_id>/delete")
@login_required
def album_delete(album_id: int):
    database.delete_album(album_id)
    flash("Albom o'chirildi (rasmlar saqlanib qoladi).", "info")
    return redirect(url_for("admin.gallery"))


@admin_bp.post("/gallery/<path:filename>/album")
@login_required
def gallery_set_album(filename: str):
    safe = secure_filename(filename)
    album_id = request.form.get("album_id", "").strip()
    database.set_image_album(safe, int(album_id) if album_id.isdigit() else None)
    flash("Rasm albomi yangilandi.", "success")
    return redirect(url_for("admin.gallery"))


@admin_bp.post("/gallery/<path:filename>/delete")
@login_required
def gallery_delete(filename: str):
    safe = secure_filename(filename)
    fpath = os.path.join(UPLOAD_FOLDER, safe)
    used = database.get_used_image_filenames()
    if safe in used and not request.form.get("force"):
        flash("Bu rasm hozir ishlatilmoqda — baribir o'chirish uchun qayta urinib ko'ring.", "danger")
        return redirect(url_for("admin.gallery"))
    if os.path.isfile(fpath):
        os.remove(fpath)
        flash("Rasm o'chirildi.", "info")
    else:
        flash("Rasm topilmadi.", "danger")
    return redirect(url_for("admin.gallery"))


@admin_bp.post("/gallery/cleanup")
@login_required
def gallery_cleanup():
    used = database.get_used_image_filenames()
    removed = 0
    for fname in os.listdir(UPLOAD_FOLDER):
        fpath = os.path.join(UPLOAD_FOLDER, fname)
        if os.path.isfile(fpath) and _allowed(fname) and fname not in used:
            os.remove(fpath)
            removed += 1
    flash(f"{removed} ta ishlatilmayotgan rasm o'chirildi.", "success")
    return redirect(url_for("admin.gallery"))


# ── Zaxira nusxa (backup) ────────────────────────────────────────────────────

@admin_bp.post("/backup/create")
@login_required
def backup_create():
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_name = f"backup-{ts}.zip"
    backup_path = os.path.join(BACKUP_FOLDER, backup_name)

    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
        db_path = cfg.DB_PATH
        if os.path.isfile(db_path):
            zf.write(db_path, arcname=os.path.basename(db_path))
        for fname in os.listdir(UPLOAD_FOLDER):
            fpath = os.path.join(UPLOAD_FOLDER, fname)
            if os.path.isfile(fpath):
                zf.write(fpath, arcname=os.path.join("uploads", fname))

    flash("Zaxira nusxa yaratildi.", "success")
    return redirect(url_for("admin.config_page") + "#backup")


@admin_bp.get("/backup/list")
@login_required
def backup_list_json():
    backups = _list_backups()
    return jsonify(backups)


def _list_backups():
    backups = []
    for fname in sorted(os.listdir(BACKUP_FOLDER), reverse=True):
        fpath = os.path.join(BACKUP_FOLDER, fname)
        if os.path.isfile(fpath) and fname.endswith(".zip"):
            backups.append({
                "name": fname,
                "size_kb": round(os.path.getsize(fpath) / 1024, 1),
                "created": datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%Y-%m-%d %H:%M"),
            })
    return backups


@admin_bp.get("/backup/<path:filename>/download")
@login_required
def backup_download(filename: str):
    safe = secure_filename(filename)
    fpath = os.path.join(BACKUP_FOLDER, safe)
    if not os.path.isfile(fpath):
        flash("Zaxira fayli topilmadi.", "danger")
        return redirect(url_for("admin.config_page") + "#backup")
    return send_file(fpath, as_attachment=True, download_name=safe)


@admin_bp.post("/backup/<path:filename>/delete")
@login_required
def backup_delete(filename: str):
    safe = secure_filename(filename)
    fpath = os.path.join(BACKUP_FOLDER, safe)
    if os.path.isfile(fpath):
        os.remove(fpath)
        flash("Zaxira o'chirildi.", "info")
    return redirect(url_for("admin.config_page") + "#backup")


@admin_bp.post("/backup/<path:filename>/restore")
@login_required
def backup_restore(filename: str):
    safe = secure_filename(filename)
    fpath = os.path.join(BACKUP_FOLDER, safe)
    if not os.path.isfile(fpath):
        flash("Zaxira fayli topilmadi.", "danger")
        return redirect(url_for("admin.config_page") + "#backup")

    # Tiklashdan oldin joriy holatni avtomatik zaxiralab qo'yamiz
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    pre_restore_path = os.path.join(BACKUP_FOLDER, f"pre-restore-{ts}.zip")
    with zipfile.ZipFile(pre_restore_path, "w", zipfile.ZIP_DEFLATED) as zf:
        db_path = cfg.DB_PATH
        if os.path.isfile(db_path):
            zf.write(db_path, arcname=os.path.basename(db_path))
        for fname in os.listdir(UPLOAD_FOLDER):
            fp = os.path.join(UPLOAD_FOLDER, fname)
            if os.path.isfile(fp):
                zf.write(fp, arcname=os.path.join("uploads", fname))

    try:
        with zipfile.ZipFile(fpath, "r") as zf:
            for member in zf.namelist():
                # Path traversal himoyasi
                if member.startswith("/") or ".." in member:
                    continue
                if member.startswith("uploads/"):
                    target = os.path.join(UPLOAD_FOLDER, secure_filename(os.path.basename(member)))
                elif member == os.path.basename(cfg.DB_PATH):
                    target = cfg.DB_PATH
                else:
                    continue
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        flash("Zaxiradan muvaffaqiyatli tiklandi. Joriy holat ham avtomatik zaxiralandi.", "success")
    except Exception as e:
        flash(f"Tiklashda xatolik: {e}", "danger")

    return redirect(url_for("admin.config_page") + "#backup")


# ── Konfiguratsiya (profil / xavfsizlik / email / teglar / backup) ──────────

@admin_bp.get("/feedback")
@login_required
def feedback_list():
    items = database.get_all_feedback()
    for it in items:
        if it["file_path"]:
            it["file_url"] = url_for("static", filename=f"uploads/feedback/{it['file_path']}")
    page_settings = database.get_feedback_page_settings()
    new_count = database.get_feedback_count("new")
    return render_template(
        "admin/feedback.html",
        items=items, page_settings=page_settings, new_count=new_count,
        username=session.get("admin_username", "admin"), active="feedback",
    )


@admin_bp.post("/feedback/<int:feedback_id>/seen")
@login_required
def feedback_mark_seen(feedback_id: int):
    database.mark_feedback_seen(feedback_id)
    return redirect(url_for("admin.feedback_list"))


@admin_bp.post("/feedback/<int:feedback_id>/delete")
@login_required
def feedback_delete(feedback_id: int):
    fname = database.delete_feedback(feedback_id)
    if fname:
        fpath = os.path.join(os.path.dirname(__file__), "static", "uploads", "feedback", fname)
        if os.path.isfile(fpath):
            os.remove(fpath)
    flash("Feedback o'chirildi.", "info")
    return redirect(url_for("admin.feedback_list"))


@admin_bp.post("/feedback/pages/<page_slug>/toggle")
@login_required
def feedback_page_toggle(page_slug: str):
    enabled = request.form.get("enabled") == "1"
    database.set_feedback_page_enabled(page_slug, enabled)
    return redirect(url_for("admin.feedback_list"))


@admin_bp.get("/profile")
@login_required
def profile():
    profile = database.get_profile()
    return render_template(
        "admin/profile.html",
        profile=profile,
        username=session.get("admin_username", "admin"),
    )


@admin_bp.get("/config")
@login_required
def config_page():
    profile  = database.get_profile()
    backups  = _list_backups()
    smtp     = notifications.get_smtp_settings()
    error_stats = database.get_404_stats(20)
    reply_templates = database.get_all_reply_templates()
    all_msg_tags = database.get_all_message_tags()
    return render_template(
        "admin/config.html",
        profile=profile, backups=backups, smtp=smtp,
        username=session.get("admin_username", "admin"),
        error_stats=error_stats, reply_templates=reply_templates,
        all_msg_tags=all_msg_tags, active="config",
    )


@admin_bp.post("/errors/clear")
@login_required
def errors_clear():
    database.clear_404_logs()
    flash("404 statistikasi tozalandi.", "info")
    return redirect(url_for("admin.config_page") + "#errors")


# ── Maqolani PDF qilib yuklab olish ──────────────────────────────────────────

@admin_bp.get("/articles/<slug>/pdf")
@login_required
def article_pdf(slug: str):
    import re as _re
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    article = database.get_article_by_slug(slug)
    if not article:
        flash("Maqola topilmadi.", "danger")
        return redirect(url_for("admin.articles_list"))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm,
                             leftMargin=2*cm, rightMargin=2*cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ArticleTitle", parent=styles["Title"], fontSize=20, spaceAfter=12)
    meta_style  = ParagraphStyle("ArticleMeta", parent=styles["Normal"], textColor="#666666", spaceAfter=16)
    body_style  = ParagraphStyle("ArticleBody", parent=styles["Normal"], fontSize=11, leading=16, spaceAfter=10)

    # Oddiy HTML teglarni reportlab qo'llab-quvvatlaydigan formatga soddalashtirish
    raw = article.content or ""
    raw = _re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", raw)
    raw = _re.sub(r"(?i)</p\s*>", "<br/><br/>", raw)
    raw = _re.sub(r"(?i)<br\s*/?>", "<br/>", raw)
    for tag in ("h1", "h2", "h3", "h4", "ul", "ol", "li", "div", "span", "img", "a"):
        raw = _re.sub(rf"(?i)</?{tag}[^>]*>", "", raw)
    raw = _re.sub(r"(?i)<(?!/?(b|i|u|br)\b)[^>]+>", "", raw)
    # reportlab mini-XML uchun maxsus belgilarni to'g'ri kodlash (ruxsat etilgan teglardan tashqari)
    raw = _re.sub(r"&(?!amp;|lt;|gt;|#)", "&amp;", raw)

    elements = [
        Paragraph(article.title, title_style),
        Paragraph(f"Muallif: {article.author} &nbsp;|&nbsp; Sana: {article.date}", meta_style),
        Spacer(1, 6),
    ]
    for para in raw.split("<br/><br/>"):
        para = para.strip()
        if para:
            try:
                elements.append(Paragraph(para, body_style))
                elements.append(Spacer(1, 4))
            except Exception:
                elements.append(Paragraph(_re.sub(r"<[^>]+>", "", para), body_style))
                elements.append(Spacer(1, 4))

    doc.build(elements)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"{slug}.pdf", mimetype="application/pdf")


@admin_bp.post("/config/profile")
@login_required
def config_profile_update():
    display_name = request.form.get("display_name", "").strip() or "Admin"
    bio          = request.form.get("bio", "").strip() or None

    avatar = None
    file = request.files.get("avatar")
    if file and file.filename:
        if _allowed(file.filename):
            ext = secure_filename(file.filename).rsplit(".", 1)[1].lower()
            avatar = f"avatar-{uuid.uuid4().hex[:8]}.{ext}"
            file.save(os.path.join(UPLOAD_FOLDER, avatar))
        else:
            flash("Avatar uchun ruxsat etilmagan fayl formati.", "danger")

    cover = None
    cover_file = request.files.get("cover_image")
    if cover_file and cover_file.filename:
        if _allowed(cover_file.filename):
            ext = secure_filename(cover_file.filename).rsplit(".", 1)[1].lower()
            cover = f"cover-{uuid.uuid4().hex[:8]}.{ext}"
            cover_file.save(os.path.join(UPLOAD_FOLDER, cover))
        else:
            flash("Orqa fon uchun ruxsat etilmagan fayl formati.", "danger")

    database.update_profile(display_name=display_name, avatar=avatar, cover_image=cover, bio=bio)
    flash("Profil yangilandi.", "success")
    return redirect(url_for("admin.profile"))


@admin_bp.post("/config/password")
@login_required
def config_password_update():
    current_pw = request.form.get("current_password", "")
    new_pw     = request.form.get("new_password", "")
    confirm_pw = request.form.get("confirm_password", "")

    db_hash = database.get_setting("ADMIN_PASSWORD_HASH")
    effective_hash = db_hash or cfg.ADMIN_PASSWORD_HASH
    current_ok = (
        auth_module.verify_password(current_pw, effective_hash)
        if effective_hash else current_pw == cfg.ADMIN_PASSWORD
    )

    if not current_ok:
        flash("Joriy parol noto'g'ri.", "danger")
    elif len(new_pw) < 8:
        flash("Yangi parol kamida 8 ta belgidan iborat bo'lishi kerak.", "danger")
    elif new_pw != confirm_pw:
        flash("Yangi parollar mos kelmadi.", "danger")
    else:
        database.set_setting("ADMIN_PASSWORD_HASH", auth_module.hash_password(new_pw))
        flash("Parol muvaffaqiyatli yangilandi.", "success")

    return redirect(url_for("admin.config_page") + "#security")


@admin_bp.post("/config/email")
@login_required
def config_email_update():
    smtp_email    = request.form.get("smtp_email", "").strip()
    smtp_password = request.form.get("smtp_app_password", "").strip()
    enabled       = "1" if request.form.get("smtp_enabled") else "0"

    database.set_setting("SMTP_EMAIL", smtp_email)
    if smtp_password:
        database.set_setting("SMTP_APP_PASSWORD", smtp_password)
    database.set_setting("SMTP_NOTIFY_ENABLED", enabled)

    flash("Email sozlamalari saqlandi.", "success")
    return redirect(url_for("admin.config_page") + "#email")


@admin_bp.post("/config/email/test")
@login_required
def config_email_test():
    ok, err = notifications.send_email(
        "Blog: test xabari",
        "Bu sizning Gmail sozlamalaringiz to'g'ri ishlayotganini tekshirish uchun test xabari.",
    )
    if ok:
        flash("Test xabari muvaffaqiyatli yuborildi.", "success")
    else:
        flash(f"Xatolik: {err}", "danger")
    return redirect(url_for("admin.config_page") + "#email")


# ── Analitika ─────────────────────────────────────────────────────────────────

@admin_bp.get("/analytics")
@login_required
def analytics():
    summary   = database.get_visits_summary()
    daily     = database.get_daily_visits(14)
    top_pages = database.get_top_pages(10)
    referrers = database.get_referrer_stats(8)
    devices   = database.get_device_stats()
    total_views = database.get_total_views()
    top_articles = database.get_top_articles(8)
    return render_template(
        "admin/analytics.html",
        summary=summary, daily=daily, top_pages=top_pages,
        referrers=referrers, devices=devices, total_views=total_views,
        top_articles=top_articles,
        username=session.get("admin_username", "admin"),
    )


@admin_bp.post("/analytics/clear")
@login_required
def analytics_clear():
    database.clear_visit_logs()
    flash("Tashrif statistikasi tozalandi.", "info")
    return redirect(url_for("admin.analytics"))


# ── SEO markazi ────────────────────────────────────────────────────────────────

@admin_bp.get("/seo")
@login_required
def seo():
    audit = database.get_seo_audit()
    missing_count = sum(1 for a in audit if not a["has_description"])
    site_settings = database.get_settings_dict([
        "SITE_META_DESCRIPTION", "SITE_META_KEYWORDS", "SITE_OG_IMAGE",
    ])
    robots_txt = database.get_setting("ROBOTS_TXT") or (
        f"User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: {request.url_root.rstrip('/')}sitemap.xml\n"
    )
    return render_template(
        "admin/seo.html",
        audit=audit, missing_count=missing_count,
        site_settings=site_settings, robots_txt=robots_txt,
        username=session.get("admin_username", "admin"),
    )


@admin_bp.post("/seo/site")
@login_required
def seo_site_update():
    database.set_setting("SITE_META_DESCRIPTION", request.form.get("site_meta_description", "").strip()[:300])
    database.set_setting("SITE_META_KEYWORDS", request.form.get("site_meta_keywords", "").strip()[:300])
    database.set_setting("SITE_OG_IMAGE", request.form.get("site_og_image", "").strip()[:300])
    flash("Sayt SEO sozlamalari saqlandi.", "success")
    return redirect(url_for("admin.seo") + "#site")


@admin_bp.post("/seo/robots")
@login_required
def seo_robots_update():
    database.set_setting("ROBOTS_TXT", request.form.get("robots_txt", "").strip())
    flash("robots.txt yangilandi.", "success")
    return redirect(url_for("admin.seo") + "#robots")


@admin_bp.post("/seo/article/<slug>")
@login_required
def seo_article_update(slug: str):
    meta_description = request.form.get("meta_description", "").strip()[:300] or None
    meta_keywords = request.form.get("meta_keywords", "").strip()[:300] or None
    database.update_article_meta(slug, meta_description, meta_keywords)
    flash(f"\"{slug}\" uchun SEO ma'lumotlari yangilandi.", "success")
    return redirect(url_for("admin.seo") + "#articles")


# ── Qo'llanma ──────────────────────────────────────────────────────────────────

@admin_bp.get("/guide")
@login_required
def guide():
    return render_template(
        "admin/guide.html",
        username=session.get("admin_username", "admin"), active="guide",
    )
