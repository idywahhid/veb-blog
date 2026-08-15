"""
make_hash.py — Parol uchun xesh yaratish vositasi

Foydalanish:
    python make_hash.py

Natijani .env fayliga ADMIN_PASSWORD_HASH= ga qo'ying.
"""
import getpass
import auth


def main():
    print("Admin parolini kiriting (kiritayotganda ko'rinmaydi):")
    password = getpass.getpass("Parol: ")
    confirm  = getpass.getpass("Qayta kiriting: ")

    if password != confirm:
        print("❌ Parollar mos kelmadi!")
        return

    if len(password) < 12:
        print("⚠️  Ogohlantirish: Parol 12 ta belgidan kam. Kuchli parol tavsiya etiladi.")

    hashed = auth.hash_password(password)
    print("\n✅ .env fayliga qo'shing:\n")
    print(f"ADMIN_PASSWORD_HASH={hashed}")
    print("\n⚠️  .env dan ADMIN_PASSWORD satrini o'chirishni unutmang!")


if __name__ == "__main__":
    main()