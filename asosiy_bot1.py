import asyncio
import html
import os
import re
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Token kodga yozilmaydi. Terminalda o'rnating:
#   PowerShell: $env:BOT_TOKEN="yangi_token"
#   CMD:        set BOT_TOKEN=yangi_token
#   Linux/Mac:  export BOT_TOKEN="yangi_token"
TOKEN = os.getenv("BOT_TOKEN", "")
if not TOKEN and os.path.exists("token.txt"):          # token.txt: ichida faqat token
    TOKEN = open("token.txt", encoding="utf-8").read().strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "8921006774").split(",") if x.strip().isdigit()}
DB_PATH = os.getenv("DB_PATH", "ziyo_kutubxonasi.db")

dp = Dispatcher()

# --- Doimiy foydalanuvchi bazasi ---
def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db_connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, joined_at TEXT NOT NULL, last_seen TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS favorites (user_id INTEGER NOT NULL, item_type TEXT NOT NULL, item_id TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(user_id,item_type,item_id))")
        db.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, item_type TEXT NOT NULL, item_id TEXT NOT NULL, title TEXT NOT NULL, opened_at TEXT NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_history_user ON history(user_id, opened_at DESC)")

def register_user(user):
    now=datetime.utcnow().isoformat(timespec="seconds")
    with db_connect() as db:
        db.execute("""INSERT INTO users VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, last_name=excluded.last_name, last_seen=excluded.last_seen""", (user.id,user.username or "",user.first_name or "",user.last_name or "",now,now))

def add_history(user_id,item_type,item_id,title):
    with db_connect() as db:
        db.execute("INSERT INTO history(user_id,item_type,item_id,title,opened_at) VALUES(?,?,?,?,?)",(user_id,item_type,item_id,title,datetime.utcnow().isoformat(timespec="seconds")))
        db.execute("DELETE FROM history WHERE user_id=? AND id NOT IN (SELECT id FROM history WHERE user_id=? ORDER BY opened_at DESC LIMIT 50)",(user_id,user_id))

def toggle_favorite(user_id,item_type,item_id,title):
    with db_connect() as db:
        row=db.execute("SELECT 1 FROM favorites WHERE user_id=? AND item_type=? AND item_id=?",(user_id,item_type,item_id)).fetchone()
        if row:
            db.execute("DELETE FROM favorites WHERE user_id=? AND item_type=? AND item_id=?",(user_id,item_type,item_id)); return False
        db.execute("INSERT INTO favorites VALUES(?,?,?,?,?)",(user_id,item_type,item_id,title,datetime.utcnow().isoformat(timespec="seconds"))); return True

def is_favorite(user_id,item_type,item_id):
    with db_connect() as db: return db.execute("SELECT 1 FROM favorites WHERE user_id=? AND item_type=? AND item_id=?",(user_id,item_type,item_id)).fetchone() is not None

def get_favorites(user_id):
    with db_connect() as db: return db.execute("SELECT item_type,item_id,title FROM favorites WHERE user_id=? ORDER BY created_at DESC",(user_id,)).fetchall()

def get_history(user_id):
    with db_connect() as db: return db.execute("SELECT item_type,item_id,title FROM history WHERE user_id=? GROUP BY item_type,item_id ORDER BY MAX(opened_at) DESC LIMIT 20",(user_id,)).fetchall()

def admin_only(uid): return uid in ADMIN_IDS

def favorite_button(item_type,item_id,title,user_id):
    marked=is_favorite(user_id,item_type,item_id)
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💔 Sevimlidan olib tashlash" if marked else "⭐ Sevimlilarga qo'shish", callback_data=f"fav_{item_type}_{item_id}")]])

def favorites_keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=("📚 " if r["item_type"]=="book" else "🎧 ")+r["title"][:55],callback_data=f"openfav_{r['item_type']}_{r['item_id']}")] for r in rows])

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Statistika",callback_data="admin_stats")],[InlineKeyboardButton(text="👥 Foydalanuvchilar",callback_data="admin_users")],[InlineKeyboardButton(text="📢 Xabar yuborish",callback_data="admin_broadcast")]])

init_db()
admin_broadcast_state=set()

# ======================================================================
#  1-QISM: MAKTAB, MAKTABGACHA VA INGLIZ TILI KITOBLARI
# ======================================================================
RAW_BOOKS = {
    # --- 1-SINF ---
    "1_alifbe": {"file_id": "BQACAgIAAxkBAANUaroz0E0DCGlzB5jyRnKh6PnCMGwAAtqsAAJoldBJUS_PjJQMhO89BA", "caption": "📘 **1-sinf Alifbe darsligi**"},
    "1_onatili": {"file_id": "BQACAgIAAxkBAANNaroy21bw0XR5x7Er8HJKa07sGwYAAt8PAAL1NzhJO9CV620Hny09BA", "caption": "📗 **1-sinf Ona tili va o'qish savodxonligi**"},
    "1_matematika": {"file_id": "BQACAgIAAxkBAANLaroy223mxqgJrnt7ttyy3AlHnHMAAuEPAAL1NzhJPHFGE-eP-309BA", "caption": "📙 **1-sinf Matematika darsligi**"},
    "1_tabiiy": {"file_id": "BQACAgIAAxkBAANOaroy25L4KsN5aK_9hnrxZLrjlIMAAuAPAAL1NzhJku7jzXsIkMM9BA", "caption": "🌱 **1-sinf Tabiiy fanlar darsligi**"},
    "1_tarbiya": {"file_id": "BQACAgIAAxkBAANMaroy2zBWiQW96dYTMyu7a4eP7GcAAu4KAAIKQ9lKu7bLVEswLMg9BA", "caption": "🕊 **1-sinf Tarbiya darsligi**"},
    "1_ingliz": {"file_id": "BQACAgIAAxkBAANParoy2wo7lHVwz5Rg-mGySYMJSrkAAnMaAAKbQIlLKs5ZG7kt9mM9BA", "caption": "🇬🇧 **1-sinf Ingliz tili darsligi**"},

    # --- 2-SINF ---
    "2_onatili": {"file_id": "BQACAgIAAxkBAANjaro1eVH_ZFPWbq00Bu71npispMkAAqQQAAJbAZBJH8apoh7YG-M9BA", "caption": "📗 **2-sinf Ona tili va o'qish savodxonligi (1-qism)**"},
    "2_tabiiy": {"file_id": "BQACAgIAAxkBAANlaro1eTyuYfGg6WSqLraITxV7g9oAAo8RAAKuJ-lIUnPrIpkZTfs9BA", "caption": "🌱 **2-sinf Tabiiy fanlar darsligi**"},
    "2_tasviriy": {"file_id": "BQACAgIAAxkBAANmaro1eUW1MnkvJThi122BAAHA8g7-AAKZEAACWwGQSVZylG1WqboEPQQ", "caption": "🎨 **2-sinf Tasviriy san'at darsligi**"},
    "2_musiqa": {"file_id": "BQACAgIAAxkBAANnaro1edHJ56I2uhvdklsNb2TrpV0AApoQAAJbAZBJoqfUyGY6y0I9BA", "caption": "🎵 **2-sinf Musiqa darsligi**"},
    "2_texnologiya": {"file_id": "BQACAgIAAxkBAANoaro1eYePh-zZetLIMxLuOXkjWD4AAp8QAAJbAZBJ_ytBh03sVYk9BA", "caption": "🛠 **2-sinf Texnologiya darsligi**"},
    "2_rustili": {"file_id": "BQACAgIAAxkBAANparo1eZ2RuPDVObcav46DiOub9xQAAp0QAAJbAZBJGB1SLhgKhi09BA", "caption": "🇷🇺 **2-sinf Rus tili darsligi**"},

    # --- 3-SINF ---
    "3_onatili": {"file_id": "BQACAgIAAxkBAANsaro1eZ9oow5-XwNUcgABnsx2JJrHAAMdAAJ13JFLlRbFQrYIQ6I9BA", "caption": "📗 **3-sinf Ona tili va o'qish savodxonligi (1-qism)**"},
    "3_matematika": {"file_id": "BQACAgIAAxkBAANtaro1eZy1_0CVOmy5VluAMIdpVCkAAkIbAAJPmolLA476ivCINbw9BA", "caption": "📙 **3-sinf Matematika darsligi**"},
    "3_texno": {"file_id": "BQACAgIAAxkBAANvaro1eTKZY0fK3AuwyZaoHEed1xMAAsoaAAJPmolL_q0rR8k286k9BA", "caption": "🛠 **3-sinf Texnologiya darsligi**"},
    "3_musiqa": {"file_id": "BQACAgIAAxkBAANwaro1ecRyE9TKkpHVIcGJ5siguq4AAi4bAAJPmolLj7WHUDhR-0s9BA", "caption": "🎵 **3-sinf Musiqa darsligi**"},
    "3_tabiiy": {"file_id": "BQACAgIAAxkBAANxaro1ecTDxTvPy4jGSkZL8MPBXkMAAgobAAJPmolLMzqOLYEPhO09BA", "caption": "🌱 **3-sinf Tabiiy fanlar darsligi**"},
    "3_ingliz": {"file_id": "BQACAgIAAxkBAANyaro1eUDEtk43l26Wt2GjVqISVtsAArEfAAKbQJFL9ye3PZtggHs9BA", "caption": "🇬🇧 **3-sinf Ingliz tili (Guess What!)**"},
    "3_rustili": {"file_id": "BQACAgIAAxkBAANzaro1eSNKb-0Qh8WIyMaWzNIVVWUAAnUbAAJPmolLz1fm-cySp0g9BA", "caption": "🇷🇺 **3-sinf Rus tili darsligi**"},
    "3_tarbiya": {"file_id": "BQACAgIAAxkBAAN0aro1eeOngakLtnAsy9XniU9ar2IAAk0HAALdcwABS0HL32iaDxRtPQQ", "caption": "🕊 **3-sinf Tarbiya darsligi**"},

    # --- 7-SINF ---
    "7_algebra": {"file_id": "BQACAgIAAxkBAAO8aro1eT8cli2ymVKnDuEfs0xxlOkAAt0DAAIeU4BJBBvaIcrfe-c9BA", "caption": "📐 **7-sinf Algebra darsligi**"},
    "7_uzbtarixi": {"file_id": "BQACAgIAAxkBAAO_aro1eQtECyVUBUPZzk8kOfuiJpAAAuUDAAIeU4BJuGLQ4sxEplE9BA", "caption": "📜 **7-sinf O'zbekiston tarixi**"},

    # --- 8-SINF ---
    "8_adabiyot": {"file_id": "BQACAgQAAxkBAAOparo1eUvR1Dju3i0WtANskGq0Ms4AAl4JAAKdm0lRvddaRwKpCKE9BA", "caption": "📖 **8-sinf Adabiyot darsligi**"},
    "8_algebra": {"file_id": "BQACAgIAAxkBAAOqaro1eZPVUpjDMP0SwL6vzv8Vc4MAAlEEAALnNGFKeEo0CU1yQzk9BA", "caption": "📐 **8-sinf Algebra darsligi**"},
    "8_biologiya": {"file_id": "BQACAgIAAxkBAAOraro1eSJ932-6g5R8wKktamXxDzMAAoFAAAKCbyhLdGgMpRXkPxU9BA", "caption": "🧬 **8-sinf Odam va uning salomatligi**"},
    "8_jahontarixi": {"file_id": "BQACAgIAAxkBAAOsaro1eflYvcbbA5p2222bIgifm7QAAuwDAAIeU4BJDlAii2mYqm89BA", "caption": "🌍 **8-sinf Jahon tarixi**"},
    "8_geometriya": {"file_id": "BQACAgIAAxkBAAOtaro1eWxVeSOhYe6__Fe2W3idirwAAkUGAALM0JlIy_R3ffxKgJk9BA", "caption": "📐 **8-sinf Geometriya darsligi**"},
    "8_uzbtarixi": {"file_id": "BQACAgIAAxkBAAOvaro1ecwU3Q4nyoQufsCwAVPCA5MAAvA1AAIe2cBLui86B2v4knQ9BA", "caption": "📜 **8-sinf O'zbekiston tarixi**"},
    "8_texnologiya": {"file_id": "BQACAgIAAxkBAAOxaro1eZsJ-7znbC5_s_JjcUVBTWgAAtcGAALM0JlIIh0b7Acbm_Q9BA", "caption": "🛠 **8-sinf Texnologiya darsligi**"},
    "8_fizika": {"file_id": "BQACAgIAAxkBAAOyaro1eYOFoQABeQPJBpJO5kRcYwsVAAKNBAACDYy4S71pzEnDAcKSPQQ", "caption": "⚡️ **8-sinf Fizika darsligi**"},
    "8_kimyo": {"file_id": "BQACAgIAAxkBAAOzaro1ecBmH_sfD_aI_Ga4u3mfV98AAoYEAAINjLhLyKalBw5_DCo9BA", "caption": "🧪 **8-sinf Kimyo darsligi**"},
    "8_iqtisod": {"file_id": "BQACAgIAAxkBAAO0aro1eayIeTrtBF_LjSV3pXcQKE4AAv4DAAJxGMBLFhartKAms509BA", "caption": "📊 **8-sinf Iqtisodiy bilim asoslari**"},
    "8_ingliz": {"file_id": "BQACAgIAAxkBAAO2aro1eV3rjyfPXVyKRy9DLpU216AAAokEAAINjLhLlHHhEfg8P-k9BA", "caption": "🇬🇧 **8-sinf Ingliz tili darsligi**"},
    "8_tarbiya": {"file_id": "BQACAgIAAxkBAAO4aro1efFSFDoxO0vMxfcgWigv_xQAAlYRAAIpiBhJjtdhjvFgLJc9BA", "caption": "🕊 **8-sinf Tarbiya darsligi**"},

    # --- 9-SINF ---
    "9_onatili": {"file_id": "BQACAgIAAxkBAAOWaro1eX4bJt5GQKlIqbYUw2o5spYAAr4EAAKK0xBJ4m8xXVpbOzg9BA", "caption": "📗 **9-sinf Ona tili darsligi**"},
    "9_adabiyot": {"file_id": "BQACAgIAAxkBAAOXaro1eYx-MEPNiZhWwGdODHTxecoAAkkEAAJp5QlJXFKx9DUtQC89BA", "caption": "📖 **9-sinf Adabiyot darsligi**"},
    "9_algebra": {"file_id": "BQACAgIAAxkBAAOYaro1eVfqKbtW8UNVpMOV5CefjzYAAgoEAAIHbgFLYRKKn-tnP5Y9BA", "caption": "📐 **9-sinf Algebra darsligi**"},
    "9_geofrafiya": {"file_id": "BQACAgIAAxkBAAOearo1eUcTPFRaBIX_aFELEDwvcVUAAkkEAAJGUUlIOlszMocraj09BA", "caption": "🌍 **9-sinf Geografiya darsligi**"},
    "9_milliygoya": {"file_id": "BQACAgIAAxkBAAOgaro1eb1UanaTZrw_C2LTDtiWmY8AAhYGAAJu4ohIg5V5zaKnIuM9BA", "caption": "🇺🇿 **9-sinf Milliy istiqlol g'oyasi**"},
    "9_geometriya": {"file_id": "BQACAgIAAxkBAAOiaro1eTn8JnUJHUkwiNP0n3lxeYoAAg4GAAJu4ohIJt9EeZgNNYk9BA", "caption": "📐 **9-sinf Geometriya darsligi**"},
    "9_texnologiya": {"file_id": "BQACAgIAAxkBAAOlaro1eWNrcySCYYoYxNrzis8ZMYwAAhoGAAJu4ohIA0DI0Qiuflc9BA", "caption": "🛠 **9-sinf Texnologiya darsligi**"},
    "9_fizika": {"file_id": "BQACAgIAAxkBAAOcaro1eXhAU4dw9ZF7FVNJmrP8QbYAAiwHAALRUqhKB32iZqyteJg9BA", "caption": "⚡️ **9-sinf Fizika darsligi**"},
    "9_rustili": {"file_id": "BQACAgUAAxkBAAOnaro1eXi1jq1O35U0nMnXdg3q8kEAAoAJAAKHteFWeTUZ5oI9w9A9BA", "caption": "🇷🇺 **9-sinf Rus tili darsligi**"},

    # --- 10-SINF ---
    "10_onatili": {"file_id": "BQACAgIAAxkBAAOEaro1efJInvIVWsLlNDVWY6FW3w8AAq0cAAIgq2BIg7Z6sAczUyw9BA", "caption": "📗 **10-sinf Ona tili darsligi**"},
    "10_huquq": {"file_id": "BQACAgIAAxkBAAOIaro1eew1QAQtRYdAqA0EjwdG0YcAApwwAAJppblLwcgGvYOoiO49BA", "caption": "⚖️ **10-sinf Huquq darsligi**"},
    "10_dunyodinlari": {"file_id": "BQACAgIAAxkBAAOJaro1ebnZbKL8OQqX4srOoemUJUUAAp8DAAIOWKBJH7o7mdSpblc9BA", "caption": "📖 **10-sinf Dunyo dinlari tarixi**"},
    "10_geografiya": {"file_id": "BQACAgIAAxkBAAOKaro1eZIIVKD0K7mG2vYUcKFZbU4AAqYgAAKJxthI8z-u7jfoEKA9BA", "caption": "🌍 **10-sinf Geografiya darsligi**"},
    "10_fizika": {"file_id": "BQACAgIAAxkBAAOLaro1ecUeR97aiBOmsebehUwmoygAAkEgAAJNTEBIz1Y5FaYzUHE9BA", "caption": "⚡️ **10-sinf Fizika darsligi**"},
    "10_11_informatika": {"file_id": "BQACAgIAAxkBAAOParo1eUGwY6EGt96fJ9l4yeJnBikAAuYxAALLGwhL5UtkUbeRT3o9BA", "caption": "💻 **10-11-sinf Cambridge Informatika**"},
    "10_jahontarixi": {"file_id": "BQACAgIAAxkBAAOQaro1eeMkuSlmVqJgzfaQmHEmbEoAAlceAALAkNBIblHvzxa6uf49BA", "caption": "🌍 **10-sinf Jahon tarixi**"},
    "10_uzbtarixi": {"file_id": "BQACAgIAAxkBAAORaro1eXm1a4Tz9Az5y1_z95e5aYIAAoodAAKkN_FIfkjBJ-F0AqA9BA", "caption": "📜 **10-sinf O'zbekiston tarixi**"},
    "10_kimyo": {"file_id": "BQACAgIAAxkBAAOSaro1edhvDviX1w7ekD_qVh4kbjcAAgJDAAIQYhlLyQvOIN3JKOE9BA", "caption": "🧪 **10-sinf Kimyo darsligi**"},
    "10_11_manaviyat": {"file_id": "BQACAgIAAxkBAAOTaro1edz9ko-RsRU6EhNtYHiVOa8AAlACAALEQrhINviEl6sYsK89BA", "caption": "🇺🇿 **10-11-sinf Ma'naviyat asoslari**"},
    "10_algebra": {"file_id": "BQACAgIAAxkBAAOUaro1eVT1-NRHVDg2bpU4jGdNnAIAAusqAAL_FEhIIXFzXK33C8w9BA", "caption": "📐 **10-sinf Algebra darsligi**"},
    "10_tarbiya": {"file_id": "BQACAgIAAxkBAAOVaro1eY1gQh0jZXsLX0t_6PNmqx0AAjsQAALOpUBK3ameqPd_xOc9BA", "caption": "🕊 **10-sinf Tarbiya darsligi**"},

    # --- 11-SINF ---
    "11_onatili2": {"file_id": "BQACAgIAAxkBAAN1aro1eWk7di1ke1VSmQc6EmTc6ygAArgIAAJTEBFLzPJNG8FdaDQ9BA", "caption": "📗 **11-sinf Ona tili (2-qism)**"},
    "11_adabiyot1": {"file_id": "BQACAgIAAxkBAAN2aro1ecAHmUM4hHg8R2hJ-tlZwIsAAsoFAAKg8BlJlkRTpVq01uo9BA", "caption": "📖 **11-sinf Adabiyot (1-qism)**"},
    "11_jahontarixi": {"file_id": "BQACAgIAAxkBAAN3aro1edB3yAFIVVErmhrSpbujk44AAvwGAALM0JlIRyF7aDyVlGY9BA", "caption": "🌍 **11-sinf Jahon tarixi**"},
    "11_uzbtarixi": {"file_id": "BQACAgIAAxkBAAN5aro1edGTAWE8vZkGqOTNsPHoxQ0AAgcHAALM0JlIkFXC-ecWSV49BA", "caption": "📜 **11-sinf O'zbekiston tarixi**"},
    "11_astronomiya": {"file_id": "BQACAgIAAxkBAAN7aro1eSsLZ-A-LFJfwnYj6VVtGg0AAgoHAALM0JlI0AXsMm-srTg9BA", "caption": "🌌 **11-sinf Astronomiya darsligi**"},
    "11_kimyo": {"file_id": "BQACAgIAAxkBAAN8aro1efeGZHDt2rg9fgH0PKWhs_4AAgkHAALM0JlI3f9jyN4pUxw9BA", "caption": "🧪 **11-sinf Umumiy kimyo darsligi**"},
    "11_biologiya": {"file_id": "BQACAgIAAxkBAAN9aro1eR56oczLYW7yVn49UOmIYYUAAgsHAALM0JlIkGMGeZgg4fQ9BA", "caption": "🧬 **11-sinf Biologiya darsligi**"},
    "11_huquq": {"file_id": "BQACAgIAAxkBAAN-aro1eR3mAkuK3cVPN6QPeWiQGz0AAgwHAALM0JlInIt0o1-1A3E9BA", "caption": "⚖️ **11-sinf Davlat va huquq asoslari**"},
    "11_fizika": {"file_id": "BQACAgIAAxkBAAN_aro1eZeR5n3vrbj5STiRrjKkYyQAAg4HAALM0JlIdKyyx7RhClM9BA", "caption": "⚡️ **11-sinf Fizika darsligi**"},
    "11_dunyodinlari": {"file_id": "BQACAgIAAxkBAAOAaro1eY5FH8ZtZgsfszkyZnkau9IAAg0HAALM0JlI3k-sinqoNY09BA", "caption": "📖 **11-sinf Dunyo dinlari tarixi**"},
    "11_tarbiya": {"file_id": "BQACAgIAAxkBAAOCaro1easdyl5i50pC95CeSuMq_O0AAiARAAJGXzFIBWjcsMQw2889BA", "caption": "🕊 **11-sinf Tarbiya darsligi**"},
    "11_ingliz": {"file_id": "BQACAgIAAxkBAAODaro1eb1nsa7-QJOcVUNkvj7-m58AAvYYAAKpaZhLvAABuhzw7US5PQQ", "caption": "🇬🇧 **11-sinf Ingliz tili (Prepare SB)**"},

    # --- MAKTABGACHA TA'LIM ---
    "pre_alifbe": {"file_id": "BQACAgIAAxkBAANUaroz0E0DCGlzB5jyRnKh6PnCMGwAAtqsAAJoldBJUS_PjJQMhO89BA", "caption": "🔤 **Bolalar uchun Alifbe darsligi**\n\nKichkintoylar uchun maxsus! 🧸"},
    "pre_1yosh1": {"file_id": "BQACAgIAAxkBAAIBQmq6nEF9TZFMOVUAAQ0783IZbU8moQACLD0AAr7XUEk6BzrA-BjM9z0E", "caption": "🧸 **1 yoshdan katta bolalar uchun mashg'ulotlar (1-qism)**"},
    "pre_1yosh2": {"file_id": "BQACAgIAAxkBAAIBQ2q6nEGBVpmxzHhkxniDB3AVb8a4AAItPQACvtdQSSqJFAs38M9TPQQ", "caption": "🧸 **1 yoshdan katta bolalar uchun mashg'ulotlar (2-qism)**"},
    "pre_nutq": {"file_id": "BQACAgIAAxkBAAIBRmq6nEE8aJ3wA-qzhEWAeB2G2a20AAIKiAACYxj5S0KcXYH_6aaqPQQ", "caption": "🗣 **Nutqni rivojlantiruvchi 10 ta amaliy mashq**"},
    "pre_pazl": {"file_id": "BQACAgIAAxkBAAIBQWq6nEFun0meedUQAAFHd6nwfDp_LAACrCkAAt17aUtL-5qQ3euezz0E", "caption": "🧩 **Pazllar va mantiqiy rasmlar to'plami**"},
    "pre_flashcard": {"file_id": "BQACAgIAAxkBAAIBRGq6nEGg0XVYQn5wqO5haaIwoWerAAKlcwACUSuBSyIro4HhV5llPQQ", "caption": "🎴 **Flashcard (Rasmli kartochkalar)**"},
    "pre_baliq": {"file_id": "BQACAgIAAxkBAAIBRWq6nEHxsAzEAo7mlnEPbAKcNkSkAALqfQACk9NZS_HLM3njrYwUPQQ", "caption": "🎨 **Rangli baliqchalar bo'yash va o'yin kitobi**"},
    "pre_paygambar": {"file_id": "BQACAgIAAxkBAAIBR2q6nEFLzSH4K0Uq5akMyInoeLa8AAJBFwAClRyBSPHPVQuJvNoePQQ", "caption": "🌙 **Payg'ambarning istagi — Bolalar uchun Qur'ondan qissa**"},
    "pre_salom": {"file_id": "BQACAgIAAxkBAAIBSGq6nEEjVTyyG9RqwvuRGxtQmYhIAAKKHwACqO25SJStjoMplzCOPQQ", "caption": "🕊 **Salomlashish naqadar go'zal (Odob-axloq)**"},
    "pre_bemor": {"file_id": "BQACAgIAAxkBAAIBSWq6nEFDNFTr4RlDT7vpbRrxE7IxAAJWIAACFhHYSbYCfis3CzTcPQQ", "caption": "❤️ **Bemorlarni yo'qlamoq qanday yaxshi**"},
    "pre_kechirish": {"file_id": "BQACAgIAAxkBAAIBS2q6nEH290y_l3utER6Tj9jx6G1dAAKoHQAC3huZS4PIdlJzrKTwPQQ", "caption": "🌸 **Kechirish qanday yaxshi (Tarbiyaviy qissa)**"},
    "pre_birodarlik": {"file_id": "BQACAgIAAxkBAAIBSmq6nEHkIj8WOHGfssyI0Gzeo_aMAAJ3HgACvUQJSjG5XmF4ymFTPQQ", "caption": "🤝 **Birodarlik o'yini qanday yaxshi**"},

    # --- INGLIZ TILI (NAVIGATE) ---
    "nav_beginner": {"file_id": "BQACAgIAAxkBAAIBY2q6n3MUnHrdjQ3t80EXOLhP7eITAAL7DgAC6P3IScOOQ2r07fVMPQQ", "caption": "🇬🇧 **Navigate Beginner A1 Coursebook**\n\nGood luck with your English! 📚"},
    "nav_elem": {"file_id": "BQACAgQAAxkBAAIBZWq6n96XqfwhZsgz_XtRTxGWbtgfAAL2BwACQadAUeOBo_Qx-WBnPQQ", "caption": "🇬🇧 **Navigate Elementary A2 Coursebook (Teacher's Edition)**\n\nGood luck with your English! 📚"},
    "nav_pre_inter": {"file_id": "BQACAgQAAxkBAAIBZ2q6oAp1IXF2n5kvWM6fyu8j-s3bAALTBgACbzEoUc5ZumovKPxSPQQ", "caption": "🇬🇧 **Navigate Pre-Intermediate B1 Coursebook**\n\nGood luck with your English! 📚"},
    "nav_inter": {"file_id": "BQACAgQAAxkBAAIBaWq6oFUPFOHA0ZBwjxjelFD_YwmoAAIfBwACg1MwUQvVFUrkGMGLPQQ", "caption": "🇬🇧 **Navigate Intermediate B1+ Coursebook**\n\nGood luck with your English! 📚"},
    "nav_upper": {"file_id": "BQACAgQAAxkBAAIBa2q6oGxhMqQ77I2YUFZ6T6fe91q2AAI9BwACAr8oUS2I46bf-A6mPQQ", "caption": "🇬🇧 **Navigate Upper-Intermediate B2 Coursebook**\n\nGood luck with your English! 📚"},
    "nav_adv": {"file_id": "BQACAgQAAxkBAAIBbWq6oI6bVJnPRLFqCM3u032o16v1AAK2CAAC8zEwUdLq8R-OIZmYPQQ", "caption": "🇬🇧 **Navigate Advanced C1 Coursebook**\n\nGood luck with your English! 📚"},
}

# ======================================================================
#  2-QISM: DETEKTIV KITOBLAR  (sarlavha, muallif, file_id)
# ======================================================================
DETEKTIV_KITOBLAR = [
    ("Burgut tog'da ulg'ayadi (1-kitob)", "Nuriddin Ismoilov", "BQACAgIAAxkBAAIBs2q7xgK69Up4S4M-EmBZFm5gJSlUAAJNdgACP9PIS04oD546Lwo7PQQ"),
    ("Mansabdorning o‘g‘irlanishi", "Agata Kristi", "BQACAgIAAxkBAAIB9mq7xgK7J2itXKrt8lqxWr5dIibZAAKvMQACbXjgS_Fr4TzFPb9XPQQ"),
    ("Iblis saltanati (2-kitob)", "Nuriddin Ismoilov", "BQACAgIAAxkBAAIBuWq7xgI4hFWqQKgMNmP1CVemOF2SAAIBewACQccRSI-H00zRLc-KPQQ"),
    ("Ishtar ibodatxonasidagi qotillik", "Agata Kristi", "BQACAgIAAxkBAAIBqWq7xgKVmgPM2i6UPThfBgEChM0OAAKiMQACbXjgSz62fk5uWIDePQQ"),
    ("Omonat g‘or siri", "Nuriddin Ismoilov", "BQACAgQAAxkBAAIBrGq7xgKMIcCalz-SNOdh_NWRAAFKCgACCwoAApo38VG53ONa9cLe_T0E"),
    ("Uch mushketyor", "Aleksandr Dyuma", "BQACAgIAAxkBAAIB0Gq7xgJrKa1fTMM0ZYt5VGLe1fw0AAKvlwACkMEoSu_MnZm4RrCxPQQ"),
    ("Mafiya sardori (1-kitob)", "Nuriddin Ismoilov", "BQACAgIAAxkBAAIBrWq7xgJB-k1g-2tdoWyRVKLg026FAAKOgQACswMYS3Ob8wmhNNsbPQQ"),
    ("Tansoqchi (2-kitob)", "Nuriddin Ismoilov", "BQACAgIAAxkBAAIBsmq7xgKgVshILiwHDOQ-qKeC9gmbAALOjAACxMlhSyEivcY00cqBPQQ"),
    ("Gonkongdan kelgan tobut", "Jeyms Xedli Cheyz", "BQACAgEAAxkBAAIBxGq7xgLdGDORNBDHJInR0GnFCtALAAImAwAC9WFBRUHslmDNsFbRPQQ"),
    ("Orziqib kutaman ertani", "Sidni Sheldon", "BQACAgQAAxkBAAIByGq7xgIPbroBjQtjL-KK7t6jjsk7AALmCwACo6OZUfSzTqDh4DwyPQQ"),
    ("Baxtning olis manzili", "Nuriddin Ismoilov", "BQACAgUAAxkBAAIB5mq7xgJNQy8Jwu5H92EZmIQd-ii3AALcDwACTneQVWbnsOteDT5LPQQ"),
    ("Sudxo'rning o'limi", "Sadriddin Ayniy", "BQACAgIAAxkBAAIBwWq7xgIMuWc0jYq4-asg9MD1V7VsAALWNQACDrnASQkHXg19iejkPQQ"),
    ("Zindonband qiz nolasi", "Azamat Qorjovov", "BQACAgUAAxkBAAIB22q7xgISZzQHMwqOfzO1XvOCNEjWAALwDAAC6XiJVZqGkk5u6AtEPQQ"),
    ("Kassandra tamg‘asi", "Chingiz Aytmatov", "BQACAgIAAxkBAAIBv2q7xgKpZNEAAWmVK6a0qr_axHWlOQAC1TUAAg65wEmbKMiZoBZyWD0E"),
    ("Sotqin", "Jeyms Xedli Cheyz", "BQACAgEAAxkBAAIBxmq7xgKP0AoS_WOqoF3XmHDjNOklAAJFAgACiCSoRd1zSCEgLx4JPQQ"),
    ("Qon sachragan devor", "Noma'lum", "BQACAgIAAxkBAAIBqGq7xgJMes3KAAGkMVB4HYDekwABsa8AAsZ9AAK7v9FKVhLgeXmUsI89BA"),
    ("Uesseks sovrini", "Noma'lum", "BQACAgIAAxkBAAIBp2q7xgKsvW_FXgABd0Qv_HUpVNxa5QACqXsAAoxDqEpXw6h2MHaYWT0E"),
    ("O‘limga mahkum qilinganlar", "Nuriddin Ismoilov", "BQACAgEAAxkBAAIBqmq7xgLQMKvtJrvnUCd9EASr2lDaAALvAgAC3-gxRkDANahonrCfPQQ"),
    ("Seyfdagi pullar", "Jeyms Xedli Cheyz", "BQACAgIAAxkBAAIBw2q7xgJFoE6ziZW7kzjqfbhJ-vuEAALUNQACDrnAScJma_7mR6CAPQQ"),
    ("Kechikkan qasos", "Komil Sindarov", "BQACAgIAAxkBAAIB1Gq7xgKzj3LRpyUWUH6sib3crxcoAALMJgACUM3RS89ARYHqE74SPQQ"),
    ("Iblis saltanati (1-kitob)", "Nuriddin Ismoilov", "BQACAgIAAxkBAAIBuGq7xgJK5YGJc51UE-bYaGJm5usKAAKKhQACQccBSGsfzv-wt5A6PQQ"),
    ("Burgut tog‘da ulg‘ayadi (5-kitob)", "Nuriddin Ismoilov", "BQACAgQAAxkBAAIBt2q7xgKK7g0Q1vLc5S3DVlEnLl-gAAJ_DAACPXjAUArfGt5EtzsXPQQ"),
    ("Mafiya sardori (2-kitob)", "Nuriddin Ismoilov", "BQACAgIAAxkBAAIBrmq7xgKqSKjDR263NVvbAYZYPaIRAAIziQACuU8gS5ExWNBhJuriPQQ"),
    ("Napoleonzoda", "Sharl Loran", "BQACAgQAAxkBAAIBymq7xgKH2gZQhgR1flBT-xhDMIsNAALpDQACy23JUm2aA9tvnIUuPQQ"),
    ("Da Vinchi siri", "Den Braun", "BQACAgEAAxkBAAIBx2q7xgJSvNnO-K-atGx18K6hfIG3AAL-AwACV5yJRZe_HTGNLhk2PQQ"),
    ("Zo‘raki muttaham", "Martti Larni", "BQACAgIAAxkBAAIBwGq7xgJB5zb_uoYT6Kra4m9J24cmAALTNQACDrnASZKQpZKe46JCPQQ"),
    ("Qo‘rqinchli Tehron", "Mushfiq Kozimiy", "BQACAgQAAxkBAAIBy2q7xgLXYTjM_slcsA11jPT8gPItAAJgEAACgsGhUk3ijA2yk2d2PQQ"),
    ("Burgut tog‘da ulg‘ayadi (3-kitob)", "Nuriddin Ismoilov", "BQACAgIAAxkBAAIBtWq7xgKkcpOL2Ta9Az9XncCAFMH_AALEggACbhHZS242gIJE7hiSPQQ"),
    ("Graf Monte-Kristo (2-kitob)", "Aleksandr Dyuma", "BQACAgQAAxkBAAIBzmq7xgIJuzKodG2_Uvp4hJi_ZHBbAAKACwACNueoU1LfK00xIxbSPQQ"),
    ("Ikki Diana", "Aleksandr Dyuma", "BQACAgIAAxkBAAIBz2q7xgJ9t2G9A_kefb5GFFWEZEcBAAK4iQACEDToSeNwY9K8hCZIPQQ"),
    ("Qil ustidagi taqdir (1-kitob)", "Azamat Qorjovov", "BQACAgQAAxkBAAIB3Gq7xgJplwr6-eLOotG72yxmuowUAAJiCwACHwO4UddsWMc4lh6VPQQ"),
    ("O'g'irlangan bolalik", "Komil Sindarov", "BQACAgUAAxkBAAIB1Wq7xgL681Og-yLK4UGeA7OjRnX4AAIeEgAChF6xVUW5bI9J14cIPQQ"),
    ("Go‘r qizi", "Azamat Qorjovov", "BQACAgQAAxkBAAIB2mq7xgIbHWYjArvahy7zu9aG6eJgAALjDAACzD7pUxxMxl9sNsLtPQQ"),
    ("Iblis saltanati (3-kitob)", "Nuriddin Ismoilov", "BQACAgIAAxkBAAIBumq7xgIquDraZb-cc05Z_Tqw8GvkAAKwdgACQDoZSLKFiSJd0ELHPQQ"),
    ("Burgut tog‘da ulg‘ayadi (4-kitob)", "Nuriddin Ismoilov", "BQACAgQAAxkBAAIBtmq7xgJqTDV3JCQ2gGyVMVjxRLK1AAICCgACPXi4UHODs9YPZ3QFPQQ"),
    ("Suiqasddan so'nggi sukut", "Noma'lum", "BQACAgIAAxkBAAIB02q7xgIliy0WOGvTyU3eky5uEndMAAL1MAACUM3JS7KZ1UKPv__0PQQ"),
    ("Cho‘qintirgan ota yoxud mafiya sardori", "Mario Pyuzo", "BQACAgIAAxkBAAIB12q7xgIBfEZ-YnxGoQMW-qVrvYWYAAKXiAACh_PoSl6up7hfxFhoPQQ"),
    ("Kumush", "Artur Konan Doyl", "BQACAgIAAxkBAAIB6Wq7xgI9LQ3boLJ8B-i0HBpIakLdAAJKLwAC60kYS2QmtO1waDZOPQQ"),
    ("Qora qasr asirasi (1-qism)", "Habib Temirov", "BQACAgIAAxkBAAIB4mq7xgIr1CSUHPKtV2i9tTxvXOVtAALBlQACdNLYS1KR22ycFWkKPQQ"),
    ("Merosxor", "Azamat Qorjovov", "BQACAgQAAxkBAAIB2Wq7xgIaJPXsUrDKixLA_bkEVuBZAAL-DAACuHghU2NFMb88dbTmPQQ"),
    ("Dang‘illama hovlidagi o‘lim", "Jeyms Xedli Cheyz", "BQACAgIAAxkBAAIBxWq7xgK-WlhNVIoUbtfVWKhzWc2NAALNJgACUM3RSzSzdoUaj7NxPQQ"),
    ("Generalning bevasi", "Habib Temirov", "BQACAgQAAxkBAAIB4Wq7xgIbVt7sa9MPDji_P8qohXKEAAJcCwACkbVpUQABwhfV0i-KHj0E"),
    ("Detektiv hikoyalar", "To'plam", "BQACAgEAAxkBAAIB2Gq7xgKQKBnGTRV0OP7ktA5YHw-0AAL8AgAC_SngRUmEsKUqA084PQQ"),
    ("Mafiya sardori (3-kitob)", "Nuriddin Ismoilov", "BQACAgUAAxkBAAIBr2q7xgK6H3PlEHKaP5AWYRtMYAWLAAKjEwAClIEBVNQNZeGLHwKWPQQ"),
    ("Qil ustidagi taqdir (4-kitob)", "Azamat Qorjovov", "BQACAgQAAxkBAAIB32q7xgItrytIUOHWQkCdAAE1_hFQ1AACZQsAAh8DuFGnevywGg5B3j0E"),
    ("Qora qasr asirasi (4-qism)", "Habib Temirov", "BQACAgIAAxkBAAIB5Wq7xgITcJ0zQA_Bf5wa88W5EtiQAALrgAACZqUQSPuv6tGGVvJ0PQQ"),
    ("Qil ustidagi taqdir (3-kitob)", "Azamat Qorjovov", "BQACAgQAAxkBAAIB3mq7xgKvRpO9hexqOcc9S4dXIM3sAAJkCwACHwO4UQX4E3oAAc3YRT0E"),
    ("Qil ustidagi taqdir (5-kitob)", "Azamat Qorjovov", "BQACAgQAAxkBAAIB4Gq7xgJs7mfmIW9TDvmYIqPcHC3lAAJmCwACHwO4UUruadj6nPvaPQQ"),
    ("Amirlikning oltin taxti izidan", "Komil Sindarov", "BQACAgUAAxkBAAIB1mq7xgIAAaebM17BJbl_lxDuZCt-pwACExgAAgfOuVU3A7X6ukWuUD0E"),
    ("Uqubat", "Isfandiyor", "BQACAgQAAxkBAAIB6Gq7xgIan0-PugyzNzYkrVfNZcw5AAKzCwACJd5YUI_m4TDEXfyTPQQ"),
    ("Qora qasr asirasi (2-qism)", "Habib Temirov", "BQACAgIAAxkBAAIB42q7xgIrG60BrYWfkyDc6oWZ3dn2AAIwhgACP4joSx3_Koinx3-qPQQ"),
    ("Qarg‘ish", "Beso Xvedelidze", "BQACAgIAAxkBAAIB72q7xgJz3uLF5kdq_LUp2PhJXenxAAIxNgACg4soS0qDZl4kG1pePQQ"),
    ("Oq tanli sardor", "Mayn Rid", "BQACAgIAAxkBAAIB8Wq7xgKKAAHvXMxdVx3SdOK7LyrPxAAC4CkAAqrcuUu3B_kY2DWJFT0E"),
    ("Yo‘qotgan kalit", "Agata Kristi", "BQACAgIAAxkBAAIB9Gq7xgJMvoJKTCxTafdXZ-1iQ_viAAKoMQACbXjgSzcb0QpV4kBlPQQ"),
    ("Lo‘li qiz", "Agata Kristi", "BQACAgIAAxkBAAIB9Wq7xgITuPXiZHpbt2q1TueFCR6cAAKuMQACbXjgS_dBORB3JswoPQQ"),
    ("Qallobning qismati", "Ben Pastor", "BQACAgIAAxkBAAIB62q7xgLQGILndHxJ5lpmxLWGauTQAAIGMwACg4soSyGAFs8lN06JPQQ"),
]

# ======================================================================
#  3-QISM: HAMMA KITOBLARNI BITTA BAZAGA YIG'ISH
# ======================================================================
def md_to_html(text: str) -> str:
    """**qalin** -> <b>qalin</b>"""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def plain_first_line(caption: str) -> str:
    """Tugma uchun: sarlavhaning birinchi qatori, ** belgisiz."""
    return caption.split("\n")[0].replace("**", "").strip()


# BOOKS[kalit] = {"file_id", "caption" (HTML), "button" (tugma matni)}
BOOKS: dict[str, dict] = {}

for _key, _data in RAW_BOOKS.items():
    BOOKS[_key] = {
        "file_id": _data["file_id"],
        "caption": md_to_html(_data["caption"]),
        "button": plain_first_line(_data["caption"]),
    }

ROMANTIK_KITOBLAR = [
    ("Xatolaring bilan sevaman", "", "BQACAgIAAxkBAAICiWq-DgSnfeS7RFwTgOXVphAPVtsZAAJGbAACF6WISXC4NMJ6kQo_PQQ"),
    ("Yulduzlar aybdor", "John Green", "BQACAgIAAxkBAAICkmq-DgTc8A5CgBe5Fl_MPMtingi1AAIccQACnPp4SO0m_1GtiDF5PQQ"),
    ("Ishq imtihoni", "", "BQACAgIAAxkBAAICnGq-DgTxzowHbJd6xrfKWIcW5jrFAAJ6dQACt9SBS0imbkYheLYpPQQ"),
    ("Ishq imtihoni 2", "", "BQACAgIAAxkBAAICnWq-DgQ7njqr6wkPu66-un2YX9nZAALlgQACHgQJSKMFTI8swsrDPQQ"),
    ("Seni sevaman dema, sev!", "", "BQACAgIAAxkBAAICoWq-DgSkxb3kFn_YvwUYcFcBh-TtAAIhIAACHVkAAUuWjDDL4j4t3D0E"),
    ("Qorako'z Majnun", "", "BQACAgIAAxkBAAICmGq-DgR2QYONrEZXeuCIZyZxB-gpAAIxgQACHgQJSOWKGhxVekmcPQQ"),
    ("Qarzga olingan umr", "Erix Mariya Remark", "BQACAgIAAxkBAAICrGq-DgSSzKSeW76knG4V1xzwMNJTAAKZeAACSwNxS77U7Malg-WRPQQ"),
    ("Muhabbat masofasi", "", "BQACAgIAAxkBAAICuGq-DgQbFfonj3P_EEgUuK7OMhQJAALiWAACVshJSJ4jBhuRVxhlPQQ"),
    ("Meni unutma, senga sevishni men o'rgatdim", "", "BQACAgIAAxkBAAICyGq-DgS47aL6CX24pS-A5rkOLI_NAAIbdwACXQABkUuQlMqsbZSuWD0E"),
    ("To'siqlarga qaramay sevdik", "Mirach Chag'riy Oqtosh", "BQACAgIAAxkBAAIC2Wq-DgS1i7byVD5qOrlC3dbeiY1GAAKXDgACooqYSNBeEZgITjjpPQQ"),
    ("Senga o'xshashi yo'q", "Mirach Chag'riy Oqtosh", "BQACAgIAAxkBAAICzGq-DgSMFcFTkYiPStjVZOmorGv6AAIYgwACOy3hSC-K_cc9DQVePQQ"),
    ("Bir muhabbat tarixi", "", "BQACAgIAAxkBAAIC02q-DgQaqi5Z9oT0nVhxrQfNXJr-AAJoPQACVDVQS00fQ850YA4IPQQ"),
    ("Romeo va Julietta", "Vilyam Shekspir", "BQACAgIAAxkBAAIC1Gq-DgRSbMKeT-Kf5A8lsmc9G-fqAAJYAAMrVKBJA_ejcf_N9MU9BA"),
    ("Yevgeniy Onegin", "Aleksandr Pushkin", "BQACAgIAAxkBAAICkGq-DgTJLGwHyNpslzcxvCAAAUJQwwACn2kAApppoUlxsSxeP_u_UD0E"),
    ("Ishqqa oid 40 qoida", "Elif Shafak", "BQACAgIAAxkBAAICzWq-DgTxfIrzOkuH640AARhuLLny3gACeXIAArm3MUpMgV1hWXvm1j0E"),
]

TARIXIY_KITOBLAR = [
    ("O'zbekiston tarixi", "", "BQACAgIAAxkBAAIDNmq-EbD8PhGzW436dozTKharEF_FAAKkJQACEMjYSv2y7PT-N0mbPQQ"),
    ("O'zbekiston tarixi (2-nusxa)", "", "BQACAgIAAxkBAAIDPmq-EbCPjtHcjuoxNTbphWycpvz2AALYJQACEMjYSpvpf-vr3RyuPQQ"),
    ("O'zbekiston tarixi 2", "", "BQACAgIAAxkBAAIDPWq-EbC1Qw_cSUizzkzzYJsTqQTlAALPJQACEMjYSt08bc98P5D4PQQ"),
    ("O'zbekiston tarixi", "Erbo'tayeva, 2011", "BQACAgIAAxkBAAIDN2q-EbAvv4k0q6XfviWex3vZHPF9AAKmJQACEMjYSpNhlxTHT8fIPQQ"),
    ("O'zbekiston tarixi", "Sodiqov, 2012", "BQACAgIAAxkBAAIDOWq-EbBO6O2irmHh1bUDYhjCtfI_AAKwJQACEMjYSiIR6R2AdXoHPQQ"),
    ("O'zbekiston tarixi", "Karimov", "BQACAgIAAxkBAAIDOGq-EbBu2mhKwEdavCF1bGajXezrAAKnJQACEMjYSoBv-0UCttFGPQQ"),
    ("O'zbekiston tarixi (Namangan)", "", "BQACAgIAAxkBAAIDPGq-EbDjP4MSNrJPrnaCHXdrkMAyAAKzJQACEMjYShKVH64VzuKNPQQ"),
    ("O'zbekiston tarixi, 1-qism", "", "BQACAgIAAxkBAAIDO2q-EbCdbcDLfwpe82erlV3d5d9qAAKyJQACEMjYStwDhCX2Uu6uPQQ"),
    ("O'zbekiston tarixi (leksiyalar)", "", "BQACAgIAAxkBAAIDOmq-EbAWp98oZaIgCMDCPBVsb5oxAAKxJQACEMjYSpB-NbTWcwljPQQ"),
    ("O'zbekiston tarixi (darslik)", "Murtazoyeva", "BQACAgIAAxkBAAIDQ2q-EbD2QLCSVyoqfJGH9HPhQNuwAAJ1JgACEMjYSowhgQEDPpuvPQQ"),
    ("O'zbekiston tarixi. Davlat va jamiyat taraqqiyoti", "", "BQACAgIAAxkBAAIDQGq-EbBZbyAAAcURsklCssk7bHygtAACJiYAAhDI2EqY-KDe9iDY6T0E"),
    ("O'zbekistonning yangi tarixi. 1-kitob", "", "BQACAgIAAxkBAAIDRGq-EbDihjdKxBiU7Agde7RQO4M_AAKKJgACEMjYSuXMvGwt14ckPQQ"),
    ("O'zbekistonning yangi tarixi. 2-kitob", "", "BQACAgIAAxkBAAIDRWq-EbDc6o8g7XFnYe9w58xuSJUnAAKOJgACEMjYSlzNJq4GNfCjPQQ"),
    ("To'rt asr oldingi Toshkent", "", "BQACAgIAAxkBAAIDg2q-EbD_cIsAAY_LCIkkJbTaz1ZqBAACDiIAAr5hqUjh7UdVae5Gnj0E"),
    ("Toshkent shahrining irrigatsiya shohobchalari", "", "BQACAgIAAxkBAAIDf2q-EbAMFu5fQFb6DGBefn8Y7MStAAIGIgACvmGpSK2btAvbktlePQQ"),
    ("Toshkentning yangi shahar qismi tarixi", "", "BQACAgIAAxkBAAIDe2q-EbA2MavAxLqLr11u-13Z-JEpAAIBIgACvmGpSHQSRKi-m3CyPQQ"),
    ("O'zbekistonning qadimiy mudofaa inshootlari tarixidan", "", "BQACAgIAAxkBAAIDQWq-EbBnyiF09NlAsh02T4V1lNDIAAJPJgACEMjYSgUz4CqD56DbPQQ"),
    ("O'zbek xalqining qadimiy e'tiqod va marosimlari", "", "BQACAgIAAxkBAAIDQmq-EbCLQ1h5Zkjv9ZEwuMjUtGuKAAJjJgACEMjYSnaq5ONGzkl-PQQ"),
    ("O'zbeklar turmush tarzi va madaniyati", "I. Jabborov, 2003", "BQACAgIAAxkBAAIDc2q-EbDd4DS1r7adMpAQcvR7cAPdAAKZHAAC8SLpSqGbGRNJiitRPQQ"),
    ("Markaziy Osiyo xalqlari tarixshunosligi", "A. Doniyorov, 2020", "BQACAgIAAxkBAAIDP2q-EbDwR_1LrmcUMli8tYRHPT8CAAIgJgACEMjYSlWcIEkmDOvnPQQ"),
    ("Amir Temur tarixi", "", "BQACAgIAAxkBAAIDW2q-EbDXSuvrzwovoUQa0reccMVqAAJxHAAC8SLpSs_hMa9H1tU7PQQ"),
    ("Temurning Hindiston yurishi kundaligi", "Giyasiddin Ali", "BQACAgIAAxkBAAIDdmq-EbCSYii4TZiyT5U1GOSZZJ00AAJRFQACC4WoSb3evDGxdrzaPQQ"),
    ("Qarakhanid Roads to China", "", "BQACAgIAAxkBAAIDR2q-EbBjek_aNcD2iIvdAAEIcQAB6O4AArkgAAIQyOBKm_5cLNIHXEA9BA"),
    ("Buxoro toponimikasi", "", "BQACAgIAAxkBAAIDWWq-EbDwo8Y4HuWNlGx4aY2S-QR_AAJrHAAC8SLpSqbwiJ3Ak_ZRPQQ"),
    ("Tuhfai ahli Buxoro", "Mirzo Sirojiddin Hakim", "BQACAgIAAxkBAAIDdGq-EbB6CTaYpkA2otZoOAwgvkX_AAKOHwACB9gBS2dH1NWPqPGLPQQ"),
    ("Tadqiqoti arki Buxoro", "", "BQACAgIAAxkBAAIDdWq-EbDle8Bv7tkYigQPBBDwFlUJAAKYHwACB9gBSw16PdiQIFnzPQQ"),
    ("Quqon nazmiy manbalar", "", "BQACAgIAAxkBAAIDhmq-EbBD79wgrDx73PQyXy33KeA9AAIaIgACWt3YSLYUFjmHLgTLPQQ"),
    ("Abdulla Avloniy", "", "BQACAgIAAxkBAAIDUmq-EbCt3gLHn2DMYMmPvlREZZYIAAI3GQACVz5AS0iNd94Ra--2PQQ"),
    ("Mahmudxo'ja Behbudiy", "", "BQACAgIAAxkBAAIDVmq-EbAWjGel9uIQJCoffyzw0DxsAAI7GQACVz5ASxLs0DhInp8EPQQ"),
    ("Abdulhamid Cho'lpon", "", "BQACAgIAAxkBAAIDUWq-EbALNcl3UhD-dcztj5RBAfGhAAI1GQACVz5AS_qbGgMU72KAPQQ"),
    ("Abdurauf Fitrat", "", "BQACAgIAAxkBAAIDVGq-EbDfeGUnHRiXTDUlTe5ruN4dAAI5GQACVz5AS6i3M4eakSS-PQQ"),
    ("Munavvar Qori Abdurashidxonov", "", "BQACAgIAAxkBAAIDV2q-EbDAVEDjaOFUjKr6b4lffg51AAI8GQACVz5AS3PSqwxOKbyhPQQ"),
    ("G'. Zafariy", "", "BQACAgIAAxkBAAIDWGq-EbC1tVQByKSmxFtzGVi-bq0bAAI9GQACVz5AS2aNhJyYxlxVPQQ"),
]

DINIY_KITOBLAR = [
    ("Saodat asri qissalari. 1-kitob", "", "BQACAgIAAxkBAAICr2q-DgSe8cCBSQS_fURSD6tCFtw5AAK8AANwF5hK5w0P54auFBc9BA"),
    ("Saodat asri qissalari. 2-kitob", "Ahmad Lutfiy Qozonchi", "BQACAgIAAxkBAAID0Wq-FYRZCMRGMKVU1m4YHPx_8jCbAAJhAANfM6oOft2dne0OP4I9BA"),
    ("Saodat asri qissalari. 3-kitob", "", "BQACAgIAAxkBAAICsWq-DgQ7MOGoxQABXxYf4Hr9dyu0mwACvAoAApeR4Eg6EArnSxUo8D0E"),
    ("Saodat asri qissalari. 4-kitob", "", "BQACAgIAAxkBAAICsmq-DgQwy8wVuXQgdoLB3Bd23E3yAAKVCQACx2qQSPJGv4gEo5KEPQQ"),
    ("Allohga qoching. 1-qism", "", "BQACAgIAAxkBAAICu2q-DgTTWTGR3vJHZXG03pBFMcWOAAJcfQACI9hxSQVyWvf1bpn5PQQ"),
    ("Allohga qoching. 2-qism", "", "BQACAgIAAxkBAAICvGq-DgQnPuPmB0tCYxEzQbZf69rYAAJifQACI9hxSWelUEeM9kmQPQQ"),
    ("Jannatga taklifnoma", "", "BQACAgIAAxkBAAIC2Gq-DgTF-MhwGDuFMrI4yY24-8igAAIyGQACFrlxSUgRroK20yJAPQQ"),
    ("Nafs tarbiyasi (Riyozatun nafs)", "Imom G'azzoliy", "BQACAgIAAxkBAAIC22q-DgSgtvXPz5S8LMvO2FSGzXqBAALxgQAC5j_QSEFUrGwfOMYRPQQ"),
]

GENRE_PAGE_SIZE = 10
GENRES: dict[str, dict] = {}   # kod -> {"title": ..., "keys": [...]}
GENRE_BY_CAT = {"cat_detektiv": "det", "cat_romantik": "rom", "cat_tarixiy": "tar", "cat_muqaddas": "din"}


def add_genre(code: str, emoji: str, title: str, books: list) -> None:
    keys = []
    for i, (book_title, author, fid) in enumerate(books):
        key = f"{code}_{i}"
        caption = f"{emoji} <b>{html.escape(book_title)}</b>"
        button = f"{emoji} {book_title}"
        if author:
            caption += f"\n<i>Muallif: {html.escape(author)}</i>"
            button += f" — {author}"
        BOOKS[key] = {"file_id": fid, "caption": caption, "button": button}
        keys.append(key)
    keys.sort(key=lambda k: BOOKS[k]["button"].lower())  # alifbo tartibida
    GENRES[code] = {"title": title, "keys": keys}


add_genre("det", "🕵️", "🕵️ <b>Detektiv janridagi kitoblar</b>", DETEKTIV_KITOBLAR)
add_genre("rom", "❤️️", "❤️ <b>Romantik kitoblar</b>", ROMANTIK_KITOBLAR)
add_genre("tar", "📜", "📜 <b>Tarixiy kitoblar</b>", TARIXIY_KITOBLAR)
add_genre("din", "📖", "📖 <b>Diniy kitoblar</b>", DINIY_KITOBLAR)


# ======================================================================
#  4-QISM: MENYULAR
# ======================================================================
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📚 Kitob katalogi"), KeyboardButton(text="🎧 Audiokitoblar")],
        [KeyboardButton(text="⭐ Sevimlilar"), KeyboardButton(text="🕘 Tarix")],
        [KeyboardButton(text="👤 Profil"), KeyboardButton(text="🔝 Eng ko'p o'qilgan kitoblar")],
        [KeyboardButton(text="✍️ Taklif va shikoyatlar"), KeyboardButton(text="🔍 Qidiruv")],
        [KeyboardButton(text="ℹ️ Bot haqida"), KeyboardButton(text="🎮 O'yin")],
    ],
    resize_keyboard=True,
)

catalog_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🏫 Maktab darsliklari", callback_data="cat_maktab")],
        [InlineKeyboardButton(text="🧸 Maktabgacha ta'lim", callback_data="cat_maktabgacha")],
        [InlineKeyboardButton(text="🇬🇧 Ingliz tili darajalari", callback_data="cat_ingliz")],
        [
            InlineKeyboardButton(text="🕵️ Detektiv", callback_data="cat_detektiv"),
            InlineKeyboardButton(text="❤️ Romantik", callback_data="cat_romantik"),
        ],
        [
            InlineKeyboardButton(text="📜 Tarixiy", callback_data="cat_tarixiy"),
            InlineKeyboardButton(text="📖 Diniy kitoblar", callback_data="cat_muqaddas"),
        ],
    ]
)

maktab_classes_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text=f"{n}-sinf", callback_data=f"class_{n}") for n in (1, 2, 3)],
        [InlineKeyboardButton(text=f"{n}-sinf", callback_data=f"class_{n}") for n in (7, 8, 9)],
        [InlineKeyboardButton(text=f"{n}-sinf", callback_data=f"class_{n}") for n in (10, 11)],
    ]
)


def keys_for_class(n: int) -> list[str]:
    keys = [k for k in BOOKS if k.split("_")[0] == str(n)]
    if n == 11:  # 10-11-sinf umumiy darsliklari 11-sinfda ham chiqsin
        keys += [k for k in BOOKS if k.startswith("10_11_")]
    return keys


def books_keyboard(keys: list[str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=BOOKS[k]["button"], callback_data=f"book_{k}")]
            for k in keys
        ]
    )


preschool_menu = books_keyboard([k for k in BOOKS if k.startswith("pre_")])
english_menu = books_keyboard([k for k in BOOKS if k.startswith("nav_")])


def genre_keyboard(code: str, page: int) -> InlineKeyboardMarkup:
    keys = GENRES[code]["keys"]
    total_pages = max(1, (len(keys) + GENRE_PAGE_SIZE - 1) // GENRE_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * GENRE_PAGE_SIZE
    rows = [
        [InlineKeyboardButton(text=BOOKS[k]["button"], callback_data=f"book_{k}")]
        for k in keys[start:start + GENRE_PAGE_SIZE]
    ]
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"gpage_{code}_{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"gpage_{code}_{page + 1}"))
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ======================================================================
#  AUDIOKITOBLAR
# ======================================================================
# Har bir audiokitob: nomi, muallifi va qismlari (qism nomi, file_id).
# Bitta faylli kitobda faqat bitta qism yozing.
AUDIO_BOOKS = [
    {
        "title": '1-kitob. 01-Fil va Abobil qushlari',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID7Gq-F5XxWcfphLtssefQolz6aDK8AAIGAAOh9_BLlrk9m7s2pvo9BA'),
        ],
    },
    {
        "title": '1-kitob. 07-Bir qurbon - yuz qurbon',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID8mq-F5V2mEysZJOC_wTbY44DQnZSAAIMAAOh9_BLloWlFGVJ-rA9BA'),
        ],
    },
    {
        "title": '1-kitob. 28-Bilol Habashiy',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEB2q-F5Uu-QOhlGp9afRo2Z9BbEseAAIhAAOh9_BLcfVTDZEiFHc9BA'),
        ],
    },
    {
        "title": "2-kitob. 01-Oyning ikkiga bo'linishi",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEE2q-F5WCxDvbh5Cx_Yfq_6cKkvMYAAIuAAOh9_BLaeU8al13sMI9BA'),
        ],
    },
    {
        "title": "1-kitob. 05-Abdulmuttalibning mehr quchog'i",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID8Gq-F5XGjSy_KhDy80EL34u9_MgvAAIKAAOh9_BLZll2eixzvuk9BA'),
        ],
    },
    {
        "title": '1-kitob. 30-Amr ibn Hishom - Abu Jahl',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIECWq-F5U3E5EefrVW420cOIX76jlfAAIjAAOh9_BLNNG6Che76AQ9BA'),
        ],
    },
    {
        "title": '1-kitob. 14-Fijor urushi',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID-Wq-F5UtHoRiH5Yag4XDp9p2Wr5_AAITAAOh9_BLawSd1GPJL7s9BA'),
        ],
    },
    {
        "title": "3-kitob. 24-Handaq g'azoti",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIET2q-F5VOh-iPYe0_H2ASB_VXWo12AAJkAANRMPBL5NVYGbvnfe09BA'),
        ],
    },
    {
        "title": '1-kitob. 10-Bulutlarga qilingan ishora',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID9Wq-F5V02U3v7xksUGJQvzLK8pvJAAIPAAOh9_BLbqiczXruTxM9BA'),
        ],
    },
    {
        "title": "1-kitob. 26-Ochiq da'vat sari ilk odim",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEBWq-F5XbJNoILjCCUE40NJdpnb6GAAIfAAOh9_BLaQg28OyWVmM9BA'),
        ],
    },
    {
        "title": '1-kitob. 15-Sharafli ahdlashuv_2',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID-mq-F5Wc8i4w4YihO866ptkOcQPwAAIUAAOh9_BLPYZGaGyj_gE9BA'),
        ],
    },
    {
        "title": '2-kitob. 11-Abu Tolibning vafoti',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEHWq-F5XydFzoJdW1PWs4p19QvxC0AAI-AAOh9_BLRjuxfHGCBUU9BA'),
        ],
    },
    {
        "title": "1-kitob. 20-Ka'ba hakamligi",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID_2q-F5WE-_sKvI6HaZeHT4eX9hsIAAIZAAOh9_BLLiPb2PX4J209BA'),
        ],
    },
    {
        "title": '1-kitob. 23-Ukoz bozori',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEAmq-F5UZB0zI_gmVmOcW_Fy0_QABbgACHAADoffwS7_okKACPt1rPQQ'),
        ],
    },
    {
        "title": '1-kitob. 37-Habashiston sari',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEEGq-F5U6mUfg2BFaCNyNsteijMvmAAIqAAOh9_BLk0FFFVbrI_U9BA'),
        ],
    },
    {
        "title": '2-kitob. 13-Toif safari',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEH2q-F5XIvwl2Y3hQWLMESC3V_uw1AAJBAAOh9_BLPpoLgpMrXm89BA'),
        ],
    },
    {
        "title": '1-kitob. 19-Dardli bir ota',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID_mq-F5UBweE3w1zhWqmKIbZT6CgsAAIYAAOh9_BLymhZBqEzpTI9BA'),
        ],
    },
    {
        "title": "1_kitob_33_Jahannamni_qo'riqlaydigan",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEDGq-F5VC1mHeLDlTXAEjF0iYnZAgAAImAAOh9_BLkbdbOpVDL309BA'),
        ],
    },
    {
        "title": '1-kitob. 02-Mavlidi Nabaviy',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID7Wq-F5XPawE9hHat1mocpo3WcYFMAAIHAAOh9_BLyVJg52VrJCo9BA'),
        ],
    },
    {
        "title": '1-kitob. 24-Intizor kutilgan tong',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEA2q-F5X15Q8aKkTHfszyfxRcVHOOAAIdAAOh9_BL_X3HB1jDqfM9BA'),
        ],
    },
    {
        "title": '2-kitob. 16-Yasrib iymon qarorgohiga aylanadi',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEImq-F5ViZKbKCUnLFkWCQerTMYGGAAJaAAOh9_BLp08Y0tpHU3c9BA'),
        ],
    },
    {
        "title": '1-kitob. 36-Maxsus duo',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIED2q-F5V5xYrbq59MdoWXxqfELvpZAAIpAAOh9_BLUGtpiDKdWHU9BA'),
        ],
    },
    {
        "title": '1-kitob. 25-Sobuqini avvaliyn',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEBGq-F5UCinKyiPgawR7sveiNZSOaAAIeAAOh9_BL9OG3ifHpR3A9BA'),
        ],
    },
    {
        "title": '1-kitob. 11-Shom safari',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID9mq-F5UsnGkU8rJvf9lyqhusskwOAAIQAAOh9_BLJ6RYvOOyX009BA'),
        ],
    },
    {
        "title": '1-kitob. 08-Azim daraxtning qulashi',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID82q-F5WnhPFQmyA35yYZ7Cpcc-uvAAINAAOh9_BLCgwlycfluPY9BA'),
        ],
    },
    {
        "title": '2-kitob. 04-Yakkama-yakka olishuv',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEFmq-F5VJpxIESvQPvYBIlLanGS8qAAIxAAOh9_BL2Rw4weWFcm49BA'),
        ],
    },
    {
        "title": "1-kitob. 35-Hazrati Hamzaning musulmon bo'lishi",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEDmq-F5UdIg_i2bPK9h-kOnnL79wfAAIoAAOh9_BLzFM0YAsbtDw9BA'),
        ],
    },
    {
        "title": "1-kitob. 22-Haq din yo'lida",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEAWq-F5UNvuXFdhik5fB7yyf6RZpkAAIbAAOh9_BLAAH-x7j2yfwoPQQ'),
        ],
    },
    {
        "title": '1-kitob. 21-Salmon va yahudiy olimlari',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEAAFqvheVT-tL2usyaf3ETkjqzzpU5wACGgADoffwS40YMEBWT_9fPQQ'),
        ],
    },
    {
        "title": "2-kitob. 02-G'arazli istaklar",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEFGq-F5XFhoOGfsqQ99BMy1gXrAR3AAIvAAOh9_BLVNNbioL9kyM9BA'),
        ],
    },
    {
        "title": '1-kitob. 27-Nizo va qiynoqlar',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEBmq-F5XbksAMdBZrtsxgFAG3tTmfAAIgAAOh9_BL8S6QVddH4QY9BA'),
        ],
    },
    {
        "title": "2-kitob. 14-Isro va me'roj",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEIGq-F5W-8Roe2qitkDDU8iXw6BhSAAJKAAOh9_BLBbvQPD84J6c9BA'),
        ],
    },
    {
        "title": '2-kitob. 33-Abu Sufyonning savdo karvoni',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEM2q-F5UHJeQO3Y6DBqkBq4OpiPTnAAJvAAOh9_BLmcvTpX-yu-w9BA'),
        ],
    },
    {
        "title": '2-kitob. 05-Ashobi Kahf',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEF2q-F5UnZstUMXBe9rQv6-cw2NZrAAIyAAOh9_BLZr23rvXOxnM9BA'),
        ],
    },
    {
        "title": '1-kitob. 18-Jasur bola va kichkina mahbus',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID_Wq-F5WMRp2bLZHXNGKpNwABj75MdQACFwADoffwS1wPwWP_xIgZPQQ'),
        ],
    },
    {
        "title": "1-kitob. 03-Bani Sa'd yurtida",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID7mq-F5VrE8Hergtt20xB1H4jTGwCAAIIAAOh9_BLi7TK29Bcm-09BA'),
        ],
    },
    {
        "title": '1-kitob. 16-Salmon Forsiy',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID-2q-F5XbPebDvRKqwCKtLL-sZ_eXAAIVAAOh9_BLKaz26d-33Xo9BA'),
        ],
    },
    {
        "title": '1-kitob. 17-Xadichaning savdo karvoni',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID_Gq-F5WdYJhz3p4ym0FRP-Hpb7oUAAIWAAOh9_BLnIXYXcvkrpM9BA'),
        ],
    },
    {
        "title": '1-kitob. 09-Abu Tolib xonadonida',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID9Gq-F5XKSxBMOkxMtV8jfxWNTtRMAAIOAAOh9_BLYIvrsuCEYAQ9BA'),
        ],
    },
    {
        "title": '1-kitob. 13-Arslon bolasi',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID-Gq-F5WGMX0nhhBcWWofUSNHbuT4AAISAAOh9_BLXo8XD0JsV109BA'),
        ],
    },
    {
        "title": '1-kitob. 04-Abvoda qazilgan mozor',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAID72q-F5WX3TZHK88lhoCcBolHrsNeAAIJAAOh9_BLWLzJgndynWI9BA'),
        ],
    },
    {
        "title": '1-kitob. 32-Eskilardan qolgan afsona',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEC2q-F5WkMUvUpSJeuEdcJuVLtOiJAAIlAAOh9_BLguBenD-SQOw9BA'),
        ],
    },
    {
        "title": '1-kitob. 38-Favqulodda taklif',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEEWq-F5WhXX5S0-8HcF5QYWPWQsMBAAIrAAOh9_BL2FtDgUH6fP89BA'),
        ],
    },
    {
        "title": "1-kitob. 34-Vahiyning to'xtab qolishi",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEDWq-F5VRYF26Gr00cT5vXdun7z1HAAInAAOh9_BLUzluhcc_YqI9BA'),
        ],
    },
    {
        "title": '2-kitob. 06-Hazrati Muso va Hizr',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEGGq-F5Vc_QtPpQj5MjB6WGKZ1N08AAI0AAOh9_BLfyboZ8LkLMM9BA'),
        ],
    },
    {
        "title": '1-kitob. 31-Utba ibn Robia',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIECmq-F5U973bfBDHDDiapD9CrDBnNAAIkAAOh9_BLkwqLtlETOXM9BA'),
        ],
    },
    {
        "title": '2-kitob. 19-Rasululloh SAVning hijratlari',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEJWq-F5XRjIOWAmaplkIo--0FEGQwAAJdAAOh9_BLMg2DbYNKf749BA'),
        ],
    },
    {
        "title": '3-kitob. 04-Bani Qurayza yahudiylari',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEO2q-F5UqNQXUI8KJnK9pFAnmWwe8AAJQAANRMPBLQf5QMx9VLxI9BA'),
        ],
    },
    {
        "title": '2-kitob. 09-Til bilmas temirchi',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEG2q-F5URnIspiLWbCn6EU5hcvkCwAAI8AAOh9_BLmux-Q7DAe509BA'),
        ],
    },
    {
        "title": "3-kitob. 11-Uhud g'azotidan bir kun oldin",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEQmq-F5W8Vwuo4KVLesK1HENu1rNyAAJXAANRMPBLh55DvIXIf149BA'),
        ],
    },
    {
        "title": "3-kitob. 06-Saviq va G'atafon g'azotlari",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEPWq-F5XP86wHgwmsXo_UH59gChSGAAJSAANRMPBLldyNFHAZzD89BA'),
        ],
    },
    {
        "title": '2-kitob. 21-Quboda ilk masjid',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEJ2q-F5WShS938FsgB5d9Lufzns4_AAJgAAOh9_BLyK7wTlk1Wns9BA'),
        ],
    },
    {
        "title": '3-kitob. 07-Hazrati Usmonning Ummu Gulsumga uylanishi',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEPmq-F5UhTGK4htc8p6_SYqmmm4QTAAJTAANRMPBL03PxiMybZSk9BA'),
        ],
    },
    {
        "title": '2-kitob. 08-Azobli uch yil',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEGmq-F5Xar65g23AnlEhY4YyTF42aAAI6AAOh9_BLj_KsjSx8VBg9BA'),
        ],
    },
    {
        "title": "2-kitob. 20-Yasrib yo'lida",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEJmq-F5VHKlnyfOE5CEsKt_tL2B1PAAJeAAOh9_BLcDU1IqOTLdE9BA'),
        ],
    },
    {
        "title": '3-kitob. 20-Ummu Mihjan. Abu Salamaning vafoti',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIES2q-F5Ud5O4Z_jQxhAZTnxhJKygdAAJgAANRMPBLgFu3-HY_CMc9BA'),
        ],
    },
    {
        "title": '2-kitob. 15-Yasriblik ilk musulmonlar',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEIWq-F5WpfFZl8PQ-HD69G1jVZTbNAAJTAAOh9_BL3fduUgKsl7Y9BA'),
        ],
    },
    {
        "title": "2-kitob. 37-Asirlar va o'ljalar",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEN2q-F5WC2o9-EN-3lNPZX-uHSGH9AAJ0AAOh9_BLS5ycuUGEdUE9BA'),
        ],
    },
    {
        "title": '2-kitob. 10-Shoir qanday aldandi',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEHGq-F5XrN6GwCtDUT7QKOW2Vi149AAI9AAOh9_BLeWPajIz-sDg9BA'),
        ],
    },
    {
        "title": "3-kitob. 15-Hamroul Asad g'azoti",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIERmq-F5XoqAs_VU4_XCB1M-kSUxQ-AAJbAANRMPBLV4J2mXqd_Wk9BA'),
        ],
    },
    {
        "title": "2-kitob. 26-Hazrati Alining Fotimaga sovchi qo'yishi",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIELGq-F5XgDK2IUUvalWjT3K0Sa3TLAAJoAAOh9_BLyeCNZL-8iJ09BA'),
        ],
    },
    {
        "title": "3-kitob. 25-Bani Qurayza g'azoti",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEjWq-F-FCBrkSnRvzor3ChOAlYLqEAAJlAANRMPBLGQ84uApnINU9BA'),
        ],
    },
    {
        "title": "3-kitob. 28-Davmatul Jandal g'azoti",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEkGq-F-GG02TyZhADpU3BDyL6U0JhAAJoAANRMPBLDJmisAkWbSU9BA'),
        ],
    },
    {
        "title": '3-kitob. 34-Hudaybiya safari',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIElmq-F-EUak4s-cHPFSlqupcQp6vuAAJuAANRMPBLUJf9qQe3tz89BA'),
        ],
    },
    {
        "title": '3-kitob. 26-Rasululloh SAVning Zaynab onamizga uylanishlari',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEjmq-F-GT5IHfMw5MHmGghgTRYUjrAAJmAANRMPBL4FapewHRZhg9BA'),
        ],
    },
    {
        "title": '3-kitob. 37-Hiraqlga maktub',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEmWq-F-Ey3sLyPtyo5qkOO2mCyZJqAAJxAANRMPBLHO0Jxovqn5E9BA'),
        ],
    },
    {
        "title": '4-kitob. 15 - Safar xotiralari',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEqWq-F-HUYuo9WufdPMK6usMFwKcLAAKBAANRMPBL0kx_dmFK0oU9BA'),
        ],
    },
    {
        "title": '3-kitob. 30-Bani Mustaliq safari',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEkmq-F-HlvjFlWCpxtix98hcpeamgAAJqAANRMPBLL79lC5UiVrM9BA'),
        ],
    },
    {
        "title": '4-kitob. 05 - Sulaym qabilasi',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEn2q-F-H5JMmRbvY6GCbN2Q5LgXNRAAJ3AANRMPBLKfmwExDM3jc9BA'),
        ],
    },
    {
        "title": '3-kitob. 38-Muqovqis va Kisroga maktub',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEmmq-F-Fd6i4c58V3ZXaEtzjkdq0yAAJyAANRMPBLOlTQ-eAFT_o9BA'),
        ],
    },
    {
        "title": '4-kitob. 09 - Janoza namozi. Qori Salim',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEo2q-F-HSSkb82-VOkkYzRBHxzmzYAAJ7AANRMPBLGjghO0sJTAk9BA'),
        ],
    },
    {
        "title": '4-kitob. 26 - Hajning farz etilishi',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEtGq-F-GMyJ9PBFvonEEtnphfUFBFAAKMAANRMPBLYadk645Pbi49BA'),
        ],
    },
    {
        "title": '3-kitob. 35-Ummu Habiba onamiz r.a.',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEl2q-F-GJDfu2bs4La03UkBoAASfEFwACbwADUTDwS5scbGHc8diuPQQ'),
        ],
    },
    {
        "title": '3-kitob. 27-Aroqning harom qilinishi',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEj2q-F-GMa8U6nYHRK8bu44JvEkakAAJnAANRMPBLiHp5lqoc3Nk9BA'),
        ],
    },
    {
        "title": "3-kitob. 31-Hazrati Oyishaga bo'hton",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEk2q-F-HvEw_bFkP8saNrTyWWYWo8AAJrAANRMPBLP5BuRXwBDis9BA'),
        ],
    },
    {
        "title": "3-kitob. 29-Abdulloh ibn Mas'ud",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEkWq-F-HIdOquZT3hjbXnwO-bsuTIAAJpAANRMPBLECpY2-i4y2o9BA'),
        ],
    },
    {
        "title": '4-kitob. 12 - Mu\'ta g\'azoti',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEpmq-F-FXG7iamokIL-TwuqeOjrF0AAJ-AANRMPBL5VVR-gvbss49BA'),
        ],
    },
    {
        "title": '4-kitob. 10 - Sayful-bahr safari',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEpGq-F-Htha9W2RFo6ghee9ADoNDrAAJ8AANRMPBLY9ViXKSK72w9BA'),
        ],
    },
    {
        "title": '4-kitob. 01 - Xola. Xansa. Abu Umayr',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEm2q-F-FFGCuEKmHuvNPBfbRo7VCOAAJzAANRMPBLsuhihXRzqlg9BA'),
        ],
    },
    {
        "title": '4-kitob. 06 - Hazrati Safiyyaga taskin',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEoGq-F-HWnfqUHQptMjHXRiLjk2wpAAJ4AANRMPBLHTh0f26kl3g9BA'),
        ],
    },
    {
        "title": '4-kitob. 13 - Rasululloh SAVga suiqasd. Minbar',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEp2q-F-G0vgE06Aoj-ziUtTmuRSR7AAJ_AANRMPBLIpM7fooqGLk9BA'),
        ],
    },
    {
        "title": "4-kitob. 07 - Yomg'ir so'rash",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEoWq-F-HxNj2hSOtqk6_0V7DoqTmQAAJ5AANRMPBLyWblTSWymLw9BA'),
        ],
    },
    {
        "title": '4-kitob. 02 - Umra qazosi',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEnGq-F-FelPhh__mxMwyquvcLbX3ZAAJ0AANRMPBLN4WXrebfRyg9BA'),
        ],
    },
    {
        "title": "4-kitob. 08 - Zotus-salosil g'azoti",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEomq-F-GC2XDY6MmUSvxl_tJVglb0AAJ6AANRMPBLQTOM0uuZ2rk9BA'),
        ],
    },
    {
        "title": '4-kitob. 18 - Fath xutbasi',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIErGq-F-Gf18IRtMAzj5UB6dHuPKVMAAKEAANRMPBLKLF8bHX7rrU9BA'),
        ],
    },
    {
        "title": "4-kitob. 04 - Tamimliklarning musulmon bo'lishi",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEnmq-F-GIiYEx03_skHXtxWRJ6dgYAAJ2AANRMPBL5WBkJSML7sY9BA'),
        ],
    },
    {
        "title": '3-kitob. 32-Juvayriya binti Horis r.a.',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIElGq-F-FK3pd9gWaqHjIF7JF7-0lqAAJsAANRMPBLkcf79w5ZDfE9BA'),
        ],
    },
    {
        "title": '4-kitob. 14 - Makka fathining boshlanishi',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEqGq-F-H_5EbjHu5g33wE1L_-lVYhAAKAAANRMPBLYYtceXTRz7g9BA'),
        ],
    },
    {
        "title": '4-kitob. 28 - Sut ziyofati',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEtmq-F-EQ412WoRyR7ro4-_Z0IM-zAAKOAANRMPBLXPwHyYxlDLg9BA'),
        ],
    },
    {
        "title": '4-kitob. 23 - Kichkina mehmon',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEsWq-F-F_SHnHCapLJXShPp6tEvjsAAKJAANRMPBLLeclpxLCkZQ9BA'),
        ],
    },
    {
        "title": '7. Tasadduq Yo Rasululloh - Buyuk alomat',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEyWq-F-FjcD7slJGu6cOw_yX1OBLmAAIxAQACq8dBS735yvNNixkcPQQ'),
        ],
    },
    {
        "title": '10.   Tasadduq Yo Rasululloh - Zayd ibn Horisa',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEzGq-F-GPgQPsBfqc9-Sr3xr8LM_QAAI0AQACq8dBS-KjuSoIReKXPQQ'),
        ],
    },
    {
        "title": "4-kitob. 21 - Toif qamali. Hunayn o'ljalari",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEr2q-F-ESo-tq9ne-_zkLPGNYC6adAAKHAANRMPBLgNhhe1uLZGs9BA'),
        ],
    },
    {
        "title": '4-kitob. 36 - Tabukka qatnashmagan 3 kishi',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEvmq-F-G5jsVuPTRwie3D2I_C9NsIAAKWAANRMPBLvl_upkOw8d89BA'),
        ],
    },
    {
        "title": '1. Muqaddima',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEw2q-F-Ff24GOnd7de_hMV9WgkuPEAAJUBAACQGrgStrD5WGPE2DoPQQ'),
        ],
    }
]


# ======================================================================
#  5-QISM: HANDLERLAR  (bu qismni fayl OXIRIGA, AUDIO_BOOKS dan keyin qo'shing)
# ======================================================================
import difflib
import hashlib
import logging
import time
from datetime import timedelta

from aiogram import BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup, default_state
from aiogram.types import BotCommand, BufferedInputFile, CallbackQuery, Message

logging.basicConfig(level=logging.INFO)

# ----------------------------------------------------------------------
#  Qo'shimcha baza jadvallari
# ----------------------------------------------------------------------
def db_exec(sql, params=()):
    conn = db_connect()
    try:
        with conn:
            return conn.execute(sql, params).lastrowid
    finally:
        conn.close()


def db_all(sql, params=()):
    conn = db_connect()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def db_one(sql, params=()):
    rows = db_all(sql, params)
    return rows[0] if rows else None


def now_iso():
    return datetime.utcnow().isoformat(timespec="seconds")


def init_db_extra():
    conn = db_connect()
    try:
        with conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, kind TEXT NOT NULL,
                text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', admin_reply TEXT,
                created_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, query TEXT NOT NULL,
                results INTEGER NOT NULL, created_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS book_stats (
                item_type TEXT NOT NULL, item_id TEXT NOT NULL, title TEXT NOT NULL,
                cnt INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(item_type, item_id))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, name TEXT NOT NULL,
                file_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)""")
        try:
            with conn:
                conn.execute("ALTER TABLE users ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # ustun allaqachon bor
    finally:
        conn.close()


init_db_extra()

# ----------------------------------------------------------------------
#  Audio bazasi (barqaror ID: birinchi file_id dan hash)
# ----------------------------------------------------------------------
def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


AUDIO_MAP: dict[str, dict] = {}
for _a in AUDIO_BOOKS:
    AUDIO_MAP[hashlib.md5(_a["parts"][0][1].encode()).hexdigest()[:8]] = _a
AUDIO_IDS = sorted(AUDIO_MAP, key=lambda i: natural_key(AUDIO_MAP[i]["title"]))
AUDIO_PAGE_SIZE = 10


def audio_keyboard(page: int) -> InlineKeyboardMarkup:
    total = max(1, (len(AUDIO_IDS) + AUDIO_PAGE_SIZE - 1) // AUDIO_PAGE_SIZE)
    page = max(0, min(page, total - 1))
    chunk = AUDIO_IDS[page * AUDIO_PAGE_SIZE:(page + 1) * AUDIO_PAGE_SIZE]
    rows = [[InlineKeyboardButton(text="🎧 " + AUDIO_MAP[i]["title"][:55], callback_data=f"audio_{i}")] for i in chunk]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"apage_{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total}", callback_data="noop"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"apage_{page + 1}"))
    rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ----------------------------------------------------------------------
#  Yordamchi funksiyalar
# ----------------------------------------------------------------------
def item_title(item_type: str, item_id: str):
    if item_type == "book":
        b = BOOKS.get(item_id)
        return b["button"] if b else None
    a = AUDIO_MAP.get(item_id)
    return a["title"] if a else None


def with_back(kb: InlineKeyboardMarkup, back_cb: str = "cat_back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=list(kb.inline_keyboard) + [[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_cb)]]
    )


async def safe_edit(c: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None):
    try:
        await c.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass  # "message is not modified" va shunga o'xshashlar


async def notify_admins(bot: Bot, text: str, reply_markup=None):
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, text, reply_markup=reply_markup)
        except TelegramAPIError:
            pass


def bump_stat(item_type, item_id, title):
    db_exec(
        "INSERT INTO book_stats(item_type,item_id,title,cnt) VALUES(?,?,?,1) "
        "ON CONFLICT(item_type,item_id) DO UPDATE SET cnt=cnt+1, title=excluded.title",
        (item_type, item_id, title),
    )


async def send_item(bot: Bot, user_id: int, item_type: str, item_id: str) -> bool:
    title = item_title(item_type, item_id)
    if not title:
        return False
    kb = favorite_button(item_type, item_id, title, user_id)
    try:
        if item_type == "book":
            b = BOOKS[item_id]
            await bot.send_document(user_id, b["file_id"], caption=b["caption"], reply_markup=kb)
        else:
            a = AUDIO_MAP[item_id]
            parts = a["parts"]
            for n, (pname, fid) in enumerate(parts):
                cap = f"🎧 <b>{html.escape(a['title'])}</b>"
                if a.get("author"):
                    cap += f"\n<i>{html.escape(a['author'])}</i>"
                if len(parts) > 1:
                    cap += f"\n{html.escape(pname)} ({n + 1}/{len(parts)})"
                markup = kb if n == len(parts) - 1 else None
                try:
                    await bot.send_audio(user_id, fid, caption=cap, reply_markup=markup)
                except TelegramBadRequest:
                    await bot.send_document(user_id, fid, caption=cap, reply_markup=markup)
    except TelegramAPIError as e:
        logging.warning("Fayl yuborilmadi %s/%s: %s", item_type, item_id, e)
        await notify_admins(bot, f"⚠️ <b>Fayl yuborilmadi</b>\n{html.escape(title)}\n<code>{item_type}/{html.escape(item_id)}</code>\n{html.escape(str(e))}")
        return False
    add_history(user_id, item_type, item_id, title)
    bump_stat(item_type, item_id, title)
    return True


# ----------------------------------------------------------------------
#  Qidiruv
# ----------------------------------------------------------------------
def norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[‘’`ʻʼ´′']", "", s)       # o', o‘, oʻ ... hammasi bir xil bo'lsin
    s = s.replace("-", " ").replace("_", " ")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


SEARCH_INDEX: list[tuple[str, str, str, str]] = []   # (tur, id, ko'rinadigan nom, normallashgan matn)
for _k, _b in BOOKS.items():
    SEARCH_INDEX.append(("book", _k, "📚 " + _b["button"], norm(_b["button"])))
for _i, _a in AUDIO_MAP.items():
    SEARCH_INDEX.append(("audio", _i, "🎧 " + _a["title"], norm(_a["title"] + " " + _a.get("author", ""))))
SEARCH_WORDS = {w for *_, text in SEARCH_INDEX for w in text.split()}


def _match(tokens: list[str]):
    scored = []
    for t, i, label, text in SEARCH_INDEX:
        hit = sum(1 for w in tokens if w in text)
        if hit:
            scored.append((hit, t, i, label))
    full = [x for x in scored if x[0] == len(tokens)]
    if full:
        return [(t, i, l) for _, t, i, l in full], True
    if len(tokens) > 1 and scored:
        scored.sort(key=lambda x: -x[0])
        return [(t, i, l) for _, t, i, l in scored], False
    return [], False


def search_items(query: str, limit: int = 30):
    tokens = norm(query).split()
    if not tokens:
        return [], False
    res, exact = _match(tokens)
    if not res:  # imlo xatosi bo'lishi mumkin
        fixed = []
        for w in tokens:
            m = difflib.get_close_matches(w, SEARCH_WORDS, n=1, cutoff=0.75)
            fixed.append(m[0] if m else w)
        if fixed != tokens:
            res, exact = _match(fixed)
    return res[:limit], exact


# ----------------------------------------------------------------------
#  Middleware: foydalanuvchini yozib borish + spamdan himoya
# ----------------------------------------------------------------------
def touch_user(u):
    now = now_iso()
    db_exec(
        "INSERT INTO users(user_id,username,first_name,last_name,joined_at,last_seen) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, "
        "last_name=excluded.last_name, last_seen=excluded.last_seen, blocked=0",
        (u.id, u.username or "", u.first_name or "", u.last_name or "", now, now),
    )


class UserAndFlood(BaseMiddleware):
    def __init__(self, gap: float = 0.5):
        self.gap = gap
        self.last: dict[int, float] = {}

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user and not user.is_bot:
            t = time.monotonic()
            if user.id not in ADMIN_IDS and t - self.last.get(user.id, 0) < self.gap:
                if isinstance(event, CallbackQuery):
                    await event.answer()
                return
            if len(self.last) > 20000:
                self.last.clear()
            self.last[user.id] = t
            touch_user(user)
        return await handler(event, data)


dp.message.middleware(UserAndFlood())
dp.callback_query.middleware(UserAndFlood())

# ----------------------------------------------------------------------
#  Holatlar (FSM)
# ----------------------------------------------------------------------
class FeedbackSt(StatesGroup):
    waiting = State()


class AdminSt(StatesGroup):
    broadcast = State()
    reply = State()


FB_KINDS = {"taklif": "💡 Taklif", "shikoyat": "⚠️ Shikoyat", "kitob": "📚 Kitob so'rovi"}
PENDING_BROADCAST: dict[int, tuple[int, int]] = {}
BG_TASKS: set = set()

# Asosiy menyudagi tugma matnlarini main_menu dan olamiz (emoji xato ketmasligi uchun)
(MB_CATALOG, MB_AUDIO, MB_FAV, MB_HIST, MB_PROFILE, MB_TOP, MB_FB, MB_SEARCH, MB_ABOUT, MB_GAME) = [
    b.text for row in main_menu.keyboard for b in row
]
IS_ADMIN = F.from_user.id.in_(ADMIN_IDS)


def admin_keyboard():  # eski admin_keyboard o'rniga (keyingi ta'rif ustun turadi)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats"),
         InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admin_users")],
        [InlineKeyboardButton(text="📬 Taklif/shikoyatlar", callback_data="admin_feedback"),
         InlineKeyboardButton(text="🔎 Qidiruvlar", callback_data="admin_searches")],
        [InlineKeyboardButton(text="📢 Xabar yuborish", callback_data="admin_broadcast")],
    ])


# ======================================================================
#  FOYDALANUVCHI BUYRUQLARI VA MENYU
# ======================================================================
@dp.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    name = html.escape(m.from_user.first_name or "do'st")
    await m.answer(
        f"Assalomu alaykum, <b>{name}</b>! 👋\n\n"
        "📚 <b>Ziyo kutubxonasi</b> botiga xush kelibsiz!\n"
        "Darsliklar, badiiy kitoblar va audiokitoblar bir joyda.\n\n"
        "🔍 Kitob nomini <b>shunchaki yozing</b> — men topib beraman.",
        reply_markup=main_menu,
    )


@dp.message(Command("help", "menu"))
async def cmd_help(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Quyidagi menyudan foydalaning yoki kitob nomini yozing 👇", reply_markup=main_menu)


@dp.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("❌ Bekor qilindi.", reply_markup=main_menu)


@dp.message(F.text == MB_CATALOG)
async def menu_catalog(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("📚 Bo'limni tanlang:", reply_markup=catalog_menu)


@dp.message(F.text == MB_AUDIO)
async def menu_audio(m: Message, state: FSMContext):
    await state.clear()
    if not AUDIO_IDS:
        await m.answer("🎧 Audiokitoblar tez orada qo'shiladi.")
        return
    await m.answer(f"🎧 <b>Audiokitoblar</b> ({len(AUDIO_IDS)} ta)\nTanlang:", reply_markup=audio_keyboard(0))


@dp.message(F.text == MB_FAV)
async def menu_fav(m: Message, state: FSMContext):
    await state.clear()
    rows = get_favorites(m.from_user.id)
    if not rows:
        await m.answer("⭐ Sevimlilar ro'yxati bo'sh.\nKitob ostidagi «⭐ Sevimlilarga qo'shish» tugmasini bosing.")
        return
    await m.answer(f"⭐ <b>Sevimlilaringiz</b> ({len(rows)} ta):", reply_markup=favorites_keyboard(rows[:50]))


@dp.message(F.text == MB_HIST)
async def menu_hist(m: Message, state: FSMContext):
    await state.clear()
    rows = get_history(m.from_user.id)
    if not rows:
        await m.answer("🕘 Hali hech narsa ochmagansiz.")
        return
    await m.answer("🕘 <b>Oxirgi ochilganlar:</b>", reply_markup=favorites_keyboard(rows))


@dp.message(F.text == MB_PROFILE)
async def menu_profile(m: Message, state: FSMContext):
    await state.clear()
    uid = m.from_user.id
    u = db_one("SELECT joined_at FROM users WHERE user_id=?", (uid,))
    favs = db_one("SELECT COUNT(*) c FROM favorites WHERE user_id=?", (uid,))["c"]
    hist = db_one("SELECT COUNT(DISTINCT item_type||item_id) c FROM history WHERE user_id=?", (uid,))["c"]
    srch = db_one("SELECT COUNT(*) c FROM searches WHERE user_id=?", (uid,))["c"]
    uname = f"@{m.from_user.username}" if m.from_user.username else "—"
    await m.answer(
        f"👤 <b>Profil</b>\n\n"
        f"Ism: {html.escape(m.from_user.full_name)}\n"
        f"Username: {html.escape(uname)}\n"
        f"ID: <code>{uid}</code>\n"
        f"Qo'shilgan sana: {u['joined_at'][:10] if u else '—'}\n\n"
        f"⭐ Sevimlilar: <b>{favs}</b>\n"
        f"📖 Ochilgan kitoblar: <b>{hist}</b>\n"
        f"🔍 Qidiruvlar: <b>{srch}</b>"
    )


@dp.message(F.text == MB_TOP)
async def menu_top(m: Message, state: FSMContext):
    await state.clear()
    rows = db_all("SELECT item_type,item_id,title,cnt FROM book_stats ORDER BY cnt DESC LIMIT 10")
    if not rows:
        await m.answer("🔝 Hali statistika yo'q. Birinchi bo'ling — kitob oching! 📚")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{n}. {'🎧' if r['item_type'] == 'audio' else '📚'} {r['title'][:42]} · {r['cnt']}",
            callback_data=f"openfav_{r['item_type']}_{r['item_id']}")]
        for n, r in enumerate(rows, 1)
    ])
    await m.answer("🔝 <b>Eng ko'p o'qilgan kitoblar</b>\n(raqam — ochilgan marta)", reply_markup=kb)


@dp.message(F.text == MB_SEARCH)
async def menu_search(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(
        "🔍 Kitob yoki muallif nomini yozing.\n"
        "Masalan: <i>algebra 8</i>, <i>agata kristi</i>, <i>saodat asri</i>"
    )


@dp.message(F.text == MB_ABOUT)
async def menu_about(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(
        "ℹ️ <b>Ziyo kutubxonasi</b>\n\n"
        f"📚 Kitoblar: <b>{len(BOOKS)}</b> ta\n"
        f"🎧 Audiokitoblar: <b>{len(AUDIO_MAP)}</b> ta\n\n"
        "Maktab darsliklari, maktabgacha ta'lim, ingliz tili, detektiv, romantik, tarixiy va diniy kitoblar.\n\n"
        "Taklif yoki shikoyatingiz bo'lsa — «✍️ Taklif va shikoyatlar» tugmasini bosing."
    )


# ======================================================================
#  KATALOG (inline)
# ======================================================================
@dp.callback_query(F.data == "noop")
async def cb_noop(c: CallbackQuery):
    await c.answer()


@dp.callback_query(F.data == "cat_back")
async def cb_cat_back(c: CallbackQuery):
    await c.answer()
    await safe_edit(c, "📚 Bo'limni tanlang:", catalog_menu)


@dp.callback_query(F.data.startswith("cat_"))
async def cb_cat(c: CallbackQuery):
    await c.answer()
    cat = c.data
    if cat == "cat_maktab":
        await safe_edit(c, "🏫 Sinfni tanlang:", with_back(maktab_classes_menu))
    elif cat == "cat_maktabgacha":
        await safe_edit(c, "🧸 <b>Maktabgacha ta'lim</b>", with_back(preschool_menu))
    elif cat == "cat_ingliz":
        await safe_edit(c, "🇬🇧 <b>Ingliz tili darajalari</b>", with_back(english_menu))
    elif cat in GENRE_BY_CAT:
        code = GENRE_BY_CAT[cat]
        await safe_edit(c, GENRES[code]["title"], with_back(genre_keyboard(code, 0)))


@dp.callback_query(F.data.startswith("gpage_"))
async def cb_gpage(c: CallbackQuery):
    await c.answer()
    _, code, page = c.data.rsplit("_", 2)
    if code in GENRES:
        await safe_edit(c, GENRES[code]["title"], with_back(genre_keyboard(code, int(page))))


@dp.callback_query(F.data.startswith("class_"))
async def cb_class(c: CallbackQuery):
    n = int(c.data.split("_")[1])
    keys = keys_for_class(n)
    if not keys:
        await c.answer("Bu sinf darsliklari tez orada qo'shiladi 🙂", show_alert=True)
        return
    await c.answer()
    await safe_edit(c, f"🏫 <b>{n}-sinf darsliklari</b>", with_back(books_keyboard(keys), "cat_maktab"))


@dp.callback_query(F.data.startswith("apage_"))
async def cb_apage(c: CallbackQuery):
    await c.answer()
    await safe_edit(c, f"🎧 <b>Audiokitoblar</b> ({len(AUDIO_IDS)} ta)\nTanlang:", audio_keyboard(int(c.data[6:])))


async def _deliver(c: CallbackQuery, bot: Bot, item_type: str, item_id: str):
    await c.answer()
    ok = await send_item(bot, c.from_user.id, item_type, item_id)
    if not ok:
        await bot.send_message(c.from_user.id, "😔 Kechirasiz, bu fayl hozir yuborilmadi. Adminlarga xabar berildi.")


@dp.callback_query(F.data.startswith("book_"))
async def cb_book(c: CallbackQuery, bot: Bot):
    await _deliver(c, bot, "book", c.data[5:])


@dp.callback_query(F.data.startswith("audio_"))
async def cb_audio(c: CallbackQuery, bot: Bot):
    await _deliver(c, bot, "audio", c.data[6:])


@dp.callback_query(F.data.startswith("openfav_"))
async def cb_openfav(c: CallbackQuery, bot: Bot):
    _, t, i = c.data.split("_", 2)
    if not item_title(t, i):
        await c.answer("Bu kitob endi mavjud emas", show_alert=True)
        return
    await _deliver(c, bot, t, i)


@dp.callback_query(F.data.startswith("fav_"))
async def cb_fav(c: CallbackQuery):
    _, t, i = c.data.split("_", 2)
    title = item_title(t, i)
    if not title:
        await c.answer("Topilmadi", show_alert=True)
        return
    added = toggle_favorite(c.from_user.id, t, i, title)
    await c.answer("⭐ Sevimlilarga qo'shildi" if added else "💔 Sevimlilardan olib tashlandi")
    try:
        await c.message.edit_reply_markup(reply_markup=favorite_button(t, i, title, c.from_user.id))
    except TelegramBadRequest:
        pass


# ======================================================================
#  TAKLIF VA SHIKOYATLAR
# ======================================================================
def fb_keyboard(fid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ Javob yozish", callback_data=f"fbreply_{fid}"),
        InlineKeyboardButton(text="✅ Ko'rib chiqildi", callback_data=f"fbdone_{fid}"),
    ]])


def fb_text(fid, kind, uid, name, uname, text, created) -> str:
    who = f'<a href="tg://user?id={uid}">{html.escape(name or "Foydalanuvchi")}</a>'
    if uname:
        who += f" @{html.escape(uname)}"
    return (f"{FB_KINDS.get(kind, kind)} <b>#{fid}</b>\n👤 {who} · <code>{uid}</code>\n"
            f"🕒 {created}\n\n{html.escape(text)}")


@dp.message(F.text == MB_FB)
async def menu_feedback(m: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=FB_KINDS["taklif"], callback_data="fb_taklif")],
        [InlineKeyboardButton(text=FB_KINDS["shikoyat"], callback_data="fb_shikoyat")],
        [InlineKeyboardButton(text=FB_KINDS["kitob"], callback_data="fb_kitob")],
    ])
    await m.answer("✍️ Nima yubormoqchisiz?", reply_markup=kb)


@dp.callback_query(F.data.startswith("fb_"))
async def cb_fb_kind(c: CallbackQuery, state: FSMContext):
    kind = c.data[3:]
    if kind not in FB_KINDS:
        await c.answer()
        return
    await c.answer()
    await state.set_state(FeedbackSt.waiting)
    await state.update_data(kind=kind)
    hint = {
        "taklif": "💡 Taklifingizni yozing:",
        "shikoyat": "⚠️ Shikoyatingizni yozing (nima ishlamadi?):",
        "kitob": "📚 Qaysi kitobni qo'shishimizni xohlaysiz? Nomi va muallifini yozing:",
    }[kind]
    await c.message.answer(hint + "\n\n<i>Bekor qilish: /cancel</i>")


@dp.message(FeedbackSt.waiting, F.text)
async def feedback_received(m: Message, state: FSMContext, bot: Bot):
    text = m.text.strip()
    if len(text) < 5:
        await m.answer("Iltimos, batafsilroq yozing (kamida 5 ta belgi).")
        return
    if len(text) > 1500:
        await m.answer("Xabar juda uzun (1500 belgigacha). Qisqartirib yuboring.")
        return
    today = datetime.utcnow().strftime("%Y-%m-%d")
    cnt = db_one("SELECT COUNT(*) c FROM feedback WHERE user_id=? AND created_at LIKE ?", (m.from_user.id, today + "%"))["c"]
    if cnt >= 5:
        await state.clear()
        await m.answer("Bugun ko'p murojaat yubordingiz. Ertaga yana yozing 🙏", reply_markup=main_menu)
        return
    kind = (await state.get_data()).get("kind", "taklif")
    created = now_iso()
    fid = db_exec("INSERT INTO feedback(user_id,kind,text,created_at) VALUES(?,?,?,?)", (m.from_user.id, kind, text, created))
    await state.clear()
    await m.answer(f"✅ Rahmat! Murojaatingiz qabul qilindi (#{fid}).", reply_markup=main_menu)
    await notify_admins(
        bot,
        fb_text(fid, kind, m.from_user.id, m.from_user.full_name, m.from_user.username, text, created),
        reply_markup=fb_keyboard(fid),
    )


@dp.message(FeedbackSt.waiting)
async def feedback_not_text(m: Message):
    await m.answer("Iltimos, faqat matn yuboring yoki /cancel bosing.")


# ======================================================================
#  O'YINLAR: viktorina, kitobni top, so'z topish, kunlik savol, reyting
# ======================================================================
import random

# (mavzu, savol, TO'G'RI javob, xato1, xato2, xato3)
QUIZ = [
    ("➗ Matematika", "7 × 8 = ?", "56", "54", "48", "63"),
    ("➗ Matematika", "144 sonining kvadrat ildizi nechaga teng?", "12", "11", "14", "16"),
    ("➗ Matematika", "Uchburchak ichki burchaklari yig'indisi necha gradus?", "180°", "90°", "270°", "360°"),
    ("➗ Matematika", "200 ning 15 foizi nechaga teng?", "30", "15", "20", "45"),
    ("➗ Matematika", "Tomonlari 6 va 4 bo'lgan to'g'ri to'rtburchakning yuzi nechaga teng?", "24", "10", "20", "48"),
    ("➗ Matematika", "2 ning 10-darajasi nechaga teng?", "1024", "512", "100", "2048"),
    ("➗ Matematika", "Aylana uzunligini topish formulasi qaysi?", "2πr", "πr²", "4πr²", "πr³"),
    ("➗ Matematika", "Eng kichik tub son qaysi?", "2", "1", "3", "0"),
    ("🌍 Geografiya", "O'zbekiston poytaxti qaysi shahar?", "Toshkent", "Samarqand", "Buxoro", "Namangan"),
    ("🌍 Geografiya", "Dunyodagi eng katta okean qaysi?", "Tinch okeani", "Atlantika okeani", "Hind okeani", "Shimoliy Muz okeani"),
    ("🌍 Geografiya", "Dunyodagi eng baland tog' cho'qqisi qaysi?", "Jomolungma (Everest)", "Elbrus", "Monblan", "Kilimanjaro"),
    ("🪐 Astronomiya", "Quyoshga eng yaqin sayyora qaysi?", "Merkuriy", "Venera", "Mars", "Yer"),
    ("🪐 Astronomiya", "Quyosh tizimidagi eng katta sayyora qaysi?", "Yupiter", "Saturn", "Neptun", "Yer"),
    ("📜 Tarix", "Amir Temur qaysi yilda tug'ilgan?", "1336-yil", "1226-yil", "1405-yil", "1370-yil"),
    ("📜 Tarix", "O'zbekiston qaysi yilda mustaqillik e'lon qilgan?", "1991-yil", "1989-yil", "1990-yil", "1992-yil"),
    ("📜 Tarix", "Mirzo Ulug'bek qaysi fan sohasida mashhur bo'lgan?", "Astronomiya", "Tibbiyot", "Kimyo", "Geologiya"),
    ("📜 Tarix", "Ibn Sino (Avitsenna) qaysi sohada mashhur?", "Tibbiyot", "Astronomiya", "Me'morchilik", "Dengizchilik"),
    ("📜 Tarix", "Algebra fanining asoschilaridan biri, vatandoshimiz kim?", "Al-Xorazmiy", "Beruniy", "Navoiy", "Farg'oniy"),
    ("📜 Tarix", "«Boburnoma» asarining muallifi kim?", "Zahiriddin Muhammad Bobur", "Alisher Navoiy", "Amir Temur", "Mirzo Ulug'bek"),
    ("📚 Adabiyot", "«O'tkan kunlar» romanining muallifi kim?", "Abdulla Qodiriy", "Cho'lpon", "Oybek", "G'afur G'ulom"),
    ("📚 Adabiyot", "«Kecha va kunduz» romanining muallifi kim?", "Cho'lpon", "Abdulla Qodiriy", "Oybek", "Hamza"),
    ("📚 Adabiyot", "Alisher Navoiyning «Xamsa»si nechta dostondan iborat?", "5 ta", "3 ta", "7 ta", "10 ta"),
    ("📚 Adabiyot", "«Sariq devni minib» asarining muallifi kim?", "Xudoyberdi To'xtaboyev", "Abdulla Qahhor", "Pirimqul Qodirov", "Odil Yoqubov"),
    ("📚 Adabiyot", "«Romeo va Julyetta» tragediyasining muallifi kim?", "Vilyam Shekspir", "Aleksandr Pushkin", "Lev Tolstoy", "Viktor Gyugo"),
    ("📚 Adabiyot", "«Uch mushketyor» romanining muallifi kim?", "Aleksandr Dyuma", "Jyul Vern", "Mark Tven", "Artur Konan Doyl"),
    ("📚 Adabiyot", "Sherlok Xolms obrazini kim yaratgan?", "Artur Konan Doyl", "Agata Kristi", "Edgar Po", "Jeyms Xedli Cheyz"),
    ("📚 Adabiyot", "«Yevgeniy Onegin» asarining muallifi kim?", "Aleksandr Pushkin", "Lev Tolstoy", "Fyodor Dostoyevskiy", "Anton Chexov"),
    ("✍️ Ona tili", "«Kitob» so'zida nechta bo'g'in bor?", "2 ta", "1 ta", "3 ta", "4 ta"),
    ("✍️ Ona tili", "Ot so'z turkumi qaysi so'roqqa javob beradi?", "Kim? Nima?", "Qanday?", "Nima qildi?", "Qancha?"),
    ("✍️ Ona tili", "Sifat so'z turkumi qaysi so'roqqa javob beradi?", "Qanday?", "Kim?", "Nima qildi?", "Necha?"),
    ("✍️ Ona tili", "«Katta» so'zining qarama-qarshi ma'nosi (antonimi) qaysi?", "Kichik", "Uzun", "Baland", "Keng"),
    ("🔬 Fan", "Suvning kimyoviy formulasi qaysi?", "H₂O", "CO₂", "O₂", "NaCl"),
    ("🔬 Fan", "Havo tarkibida eng ko'p uchraydigan gaz qaysi?", "Azot", "Kislorod", "Karbonat angidrid", "Vodorod"),
    ("🔬 Fan", "O'simliklar fotosintez jarayonida qaysi gazni yutadi?", "Karbonat angidrid", "Kislorod", "Azot", "Vodorod"),
    ("🔬 Fan", "Klassik tasnifda insonda nechta sezgi a'zosi bor?", "5 ta", "3 ta", "4 ta", "7 ta"),
    ("🔬 Fan", "Oddiy (kabisa bo'lmagan) yilda necha kun bor?", "365", "360", "364", "366"),
    ("🔬 Fan", "Yerning tabiiy yo'ldoshi qaysi?", "Oy", "Mars", "Quyosh", "Venera"),
]

WORDS = [
    "kitob", "maktab", "daftar", "qalam", "darslik", "bilim", "ustoz", "doska", "anor", "uzum",
    "shahar", "qishloq", "daryo", "bahor", "quyosh", "yulduz", "samolyot", "kompyuter", "telefon",
    "matematika", "tarix", "fizika", "kimyo", "biologiya", "adabiyot", "musiqa", "Toshkent",
    "Samarqand", "Buxoro", "Xiva", "Namangan", "Andijon", "Navoiy", "Nukus", "kutubxona", "talaba",
]

# "Kitobni top" uchun: (kalit, nomi, muallif) — faqat muallifi aniq kitoblar
_NO_AUTHOR = {"", "Noma'lum", "To'plam"}
BOOK_QUIZ: list[tuple[str, str, str]] = []
for _code, _lst in (("det", DETEKTIV_KITOBLAR), ("rom", ROMANTIK_KITOBLAR), ("din", DINIY_KITOBLAR)):
    for _i, (_t, _a, _f) in enumerate(_lst):
        if _a not in _NO_AUTHOR:
            BOOK_QUIZ.append((f"{_code}_{_i}", _t, _a))
BOOK_QUIZ_MAP = {k: (t, a) for k, t, a in BOOK_QUIZ}
AUTHOR_POOL = sorted({a for _, _, a in BOOK_QUIZ})


class GameSt(StatesGroup):
    word = State()


def init_game_db():
    conn = db_connect()
    try:
        with conn:
            conn.execute("CREATE TABLE IF NOT EXISTS game_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, game TEXT NOT NULL, points INTEGER NOT NULL, created_at TEXT NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_game_user ON game_log(user_id)")
            conn.execute("CREATE TABLE IF NOT EXISTS daily_answers (user_id INTEGER NOT NULL, day TEXT NOT NULL, correct INTEGER NOT NULL, PRIMARY KEY(user_id, day))")
    finally:
        conn.close()


init_game_db()


# ---------------- yordamchilar ----------------
def tk_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=5)      # Toshkent vaqti


def today_key() -> str:
    return tk_now().strftime("%Y-%m-%d")


def week_start_utc_iso() -> str:
    n = tk_now()
    monday = (n - timedelta(days=n.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return (monday - timedelta(hours=5)).isoformat(timespec="seconds")


def add_points(user_id: int, game: str, pts: int):
    if pts > 0:
        db_exec("INSERT INTO game_log(user_id,game,points,created_at) VALUES(?,?,?,?)", (user_id, game, pts, now_iso()))


def total_points(uid: int, since: str | None = None) -> int:
    if since:
        r = db_one("SELECT COALESCE(SUM(points),0) c FROM game_log WHERE user_id=? AND created_at>=?", (uid, since))
    else:
        r = db_one("SELECT COALESCE(SUM(points),0) c FROM game_log WHERE user_id=?", (uid,))
    return r["c"]


def _order(seed: str) -> list[int]:
    """Javob variantlari tartibi: seed bo'yicha aralashadi, holat saqlash shart emas."""
    o = [0, 1, 2, 3]
    random.Random(seed).shuffle(o)
    return o


def _answer_kb(prefix: str, texts: list[str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t[:60], callback_data=f"{prefix}_{p}")] for p, t in enumerate(texts)
    ])


def _after_kb(again_cb: str, again_text: str = "➡️ Keyingi savol", extra: list | None = None) -> InlineKeyboardMarkup:
    rows = []
    if extra:
        rows.append(extra)
    rows.append([InlineKeyboardButton(text=again_text, callback_data=again_cb)])
    rows.append([InlineKeyboardButton(text="🏆 Reyting", callback_data="g_rank_w"),
                 InlineKeyboardButton(text="🎮 O'yinlar", callback_data="g_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def games_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧠 Viktorina", callback_data="g_quiz"),
         InlineKeyboardButton(text="📖 Kitobni top", callback_data="g_book")],
        [InlineKeyboardButton(text="🔤 So'z topish", callback_data="g_word"),
         InlineKeyboardButton(text="📅 Kunlik savol", callback_data="g_daily")],
        [InlineKeyboardButton(text="🏆 Reyting", callback_data="g_rank_w")],
    ])


def games_text(uid: int) -> str:
    return (
        "🎮 <b>O'yinlar markazi</b>\n\n"
        f"⭐ Ballaringiz: <b>{total_points(uid)}</b> (shu hafta: <b>{total_points(uid, week_start_utc_iso())}</b>)\n\n"
        "🧠 Viktorina — +10 ball\n"
        "📖 Kitobni top — +10 ball\n"
        "🔤 So'z topish — +5 yoki +10 ball\n"
        "📅 Kunlik savol — +20 ball (kuniga 1 marta)\n\n"
        "Haftalik reytingda birinchi o'rinlar uchun kurashing! 🏆"
    )


# ---------------- o'yinlar menyusi ----------------
@dp.message(F.text == MB_GAME)
@dp.message(Command("oyin"))
async def menu_game(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(games_text(m.from_user.id), reply_markup=games_menu_kb())


@dp.callback_query(F.data == "g_menu")
async def cb_g_menu(c: CallbackQuery):
    await c.answer()
    await c.message.answer(games_text(c.from_user.id), reply_markup=games_menu_kb())


# ---------------- 1) VIKTORINA ----------------
@dp.callback_query(F.data == "g_quiz")
async def cb_quiz(c: CallbackQuery):
    await c.answer()
    qid = random.randrange(len(QUIZ))
    topic, q, *opts = QUIZ[qid]
    order = _order(f"qz{qid}:{c.from_user.id}")
    texts = [opts[i] for i in order]
    await c.message.answer(f"🧠 <b>Viktorina</b> · {topic}\n\n{html.escape(q)}", reply_markup=_answer_kb(f"qz_{qid}", texts))


@dp.callback_query(F.data.startswith("qz_"))
async def cb_qz(c: CallbackQuery):
    _, qid, pos = c.data.split("_")
    qid, pos = int(qid), int(pos)
    if qid >= len(QUIZ):
        await c.answer("Savol topilmadi", show_alert=True)
        return
    topic, q, *opts = QUIZ[qid]
    ok = _order(f"qz{qid}:{c.from_user.id}")[pos] == 0
    add_points(c.from_user.id, "quiz", 10 if ok else 0)
    await c.answer("✅ To'g'ri! +10 ball" if ok else "❌ Noto'g'ri")
    res = "✅ <b>To'g'ri!</b> +10 ball" if ok else f"❌ <b>Noto'g'ri.</b>\nTo'g'ri javob: <b>{html.escape(opts[0])}</b>"
    await safe_edit(c, f"🧠 <b>Viktorina</b> · {topic}\n\n{html.escape(q)}\n\n{res}", _after_kb("g_quiz"))


# ---------------- 2) KITOBNI TOP ----------------
def _book_opts(author: str, seed: int):
    rng = random.Random(f"bk{seed}")
    wrong = rng.sample([a for a in AUTHOR_POOL if a != author], 3)
    opts = [author] + wrong
    order = [0, 1, 2, 3]
    rng.shuffle(order)
    return opts, order


@dp.callback_query(F.data == "g_book")
async def cb_gbook(c: CallbackQuery):
    await c.answer()
    key, title, author = random.choice(BOOK_QUIZ)
    seed = random.randrange(100000)
    opts, order = _book_opts(author, seed)
    texts = [opts[i] for i in order]
    await c.message.answer(
        f"📖 <b>Kitobni top</b>\n\n«{html.escape(title)}» kitobining muallifi kim?",
        reply_markup=_answer_kb(f"bk_{key}_{seed}", texts),
    )


@dp.callback_query(F.data.startswith("bk_"))
async def cb_bk(c: CallbackQuery):
    key, seed, pos = c.data[3:].rsplit("_", 2)
    if key not in BOOK_QUIZ_MAP:
        await c.answer("Savol topilmadi", show_alert=True)
        return
    title, author = BOOK_QUIZ_MAP[key]
    _, order = _book_opts(author, int(seed))
    ok = order[int(pos)] == 0
    add_points(c.from_user.id, "book", 10 if ok else 0)
    await c.answer("✅ To'g'ri! +10 ball" if ok else "❌ Noto'g'ri")
    res = "✅ <b>To'g'ri!</b> +10 ball" if ok else f"❌ <b>Noto'g'ri.</b>\nMuallif: <b>{html.escape(author)}</b>"
    await safe_edit(
        c,
        f"📖 <b>Kitobni top</b>\n\n«{html.escape(title)}»\n\n{res}",
        _after_kb("g_book", extra=[InlineKeyboardButton(text="📖 Kitobni o'qish", callback_data=f"book_{key}")]),
    )


# ---------------- 3) KUNLIK SAVOL ----------------
def daily_qid() -> int:
    return tk_now().date().toordinal() % len(QUIZ)


def daily_streak(uid: int) -> int:
    rows = db_all("SELECT day FROM daily_answers WHERE user_id=? AND correct=1 ORDER BY day DESC LIMIT 400", (uid,))
    days = {r["day"] for r in rows}
    d = tk_now().date()
    if d.strftime("%Y-%m-%d") not in days:
        d -= timedelta(days=1)
    n = 0
    while d.strftime("%Y-%m-%d") in days:
        n += 1
        d -= timedelta(days=1)
    return n


@dp.callback_query(F.data == "g_daily")
async def cb_daily(c: CallbackQuery):
    await c.answer()
    uid = c.from_user.id
    row = db_one("SELECT correct FROM daily_answers WHERE user_id=? AND day=?", (uid, today_key()))
    if row:
        await c.message.answer(
            f"📅 Bugungi savolga javob bergansiz ({'✅ to‘g‘ri' if row['correct'] else '❌ noto‘g‘ri'}).\n"
            f"🔥 Ketma-ket to'g'ri kunlar: <b>{daily_streak(uid)}</b>\n\nErtaga yangi savol bo'ladi!",
            reply_markup=_after_kb("g_quiz", "🧠 Viktorina o'ynash"),
        )
        return
    qid = daily_qid()
    topic, q, *opts = QUIZ[qid]
    texts = [opts[i] for i in _order(f"dq{qid}:{uid}")]
    await c.message.answer(
        f"📅 <b>Kunlik savol</b> · {topic}\n\n{html.escape(q)}\n\n⭐ To'g'ri javob: +20 ball (faqat 1 urinish)",
        reply_markup=_answer_kb(f"dq_{qid}", texts),
    )


@dp.callback_query(F.data.startswith("dq_"))
async def cb_dq(c: CallbackQuery):
    _, qid, pos = c.data.split("_")
    qid, pos = int(qid), int(pos)
    uid = c.from_user.id
    if qid != daily_qid():
        await c.answer("Bu savol eskirdi. Yangisini oling.", show_alert=True)
        return
    topic, q, *opts = QUIZ[qid]
    ok = _order(f"dq{qid}:{uid}")[pos] == 0
    try:
        db_exec("INSERT INTO daily_answers(user_id,day,correct) VALUES(?,?,?)", (uid, today_key(), 1 if ok else 0))
    except sqlite3.IntegrityError:
        await c.answer("Bugun allaqachon javob bergansiz", show_alert=True)
        return
    add_points(uid, "daily", 20 if ok else 0)
    await c.answer("✅ To'g'ri! +20 ball" if ok else "❌ Noto'g'ri")
    res = ("✅ <b>To'g'ri!</b> +20 ball\n🔥 Ketma-ket kunlar: <b>%d</b>" % daily_streak(uid)) if ok else \
          f"❌ <b>Noto'g'ri.</b>\nTo'g'ri javob: <b>{html.escape(opts[0])}</b>"
    await safe_edit(c, f"📅 <b>Kunlik savol</b> · {topic}\n\n{html.escape(q)}\n\n{res}\n\nErtaga yangi savol! 🌙",
                    _after_kb("g_quiz", "🧠 Viktorina o'ynash"))


# ---------------- 4) SO'Z TOPISH ----------------
def _norm_word(s: str) -> str:
    return re.sub(r"[‘’`ʻʼ´′'\s]", "", s.lower())


def _scramble(w: str) -> str:
    letters = list(w)
    for _ in range(30):
        random.shuffle(letters)
        if "".join(letters) != w:
            break
    return "  ".join(x.upper() for x in letters)


WORD_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="💡 Maslahat", callback_data="g_hint"),
     InlineKeyboardButton(text="⏭ O'tkazish", callback_data="g_skip")],
])


@dp.callback_query(F.data == "g_word")
async def cb_word(c: CallbackQuery, state: FSMContext):
    await c.answer()
    w = random.choice(WORDS)
    await state.set_state(GameSt.word)
    await state.update_data(word=w, tries=0, hint=False)
    await c.message.answer(
        f"🔤 <b>So'z topish</b>\n\nHarflari aralashib ketgan so'zni toping:\n\n<b>{_scramble(w)}</b>\n\n"
        f"({len(w)} ta harf) Javobni yozib yuboring.\n<i>Chiqish: /cancel</i>",
        reply_markup=WORD_KB,
    )


@dp.callback_query(GameSt.word, F.data == "g_hint")
async def cb_hint(c: CallbackQuery, state: FSMContext):
    w = (await state.get_data()).get("word", "")
    await state.update_data(hint=True)
    await c.answer(f"💡 Birinchi harf: {w[:1].upper()}  (ball yarmiga kamayadi)", show_alert=True)


@dp.callback_query(GameSt.word, F.data == "g_skip")
async def cb_skip(c: CallbackQuery, state: FSMContext):
    w = (await state.get_data()).get("word", "")
    await state.clear()
    await c.answer()
    await c.message.answer(f"⏭ So'z: <b>{html.escape(w)}</b>", reply_markup=_after_kb("g_word", "🔤 Yangi so'z"))


@dp.callback_query(F.data.in_({"g_hint", "g_skip"}))
async def cb_word_over(c: CallbackQuery):
    await c.answer("Bu o'yin tugagan. Yangisini boshlang.", show_alert=True)


@dp.message(GameSt.word, F.text, ~F.text.startswith("/"))
async def word_answer(m: Message, state: FSMContext):
    data = await state.get_data()
    w = data.get("word", "")
    if _norm_word(m.text) == _norm_word(w):
        pts = 5 if len(w) <= 6 else 10
        if data.get("hint"):
            pts = max(1, pts // 2)
        add_points(m.from_user.id, "word", pts)
        await state.clear()
        await m.answer(f"✅ <b>To'g'ri!</b> So'z: <b>{html.escape(w)}</b>\n+{pts} ball",
                       reply_markup=_after_kb("g_word", "🔤 Yangi so'z"))
        return
    tries = data.get("tries", 0) + 1
    if tries >= 3:
        await state.clear()
        await m.answer(f"❌ Urinishlar tugadi. So'z: <b>{html.escape(w)}</b>",
                       reply_markup=_after_kb("g_word", "🔤 Yangi so'z"))
        return
    await state.update_data(tries=tries)
    await m.answer(f"❌ Noto'g'ri. Yana urinib ko'ring (qolgan urinish: {3 - tries})", reply_markup=WORD_KB)


# ---------------- 5) REYTING ----------------
def rank_view(scope: str, uid: int):
    since = week_start_utc_iso() if scope == "w" else None
    where = "WHERE g.created_at>=?" if since else ""
    params = (since,) if since else ()
    rows = db_all(
        "SELECT g.user_id AS uid, SUM(g.points) AS p, u.first_name AS fn FROM game_log g "
        "LEFT JOIN users u ON u.user_id=g.user_id " + where +
        " GROUP BY g.user_id HAVING p>0 ORDER BY p DESC LIMIT 10", params)
    title = "📅 <b>Haftalik reyting</b>" if scope == "w" else "🌍 <b>Umumiy reyting</b>"
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for n, r in enumerate(rows, 1):
        mark = medals[n - 1] if n <= 3 else f"{n}."
        name = html.escape((r["fn"] or "Foydalanuvchi")[:16])
        lines.append(f"{mark} {name} — <b>{r['p']}</b>" + (" 👈" if r["uid"] == uid else ""))
    text = title + "\n\n" + ("\n".join(lines) if lines else "Hali hech kim ball to'plamagan. Birinchi bo'ling! 🚀")
    mine = total_points(uid, since)
    if mine > 0:
        where2 = "WHERE created_at>=?" if since else ""
        rank = db_one("SELECT COUNT(*) c FROM (SELECT user_id, SUM(points) p FROM game_log " + where2 +
                      " GROUP BY user_id) WHERE p>?", params + (mine,))["c"] + 1
        text += f"\n\nSizning o'rningiz: <b>{rank}</b> · ballingiz: <b>{mine}</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Shu hafta", callback_data="g_rank_w"),
         InlineKeyboardButton(text="🌍 Hamma vaqt", callback_data="g_rank_a")],
        [InlineKeyboardButton(text="🎮 O'yinlar", callback_data="g_menu")],
    ])
    return text, kb


@dp.callback_query(F.data.in_({"g_rank_w", "g_rank_a"}))
async def cb_rank(c: CallbackQuery):
    await c.answer()
    text, kb = rank_view(c.data[-1], c.from_user.id)
    await safe_edit(c, text, kb)


# ======================================================================
#  QIDIRUV (menyuga kirmagan har qanday oddiy matn)
# ======================================================================
@dp.message(default_state, F.text, ~F.text.startswith("/"))
async def do_search(m: Message):
    q = m.text.strip()[:100]
    results, exact = search_items(q)
    db_exec("INSERT INTO searches(user_id,query,results,created_at) VALUES(?,?,?,?)",
            (m.from_user.id, norm(q) or q.lower(), len(results), now_iso()))
    if not results:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📚 Shu kitobni so'rash", callback_data="fb_kitob")]])
        await m.answer(
            f"😔 «{html.escape(q)}» bo'yicha hech narsa topilmadi.\n"
            "Yozilishini tekshirib ko'ring yoki kitobni bizdan so'rang.",
            reply_markup=kb,
        )
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label[:60], callback_data=f"openfav_{t}_{i}")] for t, i, label in results
    ])
    head = f"🔍 «{html.escape(q)}» bo'yicha <b>{len(results)}</b> ta natija:" if exact else \
           f"🔍 «{html.escape(q)}» aniq topilmadi, o'xshashlari:"
    await m.answer(head, reply_markup=kb)


# ======================================================================
#  ADMIN PANEL
# ======================================================================
@dp.message(Command("admin"), IS_ADMIN)
async def cmd_admin(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("🛠 <b>Admin panel</b>", reply_markup=admin_keyboard())


def _top(rows, key="title", n="cnt") -> str:
    if not rows:
        return "—"
    return "\n".join(f"{k}. {html.escape(str(r[key])[:50])} — <b>{r[n]}</b>" for k, r in enumerate(rows, 1))


@dp.callback_query(F.data == "admin_stats", IS_ADMIN)
async def admin_stats(c: CallbackQuery):
    await c.answer()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    week = (datetime.utcnow() - timedelta(days=7)).isoformat(timespec="seconds")
    q = lambda sql, p=(): db_one(sql, p)["c"]
    total = q("SELECT COUNT(*) c FROM users")
    new_today = q("SELECT COUNT(*) c FROM users WHERE joined_at LIKE ?", (today + "%",))
    act_today = q("SELECT COUNT(*) c FROM users WHERE last_seen LIKE ?", (today + "%",))
    act_week = q("SELECT COUNT(*) c FROM users WHERE last_seen>=?", (week,))
    blocked = q("SELECT COUNT(*) c FROM users WHERE blocked=1")
    downloads = db_one("SELECT COALESCE(SUM(cnt),0) c FROM book_stats")["c"]
    favs = q("SELECT COUNT(*) c FROM favorites")
    new_fb = q("SELECT COUNT(*) c FROM feedback WHERE status='new'")
    searches = q("SELECT COUNT(*) c FROM searches")
    top_dl = db_all("SELECT title,cnt FROM book_stats ORDER BY cnt DESC LIMIT 5")
    top_fav = db_all("SELECT title, COUNT(*) cnt FROM favorites GROUP BY item_type,item_id ORDER BY cnt DESC LIMIT 5")
    await c.message.answer(
        "📊 <b>Statistika</b>\n\n"
        f"👥 Jami: <b>{total}</b> (botni bloklaganlar: {blocked})\n"
        f"🆕 Bugun qo'shilgan: <b>{new_today}</b>\n"
        f"🟢 Bugun faol: <b>{act_today}</b> · 7 kunda: <b>{act_week}</b>\n\n"
        f"📥 Jami yuklashlar: <b>{downloads}</b>\n"
        f"⭐ Sevimlilar soni: <b>{favs}</b>\n"
        f"🔍 Qidiruvlar: <b>{searches}</b>\n"
        f"📬 Yangi murojaatlar: <b>{new_fb}</b>\n\n"
        f"🔝 <b>Eng ko'p yuklangan:</b>\n{_top(top_dl)}\n\n"
        f"💖 <b>Eng ko'p sevimlilarga qo'shilgan:</b>\n{_top(top_fav)}",
        reply_markup=admin_keyboard(),
    )


@dp.callback_query(F.data == "admin_users", IS_ADMIN)
async def admin_users(c: CallbackQuery):
    await c.answer()
    total = db_one("SELECT COUNT(*) c FROM users")["c"]
    rows = db_all("SELECT user_id,username,first_name,joined_at FROM users ORDER BY joined_at DESC LIMIT 15")
    lines = [
        f"• {html.escape(r['first_name'] or '—')} {('@' + html.escape(r['username'])) if r['username'] else ''} "
        f"<code>{r['user_id']}</code> · {r['joined_at'][:10]}"
        for r in rows
    ]
    await c.message.answer(f"👥 <b>Foydalanuvchilar: {total}</b>\nOxirgi 15 ta:\n\n" + "\n".join(lines),
                           reply_markup=admin_keyboard())


@dp.callback_query(F.data == "admin_searches", IS_ADMIN)
async def admin_searches(c: CallbackQuery):
    await c.answer()
    top = db_all("SELECT query, COUNT(*) cnt FROM searches GROUP BY query ORDER BY cnt DESC LIMIT 10")
    miss = db_all("SELECT query, COUNT(*) cnt FROM searches WHERE results=0 GROUP BY query ORDER BY cnt DESC LIMIT 10")
    await c.message.answer(
        f"🔎 <b>Eng ko'p qidirilganlar:</b>\n{_top(top, 'query')}\n\n"
        f"❌ <b>Topilmagan so'rovlar</b> (qaysi kitobni qo'shish kerak):\n{_top(miss, 'query')}",
        reply_markup=admin_keyboard(),
    )


@dp.callback_query(F.data == "admin_feedback", IS_ADMIN)
async def admin_feedback(c: CallbackQuery):
    await c.answer()
    rows = db_all(
        "SELECT f.id,f.kind,f.user_id,f.text,f.created_at,u.first_name,u.username "
        "FROM feedback f LEFT JOIN users u ON u.user_id=f.user_id "
        "WHERE f.status='new' ORDER BY f.id DESC LIMIT 10"
    )
    if not rows:
        await c.message.answer("✅ Yangi murojaatlar yo'q.", reply_markup=admin_keyboard())
        return
    for r in rows:
        await c.message.answer(
            fb_text(r["id"], r["kind"], r["user_id"], r["first_name"], r["username"], r["text"], r["created_at"]),
            reply_markup=fb_keyboard(r["id"]),
        )


@dp.callback_query(F.data.startswith("fbdone_"), IS_ADMIN)
async def admin_fb_done(c: CallbackQuery):
    db_exec("UPDATE feedback SET status='done' WHERE id=?", (int(c.data[7:]),))
    await c.answer("✅ Belgilandi")
    try:
        await c.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass


@dp.callback_query(F.data.startswith("fbreply_"), IS_ADMIN)
async def admin_fb_reply(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.set_state(AdminSt.reply)
    await state.update_data(fid=int(c.data[8:]))
    await c.message.answer("✍️ Javob matnini yozing (bekor: /cancel):")


@dp.message(AdminSt.reply, F.text, IS_ADMIN)
async def admin_fb_reply_send(m: Message, state: FSMContext, bot: Bot):
    fid = (await state.get_data()).get("fid")
    await state.clear()
    row = db_one("SELECT user_id FROM feedback WHERE id=?", (fid,))
    if not row:
        await m.answer("Murojaat topilmadi.")
        return
    try:
        await bot.send_message(row["user_id"], f"📩 <b>Admin javobi</b> (#{fid}):\n\n{html.escape(m.text)}")
    except TelegramAPIError as e:
        await m.answer(f"❌ Yuborilmadi: {html.escape(str(e))}")
        return
    db_exec("UPDATE feedback SET status='replied', admin_reply=? WHERE id=?", (m.text, fid))
    await m.answer("✅ Javob yuborildi.", reply_markup=main_menu)


# ---------------- Xabar yuborish (broadcast) ----------------
@dp.callback_query(F.data == "admin_broadcast", IS_ADMIN)
async def admin_broadcast(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.set_state(AdminSt.broadcast)
    await c.message.answer("📢 Hammaga yuboriladigan xabarni yuboring (matn, rasm, fayl...).\nBekor: /cancel")


@dp.message(AdminSt.broadcast, IS_ADMIN)
async def admin_broadcast_preview(m: Message, state: FSMContext):
    await state.clear()
    PENDING_BROADCAST[m.from_user.id] = (m.chat.id, m.message_id)
    n = db_one("SELECT COUNT(*) c FROM users WHERE blocked=0")["c"]
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"✅ {n} kishiga yuborish", callback_data="bc_confirm"),
        InlineKeyboardButton(text="❌ Bekor", callback_data="bc_cancel"),
    ]])
    await m.reply("Shu xabar yuborilsinmi?", reply_markup=kb)


@dp.callback_query(F.data == "bc_cancel", IS_ADMIN)
async def bc_cancel(c: CallbackQuery):
    PENDING_BROADCAST.pop(c.from_user.id, None)
    await c.answer("Bekor qilindi")
    await safe_edit(c, "❌ Bekor qilindi.")


@dp.callback_query(F.data == "bc_confirm", IS_ADMIN)
async def bc_confirm(c: CallbackQuery, bot: Bot):
    data = PENDING_BROADCAST.pop(c.from_user.id, None)
    if not data:
        await c.answer("Xabar topilmadi", show_alert=True)
        return
    await c.answer("Yuborish boshlandi")
    await safe_edit(c, "⏳ Yuborilmoqda...")
    task = asyncio.create_task(run_broadcast(bot, c.from_user.id, *data))
    BG_TASKS.add(task)
    task.add_done_callback(BG_TASKS.discard)


async def run_broadcast(bot: Bot, admin_id: int, from_chat: int, msg_id: int):
    users = [r["user_id"] for r in db_all("SELECT user_id FROM users WHERE blocked=0")]
    ok = fail = blocked = 0
    for uid in users:
        for attempt in (1, 2):
            try:
                await bot.copy_message(uid, from_chat, msg_id)
                ok += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                continue
            except TelegramForbiddenError:
                blocked += 1
                db_exec("UPDATE users SET blocked=1 WHERE user_id=?", (uid,))
            except TelegramAPIError:
                fail += 1
            break
        await asyncio.sleep(0.05)   # Telegram limiti: sekundiga ~30 xabar
    await bot.send_message(admin_id, f"📢 <b>Tugadi</b>\n✅ Yuborildi: {ok}\n🚫 Bloklagan: {blocked}\n⚠️ Xato: {fail}")


# ---------------- file_id ni avtomatik olish (admin uchun) ----------------
@dp.message((F.document | F.audio), IS_ADMIN)
async def admin_get_file_id(m: Message):
    if m.document:
        kind, name, fid = "document", m.document.file_name or "nomsiz", m.document.file_id
    else:
        kind = "audio"
        name = m.audio.title or m.audio.file_name or "nomsiz"
        fid = m.audio.file_id
    clean = re.sub(r"\.(pdf|docx?|epub|mp3|m4a)$", "", name, flags=re.I)
    try:
        db_exec("INSERT INTO uploads(kind,name,file_id,created_at) VALUES(?,?,?,?)", (kind, clean, fid, now_iso()))
    except sqlite3.IntegrityError:
        pass
    if kind == "audio":
        snippet = f'{{"title": "{clean}", "author": "", "parts": [("Audio", "{fid}")]}},'
    else:
        snippet = f'("{clean}", "", "{fid}"),'
    await m.reply(
        f"📎 <b>{html.escape(clean)}</b>\n\nfile_id:\n<code>{html.escape(fid)}</code>\n\n"
        f"Kodga qo'yish uchun (janr ro'yxati / AUDIO_BOOKS):\n<code>{html.escape(snippet)}</code>\n\n"
        "Hammasini fayl ko'rinishida olish: /ids"
    )


@dp.message(Command("ids"), IS_ADMIN)
async def admin_ids(m: Message):
    rows = db_all("SELECT kind,name,file_id FROM uploads ORDER BY id")
    if not rows:
        await m.answer("Hali fayl yuborilmagan. Botga PDF yoki audio yuboring.")
        return
    lines = [f'("{r["name"]}", "", "{r["file_id"]}"),  # {r["kind"]}' for r in rows]
    await m.answer_document(BufferedInputFile("\n".join(lines).encode("utf-8"), filename="file_ids.txt"),
                            caption=f"📎 {len(rows)} ta file_id")


# ---------------- Admin: kim qaysi kitobni ochgani, foydalanuvchiga xabar ----------------
def _t(iso: str) -> str:  # UTC -> Toshkent vaqti
    return (datetime.fromisoformat(iso) + timedelta(hours=5)).strftime("%d.%m %H:%M")


@dp.message(Command("user"), IS_ADMIN)
async def admin_user(m: Message):
    parts = m.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await m.answer("Ishlatish: <code>/user 123456789</code>")
        return
    uid = int(parts[1])
    u = db_one("SELECT first_name,username FROM users WHERE user_id=?", (uid,))
    if not u:
        await m.answer("Bunday foydalanuvchi topilmadi.")
        return
    rows = db_all("SELECT item_type,title,opened_at FROM history WHERE user_id=? ORDER BY opened_at DESC LIMIT 20", (uid,))
    lines = [f"{'🎧' if r['item_type'] == 'audio' else '📚'} {html.escape(r['title'])} · {_t(r['opened_at'])}" for r in rows]
    await m.answer(
        f"👤 <b>{html.escape(u['first_name'] or '—')}</b> {('@' + html.escape(u['username'])) if u['username'] else ''}\n"
        f"🎮 O'yin ballari: <b>{total_points(uid)}</b>\n\n"
        + ("\n".join(lines) if lines else "Hali kitob ochmagan.")
    )


@dp.message(Command("log"), IS_ADMIN)
async def admin_log(m: Message):
    rows = db_all(
        "SELECT h.user_id,h.item_type,h.title,h.opened_at,u.first_name,u.username "
        "FROM history h LEFT JOIN users u ON u.user_id=h.user_id ORDER BY h.opened_at DESC LIMIT 20"
    )
    if not rows:
        await m.answer("Hali hech kim kitob ochmagan.")
        return
    lines = [
        f"{_t(r['opened_at'])} · {html.escape(r['first_name'] or '—')} "
        f"{('@' + html.escape(r['username'])) if r['username'] else ''} <code>{r['user_id']}</code>\n"
        f"   {'🎧' if r['item_type'] == 'audio' else '📚'} {html.escape(r['title'])}"
        for r in rows
    ]
    await m.answer("🕘 <b>Oxirgi 20 ta ochilgan kitob:</b>\n\n" + "\n".join(lines))


@dp.message(Command("send"), IS_ADMIN)
async def admin_send(m: Message, bot: Bot):
    parts = m.text.split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await m.answer("Ishlatish: <code>/send 123456789 Xabar matni</code>")
        return
    uid = int(parts[1])
    try:
        await bot.send_message(uid, f"📩 <b>Admin xabari:</b>\n\n{html.escape(parts[2])}")
    except TelegramForbiddenError:
        await m.answer("❌ Foydalanuvchi botni bloklagan yoki /start bosmagan.")
        return
    except TelegramAPIError as e:
        await m.answer(f"❌ Yuborilmadi: {html.escape(str(e))}")
        return
    await m.answer("✅ Yuborildi.")


# ======================================================================
#  ISHGA TUSHIRISH
# ======================================================================
@dp.error()
async def on_error(event):
    logging.exception("Kutilmagan xato: %s", event.exception)
    return True


async def main():
    if not TOKEN:
        raise SystemExit("BOT_TOKEN o'rnatilmagan! Masalan: export BOT_TOKEN='...'")
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_my_commands([
        BotCommand(command="start", description="Botni boshlash"),
        BotCommand(command="menu", description="Asosiy menyu"),
        BotCommand(command="oyin", description="O'yinlar"),
        BotCommand(command="cancel", description="Bekor qilish"),
    ])
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
