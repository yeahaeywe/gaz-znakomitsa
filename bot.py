
import os
import asyncio
import aiosqlite

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
DB_PATH = os.getenv("DB_PATH", "vibematch.db")

bot = None
dp = Dispatcher(storage=MemoryStorage())


# -------------------- РЕГИСТРАЦИЯ --------------------

class ProfileForm(StatesGroup):
    name = State()
    age_group = State()
    interests = State()
    bio = State()


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
        [InlineKeyboardButton(
            text="👁 Скрыть анкету", callback_data="hide"
        )],
        [InlineKeyboardButton(
            text="🌟 Показывать анкету", callback_data="show"
        )],
    ])


def chat_button(partner_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💬 Открыть чат",
            callback_data=f"chatwith:{partner_id}",
        )]
    ])


# -------------------- БАЗА ДАННЫХ --------------------

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                age_group TEXT NOT NULL,
                interests TEXT NOT NULL,
                bio TEXT NOT NULL DEFAULT '',
                visible INTEGER NOT NULL DEFAULT 1
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS likes (
                from_id INTEGER NOT NULL,
                to_id INTEGER NOT NULL,
                UNIQUE(from_id, to_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                user1 INTEGER NOT NULL,
                user2 INTEGER NOT NULL,
                UNIQUE(user1, user2)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS blocks (
                from_id INTEGER NOT NULL,
                to_id INTEGER NOT NULL,
                UNIQUE(from_id, to_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                reporter INTEGER NOT NULL,
                reported INTEGER NOT NULL,
                reason TEXT NOT NULL DEFAULT 'Не указана'
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                user_id INTEGER PRIMARY KEY,
                partner_id INTEGER NOT NULL
            )
        """)

        await db.commit()


async def get_profile(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM profiles WHERE user_id = ?",
            (user_id,),
        )
        return await cur.fetchone()


async def is_blocked(uid, target):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT 1 FROM blocks
            WHERE (from_id = ? AND to_id = ?)
               OR (from_id = ? AND to_id = ?)
        """, (uid, target, target, uid))
        return await cur.fetchone() is not None


async def has_match(uid, target):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT 1 FROM matches
            WHERE (user1 = ? AND user2 = ?)
               OR (user1 = ? AND user2 = ?)
        """, (uid, target, target, uid))
        return await cur.fetchone() is not None


async def close_chat_sessions(uid, target=None):
    async with aiosqlite.connect(DB_PATH) as db:
        if target is None:
            await db.execute("""
                DELETE FROM chat_sessions
                WHERE user_id = ? OR partner_id = ?
            """, (uid, uid))
        else:
            await db.execute("""
                DELETE FROM chat_sessions
                WHERE (user_id = ? AND partner_id = ?)
                   OR (user_id = ? AND partner_id = ?)
            """, (uid, target, target, uid))
        await db.commit()


# -------------------- СТАРТ И АНКЕТА --------------------

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()

    profile = await get_profile(message.from_user.id)

    if profile:
        await message.answer(
            f"С возвращением в VibeMatch, {profile['name']}! 💜",
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

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="13–15", callback_data="age:13-15"
        )],
        [InlineKeyboardButton(
            text="16–17", callback_data="age:16-17"
        )],
        [InlineKeyboardButton(
            text="18+", callback_data="age:18+"
        )],
    ])

    await message.answer(
        "Выбери свою возрастную группу. "
        "Анкеты будут показываться только внутри этой группы.",
        reply_markup=kb,
    )
    await state.set_state(ProfileForm.age_group)


@dp.callback_query(ProfileForm.age_group, F.data.startswith("age:"))
async def form_age(callback: CallbackQuery, state: FSMContext):
    age_group = callback.data.split(":", 1)[1]

    await state.update_data(age_group=age_group)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Напиши свои интересы через запятую."
    )
    await state.set_state(ProfileForm.interests)
    await callback.answer()


@dp.message(ProfileForm.interests)
async def form_interests(message: Message, state: FSMContext):
    interests = (message.text or "").strip()

    if not 2 <= len(interests) <= 200:
        await message.answer(
            "Укажи интересы длиной от 2 до 200 символов."
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

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO profiles
                (user_id, name, age_group, interests, bio, visible)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                name = excluded.name,
                age_group = excluded.age_group,
                interests = excluded.interests,
                bio = excluded.bio,
                visible = 1
        """, (
            message.from_user.id,
            data["name"],
            data["age_group"],
            data["interests"],
            bio,
        ))
        await db.commit()

    await state.clear()
    await message.answer(
        "✅ Анкета сохранена!",
        reply_markup=menu(),
    )


# -------------------- МОЯ АНКЕТА --------------------

@dp.callback_query(F.data == "myprofile")
async def myprofile(callback: CallbackQuery):
    p = await get_profile(callback.from_user.id)

    if not p:
        await callback.message.answer(
            "Сначала создай анкету командой /start."
        )
    else:
        await callback.message.answer(
            f"👤 {p['name']}\n"
            f"Возрастная группа: {p['age_group']}\n"
            f"Интересы: {p['interests']}\n"
            f"О себе: {p['bio'] or 'Не указано'}\n"
            f"Статус: {'видна' if p['visible'] else 'скрыта'}",
            reply_markup=menu(),
        )

    await callback.answer()


@dp.callback_query(F.data == "hide")
async def hide_profile(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE profiles SET visible = 0 WHERE user_id = ?",
            (callback.from_user.id,),
        )
        await db.commit()

    await callback.message.answer(
        "👁 Анкета скрыта.",
        reply_markup=menu(),
    )
    await callback.answer()


@dp.callback_query(F.data == "show")
async def show_profile(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE profiles SET visible = 1 WHERE user_id = ?",
            (callback.from_user.id,),
        )
        await db.commit()

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
        await callback.message.answer(
            "Сначала создай анкету: /start"
        )
        await callback.answer()
        return

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cur = await db.execute("""
            SELECT p.* FROM profiles p
            WHERE p.visible = 1
              AND p.user_id != ?
              AND p.age_group = ?
              AND p.user_id NOT IN (
                  SELECT to_id FROM blocks WHERE from_id = ?
              )
              AND p.user_id NOT IN (
                  SELECT from_id FROM blocks WHERE to_id = ?
              )
              AND p.user_id NOT IN (
                  SELECT to_id FROM likes WHERE from_id = ?
              )
            ORDER BY RANDOM()
            LIMIT 1
        """, (
            uid, me["age_group"], uid, uid, uid
        ))

        p = await cur.fetchone()

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


# -------------------- ЛАЙКИ И СОВПАДЕНИЯ --------------------

@dp.callback_query(F.data.startswith("like:"))
async def like_profile(callback: CallbackQuery):
    uid = callback.from_user.id
    target = int(callback.data.split(":", 1)[1])

    if uid == target:
        await callback.answer(
            "Это твоя анкета.",
            show_alert=True,
        )
        return

    me = await get_profile(uid)
    other = await get_profile(target)

    if not me or not other or not other["visible"]:
        await callback.answer(
            "Анкета больше недоступна.",
            show_alert=True,
        )
        return

    if me["age_group"] != other["age_group"]:
        await callback.answer(
            "Возрастные группы не совпадают.",
            show_alert=True,
        )
        return

    if await is_blocked(uid, target):
        await callback.answer(
            "Взаимодействие недоступно.",
            show_alert=True,
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO likes VALUES (?, ?)",
            (uid, target),
        )

        cur = await db.execute(
            "SELECT 1 FROM likes WHERE from_id = ? AND to_id = ?",
            (target, uid),
        )
        mutual = await cur.fetchone() is not None

        if mutual:
            a, b = sorted((uid, target))
            await db.execute(
                "INSERT OR IGNORE INTO matches VALUES (?, ?)",
                (a, b),
            )

        await db.commit()

    if mutual:
        await callback.message.answer(
            "🎉 Взаимная симпатия!\n\n"
            "Вы оба заинтересованы в знакомстве. "
            "Нажми кнопку ниже, чтобы предложить начать общение.",
            reply_markup=chat_button(target),
        )

        try:
            await bot.send_message(
                target,
                "🎉 У тебя взаимная симпатия в VibeMatch!\n"
                "Открой чат, если хочешь начать общение.",
                reply_markup=chat_button(uid),
            )
        except Exception:
            pass

    else:
        await callback.answer("Лайк отправлен 💜")

    await callback.answer()


# -------------------- МОИ ЧАТЫ --------------------

async def get_user_chats(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cur = await db.execute("""
            SELECT p.user_id, p.name
            FROM matches m
            JOIN profiles p
              ON p.user_id = CASE
                  WHEN m.user1 = ? THEN m.user2
                  ELSE m.user1
              END
            WHERE (m.user1 = ? OR m.user2 = ?)
              AND NOT EXISTS (
                  SELECT 1 FROM blocks b
                  WHERE (b.from_id = ? AND b.to_id = p.user_id)
                     OR (b.from_id = p.user_id AND b.to_id = ?)
              )
            ORDER BY p.name
        """, (uid, uid, uid, uid, uid))

        return await cur.fetchall()


def chats_keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"💬 {row['name'][:40]}",
            callback_data=f"chatwith:{row['user_id']}",
        )]
        for row in rows
    ])


async def show_chats(message: Message, uid: int):
    rows = await get_user_chats(uid)

    if not rows:
        await message.answer(
            "Пока нет совпадений. Найди собеседника "
            "и дождись взаимного лайка 💜"
        )
        return

    await message.answer(
        "💬 Твои совпадения — выбери собеседника:",
        reply_markup=chats_keyboard(rows),
    )


@dp.message(Command("chats"))
async def chats_command(message: Message):
    await show_chats(message, message.from_user.id)


@dp.callback_query(F.data == "chats")
async def chats_button(callback: CallbackQuery):
    await show_chats(callback.message, callback.from_user.id)
    await callback.answer()


# -------------------- ОТКРЫТИЕ ЧАТА --------------------

@dp.callback_query(F.data.startswith("chatwith:"))
async def open_chat(callback: CallbackQuery):
    uid = callback.from_user.id

    try:
        target = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный чат.", show_alert=True)
        return

    if uid == target:
        await callback.answer(
            "Нельзя открыть чат с собой.",
            show_alert=True,
        )
        return

    me = await get_profile(uid)
    other = await get_profile(target)

    if not me or not other:
        await callback.answer(
            "Анкета недоступна.",
            show_alert=True,
        )
        return

    if me["age_group"] != other["age_group"]:
        await callback.answer(
            "Возрастные группы не совпадают.",
            show_alert=True,
        )
        return

    if not await has_match(uid, target) or await is_blocked(uid, target):
        await callback.answer(
            "Чат недоступен.",
            show_alert=True,
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO chat_sessions (user_id, partner_id)
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET partner_id = excluded.partner_id
        """, (uid, target))

        cur = await db.execute(
            "SELECT partner_id FROM chat_sessions WHERE user_id = ?",
            (target,),
        )
        target_session = await cur.fetchone()
        await db.commit()

    await callback.answer()

    if target_session and target_session[0] == uid:
        await callback.message.answer(
            f"💜 Чат с {other['name']} открыт!\n\n"
            "Отправляй сообщения прямо сюда.\n"
            "Завершить общение: /stopchat"
        )

        try:
            await bot.send_message(
                target,
                f"💜 Чат с {me['name']} открыт!\n\n"
                "Отправляй сообщения прямо сюда.\n"
                "Завершить общение: /stopchat",
            )
        except Exception:
            pass
    else:
        await callback.message.answer(
            f"💌 Запрос на общение с {other['name']} отправлен.\n"
            "Чат заработает, когда собеседник тоже его откроет."
        )

        try:
            await bot.send_message(
                target,
                f"💜 {me['name']} хочет начать общение в VibeMatch.",
                reply_markup=chat_button(uid),
            )
        except Exception:
            await callback.message.answer(
                "Не удалось уведомить собеседника. Попробуй позже."
            )


# -------------------- ЗАВЕРШЕНИЕ ЧАТА --------------------

@dp.message(Command("stopchat"))
async def stop_chat(message: Message):
    uid = message.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT partner_id FROM chat_sessions WHERE user_id = ?",
            (uid,),
        )
        row = await cur.fetchone()

    if not row:
        await message.answer("У тебя нет активного чата.")
        return

    target = row[0]
    await close_chat_sessions(uid, target)

    await message.answer(
        "🛑 Чат завершён.\n"
        "Чтобы начать общение снова, открой «Мои чаты»."
    )

    try:
        await bot.send_message(
            target,
            "🛑 Собеседник завершил чат. "
            "Чтобы общаться снова, открой «Мои чаты»."
        )
    except Exception:
        pass


# -------------------- БЛОКИРОВКА И ЖАЛОБЫ --------------------

@dp.callback_query(F.data.startswith("block:"))
async def block_profile(callback: CallbackQuery):
    uid = callback.from_user.id

    try:
        target = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный пользователь.")
        return

    if uid == target:
        await callback.answer()
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO blocks VALUES (?, ?)",
            (uid, target),
        )
        await db.commit()

    await close_chat_sessions(uid, target)

    await callback.message.answer(
        "🚫 Пользователь заблокирован. Общение закрыто."
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("report:"))
async def report_profile(callback: CallbackQuery):
    uid = callback.from_user.id

    try:
        target = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer()
        return

    if uid == target:
        await callback.answer()
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reports VALUES (?, ?, ?)",
            (uid, target, "Жалоба из карточки анкеты"),
        )
        await db.commit()

    await callback.message.answer(
        "⚠️ Жалоба принята. Спасибо за помощь в поддержании "
        "безопасного сообщества."
    )
    await callback.answer()


# -------------------- УДАЛЕНИЕ АНКЕТЫ --------------------

@dp.message(Command("delete"))
async def delete_profile(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id

    await close_chat_sessions(uid)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM profiles WHERE user_id = ?", (uid,)
        )
        await db.execute(
            "DELETE FROM likes WHERE from_id = ? OR to_id = ?",
            (uid, uid),
        )
        await db.execute(
            "DELETE FROM matches WHERE user1 = ? OR user2 = ?",
            (uid, uid),
        )
        await db.execute(
            "DELETE FROM blocks WHERE from_id = ? OR to_id = ?",
            (uid, uid),
        )
        await db.execute(
            "DELETE FROM reports WHERE reporter = ? OR reported = ?",
            (uid, uid),
        )
        await db.commit()

    await message.answer(
        "🗑 Анкета и связанные данные удалены. "
        "Напиши /start, чтобы начать заново."
    )


# -------------------- ПЕРЕДАЧА СООБЩЕНИЙ --------------------

@dp.message()
async def relay_chat_message(message: Message, state: FSMContext):
    if not message.from_user or message.chat.type != "private":
        return

    uid = message.from_user.id

    # Команды обрабатываются отдельными обработчиками.
    if message.text and message.text.startswith("/"):
        return

    # Не перехватываем сообщения, пока заполняется анкета.
    if await state.get_state():
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT partner_id FROM chat_sessions WHERE user_id = ?",
            (uid,),
        )
        session = await cur.fetchone()

    if not session:
        return

    target = session[0]

    if await is_blocked(uid, target) or not await has_match(uid, target):
        await close_chat_sessions(uid, target)
        await message.answer(
            "Чат больше недоступен. Проверь «Мои чаты»."
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT partner_id FROM chat_sessions WHERE user_id = ?",
            (target,),
        )
        reciprocal = await cur.fetchone()

    if not reciprocal or reciprocal[0] != uid:
        await message.answer(
            "💌 Запрос отправлен. Дождись, пока собеседник "
            "тоже откроет чат."
        )
        return

    sender = await get_profile(uid)

    if not sender:
        await message.answer(
            "Сначала создай анкету командой /start."
        )
        return

    try:
        if message.text:
            await bot.send_message(
                target,
                f"💬 {sender['name']}:\n{message.text[:3500]}",
            )
        else:
            # Копирует фото, видео, документы, стикеры,
            # голосовые и другие поддерживаемые сообщения.
            await bot.send_message(
                target,
                f"💬 Сообщение от {sender['name']}:",
            )
            await bot.copy_message(
                chat_id=target,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )

    except Exception:
        await message.answer(
            "Не удалось доставить сообщение. "
            "Возможно, собеседник больше не может получать сообщения "
            "от бота."
        )


# -------------------- ЗАПУСК --------------------

async def main():
    global bot

    if not TOKEN:
        raise RuntimeError(
            "Не задан BOT_TOKEN в переменных окружения хостинга."
        )

    bot = Bot(token=TOKEN)
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
