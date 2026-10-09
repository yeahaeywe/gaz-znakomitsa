
import os
import asyncio
import aiosqlite

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)

TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "vibematch.db")

bot = None
dp = Dispatcher(storage=MemoryStorage())


class ProfileForm(StatesGroup):
    name = State()
    age_group = State()
    interests = State()
    bio = State()


def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔎 Найти собеседника", callback_data="browse")],
        [InlineKeyboardButton(text="👤 Моя анкета", callback_data="myprofile")],
        [InlineKeyboardButton(text="👁 Скрыть анкету", callback_data="hide")],
        [InlineKeyboardButton(text="🌟 Показывать анкету", callback_data="show")]
    ])


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
        await db.commit()


async def get_profile(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM profiles WHERE user_id = ?", (user_id,)
        )
        return await cur.fetchone()


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "💜 Добро пожаловать в VibeMatch!\n\n"
        "Здесь можно найти друзей и собеседников по интересам.\n"
        "Не публикуй телефон, адрес или другие личные данные.\n\n"
        "Создадим твою анкету? Напиши, как тебя называть."
    )
    await state.set_state(ProfileForm.name)


@dp.message(ProfileForm.name)
async def form_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not 2 <= len(name) <= 24:
        await message.answer("Имя должно содержать от 2 до 24 символов.")
        return
    await state.update_data(name=name)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="13–15", callback_data="age:13-15")],
        [InlineKeyboardButton(text="16–17", callback_data="age:16-17")],
        [InlineKeyboardButton(text="18+", callback_data="age:18+")],
    ])
    await message.answer(
        "Выбери свою возрастную группу. Анкеты будут показываться "
        "только людям из той же группы.",
        reply_markup=kb
    )
    await state.set_state(ProfileForm.age_group)


@dp.callback_query(ProfileForm.age_group, F.data.startswith("age:"))
async def form_age(callback: CallbackQuery, state: FSMContext):
    age_group = callback.data.split(":", 1)[1]
    await state.update_data(age_group=age_group)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Напиши свои интересы через запятую.")
    await state.set_state(ProfileForm.interests)
    await callback.answer()


@dp.message(ProfileForm.interests)
async def form_interests(message: Message, state: FSMContext):
    interests = (message.text or "").strip()
    if not 2 <= len(interests) <= 200:
        await message.answer("Укажи интересы длиной до 200 символов.")
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
        await message.answer("Описание слишком длинное. Максимум 300 символов.")
        return

    data = await state.get_data()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO profiles
                (user_id, name, age_group, interests, bio, visible)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                name=excluded.name,
                age_group=excluded.age_group,
                interests=excluded.interests,
                bio=excluded.bio,
                visible=1
        """, (
            message.from_user.id, data["name"], data["age_group"],
            data["interests"], bio
        ))
        await db.commit()

    await state.clear()
    await message.answer("✅ Анкета сохранена!", reply_markup=menu())


@dp.callback_query(F.data == "myprofile")
async def myprofile(callback: CallbackQuery):
    p = await get_profile(callback.from_user.id)
    if not p:
        await callback.message.answer("Сначала создай анкету командой /start.")
    else:
        await callback.message.answer(
            f"👤 {p['name']}\n"
            f"Возрастная группа: {p['age_group']}\n"
            f"Интересы: {p['interests']}\n"
            f"О себе: {p['bio'] or 'Не указано'}\n"
            f"Статус: {'видна' if p['visible'] else 'скрыта'}",
            reply_markup=menu()
        )
    await callback.answer()


@dp.callback_query(F.data == "hide")
async def hide_profile(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE profiles SET visible=0 WHERE user_id=?",
            (callback.from_user.id,)
        )
        await db.commit()
    await callback.message.answer("👁 Анкета скрыта.", reply_markup=menu())
    await callback.answer()


@dp.callback_query(F.data == "show")
async def show_profile(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE profiles SET visible=1 WHERE user_id=?",
            (callback.from_user.id,)
        )
        await db.commit()
    await callback.message.answer("💜 Анкета снова видна.", reply_markup=menu())
    await callback.answer()


@dp.callback_query(F.data == "browse")
async def browse(callback: CallbackQuery):
    uid = callback.from_user.id
    me = await get_profile(uid)
    if not me:
        await callback.message.answer("Сначала создай анкету: /start")
        await callback.answer()
        return

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT p.* FROM profiles p
            WHERE p.visible=1 AND p.user_id != ?
              AND p.age_group = ?
              AND p.user_id NOT IN (
                  SELECT to_id FROM blocks WHERE from_id=?
              )
              AND p.user_id NOT IN (
                  SELECT from_id FROM blocks WHERE to_id=?
              )
              AND p.user_id NOT IN (
                  SELECT to_id FROM likes WHERE from_id=?
              )
            ORDER BY RANDOM() LIMIT 1
        """, (uid, me["age_group"], uid, uid, uid))
        p = await cur.fetchone()

    if not p:
        await callback.message.answer(
            "Пока нет новых анкет. Попробуй позже 💜",
            reply_markup=menu()
        )
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💜 Нравится", callback_data=f"like:{p['user_id']}"
                ),
                InlineKeyboardButton(
                    text="➡️ Дальше", callback_data="browse"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Заблокировать", callback_data=f"block:{p['user_id']}"
                ),
                InlineKeyboardButton(
                    text="⚠️ Жалоба", callback_data=f"report:{p['user_id']}"
                )
            ]
        ])
        await callback.message.answer(
            f"💜 {p['name']}\n"
            f"Интересы: {p['interests']}\n"
            f"О себе: {p['bio'] or 'Не указано'}",
            reply_markup=kb
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("like:"))
async def like_profile(callback: CallbackQuery):
    uid = callback.from_user.id
    target = int(callback.data.split(":")[1])
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

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM blocks WHERE "
            "(from_id=? AND to_id=?) OR (from_id=? AND to_id=?)",
            (uid, target, target, uid)
        )
        if await cur.fetchone():
            await callback.answer("Взаимодействие недоступно.", show_alert=True)
            return

        await db.execute(
            "INSERT OR IGNORE INTO likes VALUES (?, ?)", (uid, target)
        )
        cur = await db.execute(
            "SELECT 1 FROM likes WHERE from_id=? AND to_id=?",
            (target, uid)
        )
        mutual = await cur.fetchone()

        if mutual:
            a, b = sorted((uid, target))
            await db.execute(
                "INSERT OR IGNORE INTO matches VALUES (?, ?)", (a, b)
            )
        await db.commit()

    if mutual:
        await callback.message.answer(
            "🎉 Взаимная симпатия! Вы оба заинтересованы в знакомстве.\n"
            "Пока личный чат через бота ещё не подключён."
        )
        try:
            await bot.send_message(
                target, "🎉 У тебя новая взаимная симпатия в VibeMatch!"
            )
        except Exception:
            pass
    else:
        await callback.answer("Лайк отправлен 💜")
    await callback.answer()


@dp.callback_query(F.data.startswith("block:"))
async def block_profile(callback: CallbackQuery):
    uid = callback.from_user.id
    target = int(callback.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO blocks VALUES (?, ?)", (uid, target)
        )
        await db.commit()
    await callback.message.answer("Пользователь заблокирован.")
    await callback.answer()


@dp.callback_query(F.data.startswith("report:"))
async def report_profile(callback: CallbackQuery):
    uid = callback.from_user.id
    target = int(callback.data.split(":")[1])
    if uid == target:
        await callback.answer()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reports VALUES (?, ?, ?)",
            (uid, target, "Жалоба из карточки анкеты")
        )
        await db.commit()
    await callback.message.answer(
        "Жалоба принята. Перед запуском для широкой аудитории "
        "нужно подключить очередь модерации."
    )
    await callback.answer()


@dp.message(Command("delete"))
async def delete_profile(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        for table in ("profiles", "likes", "matches", "blocks", "reports"):
            if table == "profiles":
                await db.execute(
                    "DELETE FROM profiles WHERE user_id=?", (uid,)
                )
            elif table == "likes":
                await db.execute(
                    "DELETE FROM likes WHERE from_id=? OR to_id=?", (uid, uid)
                )
            elif table == "matches":
                await db.execute(
                    "DELETE FROM matches WHERE user1=? OR user2=?", (uid, uid)
                )
            elif table == "blocks":
                await db.execute(
                    "DELETE FROM blocks WHERE from_id=? OR to_id=?", (uid, uid)
                )
            else:
                await db.execute(
                    "DELETE FROM reports WHERE reporter=?", (uid,)
                )
        await db.commit()
    await message.answer("Анкета и связанные данные удалены. /start — начать заново.")


async def main():
    global bot

    if not TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN")

    bot = Bot(token=TOKEN)
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

