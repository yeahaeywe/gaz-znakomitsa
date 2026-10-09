
import os
import asyncio
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = None
db = None
dp = Dispatcher(storage=MemoryStorage())


# -------------------- РЕГИСТРАЦИЯ --------------------

class ProfileForm(StatesGroup):
    name = State()
    age_group = State()
    interests = State()
    bio = State()


AGE_GROUPS = {"13-15", "16-17", "18+"}


def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔎 Найти собеседника", callback_data="browse"
        )],
        [InlineKeyboardButton(
            text="💬 Мои чаты", callback_data="chats"
        )],
        [InlineKeyboardButton(
            text="👤 Моя анкета", callback_data="myprofile"
        )],
        [
            InlineKeyboardButton(
                text="👁 Скрыть анкету", callback_data="hide"
            ),
            InlineKeyboardButton(
                text="🌟 Показывать анкету", callback_data="show"
            ),
        ],
    ])


def age_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="13–15", callback_data="age:13-15")],
        [InlineKeyboardButton(text="16–17", callback_data="age:16-17")],
        [InlineKeyboardButton(text="18+", callback_data="age:18+")],
    ])


# -------------------- POSTGRESQL --------------------

async def init_db():
    await db.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            user_id BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            age_group TEXT NOT NULL,
            interests TEXT NOT NULL,
            bio TEXT NOT NULL DEFAULT '',
            visible BOOLEAN NOT NULL DEFAULT TRUE
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS likes (
            from_id BIGINT NOT NULL,
            to_id BIGINT NOT NULL,
            UNIQUE(from_id, to_id)
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            user1 BIGINT NOT NULL,
            user2 BIGINT NOT NULL,
            UNIQUE(user1, user2)
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS blocks (
            from_id BIGINT NOT NULL,
            to_id BIGINT NOT NULL,
            UNIQUE(from_id, to_id)
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id BIGSERIAL PRIMARY KEY,
            reporter BIGINT NOT NULL,
            reported BIGINT NOT NULL,
            reason TEXT NOT NULL DEFAULT 'Не указана',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            user_id BIGINT PRIMARY KEY,
            partner_id BIGINT NOT NULL
        )
    """)


async def get_profile(user_id):
    return await db.fetchrow(
        "SELECT * FROM profiles WHERE user_id = $1",
        user_id,
    )


async def is_blocked(user1, user2):
    result = await db.fetchval("""
        SELECT EXISTS(
            SELECT 1 FROM blocks
            WHERE (from_id = $1 AND to_id = $2)
               OR (from_id = $2 AND to_id = $1)
        )
    """, user1, user2)
    return result


async def has_match(user1, user2):
    a, b = sorted((user1, user2))
    return await db.fetchval("""
        SELECT EXISTS(
            SELECT 1 FROM matches
            WHERE user1 = $1 AND user2 = $2
        )
    """, a, b)


async def close_chat_sessions(user_id):
    partner = await db.fetchval(
        "SELECT partner_id FROM chat_sessions WHERE user_id = $1",
        user_id,
    )

    await db.execute(
        "DELETE FROM chat_sessions WHERE user_id = $1",
        user_id,
    )

    if partner is not None:
        await db.execute(
            "DELETE FROM chat_sessions WHERE user_id = $1",
            partner,
        )

    return partner


# -------------------- СТАРТ --------------------

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()

    profile = await get_profile(message.from_user.id)

    if profile:
        await message.answer(
            f"💜 С возвращением, {profile['name']}!\n\n"
            "Добро пожаловать в VibeMatch.",
            reply_markup=menu(),
        )
        return

    await message.answer(
        "💜 Добро пожаловать в VibeMatch!\n\n"
        "Здесь можно найти друзей и собеседников по интересам.\n"
        "Не публикуй телефон, адрес, пароли и другие личные данные.\n\n"
        "Как тебя называть?"
    )
    await state.set_state(ProfileForm.name)


@dp.message(ProfileForm.name)
async def form_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()

    if not 2 <= len(name) <= 24:
        await message.answer(
            "Имя должно содержать от 2 до 24 символов."
        )
        return

    await state.update_data(name=name)
    await message.answer(
        "Выбери свою возрастную группу. "
        "Анкеты показываются только внутри той же группы.",
        reply_markup=age_keyboard(),
    )
    await state.set_state(ProfileForm.age_group)


@dp.callback_query(ProfileForm.age_group, F.data.startswith("age:"))
async def form_age(callback: CallbackQuery, state: FSMContext):
    age_group = callback.data.split(":", 1)[1]

    if age_group not in AGE_GROUPS:
        await callback.answer("Неверная возрастная группа.", show_alert=True)
        return

    await state.update_data(age_group=age_group)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Напиши свои интересы через запятую.")
    await state.set_state(ProfileForm.interests)
    await callback.answer()


@dp.message(ProfileForm.interests)
async def form_interests(message: Message, state: FSMContext):
    interests = (message.text or "").strip()

    if not 2 <= len(interests) <= 200:
        await message.answer(
            "Интересы должны содержать от 2 до 200 символов."
        )
        return

    await state.update_data(interests=interests)
    await message.answer(
        "Напиши короткое описание себя (до 300 символов).\n"
        "Не указывай телефон, адрес или пароли."
    )
    await state.set_state(ProfileForm.bio)


@dp.message(ProfileForm.bio)
async def form_bio(message: Message, state: FSMContext):
    bio = (message.text or "").strip()

    if len(bio) > 300:
        await message.answer(
            "Описание слишком длинное. Максимум 300 символов."
        )
        return

    data = await state.get_data()

    await db.execute("""
        INSERT INTO profiles
            (user_id, name, age_group, interests, bio, visible)
        VALUES ($1, $2, $3, $4, $5, TRUE)
        ON CONFLICT (user_id) DO UPDATE SET
            name = EXCLUDED.name,
            age_group = EXCLUDED.age_group,
            interests = EXCLUDED.interests,
            bio = EXCLUDED.bio,
            visible = TRUE
    """,
        message.from_user.id,
        data["name"],
        data["age_group"],
        data["interests"],
        bio,
    )

    await state.clear()
    await message.answer(
        "✅ Анкета сохранена в PostgreSQL!",
        reply_markup=menu(),
    )


# -------------------- МОЯ АНКЕТА --------------------

@dp.callback_query(F.data == "myprofile")
async def myprofile(callback: CallbackQuery):
    p = await get_profile(callback.from_user.id)

    if not p:
        await callback.message.answer("Сначала создай анкету: /start")
    else:
        status = "видна" if p["visible"] else "скрыта"
        await callback.message.answer(
            f"👤 {p['name']}\n"
            f"Возрастная группа: {p['age_group']}\n"
            f"Интересы: {p['interests']}\n"
            f"О себе: {p['bio'] or 'Не указано'}\n"
            f"Статус: {status}",
            reply_markup=menu(),
        )

    await callback.answer()


@dp.callback_query(F.data == "hide")
async def hide_profile(callback: CallbackQuery):
    await db.execute(
        "UPDATE profiles SET visible = FALSE WHERE user_id = $1",
        callback.from_user.id,
    )
    await callback.message.answer(
        "👁 Анкета скрыта.",
        reply_markup=menu(),
    )
    await callback.answer()


@dp.callback_query(F.data == "show")
async def show_profile(callback: CallbackQuery):
    profile = await get_profile(callback.from_user.id)

    if not profile:
        await callback.answer("Сначала создай анкету через /start", show_alert=True)
        return

    await db.execute(
        "UPDATE profiles SET visible = TRUE WHERE user_id = $1",
        callback.from_user.id,
    )
    await callback.message.answer(
        "💜 Анкета снова видна.",
        reply_markup=menu(),
    )
    await callback.answer()


# -------------------- ПОИСК АНКЕТ --------------------

@dp.callback_query(F.data == "browse")
async def browse(callback: CallbackQuery):
    uid = callback.from_user.id
    me = await get_profile(uid)

    if not me:
        await callback.message.answer("Сначала создай анкету: /start")
        await callback.answer()
        return

    p = await db.fetchrow("""
        SELECT p.*
        FROM profiles p
        WHERE p.visible = TRUE
          AND p.user_id != $1
          AND p.age_group = $2
          AND NOT EXISTS (
              SELECT 1 FROM blocks b
              WHERE (b.from_id = $1 AND b.to_id = p.user_id)
                 OR (b.from_id = p.user_id AND b.to_id = $1)
          )
          AND NOT EXISTS (
              SELECT 1 FROM likes l
              WHERE l.from_id = $1 AND l.to_id = p.user_id
          )
        ORDER BY RANDOM()
        LIMIT 1
    """, uid, me["age_group"])

    if not p:
        await callback.message.answer(
            "Пока нет новых анкет. Попробуй позже 💜",
            reply_markup=menu(),
        )
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💜 Нравится",
                    callback_data=f"like:{p['user_id']}",
                ),
                InlineKeyboardButton(
                    text="➡️ Дальше",
                    callback_data="browse",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Заблокировать",
                    callback_data=f"block:{p['user_id']}",
                ),
                InlineKeyboardButton(
                    text="⚠️ Жалоба",
                    callback_data=f"report:{p['user_id']}",
                ),
            ],
        ])

        await callback.message.answer(
            f"💜 {p['name']}\n"
            f"Интересы: {p['interests']}\n"
            f"О себе: {p['bio'] or 'Не указано'}",
            reply_markup=kb,
        )

    await callback.answer()


# -------------------- ЛАЙКИ И ВЗАИМНОСТЬ --------------------

@dp.callback_query(F.data.startswith("like:"))
async def like_profile(callback: CallbackQuery):
    uid = callback.from_user.id

    try:
        target = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная анкета.", show_alert=True)
        return

    if uid == target:
        await callback.answer("Это твоя анкета.", show_alert=True)
        return

    me = await get_profile(uid)
    other = await get_profile(target)

    if not me or not other or not other["visible"]:
        await callback.answer("Анкета больше недоступна.", show_alert=True)
        return

    if me["age_group"] != other["age_group"]:
        await callback.answer("Возрастные группы не совпадают.", show_alert=True)
        return

    if await is_blocked(uid, target):
        await callback.answer("Взаимодействие недоступно.", show_alert=True)
        return

    await db.execute("""
        INSERT INTO likes (from_id, to_id)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
    """, uid, target)

    mutual = await db.fetchval("""
        SELECT EXISTS(
            SELECT 1 FROM likes
            WHERE from_id = $1 AND to_id = $2
        )
    """, target, uid)

    if mutual:
        a, b = sorted((uid, target))

        await db.execute("""
            INSERT INTO matches (user1, user2)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
        """, a, b)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="💬 Открыть чат",
                callback_data=f"openchat:{target}",
            )]
        ])

        await callback.message.answer(
            "🎉 Взаимная симпатия! Вы оба хотите познакомиться.\n"
            "Чтобы начать переписку, открой чат.",
            reply_markup=kb,
        )

        other_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="💬 Открыть чат",
                callback_data=f"openchat:{uid}",
            )]
        ])

        try:
            await bot.send_message(
                target,
                "🎉 У тебя взаимная симпатия в VibeMatch!",
                reply_markup=other_kb,
            )
        except Exception:
            pass

        await callback.answer("Взаимная симпатия! 💜")
    else:
        await callback.answer("Лайк отправлен 💜")


# -------------------- СПИСОК ЧАТОВ --------------------

async def show_chats(message: Message, uid: int):
    rows = await db.fetch("""
        SELECT p.user_id, p.name
        FROM matches m
        JOIN profiles p
          ON p.user_id = CASE
              WHEN m.user1 = $1 THEN m.user2
              ELSE m.user1
          END
        WHERE (m.user1 = $1 OR m.user2 = $1)
          AND NOT EXISTS (
              SELECT 1 FROM blocks b
              WHERE (b.from_id = $1 AND b.to_id = p.user_id)
                 OR (b.from_id = p.user_id AND b.to_id = $1)
          )
        ORDER BY p.name
    """, uid)

    if not rows:
        await message.answer(
            "Пока нет взаимных симпатий.\n"
            "Найди собеседника через меню 💜",
            reply_markup=menu(),
        )
        return

    buttons = [
        [InlineKeyboardButton(
            text=f"💬 {row['name']}",
            callback_data=f"openchat:{row['user_id']}",
        )]
        for row in rows
    ]

    await message.answer(
        "💬 Твои чаты. Выбери собеседника:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.callback_query(F.data == "chats")
async def chats_callback(callback: CallbackQuery):
    await show_chats(callback.message, callback.from_user.id)
    await callback.answer()


@dp.message(Command("chats"))
async def chats_command(message: Message):
    await show_chats(message, message.from_user.id)


# -------------------- ОТКРЫТИЕ ЧАТА --------------------

@dp.callback_query(F.data.startswith("openchat:"))
async def open_chat(callback: CallbackQuery):
    uid = callback.from_user.id

    try:
        target = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный чат.", show_alert=True)
        return

    if uid == target or not await has_match(uid, target):
        await callback.answer("Взаимная симпатия не найдена.", show_alert=True)
        return

    if await is_blocked(uid, target):
        await callback.answer("Этот чат недоступен.", show_alert=True)
        return

    other = await get_profile(target)
    if not other:
        await callback.answer("Анкета удалена.", show_alert=True)
        return

    await db.execute("""
        INSERT INTO chat_sessions (user_id, partner_id)
        VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE
        SET partner_id = EXCLUDED.partner_id
    """, uid, target)

    reciprocal = await db.fetchval("""
        SELECT EXISTS(
            SELECT 1 FROM chat_sessions
            WHERE user_id = $1 AND partner_id = $2
        )
    """, target, uid)

    if reciprocal:
        await callback.message.answer(
            f"💬 Чат с {other['name']} открыт!\n\n"
            "Отправляй текстовые сообщения, фото, видео или голосовые.\n"
            "Команда /stopchat завершает текущий чат."
        )

        try:
            my_profile = await get_profile(uid)
            await bot.send_message(
                target,
                f"💬 {my_profile['name']} тоже открыл чат!\n"
                "Теперь вы можете переписываться.\n"
                "Команда /stopchat завершает чат.",
            )
        except Exception:
            pass
    else:
        await callback.message.answer(
            f"Ты выбрал(а) чат с {other['name']}.\n"
            "Ожидаем, пока собеседник тоже откроет чат. 💜"
        )

        try:
            await bot.send_message(
                target,
                f"💬 {callback.from_user.full_name} хочет открыть чат.\n"
                "Зайди в «Мои чаты» и выбери этого собеседника.",
            )
        except Exception:
            pass

    await callback.answer()


# -------------------- ЗАВЕРШЕНИЕ ЧАТА --------------------

@dp.message(Command("stopchat"))
async def stop_chat(message: Message):
    uid = message.from_user.id
    partner = await close_chat_sessions(uid)

    if partner is None:
        await message.answer("У тебя нет активного чата.")
        return

    await message.answer("Чат завершён. 💜")

    try:
        await bot.send_message(
            partner,
            "Собеседник завершил чат. Чтобы переписываться снова, "
            "откройте чат через «Мои чаты».",
        )
    except Exception:
        pass


# -------------------- БЛОКИРОВКИ И ЖАЛОБЫ --------------------

@dp.callback_query(F.data.startswith("block:"))
async def block_profile(callback: CallbackQuery):
    try:
        target = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная анкета.", show_alert=True)
        return

    uid = callback.from_user.id

    if uid == target:
        await callback.answer("Нельзя заблокировать себя.", show_alert=True)
        return

    await db.execute("""
        INSERT INTO blocks (from_id, to_id)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
    """, uid, target)

    partner = await close_chat_sessions(uid)

    await callback.message.answer("🚫 Пользователь заблокирован.")
    await callback.answer()

    if partner == target:
        try:
            await bot.send_message(
                target,
                "Переписка завершена, чат больше недоступен.",
            )
        except Exception:
            pass


@dp.callback_query(F.data.startswith("report:"))
async def report_profile(callback: CallbackQuery):
    try:
        target = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная анкета.", show_alert=True)
        return

    uid = callback.from_user.id

    if uid == target:
        await callback.answer("Нельзя пожаловаться на себя.", show_alert=True)
        return

    await db.execute("""
        INSERT INTO reports (reporter, reported, reason)
        VALUES ($1, $2, $3)
    """, uid, target, "Жалоба из карточки анкеты")

    await callback.message.answer(
        "⚠️ Жалоба записана. Для полноценной модерации "
        "понадобится отдельная панель администратора."
    )
    await callback.answer("Жалоба отправлена")


# -------------------- УДАЛЕНИЕ АНКЕТЫ --------------------

@dp.message(Command("delete"))
async def delete_profile(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id

    partner = await close_chat_sessions(uid)

    async with db.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM profiles WHERE user_id = $1", uid
            )
            await conn.execute(
                "DELETE FROM likes WHERE from_id = $1 OR to_id = $1", uid
            )
            await conn.execute(
                "DELETE FROM matches WHERE user1 = $1 OR user2 = $1", uid
            )
            await conn.execute(
                "DELETE FROM blocks WHERE from_id = $1 OR to_id = $1", uid
            )
            await conn.execute(
                "DELETE FROM reports WHERE reporter = $1 OR reported = $1", uid
            )
            await conn.execute(
                "DELETE FROM chat_sessions WHERE user_id = $1 OR partner_id = $1",
                uid,
            )

    if partner is not None:
        try:
            await bot.send_message(
                partner,
                "Собеседник удалил анкету. Чат завершён.",
            )
        except Exception:
            pass

    await message.answer(
        "✅ Анкета и связанные данные удалены.\n"
        "Напиши /start, чтобы начать заново."
    )


# -------------------- ПЕРЕСЫЛКА СООБЩЕНИЙ --------------------

@dp.message()
async def relay_message(message: Message):
    uid = message.from_user.id

    session = await db.fetchrow("""
        SELECT partner_id
        FROM chat_sessions
        WHERE user_id = $1
    """, uid)

    if not session:
        return

    target = session["partner_id"]

    reciprocal = await db.fetchval("""
        SELECT EXISTS(
            SELECT 1 FROM chat_sessions
            WHERE user_id = $1 AND partner_id = $2
        )
    """, target, uid)

    if not reciprocal:
        await message.answer(
            "⏳ Собеседник ещё не открыл чат. "
            "Когда он подключится, переписка начнётся."
        )
        return

    if await is_blocked(uid, target) or not await has_match(uid, target):
        await close_chat_sessions(uid)
        await message.answer("Этот чат больше недоступен.")
        return

    profile = await get_profile(uid)
    if not profile:
        await close_chat_sessions(uid)
        return

    try:
        if message.text:
            await bot.send_message(
                target,
                f"💬 {profile['name']}:\n{message.text}",
            )
        else:
            await bot.send_message(
                target,
                f"💬 Сообщение от {profile['name']}:",
            )
            await bot.copy_message(
                chat_id=target,
                from_chat_id=uid,
                message_id=message.message_id,
            )
    except Exception:
        await message.answer(
            "Не удалось отправить сообщение. "
            "Возможно, собеседник заблокировал бота."
        )


# -------------------- ЗАПУСК --------------------

async def main():
    global bot, db

    if not TOKEN:
        raise RuntimeError("Не задана переменная BOT_TOKEN")

    if not DATABASE_URL:
        raise RuntimeError("Не задана переменная DATABASE_URL")

    # Передаём asyncpg URL без параметров sslmode/channel_binding:
    # TLS включаем отдельно через ssl="require".
    parsed = urlsplit(DATABASE_URL)
    clean_url = urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        "",
        "",
    ))

    db = await asyncpg.create_pool(
        dsn=clean_url,
        ssl="require",
        min_size=1,
        max_size=5,
    )

    await init_db()

    bot = Bot(token=TOKEN)

    try:
        print("VibeMatch подключён к PostgreSQL. Запускаю бота...")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
