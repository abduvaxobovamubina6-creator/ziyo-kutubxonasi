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
#   Linux/Mac:  export BOT_TOKEN="yangi_token"
#   Windows:    set BOT_TOKEN=yangi_token
TOKEN = os.getenv("BOT_TOKEN", "")
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
add_genre("rom", "❤️", "❤️ <b>Romantik kitoblar</b>", ROMANTIK_KITOBLAR)
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
        [KeyboardButton(text="ℹ️ Bot haqida")],
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
        [InlineKeyboardButton(text=f"{n}-sinf", callback_data=f"class_{n}") for n in (4, 5, 6)],
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
# Namuna (# belgisini olib tashlab, o'z ma'lumotingizni yozing):
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
        "title": "4-kitob. 12 - Mu'ta g'azoti",
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
    },
    {
        "title": '4-kitob. 16 - Abu Sufyon va sheriklari',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEqmq-F-G4SpcPoq6O_XGuU1oZrDz9AAKCAANRMPBLM35J0Uc0EM89BA'),
        ],
    },
    {
        "title": '4-kitob. 24 - Hazrati Zaynabning vafoti',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEsmq-F-Ep-9sfDeamRHWlAnDPyp50AAKKAANRMPBLJcCG6wKF-rQ9BA'),
        ],
    },
    {
        "title": '4-kitob. 34 - Najron elchilari',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEvGq-F-G_HBBVZidZtMrHHm6aVWRSAAKUAANRMPBLkycszi272PA9BA'),
        ],
    },
    {
        "title": "4-kitob. 11 - Ummul-mo'miniynlarga tanbeh",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEpWq-F-ESWSNtqLO1kZ7Ib3Qz_By0AAJ9AANRMPBLLWeAqPwIb3w9BA'),
        ],
    },
    {
        "title": '4-kitob. 37 - Hadya hirqa',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgIAAxkBAAIEv2q-F-EkVSG8R1-9NIWKC2Hp8IzBAAKXAANRMPBLfUxmpSUHKy89BA'),
        ],
    },
    {
        "title": 'Iqtisodiy_tahlil:_Arzon_uy_joy_hammaga_yetadimi_t_me/audiokitoblar',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFNWq-GLm9Vn2zowHMX1o62Yy2rVh2AAI0DAAC_jcYUDZyE72gQJWYPQQ'),
        ],
    },
    {
        "title": 'Gurung (qissa va hikoyalar)-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFMGq-GLmKtmKg0C3S9C5JD9y6SEoLAAJYDAACGZRIUH7UJwTK3NDhPQQ'),
        ],
    },
    {
        "title": 'Alisher Navoiy (audiodrama)-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFL2q-GLk-UFv6-G-SnwpA4CPOYra6AALtCwAC_jcgUHQ-qNx-GpAYPQQ'),
        ],
    },
    {
        "title": '03. Oqqushlar, oppoq qushlar-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFM2q-GLnPHDpp2NvjD16YuJK_NXwrAAIMCwAC_jcYUBz5dYWuzqaWPQQ'),
        ],
    },
    {
        "title": '01. Oqqushlar, oppoq qushlar-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFMWq-GLkj7RxwcNYR_EPtnB0uVyOEAALxCgAC_jcYUP_vXOXItuAlPQQ'),
        ],
    },
    {
        "title": '12. Ko‘hna dunyo (so‘nggi qism)-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFUWq-GLl7iIg03QzR2bKnRpawGCV7AAIiDgACGZRQULjlR8Y8gFg6PQQ'),
        ],
    },
    {
        "title": 'Zulmat ichra nur (Mirkarim Osim)-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFOGq-GLkaf4POOY2emHE10y96EpoiAAKKCQACanT4UH534kdMjFVAPQQ'),
        ],
    },
    {
        "title": 'Chotqol yo‘lbarsi (Mirmuhsin)-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFLmq-GLmaRDh5mUs-JEiCfA2vKXEuAAL7DQACGZRQUIP5kIcd6pQlPQQ'),
        ],
    },
    {
        "title": '01. Iblis saltanati (1-kitob)-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFOWq-GLm7Il7uBVWVTNuBfJbPt8miAAI8DAACGZRIUC3TUBRnFSzQPQQ'),
        ],
    },
    {
        "title": "Diyor_Imomxo'jayev_bilan_katta_intervyu_t_me/audiokitoblar_uz",
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFN2q-GLnhU-mzAq4WWIR6VxhebXqLAALMCAACJLbxUtsv61E-aL8hPQQ'),
        ],
    },
    {
        "title": '03. Ko‘hna dunyo-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFSGq-GLnFKwK0VR9sKvzTqTEXum9kAAIJDgACGZRQUNtKp4ja_B6gPQQ'),
        ],
    },
    {
        "title": '01. Ko‘hna dunyo-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFRmq-GLmS-AwqaagAAengMkh6e9G9owACBA4AAhmUUFAntdnvUC80mz0E'),
        ],
    },
    {
        "title": '11. Ko‘hna dunyo-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFUGq-GLmrXgABJJT3GfetASoKXmIAAecAAiAOAAIZlFBQV2vzX1njtQE9BA'),
        ],
    },
    {
        "title": '03. Iblis saltanati (1-kitob)-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFO2q-GLlEzEY473DqiHq9QiUjhetMAAJNDAACGZRIUD3ksOKeZKD3PQQ'),
        ],
    },
    {
        "title": 'Kitob... Tavsiya va tahlil (3-son)',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFQWq-GLmWamhhGSOz9dfWtfHZBc2nAALvHgACrNmhUgLbinYs-9qyPQQ'),
        ],
    },
    {
        "title": '02. Oqqushlar, oppoq qushlar-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFMmq-GLn4Xc1hZ93IpydutLbx6hiVAAIHCwAC_jcYUIa1cPL4TGW8PQQ'),
        ],
    },
    {
        "title": '08. Ko‘hna dunyo-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFTWq-GLkc4kG_B5gJs3kBQyO7OzEdAAIVDgACGZRQUK_7f7bKI4AaPQQ'),
        ],
    },
    {
        "title": '10. Ko‘hna dunyo-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFT2q-GLm_Qh5NxlHMO4Qw0b4ZqhCeAAIXDgACGZRQUAzOrujUcU1NPQQ'),
        ],
    },
    {
        "title": 'Shuhrat Abdurahmonov bilan suhbat-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFPmq-GLmsqnHDZvxlyxbAQ-43-kgqAAIxDAAC_jcYUDXas7JhmGeKPQQ'),
        ],
    },
    {
        "title": 'Qobusnoma (Kaykovus)-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFPWq-GLlm5kDV9JKvvFzezLb3SSiCAAKJCQACanT4UBnYeUAd9jT0PQQ'),
        ],
    },
    {
        "title": '06. Ko‘hna dunyo-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFS2q-GLlr2B3jN4vUpyE1Len6VFvIAAISDgACGZRQUANdVv_4mI97PQQ'),
        ],
    },
    {
        "title": '02. Seyfdagi pullar-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFVmq-GLn4NHWKAAEjdTaj4cTHR8jDnAACKAkAAhZEOFHkLvA6AglqaT0E'),
        ],
    },
    {
        "title": 'Dunyoni zabt etgan kitoblar - Farengeyt bo_yicha 451 daraja ',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFWGq-GLnRh8-G7shYmGE5NjxK286kAAIyKgAClwIxUzNDx1Z0FX0UPQQ'),
        ],
    },
    {
        "title": '01. Dunyo malikalari-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFU2q-GLmLZ7QO2z9uGwiGAX6oYt1KAALlCQACQlpQUF1QhoTRzMdxPQQ'),
        ],
    },
    {
        "title": '03. Seyfdagi pullar-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFV2q-GLlEls-4fhwkfBT3Za-htHaGAAIpCQACFkQ4UbF60gUMGPutPQQ'),
        ],
    },
    {
        "title": '07. Ko‘hna dunyo-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFTGq-GLm35jtPEhp0jXSZvUeq4AVpAAIUDgACGZRQUBkAAemQHNDjFz0E'),
        ],
    },
    {
        "title": '03. Sehrli kuch-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFRGq-GLkS-CpZ6EUzCzJaYx0_btxwAAL5CQACQlpQUM3fiUL32akVPQQ'),
        ],
    },
    {
        "title": '02. Dunyo malikalari-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFVGq-GLkK2TVKlQPKnOpwbCabknbCAALqCQACQlpQUEprxWgupXvvPQQ'),
        ],
    },
    {
        "title": '02. Ko‘hna dunyo-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFR2q-GLkwzsCH0eYQSlLkFPqrhPpuAAIHDgACGZRQUN6GQn0z7h6UPQQ'),
        ],
    },
    {
        "title": '04. Iblis saltanati (1-kitob)-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFPGq-GLnMTyihhYLQOyD-sREm0LReAAJODAACGZRIUFEGK4RGYeeAPQQ'),
        ],
    },
    {
        "title": '05. Ko‘hna dunyo-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFSmq-GLlrLJ5pfN0U4oQ0IEM1aAXtAAIMDgACGZRQUMRLoPqrW1GoPQQ'),
        ],
    },
    {
        "title": 'Dunyoni zabt etgan kitoblar - _Jarayon_ (Frans Kafka)',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFUmq-GLnDHLYQfisnJP0hikNqKr5qAAL6QAACV33wUljykAiswG5CPQQ'),
        ],
    },
    {
        "title": '01. Seyfdagi pullar-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFVWq-GLmbeqjjsRPKY9kwqaly630mAAIgCQACFkQ4UboLwkXvNBdTPQQ'),
        ],
    },
    {
        "title": '04. Oqqushlar, oppoq qushlar-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFNGq-GLk-4BhpB16uLSvPSwFl3k9CAAIYCwAC_jcYUMwh4buQIp3dPQQ'),
        ],
    },
    {
        "title": 'Dunyoni zabt etgan kitoblar - Inson komediyasi ',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFWWq-GLmBGpiQSWHYVgoQKIYQb2W3AALJHwACaXtAUz3isYgBHhYjPQQ'),
        ],
    },
    {
        "title": '02. Sehrli kuch-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFQ2q-GLnsrU29eGB9U_Ic9MDLTJltAAL4CQACQlpQUPjjIbLRQpCEPQQ'),
        ],
    },
    {
        "title": '01. Sehrli kuch-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFQmq-GLnNjT4djatyTTPS_Fc3tW4cAAL0CQACQlpQUPRJV_RuMn6FPQQ'),
        ],
    },
    {
        "title": 'Kitob... Tavsiya va tahlil (1-son)',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFP2q-GLnSW3WH6VjlbbudNfv_2udCAALuHgAC-Z8gUlOVHRL1Aa6lPQQ'),
        ],
    },
    {
        "title": 'Jannatga yo‘l (Abdulla Oripov)-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFLWq-GLn2M_eVmsaSdG4hmid2zj3ZAAJQDAACGZRIUEmfYF4NC6sTPQQ'),
        ],
    },
    {
        "title": '04. Sehrli kuch-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFRWq-GLk9vjiOBMNuJdWt5KJnFiYBAAL6CQACQlpQUK9tvf1Rwc21PQQ'),
        ],
    },
    {
        "title": 'Xayrulla Bozorov bilan suhbat-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFQGq-GLmgvYP8mciZMcJXkM1zJuISAAItDAAC_jcYUJNusQABTIG0dD0E'),
        ],
    },
    {
        "title": 'Oltin devor (Erkin Vohidov)-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFNmq-GLmK0JNnhGe4zbdp8d6eDDv2AAJTDAACGZRIUMDD4kPmV-kdPQQ'),
        ],
    },
    {
        "title": '02. Iblis saltanati (1-kitob)-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFOmq-GLnE4TFv_P1W8CWjiJ5H29_JAAJKDAACGZRIUAUQKJe1vRBPPQQ'),
        ],
    },
    {
        "title": '09. Ko‘hna dunyo-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFTmq-GLkv_IYWtsluNCaFCDs5ilc1AAIWDgACGZRQUGNPzy6AQlu8PQQ'),
        ],
    },
    {
        "title": '04. Ko‘hna dunyo-t.me/audiokitoblar_uz',
        "author": "",
        "parts": [
            ("Audio", 'CQACAgQAAxkBAAIFSWq-GLnclhaI8-HgJlDdatpIDromAAILDgACGZRQUBNt-oQhEdYVPQQ'),
        ],
    },
]
AUDIO_PAGE_SIZE = 10


def audio_list_keyboard(page: int) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(AUDIO_BOOKS) + AUDIO_PAGE_SIZE - 1) // AUDIO_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * AUDIO_PAGE_SIZE
    rows = []
    for i in range(start, min(start + AUDIO_PAGE_SIZE, len(AUDIO_BOOKS))):
        book = AUDIO_BOOKS[i]
        text = f"🎧 {book['title']}"
        if book.get("author"):
            text += f" — {book['author']}"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"abook_{i}")])
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"apage_{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"apage_{page + 1}"))
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def audio_parts_keyboard(i: int) -> InlineKeyboardMarkup:
    parts = AUDIO_BOOKS[i]["parts"]
    rows = [
        [InlineKeyboardButton(text=f"🎧 {name}", callback_data=f"apart_{i}_{j}")]
        for j, (name, _fid) in enumerate(parts)
    ]
    rows.append([InlineKeyboardButton(text="📥 Hammasini yuborish", callback_data=f"aall_{i}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_audio_part(message: types.Message, book: dict, part_name: str, file_id: str) -> None:
    caption = f"🎧 <b>{html.escape(book['title'])}</b>"
    if book.get("author"):
        caption += f"\n<i>{html.escape(book['author'])}</i>"
    if len(book["parts"]) > 1:
        caption += f"\n{html.escape(part_name)}"
    try:
        item_id=str(next((idx for idx,b in enumerate(AUDIO_BOOKS) if b is book),0))
        register_user(message.from_user)
        add_history(message.from_user.id,"audio",item_id,book["title"])
        await message.answer_audio(audio=file_id, caption=caption, parse_mode="HTML", reply_markup=favorite_button("audio",item_id,book["title"],message.from_user.id))
    except TelegramAPIError:
        # file_id hujjat (document) sifatida saqlangan bo'lsa, shunday yuboramiz
        try:
            await message.answer_document(document=file_id, caption=caption, parse_mode="HTML", reply_markup=favorite_button("audio",str(next((idx for idx,b in enumerate(AUDIO_BOOKS) if b is book),0)),book["title"],message.from_user.id))
        except TelegramAPIError:
            await message.answer(f"⚠️ «{html.escape(part_name)}» ni yuborib bo'lmadi.", parse_mode="HTML")


# ======================================================================
#  5-QISM: QIDIRUV
# ======================================================================
def normalize(text: str) -> str:
    text = text.lower()
    for ch in "ʻʼ‘’'`´":
        text = text.replace(ch, "")
    text = text.replace("ğ", "g").replace(".", " ")
    text = re.sub(r"[-–—_]", " ", text)
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


SEARCH_INDEX = {key: normalize(plain_first_line(RAW_BOOKS[key]["caption"])) if key in RAW_BOOKS
                else normalize(BOOKS[key]["button"]) for key in BOOKS}


def search_books(query: str) -> list[str]:
    words = normalize(query).split()
    if not words:
        return []
    return [k for k, title in SEARCH_INDEX.items() if all(w in title for w in words)]


# ======================================================================
#  6-QISM: HANDLERLAR
# ======================================================================
@dp.message(CommandStart())
async def start_handler(message: types.Message):
    register_user(message.from_user)
    name = html.escape(message.from_user.first_name or "do'st")
    await message.answer(
        f"Assalomu alaykum, <b>{name}</b>!\n\n"
        f"📚 <b>'Ziyo Kutubxonasi'</b> rasmiy botiga xush kelibsiz.\n"
        f"O'zingizga kerakli bo'limni tanlash uchun quyidagi menyudan foydalaning:",
        reply_markup=main_menu,
        parse_mode="HTML",
    )


@dp.message(F.text == "📚 Kitob katalogi")
async def catalog_handler(message: types.Message):
    await message.answer("📂 <b>Kitoblar katalogi bo'limi:</b>", reply_markup=catalog_menu, parse_mode="HTML")


@dp.message(F.text == "🎧 Audiokitoblar")
async def audio_handler(message: types.Message):
    if not AUDIO_BOOKS:
        await message.answer(
            "🎧 <b>Audiokitoblar bo'limi</b>\n\nYaqin orada bu yerga audiokitoblarni joylaymiz!",
            parse_mode="HTML",
        )
        return
    await message.answer(
        f"🎧 <b>Audiokitoblar</b> (jami {len(AUDIO_BOOKS)} ta):",
        reply_markup=audio_list_keyboard(0),
        parse_mode="HTML",
    )


@dp.message(F.text == "🔝 Eng ko'p o'qilgan kitoblar")
async def top_books_handler(message: types.Message):
    await message.answer(
        "🔥 <b>Eng ko'p o'qilayotgan kitoblar Top-3:</b>\n\n"
        "1. 📖 <i>O'tkan kunlar</i> — Abdulla Qodiriy\n"
        "2. 📘 <i>Navigate Elementary</i> — Oxford\n"
        "3. 🌙 <i>Ijtimoiy odoblar</i> — Shayx Muhammad Sodiq",
        parse_mode="HTML",
    )


@dp.message(F.text == "✍️ Taklif va shikoyatlar")
async def feedback_handler(message: types.Message):
    await message.answer(
        "✍️ <b>Taklif va Murojaatlar bo'limi</b>\n\n"
        "Taklif yoki shikoyatlaringiz bo'lsa administratorga bevosita murojaat qiling:\n\n"
        "👤 <b>Admin:</b> @Masudbeklynux",
        parse_mode="HTML",
    )


@dp.message(F.text == "🔍 Qidiruv")
async def search_instruction_handler(message: types.Message):
    await message.answer(
        "🔍 <b>Kitob qidiruv tizimi</b>\n\n"
        "📌 Kitob nomini (yoki nomining bir qismini) yozing. Katta-kichik harf farqi yo'q, "
        "probel o'rniga nuqta (.) ham qo'ysangiz bo'ladi.\n"
        "💡 Misol: <code>mafiya sardori</code> yoki <code>QIL.USTIDAGI.TAQDIR</code>",
        parse_mode="HTML",
    )


@dp.message(F.text == "ℹ️ Bot haqida")
async def info_handler(message: types.Message):
    await message.answer(
        "ℹ️ <b>'Ziyo Kutubxonasi' boti:</b> Jamiyatimizda kitobxonlikni oshirish uchun yaratilgan ochiq loyiha.",
        parse_mode="HTML",
    )


# ---------------- Inline callback'lar ----------------
@dp.callback_query(F.data == "noop")
async def noop_callback(callback: types.CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data == "cat_maktab")
async def school_books_callback(callback: types.CallbackQuery):
    await callback.message.answer("🏫 <b>Sinfni tanlang:</b>", reply_markup=maktab_classes_menu, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "cat_maktabgacha")
async def preschool_callback(callback: types.CallbackQuery):
    await callback.message.answer("🧸 <b>Maktabgacha ta'lim kitoblari:</b>", reply_markup=preschool_menu, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "cat_ingliz")
async def english_callback(callback: types.CallbackQuery):
    await callback.message.answer(
        "🇬🇧 <b>Navigate darsliklari (Darajani tanlang):</b>", reply_markup=english_menu, parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.in_(set(GENRE_BY_CAT)))
async def genre_callback(callback: types.CallbackQuery):
    code = GENRE_BY_CAT[callback.data]
    genre = GENRES[code]
    await callback.message.answer(
        f"{genre['title']} (jami {len(genre['keys'])} ta):",
        reply_markup=genre_keyboard(code, 0),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("gpage_"))
async def genre_page_callback(callback: types.CallbackQuery):
    _, code, page = callback.data.split("_")
    if code in GENRES:
        try:
            await callback.message.edit_reply_markup(reply_markup=genre_keyboard(code, int(page)))
        except TelegramAPIError:
            pass
    await callback.answer()


@dp.callback_query(F.data.startswith("class_"))
async def select_class_callback(callback: types.CallbackQuery):
    class_num = int(callback.data.split("_")[1])
    keys = keys_for_class(class_num)
    if keys:
        await callback.message.answer(
            f"📘 <b>{class_num}-sinf darsliklar ro'yxati:</b>\n\nKerakli darslikni tanlang:",
            reply_markup=books_keyboard(keys),
            parse_mode="HTML",
        )
    else:
        await callback.message.answer("⚠️ Ushbu sinf darsliklari tez orada bazaga joylanadi!")
    await callback.answer()


# ---------------- Kitobni yuborish ----------------
@dp.callback_query(F.data.startswith("book_"))
async def send_book_by_callback(callback: types.CallbackQuery):
    book_key = callback.data[len("book_"):]
    book = BOOKS.get(book_key)

    if not book:
        await callback.message.answer("⚠️ Ushbu kitob topilmadi.")
        await callback.answer()
        return

    await callback.answer("⏳ Kitob yuklanmoqda, kuting...")
    try:
        title=plain_first_line(book["caption"])
        register_user(callback.from_user)
        add_history(callback.from_user.id,"book",book_key,title)
        await callback.message.answer_document(
            document=book["file_id"],
            caption=book["caption"],
            parse_mode="HTML",
            reply_markup=favorite_button("book",book_key,title,callback.from_user.id),
        )
    except TelegramAPIError:
        await callback.message.answer(
            "⚠️ Faylni yuborib bo'lmadi. File ID shu botga tegishli ekanini tekshiring."
        )


# Boshqa janrlar (hozircha bo'sh)
@dp.callback_query(F.data.startswith("cat_"))
async def other_genres_callback(callback: types.CallbackQuery):
    await callback.message.answer("📚 Ushbu bo'limga kitoblar tez orada qo'shiladi!")
    await callback.answer()


# ---------------- Audiokitoblar ----------------
@dp.callback_query(F.data.startswith("apage_"))
async def audio_page_callback(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[1])
    try:
        await callback.message.edit_reply_markup(reply_markup=audio_list_keyboard(page))
    except TelegramAPIError:
        pass
    await callback.answer()


@dp.callback_query(F.data.startswith("abook_"))
async def audio_book_callback(callback: types.CallbackQuery):
    i = int(callback.data.split("_")[1])
    if i >= len(AUDIO_BOOKS):
        await callback.answer("Kitob topilmadi", show_alert=True)
        return
    book = AUDIO_BOOKS[i]
    if len(book["parts"]) == 1:
        await callback.answer("⏳ Yuklanmoqda...")
        name, fid = book["parts"][0]
        await send_audio_part(callback.message, book, name, fid)
    else:
        await callback.message.answer(
            f"🎧 <b>{html.escape(book['title'])}</b>\n\nQismni tanlang:",
            reply_markup=audio_parts_keyboard(i),
            parse_mode="HTML",
        )
        await callback.answer()


@dp.callback_query(F.data.startswith("apart_"))
async def audio_part_callback(callback: types.CallbackQuery):
    _, i, j = callback.data.split("_")
    try:
        book = AUDIO_BOOKS[int(i)]
        name, fid = book["parts"][int(j)]
    except (IndexError, ValueError):
        await callback.answer("Qism topilmadi", show_alert=True)
        return
    await callback.answer("⏳ Yuklanmoqda...")
    await send_audio_part(callback.message, book, name, fid)


@dp.callback_query(F.data.startswith("aall_"))
async def audio_all_callback(callback: types.CallbackQuery):
    i = int(callback.data.split("_")[1])
    if i >= len(AUDIO_BOOKS):
        await callback.answer("Kitob topilmadi", show_alert=True)
        return
    book = AUDIO_BOOKS[i]
    await callback.answer(f"⏳ {len(book['parts'])} ta qism yuborilmoqda...")
    for name, fid in book["parts"]:
        await send_audio_part(callback.message, book, name, fid)
        await asyncio.sleep(0.5)  # Telegram cheklovidan saqlanish uchun


# ---------------- Audio yuborilsa file_id ni qaytarish ----------------
@dp.message(F.audio)
async def get_audio_id_handler(message: types.Message):
    audio = message.audio
    name = html.escape(audio.file_name or audio.title or "nomsiz")
    await message.reply(
        f"🎧 <b>Audio nomi:</b> {name}\n\n"
        f"🔑 <b>file_id:</b>\n<code>{audio.file_id}</code>",
        parse_mode="HTML",
    )


# ---------------- Fayl yuborilsa file_id ni qaytarish ----------------
@dp.message(F.document)
async def get_file_id_handler(message: types.Message):
    file_id = message.document.file_id
    file_name = html.escape(message.document.file_name or "nomsiz")
    await message.reply(
        f"📄 <b>Fayl nomi:</b> {file_name}\n\n"
        f"🔑 <b>file_id:</b>\n<code>{file_id}</code>",
        parse_mode="HTML",
    )


# ---------------- Profil / Sevimlilar / Tarix ----------------
@dp.message(F.text == "👤 Profil")
async def profile_handler(message: types.Message):
    register_user(message.from_user)
    with db_connect() as db:
        u=db.execute("SELECT joined_at FROM users WHERE user_id=?",(message.from_user.id,)).fetchone()
        f=db.execute("SELECT COUNT(*) c FROM favorites WHERE user_id=?",(message.from_user.id,)).fetchone()["c"]
        h=db.execute("SELECT COUNT(*) c FROM history WHERE user_id=?",(message.from_user.id,)).fetchone()["c"]
    await message.answer(f"👤 <b>Mening profilim</b>\n\n🆔 ID: <code>{message.from_user.id}</code>\n📅 Qo'shilgan: {u['joined_at'][:10]}\n⭐ Sevimlilar: {f} ta\n🕘 Tarix: {h} ta",parse_mode="HTML")

@dp.message(F.text == "⭐ Sevimlilar")
async def favorites_handler(message: types.Message):
    rows=get_favorites(message.from_user.id)
    if not rows: return await message.answer("⭐ Hozircha sevimlilar yo'q.")
    await message.answer("⭐ <b>Sevimlilarim:</b>",reply_markup=favorites_keyboard(rows),parse_mode="HTML")

@dp.message(F.text == "🕘 Tarix")
async def history_handler(message: types.Message):
    rows=get_history(message.from_user.id)
    if not rows: return await message.answer("🕘 Ko'rish tarixingiz hozircha bo'sh.")
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=("📚 " if r["item_type"]=="book" else "🎧 ")+r["title"][:55],callback_data=f"openhist_{r['item_type']}_{r['item_id']}")] for r in rows])
    await message.answer("🕘 <b>Oxirgi ko'rilganlar:</b>",reply_markup=kb,parse_mode="HTML")

@dp.callback_query(F.data.startswith("fav_"))
async def favorite_callback(callback: types.CallbackQuery):
    _,typ,item_id=callback.data.split("_",2)
    if typ=="book" and item_id in BOOKS: title=plain_first_line(BOOKS[item_id]["caption"])
    elif typ=="audio":
        try: title=AUDIO_BOOKS[int(item_id)]["title"]
        except (ValueError,IndexError): return await callback.answer("Element topilmadi",show_alert=True)
    else: return await callback.answer("Element topilmadi",show_alert=True)
    state=toggle_favorite(callback.from_user.id,typ,item_id,title)
    await callback.answer("⭐ Sevimlilarga qo'shildi" if state else "💔 Sevimlilardan olib tashlandi")
    try: await callback.message.edit_reply_markup(reply_markup=favorite_button(typ,item_id,title,callback.from_user.id))
    except TelegramAPIError: pass

async def open_saved_item(message,typ,item_id):
    if typ=="book" and item_id in BOOKS:
        book=BOOKS[item_id]; title=plain_first_line(book["caption"]); add_history(message.from_user.id,"book",item_id,title)
        await message.answer_document(document=book["file_id"],caption=book["caption"],parse_mode="HTML",reply_markup=favorite_button("book",item_id,title,message.from_user.id)); return
    if typ=="audio":
        try:
            i=int(item_id); book=AUDIO_BOOKS[i]; name,fid=book["parts"][0]; await send_audio_part(message,book,name,fid); return
        except (ValueError,IndexError,TelegramAPIError): pass
    await message.answer("⚠️ Bu material endi mavjud emas.")

@dp.callback_query(F.data.startswith("openfav_"))
async def open_fav(callback: types.CallbackQuery):
    _,typ,item_id=callback.data.split("_",2); await callback.answer("⏳ Yuklanmoqda..."); await open_saved_item(callback.message,typ,item_id)

@dp.callback_query(F.data.startswith("openhist_"))
async def open_hist(callback: types.CallbackQuery):
    _,typ,item_id=callback.data.split("_",2); await callback.answer("⏳ Yuklanmoqda..."); await open_saved_item(callback.message,typ,item_id)

@dp.message(F.text == "/admin")
async def admin_command(message: types.Message):
    if not admin_only(message.from_user.id): return await message.answer("⛔ Sizda admin huquqi yo'q.")
    await message.answer("🛠 <b>Admin panel</b>",reply_markup=admin_keyboard(),parse_mode="HTML")

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if not admin_only(callback.from_user.id): return await callback.answer("⛔ Ruxsat yo'q",show_alert=True)
    with db_connect() as db:
        u=db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]; f=db.execute("SELECT COUNT(*) c FROM favorites").fetchone()["c"]; h=db.execute("SELECT COUNT(*) c FROM history").fetchone()["c"]
    await callback.message.answer(f"📊 <b>Statistika</b>\n\n👥 Foydalanuvchilar: {u}\n⭐ Sevimlilar: {f}\n🕘 Tarix yozuvlari: {h}\n📚 Kitoblar: {len(BOOKS)}\n🎧 Audiolar: {len(AUDIO_BOOKS)}",parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: types.CallbackQuery):
    if not admin_only(callback.from_user.id): return await callback.answer("⛔ Ruxsat yo'q",show_alert=True)
    with db_connect() as db: rows=db.execute("SELECT first_name,username,user_id FROM users ORDER BY last_seen DESC LIMIT 20").fetchall()
    text="👥 <b>Oxirgi foydalanuvchilar:</b>\n\n"+"".join(f"• {html.escape(r['first_name'] or '-')} — @{r['username'] or '-'} — <code>{r['user_id']}</code>\n" for r in rows)
    await callback.message.answer(text,parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: types.CallbackQuery):
    if not admin_only(callback.from_user.id): return await callback.answer("⛔ Ruxsat yo'q",show_alert=True)
    admin_broadcast_state.add(callback.from_user.id); await callback.message.answer("📢 Xabar matnini yuboring. Bekor qilish: /cancel"); await callback.answer()

@dp.message(F.text == "/cancel")
async def cancel_broadcast(message: types.Message):
    admin_broadcast_state.discard(message.from_user.id); await message.answer("✅ Bekor qilindi.")

@dp.message(F.text, lambda message: message.from_user.id in admin_broadcast_state)
async def admin_broadcast(message: types.Message):
    if not admin_only(message.from_user.id): admin_broadcast_state.discard(message.from_user.id); return
    admin_broadcast_state.discard(message.from_user.id)
    with db_connect() as db: ids=[r["user_id"] for r in db.execute("SELECT user_id FROM users").fetchall()]
    sent=0
    for uid in ids:
        try: await message.bot.send_message(uid,message.text); sent+=1; await asyncio.sleep(0.04)
        except TelegramAPIError: pass
    await message.answer(f"📢 Xabar {sent} ta foydalanuvchiga yuborildi.")


# ---------------- Qidiruv (eng oxirida turishi kerak) ----------------
@dp.message(F.text & ~F.text.startswith("/"))
async def search_handler(message: types.Message):
    query = message.text.strip()
    if len(normalize(query)) < 3:
        await message.answer("🔍 Qidirish uchun kamida 3 ta harf yozing.")
        return

    found = search_books(query)
    if not found:
        await message.answer("😕 Hech narsa topilmadi. Nomini boshqacha yozib ko'ring yoki katalogdan qidiring.")
        return

    shown = found[:10]
    text = f"🔎 <b>{len(found)} ta natija topildi:</b>"
    if len(found) > len(shown):
        text += f"\n(Dastlabki {len(shown)} tasi ko'rsatildi, aniqroq yozing)"
    await message.answer(text, reply_markup=books_keyboard(shown), parse_mode="HTML")


# ======================================================================
async def main():
    if not TOKEN:
        raise SystemExit(
            "BOT_TOKEN topilmadi. Avval BotFather'dan yangi token oling va "
            "BOT_TOKEN muhit o'zgaruvchisiga yozing."
        )
    bot = Bot(token=TOKEN)
    print(f"Ziyo Kutubxonasi boti ishga tushdi... (jami {len(BOOKS)} ta kitob)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())