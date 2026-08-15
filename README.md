# wahhid — shaxsiy blog

Flask asosidagi terminal-uslubidagi shaxsiy blog/kundalik.

## O'rnatish

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env faylini to'ldiring (SECRET_KEY, ADMIN_PASSWORD_HASH va h.k.)
```

Admin parol hash yaratish:

```bash
python make_hash.py
```

Natijadagi qiymatni `.env` faylidagi `ADMIN_PASSWORD_HASH` ga qo'ying.

## Ishga tushirish

```bash
flask --app app run
```

Production uchun:

```bash
gunicorn app:app -c gunicorn.conf.py
```

## Muhit o'zgaruvchilari

Barcha kerakli o'zgaruvchilar `.env.example` faylida ko'rsatilgan.
