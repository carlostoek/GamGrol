import os
import logging
import csv
from datetime import datetime, timedelta
from contextlib import suppress
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
import sqlite3
import asyncio

# Configuración inicial
logging.basicConfig(level=logging.INFO)
bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))
dp = Dispatcher()

# Base de datos
DB_NAME = "gamification.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Tabla de usuarios
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                 user_id INTEGER PRIMARY KEY,
                 username TEXT,
                 full_name TEXT,
                 points INTEGER DEFAULT 0,
                 level INTEGER DEFAULT 1,
                 last_active DATE
                 )''')
    
    # Tabla de logros
    c.execute('''CREATE TABLE IF NOT EXISTS achievements (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 name TEXT,
                 description TEXT,
                 icon TEXT
                 )''')
    
    # Tabla de logros de usuarios
    c.execute('''CREATE TABLE IF NOT EXISTS user_achievements (
                 user_id INTEGER,
                 achievement_id INTEGER,
                 unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                 FOREIGN KEY(user_id) REFERENCES users(user_id),
                 FOREIGN KEY(achievement_id) REFERENCES achievements(id)
                 )''')
    
    # Tabla de misiones
    c.execute('''CREATE TABLE IF NOT EXISTS missions (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 name TEXT,
                 description TEXT,
                 points INTEGER,
                 type TEXT,  -- daily/weekly
                 cooldown_hours INTEGER
                 )''')
    
    # Tabla de misiones completadas
    c.execute('''CREATE TABLE IF NOT EXISTS completed_missions (
                 user_id INTEGER,
                 mission_id INTEGER,
                 completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                 FOREIGN KEY(user_id) REFERENCES users(user_id),
                 FOREIGN KEY(mission_id) REFERENCES missions(id)
                 )''')
    
    # Tabla de tienda
    c.execute('''CREATE TABLE IF NOT EXISTS shop (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 name TEXT,
                 description TEXT,
                 cost INTEGER,
                 stock INTEGER DEFAULT -1  -- -1 = ilimitado
                 )''')
    
    # Tabla de eventos
    c.execute('''CREATE TABLE IF NOT EXISTS events (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 name TEXT,
                 description TEXT,
                 multiplier REAL DEFAULT 1.0,
                 active BOOLEAN DEFAULT 0,
                 start_time TIMESTAMP,
                 end_time TIMESTAMP
                 )''')
    
    # Insertar logros iniciales
    initial_achievements = [
        ("Primeros Pasos", "Completa tu primera misión", "🚀"),
        ("Nivel 5", "Alcanza el nivel 5", "⭐"),
        ("Comprometido", "Participa 3 días seguidos", "🔥"),
        ("Coleccionista", "Desbloquea 5 logros", "🏆"),
        ("Maestro de Trivias", "Responde correctamente 10 trivias", "🧠")
    ]
    
    c.executemany('INSERT OR IGNORE INTO achievements (name, description, icon) VALUES (?, ?, ?)', initial_achievements)
    
    # Insertar misiones iniciales
    initial_missions = [
        ("Visita Diaria", "Haz clic en el post destacado", 5, "daily", 24),
        ("Trivia Semanal", "Participa en la trivia de esta semana", 20, "weekly", 168),
        ("Explorador", "Visita 3 secciones diferentes", 15, "daily", 24),
        ("Comprador", "Adquiere un artículo en la tienda", 10, "weekly", 168),
        ("Social", "Comparte el canal con un amigo", 25, "daily", 24)
    ]
    
    c.executemany('INSERT OR IGNORE INTO missions (name, description, points, type, cooldown_hours) VALUES (?, ?, ?, ?, ?)', initial_missions)
    
    conn.commit()
    conn.close()

init_db()

# Clase para manejar la base de datos
class Database:
    @staticmethod
    def get_connection():
        return sqlite3.connect(DB_NAME)
    
    @staticmethod
    def get_user(user_id: int):
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        conn.close()
        return user
    
    @staticmethod
    def create_user(user: types.User):
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
                  (user.id, user.username, user.full_name))
        conn.commit()
        conn.close()
    
    @staticmethod
    def update_user_points(user_id: int, points: int):
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
        
        # Verificar si subió de nivel
        user = Database.get_user(user_id)
        if user:
            new_level = Database.calculate_level(user[3] + points)
            if new_level > user[4]:
                c.execute("UPDATE users SET level = ? WHERE user_id = ?", (new_level, user_id))
                conn.commit()
                conn.close()
                return new_level
        
        conn.commit()
        conn.close()
        return False
    
    @staticmethod
    def calculate_level(points: int):
        # Fórmula de niveles: nivel^2 * 10
        level = 1
        while points >= (level ** 2) * 10:
            level += 1
        return level
    
    @staticmethod
    def get_achievements(user_id: int):
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute('''SELECT a.id, a.name, a.description, a.icon 
                     FROM user_achievements ua
                     JOIN achievements a ON ua.achievement_id = a.id
                     WHERE ua.user_id = ?''', (user_id,))
        achievements = c.fetchall()
        conn.close()
        return achievements
    
    @staticmethod
    def unlock_achievement(user_id: int, achievement_name: str):
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM achievements WHERE name = ?", (achievement_name,))
        achievement = c.fetchone()
        
        if achievement:
            achievement_id = achievement[0]
            # Verificar si ya lo tiene
            c.execute("SELECT * FROM user_achievements WHERE user_id = ? AND achievement_id = ?", 
                      (user_id, achievement_id))
            if not c.fetchone():
                c.execute("INSERT INTO user_achievements (user_id, achievement_id) VALUES (?, ?)",
                          (user_id, achievement_id))
                conn.commit()
                conn.close()
                return True
        conn.close()
        return False
    
    @staticmethod
    def complete_mission(user_id: int, mission_id: int):
        conn = Database.get_connection()
        c = conn.cursor()
        
        # Verificar si ya completó la misión recientemente
        c.execute('''SELECT completed_at FROM completed_missions 
                     WHERE user_id = ? AND mission_id = ? 
                     ORDER BY completed_at DESC LIMIT 1''', (user_id, mission_id))
        last_completion = c.fetchone()
        
        if last_completion:
            last_time = datetime.strptime(last_completion[0], "%Y-%m-%d %H:%M:%S")
            mission = Database.get_mission(mission_id)
            if mission and (datetime.now() - last_time) < timedelta(hours=mission[4]):
                conn.close()
                return False
        
        # Registrar misión completada
        c.execute("INSERT INTO completed_missions (user_id, mission_id) VALUES (?, ?)",
                  (user_id, mission_id))
        
        # Obtener puntos de la misión
        mission = Database.get_mission(mission_id)
        if mission:
            points = mission[3]
            # Aplicar multiplicador de eventos activos
            multiplier = Database.get_active_multiplier()
            points = int(points * multiplier)
            
            # Actualizar puntos del usuario
            Database.update_user_points(user_id, points)
            
            # Verificar logros
            if mission_id == 1:  # Primera misión
                Database.unlock_achievement(user_id, "Primeros Pasos")
            
            conn.commit()
            conn.close()
            return points
        conn.close()
        return 0
    
    @staticmethod
    def get_mission(mission_id: int):
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM missions WHERE id = ?", (mission_id,))
        mission = c.fetchone()
        conn.close()
        return mission
    
    @staticmethod
    def get_active_missions(user_id: int):
        conn = Database.get_connection()
        c = conn.cursor()
        
        # Obtener todas las misiones
        c.execute("SELECT * FROM missions")
        all_missions = c.fetchall()
        
        # Filtrar misiones disponibles
        available_missions = []
        for mission in all_missions:
            mission_id = mission[0]
            c.execute('''SELECT completed_at FROM completed_missions 
                         WHERE user_id = ? AND mission_id = ?
                         ORDER BY completed_at DESC LIMIT 1''', (user_id, mission_id))
            last_completion = c.fetchone()
            
            if not last_completion:
                available_missions.append(mission)
            else:
                last_time = datetime.strptime(last_completion[0], "%Y-%m-%d %H:%M:%S")
                cooldown = timedelta(hours=mission[5])
                if (datetime.now() - last_time) > cooldown:
                    available_missions.append(mission)
        
        conn.close()
        return available_missions
    
    @staticmethod
    def get_shop_items():
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM shop")
        items = c.fetchall()
        conn.close()
        return items
    
    @staticmethod
    def create_shop_item(name: str, description: str, cost: int, stock: int = -1):
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("INSERT INTO shop (name, description, cost, stock) VALUES (?, ?, ?, ?)",
                  (name, description, cost, stock))
        conn.commit()
        conn.close()
    
    @staticmethod
    def create_event(name: str, description: str, multiplier: float, hours: int):
        conn = Database.get_connection()
        c = conn.cursor()
        now = datetime.now()
        end_time = now + timedelta(hours=hours)
        
        # Desactivar eventos anteriores
        c.execute("UPDATE events SET active = 0")
        
        # Crear nuevo evento
        c.execute('''INSERT INTO events (name, description, multiplier, active, start_time, end_time)
                     VALUES (?, ?, ?, 1, ?, ?)''',
                  (name, description, multiplier, now.strftime("%Y-%m-%d %H:%M:%S"), 
                   end_time.strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_active_multiplier():
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("SELECT multiplier FROM events WHERE active = 1 AND end_time > CURRENT_TIMESTAMP")
        event = c.fetchone()
        conn.close()
        return event[0] if event else 1.0
    
    @staticmethod
    def get_ranking():
        conn = Database.get_connection()
        c = conn.cursor()
        c.execute("SELECT user_id, username, points, level FROM users ORDER BY points DESC LIMIT 10")
        ranking = c.fetchall()
        conn.close()
        return ranking
    
    @staticmethod
    def reset_season():
        conn = Database.get_connection()
        c = conn.cursor()
        
        # Guardar historial
        c.execute('''CREATE TABLE IF NOT EXISTS season_history AS
                     SELECT user_id, username, points, level, datetime('now') AS reset_date
                     FROM users''')
        
        # Resetear puntos y niveles
        c.execute("UPDATE users SET points = 0, level = 1")
        
        # Limpiar misiones completadas
        c.execute("DELETE FROM completed_missions")
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def export_data():
        filename = "user_data.csv"
        conn = Database.get_connection()
        
        # Exportar usuarios
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            c = conn.cursor()
            c.execute("SELECT * FROM users")
            writer.writerow([i[0] for i in c.description])
            writer.writerows(c.fetchall())
        
        conn.close()
        return filename

# ======================
# HANDLERS PRINCIPALES
# ======================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    Database.create_user(message.from_user)
    await show_main_menu(message)

@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):
    await show_main_menu(message)

async def show_main_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👤 Perfil", callback_data="profile"),
        InlineKeyboardButton(text="📋 Misiones", callback_data="missions")
    )
    builder.row(
        InlineKeyboardButton(text="🏪 Tienda", callback_data="shop"),
        InlineKeyboardButton(text="🏆 Ranking", callback_data="ranking")
    )
    
    await message.answer(
        "🎮 Bienvenido al Sistema de Gamificación\n"
        "Elige una opción del menú:",
        reply_markup=builder.as_markup()
    )

# ======================
# PERFIL DE USUARIO
# ======================

@dp.callback_query(F.data == "profile"))
async def show_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = Database.get_user(user_id)
    
    if not user:
        await callback.answer("Usuario no encontrado")
        return
    
    points = user[3]
    level = user[4]
    achievements = Database.get_achievements(user_id)
    
    # Calcular progreso al siguiente nivel
    current_level_points = (level ** 2) * 10
    next_level_points = ((level + 1) ** 2) * 10
    progress = min(100, int((points - current_level_points) / (next_level_points - current_level_points) * 100))
    
    # Construir texto del perfil
    text = (
        f"👤 *Perfil de {callback.from_user.full_name}*\n\n"
        f"⭐ *Puntos:* `{points}`\n"
        f"🚀 *Nivel:* `{level}`\n"
        f"📊 *Progreso:* `{progress}%`\n\n"
        f"🏆 *Logros:* `{len(achievements)}/20`"
    )
    
    # Construir logros
    achievements_text = "\n".join([f"{a[3]} {a[1]}" for a in achievements[:3]])
    if achievements_text:
        text += f"\n\n{achievements_text}"
    
    # Botones
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Ver Todos los Logros", callback_data="all_achievements"),
        InlineKeyboardButton(text="Misiones Activas", callback_data="missions")
    )
    builder.row(InlineKeyboardButton(text="⬅️ Menú Principal", callback_data="main_menu"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

# ======================
# SISTEMA DE MISIONES
# ======================

@dp.callback_query(F.data == "missions"))
async def show_missions(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    missions = Database.get_active_missions(user_id)
    
    if not missions:
        text = "🎯 No tienes misiones disponibles en este momento"
    else:
        text = "🎯 *Misiones Activas*\n\n"
        for mission in missions:
            text += f"• {mission[1]} - `+{mission[3]} puntos`\n{mission[2]}\n\n"
    
    builder = InlineKeyboardBuilder()
    for mission in missions[:3]:  # Mostrar máximo 3 misiones
        builder.row(InlineKeyboardButton(
            text=f"✅ Completar: {mission[1]}",
            callback_data=f"complete_mission:{mission[0]}"
        ))
    
    builder.row(InlineKeyboardButton(text="⬅️ Menú Principal", callback_data="main_menu"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("complete_mission:"))
async def complete_mission(callback: types.CallbackQuery):
    mission_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    points_earned = Database.complete_mission(user_id, mission_id)
    
    if points_earned:
        # Verificar si desbloqueó algún logro
        user = Database.get_user(user_id)
        if user and user[4] >= 5:
            Database.unlock_achievement(user_id, "Nivel 5")
        
        await callback.answer(f"✅ ¡Misión completada! +{points_earned} puntos", show_alert=True)
        await show_missions(callback)
    else:
        await callback.answer("⏳ Esta misión no está disponible todavía", show_alert=True)

# ======================
# TIENDA DE RECOMPENSAS
# ======================

@dp.callback_query(F.data == "shop"))
async def show_shop(callback: types.CallbackQuery):
    items = Database.get_shop_items()
    
    if not items:
        text = "🏪 La tienda está vacía por ahora"
    else:
        text = "🏪 *Tienda de Recompensas*\n\n"
        for item in items:
            text += f"• *{item[1]}* - `{item[3]} puntos`\n{item[2]}\n\n"
    
    builder = InlineKeyboardBuilder()
    for item in items[:3]:  # Mostrar máximo 3 ítems
        builder.row(InlineKeyboardButton(
            text=f"🛒 Canjear: {item[1]}",
            callback_data=f"redeem:{item[0]}"
        ))
    
    builder.row(InlineKeyboardButton(text="⬅️ Menú Principal", callback_data="main_menu"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

# ======================
# RANKING DE USUARIOS
# ======================

@dp.callback_query(F.data == "ranking"))
async def show_ranking(callback: types.CallbackQuery):
    ranking = Database.get_ranking()
    
    if not ranking:
        text = "🏆 Todavía no hay datos para mostrar el ranking"
    else:
        text = "🏆 *Top 10 Jugadores*\n\n"
        for i, player in enumerate(ranking, 1):
            username = player[1] or f"Usuario {player[0]}"
            text += f"{i}. {username} - `{player[2]} puntos` (Nvl {player[3]})\n"
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔄 Actualizar", callback_data="ranking"))
    builder.row(InlineKeyboardButton(text="⬅️ Menú Principal", callback_data="main_menu"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

# ======================
# PANEL DE ADMINISTRACIÓN
# ======================

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != int(os.getenv("ADMIN_ID")):
        await message.answer("⛔ Acceso denegado")
        return
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✨ Activar Evento", callback_data="activate_event"),
        InlineKeyboardButton(text="🎁 Crear Recompensa", callback_data="create_reward")
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Resetear Temporada", callback_data="reset_season"),
        InlineKeyboardButton(text="📤 Exportar Datos", callback_data="export_data")
    )
    
    await message.ans
