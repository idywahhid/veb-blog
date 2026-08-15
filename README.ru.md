[🇺🇿 O'zbekcha](README.md) | [🇬🇧 English](README.en.md) | [🇷🇺 Русский](README.ru.md)

# wahhid — личный блог

Личный блог и дневник на Flask, оформленный в стиле терминала/редактора кода. Тёмная тема, эстетика `$` prompt и полнофункциональная админ-панель.

## Возможности

- 📝 Статьи — написание, редактирование, черновики, автосохранение
- 🖼️ Галерея — альбомы изображений и управление медиа
- 💬 Форма обратной связи и контактов — защищена rate-limit по IP
- 📧 Email-уведомления о новых сообщениях через Gmail SMTP
- 🔐 Админ-панель — вход (с защитой от brute-force), настройки, ответы на сообщения
- 🎨 Тёмный дизайн в стиле терминала (JetBrains Mono, зелёный акцент)

## Технологии

- **Backend:** Python, Flask 3
- **База данных:** SQLite
- **Сервер:** Gunicorn (для production)
- **Работа с изображениями:** Pillow
- **Генерация PDF:** ReportLab

## Установка

```bash
git clone https://github.com/idywahhid/veb-blog.git
cd veb-blog

python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Заполните .env (SECRET_KEY, ADMIN_PASSWORD_HASH и т.д.)
```

Создание хеша пароля администратора:

```bash
python make_hash.py
```

Полученное значение вставьте в `ADMIN_PASSWORD_HASH` в файле `.env`.

## Запуск

Режим разработки:

```bash
flask --app app run
```

Production:

```bash
gunicorn app:app -c gunicorn.conf.py
```

## Страницы

### 🏠 Главная (`/`)
Стартовая страница в стиле терминала — краткое представление, ссылки на последние статьи и интерактивный блок "терминал" с информацией о профиле.

![Главная страница](static/screenshots/home.jpg)

### 📰 Блог (`/blog`)
Все опубликованные статьи, сгруппированные по дате, с панелью поиска.

![Страница блога](static/screenshots/blog.jpg)

### 📄 Статья (`/blog/<slug>`)
Полный текст статьи, время чтения, местоположение и навигация к предыдущей/следующей статье.

![Страница статьи](static/screenshots/article.jpg)

### 👤 Обо мне (`/about`)
Краткий рассказ об авторе и о том, что можно найти в блоге.

![Страница «Обо мне»](static/screenshots/about.jpg)

### ✉️ Контакты (`/kontakt`)
Форма отправки сообщения в стиле терминала и список каналов связи. Защищена rate-limit.

![Страница контактов](static/screenshots/kontakt.jpg)

### 🔐 Админ — вход (`/admin/login`)
Вход по логину и паролю с защитой от brute-force.

![Вход в админку](static/screenshots/admin_login.jpg)

### 📊 Админ — панель управления
Управление статьями, обратной связью, галереей и настройками в одном месте.

![Админ-панель](static/screenshots/admin_dashboard.jpg)

## Переменные окружения

| Переменная | Описание |
|---|---|
| `SECRET_KEY` | Секретный ключ Flask (обязателен для production) |
| `DEBUG` | Режим разработки (`true`/`false`) |
| `SESSION_COOKIE_SECURE` | Отправлять cookie только по HTTPS (в production — `true`) |
| `ADMIN_USERNAME` | Логин админ-панели |
| `ADMIN_PASSWORD_HASH` | Хеш пароля, созданный через `make_hash.py` |
| `DB_PATH` | Путь к файлу базы данных SQLite |
| `CONTACT_EMAIL` / `CONTACT_TELEGRAM` / `CONTACT_LINKEDIN` / `CONTACT_GITHUB` | Ссылки на странице контактов |
| `TELEGRAM_CHANNEL` | Ссылка на Telegram-канал |

Все переменные с примерами описаны в файле `.env.example`.

## Структура проекта

```
├── app.py              # Основное Flask-приложение
├── admin.py             # Маршруты админ-панели
├── auth.py              # Хеширование/проверка пароля
├── config.py             # Загрузка настроек из .env
├── database.py           # Работа с SQLite
├── notifications.py       # Email-уведомления
├── templates/             # HTML-шаблоны
├── static/                # CSS, JS, изображения
└── requirements.txt        # Зависимости Python
```

## Лицензия

Личный проект. Можете адаптировать под свои нужды.
