import asyncio
import logging
import os
import csv
import io
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from sqlalchemy import Column, Integer, String, JSON, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import IntegrityError

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 123456789))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db")

# Inicializar bot y dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# Base de datos (SQLAlchemy)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    username = Column(String, nullable=True)
    points = Column(Integer, default=0)
    level = Column(Integer, default=1)
    achievements = Column(JSON, default=[])
    completed_missions = Column(JSON, default=[])

class Mission(Base):
    __tablename__ = "missions"
    id = Column(Integer, primary_key=True)
    title = Column(String)
    description = Column(String)
    points = Column(Integer)
    type = Column(String)
    active = Column(Integer, default=1)

class Reward(Base):
    __tablename__ = "rewards"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    description = Column(String)
    cost = Column(Integer)
    stock = Column(Integer, default=1)

# Configuración de la base de datos
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as session:
        missions = [
            Mission(title="Trivia Diaria", description="Responde la trivia del día", points=10, type="daily"),
            Mission(title="Post Destacado", description="Clic en el post", points=5, type="daily")
        ]
        rewards = [
            Reward(name="Sticker Exclusivo", description="Un sticker único", cost=20, stock=10),
            Reward(name="Rol VIP", description="Acceso a canal VIP", cost=50, stock=5)
        ]
        for mission in missions:
            existing = await session.execute(select(Mission).filter_by(title=mission.title))
            if not existing.scalars().first():
                session.add(mission)
        for reward in rewards:
            existing = await session.execute(select(Reward).filter_by(name=reward.name))
            if not existing.scalars().first():
                session.add(reward)
        await session.commit()

async def get_db():
    async with async_session() as session:
        yield session

# Lógica de gamificación
async def award_points(user: User, points: int, session: AsyncSession):
    user.points += points
    await session.commit()

async def check_level_up(user: User, session: AsyncSession):
    level_thresholds = {2: 10, 3: 25, 4: 50, 5: 100}
    for level, points_needed in level_thresholds.items():
        if user.points >= points_needed and user.level < level:
            user.level = level
            await award_achievement(user, f"Nivel {level} Alcanzado", session)
            await session.commit()
            return True
    return False

async def award_achievement(user: User, achievement: str, session: AsyncSession):
    if achievement not in user.achievements:
        user.achievements.append(achievement)
        await session.commit()
        return True
    return False

# Menú fijo
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Perfil"), KeyboardButton(text="Misiones")],
        [KeyboardButton(text="Tienda"), KeyboardButton(text="Ranking")]
    ],
    resize_keyboard=True
)

# Menú inline para "Volver al Menú"
inline_main_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Perfil", callback_data="menu_perfil")],
    [InlineKeyboardButton(text="Misiones", callback_data="menu_misiones")],
    [InlineKeyboardButton(text="Tienda", callback_data="menu_tienda")],
    [InlineKeyboardButton(text="Ranking", callback_data="menu_ranking")]
])

# Handlers
@router.message(Command("start"))
async def cmd_start(message: Message):
    logger.info(f"Procesando /start para usuario {message.from_user.id}")
    async with async_session() as session:
        try:
            user = await session.execute(select(User).filter_by(telegram_id=message.from_user.id))
            user = user.scalars().first()
            if not user:
                user = User(telegram_id=message.from_user.id, username=message.from_user.username)
                session.add(user)
                await session.commit()
                logger.info(f"Usuario {message.from_user.id} creado")
            await message.answer(
                "¡Bienvenido al bot gamificado! 🎮\nUsa el menú para navegar.",
                reply_markup=main_menu
            )
        except IntegrityError:
            await message.answer(
                "¡Ya estás registrado! Usa el menú para navegar.",
                reply_markup=main_menu
            )
        except Exception as e:
            logger.error(f"Error en /start: {e}")
            await message.answer("Ocurrió un error al iniciar. Intenta de nuevo.")

@router.message(F.text == "Perfil")
@router.callback_query(F.data == "menu_perfil")
async def cmd_profile(message: Message | CallbackQuery):
    user_id = message.from_user.id if isinstance(message, Message) else message.from_user.id
    logger.info(f"Procesando Perfil para usuario {user_id}")
    async with async_session() as session:
        try:
            user = await session.execute(select(User).filter_by(telegram_id=user_id))
            user = user.scalars().first()
            if user:
                profile_text = (
                    f"👤 Perfil de @{user.username or user.telegram_id}\n"
                    f"📊 Puntos: {user.points}\n"
                    f"🏆 Nivel: {user.level}\n"
                    f"🎖 Logros: {', '.join(user.achievements) or 'Ninguno'}"
                )
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Volver al Menú", callback_data="back_to_menu")]
                ])
                if isinstance(message, Message):
                    await message.answer(profile_text, reply_markup=keyboard)
                else:
                    await message.message.edit_text(profile_text, reply_markup=keyboard)
                    await message.answer()
            else:
                response = "Por favor, usa /start primero."
                if isinstance(message, Message):
                    await message.answer(response)
                else:
                    await message.message.answer(response)
                    await message.answer()
        except Exception as e:
            logger.error(f"Error en Perfil: {e}")
            response = "Ocurrió un error al mostrar el perfil."
            if isinstance(message, Message):
                await message.answer(response)
            else:
                await message.message.answer(response)
                await message.answer()

@router.message(F.text == "Misiones")
@router.callback_query(F.data == "menu_misiones")
async def show_missions(message: Message | CallbackQuery):
    user_id = message.from_user.id if isinstance(message, Message) else message.from_user.id
    logger.info(f"Procesando Misiones para usuario {user_id}")
    async with async_session() as session:
        try:
            missions = await session.execute(select(Mission).filter_by(active=1))
            missions = missions.scalars().all()
            if not missions:
                response = "No hay misiones disponibles."
                if isinstance(message, Message):
                    await message.answer(response)
                else:
                    await message.message.edit_text(response)
                    await message.answer()
                return
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=mission.title, callback_data=f"mission_{mission.id}")]
                for mission in missions
            ])
            if isinstance(message, Message):
                await message.answer("Misiones disponibles:", reply_markup=keyboard)
            else:
                await message.message.edit_text("Misiones disponibles:", reply_markup=keyboard)
                await message.answer()
        except Exception as e:
            logger.error(f"Error en Misiones: {e}")
            response = "Ocurrió un error al mostrar misiones."
            if isinstance(message, Message):
                await message.answer(response)
            else:
                await message.message.answer(response)
                await message.answer()

@router.callback_query(F.data.startswith("mission_"))
async def handle_mission(callback: CallbackQuery):
    logger.info(f"Procesando misión para usuario {callback.from_user.id}")
    mission_id = int(callback.data.split("_")[1])
    async with async_session() as session:
        try:
            mission = await session.get(Mission, mission_id)
            user = await session.execute(select(User).filter_by(telegram_id=callback.from_user.id))
            user = user.scalars().first()
            if mission and user:
                if mission_id not in user.completed_missions:
                    user.points += mission.points
                    user.completed_missions.append(mission_id)
                    await award_achievement(user, "Primera Misión Completada", session)
                    await session.commit()
                    level_up = await check_level_up(user, session)
                    msg = f"¡Misión completada! Ganaste {mission.points} puntos."
                    if level_up:
                        msg += f"\n¡Subiste al nivel {user.level}!"
                    await callback.message.answer(msg)
                else:
                    await callback.message.answer("Ya completaste esta misión.")
            else:
                await callback.message.answer("Misión o usuario no encontrado.")
            await callback.answer()
        except Exception as e:
            logger.error(f"Error en handle_mission: {e}")
            await callback.message.answer("Ocurrió un error al completar la misión.")

@router.message(F.text == "Tienda")
@router.callback_query(F.data == "menu_tienda")
async def show_store(message: Message | CallbackQuery):
    user_id = message.from_user.id if isinstance(message, Message) else message.from_user.id
    logger.info(f"Procesando Tienda para usuario {user_id}")
    async with async_session() as session:
        try:
            rewards = await session.execute(select(Reward).filter(Reward.stock > 0))
            rewards = rewards.scalars().all()
            if not rewards:
                response = "No hay recompensas disponibles."
                if isinstance(message, Message):
                    await message.answer(response)
                else:
                    await message.message.edit_text(response)
                    await message.answer()
                return
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"{r.name} ({r.cost} pts)", callback_data=f"reward_{r.id}")]
                for r in rewards
            ])
            if isinstance(message, Message):
                await message.answer("Tienda de recompensas:", reply_markup=keyboard)
            else:
                await message.message.edit_text("Tienda de recompensas:", reply_markup=keyboard)
                await message.answer()
        except Exception as e:
            logger.error(f"Error en Tienda: {e}")
            response = "Ocurrió un error al mostrar la tienda."
            if isinstance(message, Message):
                await message.answer(response)
            else:
                await message.message.answer(response)
                await message.answer()

@router.callback_query(F.data.startswith("reward_"))
async def handle_reward(callback: CallbackQuery):
    logger.info(f"Procesando recompensa para usuario {callback.from_user.id}")
    reward_id = int(callback.data.split("_")[1])
    async with async_session() as session:
        try:
            reward = await session.get(Reward, reward_id)
            user = await session.execute(select(User).filter_by(telegram_id=callback.from_user.id))
            user = user.scalars().first()
            if reward and user and reward.stock > 0:
                if user.points >= reward.cost:
                    user.points -= reward.cost
                    reward.stock -= 1
                    await session.commit()
                    await callback.message.answer(f"¡Canjeaste {reward.name}!")
                else:
                    await callback.message.answer("No tienes suficientes puntos.")
            else:
                await callback.message.answer("Recompensa no disponible.")
            await callback.answer()
        except Exception as e:
            logger.error(f"Error en handle_reward: {e}")
            await callback.message.answer("Ocurrió un error al canjear la recompensa.")

@router.message(F.text == "Ranking")
@router.callback_query(F.data == "menu_ranking")
async def show_ranking(message: Message | CallbackQuery):
    user_id = message.from_user.id if isinstance(message, Message) else message.from_user.id
    logger.info(f"Procesando Ranking para usuario {user_id}")
    async with async_session() as session:
        try:
            users = await session.execute(select(User).order_by(User.points.desc()).limit(10))
            users = users.scalars().all()
            ranking_text = "🏆 Top 10 Jugadores:\n"
            for i, user in enumerate(users, 1):
                ranking_text += f"{i}. @{user.username or user.telegram_id} - {user.points} pts (Nivel {user.level})\n"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Volver al Menú", callback_data="back_to_menu")]
            ])
            if isinstance(message, Message):
                await message.answer(ranking_text, reply_markup=keyboard)
            else:
                await message.message.edit_text(ranking_text, reply_markup=keyboard)
                await message.answer()
        except Exception as e:
            logger.error(f"Error en Ranking: {e}")
            response = "Ocurrió un error al mostrar el ranking."
            if isinstance(message, Message):
                await message.answer(response)
            else:
                await message.message.answer(response)
                await message.answer()

@router.message(Command("exportar"))
async def export_data(message: Message):
    logger.info(f"Procesando /exportar para usuario {message.from_user.id}")
    if message.from_user.id != ADMIN_ID:
        await message.answer("No tienes permisos.")
        return
    async with async_session() as session:
        try:
            users = await session.execute(select(User))
            users = users.scalars().all()
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["telegram_id", "username", "points", "level", "achievements"])
            for user in users:
                writer.writerow([user.telegram_id, user.username, user.points, user.level, user.achievements])
            await message.answer_document(
                document=io.BytesIO(output.getvalue().encode()),
                filename="users_export.csv"
            )
        except Exception as e:
            logger.error(f"Error en exportar: {e}")
            await message.answer("Ocurrió un error al exportar datos.")

@router.message(Command("resetear"))
async def reset_season(message: Message):
    logger.info(f"Procesando /resetear para usuario {message.from_user.id}")
    if message.from_user.id != ADMIN_ID:
        await message.answer("No tienes permisos.")
        return
    async with async_session() as session:
        try:
            await session.execute("UPDATE users SET points = 0, level = 1, achievements = '[]', completed_missions = '[]'")
            await session.commit()
            await message.answer("Temporada reseteada.")
        except Exception as e:
            logger.error(f"Error en resetear: {e}")
            await message.answer("Ocurrió un error al resetear la temporada.")

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    logger.info(f"Procesando back_to_menu para usuario {callback.from_user.id}")
    try:
        await callback.message.edit_text("Elige una opción:", reply_markup=inline_main_menu)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error en back_to_menu: {e}")
        await callback.message.answer("Ocurrió un error al volver al menú.")
        await callback.answer()

# Inicialización y ejecución
async def main():
    try:
        await init_db()
        dp.include_router(router)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error en main: {e}")

if __name__ == "__main__":
    asyncio.run(main())
