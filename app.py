"""
app.py — Blog asosiy fayli
"""
import hmac
import os
import random
import secrets
import time
import uuid
from collections import defaultdict
from datetime import timedelta

from flask import (Flask, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)

import database
from admin import admin_bp
from config import cfg
import notifications

app = Flask(__name__)
app.secret_key = cfg.SECRET_KEY
app.permanent_session_lifetime = timedelta(seconds=cfg.PERMANENT_SESSION_LIFETIME)
app.config["SESSION_COOKIE_HTTPONLY"] = cfg.SESSION_COOKIE_HTTPONLY
app.config["SESSION_COOKIE_SAMESITE"] = cfg.SESSION_COOKIE_SAMESITE
app.config["SESSION_COOKIE_SECURE"]   = cfg.SESSION_COOKIE_SECURE
app.config["MAX_CONTENT_LENGTH"]      = cfg.MAX_CONTENT_LENGTH  # 5 MB yuklash limiti

app.register_blueprint(admin_bp)
database.init_db()


@app.teardown_appcontext
def teardown_db(exception=None):
    database.close_db(exception)


# ── CSRF himoya ────────────────────────────────────────────────────────────────

def generate_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = generate_csrf_token


@app.before_request
def check_csrf():
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        token = (
            request.form.get("csrf_token")
            or request.headers.get("X-CSRF-Token")
        )
        sess_token = session.get("csrf_token")
        if not token or not sess_token or not hmac.compare_digest(token, sess_token):
            abort(403)


# ── Brute-force himoya (in-memory, single-process uchun) ──────────────────────
# Ishlab chiqarish muhitida Redis yoki boshqa tashqi storage ishlatish tavsiya etiladi.

_login_attempts: dict[str, list[float]] = defaultdict(list)


def _get_client_ip() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()


def is_login_locked(ip: str) -> bool:
    now = time.time()
    window = cfg.LOGIN_LOCKOUT_SECONDS
    attempts = [t for t in _login_attempts[ip] if now - t < window]
    _login_attempts[ip] = attempts
    return len(attempts) >= cfg.MAX_LOGIN_ATTEMPTS


def record_failed_login(ip: str) -> None:
    _login_attempts[ip].append(time.time())


def reset_login_attempts(ip: str) -> None:
    _login_attempts.pop(ip, None)


# Admin blueprint ga expose qilish uchun
app.is_login_locked    = is_login_locked
app.record_failed_login = record_failed_login
app.reset_login_attempts = reset_login_attempts


# ── Umumiy spam himoyasi: feedback + kontakt + cofe (IP bo'yicha, in-memory) ───
# Uchalasi ham bitta umumiy limitga ega: 25 daqiqada 2 ta so'rov.
# Foydalanuvchiga har doim "25 daqiqa" ko'rsatiladi, lekin haqiqiy oyna
# 20-25 daqiqa orasidan tasodifiy tanlanadi — shunda limit qachon tugashini
# aniq bilib bo'lmaydi va avtomatlashtirish qiyinlashadi.

_feedback_windows: dict[str, float] = {}

RATE_LIMIT_MESSAGE = f"Juda ko'p urinish. {cfg.SHARED_WINDOW_DISPLAY_MINUTES} daqiqadan so'ng qayta urinib ko'ring."


def _get_feedback_window(ip: str) -> float:
    if ip not in _feedback_windows:
        minutes = random.choice(cfg.SHARED_WINDOW_MINUTES_CHOICES)
        _feedback_windows[ip] = minutes * 60
    return _feedback_windows[ip]


def is_feedback_rate_limited(ip: str) -> bool:
    # DB orqali tekshiriladi — gunicorn workerlari orasida umumiy.
    window = _get_feedback_window(ip)
    return database.is_feedback_rate_limited(ip, window, cfg.MAX_FEEDBACK_PER_WINDOW)


def record_feedback_attempt(ip: str) -> None:
    window = _get_feedback_window(ip)
    database.record_feedback_attempt(ip, window)


def apply_forced_slowdown() -> None:
    """Har bir yuborishda majburiy kechikish — botlarni sekinlashtirish uchun."""
    time.sleep(random.uniform(cfg.FORCED_SLOWDOWN_MIN_SECONDS, cfg.FORCED_SLOWDOWN_MAX_SECONDS))


# ── Ommaviy routelar ───────────────────────────────────────────────────────────

@app.before_request
def _auto_publish_scheduled():
    database.auto_publish_scheduled()


_SKIP_VISIT_PREFIXES = ("/admin", "/static", "/sitemap.xml", "/robots.txt", "/feedback/submit")


@app.before_request
def _track_visit():
    """Analitika bo'limi uchun sahifa tashriflarini jurnalga yozadi (admin/statik yo'llar bundan mustasno)."""
    if request.method != "GET":
        return
    path = request.path
    if any(path.startswith(p) for p in _SKIP_VISIT_PREFIXES):
        return
    try:
        database.log_visit(path, request.referrer, request.headers.get("User-Agent", ""))
    except Exception:
        pass


_FEEDBACK_UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "uploads", "feedback")
_FEEDBACK_ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp", "pdf"}
os.makedirs(_FEEDBACK_UPLOAD_FOLDER, exist_ok=True)

_PAGE_SLUG_BY_ENDPOINT = {
    "home": "home", "blog": "blog", "show_article": "article",
    "about": "about", "kontakt": "kontakt", "javoblar": "javoblar", "cofe": "cofe",
}


@app.context_processor
def inject_feedback_context():
    page_slug = _PAGE_SLUG_BY_ENDPOINT.get(request.endpoint)
    enabled = database.is_feedback_enabled(page_slug) if page_slug else False
    return {"feedback_enabled": enabled, "feedback_page_slug": page_slug or ""}


@app.post("/feedback/submit")
def feedback_submit():
    name        = request.form.get("name", "").strip()[:120]
    description = request.form.get("description", "").strip()
    page_slug   = request.form.get("page_slug", "").strip()[:40]
    ip          = _get_client_ip()

    # Honeypot: bot to'ldirsa, jim javob qaytariladi
    if request.form.get("website", "").strip():
        return jsonify({"ok": True})

    apply_forced_slowdown()

    # IP bo'yicha umumiy spam himoyasi (feedback + kontakt + cofe uchun bitta)
    if is_feedback_rate_limited(ip):
        return jsonify({"ok": False, "error": RATE_LIMIT_MESSAGE}), 429

    if len(description) < 10 or len(description) > 999:
        return jsonify({"ok": False, "error": "Tavsif 10-999 belgi orasida bo'lishi kerak."}), 400

    record_feedback_attempt(ip)

    file_path = None
    f = request.files.get("attachment")
    if f and f.filename:
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in _FEEDBACK_ALLOWED_EXT:
            return jsonify({"ok": False, "error": "Ruxsat etilmagan fayl formati."}), 400
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(0)
        if size > 5 * 1024 * 1024:
            return jsonify({"ok": False, "error": "Fayl hajmi 5MB dan oshmasligi kerak."}), 400
        fname = f"{uuid.uuid4().hex}.{ext}"
        f.save(os.path.join(_FEEDBACK_UPLOAD_FOLDER, fname))
        file_path = fname

    database.add_feedback(name or None, description, file_path, page_slug or None)
    return jsonify({"ok": True})


@app.get("/")
def home():
    articles = list(database.get_all_articles().values())[:5]
    return render_template(
        "index.html",
        articles=articles,
        contact_telegram=cfg.CONTACT_TELEGRAM,
        contact_github=cfg.CONTACT_GITHUB,
        contact_email=cfg.CONTACT_EMAIL,
        telegram_channel=cfg.TELEGRAM_CHANNEL,
    )


@app.get("/blog")
def blog():
    q     = request.args.get("q", "").strip()
    year  = request.args.get("year", "").strip()
    month = request.args.get("month", "").strip()

    all_articles = database.get_all_articles()

    if q:
        q_lower = q.lower()
        all_articles = {
            s: a for s, a in all_articles.items()
            if q_lower in a.title.lower() or q_lower in a.content.lower()
        }
    if year and year.isdigit() and len(year) == 4:
        all_articles = {s: a for s, a in all_articles.items()
                        if a.date and a.date[:4] == year}
    if month and month.isdigit() and len(month) == 2:
        all_articles = {s: a for s, a in all_articles.items()
                        if a.date and a.date[5:7] == month}

    all_for_filter = database.get_all_articles()
    years  = sorted({a.date[:4] for a in all_for_filter.values() if a.date}, reverse=True)
    months = sorted({a.date[5:7] for a in all_for_filter.values() if a.date})

    return render_template(
        "blog.html",
        articles=all_articles.items(),
        years=years, months=months,
        q=q, selected_year=year, selected_month=month,
    )


@app.get("/blog/<slug>")
def show_article(slug: str):
    article = database.get_article_by_slug(slug)
    if not article or article.is_draft:
        return render_template("404.html"), 404

    database.increment_views(slug)

    all_list = list(database.get_all_articles().values())
    idx = next((i for i, a in enumerate(all_list) if a.slug == slug), None)

    prev_article = all_list[idx + 1] if idx is not None and idx + 1 < len(all_list) else None
    next_article = all_list[idx - 1] if idx is not None and idx > 0 else None

    return render_template(
        "article.html",
        article=article,
        prev_article=prev_article,
        next_article=next_article,
    )


@app.get("/about")
def about():
    return render_template(
        "about.html",
        contact_telegram=cfg.CONTACT_TELEGRAM,
        contact_linkedin=cfg.CONTACT_LINKEDIN,
        telegram_channel=cfg.TELEGRAM_CHANNEL,
    )


@app.route("/kontakt", methods=["GET", "POST"])
def kontakt():
    rate_limit_error = None
    is_ajax = request.headers.get("X-Requested-With") == "fetch"  # cofe sahifasidan keladi

    if request.method == "POST":
        ip = _get_client_ip()
        apply_forced_slowdown()

        # IP bo'yicha umumiy spam himoyasi (feedback + kontakt + cofe uchun bitta)
        if is_feedback_rate_limited(ip):
            if is_ajax:
                return jsonify({"ok": False, "error": RATE_LIMIT_MESSAGE}), 429
            rate_limit_error = RATE_LIMIT_MESSAGE
        else:
            name     = request.form.get("name", "").strip()
            platform = request.form.get("platform", "").strip()
            username = request.form.get("username", "").strip()
            subject  = request.form.get("subject", "").strip()
            body     = request.form.get("message", "").strip()

            # Honeypot: bot to'ldirsa, jim javob qaytariladi
            if platform:
                if is_ajax:
                    return jsonify({"ok": True})
                return redirect(url_for("kontakt"))

            if not name or not body:
                err = "Ism va xabar majburiy."
                if is_ajax:
                    return jsonify({"ok": False, "error": err}), 400
                flash(err, "danger")
            elif len(name) > 120 or len(body) > 5000:
                err = "Matn juda uzun."
                if is_ajax:
                    return jsonify({"ok": False, "error": err}), 400
                flash(err, "danger")
            else:
                record_feedback_attempt(ip)
                database.add_message(
                    name, body,
                    platform[:80] or None,
                    username[:80] or None,
                    subject[:200] or None,
                )
                notifications.notify_new_message(name, body, subject[:200] or None)
                if is_ajax:
                    return jsonify({"ok": True})
                flash("Xabaringiz yuborildi!", "success")
                return redirect(url_for("kontakt"))

    return render_template(
        "kontakt.html",
        contact_email=cfg.CONTACT_EMAIL,
        contact_telegram=cfg.CONTACT_TELEGRAM,
        contact_linkedin=cfg.CONTACT_LINKEDIN,
        contact_github=cfg.CONTACT_GITHUB,
        telegram_channel=cfg.TELEGRAM_CHANNEL,
        rate_limit_error=rate_limit_error,
    )


@app.get("/javoblar")
def javoblar():
    messages = database.get_replied_messages()
    return render_template("javoblar.html", messages=messages)


@app.get("/kofe")
def kofe():
    return redirect(url_for("cofe"), 301)


@app.get("/cofe")
def cofe():
    return render_template("cofe.html")


# ── SEO: sitemap.xml va robots.txt ────────────────────────────────────────────

@app.get("/sitemap.xml")
def sitemap_xml():
    from flask import Response
    articles = list(database.get_all_articles().values())
    base = request.url_root.rstrip("/")
    static_paths = ["/", "/blog", "/about", "/kontakt"]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for p in static_paths:
        lines.append(f"  <url><loc>{base}{p}</loc></url>")
    for a in articles:
        lines.append(f"  <url><loc>{base}/blog/{a.slug}</loc><lastmod>{(a.updated_at or a.date)[:10]}</lastmod></url>")
    lines.append("</urlset>")
    return Response("\n".join(lines), mimetype="application/xml")


@app.get("/robots.txt")
def robots_txt():
    from flask import Response
    default = f"User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: {request.url_root.rstrip('/')}/sitemap.xml\n"
    content = database.get_setting("ROBOTS_TXT") or default
    return Response(content, mimetype="text/plain")


# ── Xato handlerlari ──────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    try:
        if not request.path.startswith("/admin") and not request.path.startswith("/static"):
            database.log_404(request.path, request.referrer)
    except Exception:
        pass
    return render_template("404.html"), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template("404.html"), 403


@app.errorhandler(413)
def too_large(e):
    flash("Fayl hajmi juda katta (maksimum 5 MB).", "danger")
    return redirect(request.referrer or url_for("home"))


@app.errorhandler(500)
def server_error(e):
    return render_template("404.html"), 500


if __name__ == "__main__":
    # Ishlab chiqarish muhitida debug=False bo'lishi SHART
    app.run(host="127.0.0.1", port=8000, debug=cfg.DEBUG)