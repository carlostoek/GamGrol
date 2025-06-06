import asyncio
import logging
import os
import csv
import io
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, PollAnswer
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
CHANNEL_ID = int(os.getenv("CHANNEL_ID", -1001234567890))  # ID del canal VIP
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
    type = Column(String)  # "post" o "poll"
    post_id = Column(Integer, nullable=True)  # ID del mensaje en el canal
    poll_id = Column(String, nullable=True)  # ID de la encuesta
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

# Función auxiliar para limpiar mensajes antiguos
async def clean_old_messages(chat_id: int):
    try:
        # Intentar eliminar los últimos 50 mensajes del bot
        for message_id in range(1, 1000):  # Rango amplio para buscar mensajes
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception:
                continue  # Ignorar mensajes que no existen o no se pueden eliminar
    except Exception as e:
        logger.debug(f"No se pudieron eliminar mensajes antiguos: {e}")


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
            response = "Misiones disponibles:\n"
            if not missions:
                response += "No hay misiones activas en el canal. ¡Prueba esta misión temporal!\n"
            else:
                for mission in missions:
                    response += f"- {mission.title}: {mission.points} puntos\n"
            # Botón temporal "Pruébame para sumar puntos"
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

# Manejador para el botón temporal "Pruébame para sumar puntos"
@router.callback_query(F.data == "test_points")
async def handle_test_points(callback: CallbackQuery):
    logger.info(f"Procesando botón de prueba para usuario {callback.from_user.id}")
    async with async_session() as session:
        try:
            user = await session.execute(select(User).filter_by(telegram_id=callback.from_user.id))
            user = user.scalars().first()
            if user:
                # Usamos un identificador único para la misión de prueba
                test_mission_id = "test_mission"
                if test_mission_id not in user.completed_missions:
                    user.points += 5  # Otorga 5 puntos
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
                display_name = user.username or str(user.telegram_id)
                if user.telegram_id == user_id:  # Mostrar nombre completo para el usuario que ejecuta
                    name = f"@{display_name}"
                else:  # Mostrar solo la primera letra para otros usuarios
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

# Publicar en el canal con botones inline
@router.message(Command("publicar"))
async def cmd_publish(message: Message):
    logger.info(f"Procesando /publicar para usuario {message.from_user.id}")
    if message.from_user.id != ADMIN_ID:
        await message.answer("No tienes permisos.")
        return
    if len(message.text.split()) < 2:
        await message.answer("Uso: /publicar <texto>")
        return
    post_text = " ".join(message.text.split()[1:])
    async with async_session() as session:
        try:
            mission = Mission(
                title=f"Reacción a publicación {post_text[:20]}...",
                description=post_text,
                points=5,
                type="post",
                active=1
            )
            session.add(mission)
            await session.commit()
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👍 +5 pts", callback_data=f"post_{mission.id}_up")],
                [InlineKeyboardButton(text="👎 +5 pts", callback_data=f"post_{mission.id}_down")]
            ])
            sent_message = await bot.send_message(CHANNEL_ID, post_text, reply_markup=keyboard)
            mission.post_id = sent_message.message_id
            await session.commit()
            await message.answer("Publicación enviada al canal.")
        except Exception as e:
            logger.error(f"Error en /publicar: {e}")
            await message.answer("Ocurrió un error al publicar.")

# Manejar clics en botones inline de publicaciones
@router.callback_query(F.data.startswith("post_"))
async def handle_post_reaction(callback: CallbackQuery):
    logger.info(f"Procesando reacción a publicación para usuario {callback.from_user.id}")
    data = callback.data.split("_")
    mission_id = int(data[1])
    async with async_session() as session:
        try:
            mission = await session.get(Mission, mission_id)
            user = await session.execute(select(User).filter_by(telegram_id=callback.from_user.id))
            user = user.scalars().first()
            if mission and user:
                if mission_id not in user.completed_missions:
                    user.points += mission.points
                    user.completed_missions.append(mission_id)
                    await award_achievement(user, "Primera Reacción", session)
                    await session.commit()
                    level_up = await check_level_up(user, session)
                    msg = f"¡Reacción registrada! Ganaste {mission.points} puntos."
                    if level_up:
                        msg += f"\n¡Subiste al nivel {user.level}!"
                    await callback.message.answer(msg)
                else:
                    await callback.message.answer("Ya reaccionaste a esta publicación.")
            else:
                await callback.message.answer("Publicación o usuario no encontrado.")
            await callback.answer()
        except Exception as e:
            logger.error(f"Error en handle_post_reaction: {e}")
            await callback.message.answer("Ocurrió un error al registrar la reacción.")

# Crear encuesta en el canal
@router.message(Command("encuesta"))
async def cmd_poll(message: Message):
    logger.info(f"Procesando /encuesta para usuario {message.from_user.id}")
    if message.from_user.id != ADMIN_ID:
        await message.answer("No tienes permisos.")
        return
    if len(message.text.split()) < 4:
        await message.answer("Uso: /encuesta <pregunta> <opción1> <opción2> [opción3...]")
        return
    args = message.text.split()[1:]
    question = args[0]
    options = args[1:]
    if len(options) < 2:
        await message.answer("Debe incluir al menos dos opciones.")
        return
    async with async_session() as session:
        try:
            mission = Mission(
                title=f"Encuesta: {question[:20]}...",
                description=question,
                points=10,
                type="poll",
                active=1
            )
            session.add(mission)
            await session.commit()
            poll = await bot.send_poll(
                CHANNEL_ID,
                question=question,
                options=options,
                is_anonymous=False,  # Necesario para detectar quién vota
                type="quiz" if len(options) == 4 else "regular"  # Quiz si tiene 4 opciones
            )
            mission.poll_id = poll.poll.id
            await session.commit()
            await message.answer("Encuesta enviada al canal.")
        except Exception as e:
            logger.error(f"Error en /encuesta: {e}")
            await message.answer("Ocurrió un error al crear la encuesta.")

# Manejar respuestas a encuestas
@router.poll_answer()
async def handle_poll_answer(poll_answer: PollAnswer):
    logger.info(f"Procesando respuesta a encuesta para usuario {poll_answer.user.id}")
    async with async_session() as session:
        try:
            mission = await session.execute(select(Mission).filter_by(poll_id=poll_answer.poll_id))
            mission = mission.scalars().first()
            user = await session.execute(select(User).filter_by(telegram_id=poll_answer.user.id))
            user = user.scalars().first()
            if mission and user:
                if mission.id not in user.completed_missions:
                    user.points += mission.points
                    user.completed_missions.append(mission.id)
                    await award_achievement(user, "Primera Encuesta", session)
                    await session.commit()
                    level_up = await check_level_up(user, session)
                    msg = f"¡Encuesta completada! Ganaste {mission.points} puntos."
                    if level_up:
                        msg += f"\n¡Subiste al nivel {user.level}!"
                    await bot.send_message(poll_answer.user.id, msg)
                else:
                    await bot.send_message(poll_answer.user.id, "Ya participaste en esta encuesta.")
            else:
                await bot.send_message(poll_answer.user.id, "Encuesta o usuario no encontrado.")
        except Exception as e:
            logger.error(f"Error en handle_poll_answer: {e}")
            await bot.send_message(poll_answer.user.id, "Ocurrió un error al registrar tu respuesta.")

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
