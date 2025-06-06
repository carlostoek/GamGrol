import asyncio
import io
import csv
import logging
from typing import List
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, PollAnswer
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import Column, Integer, String, select, JSON
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
import os

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    username = Column(String)
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
    type = Column(String)  # "post" or "poll"
    active = Column(Integer, default=1)
    post_id = Column(Integer, nullable=True)
    poll_id = Column(String, nullable=True)

class Reward(Base):
    __tablename__ = "rewards"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    description = Column(String)
    cost = Column(Integer)
    stock = Column(Integer)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as session:
        rewards = [
            Reward(name="Besito Digital", description="Un saludo personalizado, coqueto y tierno, exclusivo para ti.", cost=20, stock=5),
            Reward(name="Espía del Diván", description="Accede de forma anticipada a una publicación futura antes que nadie.", cost=30, stock=5),
            Reward(name="Toque Kinky", description="Un descuento sorpresa para usar en contenido exclusivo o sesiones.", cost=40, stock=5),
            Reward(name="Spoiler Indiscreto", description="Obtén una pista visual o textual de un futuro set antes del lanzamiento.", cost=50, stock=5),
            Reward(name="Entrada Furtiva al Diván", description="Acceso por 24 horas al canal VIP para quienes no están suscritos actualmente (o para regalar).", cost=60, stock=5),
            Reward(name="Confesión Prohibida", description="Diana responderá en privado una pregunta que elijas… sin filtros.", cost=70, stock=5),
            Reward(name="La Llave del Cajón Secreto", description="Acceso a una pieza de contenido 'perdido' que no está publicado en el canal.", cost=80, stock=5),
            Reward(name="Ritual de Medianoche", description="Un contenido especial que solo se entrega entre las 12:00 y la 1:00 AM. Misterioso y provocador.", cost=90, stock=5),
            Reward(name="Premonición Sensual", description="Recibe una visión anticipada de una sesión o colaboración futura, en forma de teaser o audio.", cost=100, stock=5),
            Reward(name="Capricho Premium", description="Canjeable por un video Premium completo a elección del catálogo (con restricciones de disponibilidad).", cost=150, stock=5)
        ]
        for reward in rewards:
            existing = await session.execute(select(Reward).filter_by(name=reward.name))
            if not existing.scalars().first():
                session.add(reward)
        await session.commit()

async def get_db():
    async with async_session() as session:
        yield session

async def clean_old_messages(chat_id: int):
    try:
        for message_id in range(1, 1000):
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"No se pudieron eliminar mensajes antiguos: {e}")

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

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Perfil"), KeyboardButton(text="Misiones")],
        [KeyboardButton(text="Tienda"), KeyboardButton(text="Ranking")]
    ],
    resize_keyboard=True
)

inline_main_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Perfil", callback_data="menu_perfil")],
    [InlineKeyboardButton(text="Misiones", callback_data="menu_misiones")],
    [InlineKeyboardButton(text="Tienda", callback_data="menu_tienda")],
    [InlineKeyboardButton(text="Ranking", callback_data="menu_ranking")]
])

@router.message(Command("start"))
async def cmd_start(message: Message):
    logger.info(f"Procesando /start para usuario {message.from_user.id}")
    await clean_old_messages(message.chat.id)
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
    chat_id = message.chat.id if isinstance(message, Message) else message.message.chat.id
    logger.info(f"Procesando Perfil para usuario {user_id}")
    await clean_old_messages(chat_id)
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
    chat_id = message.chat.id if isinstance(message, Message) else message.message.chat.id
    logger.info(f"Procesando Misiones para usuario {user_id}")
    await clean_old_messages(chat_id)
    async with async_session() as session:
        try:
            missions = await session.execute(select(Mission).filter_by(active=1))
            missions = missions.scalars().all()
            response = "Misiones disponibles:\n"
            if not missions:
                response += "No hay misiones activas en el canal. ¡Prueba esta misión temporal!\n"
            else:
                for mission in missions:
                    response += f"- {mission.title}: {mission.points} puntos\n"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Pruébame para sumar puntos", callback_data="test_points")],
                [InlineKeyboardButton(text="Volver al Menú", callback_data="back_to_menu")]
            ])
            if isinstance(message, Message):
                await message.answer(response, reply_markup=keyboard)
            else:
                await message.message.edit_text(response, reply_markup=keyboard)
                await message.answer()
        except Exception as e:
            logger.error(f"Error en Misiones: {e}")
            response = "Ocurrió un error al mostrar misiones."
            if isinstance(message, Message):
                await message.answer(response)
            else:
                await message.message.answer(response)
                await message.answer()

@router.callback_query(F.data == "test_points")
async def handle_test_points(callback: CallbackQuery):
    logger.info(f"Procesando botón de prueba para usuario {callback.from_user.id}")
    await clean_old_messages(callback.message.chat.id)
    async with async_session() as session:
        try:
            user = await session.execute(select(User).filter_by(telegram_id=callback.from_user.id))
            user = user.scalars().first()
            if user:
                test_mission_id = "test_mission"
                if test_mission_id not in user.completed_missions:
                    user.points += 5
                    user.completed_missions.append(test_mission_id)
                    await session.commit()
                    level_up = await check_level_up(user, session)
                    msg = "¡Prueba exitosa! Ganaste 5 puntos."
                    if level_up:
                        msg += f"\n¡Subiste al nivel {user.level}!"
                    await callback.message.answer(msg)
                else:
                    await callback.message.answer("Ya probaste esta misión.")
            else:
                await callback.message.answer("Usuario no encontrado. Usa /start primero.")
            await callback.answer()
        except Exception as e:
            logger.error(f"Error en handle_test_points: {e}")
            await callback.message.answer("Ocurrió un error al procesar la misión de prueba.")

@router.message(F.text == "Tienda")
@router.callback_query(F.data == "menu_tienda")
async def show_store(message: Message | CallbackQuery):
    user_id = message.from_user.id if isinstance(message, Message) else message.from_user.id
    chat_id = message.chat.id if isinstance(message, Message) else message.message.chat.id
    logger.info(f"Procesando Tienda para usuario {user_id}")
    await clean_old_messages(chat_id)
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
            response = "Tienda de recompensas:\nHaz clic para ver detalles y confirmar."
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"{r.name} ({r.cost} pts)", callback_data=f"reward_{r.id}")]
                for r in rewards
            ])
            if isinstance(message, Message):
                await message.answer(response, reply_markup=keyboard)
            else:
                await message.message.edit_text(response, reply_markup=keyboard)
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
    await clean_old_messages(callback.message.chat.id)
    reward_id = int(callback.data.split("_")[1])
    async with async_session() as session:
        try:
            reward = await session.get(Reward, reward_id)
            user = await session.execute(select(User).filter_by(telegram_id=callback.from_user.id))
            user = user.scalars().first()
            if reward and user:
                response = (
                    f"🎁 **{reward.name}** ({reward.cost} pts)\n"
                    f"Descripción: {reward.description}\n"
                    f"Tus puntos: {user.points}\n"
                )
                if reward.stock > 0 and user.points >= reward.cost:
                    response += "¡Puedes canjear esta recompensa! Confirma abajo."
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="Confirmar Canje", callback_data=f"confirm_reward_{reward.id}")],
                        [InlineKeyboardButton(text="Volver a Tienda", callback_data="menu_tienda")]
                    ])
                else:
                    response += "No tienes suficientes puntos o la recompensa está agotada."
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="Volver a Tienda", callback_data="menu_tienda")]
                    ])
                await callback.message.edit_text(response, reply_markup=keyboard)
            else:
                await callback.message.edit_text("Recompensa o usuario no encontrado.")
            await callback.answer()
        except Exception as e:
            logger.error(f"Error en handle_reward: {e}")
            await callback.message.edit_text("Ocurrió un error al mostrar la recompensa.")

@router.callback_query(F.data.startswith("confirm_reward_"))
async def handle_confirm_reward(callback: CallbackQuery):
    logger.info(f"Procesando confirmación de recompensa para usuario {callback.from_user.id}")
    await clean_old_messages(callback.message.chat.id)
    reward_id = int(callback.data.split("_")[2])
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
                    await callback.message.edit_text(f"¡Canjeaste {reward.name}! Te contactaremos con los detalles.")
                else:
                    await callback.message.edit_text("No tienes suficientes puntos.")
            else:
                await callback.message.edit_text("Recompensa no disponible.")
            await callback.answer()
        except Exception as e:
            logger.error(f"Error en handle_confirm_reward: {e}")
            await callback.message.edit_text("Ocurrió un error al canjear la recompensa.")

@router.message(F.text == "Ranking")
@router.callback_query(F.data == "menu_ranking")
async def show_ranking(message: Message | CallbackQuery):
    user_id = message.from_user.id if isinstance(message, Message) else message.from_user.id
    chat_id = message.chat.id if isinstance(message, Message) else message.message.chat.id
    logger.info(f"Procesando Ranking para usuario {user_id}")
    await clean_old_messages(chat_id)
    async with async_session() as session:
        try:
            users = await session.execute(select(User).order_by(User.points.desc()).limit(10))
            users = users.scalars().all()
            ranking_text = "🏆 Top 10 Jugadores:\n"
            for i, user in enumerate(users, 1):
                display_name = user.username or str(user.telegram_id)
                if user.telegram_id == user_id:
                    name = f"@{display_name}"
                else:
                    name = f"@{display_name[0]}..."
                ranking_text += f"{i}. {name} - {user.points} pts (Nivel {user.level})\n"
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
                writer.writerow([user.telegram_id, us