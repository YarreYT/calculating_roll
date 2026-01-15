import math
import re
import unicodedata
import random
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler
)
from telegram.constants import ParseMode
from telegram.error import BadRequest

# --- ИМПОРТ БАЗЫ ДАННЫХ ---
from game_data import (
    REFORGE_MODIFIERS,
    CONQUERORS_BLADE_STATS,
    DOOMBRINGER_STATS,
    FZH_STATS,
    LZS_STATS,
    ITEMS_MAPPING,
    PART_MAPPING,
    WOODEN_SWORD_THRESHOLD_PERCENT
)
from collections import deque

from config_storage import (
    load_allowed_topics, save_allowed_topics, get_group_topics,
    add_topic_to_group, remove_topic_from_group, clear_all_topics,
    set_allow_non_topic, is_topic_allowed, ALLOWED_TOPICS
)

ALLOWED_TOPICS = load_allowed_topics()

# user_id -> deque[msg_id]
_error_msgs: dict[int, deque[int]] = {}
# user_id -> last error text
_last_err_text: dict[int, str] = {}

# --- КОНФИГУРАЦИЯ ---
TOKEN = '8296615863:AAHWDGuMwqLOaGbLJ9xO9puwp8CDur8LNBQ'

GROWTH_RATE = 1 / 21
CALLBACK_CLOSE_REFORGE = "close_reforge"

user_armor_data = {}  # {user_id: {command, data: {helm, chest, legs}, stage, item_key, max_level, user_msg_id, bot_msg_id}}

# Константы этапов
STAGE_HELMET = "helm"
STAGE_CHEST = "chest"
STAGE_LEGS = "legs"

# Фразы для тех, кто пишет не в том топике
WRONG_TOPIC_TEXTS = [
    "Я не тут работаю. Понимаю, лень, но я работаю в других чатах",
    "Чё ты сюда пишешь, перейди в разрешённый чат и не еби мозги себе и админу",
    "Я не тут работаю, ёпта! Иди в разрешённый топик и там пиши, блять, команды! И начни с `!crhelp` ",
    "Чувак, ну ты чё. Не там пишешь. Пиши в разрешённом чате",
    "Долбаёб!!! Не сюда!!!! Иди в разрешённый чат",
    "Да ты тупой что ли, не здесь я работаю! Сука! Иди в разрешённый чат",
    "Да вроде же не глухие и не слепые. Ну, не первый раз же говорю вам ебланам, что с командами идите в разрешённый чат",
    "DURA: Я хуею с этой дуры"
]
WRONG_TOPIC_WEIGHTS = [10, 15, 10, 10, 20, 10, 5, 1]

WRONG_TOPIC_PICS = {
    "DURA": "https://www.meme-arsenal.com/memes/929438802e9418915479201d0e52c39d.jpg"
}
# --- НОВЫЕ КОНСТАНТЫ ДЛЯ НЕИЗВЕСТНЫХ КОМАНД ---
UNKNOWN_COMMAND_RESPONSES = {
    "Такой команды нет, еблан. Напиши !crhelp": 20,
    "Чёрный... Ой, то есть такой команды нет. !crhelp": 15,
    "Да ты тупой? Такой команды нет. Пиши !crhelp": 15,
    "Не знаю такой команды. Возможно, ты сам её придумал, долбоёб. !crhelp": 10,
    "Я хуею с этой дуры": 1,
}
UNKNOWN_COMMAND_PHOTOS = {
    "Я хуею с этой дуры": "https://www.meme-arsenal.com/memes/450c91d6864f8bbb1a3296a5537d19f7.jpg ",
}


def is_allowed_thread(update) -> bool:
    """
    Проверяет, что сообщение находится в разрешённом топике или чате.
    Работает для обычных сообщений и callback_query.
    В ЛС всегда разрешено.
    """
    # В ЛС всегда разрешено
    if update.effective_chat.type == 'private':
        return True

    # Для callback_query
    if hasattr(update, 'callback_query') and update.callback_query and update.callback_query.message:
        message = update.callback_query.message
    # Для обычных сообщений
    elif hasattr(update, 'effective_message') and update.effective_message:
        message = update.effective_message
    else:
        return False

    group_id = str(update.effective_chat.id)
    topic_id = message.message_thread_id

    return is_topic_allowed(group_id, topic_id)


def calculate_gold(base_cost: int, upg_level: int) -> int:
    """
    Вычисляет накопленную стоимость золота до определенного уровня.
    """
    if upg_level <= 0:
        return 0

    total_spent = 0
    current_cost = float(base_cost)

    for lvl in range(1, upg_level + 1):
        rounded_cost = round(current_cost)
        total_spent += rounded_cost
        current_cost = rounded_cost * 1.3

    return total_spent


def calculate_weapon_stat_at_level(base_value: float, target_level: int, is_corrupted: bool,
                                   reforge_mult: float) -> int:
    calc = base_value
    if is_corrupted:
        calc *= 1.5
    calc *= (1 + GROWTH_RATE * target_level)
    calc *= reforge_mult
    return math.floor(calc)


def calculate_armor_stat_at_level(base_val, level, is_corrupted, reforge_mult, item_type):
    if item_type == "weapon":
        return math.floor(base_val *
                          (1.5 if is_corrupted else 1.0) *
                          (1 + 0.047619047619 * level) *
                          reforge_mult)
    # --- броня ---
    current = base_val * (1.5 if is_corrupted else 1.0)
    raw = current * (1 + 0.047619047619 * level) * reforge_mult
    return round(raw + 0.45)


def infer_base_for_weapon(target_stat: float, level: int, is_corrupted: bool, reforge_mult: float) -> float:
    temp = target_stat / reforge_mult
    growth_factor = 1 + GROWTH_RATE * level
    base_before_corr = temp / growth_factor
    inferred = base_before_corr / 1.5 if is_corrupted else base_before_corr
    return inferred


def find_roll_for_armor(stats_dict: dict, target_stat: float, level: int, is_corrupted: bool) -> int:
    best_roll = 1
    min_diff = float('inf')
    for roll in range(1, 12):
        base = stats_dict[roll]
        computed = calculate_armor_stat_at_level(base, level, is_corrupted, 1.0, "armor")
        diff = abs(computed - target_stat)
        if diff < min_diff or (diff == min_diff and roll > best_roll):
            min_diff = diff
            best_roll = roll
    return best_roll


def determine_roll(stats_dict: dict, inferred_value: float) -> int:
    """
    Определяет ролл, находя базовое значение, которое ближе всего к inferred_value.
    Специальная обработка для Wooden Sword (только ролл 11).
    """
    # Для Wooden Sword (в словаре только ролл 11)
    if len(stats_dict) == 1 and 11 in stats_dict:
        return 11

    # Для остального оружия (роллы 1-11 или 6-11)
    if not stats_dict:
        raise ValueError("Словарь stats_dict пуст")

    best_roll = min(stats_dict.keys())  # Начинаем с минимального ролла
    best_diff = abs(inferred_value - stats_dict[best_roll])

    for roll in stats_dict.keys():
        current_diff = abs(inferred_value - stats_dict[roll])
        if current_diff < best_diff:
            best_diff = current_diff
            best_roll = roll

    return best_roll


def clean_args_from_separator(args: list) -> list:
    """Убирает знак '>' из аргументов, если пользователь его написал."""
    return [arg for arg in args if arg != '>']


ASC_WEAPON_KEYS = ['ws', 'mb', 'lk', 'me', 'pt', 'dd']
ASC_WEAPON_SHORT_NAMES = {
    'ws': 'W.S.',
    'mb': 'M.B.',
    'lk': 'L.K.',
    'me': 'M.E.',
    'pt': 'P.T.',
    'dd': 'D.D.'
}


def find_base_damage_for_asc(dmg: float, level: int, is_corrupted: bool, reforge_mult: float) -> tuple:
    """
    НАХОДИТ базовый урон и ролл для ASC оружия.
    Возвращает (base_dmg, roll, is_wooden_sword)

    1. Сначала проверяем, является ли это Wooden Sword V2
       (только ролл 11, база 10395)
    2. Если нет - ищем ролл через обратный расчет (6-11)
    """
    wooden_base = 10395
    wooden_calc = calculate_weapon_stat_at_level(wooden_base, level, is_corrupted, reforge_mult)

    # Проверяем Wooden Sword с погрешностью 10 единиц урона
    if abs(wooden_calc - dmg) < 10:
        return wooden_base, 11, True

    # Для остальных ASC мечей (ролл 6-11)
    inferred_base = infer_base_for_weapon(dmg, level, is_corrupted, reforge_mult)
    best_roll = 6
    best_diff = abs(CONQUERORS_BLADE_STATS[6] - inferred_base)

    for roll in range(7, 12):
        diff = abs(CONQUERORS_BLADE_STATS[roll] - inferred_base)
        if diff < best_diff:
            best_diff = diff
            best_roll = roll

    return CONQUERORS_BLADE_STATS[best_roll], best_roll, False


async def _send_error(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      error_message: str, _) -> bool:
    """
    Отправляет / редактирует error_message, удаляет сообщение игрока,
    через 3 с стирает ВСЕ свои ошибки пачкой.
    Возвращает True (выход из команды).
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    thread_id = update.effective_message.message_thread_id

    # удаляем сообщение игрока
    try:
        await update.message.delete()
    except Exception:
        pass

    # редактируем, если текст тот же
    if _last_err_text.get(user_id) == error_message and _error_msgs.get(user_id):
        try:
            mid = _error_msgs[user_id][-1]
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=mid,
                text=error_message,
                parse_mode=ParseMode.MARKDOWN,
                message_thread_id=thread_id
            )
            msg_id = mid
        except Exception:
            _last_err_text.pop(user_id, None)
            msg_id = None
    else:
        msg_id = None

    if not msg_id:
        try:
            msg = await context.bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=error_message,
                parse_mode=ParseMode.MARKDOWN
            )
            msg_id = msg.message_id
            _error_msgs.setdefault(user_id, deque()).append(msg_id)
            _last_err_text[user_id] = error_message
        except Exception:
            return True

    # 3-секундный таймер на пачку
    if len(_error_msgs[user_id]) == 1:
        async def _del_batch():
            await asyncio.sleep(3)
            msgs = _error_msgs.pop(user_id, deque())
            for mid in msgs:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass
            _last_err_text.pop(user_id, None)

        asyncio.create_task(_del_batch())
    return True


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def check_message_ownership(query, strict: bool = True) -> bool:
    """
    Проверяет, что пользователь является владельцем оригинального сообщения
    (того, на которое отвечает текущее сообщение с кнопками).

    :param query: CallbackQuery
    :param strict: Если True, при невозможности проверки возвращает False
                  Если False, при невозможности проверки возвращает True (совместимость)
    :return: True если пользователь владелец, False если нет
    """
    try:
        if query.message.reply_to_message:
            # В некоторых случаях reply_to_message может не содержать from_user (если сообщение удалено)
            if hasattr(query.message.reply_to_message, 'from_user') and query.message.reply_to_message.from_user:
                return query.message.reply_to_message.from_user.id == query.from_user.id
        # Если нет reply_to_message или from_user, в strict режиме блокируем
        return not strict
    except Exception as e:
        print(f"Ошибка при проверке ownership: {e}")
        return not strict


# --- CALLBACK ОБРАБОТЧИК ДЛЯ НОВЫХ КОМАНД ---

async def weapon_analysis_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    # 🛑 ПРОВЕРКА ВЛАДЕЛЬЦА
    if not check_message_ownership(query):
        await query.answer("Это не ваше сообщение!", show_alert=True)
        return

    await query.answer()

    # Обработка закрытия сообщения
    if query.data.startswith("close:"):
        await query.message.delete()
        try:
            parts = query.data.split(":", 2)
            if len(parts) > 1:
                message_id = int(parts[1])
                await context.bot.delete_message(
                    chat_id=query.message.chat.id,
                    message_id=message_id
                )
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
        return
    # Парсим callback_data
    data_parts = query.data.split(":")
    if len(data_parts) < 4:
        print(f"Слишком короткий callback_data: {query.data}")
        await query.answer("Ошибка: неверный формат callback", show_alert=True)
        return

    cmd_type = data_parts[0]  # asc, wasc, lasc, a, w, l
    item_key = data_parts[1]
    page = data_parts[2]

    # Получаем user_msg_id из последнего элемента
    try:
        user_msg_id = int(data_parts[-1])
    except (ValueError, IndexError):
        user_msg_id = None

    # === ОБРАБОТКА ASC КОМАНД (отдельно от старых) ===
    if cmd_type == 'asc':
        await _handle_asc_callback(query, data_parts, page)
        return

    if cmd_type == 'wasc':
        await _handle_wasc_callback(query, data_parts, page)
        return

    if cmd_type == 'lasc':
        await _handle_lasc_callback(query, data_parts, page)
        return

    # === ОБРАБОТКА СТАРЫХ КОМАНД (a, w, l) ===
    try:
        item_info = ITEMS_MAPPING[item_key]

        # Анализ оружия (!conq, !doom) - формат: a:item_key:page:dmg:upg:corr:reforge:user_msg_id
        if cmd_type == "a":
            if len(data_parts) != 8:
                await query.answer("Ошибка: неверный формат данных", show_alert=True)
                return

            dmg, upg, corr_str, reforge_name = float(data_parts[3]), int(data_parts[4]), data_parts[5], data_parts[6]
            corr = corr_str == 'y'
            reforge_mult = REFORGE_MODIFIERS.get(reforge_name, 1.0)

            base_stats = item_info['stats']
            inferred_base = infer_base_for_weapon(dmg, upg, corr, reforge_mult)
            roll = determine_roll(base_stats, inferred_base)
            base_dmg = base_stats[roll]

            if page == "total":
                text = generate_total_page(item_info, dmg, upg, corr, reforge_name, reforge_mult, roll, base_dmg)
            elif page == "process":
                text = generate_process_page(item_info, dmg, upg, corr, reforge_name, reforge_mult, roll, base_dmg)
            elif page == "tablet":
                text = generate_tablet_page(item_info, roll, corr, reforge_mult, reforge_name)
            else:
                await query.answer("Неизвестная страница", show_alert=True)
                return

            keyboard = generate_weapon_analysis_keyboard(item_key, page, dmg, upg, corr, reforge_name, user_msg_id)
            parse_mode = ParseMode.MARKDOWN_V2 if page == "tablet" else ParseMode.HTML
            await query.message.edit_text(text, parse_mode=parse_mode, reply_markup=keyboard)

        # Прогноз оружия (!wconq, !wdoom) - формат: w:item_key:page:roll:upg:corr:reforge:user_msg_id
        elif cmd_type == "w":
            if len(data_parts) != 8:
                await query.answer("Ошибка: неверный формат данных", show_alert=True)
                return

            roll, upg, corr_str, reforge_name = int(data_parts[3]), int(data_parts[4]), data_parts[5], data_parts[6]
            corr = corr_str == 'y'
            reforge_mult = REFORGE_MODIFIERS.get(reforge_name, 1.0)

            if page == "total":
                text = generate_forecast_total_page(item_info, roll, upg, corr, reforge_name, reforge_mult)
            elif page == "process":
                text = generate_forecast_process_page(item_info, roll, upg, corr, reforge_name, reforge_mult)
            else:
                await query.answer("Неизвестная страница", show_alert=True)
                return

            keyboard = generate_weapon_forecast_keyboard(item_key, page, roll, upg, corr, reforge_name, user_msg_id)
            await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

        # Сравнение оружия (!lconq, !ldoom) - формат: l:item_key:page:roll:curr_upg:curr_corr:curr_ref:des_upg:des_corr:des_ref:user_msg_id
        elif cmd_type == "l":
            if len(data_parts) != 11:
                await query.answer("Ошибка: неверный формат данных", show_alert=True)
                return

            roll = int(data_parts[3])
            curr_upg, curr_corr_str, curr_ref = int(data_parts[4]), data_parts[5], data_parts[6]
            des_upg, des_corr_str, des_ref = int(data_parts[7]), data_parts[8], data_parts[9]

            curr_corr = curr_corr_str == 'y'
            des_corr = des_corr_str == 'y'
            curr_ref_mult = REFORGE_MODIFIERS.get(curr_ref, 1.0)
            des_ref_mult = REFORGE_MODIFIERS.get(des_ref, 1.0)

            if page == "total":
                text = generate_compare_total_page(item_info, roll, curr_upg, curr_corr, curr_ref_mult, curr_ref,
                                                   des_upg, des_corr, des_ref_mult, des_ref)
            elif page == "actual_process":
                text = generate_compare_process_page(item_info, roll, curr_upg, curr_corr, curr_ref_mult, curr_ref,
                                                     "Actual")
            elif page == "wished_process":
                text = generate_compare_process_page(item_info, roll, des_upg, des_corr, des_ref_mult, des_ref,
                                                     "Wished")
            else:
                await query.answer("Неизвестная страница", show_alert=True)
                return

            keyboard = generate_weapon_compare_keyboard(item_key, page, roll, curr_upg, curr_corr, curr_ref,
                                                        des_upg, des_corr, des_ref, user_msg_id)
            await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

        else:
            await query.answer(f"Неизвестная команда: {cmd_type}", show_alert=True)

    except Exception as e:
        print(f"Ошибка в weapon_analysis_callback ({cmd_type}): {e}")
        import traceback
        traceback.print_exc()
        await query.answer("Произошла ошибка при обработке", show_alert=True)


# Добавьте эти функции в начало файла

def pack_armor_data(armor_data: dict, command: str) -> str:
    """
    Сжимает armor_data в минимальную строку.
    Формат: helm;chest;legs (каждая часть: значения через запятую, пусто если null)

    Для fz/z: hp,upg,corr
    Для wfz/wz: roll,upg,corr
    Для lfz/lz: roll,upg1,corr1,upg2,corr2
    """
    parts = []
    for part in ['helm', 'chest', 'legs']:
        data = armor_data.get(part)
        if not data:
            parts.append('')
            continue
        if 'hp' in data:  # fz/z
            parts.append(f"{int(data['hp'])},{data['upg']},{int(data['corrupted'])}")
        elif 'upg1' in data:  # lfz/lz
            parts.append(
                f"{data['roll']},{data['upg1']},{int(data['corrupted1'])},{data['upg2']},{int(data['corrupted2'])}")
        else:  # wfz/wz
            parts.append(f"{data['roll']},{data['upg']},{int(data['corrupted'])}")

    return ";".join(parts)


def unpack_armor_data(data_str: str, command: str) -> dict:
    """
    Распаковывает сжатую строку обратно в armor_data.
    """
    armor_data = {'helm': None, 'chest': None, 'legs': None}
    parts = data_str.split(";")

    for i, part_name in enumerate(['helm', 'chest', 'legs']):
        if i >= len(parts) or not parts[i]:
            continue

        values = parts[i].split(",")
        if len(values) == 3:
            if command in ['fz', 'z']:
                armor_data[part_name] = {
                    'hp': float(values[0]),
                    'upg': int(values[1]),
                    'corrupted': bool(int(values[2]))
                }
            else:
                armor_data[part_name] = {
                    'roll': int(values[0]),
                    'upg': int(values[1]),
                    'corrupted': bool(int(values[2]))
                }
        elif len(values) == 5:
            armor_data[part_name] = {
                'roll': int(values[0]),
                'upg1': int(values[1]),
                'corrupted1': bool(int(values[2])),
                'upg2': int(values[3]),
                'corrupted2': bool(int(values[4]))
            }

    return armor_data


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ASC ===

async def _handle_asc_callback(query, data_parts, page):
    """Обработчик для asc команд (!asc)"""
    if len(data_parts) != 9:
        print(f"Неверный формат asc callback: {':'.join(data_parts)}")
        await query.answer("Ошибка: неверный формат asc callback", show_alert=True)
        return

    item_key = data_parts[1]  # 'ws' / 'mb' / 'lk' ...
    dmg = float(data_parts[3])
    upg = int(data_parts[4])
    corr = data_parts[5] == 'y'
    reforge_n = data_parts[6]
    roll = int(data_parts[7])
    user_msg_id = int(data_parts[8])

    reforge_mult = REFORGE_MODIFIERS.get(reforge_n, 1.0)
    active_key = f"asc_{item_key}"  # <-- добавили

    if page == "total":
        base_dmg = ITEMS_MAPPING[active_key]['stats'][roll if item_key != 'ws' else 11]
        text = generate_asc_total_page(active_key, dmg, upg, corr,
                                       reforge_n, reforge_mult,
                                       roll if item_key != 'ws' else 11,
                                       base_dmg)
    elif page == "process":
        text = generate_asc_process_page(active_key,
                                         roll if item_key != 'ws' else 11,
                                         upg, corr, reforge_n, reforge_mult)
    elif page == "tablet":
        text = generate_asc_tablet_page(active_key,
                                        roll if item_key != 'ws' else 11,
                                        corr, reforge_mult, reforge_n)
    else:
        await query.answer("Неизвестная страница", show_alert=True)
        return

    keyboard = generate_asc_analysis_keyboard(
        dmg, upg, corr, reforge_n, user_msg_id,
        roll=roll, is_wooden_sword=(item_key == 'ws'),
        current_page=page, active_weapon=item_key  # тот же item_key
    )
    parse_mode = ParseMode.MARKDOWN_V2 if page == "tablet" else ParseMode.HTML
    try:
        await query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=keyboard)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            await query.answer()
        else:
            raise


async def _handle_wasc_callback(query, data_parts, page):
    """Обработчик для wasc команд (!wasc)"""
    if len(data_parts) != 10:  # Стало 10, а не 9 (добавили original_roll)
        print(f"Неверный формат wasc callback: {':'.join(data_parts)}")
        await query.answer("Ошибка: неверный формат wasc callback", show_alert=True)
        return

    item_key = data_parts[1]
    weapon_roll = int(data_parts[4])  # roll для конкретного меча
    upg = int(data_parts[5])
    corr = data_parts[6] == 'y'
    reforge_n = data_parts[7]
    original_roll = int(data_parts[8])  # <-- ВОТ ОН, изначальный roll
    user_msg_id = int(data_parts[9])

    reforge_mult = REFORGE_MODIFIERS.get(reforge_n, 1.0)
    active_key = f"asc_{item_key}"

    base_dmg = ITEMS_MAPPING[active_key]['stats'][weapon_roll if item_key != 'ws' else 11]
    dmg = calculate_weapon_stat_at_level(base_dmg, upg, corr, reforge_mult)

    if page == "total":
        text = generate_asc_total_page(active_key, dmg, upg, corr,
                                       reforge_n, reforge_mult,
                                       weapon_roll if item_key != 'ws' else 11,
                                       base_dmg)
    elif page == "process":
        text = generate_asc_process_page(active_key,
                                         weapon_roll if item_key != 'ws' else 11,
                                         upg, corr, reforge_n, reforge_mult)
    else:
        await query.answer("Неизвестная страница", show_alert=True)
        return

    keyboard = generate_asc_forecast_keyboard(
        original_roll=original_roll,  # <-- передаем изначальный roll
        upg=upg,
        corr=corr,
        reforge_name=reforge_n,
        user_msg_id=user_msg_id,
        current_page=page,
        active_weapon=item_key
    )
    try:
        await query.message.edit_text(text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            await query.answer()
        else:
            raise


async def _handle_lasc_callback(query, data_parts, page):
    """Обработчик для lasc команд (!lasc)"""
    if len(data_parts) != 13:  # Стало 13, а не 12 (добавили original_roll)
        print(f"Неверный формат lasc callback: {':'.join(data_parts)}")
        await query.answer("Ошибка: неверный формат lasc callback", show_alert=True)
        return

    item_key = data_parts[1]
    weapon_roll = int(data_parts[4])  # roll для конкретного меча
    curr_upg = int(data_parts[5])
    curr_corr = data_parts[6] == 'y'
    curr_ref_n = data_parts[7]
    des_upg = int(data_parts[8])
    des_corr = data_parts[9] == 'y'
    des_ref_n = data_parts[10]
    original_roll = int(data_parts[11])  # <-- ВОТ ОН, изначальный roll
    user_msg_id = int(data_parts[12])

    curr_ref_mult = REFORGE_MODIFIERS.get(curr_ref_n, 1.0)
    des_ref_mult = REFORGE_MODIFIERS.get(des_ref_n, 1.0)
    active_key = f"asc_{item_key}"

    if page == "total":
        text = generate_compare_total_page(
            ITEMS_MAPPING[active_key], weapon_roll,  # <-- используем weapon_roll
            curr_upg, curr_corr, curr_ref_mult, curr_ref_n,
            des_upg, des_corr, des_ref_mult, des_ref_n)
    elif page == "actual_process":
        text = generate_asc_process_page(
            active_key, weapon_roll, curr_upg, curr_corr, curr_ref_n, curr_ref_mult,  # <-- используем weapon_roll
            state="Актуальные")
    elif page == "wished_process":
        text = generate_asc_process_page(
            active_key, weapon_roll, des_upg, des_corr, des_ref_n, des_ref_mult,  # <-- используем weapon_roll
            state="Желаемые")
    else:
        await query.answer("Неизвестная страница", show_alert=True)
        return

    keyboard = generate_asc_compare_keyboard(
        original_roll,  # <-- передаем изначальный roll
        curr_upg, curr_corr, curr_ref_n,
        des_upg, des_corr, des_ref_n,
        user_msg_id, current_page=page, active_weapon=item_key
    )
    try:
        await query.message.edit_text(text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            await query.answer()
        else:
            raise


# --- АНАЛИЗ ОРУЖИЯ И ОБРАБОТЧИК "ДА" ---

# ### NEW: Кастомный фильтр для умного распознавания "Да"
class FilterSmartDa(filters.UpdateFilter):
    def filter(self, update):
        if not update.message or not update.message.text:
            return False

        # 1. Нормализация (превращает 𝕕𝕒, 𝓓𝓪 и прочие шрифты в обычный текст)
        text = unicodedata.normalize('NFKC', update.message.text)

        # 2. Регулярное выражение
        # (?i) - игнорировать регистр (Da, dA)
        # (?:^|\W) - начало строки ИЛИ не буква (чтобы не триггерилось на "Лада")
        # [дd] - русская Д или английская D
        # [аa]+ - русская А или английская A (одна или более, для "Даааа")
        # [\W\s]*$ - любые знаки препинания или пробелы в конце строки
        pattern = r'(?i)(?:^|\W)[дd][аa]+[\W\s]*$'

        return bool(re.search(pattern, text))


smart_da_filter = FilterSmartDa()


async def yes_handler(update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return

    # Шансы выпадения
    options = {
        "Елда": 20, "Пизда": 1, "Джигурда": 10, "Звезда": 20,
        "Поезда": 20, "Дабудидабуда": 20, "Борода": 20, "Слобода": 20,
        "Узда": 20, "Вода": 10, "Манда": 20, "Караганда": 10,
        "Чехарда": 10, "MUDA": 1
    }
    # Прямые ссылки на изображения
    photo_urls = {
        "Пизда": "https://sun9-48.userapi.com/impg/c844418/v844418142/4f7ef/wk7pnm_dqkY.jpg?size=487x487&quality=96&sign=29e3dacedac2c03eaa320ee2403f8624&type=album ",
        "MUDA": "https://www.meme-arsenal.com/memes/e580d8c1ac6e6a7bc1c623bd7ab80dce.jpg ",
        "Джигурда": "https://www.meme-arsenal.com/memes/03c918ccc821b8172f09c38ded2b8d57.jpg "
    }
    population = list(options.keys())
    weights = list(options.values())
    chosen_word = random.choices(population, weights=weights, k=1)[0]

    # ПРОВЕРКА: Если слово редкое и для него есть картинка
    if chosen_word in photo_urls:
        try:
            # Отправляем ТОЛЬКО фото (без текста)
            await update.effective_message.reply_photo(
                photo=photo_urls[chosen_word]
            )
        except Exception:
            # Если с фото что-то не так, всё же ответим текстом, чтоб бот не молчал
            await update.effective_message.reply_text(chosen_word)
    else:
        # Для всех остальных слов — обычный текстовый ответ
        await update.effective_message.reply_text(chosen_word)


def generate_weapon_analysis_keyboard(item_key, current_page, dmg, upg, corr, reforge_name, user_msg_id):
    """Генерация клавиатуры для анализа оружия (!conq, !doom) - 4 кнопки"""
    corr_str = 'y' if corr else 'n'
    ref_str = reforge_name if reforge_name != "None" else "None"

    # Формат: a:item_key:page:dmg:upg:corr:reforge:user_msg_id
    base = f"a:{item_key}:{{}}:{int(dmg)}:{upg}:{corr_str}:{ref_str}:{user_msg_id}"

    total_text = "✓ Total" if current_page == "total" else "Total"
    process_text = "✓ Process" if current_page == "process" else "Process"
    tablet_text = "✓ Tablet" if current_page == "tablet" else "Tablet"

    keyboard = [
        [
            InlineKeyboardButton(total_text, callback_data=base.format("total")),
            InlineKeyboardButton(process_text, callback_data=base.format("process")),
            InlineKeyboardButton(tablet_text, callback_data=base.format("tablet")),
        ],
        [InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def generate_weapon_forecast_keyboard(item_key, current_page, roll, upg, corr, reforge_name, user_msg_id):
    """Генерация клавиатуры для прогноза оружия (!wconq, !wdoom)"""
    corr_str = 'y' if corr else 'n'
    ref_str = reforge_name if reforge_name != "None" else "None"

    # Формат: w:item_key:page:roll:upg:corr:reforge:user_msg_id
    base = f"w:{item_key}:{{}}:{roll}:{upg}:{corr_str}:{ref_str}:{user_msg_id}"

    total_text = "✓ Total" if current_page == "total" else "Total"
    process_text = "✓ Process" if current_page == "process" else "Process"

    keyboard = [
        [
            InlineKeyboardButton(total_text, callback_data=base.format("total")),
            InlineKeyboardButton(process_text, callback_data=base.format("process")),
        ],
        [InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def generate_weapon_compare_keyboard(item_key, current_page, roll, curr_upg, curr_corr, curr_ref,
                                     des_upg, des_corr, des_ref, user_msg_id):
    """Генерация клавиатуры для сравнения (!lconq, !ldoom) - 3 кнопки"""
    curr_corr_str = 'y' if curr_corr else 'n'
    des_corr_str = 'y' if des_corr else 'n'
    ref_str = curr_ref
    des_ref_str = des_ref

    # Формат: l:item_key:page:roll:curr_upg:curr_corr:curr_ref:des_upg:des_corr:des_ref:user_msg_id
    base = f"l:{item_key}:{{}}:{roll}:{curr_upg}:{curr_corr_str}:{ref_str}:{des_upg}:{des_corr_str}:{des_ref_str}:{user_msg_id}"

    total_text = "✓ Total" if current_page == "total" else "Total"
    actual_process_text = "✓ Actual Process" if current_page == "actual_process" else "Actual Process"
    wished_process_text = "✓ Wished Process" if current_page == "wished_process" else "Wished Process"

    keyboard = [
        [
            InlineKeyboardButton(total_text, callback_data=base.format("total")),
            InlineKeyboardButton(actual_process_text, callback_data=base.format("actual_process")),
            InlineKeyboardButton(wished_process_text, callback_data=base.format("wished_process")),
        ],
        [InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def generate_total_page(item_info, dmg, upg, corr, reforge_name, reforge_mult, roll, base_dmg):
    """Генерация страницы Total для анализа оружия (!conq, !doom)"""
    max_lvl = item_info['max_level']
    b1 = item_info['upgrade_cost_lvl1']

    spent = calculate_gold(b1, upg)
    total_needed = calculate_gold(b1, max_lvl)
    remaining = max(0, total_needed - spent)

    return (
        f"📊 <b>Анализ {item_info['name']}</b>\n\n"
        f"<b>DMG:</b> <i>{int(dmg):,}</i>\n"
        f"<b>Reforge:</b> <i>{reforge_name}</i> (x{reforge_mult:.2f})\n"
        f"<b>Corrupted:</b> <i>{'Да' if corr else 'Нет'}</i>\n"
        f"<b>Upgrade:</b> <i>{upg}/{max_lvl}</i>\n\n"
        f"<b>Gold spent:</b> <i>{spent:,}</i> 💰\n"
        f"<b>Gold left:</b> <i>{remaining:,}</i> 💰\n\n"
        f"<b>BASE DMG:</b> <i>{base_dmg:,}</i>\n"
        f"<b>ROLL:</b> <i>{roll}/11</i>\n"
        f"<b>Roll quality:</b> <i>{roll / 11 * 100:.1f}%</i>"
    )


def generate_process_page(item_info, dmg, upg, corr, reforge_name, reforge_mult, roll, base_dmg):
    """Генерация страницы Process с детальными расчетами (!conq, !doom)"""
    steps = []
    current = float(dmg)

    steps.append(f"🧮 <b>Детальные вычисления: {item_info['name']}</b>\n\n")

    if reforge_mult != 1.0:
        steps.append(f"<b>1. Убираем Reforge ({reforge_name} ×{reforge_mult:.2f}):</b>")
        steps.append(f"<i>  {current:,.2f} ÷ {reforge_mult:.2f} = {current / reforge_mult:,.2f}</i>")
        current = current / reforge_mult
        steps.append("")

    if corr:
        steps.append("<b>2. Убираем Corrupted (×1.5):</b>")
        steps.append(f"<i>  {current:,.2f} ÷ 1.50 = {current / 1.5:,.2f}</i>")
        current = current / 1.5
        steps.append("")

    growth_factor = 1 + GROWTH_RATE * upg
    steps.append("<b>3. Расчет базового урона:</b>")
    steps.append(f"<i>  Фактор роста = 1 + {upg} × 0.047619 = {growth_factor:.10f}</i>")
    steps.append(f"<i>  {current:,.2f} ÷ {growth_factor:.10f} = {current / growth_factor:.2f}</i>")
    inferred_base = current / growth_factor
    steps.append("")

    steps.append("<b>4. Определение ролла:</b>")
    steps.append(f"<i>  Инференс: {inferred_base:.2f}</i>")
    steps.append("")

    stats_dict = item_info['stats']
    for r in range(1, 12):
        val = stats_dict[r]
        symbol = "←" if r == roll else " "
        comparison = "&gt;" if val < inferred_base else "&lt;"
        steps.append(f"<i>  {r:2} roll - {val:8,.2f} {comparison} {inferred_base:.2f} {symbol}</i>")

    steps.append("")
    steps.append(f"<b>✓ Выбран ролл:</b> <i>{roll}/11</i>\n")
    steps.append(f"<b>✓ BASE DMG:</b> <i>{base_dmg:,}</i>")

    return "\n".join(steps)


def generate_tablet_page(item_info, roll, corr, reforge_mult, reforge_name):
    """Генерация страницы Tablet - таблица уровней в моноширинном шрифте"""
    max_lvl = item_info['max_level']
    b1 = item_info['upgrade_cost_lvl1']
    base_dmg = item_info['stats'][roll]

    # Упрощенный заголовок без Total Gold
    header = f"{'UPG':<5} | {'Gold Cost':<11} | {'DMG':<12}"
    separator = "-" * len(header)

    rows = [header, separator]
    prev_gold = 0

    for level in range(0, max_lvl + 1):
        total_gold = calculate_gold(b1, level)
        level_cost = total_gold - prev_gold if level > 0 else 0
        prev_gold = total_gold

        dmg = calculate_weapon_stat_at_level(base_dmg, level, corr, reforge_mult)
        rows.append(f"{level:<5} | {level_cost:<11,} | {dmg:<12,}")

    table_content = "\n".join(rows)
    title_line = f"{item_info['name']} | ROLL {roll}/11 | {'CORRUPTED' if corr else 'NORMAL'} | {reforge_name}"
    footer = "Gold for +1: стоимость текущего уровня"

    # Форматируем как блок кода в MarkdownV2 (как в reforge_command)
    clean_name = item_info['name'].replace(' ', '_').replace("'", '').upper()
    block_name = f"{clean_name}_TABLET"
    return f"```{block_name}\n{title_line}\n\n{table_content}\n\n{footer}\n```"


def generate_forecast_total_page(item_info, roll, upg, corr, reforge_name, reforge_mult):
    """Генерация Total страницы для прогноза (!wconq, !wdoom)"""
    max_lvl = item_info['max_level']
    b1 = item_info['upgrade_cost_lvl1']
    base_dmg = item_info['stats'][roll]

    current_dmg = calculate_weapon_stat_at_level(base_dmg, 0, corr, reforge_mult)
    target_dmg = calculate_weapon_stat_at_level(base_dmg, upg, corr, reforge_mult)
    gold_needed = calculate_gold(b1, upg)
    dmg_increase = target_dmg - current_dmg

    return (
        f"📈 <b>Прогноз: {item_info['name']}</b>\n\n"
        f"<b>ROLL:</b> <i>{roll}/11</i> | <b>BASE:</b> <i>{base_dmg:,}</i>\n\n"
        f"<b>Reforge:</b> <i>{reforge_name}</i> (x{reforge_mult:.2f})\n"
        f"<b>Corrupted:</b> <i>{'Да' if corr else 'Нет'}</i>\n"
        f"<b>Target UPG:</b> <i>{upg}/{max_lvl}</i>\n\n"
        f"<b>DMG at 0:</b> <i>{current_dmg:,}</i>\n"
        f"<b>DMG at {upg}:</b> <i>{target_dmg:,}</i> ⚔️\n"
        f"<b>DMG increase:</b> <i>+{dmg_increase:,}</i>\n"
        f"<b>Gold needed:</b> <i>{gold_needed:,}</i> 💰"
    )


def generate_forecast_process_page(item_info, roll, upg, corr, reforge_name, reforge_mult):
    """Генерация страницы Process для прогноза оружия (!wconq, !wdoom)"""
    base_dmg = item_info['stats'][roll]
    steps = []
    steps.append(f"🧮 <b>Детальные вычисления: {item_info['name']}</b>\n\n")

    # Шаг 1: Расчет с фактором роста
    growth_factor = 1 + GROWTH_RATE * upg
    base_value = base_dmg * growth_factor
    steps.append("<b>1. Расчет общего урона:</b>")
    steps.append(f"<i>  Фактор роста = 1 + {upg} × 0.047619 = {growth_factor:.10f}</i>")
    steps.append(f"<i>  {base_dmg:,.2f} × {growth_factor:.10f} = {base_value:,.2f}</i>")
    steps.append("")

    # Шаг 2: Corrupted
    corr_mult = 1.5 if corr else 1.0
    corr_value = base_value * corr_mult
    corr_text = "Да (×1.5)" if corr else "Нет (×1.0)"
    steps.append(f"<b>2. Умножаем на Corrupted ({corr_text}):</b>")
    steps.append(f"<i>  {base_value:,.2f} × {corr_mult:.2f} = {corr_value:,.2f}</i>")
    steps.append("")

    # Шаг 3: Reforge
    if reforge_mult != 1.0:
        ref_value = corr_value * reforge_mult
        steps.append(f"<b>3. Умножаем на Reforge ({reforge_name} ×{reforge_mult:.2f}):</b>")
        steps.append(f"<i>  {corr_value:,.2f} × {reforge_mult:.2f} = {ref_value:,.2f}</i>")
        steps.append("")
        final_dmg = ref_value
    else:
        final_dmg = corr_value
        steps.append("<b>3. Reforge: Нет (×1.00)</b>")
        steps.append("")

    steps.append(f"<b>Итоговый урон = {final_dmg:,.0f}</b>")

    return "\n".join(steps)


def generate_compare_process_page(item_info, roll, upg, corr, reforge_mult, reforge_name, state):
    """Генерация Process для сравнения (!lconq, !ldoom) - для Actual или Wished"""
    base_dmg = item_info['stats'][roll]
    steps = []
    steps.append(f"🧮 <b>Детальные вычисления: {item_info['name']} ({state})</b>\n\n")

    # Шаг 1: Расчет с фактором роста
    growth_factor = 1 + GROWTH_RATE * upg
    base_value = base_dmg * growth_factor
    steps.append("<b>1. Расчет общего урона:</b>")
    steps.append(f"<i>  Фактор роста = 1 + {upg} × 0.047619 = {growth_factor:.10f}</i>")
    steps.append(f"<i>  {base_dmg:,.2f} × {growth_factor:.10f} = {base_value:,.2f}</i>")
    steps.append("")

    # Шаг 2: Corrupted
    corr_mult = 1.5 if corr else 1.0
    corr_value = base_value * corr_mult
    corr_text = "Да (×1.5)" if corr else "Нет (×1.0)"
    steps.append(f"<b>2. Умножаем на Corrupted ({corr_text}):</b>")
    steps.append(f"<i>  {base_value:,.2f} × {corr_mult:.2f} = {corr_value:,.2f}</i>")
    steps.append("")

    # Шаг 3: Reforge
    if reforge_mult != 1.0:
        ref_value = corr_value * reforge_mult
        steps.append(f"<b>3. Умножаем на Reforge ({reforge_name} ×{reforge_mult:.2f}):</b>")
        steps.append(f"<i>  {corr_value:,.2f} × {reforge_mult:.2f} = {ref_value:,.2f}</i>")
        steps.append("")
        final_dmg = ref_value
    else:
        final_dmg = corr_value
        steps.append("<b>3. Reforge: Нет (×1.00)</b>")
        steps.append("")

    steps.append(f"<b>Итоговый урон = {final_dmg:,.0f}</b>")

    return "\n".join(steps)


def generate_compare_total_page(item_info, roll, curr_upg, curr_corr, curr_ref_mult, curr_ref_name,
                                des_upg, des_corr, des_ref_mult, des_ref_name):
    """Генерация единой страницы Total для сравнения (стиль Wished)"""
    base_dmg = item_info['stats'][roll]

    curr_dmg = calculate_weapon_stat_at_level(base_dmg, curr_upg, curr_corr, curr_ref_mult)
    curr_spent = calculate_gold(item_info['upgrade_cost_lvl1'], curr_upg)

    des_dmg = calculate_weapon_stat_at_level(base_dmg, des_upg, des_corr, des_ref_mult)
    des_gold = calculate_gold(item_info['upgrade_cost_lvl1'], des_upg)
    add_gold = max(0, des_gold - curr_spent)

    upg_diff = des_upg - curr_upg
    dmg_diff = des_dmg - curr_dmg
    ref_mult_diff = des_ref_mult - curr_ref_mult

    corr_diff_text = ""
    if not curr_corr and des_corr:
        corr_diff_text = " (активируется)"
    elif curr_corr and not des_corr:
        corr_diff_text = " ❌ (невозможно)"

    # корректный знак для урона и процента
    dmg_sign = "+" if dmg_diff >= 0 else ""
    pct_sign = "+" if dmg_diff >= 0 else ""

    return (
        f"📊 <b>Сравнение: {item_info['name']}</b>\n\n"
        f"<b>ROLL:</b> <i>{roll}/11</i> | <b>BASE:</b> <i>{base_dmg:,}</i>\n\n"
        f"<b>🔸 Текущее состояние</b>\n"
        f"<b>UPG:</b> <i>{curr_upg}</i>\n"
        f"<b>Reforge:</b> <i>{curr_ref_name}</i> (x{curr_ref_mult:.2f})\n"
        f"<b>Corrupted:</b> <i>{'Да' if curr_corr else 'Нет'}</i>\n"
        f"<b>DMG:</b> <i>{curr_dmg:,}</i>\n"
        f"<b>Gold spent:</b> <i>{curr_spent:,}</i> 💰\n\n"
        f"<b>🔹 Желаемое состояние</b>\n"
        f"<b>UPG:</b> <i>{des_upg} (+{upg_diff})</i>\n"
        f"<b>Regrade:</b> <i>{des_ref_name}</i> (x{des_ref_mult:.2f}) {f'(+{ref_mult_diff:.2f})' if ref_mult_diff != 0 else ''}\n"
        f"<b>Corrupted:</b> <i>{'Да' if des_corr else 'Нет'}{corr_diff_text}</i>\n"
        f"<b>DMG:</b> <i>{des_dmg:,} ({dmg_sign}{dmg_diff:,})</i>\n\n"
        f"<b>💰 Дополнительное золото:</b> <i>{add_gold:,}</i> 💰\n"
        f"<b>📈 Прирост урона:</b> <i>{dmg_sign}{dmg_diff:,} ({pct_sign}{dmg_diff / curr_dmg * 100:.1f}%)</i>"
    )


def generate_asc_analysis_keyboard(damage, upg, corr, reforge_name,
                                   user_msg_id, roll=None,
                                   is_wooden_sword=False,
                                   current_page="total",
                                   active_weapon="ws"):
    # --- рандом активного меча при первом показе Total ---
    if current_page == "total" and active_weapon == "ws" and not is_wooden_sword:
        active_weapon = random.choice(["mb", "lk", "me", "pt", "dd"])

    corr_str = 'y' if corr else 'n'
    ref_str = reforge_name if reforge_name != "None" else "None"

    if is_wooden_sword:
        base = f"asc:ws:{{}}:{int(damage)}:{upg}:{corr_str}:{ref_str}:11:{user_msg_id}"
        total_txt = "✓ Total" if current_page == "total" and active_weapon == "ws" else "Total"
        proc_txt = "✓ Process" if current_page == "process" and active_weapon == "ws" else "Process"
        tabl_txt = "✓ Tablet" if current_page == "tablet" and active_weapon == "ws" else "Tablet"

        keyboard = [
            [InlineKeyboardButton(total_txt, callback_data=base.format("total")),
             InlineKeyboardButton(proc_txt, callback_data=base.format("process")),
             InlineKeyboardButton(tabl_txt, callback_data=base.format("tablet"))],
            [InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")]
        ]
    else:
        if roll is None:
            raise ValueError("roll required for non-WS asc weapons")

        buttons = []
        for w_key in ['mb', 'lk', 'me', 'pt', 'dd']:
            short = ASC_WEAPON_SHORT_NAMES[w_key]
            base = f"asc:{w_key}:{{}}:{int(damage)}:{upg}:{corr_str}:{ref_str}:{roll}:{user_msg_id}"

            total_btn = InlineKeyboardButton(
                f"{'✓ ' if current_page == 'total' and active_weapon == w_key else ''}{short} Total",
                callback_data=base.format("total"))
            proc_btn = InlineKeyboardButton(
                f"{'✓ ' if current_page == 'process' and active_weapon == w_key else ''}{short} Process",
                callback_data=base.format("process"))
            buttons.append([total_btn, proc_btn])

        tab_base = f"asc:mb:tablet:{int(damage)}:{upg}:{corr_str}:{ref_str}:{roll}:{user_msg_id}"
        tab_btn = InlineKeyboardButton(
            f"{'✓ ' if current_page == 'tablet' and active_weapon == 'mb' else ''}Tablet", callback_data=tab_base)
        buttons.append([tab_btn,
                        InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")])
        keyboard = buttons

    return InlineKeyboardMarkup(keyboard)


# --------------- 2. !wasc ---------------
def generate_asc_forecast_keyboard(original_roll, upg, corr, reforge_name,
                                   user_msg_id, current_page="total",
                                   active_weapon="ws"):
    """
    original_roll: тот roll, что ввел пользователь (6-11)
    """
    corr_str = 'y' if corr else 'n'
    ref_str = reforge_name if reforge_name != "None" else "None"

    buttons = []
    for w_key in ASC_WEAPON_KEYS:
        short = ASC_WEAPON_SHORT_NAMES[w_key]
        # Для WS всегда 11, для остальных — original_roll
        weapon_roll = 11 if w_key == 'ws' else original_roll
        dummy_dmg = 0
        # Формат: wasc:{weapon_key}:{page}:{dmg}:{weapon_roll}:{upg}:{corr}:{reforge}:{original_roll}:{user_msg_id}
        base = f"wasc:{w_key}:{{}}:{dummy_dmg}:{weapon_roll}:{upg}:{corr_str}:{ref_str}:{original_roll}:{user_msg_id}"

        total_btn = InlineKeyboardButton(
            f"{'✓ ' if current_page == 'total' and active_weapon == w_key else ''}{short} Total",
            callback_data=base.format("total"))
        proc_btn = InlineKeyboardButton(
            f"{'✓ ' if current_page == 'process' and active_weapon == w_key else ''}{short} Process",
            callback_data=base.format("process"))
        buttons.append([total_btn, proc_btn])

    buttons.append([InlineKeyboardButton("Свернуть",
                                         callback_data=f"close:{user_msg_id}")])
    return InlineKeyboardMarkup(buttons)


# --------------- 3. !lasc ---------------
def generate_asc_compare_keyboard(roll,  # это original_roll (введенный пользователем)
                                  curr_upg, curr_corr, curr_ref,
                                  des_upg, des_corr, des_ref,
                                  user_msg_id, current_page="total",
                                  active_weapon="ws"):
    """
    roll: оригинальный roll, введенный пользователем (6-11)
    """
    curr_corr_str = 'y' if curr_corr else 'n'
    des_corr_str = 'y' if des_corr else 'n'
    curr_ref_str = curr_ref if curr_ref != "None" else "None"
    des_ref_str = des_ref if des_ref != "None" else "None"

    buttons = []
    for w_key in ASC_WEAPON_KEYS:
        short = ASC_WEAPON_SHORT_NAMES[w_key]
        # Для WS всегда 11, для остальных — original_roll
        weapon_roll = 11 if w_key == 'ws' else roll
        dummy_dmg = 0
        # Формат: lasc:{weapon_key}:{page}:{dmg}:{weapon_roll}:{curr_upg}:{curr_corr}:{curr_ref}:{des_upg}:{des_corr}:{des_ref}:{original_roll}:{user_msg_id}
        base = f"lasc:{w_key}:{{}}:{dummy_dmg}:{weapon_roll}:{curr_upg}:{curr_corr_str}:{curr_ref_str}:{des_upg}:{des_corr_str}:{des_ref_str}:{roll}:{user_msg_id}"
        total_btn = InlineKeyboardButton(
            f"{'✓ ' if current_page == 'total' and active_weapon == w_key else ''}{short} Total",
            callback_data=base.format("total"))
        actual_btn = InlineKeyboardButton(
            f"{'✓ ' if current_page == 'actual_process' and active_weapon == w_key else ''}< Actual Process",
            callback_data=base.format("actual_process"))
        wished_btn = InlineKeyboardButton(
            f"{'✓ ' if current_page == 'wished_process' and active_weapon == w_key else ''}< Wished Process",
            callback_data=base.format("wished_process"))
        buttons.append([total_btn, actual_btn, wished_btn])
    buttons.append([InlineKeyboardButton("Свернуть",
                                         callback_data=f"close:{user_msg_id}")])
    return InlineKeyboardMarkup(buttons)


def generate_asc_total_page(item_key, dmg, upg, corr, reforge_name, reforge_mult, roll, base_dmg):
    """Генерация Total страницы для ASC оружия"""
    item_info = ITEMS_MAPPING[item_key]
    max_lvl = item_info['max_level']
    b1 = item_info['upgrade_cost_lvl1']

    # Для !wasc и !lasc base_dmg может быть None, пересчитываем
    if base_dmg is None:
        base_dmg = item_info['stats'][roll]

    spent = calculate_gold(b1, upg)
    total_needed = calculate_gold(b1, max_lvl)
    remaining = max(0, total_needed - spent)

    current_dmg = calculate_weapon_stat_at_level(base_dmg, upg, corr, reforge_mult)

    return (
        f"📊 <b>Анализ {item_info['name']}</b>\n\n"
        f"<b>ROLL:</b> <i>{roll}/11</i> | <b>BASE:</b> <i>{base_dmg:,}</i>\n\n"
        f"<b>Reforge:</b> <i>{reforge_name}</i> (x{reforge_mult:.2f})\n"
        f"<b>Corrupted:</b> <i>{'Да' if corr else 'Нет'}</i>\n"
        f"<b>Upgrade:</b> <i>{upg}/{max_lvl}</i>\n\n"
        f"<b>DMG:</b> <i>{int(current_dmg):,}</i>\n"
        f"<b>Gold spent:</b> <i>{spent:,}</i> 💰\n"
        f"<b>Gold left:</b> <i>{remaining:,}</i> 💰"
    )


def generate_asc_process_page(item_key, roll, upg, corr, reforge_name, reforge_mult, state=""):
    """Генерация Process страницы для ASC оружия"""
    item_info = ITEMS_MAPPING[item_key]
    base_stats = item_info['stats']
    base_dmg = base_stats[roll]

    state_text = f" ({state})" if state else ""

    steps = []
    steps.append(f"🧮 <b>Детальные вычисления: {item_info['name']}{state_text}</b>\n\n")

    # Шаг 1: Базовый урон
    steps.append(f"<b>1. Базовый урон (ролл {roll}):</b>")
    steps.append(f"<i>  {base_dmg:,.2f}</i>")
    steps.append("")

    # Шаг 2: Фактор роста
    growth_factor = 1 + GROWTH_RATE * upg
    base_value = base_dmg * growth_factor
    steps.append("<b>2. Применяем фактор роста:</b>")
    steps.append(f"<i>  Фактор = 1 + {upg} × 0.047619 = {growth_factor:.10f}</i>")
    steps.append(f"<i>  {base_dmg:,.2f} × {growth_factor:.10f} = {base_value:,.2f}</i>")
    steps.append("")

    # Шаг 3: Corrupted
    if corr:
        corr_value = base_value * 1.5
        steps.append("<b>3. Умножаем на Corrupted (×1.5):</b>")
        steps.append(f"<i>  {base_value:,.2f} × 1.50 = {corr_value:,.2f}</i>")
        steps.append("")
    else:
        corr_value = base_value
        steps.append("<b>3. Corrupted: Нет (×1.00)</b>")
        steps.append("")

    # Шаг 4: Reforge
    if reforge_mult != 1.0:
        final_dmg = corr_value * reforge_mult
        steps.append(f"<b>4. Умножаем на Reforge ({reforge_name} ×{reforge_mult:.2f}):</b>")
        steps.append(f"<i>  {corr_value:,.2f} × {reforge_mult:.2f} = {final_dmg:,.2f}</i>")
    else:
        final_dmg = corr_value
        steps.append("<b>4. Reforge: Нет (×1.00)</b>")

    steps.append("")
    steps.append(f"<b>✓ Итоговый урон = {final_dmg:,.0f}</b>")

    return "\n".join(steps)


def generate_asc_tablet_page(item_key, roll, corr, reforge_mult, reforge_name):
    """
    Генерация Tablet страницы для ASC оружия
    item_key: 'asc_ws', 'asc_mb' и т.д.
    roll: определенный ролл (для ws всегда 11)
    """
    item_info = ITEMS_MAPPING[item_key]
    max_lvl = item_info['max_level']
    b1 = item_info['upgrade_cost_lvl1']

    # Определяем фактический ролл
    actual_roll = 11 if item_key == "asc_ws" else roll
    base_dmg = item_info['stats'][actual_roll]

    # Генерация таблицы
    header = f"{'UPG':<5} | {'Gold Cost':<11} | {'DMG':<12}"
    separator = "-" * len(header)
    rows = [header, separator]
    prev_gold = 0

    for level in range(0, max_lvl + 1):
        total_gold = calculate_gold(b1, level)
        level_cost = total_gold - prev_gold if level > 0 else 0
        prev_gold = total_gold

        dmg = calculate_weapon_stat_at_level(base_dmg, level, corr, reforge_mult)
        rows.append(f"{level:<5} | {level_cost:<11,} | {dmg:<12,}")

    table_content = "\n".join(rows)
    title_line = f"{item_info['name']} | ROLL {actual_roll}/11 | {'CORRUPTED' if corr else 'NORMAL'} | {reforge_name}"
    footer = "Gold for +1: стоимость текущего уровня"

    # Форматирование как блок кода
    clean_name = item_info['name'].replace(' ', '_').replace("'", '').upper()
    block_name = f"{clean_name}_TABLET"
    return f"```{block_name}\n{title_line}\n\n{table_content}\n\n{footer}\n```"


def get_armor_stage_keyboard(stage: str, user_msg_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для этапа ввода данных брони"""
    buttons = []
    # ✅ Добавляем Пропустить для ВСЕХ этапов (шлем, нагрудник, штаны)
    buttons.append([InlineKeyboardButton("Пропустить", callback_data=f"armor_skip:{stage}:{user_msg_id}")])
    # Кнопка Отмена всегда присутствует
    buttons.append([InlineKeyboardButton("Отмена", callback_data=f"armor_cancel:{user_msg_id}")])
    return InlineKeyboardMarkup(buttons)


def get_armor_prompt_text(command: str, stage: str, max_level: int) -> str:
    stage_names = {
        "helm": "- <b>Шлема</b>",
        "chest": "- <b>Нагрудника</b>",
        "legs": "- <b>Штанов</b>"
    }
    # Переносы строк лучше ставить ПЕРЕД тегами, а не внутри них
    base = f"🤖 Введите данные для {stage_names[stage]}:\n"
    base += "<b>ВВОДИТЕ АРГУМЕНТЫ БЕЗ ВВОДА КОМАНДЫ ПО НОВОЙ</b>\n"
    base += "<i>Пример написания:</i>"

    if command in ['fz', 'z']:
        if stage == STAGE_HELMET:
            base += "\n\n<b>{hp} {upg} {y/n}</b>\n<i>(3279 32 y)</i>"
        elif stage == STAGE_CHEST:
            base += "\n\n<b>{hp} {upg} {y/n}</b>\n<i>(2895 31 y)</i>"
        elif stage == STAGE_LEGS:
            base += "\n\n<b>{hp} {upg} {y/n}</b>\n<i>(2788 31 y)</i>"
    elif command in ['wfz', 'wz']:
        if stage == STAGE_HELMET:
            base += "\n\n<b>{roll} > {upg} {y/n}</b>\n<i>(6 > 21 n)</i>"
        elif stage == STAGE_CHEST:
            base += "\n\n<b>{roll} > {upg} {y/n}</b>\n<i>(7 > 32 y)</i>"
        elif stage == STAGE_LEGS:
            base += "\n\n<b>{roll} > {upg} {y/n}</b>\n<i>(11 > 45 y)</i>"
    elif command in ['lfz', 'lz']:
        if stage == STAGE_HELMET:
            base += "\n\n<b>{roll} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n<i>(8 - 21 n > 45 y)</i>"
        elif stage == STAGE_CHEST:
            base += "\n\n<b>{roll} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n<i>(1 - 35 y > 40 y)</i>"
        elif stage == STAGE_LEGS:
            base += "\n\n<b>{roll} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n<i>(11 - 40 y > 45 y)</i>"
    base += f"\n\n(макс. ур: {max_level})"
    base += f"\n(ролл 1-11)"

    return base


def generate_armor_process_page(item_info: dict,
                                armor_data: dict,
                                command: str,
                                part: str,
                                page_type: str = "process") -> str:
    """Генерация Process страницы для брони с правильными расчетами"""
    part_names = {STAGE_HELMET: 'Шлем', STAGE_CHEST: 'Нагрудник', STAGE_LEGS: 'Штаны'}
    part_keys = {STAGE_HELMET: 'Helmet', STAGE_CHEST: 'Chestplate', STAGE_LEGS: 'Leggings'}

    if part not in armor_data or armor_data[part] is None:
        return "❌ Нет данных для этой части брони"

    data = armor_data[part]
    part_key = part_keys[part]
    base_stats = item_info['stats'][part_key]

    steps = [f"🧮 <b>Детальные вычисления: {item_info['name']} — {part_names[part]}</b>\n\n"]

    if command in ('fz', 'z') and page_type == "process":
        page_type = "actual_process"
    if command in ['fz', 'z']:
        # Анализ текущего состояния
        hp = data['hp']
        upg = data['upg']
        corrupted = data['corrupted']

        # Находим ролл
        roll = find_roll_for_armor(base_stats, hp, upg, corrupted)
        base_hp = base_stats[roll]

        steps.append(f"<b>1. Базовое HP (ролл {roll}):</b>")
        steps.append(f"<i>  {base_hp:,.2f}</i>\n")

        # Рост с правильным коэффициентом
        growth_factor = 1 + 0.047619047619 * upg
        base_value = base_hp * growth_factor
        steps.append("<b>2. Применяем фактор роста:</b>")
        steps.append(f"<i>  Фактор = 1 + {upg} × 0.047619 = {growth_factor:.10f}</i>")
        steps.append(f"<i>  {base_hp:,.2f} × {growth_factor:.10f} = {base_value:,.2f}</i>\n")

        # Corrupted
        if corrupted:
            corr_value = base_value * 1.5
            steps.append("<b>3. Умножаем на Corrupted (×1.5):</b>")
            steps.append(f"<i>  {base_value:,.2f} × 1.50 = {corr_value:,.2f}</i>\n")
            final_hp = corr_value
        else:
            final_hp = base_value
            steps.append("<b>3. Corrupted: Нет (×1.00)</b>\n")

        final_final_hp = round(final_hp + 0.45)
        steps.append("<b>4. Игровые условности</b>\n Для более точных значений прибавляем 0.45 \n")
        steps.append(f"<i> {final_hp:,.2f} + 0.45 = {final_final_hp:,.2f}</i> - округляем до ближайшего значения \n")

        steps.append(f"<b>✓ Итоговое HP = {final_final_hp:,.0f}</b>")
        return "\n".join(steps)

    elif command in ['wfz', 'wz']:
        # Прогноз
        roll = data['roll']
        upg = data['upg']
        corrupted = data['corrupted']

        base_hp = base_stats[roll]

        steps.append(f"<b>1. Базовое HP (ролл {roll}):</b>")
        steps.append(f"<i>  {base_hp:,.2f}</i>\n")

        # Рост с правильным коэффициентом
        growth_factor = 1 + 0.047619047619 * upg
        base_value = base_hp * growth_factor
        steps.append("<b>2. Применяем фактор роста:</b>")
        steps.append(f"<i>  Фактор = 1 + {upg} × 0.047619 = {growth_factor:.10f}</i>")
        steps.append(f"<i>  {base_hp:,.2f} × {growth_factor:.10f} = {base_value:,.2f}</i>\n")

        # Corrupted
        if corrupted:
            corr_value = base_value * 1.5
            steps.append("<b>3. Умножаем на Corrupted (×1.5):</b>")
            steps.append(f"<i>  {base_value:,.2f} × 1.50 = {corr_value:,.2f}</i>\n")
            final_hp = corr_value
        else:
            final_hp = base_value
            steps.append("<b>3. Corrupted: Нет (×1.00)</b>\n")

        final_final_hp = round(final_hp + 0.45)
        steps.append("<b>4. Игровые условности</b>\n Для более точных значений прибавляем 0.45 \n")
        steps.append(f"<i> {final_hp:,.2f} + 0.45 = {final_final_hp:,.2f}</i> - округляем до ближайшего значения \n")

        steps.append(f"<b>✓ Итоговое HP = {final_final_hp:,.0f}</b>")
        return "\n".join(steps)

    elif command in ['lfz', 'lz']:
        roll = data['roll']
        upg1 = data['upg1']
        corrupted1 = data['corrupted1']
        upg2 = data['upg2']
        corrupted2 = data['corrupted2']

        base_hp = base_stats[roll]

        if page_type == "actual_process":
            # 🔸 Только текущее
            steps.append(f"<b>🔸 Текущее состояние</b>\n")

            steps.append(f"<b>1. Базовое HP (ролл {roll}):</b>")
            steps.append(f"<i>  {base_hp:,.2f}</i>\n")

            growth_factor1 = 1 + 0.047619047619 * upg1
            base_value1 = base_hp * growth_factor1
            steps.append("<b>2. Применяем фактор роста:</b>")
            steps.append(f"<i>  Фактор = 1 + {upg1} × 0.047619 = {growth_factor1:.10f}</i>")
            steps.append(f"<i>  {base_hp:,.2f} × {growth_factor1:.10f} = {base_value1:,.2f}</i>\n")

            if corrupted1:
                corr_value1 = base_value1 * 1.5
                steps.append("<b>3. Умножаем на Corrupted (×1.5):</b>")
                steps.append(f"<i>  {base_value1:,.2f} × 1.50 = {corr_value1:,.2f}</i>\n")
                final_hp1 = corr_value1
            else:
                final_hp1 = base_value1
                steps.append("<b>3. Corrupted: Нет (×1.00)</b>\n")

            final_final_hp1 = round(final_hp1 + 0.45)
            steps.append("<b>4. Игровые условности</b>\n Для более точных значений прибавляем 0.45 \n")
            steps.append(
                f"<i> {final_hp1:,.2f} + 0.45 = {final_final_hp1:,.2f}</i> - округляем до ближайшего значения \n")
            steps.append(f"<b>✓ Итоговое HP = {final_final_hp1:,.0f}</b>")

            return "\n".join(steps)

        elif page_type == "wished_process":
            # 🔹 Только желаемое
            steps.append(f"<b>🔹 Желаемое состояние</b>\n")

            steps.append(f"<b>1. Базовое HP (ролл {roll}):</b>")
            steps.append(f"<i>  {base_hp:,.2f}</i>\n")

            growth_factor2 = 1 + 0.047619047619 * upg2
            base_value2 = base_hp * growth_factor2
            steps.append("<b>2. Применяем фактор роста:</b>")
            steps.append(f"<i>  Фактор = 1 + {upg2} × 0.047619 = {growth_factor2:.10f}</i>")
            steps.append(f"<i>  {base_hp:,.2f} × {growth_factor2:.10f} = {base_value2:,.2f}</i>\n")

            if corrupted2:
                corr_value2 = base_value2 * 1.5
                steps.append("<b>3. Умножаем на Corrupted (×1.5):</b>")
                steps.append(f"<i>  {base_value2:,.2f} × 1.50 = {corr_value2:,.2f}</i>\n")
                final_hp2 = corr_value2
            else:
                final_hp2 = base_value2
                steps.append("<b>3. Corrupted: Нет (×1.00)</b>\n")

            final_final_hp2 = round(final_hp2 + 0.45)
            steps.append("<b>4. Игровые условности</b>\n Для более точных значений прибавляем 0.45 \n")
            steps.append(
                f"<i> {final_hp2:,.2f} + 0.45 = {final_final_hp2:,.2f}</i> - округляем до ближайшего значения \n")
            steps.append(f"<b>✓ Итоговое HP = {final_final_hp2:,.0f}</b>")

            # 📈 Сравнение только в wished
            curr_hp = calculate_armor_stat_at_level(base_hp, upg1, corrupted1, 1.0, "armor")
            des_hp = calculate_armor_stat_at_level(base_hp, upg2, corrupted2, 1.0, "armor")
            hp_diff = des_hp - curr_hp
            gold1 = calculate_gold(item_info['upgrade_cost_lvl1'], upg1)
            gold2 = calculate_gold(item_info['upgrade_cost_lvl1'], upg2)
            gold_diff = max(0, gold2 - gold1)

            steps.append(f"\n<b>📈 Сравнение</b>")
            steps.append(f"<b>Прирост HP:</b> <i>+{int(hp_diff):,}</i>")
            steps.append(f"<b>Дополнительное золото:</b> <i>{gold_diff:,}</i> 💰")

            return "\n".join(steps)


def generate_armor_part_page(item_info: dict, armor_data: dict, command: str, part: str) -> str:
    """Генерация страницы ТОЛЬКО для конкретной части брони"""
    part_names = {STAGE_HELMET: 'Шлем', STAGE_CHEST: 'Нагрудник', STAGE_LEGS: 'Штаны'}
    part_keys = {STAGE_HELMET: 'Helmet', STAGE_CHEST: 'Chestplate', STAGE_LEGS: 'Leggings'}

    if part not in armor_data or armor_data[part] is None:
        return "❌ Нет данных для этой части брони"

    data = armor_data[part]
    part_key = part_keys[part]
    base_stats = item_info['stats'][part_key]

    response = f"🛡️ <b>{item_info['name']} — {part_names[part]}</b>\n\n"

    if command in ['fz', 'z']:
        hp = data['hp']
        upg = data['upg']
        corrupted = data['corrupted']

        roll = find_roll_for_armor(base_stats, hp, upg, corrupted)
        base_hp = base_stats[roll]

        spent = calculate_gold(item_info['upgrade_cost_lvl1'], upg)
        remaining = max(0, calculate_gold(item_info['upgrade_cost_lvl1'], item_info['max_level']) - spent)

        response += f"<b>ROLL:</b> <i>{roll}/11</i> | <b>BASE HP:</b> <i>{base_hp:,}</i>\n\n"
        response += f"<b>UPG:</b> <i>{upg}/{item_info['max_level']}</i>\n"
        response += f"<b>Corrupted:</b> <i>{'Да' if corrupted else 'Нет'}</i>\n"
        response += f"<b>HP:</b> <i>{int(hp):,}</i> ❤️\n\n"
        response += f"<b>Gold spent:</b> <i>{spent:,}</i> 💰\n"
        response += f"<b>Gold left:</b> <i>{remaining:,}</i> 💰"

    elif command in ['wfz', 'wz']:
        roll = data['roll']
        upg = data['upg']
        corrupted = data['corrupted']

        base_hp = base_stats[roll]
        hp_at_level = calculate_armor_stat_at_level(base_hp, upg, corrupted, 1.0, "armor")
        gold_needed = calculate_gold(item_info['upgrade_cost_lvl1'], upg)

        response += f"<b>ROLL:</b> <i>{roll}/11</i> | <b>BASE HP:</b> <i>{base_hp:,}</i>\n\n"
        response += f"<b>Target UPG:</b> <i>{upg}/{item_info['max_level']}</i>\n"
        response += f"<b>Corrupted:</b> <i>{'Да' if corrupted else 'Нет'}</i>\n"
        response += f"<b>HP:</b> <i>{int(hp_at_level):,}</i> ❤️\n\n"
        response += f"<b>Gold needed:</b> <i>{gold_needed:,}</i> 💰"

    elif command in ['lfz', 'lz']:
        roll = data['roll']
        upg1 = data['upg1']
        corrupted1 = data['corrupted1']
        upg2 = data['upg2']
        corrupted2 = data['corrupted2']

        base_hp = base_stats[roll]
        curr_hp = calculate_armor_stat_at_level(base_hp, upg1, corrupted1, 1.0, "armor")
        des_hp = calculate_armor_stat_at_level(base_hp, upg2, corrupted2, 1.0, "armor")

        response += f"<b>ROLL:</b> <i>{roll}/11</i> | <b>BASE HP:</b> <i>{base_hp:,}</i>\n\n"

        response += f"<b>🔸 Текущее</b>\n"
        response += f"<b>UPG:</b> <i>{upg1}</i>\n"
        response += f"<b>Corrupted:</b> <i>{'Да' if corrupted1 else 'Нет'}</i>\n"
        response += f"<b>HP:</b> <i>{int(curr_hp):,}</i> ❤️\n"
        response += f"<b>Gold spent:</b> <i>{calculate_gold(item_info['upgrade_cost_lvl1'], upg1):,}</i> 💰\n\n"

        response += f"<b>🔹 Желаемое</b>\n"
        response += f"<b>UPG:</b> <i>{upg2} (+{upg2 - upg1})</i>\n"
        response += f"<b>Corrupted:</b> <i>{'Да' if corrupted2 else 'Нет'}</i>\n"
        response += f"<b>HP:</b> <i>{int(des_hp):,} (+{int(des_hp - curr_hp):,})</i> ❤️\n"
        response += f"<b>Gold needed:</b> <i>{max(0, calculate_gold(item_info['upgrade_cost_lvl1'], upg2) - calculate_gold(item_info['upgrade_cost_lvl1'], upg1)):,}</i> 💰"

    return response


def generate_armor_tablet_page(item_info: dict, armor_data: dict, part: str) -> str:
    """Генерация Tablet страницы для брони (моноширинный формат)"""
    part_names = {STAGE_HELMET: 'Шлем', STAGE_CHEST: 'Нагрудник', STAGE_LEGS: 'Штаны'}
    part_keys = {STAGE_HELMET: 'Helmet', STAGE_CHEST: 'Chestplate', STAGE_LEGS: 'Leggings'}

    if part not in armor_data or armor_data[part] is None:
        return "```ОШИБКА: Нет данных для этой части брони```"

    data = armor_data[part]
    part_key = part_keys[part]
    base_stats = item_info['stats'][part_key]

    # Определяем ролл
    if 'roll' in data:
        roll = data['roll']
    else:
        roll = find_roll_for_armor(base_stats, data['hp'], data['upg'], data['corrupted'])
    base_hp = base_stats[roll]
    corrupted = data.get('corrupted', False)

    # Заголовок таблицы
    header = f"{'UPG':<5} | {'Gold Cost':<11} | {'HP':<12}"
    sep = "-" * len(header)
    rows = [header, sep]

    b1 = item_info['upgrade_cost_lvl1']
    prev_gold = 0

    for level in range(0, item_info['max_level'] + 1):
        total_gold = calculate_gold(b1, level)
        level_cost = total_gold - prev_gold if level > 0 else 0
        prev_gold = total_gold

        hp = calculate_armor_stat_at_level(base_hp, level, corrupted, 1.0, "armor")
        rows.append(f"{level:<5} | {level_cost:<11,} | {hp:<12,}")
    table_content = "\n".join(rows)
    title_line = f"{item_info['name']} — {part_names[part]} | ROLL {roll}/11 | {'CORRUPTED' if corrupted else 'NORMAL'}"
    footer = "Gold for +1: стоимость текущего уровня"

    clean_name = item_info['name'].replace(' ', '_').replace("'", '').upper()
    block_name = f"{clean_name}_{part_key.upper()}_TABLET"
    return f"```{block_name}\n{title_line}\n\n{table_content}\n\n{footer}\n```"


def generate_armor_results_keyboard(command: str, armor_data: dict, user_msg_id: int,
                                    current_page: str = "total", current_part: str = None) -> InlineKeyboardMarkup:
    """Генерация клавиатуры результатов для брони"""
    buttons = []
    parts_order = ['helm', 'chest', 'legs']
    part_names = {'helm': 'Шлем', 'chest': 'Нагрудник', 'legs': 'Штаны'}

    # Сжимаем данные ОДИН РАЗ для всех кнопок
    packed_data = pack_armor_data(armor_data, command)

    for part in parts_order:
        if armor_data[part] is not None:
            part_buttons = []
            is_current = (part == current_part)

            # Текст кнопок
            if command in ['fz', 'z']:
                total_text = f"{'✓ ' if is_current and current_page == 'total' else ''}{part_names[part]} Total"
                process_text = f"{'✓ ' if is_current and current_page == 'process' else ''}< Process"
                tablet_text = f"{'✓ ' if is_current and current_page == 'tablet' else ''}< Tablet"

                # Формат: armor:command:part:page:user_msg_id:data
                base = f"armor:{command}:{part}:{{}}:{user_msg_id}:{packed_data}"
                part_buttons.append(InlineKeyboardButton(total_text, callback_data=base.format('t')))
                part_buttons.append(InlineKeyboardButton(process_text, callback_data=base.format('p')))
                part_buttons.append(InlineKeyboardButton(tablet_text, callback_data=base.format('b')))
            elif command in ['wfz', 'wz']:
                total_text = f"{'✓ ' if is_current and current_page == 'total' else ''}{part_names[part]} Total"
                process_text = f"{'✓ ' if is_current and current_page == 'process' else ''}< Process"

                base = f"armor:{command}:{part}:{{}}:{user_msg_id}:{packed_data}"
                part_buttons.append(InlineKeyboardButton(total_text, callback_data=base.format('t')))
                part_buttons.append(InlineKeyboardButton(process_text, callback_data=base.format('p')))
            elif command in ['lfz', 'lz']:
                total_text = f"{'✓ ' if is_current and current_page == 'total' else ''}{part_names[part]} Total"
                actual_text = f"{'✓ ' if is_current and current_page == 'actual_process' else ''}< Actual"
                wished_text = f"{'✓ ' if is_current and current_page == 'wished_process' else ''}< Wished"

                base = f"armor:{command}:{part}:{{}}:{user_msg_id}:{packed_data}"
                part_buttons.append(InlineKeyboardButton(total_text, callback_data=base.format('t')))
                part_buttons.append(InlineKeyboardButton(actual_text, callback_data=base.format('a')))
                part_buttons.append(InlineKeyboardButton(wished_text, callback_data=base.format('w')))
            buttons.append(part_buttons)

    # Кнопка Свернуть (отдельный формат)
    buttons.append([InlineKeyboardButton("Свернуть", callback_data=f"armor:close:::{user_msg_id}")])
    # DEBUG
    for row in buttons:
        for btn in row:
            cb = btn.callback_data
            byte_len = len(cb.encode('utf-8'))
            print(f"[DEBUG] callback_data = {cb!r}  ->  {byte_len} bytes")
            if byte_len > 64:
                print("⚠️  ПРЕВЫШЕН 64-байтный лимит!")
    return InlineKeyboardMarkup(buttons)


async def analyze_asc_weapon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для !asc {dmg} {upg} {y/n} {reforge}"""
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args = context.args
    errors = []

    # Проверка количества аргументов
    if len(args) not in (3, 4):
        errors.append(f"❌ Неверное количество аргументов ({len(args)}). Ожидается 3 или 4.")

    reforge_name = "None"
    reforge_mult = 1.0

    # Парсинг аргументов
    if len(args) >= 3:
        try:
            damage = float(args[0])
        except ValueError:
            errors.append(f"❌ Урон ({args[0]}) должен быть числом.")
        try:
            upg_level = int(args[1])
            if upg_level > 45 or upg_level < 0:
                errors.append(f"❌ Уровень оружия ({upg_level}) не соответствует 0-45.")
        except ValueError:
            errors.append(f"❌ Уровень улучшения ({args[1]}) должен быть числом.")

        is_corrupted_str = args[2].lower()
        if is_corrupted_str not in ('y', 'n'):
            errors.append(f"❌ Статус порчи ({is_corrupted_str}) должен быть 'y' или 'n'.")

        if len(args) == 4:
            reforge_input = args[3]
            found = False
            for k_ref in REFORGE_MODIFIERS:
                if k_ref.lower() == reforge_input.lower():
                    reforge_name = k_ref
                    reforge_mult = REFORGE_MODIFIERS[k_ref]
                    found = True
                    break
            if not found:
                errors.append(f"❌ Неизвестный Reforge ({reforge_input}), напишите !reforge для списка.")

    if errors:
        example = f"`{command_name}` {{dmg}} {{upg}} {{y/n}} {{reforge}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example}"
        if await _send_error(update, context, error_message, example):
            return

    # Все параметры успешно распарсены
    damage = float(args[0])
    upg_level = int(args[1])
    is_corrupted = args[2].lower() == 'y'

    try:
        # Определяем базовый урон, ролл и тип меча
        base_dmg, roll, is_ws = find_base_damage_for_asc(damage, upg_level, is_corrupted, reforge_mult)

        # Генерируем текст для Total страницы
        if is_ws:
            active_weapon = "ws"
        else:
            active_weapon = random.choice(["mb", "lk", "me", "pt", "dd"])
        active_key = f"asc_{active_weapon}"
        base_dmg = ITEMS_MAPPING[active_key]['stats'][roll]
        text = generate_asc_total_page(active_key, damage, upg_level, is_corrupted,
                                       reforge_name, reforge_mult, roll, base_dmg)
        keyboard = generate_asc_analysis_keyboard(
            damage, upg_level, is_corrupted, reforge_name,
            update.message.message_id,
            roll=roll, is_wooden_sword=is_ws,
            current_page="total", active_weapon=active_weapon)
        await update.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            reply_to_message_id=update.message.message_id
        )
    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


async def w_analyze_asc_weapon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для !wasc {roll} > {upg} {y/n} {reforge}"""
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args_raw = context.args
    errors = []

    # Поиск разделителя
    sep_idx = -1
    for idx, arg in enumerate(args_raw):
        if arg == '>':
            sep_idx = idx
            break

    if sep_idx == -1:
        errors.append("❌ Обязательный разделитель '>' не найден.")

    if not errors:
        left_args = args_raw[:sep_idx]
        right_args = args_raw[sep_idx + 1:]

        if len(left_args) != 1:
            errors.append(f"❌ Левая часть: неверное количество аргументов ({len(left_args)}). Ожидается 1 (roll).")
        if len(right_args) not in (2, 3):
            errors.append(f"❌ Правая часть: неверное количество аргументов ({len(right_args)}). Ожидается 2 или 3.")
    if errors:
        example = f"`{command_name}` {{ролл}} > {{upg}} {{y/n}} {{reforge}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Ролл: 6-11 для обычных мечей)"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    # Парсинг roll
    try:
        roll = int(left_args[0])
        if not 6 <= roll <= 11:
            errors.append(f"❌ Ролл ({roll}) должен быть в диапазоне 6-11 для ASC оружия.")
    except ValueError:
        errors.append(f"❌ Ролл ({left_args[0]}) должен быть числом.")
    # Парсинг правой части
    try:
        target_level = int(right_args[0])
        if target_level > 45 or target_level < 0:
            errors.append(f"❌ Уровень оружия ({target_level}) не соответствует 0-45.")
    except ValueError:
        errors.append(f"❌ Уровень улучшения ({right_args[0]}) должен быть числом.")

    is_corrupted_str = right_args[1].lower()
    if is_corrupted_str not in ('y', 'n'):
        errors.append(f"❌ Статус порчи ({is_corrupted_str}) должен быть 'y' или 'n'.")

    reforge_name = "None"
    reforge_mult = 1.0
    if len(right_args) == 3:
        reforge_input = right_args[2]
        found = False
        for k_ref in REFORGE_MODIFIERS:
            if k_ref.lower() == reforge_input.lower():
                reforge_name = k_ref
                reforge_mult = REFORGE_MODIFIERS[k_ref]
                found = True
                break
        if not found:
            errors.append(f"❌ Неизвестный Reforge ({reforge_input}), напишите !reforge для списка.")
    if errors:
        example = f"`{command_name}` {{ролл}} > {{upg}} {{y/n}} {{reforge}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Ролл: 6-11)"
        if await _send_error(update, context, error_message, example):
            return

    roll = int(left_args[0])  # <-- Это original_roll
    target_level = int(right_args[0])
    is_corrupted = is_corrupted_str == 'y'

    try:
        active_weapon = random.choice(["mb", "lk", "me", "pt", "dd", "ws"])
        active_key = f"asc_{active_weapon}"

        # Для конкретного меча используем weapon_roll
        weapon_roll = 11 if active_weapon == "ws" else roll
        base_dmg = ITEMS_MAPPING[active_key]['stats'][weapon_roll]
        dmg = calculate_weapon_stat_at_level(base_dmg, target_level, is_corrupted, reforge_mult)

        text = generate_asc_total_page(active_key, dmg, target_level, is_corrupted,
                                       reforge_name, reforge_mult,
                                       weapon_roll,
                                       base_dmg)

        keyboard = generate_asc_forecast_keyboard(
            original_roll=roll,  # <-- передаем изначальный roll
            upg=target_level,
            corr=is_corrupted,
            reforge_name=reforge_name,
            user_msg_id=update.message.message_id,
            current_page="total",
            active_weapon=active_weapon
        )
        await update.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            reply_to_message_id=update.message.message_id
        )
    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


async def l_analyze_asc_weapon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для !lasc {roll} - {upg} {y/n} {reforge} > {upg} {y/n} {reforge}"""
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args_raw = context.args
    errors = []

    # Поиск разделителей
    minus_idx = -1
    gt_idx = -1
    for idx, arg in enumerate(args_raw):
        if arg == '-' and minus_idx == -1:
            minus_idx = idx
        elif arg == '>' and gt_idx == -1:
            gt_idx = idx

    if minus_idx == -1:
        errors.append("❌ Обязательный разделитель '-' не найден.")
    if gt_idx == -1:
        errors.append("❌ Обязательный разделитель '>' не найден.")
    if minus_idx != -1 and gt_idx != -1 and gt_idx <= minus_idx:
        errors.append("❌ Неверный порядок разделителей. Ожидается: {roll} - ... > ...")

    if not errors:
        roll_part = args_raw[:minus_idx]
        mid_part = args_raw[minus_idx + 1:gt_idx]
        right_part = args_raw[gt_idx + 1:]

        if len(roll_part) != 1:
            errors.append(f"❌ Ролл: ожидается 1 аргумент, получено {len(roll_part)}.")
        if len(mid_part) not in (2, 3):
            errors.append(f"❌ Текущее состояние: ожидается 2 или 3 аргумента, получено {len(mid_part)}.")
        if len(right_part) not in (2, 3):
            errors.append(f"❌ Желаемое состояние: ожидается 2 или 3 аргумента, получено {len(right_part)}.")

    # Парсинг roll
    if not errors:
        try:
            curr_roll = int(roll_part[0])
            if not 6 <= curr_roll <= 11:
                errors.append(f"❌ Ролл ({curr_roll}) должен быть в диапазоне 6-11 для ASC оружия.")
        except ValueError:
            errors.append(f"❌ Ролл ({roll_part[0]}) должен быть числом.")

    # Парсинг текущего состояния
    if not errors:
        try:
            curr_upg = int(mid_part[0])
            if not 0 <= curr_upg <= 45:
                errors.append(f"❌ Текущий уровень ({mid_part[0]}) не в 0-45.")
        except ValueError:
            errors.append(f"❌ Текущий уровень ({mid_part[0]}) должен быть числом.")

        curr_corr_str = mid_part[1].lower()
        if curr_corr_str not in ('y', 'n'):
            errors.append(f"❌ Текущий corrupted ({mid_part[1]}) должен быть 'y' или 'n'.")

        curr_ref_name = "None"
        curr_ref_mult = 1.0
        if len(mid_part) == 3:
            ref = mid_part[2]
            found = False
            for k in REFORGE_MODIFIERS:
                if k.lower() == ref.lower():
                    curr_ref_name = k
                    curr_ref_mult = REFORGE_MODIFIERS[k]
                    found = True
                    break
            if not found:
                errors.append(f"❌ Неизвестный текущий reforge ({ref}).")

    # Парсинг желаемого состояния
    if not errors:
        try:
            des_upg = int(right_part[0])
            if not 0 <= des_upg <= 45:
                errors.append(f"❌ Желаемый уровень ({right_part[0]}) не в 0-45.")
        except ValueError:
            errors.append(f"❌ Желаемый уровень ({right_part[0]}) должен быть числом.")

        des_corr_str = right_part[1].lower()
        if des_corr_str not in ('y', 'n'):
            errors.append(f"❌ Желаемый corrupted ({right_part[1]}) должен быть 'y' или 'n'.")

        des_ref_name = "None"
        des_ref_mult = 1.0
        if len(right_part) == 3:
            ref = right_part[2]
            found = False
            for k in REFORGE_MODIFIERS:
                if k.lower() == ref.lower():
                    des_ref_name = k
                    des_ref_mult = REFORGE_MODIFIERS[k]
                    found = True
                    break
            if not found:
                errors.append(f"❌ Неизвестный желаемый reforge ({ref}).")

    # Проверка коррупта
    if not errors and curr_corr_str == 'y' and des_corr_str == 'n':
        errors.append("❌ Нельзя декорраптить (y → n запрещено).")

    if errors:
        example = f"`{command_name}` {{ролл}} - {{upg}} {{y/n}} [reforge] > {{upg}} {{y/n}} [reforge]"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n" + example + "\n(Ролл: 6-11)"
        if await _send_error(update, context, error_message, example):
            return

    curr_corr = curr_corr_str == 'y'
    des_corr = des_corr_str == 'y'
    curr_roll = int(roll_part[0])

    try:
        # Генерируем текст для Total страницы
        active_weapon = random.choice(["mb", "lk", "me", "pt", "dd", "ws"])
        active_key = f"asc_{active_weapon}"

        # Для конкретного меча используем weapon_roll
        weapon_roll = 11 if active_weapon == "ws" else curr_roll
        text = generate_compare_total_page(
            ITEMS_MAPPING[active_key],
            weapon_roll,  # <-- используем weapon_roll
            curr_upg, curr_corr, curr_ref_mult, curr_ref_name,
            des_upg, des_corr, des_ref_mult, des_ref_name
        )

        keyboard = generate_asc_compare_keyboard(
            roll=curr_roll,  # <-- передаем изначальный roll
            curr_upg=curr_upg,
            curr_corr=curr_corr,
            curr_ref=curr_ref_name,
            des_upg=des_upg,
            des_corr=des_corr,
            des_ref=des_ref_name,
            user_msg_id=update.message.message_id,
            current_page="total",
            active_weapon=active_weapon
        )
        await update.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            reply_to_message_id=update.message.message_id
        )
    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчёте: {e}")


# --- ФУНКЦИИ АНАЛИЗА ТЕКУЩЕГО ПРЕДМЕТА (СТАРЫЕ КОМАНДЫ: !conq, !doom, !fzhelm, и т.д.) ---

async def analyze_weapon(update: Update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    item_info = ITEMS_MAPPING[item_key]
    max_lvl = item_info['max_level']
    args = context.args
    errors = []

    reforge_name = "None"
    reforge_mult = 1.0

    if len(args) not in (3, 4):
        errors.append(f"❌ Неверное количество аргументов ({len(args)}). Ожидается 3 или 4.")

    if len(args) in (3, 4):
        try:
            damage = float(args[0])
        except ValueError:
            errors.append(f"❌ Урон ({args[0]}) должен быть числом.")

        try:
            upg_level = int(args[1])
            if upg_level > max_lvl or upg_level < 0:
                errors.append(f"❌ Уровень меча ({upg_level}) не соответствует 0-{max_lvl}.")
        except ValueError:
            errors.append(f"❌ Уровень улучшения ({args[1]}) должен быть числом.")

        is_corrupted_str = args[2].lower()
        if is_corrupted_str not in ('y', 'n'):
            errors.append(f"❌ Статус порчи ({is_corrupted_str}) должен быть 'y' или 'n'.")

        if len(args) == 4:
            reforge_input = args[3]
            found = False
            for k_ref in REFORGE_MODIFIERS:
                if k_ref.lower() == reforge_input.lower():
                    reforge_name = k_ref
                    reforge_mult = REFORGE_MODIFIERS[k_ref]
                    found = True
                    break
            if not found:
                errors.append(f"❌ Неизвестный Reforge ({reforge_input}), напишите !reforge для списка.")

    if errors:
        example = f"`{command_name}` {{dmg}} {{upg}} {{y/n}} {{reforge}} \n(если reforge нет - не пишите)"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        if await _send_error(update, context, error_message, example):
            return

    damage = float(args[0])
    upg_level = int(args[1])
    is_corrupted = args[2].lower() == 'y'

    try:
        base_stats = item_info['stats']
        inferred_base = infer_base_for_weapon(damage, upg_level, is_corrupted, reforge_mult)
        roll = determine_roll(base_stats, inferred_base)
        base_dmg = base_stats[roll]

        text = generate_total_page(item_info, damage, upg_level, is_corrupted,
                                   reforge_name, reforge_mult, roll, base_dmg)

        keyboard = generate_weapon_analysis_keyboard(
            item_key=item_key,
            current_page="total",
            dmg=damage,
            upg=upg_level,
            corr=is_corrupted,
            reforge_name=reforge_name,
            user_msg_id=update.message.message_id  # ← фикс для всех страниц
        )
        await update.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            reply_to_message_id=update.message.message_id
        )
    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


# --- ФУНКЦИИ ПРОГНОЗИРОВАНИЯ (СТАРЫЕ КОМАНДЫ: !wconq, !wdoom, !wfzhelm, и.т.д.) ---

async def w_analyze_weapon(update: Update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args_raw = context.args
    item_info = ITEMS_MAPPING[item_key]
    max_lvl = item_info['max_level']
    errors = []

    reforge_name = "None"
    reforge_mult = 1.0

    if len(args_raw) not in (4, 5):
        errors.append(f"❌ Неверное количество аргументов ({len(args_raw)}). Ожидается 4 или 5 (с разделителем '>').")

    if len(args_raw) >= 2:
        if args_raw[1] != '>':
            errors.append(f"❌ Неправильный разделитель ({args_raw[1]}), ожидается '>'.")

    args = clean_args_from_separator(args_raw)

    if len(args) not in (3, 4):
        if len(args_raw) in (4, 5) and args_raw[1] == '>':
            pass
        elif not errors:
            errors.append(f"❌ Неверное количество параметров ({len(args)}) после разделителя (ожидается 3 или 4).")

    if len(args) in (3, 4):
        try:
            roll = int(args[0])
            if not (1 <= roll <= 11):
                errors.append(f"❌ Значение ролла ({roll}) не соответствует 1-11.")
        except ValueError:
            errors.append(f"❌ Ролл ({args[0]}) должен быть числом.")

        try:
            target_level = int(args[1])
            if target_level > max_lvl or target_level < 0:
                errors.append(f"❌ Уровень меча ({target_level}) не соответствует 0-{max_lvl}.")
        except ValueError:
            errors.append(f"❌ Уровень улучшения ({args[1]}) должен быть числом.")

        is_corrupted_str = args[2].lower()
        if is_corrupted_str not in ('y', 'n'):
            errors.append(f"❌ Статус порчи ({is_corrupted_str}) должен быть 'y' или 'n'.")

        if len(args) == 4:
            reforge_input = args[3]
            found = False
            for k_ref in REFORGE_MODIFIERS:
                if k_ref.lower() == reforge_input.lower():
                    reforge_name = k_ref
                    reforge_mult = REFORGE_MODIFIERS[k_ref]
                    found = True
                    break
            if not found:
                errors.append(f"❌ Неизвестный Reforge ({reforge_input}), напишите !reforge для списка.")

    if errors:
        example = f"`{command_name}` {{ролл}} > {{upg до {max_lvl}}} {{y/n}} {{reforge}} \n(если reforge нет - не пишите)"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example}"
        if await _send_error(update, context, error_message, example):
            return

    roll = int(args[0])
    target_level = int(args[1])
    is_corrupted = args[2].lower() == 'y'

    try:
        base_stats = item_info['stats']
        base_dmg = base_stats[roll]

        text = generate_forecast_total_page(item_info, roll, target_level, is_corrupted,
                                            reforge_name, reforge_mult)

        keyboard = generate_weapon_forecast_keyboard(
            item_key=item_key,
            current_page="total",
            roll=roll,
            upg=target_level,
            corr=is_corrupted,
            reforge_name=reforge_name,
            user_msg_id=update.message.message_id  # ← фикс
        )
        await update.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            reply_to_message_id=update.message.message_id
        )
    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


# --- L-ФУНКЦИИ (СРАВНЕНИЕ) ---

async def l_analyze_weapon(update: Update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    """Сравнение оружия: !lconq / !ldoom
    Формат: {roll} - {upg1} {y/n1} [reforge1] > {upg2} {y/n2} [reforge2]
    reforge в обеих частях необязателен."""
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args_raw = context.args
    item_info = ITEMS_MAPPING[item_key]
    max_lvl = item_info['max_level']
    errors = []

    # --- 1. Ищем оба разделителя ---
    minus_idx = -1
    gt_idx = -1
    for idx, arg in enumerate(args_raw):
        if arg == '-' and minus_idx == -1:
            minus_idx = idx
        elif arg == '>' and gt_idx == -1:
            gt_idx = idx

    if minus_idx == -1:
        errors.append("❌ Обязательный разделитель '-' не найден.")
    if gt_idx == -1:
        errors.append("❌ Обязательный разделитель '>' не найден.")
    if minus_idx != -1 and gt_idx != -1 and gt_idx <= minus_idx:
        errors.append("❌ Неверный порядок разделителей. Ожидается: {roll} - ... > ...")

    if not errors:
        roll_part = args_raw[:minus_idx]
        mid_part = args_raw[minus_idx + 1:gt_idx]
        right_part = args_raw[gt_idx + 1:]

        if len(roll_part) != 1:
            errors.append(f"❌ Левая часть: ожидается 1 аргумент (roll), получено {len(roll_part)}.")
        # mid/right: 2 аргумента минимум, 3 максимум
        if len(mid_part) not in (2, 3):
            errors.append(
                f"❌ Средняя часть: ожидается 2 или 3 аргумента (текущее состояние), получено {len(mid_part)}.")
        if len(right_part) not in (2, 3):
            errors.append(
                f"❌ Правая часть: ожидается 2 или 3 аргумента (желаемое состояние), получено {len(right_part)}.")

    # --- 2. Парсинг roll ---
    if not errors:
        try:
            curr_roll = int(roll_part[0])
            if not 1 <= curr_roll <= 11:
                errors.append(f"❌ Ролл ({roll_part[0]}) не в диапазоне 1-11.")
        except ValueError:
            errors.append(f"❌ Ролл ({roll_part[0]}) должен быть числом.")

    # --- 3. Парсинг текущего состояния ---
    if not errors:
        try:
            curr_upg = int(mid_part[0])
            if not 0 <= curr_upg <= max_lvl:
                errors.append(f"❌ Текущий уровень ({mid_part[0]}) не в 0-{max_lvl}.")
        except ValueError:
            errors.append(f"❌ Текущий уровень ({mid_part[0]}) должен быть числом.")

        curr_corr_str = mid_part[1].lower()
        if curr_corr_str not in ('y', 'n'):
            errors.append(f"❌ Текущий corrupted ({mid_part[1]}) должен быть 'y' или 'n'.")

        curr_ref_name = "None"
        curr_ref_mult = 1.0
        if len(mid_part) == 3:
            ref = mid_part[2]
            found = False
            for k in REFORGE_MODIFIERS:
                if k.lower() == ref.lower():
                    curr_ref_name = k
                    curr_ref_mult = REFORGE_MODIFIERS[k]
                    found = True
                    break
            if not found:
                errors.append(f"❌ Неизвестный текущий reforge ({ref}).")

    # --- 4. Парсинг желаемого состояния ---
    if not errors:
        try:
            des_upg = int(right_part[0])
            if not 0 <= des_upg <= max_lvl:
                errors.append(f"❌ Желаемый уровень ({right_part[0]}) не в 0-{max_lvl}.")
        except ValueError:
            errors.append(f"❌ Желаемый уровень ({right_part[0]}) должен быть числом.")

        des_corr_str = right_part[1].lower()
        if des_corr_str not in ('y', 'n'):
            errors.append(f"❌ Желаемый corrupted ({right_part[1]}) должен быть 'y' или 'n'.")

        des_ref_name = "None"
        des_ref_mult = 1.0
        if len(right_part) == 3:
            ref = right_part[2]
            found = False
            for k in REFORGE_MODIFIERS:
                if k.lower() == ref.lower():
                    des_ref_name = k
                    des_ref_mult = REFORGE_MODIFIERS[k]
                    found = True
                    break
            if not found:
                errors.append(f"❌ Неизвестный желаемый reforge ({ref}).")

    # --- 5. Проверка corrupt ---
    if not errors and curr_corr_str == 'y' and des_corr_str == 'n':
        errors.append("❌ Нельзя декорраптить (y → n запрещено).")

    # --- 6. Вывод ошибок, если есть ---
    if errors:
        example = f"`{command_name}` {{ролл}} - {{upg}} {{y/n}} [reforge] > {{upg}} {{y/n}} [reforge]"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n" + example + f"\n(Макс. ур: {max_lvl})"
        if await _send_error(update, context, error_message, example):
            return

    # --- 7. Расчёт и вывод ---
    curr_corr = curr_corr_str == 'y'
    des_corr = des_corr_str == 'y'

    try:
        text = generate_compare_total_page(
            item_info, curr_roll, curr_upg, curr_corr, curr_ref_mult, curr_ref_name,
            des_upg, des_corr, des_ref_mult, des_ref_name
        )
        keyboard = generate_weapon_compare_keyboard(
            item_key, "total", curr_roll, curr_upg, curr_corr, curr_ref_name,
            des_upg, des_corr, des_ref_name,
            user_msg_id=update.message.message_id
        )
        await update.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            reply_to_message_id=update.message.message_id
        )
    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчёте: {e}")


async def handle_armor_command(update: Update, context: ContextTypes.DEFAULT_TYPE, command: str):
    """Обработчик команд брони (!fz, !z, !wfz, !wz, !lfz, !lz)"""
    if not is_allowed_thread(update):
        return

    user_id = update.effective_user.id
    if user_id in user_armor_data:
        error_message = "🛑 **Вы уже начали сессию, закончите её введением данных, либо же нажатием кнопки ""Отмена"".**\n"
        error_message += "Если вы вводите аргументы вместе с командой \n(типа: !wfz 7 > 32 y),\n то просто не пишите аргументы с командой. Это написано у вас в ПРИМЕРЕ НАПИСАНИЯ. Будьте внимательнее"
        if await _send_error(update, context, error_message, ""):
            return

    item_key = "fzh" if command in {'fz', 'wfz', 'lfz'} else "lzs"
    item_info = ITEMS_MAPPING[item_key]
    max_level = item_info['max_level']
    print(f"[DEBUG] item_key={item_key}, max_level={item_info['max_level']}")

    # Инициализируем данные пользователя
    user_armor_data[user_id] = {
        'command': command,
        'data': {STAGE_HELMET: None, STAGE_CHEST: None, STAGE_LEGS: None},
        'stage': STAGE_HELMET,
        'item_key': item_key,
        'max_level': max_level,
        'user_msg_id': update.message.message_id,
        'chat_id': update.effective_chat.id  # Сохраняем chat_id
    }
    # Отправляем первый запрос
    prompt_text = get_armor_prompt_text(command, STAGE_HELMET, max_level)
    keyboard = get_armor_stage_keyboard(STAGE_HELMET, update.message.message_id)

    bot_msg = await update.message.reply_text(
        text=prompt_text,
        parse_mode=ParseMode.HTML,  # ← вот это
        reply_markup=keyboard,
        reply_to_message_id=update.message.message_id
    )
    # Сохраняем ID сообщения бота
    user_armor_data[user_id]['bot_msg_id'] = bot_msg.message_id


import asyncio  # нужен для задержки

# ------------------------------------------------------------------
#  храним: user_id  -> (bot_msg_id, last_error_text)
_last_err: dict[int, tuple[int, str]] = {}
# user_id -> deque([msg_id, msg_id, ...])
_err_queue: dict[int, deque[int]] = {}


async def handle_armor_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ввода данных для брони. Принимает ЛЮБОЙ текстовый ввод и валидирует его."""
    if not is_allowed_thread(update):
        return

    text = update.message.text.strip()
    if text.startswith('!'):
        return  # пусть bang_router разбирается

    user_id = update.effective_user.id
    if user_id not in user_armor_data:
        return  # не наш диалог — игнорируем

    user_data = user_armor_data[user_id]
    command = user_data['command']
    stage = user_data['stage']
    max_level = user_data['max_level']
    parts = text.split()

    example_map = {
        'fz': '{hp} {upg} {y/n}',
        'z': '{hp} {upg} {y/n}',
        'wfz': '{roll} > {upg} {y/n}',
        'wz': '{roll} > {upg} {y/n}',
        'lfz': '{roll} - {upg1} {y/n1} > {upg2} {y/n2}',
        'lz': '{roll} - {upg1} {y/n1} > {upg2} {y/n2}'
    }
    example = f"{example_map.get(command, '{аргументы}')}"

    errors = []
    stage_data = None

    # ---------- валидация ----------
    if command in ('fz', 'z'):
        if len(parts) != 3:
            errors.append(f"❌ Неверное количество аргументов ({len(parts)}). Ожидается 3.")
        else:
            try:
                float(parts[0])
            except ValueError:
                errors.append(f"❌ HP ({parts[0]}) должен быть числом.")
            try:
                upg = int(parts[1])
                if not 0 <= upg <= max_level: errors.append(f"❌ UPG ({upg}) должен быть в диапазоне 0-{max_level}.")
            except ValueError:
                errors.append(f"❌ UPG ({parts[1]}) должен быть числом.")
            if parts[2].lower() not in ('y', 'n'): errors.append(f"❌ Corrupted ({parts[2]}) должен быть 'y' или 'n'.")
    elif command in ('wfz', 'wz'):
        if len(parts) != 4 or parts[1] != '>':
            errors.append("❌ Неверный формат. Ожидается: {roll} > {upg} {y/n}")
        else:
            try:
                roll = int(parts[0])
                if not 1 <= roll <= 11: errors.append(f"❌ Roll ({roll}) должен быть в диапазоне 1-11.")
            except ValueError:
                errors.append(f"❌ Roll ({parts[0]}) должен быть числом.")
            try:
                upg = int(parts[2])
                if not 0 <= upg <= max_level: errors.append(f"❌ UPG ({upg}) должен быть в диапазоне 0-{max_level}.")
            except ValueError:
                errors.append(f"❌ UPG ({parts[2]}) должен быть числом.")
            if parts[3].lower() not in ('y', 'n'): errors.append(f"❌ Corrupted ({parts[3]}) должен быть 'y' или 'n'.")
    elif command in ('lfz', 'lz'):
        if len(parts) != 7 or parts[1] != '-' or parts[4] != '>':
            errors.append("❌ Неверный формат. Ожидается: {roll} - {upg1} {y/n1} > {upg2} {y/n2}")
        else:
            try:
                roll = int(parts[0])
                if not 1 <= roll <= 11: errors.append(f"❌ Roll ({roll}) должен быть в диапазоне 1-11.")
            except ValueError:
                errors.append(f"❌ Roll ({parts[0]}) должен быть числом.")
            try:
                upg1 = int(parts[2])
                if not 0 <= upg1 <= max_level: errors.append(f"❌ UPG1 ({upg1}) должен быть в диапазоне 0-{max_level}.")
            except ValueError:
                errors.append(f"❌ UPG1 ({parts[2]}) должен быть числом.")
            if parts[3].lower() not in ('y', 'n'): errors.append(f"❌ Corrupted1 ({parts[3]}) должен быть 'y' или 'n'.")
            try:
                upg2 = int(parts[5])
                if not 0 <= upg2 <= max_level: errors.append(f"❌ UPG2 ({upg2}) должен быть в диапазоне 0-{max_level}.")
            except ValueError:
                errors.append(f"❌ UPG2 ({parts[5]}) должен быть числом.")
            if parts[6].lower() not in ('y', 'n'): errors.append(f"❌ Corrupted2 ({parts[6]}) должен быть 'y' или 'n'.")
            if parts[3].lower() == 'y' and parts[6].lower() == 'n': errors.append(
                "❌ Нельзя декорраптить (y → n запрещено).")

    # ---------- вывод ошибок (анти-спам) ----------
    if errors:
        # Вариант 1: Создать переменную заранее (рекомендуется)
        errors_str = '\n'.join(errors)
        error_text = (
            f"🛑 **Обнаружены ошибки формата для `!{command}`:**\n"
            f"{errors_str}\n\n"
            f"**Пример написания:**\n{example}"
        )
        chat_id = update.effective_chat.id
        thread_id = update.effective_message.message_thread_id

        # сразу удаляем сообщение игрока
        try:
            await update.message.delete()
        except Exception:
            pass

        # отправляем своё
        try:
            msg = await context.bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=error_text,
                parse_mode=ParseMode.MARKDOWN
            )
            _err_queue.setdefault(user_id, deque()).append(msg.message_id)
        except Exception:
            return

        # 3-секундный таймер на пачку
        async def _del_batch():
            await asyncio.sleep(3)
            msgs = _err_queue.pop(user_id, deque())
            for mid in msgs:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass

        # запускаем таймер только один раз за «сессию» спама
        if len(_err_queue[user_id]) == 1:  # первое сообщение – пустили таймер
            asyncio.create_task(_del_batch())
        return

    # ---------- сохранение данных ----------
    if command in ('fz', 'z'):
        stage_data = {'hp': float(parts[0]), 'upg': int(parts[1]), 'corrupted': parts[2].lower() == 'y'}
    elif command in ('wfz', 'wz'):
        stage_data = {'roll': int(parts[0]), 'upg': int(parts[2]), 'corrupted': parts[3].lower() == 'y'}
    elif command in ('lfz', 'lz'):
        stage_data = {
            'roll': int(parts[0]),
            'upg1': int(parts[2]), 'corrupted1': parts[3].lower() == 'y',
            'upg2': int(parts[5]), 'corrupted2': parts[6].lower() == 'y'
        }
    user_data['data'][stage] = stage_data
    await update.message.delete()

    # ---------- переход к следующей части ----------
    next_stage_map = {STAGE_HELMET: STAGE_CHEST, STAGE_CHEST: STAGE_LEGS}
    next_stage = next_stage_map.get(stage)
    if next_stage:
        user_data['stage'] = next_stage
        prompt = get_armor_prompt_text(command, next_stage, max_level)
        keyboard = get_armor_stage_keyboard(next_stage, user_data['user_msg_id'])
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=user_data['bot_msg_id'],
                text=prompt,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        except Exception:
            bot_msg = await update.message.reply_text(prompt, parse_mode=ParseMode.HTML,
                                                      reply_markup=keyboard)
            user_data['bot_msg_id'] = bot_msg.message_id
    else:
        await generate_armor_results(update, context, user_id)


async def armor_stage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback для кнопок Пропустить/Отмена в этапах ввода брони"""
    query = update.callback_query
    await query.answer()

    if not is_allowed_thread(update):
        return

    data_parts = query.data.split(":")
    action = data_parts[0]
    stage = data_parts[1] if len(data_parts) > 2 else None
    user_msg_id = int(data_parts[-1])

    user_id = update.effective_user.id

    # 🛑 ПРОВЕРКА ВЛАДЕЛЬЦА: только тот, кто начал сессию
    if user_id not in user_armor_data or user_armor_data[user_id]['user_msg_id'] != user_msg_id:
        # Дополнительная проверка через reply_to_message (на всякий случай)
        if not check_message_ownership(query, strict=False):
            await query.answer("Это не ваша сессия!", show_alert=True)
            return

    if action == "armor_skip":
        if user_id not in user_armor_data:
            return

        user_data = user_armor_data[user_id]
        next_stage = None

        # Определяем следующий этап
        if stage == STAGE_HELMET:
            next_stage = STAGE_CHEST
        elif stage == STAGE_CHEST:
            next_stage = STAGE_LEGS

        if next_stage:
            user_data['stage'] = next_stage
            prompt_text = get_armor_prompt_text(user_data['command'], next_stage, user_data['max_level'])
            keyboard = get_armor_stage_keyboard(next_stage, user_msg_id)

            try:
                await query.message.edit_text(
                    text=prompt_text,
                    parse_mode=ParseMode.HTML,  # <-- Добавить сюда
                    reply_markup=keyboard
                )
            except:
                pass
        else:
            # Последний этап - генерируем результаты
            await generate_armor_results(update, context, user_id)

    elif action == "armor_cancel":
        # Отмена - удаляем все сообщения и данные
        try:
            await query.message.delete()
            await context.bot.delete_message(
                chat_id=query.message.chat_id,
                message_id=user_msg_id
            )
        except:
            pass

        if user_id in user_armor_data:
            del user_armor_data[user_id]


async def armor_results_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    print(f"[ARMOR_CB] Получен callback: {query.data}")

    # 🛑 ПРОВЕРКА ВЛАДЕЛЬЦА
    if not check_message_ownership(query):
        await query.answer("Это не ваше сообщение!", show_alert=True)
        return

    await query.answer()

    if not is_allowed_thread(update):
        return

    data_parts = query.data.split(":")
    if len(data_parts) < 5:
        return

    # Обработка Свернуть
    if data_parts[1] == "close":
        try:
            user_msg_id = int(data_parts[-1])
            await query.message.delete()
            await context.bot.delete_message(
                chat_id=query.message.chat_id,
                message_id=user_msg_id
            )
        except Exception as e:
            print(f"Ошибка при сворачивании: {e}")
        return
    # Обычные действия
    if len(data_parts) != 6:
        print(f"[LOG] Неверный формат: {data_parts}")
        return

    _, command, part, page, user_msg_id, packed_data = data_parts

    # Распаковываем данные
    armor_data = unpack_armor_data(packed_data, command)
    if not armor_data:
        await query.answer("Ошибка: данные повреждены", show_alert=True)
        return

    # Определяем item_key
    item_key = "fzh" if command in ['fz', 'wfz', 'lfz'] else "lzs"
    item_info = ITEMS_MAPPING[item_key]

    # Преобразуем страницу
    page_map = {'t': 'total', 'p': 'process', 'b': 'tablet', 'a': 'actual_process', 'w': 'wished_process'}
    page_full = page_map.get(page, page)

    # Генерируем текст
    if page_full == "total":
        text = generate_armor_part_page(item_info, armor_data, command, part)
    elif page_full == "process":
        text = generate_armor_process_page(item_info, armor_data, command, part, "process")
    elif page_full == "tablet":
        text = generate_armor_tablet_page(item_info, armor_data, part)
    else:
        text = generate_armor_process_page(item_info, armor_data, command, part, page_full)

    # Генерируем клавиатуру с теми же данными
    keyboard = generate_armor_results_keyboard(command, armor_data, int(user_msg_id), current_page=page_full,
                                               current_part=part)

    try:
        await query.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML if page_full != "tablet" else ParseMode.MARKDOWN_V2,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"Ошибка при редактировании: {e}")


async def generate_armor_results(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    user_data = user_armor_data[user_id]
    command = user_data['command']
    item_key = user_data['item_key']
    item_info = ITEMS_MAPPING[item_key]
    armor_data = user_data['data']
    chat_id = user_data['chat_id']
    user_msg_id = user_data['user_msg_id']

    # Удаляем сообщение бота с запросом
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=user_data['bot_msg_id'])
    except:
        pass

    # Проверка: если ничего не введено
    if not any(armor_data.values()):
        insults = [
            "Ну и, что ты решил делать? Ты нихуя не написал, пиши команду заново!",
            "Нету данных - нет конфетки, пошёл нахуй! Если тебе не надо ещё раз писать ебаную команду",
            "Ахахаххаах, ебать. Пиши заново, ебанько) Без данных тебя даже в дурку не примут",
            "Еблан, ты вкурсе что ты везде прожал 3 раза Пропустить? Пиши заново, блять",
            "ЧМО ЕБАНОЕ, НАХУЙ ЕБЁШЬ МОЗГИ? ТЫ ВСЁ ПРОСКИПАЛ И РАДИ ЧЕГО? ЗАНОВО!",
            "Я бы желал вам, месье, дать по еблищу, но мне жаль, что я цифровая моделька. Имейте совесть, не ебите мозг даже мне, и админу. Если вам ненадо вводить, не пишите ебаную команду, сука!",
            "Это что-то типа: ""ХУЕСОСЫ ЕБАНЫЕ! О, кнопка Пропустить"" Уёбок. Пиши заново"
        ]

        # Отправляем гневное сообщение и запоминаем его ID
        insult_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=random.choice(insults),
            reply_to_message_id=user_msg_id
        )
        # Удаляем команду пользователя
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=user_msg_id)
        except:
            pass

        # Удаляем своё сообщение через 5 секунд
        async def delete_insult_after_delay():
            await asyncio.sleep(5)
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=insult_msg.message_id)
            except:
                pass

        asyncio.create_task(delete_insult_after_delay())

        del user_armor_data[user_id]
        return

    # Находим первую заполненную часть
    first_part = None
    for part in [STAGE_HELMET, STAGE_CHEST, STAGE_LEGS]:
        if armor_data[part] is not None:
            first_part = part
            break

    # Генерируем клавиатуру и текст для первой части
    # ТЕПЕРЬ ПЕРЕДАЁМ ПОЛНЫЕ armor_data
    keyboard = generate_armor_results_keyboard(command, armor_data, user_msg_id, current_page="total",
                                               current_part=first_part)
    text = generate_armor_part_page(item_info, armor_data, command, first_part)

    # Добавляем TOTAL HP, если все 3 части заполнены
    if all(armor_data.values()):
        total_hp = 0
        for part in [STAGE_HELMET, STAGE_CHEST, STAGE_LEGS]:
            data = armor_data[part]
            part_key = PART_MAPPING[part]
            base_stats = item_info['stats'][part_key]
            if command in ['fz', 'z']:
                roll = find_roll_for_armor(base_stats, data['hp'], data['upg'], data['corrupted'])
                base_hp = base_stats[roll]
                total_hp += data['hp']
            elif command in ['wfz', 'wz']:
                base_hp = base_stats[data['roll']]
                total_hp += calculate_armor_stat_at_level(base_hp, data['upg'], data['corrupted'], 1.0, "armor")
        text += f"\n\n<b>TOTAL HP:</b> <i>{int(total_hp):,}</i> ❤️"

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        reply_to_message_id=user_msg_id
    )
    # Очищаем временные данные (НО callback'и уже не зависят от них!)
    del user_armor_data[user_id]


# --- ТАБЛИЦЫ РОЛЛОВ ---

# Для ОРУЖИЯ (!conqr, !doomr)
async def format_sword_table(update, title, stats_dict):
    # Фиксируем шапку
    # Roll начинается с 0, Normal с 8, Corrupted с 21
    header = f"{'Roll':<5} | {'Normal':<10} | {'Corrupted':<12}"
    sep = "-" * len(header)
    rows = [header, sep]

    for level in range(1, 12):
        val = stats_dict.get(level, 0)
        corr = val * 1.5

        # Убираем .0
        v_str = f"{val:g}"
        c_str = f"{corr:g}"

        # Используем левое выравнивание с фиксированной шириной ПЕРЕД разделителем.
        # Это гарантирует, что каждое число начнется строго в одной и той же позиции.
        rows.append(f"{level:<5} | {v_str:<10} | {c_str:<12}")

    res = "\n".join(rows)
    await update.message.reply_text(f"```{title}\n{res}\n```", parse_mode=ParseMode.MARKDOWN_V2)


# Для БРОНИ (!fzr, !zr)
async def format_armor_table(update, title, stats_dict):
    # Увеличил ширину до 18, так как добавились пробелы вокруг "/"
    header = f"{'Roll':<5} | {'Helmet':<18} | {'Chestplate':<18} | {'Leggings':<18}"
    sep = "-" * len(header)
    rows = [header, sep]

    for level in range(1, 12):
        h = stats_dict["Helmet"].get(level, 0)
        c = stats_dict["Chestplate"].get(level, 0)
        l = stats_dict["Leggings"].get(level, 0)

        # Добавляем пробелы: "база / корраптед"
        h_s = f"{h:g} / {h * 1.5:g}"
        c_s = f"{c:g} / {c * 1.5:g}"
        l_s = f"{l:g} / {l * 1.5:g}"

        # Используем левое выравнивание (<18), чтобы зафиксировать начало чисел
        rows.append(f"{level:<5} | {h_s:<18} | {c_s:<18} | {l_s:<18}")

    res = "\n".join(rows)
    await update.message.reply_text(f"```{title}\n{res}\n```", parse_mode=ParseMode.MARKDOWN_V2)


def format_sword_table_text(title, stats_dict, mode="normal"):
    """Генерация текста таблицы для оружия"""
    header = f"{'Roll':<5} | {'DMG':<10}"
    sep = "-" * len(header)
    rows = [header, sep]

    for level in range(1, 12):
        val = stats_dict.get(level, 0)
        if mode == "corrupted":
            val = val * 1.5

        # ФОРМАТИРУЕМ ЗНАЧЕНИЕ ОТДЕЛЬНО
        formatted_val = f"{val:g}"
        rows.append(f"{level:<5} | {formatted_val:<10}")

    mode_text = "Обычный" if mode == "normal" else "Corrupted"

    # ОБЪЕДИНЯЕМ СТРОКИ ОТДЕЛЬНО
    table_content = "\n".join(rows)

    return f"```{title}\n{mode_text}\n\n{table_content}\n```"


def format_armor_part_table_text(title, stats_dict, part):
    """Генерация текста таблицы для конкретной части брони"""
    part_names = {"helmet": "Helmet", "chest": "Chestplate", "legs": "Leggings"}
    part_rus_names = {"helmet": "Шлем", "chest": "Нагрудник", "legs": "Штаны"}

    part_name = part_names[part]
    part_stats = stats_dict[part_name]

    header = f"{'Roll':<5} | {'Health':<10} | {'Corr Health':<12}"
    sep = "-" * len(header)
    rows = [header, sep]

    for level in range(1, 12):
        val = part_stats.get(level, 0)
        corr_val = val * 1.5

        # ФОРМАТИРУЕМ ЗНАЧЕНИЯ ОТДЕЛЬНО
        formatted_val = f"{val:g}"
        formatted_corr = f"{corr_val:g}"
        rows.append(f"{level:<5} | {formatted_val:<10} | {formatted_corr:<12}")

    # ОБЪЕДИНЯЕМ СТРОКИ ОТДЕЛЬНО
    table_content = "\n".join(rows)

    return f"```{title} - {part_rus_names[part]}\n\n{table_content}\n```"


# --- КОНСТАНТЫ ДЛЯ UI ТАБЛИЦ ---
CALLBACK_PREFIX_CONQR = "conqr"
CALLBACK_PREFIX_DOOMR = "doomr"
CALLBACK_PREFIX_FZR = "fzr"
CALLBACK_PREFIX_ZR = "zr"

CALLBACK_TABLE_CLOSE = "close"
CALLBACK_WEAPON_NORMAL = "normal"
CALLBACK_WEAPON_CORRUPTED = "corrupted"
CALLBACK_ARMOR_HELMET = "helmet"
CALLBACK_ARMOR_CHEST = "chest"
CALLBACK_ARMOR_LEGS = "legs"


# Функции для генерации текста каждой страницы помощи
def get_main_page_text():
    return """Создатель бота - H2O (YarreYT)
Версия бота - 1.0.1v РЕЛИЗ

*Общие правила:*
(y/n): y - corrupted, n - НЕ corrupted.

*Таблицы роллов:*
`!crhelp` - Показать это меню
`!reforge` - Список множителей Reforge
`!doomr` - Список роллов Дума (Doombringer)
`!conqr` - Список роллов Конки (Conqueror's Blade)
`!fzr` - Список роллов Furious Zeus Set (броня)
`!zr` - Список роллов Zeus Set (броня)

*Команды для владельца групп:*
`!roll_id` {ID Topic} {Название}
`!roll_id_clear` {ID Topic}
`!roll_allow` - для обычных групп без топиков
`!roll_deny` - удалить доступ к чату обычной группы
`!roll_status` - показать настройки бота в группе

"""


def get_instruction_page_text():
    return """Создатель бота - H2O (YarreYT)

*1. Объяснения аргументов для команд:*

`{roll}` - _индекс предмета, означающий множитель базового урона. В игре для практически всех оружий роллов от 1 до 11, за исключением Ascended оружий, у которых может быть только от 6 до 11. Чтобы узнать ролл вашего предмета, основные для этого команды в разделе_ *"!..."*
`{dmg/hp}` - _значение урона/здоровья на предмете, который у вас отображается в игре_
`{upg}` - _значение уровня улучшений на предмете, до которого вы дошли в игре. В игре для редкости Legendary доступные уровни улучшения 0-34, а для редкости Mythical и Ascended - 0-45_
`{y/n}` - _значение состояние вашего предмета._
(y - ваш предмет Corrupted; n - ваш предмет НЕ Corrupted)
`{reforge}` - _значение зачарования вашего предмета, который вы смогли получить у кузнеца. Требуется ознакомиться со списком зачарований командой_ *"!reforge"*
`"-"` и `">"` - _не менее важные символы для ввода. О них не нужно забывать. Визуально выглядит круто и вполне уместно_

*Вкратце о аргументах*
`{roll}` - все редкости: 0-11; у Ascended - 6-11
`{upg}` - легендарная редкость: 0-34; у Mythical и Ascended - 0-45
`{y/n}` - y - corrupted, n - НЕ corrupted
`{reforge}` - список зачарований: `!reforge`

*2. Объяснения предназначений команд, разделов:*

`!...` - _Основные команды бота, с которым вы можете узнать ролл вашего предмета_
`!w...` - _Второстепенные команды бота, с которыми вы, на основе ролла и желаемых характеристик, сможете узнать какие будут значения у предмета с желаемыми характеристиками, и сколько вам нужно золота для достижения этих характеристик_
`!l...` - _Второстепенные команды бота, с которыми вы можете узнать разницу между вашими характеристиками предмета и желаемыми. Чтобы сравнить между ними значения, и узнать сколько золота вам надо потратить с ваших значений ДО желаемых вами_
*У команд !w..., !l..., из-за игровых условностей, значения могут ошибаться на 1-6 единиц, но это не критично*
"""


def get_current_page_text():
    return """Создатель бота - H2O (YarreYT)

*Общие правила:*
(y/n): y - corrupted, n - НЕ corrupted.

*Анализ текущего предмета (!...)*

*Обычное оружие:*
`!conq` {dmg} {upg} {y/n} {reforge}
`!doom` {dmg} {upg} {y/n} {reforge}
`!asc` {dmg} {upg} {y/n} {reforge}

*Броня:* 
`!fz` / `!z`
На сообщение бота:
{hp} {upg} {y/n}
"""


def get_w_page_text():
    return """Создатель бота - H2O (YarreYT)

*Общие правила:*
(y/n): y - corrupted, n - НЕ corrupted.

*Прогноз желаемых результатов (!w...)*

*Обычное оружие:*
`!wconq` {ролл} > {upg} {y/n} {reforge}
`!wdoom` {ролл} > {upg} {y/n} {reforge}
`!wasc` {ролл} > {upg} {y/n} {reforge}

*Броня:* 
`!wfz` / `!wz`
На сообщение бота:
{roll} > {upg} {y/n}
"""


def get_l_page_text():
    return """Создатель бота - H2O (YarreYT)

*Общие правила:*
(y/n): y - corrupted, n - НЕ corrupted.

*Прогноз и сравнение актуальных и желаемых характеристик предмета (!l...)*

*Обычное оружие:*
`!lconq` {ролл} - {upg} {y/n} {reforge} > {upg} {y/n} {reforge}
`!ldoom` {ролл} - {upg} {y/n} {reforge} > {upg} {y/n} {reforge}
`!lasc` {ролл} - {upg} {y/n} {reforge} > {upg} {y/n} {reforge}

*Броня:* 
`!lfz` / `!lz`
На сообщение бота
{roll} - {upg1} {y/n1} > {upg2} {y/n2}
"""


def get_help_keyboard(current_page="main", user_message_id=None):
    """Генерация клавиатуры для меню помощи"""

    def make_callback(action):
        base = f"help:{action}"
        return f"{base}:{user_message_id}" if user_message_id else base

    main_text = "✓ Main" if current_page == "main" else "Main"
    instruction_text = "✓ Гайд" if current_page == "instruction" else "Гайд"
    current_text = "✓ !..." if current_page == "current" else "!..."
    w_text = "✓ !w..." if current_page == "w" else "!w..."
    l_text = "✓ !l..." if current_page == "l" else "!l..."

    keyboard = [
        [
            InlineKeyboardButton(main_text, callback_data=make_callback("main")),
            InlineKeyboardButton(instruction_text, callback_data=make_callback("instruction")),
            InlineKeyboardButton(current_text, callback_data=make_callback("current")),
            InlineKeyboardButton(w_text, callback_data=make_callback("w")),
            InlineKeyboardButton(l_text, callback_data=make_callback("l")),
        ],
        [InlineKeyboardButton("Свернуть", callback_data=make_callback("close"))]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_weapon_table_keyboard(prefix, current_page="normal", user_message_id=None):
    """Клавиатура для таблиц оружия с ID сообщения"""
    normal_text = "✓ Обычный DMG" if current_page == "normal" else "Обычный DMG"
    corrupted_text = "✓ Corrupted DMG" if current_page == "corrupted" else "Corrupted DMG"

    # Формируем callback_data с user_message_id
    normal_callback = f"{prefix}:{CALLBACK_WEAPON_NORMAL}"
    corrupted_callback = f"{prefix}:{CALLBACK_WEAPON_CORRUPTED}"
    close_callback = f"{prefix}:{CALLBACK_TABLE_CLOSE}"

    if user_message_id:
        normal_callback += f":{user_message_id}"
        corrupted_callback += f":{user_message_id}"
        close_callback += f":{user_message_id}"

    keyboard = [
        [
            InlineKeyboardButton(normal_text, callback_data=normal_callback),
            InlineKeyboardButton(corrupted_text, callback_data=corrupted_callback),
        ],
        [InlineKeyboardButton("Свернуть", callback_data=close_callback)]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_armor_table_keyboard(prefix, current_page="helmet", user_message_id=None):
    """Клавиатура для таблиц брони с ID сообщения"""
    helmet_text = "✓ Шлем" if current_page == "helmet" else "Шлем"
    chest_text = "✓ Нагрудник" if current_page == "chest" else "Нагрудник"
    legs_text = "✓ Штаны" if current_page == "legs" else "Штаны"

    # Формируем callback_data с user_message_id
    helmet_callback = f"{prefix}:{CALLBACK_ARMOR_HELMET}"
    chest_callback = f"{prefix}:{CALLBACK_ARMOR_CHEST}"
    legs_callback = f"{prefix}:{CALLBACK_ARMOR_LEGS}"
    close_callback = f"{prefix}:{CALLBACK_TABLE_CLOSE}"

    if user_message_id:
        helmet_callback += f":{user_message_id}"
        chest_callback += f":{user_message_id}"
        legs_callback += f":{user_message_id}"
        close_callback += f":{user_message_id}"

    keyboard = [
        [
            InlineKeyboardButton(helmet_text, callback_data=helmet_callback),
            InlineKeyboardButton(chest_text, callback_data=chest_callback),
            InlineKeyboardButton(legs_text, callback_data=legs_callback),
        ],
        [InlineKeyboardButton("Свернуть", callback_data=close_callback)]
    ]
    return InlineKeyboardMarkup(keyboard)


# Обработчик нажатий на кнопки меню помощи
async def unified_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    # 🛑 ПРОВЕРКА ВЛАДЕЛЬЦА (для help и таблиц)
    if not check_message_ownership(query):
        await query.answer("Это не ваше сообщение!", show_alert=True)
        return

    await query.answer()

    # Пробуем обработать закрытие reforge
    if await handle_reforge_close_callback(update, context):
        return

    if not is_allowed_thread(update):
        return

    # Парсинг callback_data: prefix:action[:user_message_id]
    data_parts = query.data.split(":")
    if len(data_parts) < 2:
        return

    prefix = data_parts[0]
    action = data_parts[1]

    # Безопасное получение user_message_id (может отсутствовать или быть не числом)
    user_message_id = None
    if len(data_parts) > 2:
        try:
            user_message_id = int(data_parts[2])
        except (ValueError, IndexError):
            # Если это не число, значит это callback от новых кнопок — игнорируем
            return

    # Обработка закрытия
    if action == CALLBACK_TABLE_CLOSE or action == "close":
        await query.message.delete()
        if user_message_id:
            try:
                await context.bot.delete_message(
                    chat_id=query.message.chat_id,
                    message_id=user_message_id
                )
            except Exception:
                pass
        return

    # Help меню
    if prefix == "help":
        page_data = {
            "main": get_main_page_text(),
            "instruction": get_instruction_page_text(),  # ДОБАВЬТЕ ЭТУ СТРОКУ!
            "current": get_current_page_text(),
            "w": get_w_page_text(),
            "l": get_l_page_text(),
        }
        if action in page_data:
            try:
                await query.message.edit_text(
                    text=page_data[action],
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_help_keyboard(action, user_message_id)
                )
            except Exception as e:
                print(f"Ошибка при редактировании help: {e}")
        return

    # Табличные команды
    if prefix in (CALLBACK_PREFIX_CONQR, CALLBACK_PREFIX_DOOMR, CALLBACK_PREFIX_FZR, CALLBACK_PREFIX_ZR):
        # ... (весь остальной код обработки таблиц остается без изменений)
        if prefix in (CALLBACK_PREFIX_CONQR, CALLBACK_PREFIX_DOOMR):
            title = "CONQUEROR_ROLLS" if prefix == CALLBACK_PREFIX_CONQR else "DOOM_ROLLS"
            stats_dict = CONQUERORS_BLADE_STATS if prefix == CALLBACK_PREFIX_CONQR else DOOMBRINGER_STATS
            format_func = format_sword_table_text
            keyboard_func = get_weapon_table_keyboard
        else:
            title = "FURIOUS_ZEUS_ARMOR" if prefix == CALLBACK_PREFIX_FZR else "ZEUS_ARMOR"
            stats_dict = FZH_STATS if prefix == CALLBACK_PREFIX_FZR else LZS_STATS
            format_func = format_armor_part_table_text
            keyboard_func = get_armor_table_keyboard

        try:
            text = format_func(title, stats_dict, action)
            keyboard = keyboard_func(prefix, action, user_message_id)
            await query.message.edit_text(
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=keyboard
            )
        except Exception as e:
            print(f"Ошибка при редактировании таблицы: {e}")
        return


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_thread(update):
        return

    await update.message.reply_text(
        text=get_main_page_text(),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_help_keyboard("main", update.message.message_id),
        reply_to_message_id=update.message.message_id
    )


from game_data import reforges


async def reforge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает красивую таблицу всех рефорджей с кнопкой "Свернуть"
    При нажатии удаляет и сообщение бота, и сообщение пользователя
    """
    # Формируем таблицу
    header = f"{'Reforge':<12} | {'Damage':>9} | {'Critical':>9} | {'Knockback':>9}"
    separator = "─" * len(header)

    lines = [header, separator]

    for ref in reforges:
        name = ref['name']
        # Делаем название чуть красивее (если нужно можно добавить эмодзи или цвет)
        name_padded = f"{name:<12}"
        line = f"{name_padded} | {ref['dmg']:>9} | {ref['crit']:>9} | {ref['knk']:>9}"
        lines.append(line)

    table_text = "\n".join(lines)

    message_content = (
        f"```Список_рефорджей\n"
        f"{table_text}\n"
        f"```"
    )
    # Сохраняем id сообщения пользователя
    user_msg_id = update.message.message_id

    # Клавиатура с одной кнопкой
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Свернуть",
                callback_data=f"{CALLBACK_CLOSE_REFORGE}:{user_msg_id}"
            )
        ]
    ])

    try:
        await update.message.reply_text(
            text=message_content,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=keyboard,
            reply_to_message_id=user_msg_id,
            disable_web_page_preview=True
        )
    except Exception as e:
        await update.message.reply_text(
            f"Не удалось отправить таблицу рефорджей: {e}",
            reply_to_message_id=user_msg_id
        )


async def handle_reforge_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик нажатия кнопки "Свернуть" для таблицы рефорджей
    """
    query = update.callback_query

    # 🛑 ПРОВЕРКА ВЛАДЕЛЬЦА
    if not check_message_ownership(query):
        await query.answer("Это не ваше сообщение!", show_alert=True)
        return True

    await query.answer()  # убираем "часики"

    data = query.data
    if not data.startswith(CALLBACK_CLOSE_REFORGE + ":"):
        return False  # не наш колбэк — пропускаем

    try:
        user_message_id = int(data.split(":", 1)[1])

        # 1. Удаляем сообщение бота
        await query.message.delete()

        # 2. Пытаемся удалить сообщение пользователя
        try:
            await context.bot.delete_message(
                chat_id=query.message.chat_id,
                message_id=user_message_id
            )
        except Exception:
            # Если сообщение пользователя уже удалено или нет прав — не страшно
            pass
        return True  # обработали

    except (ValueError, IndexError):
        # Некорректный callback_data — просто игнорируем
        return False
    except Exception as e:
        # Логируем, но пользователю не показываем
        print(f"Ошибка при сворачивании reforge: {e}")
        return False


async def bang_router(update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text.startswith("!"):
        return

    parts = text[1:].split()
    if not parts:
        return

    command = parts[0].lower()
    context.args = parts[1:]
    context.command = command
    chat = update.effective_chat
    user = update.effective_user

    # --- АДМИН КОМАНДЫ ДЛЯ УПРАВЛЕНИЯ ТОПИКАМИ ---
    # Эти команды работают в любом месте (не зависят от топика)

    async def check_admin_rights(update: Update) -> bool:
        """Проверяет права бота и владельца группы"""
        chat = update.effective_chat
        user = update.effective_user

        # В ЛС не проверяем права
        if chat.type == 'private':
            return True

        # Проверяем, что бот является администратором
        try:
            bot_member = await context.bot.get_chat_member(chat_id=chat.id, user_id=context.bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                await update.message.reply_text(
                    "❌ Бот должен быть администратором группы для выполнения этой команды."
                )
                return False
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка проверки прав бота: {e}")
            return False

        # Проверяем, что пользователь является владельцем группы
        try:
            user_member = await context.bot.get_chat_member(chat_id=chat.id, user_id=user.id)
            if user_member.status != 'creator':
                await update.message.reply_text(
                    "❌ Эта команда доступна только владельцу группы."
                )
                return False
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка проверки прав пользователя: {e}")
            return False
        return True

    # Команда: !roll_id {topic_id} {name}
    if command == "roll_id":
        if not await check_admin_rights(update):
            return

        if len(context.args) < 2:
            await update.message.reply_text(
                "❌ Формат: `!roll_id` {ID топика} {название}\n"
                "Пример: `!roll_id 12345 BEBRA",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if chat.type == 'private':
            await update.message.reply_text("❌ Эту команду можно использовать только в группах.")
            return

        try:
            topic_id = str(context.args[0])
            topic_name = " ".join(context.args[1:])
            group_id = str(chat.id)

            add_topic_to_group(group_id, topic_id, topic_name)

            await update.message.reply_text(
                f"✅ Добавлен топик для этой группы:\n"
                f"ID: `{topic_id}`\n"
                f"Название: `{topic_name}`\n"
                f"Группа: `{group_id}`",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        return

    # Команда: !roll_id_clear [{topic_id}]
    if command == "roll_id_clear":
        if not await check_admin_rights(update):
            return

        if chat.type == 'private':
            await update.message.reply_text("❌ Эту команду можно использовать только в группах.")
            return

        group_id = str(chat.id)

        if len(context.args) == 0:
            # Очистить все топики для этой группы
            clear_all_topics(group_id)
            await update.message.reply_text("✅ Все топики для этой группы очищены.")
        else:
            # Очистить конкретный топик
            try:
                topic_id = str(context.args[0])
                if remove_topic_from_group(group_id, topic_id):
                    await update.message.reply_text(f"✅ Топик `{topic_id}` удалён.", parse_mode=ParseMode.MARKDOWN)
                else:
                    await update.message.reply_text(f"❌ Топик `{topic_id}` не найден.", parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")
        return

    # Команда: !roll_allow
    if command == "roll_allow":
        if not await check_admin_rights(update):
            return

        if chat.type == 'private':
            await update.message.reply_text("❌ Эту команду можно использовать только в группах.")
            return

        group_id = str(chat.id)
        set_allow_non_topic(group_id, True)

        await update.message.reply_text(
            "✅ Разрешены команды в общем чате (без топика) для этой группы."
        )
        return

    # команда: !roll_deny
    if command == "roll_deny":
        if not await check_admin_rights(update):
            return

        if chat.type == 'private':
            await update.message.reply_text("❌ Эту команду можно использовать только в группах.")
            return

        group_id = str(chat.id)
        set_allow_non_topic(group_id, False)

        await update.message.reply_text(
            "❌ Запрещены команды в общем чате (без топика) для этой группы.\n"
            "Теперь команды доступны только в разрешённых топиках."
        )
        return

    if command == "roll_status":
        if not await check_admin_rights(update):
            return

        if chat.type == 'private':
            await update.message.reply_text("❌ Используйте в группе")
            return

        cfg = get_group_topics(str(chat.id))
        if not cfg:
            cfg = {"topics": {}, "allow_non_topic": False}

        status = f"⚙️ Настройки группы `{chat.id}`:\n\n"
        status += f"Разрешены в общем чате: `{'Да' if cfg.get('allow_non_topic') else 'Нет'}`\n\n"

        if cfg["topics"]:
            status += "📋 Разрешённые топики:\n"
            for tid, name in cfg["topics"].items():
                status += f"- `{tid}`: {name}\n"
        else:
            status += "📋 Топики не настроены"

        await update.message.reply_text(status, parse_mode=ParseMode.MARKDOWN)
        return

    # --- ПРОВЕРКА РАЗРЕШЕННОГО ТОПИКА ---
    # Для всех остальных команд проверяем топик
    if not is_allowed_thread(update):
        chat = update.effective_chat

        # В ЛС команды всегда разрешены, так что это не должно произойти
        if chat.type == 'private':
            return

        group_id = str(chat.id)
        cfg = get_group_topics(group_id)

        if cfg and cfg["topics"]:
            # Выбираем случайное грубое сообщение
            chosen = random.choices(WRONG_TOPIC_TEXTS, weights=WRONG_TOPIC_WEIGHTS, k=1)[0]

            # Формируем список топиков (только для этой группы)
            topics_list = []
            for topic_id, topic_name in cfg["topics"].items():
                topics_list.append(f"🔹 {topic_name} (ID: `{topic_id}`)")

            # Подставляем первый топик вместо {name} для совместимости
            if "{name}" in chosen:
                first_name = next(iter(cfg["topics"].values()))
                base_msg = chosen.format(name=first_name)
            else:
                base_msg = chosen

            # Добавляем список топиков
            full_msg = f"{base_msg}\n\nДоступные топики:\n{chr(10).join(topics_list)}"

            # Проверяем нужна ли картинка (по ключу до ":")
            if ':' in chosen:
                key = chosen.split(':', 1)[0]
                if key in WRONG_TOPIC_PICS:
                    try:
                        await update.effective_message.reply_photo(
                            photo=WRONG_TOPIC_PICS[key],
                            caption=full_msg,
                            parse_mode=ParseMode.MARKDOWN
                        )
                        return
                    except Exception:
                        pass

            await update.message.reply_text(full_msg, parse_mode=ParseMode.MARKDOWN)
        else:
            # Топиков нет - показываем инструкцию
            await update.message.reply_text(
                "❌ В этой группе не настроены разрешённые топики.\n"
                "Владелец группы может написать одну из двух комманд:\n`!roll_id` {ID} {название} для настройки.\n"
                "`!roll_allow` - для групп без топиков, команда для общего чата",
                parse_mode=ParseMode.MARKDOWN
            )
        return

    # --- ОСНОВНЫЕ КОМАНДЫ (все остальные) ---
    # Оружие
    if command == "conq":
        await analyze_weapon(update, context, "cb")
    elif command == "doom":
        await analyze_weapon(update, context, "db")

    # Прогноз оружия
    elif command == "wconq":
        await w_analyze_weapon(update, context, "cb")
    elif command == "wdoom":
        await w_analyze_weapon(update, context, "db")

    # Сравнение оружия
    elif command == "lconq":
        await l_analyze_weapon(update, context, "cb")
    elif command == "ldoom":
        await l_analyze_weapon(update, context, "db")

    # ASC оружие
    elif command == "asc":
        await analyze_asc_weapon(update, context)
    elif command == "wasc":
        await w_analyze_asc_weapon(update, context)
    elif command == "lasc":
        await l_analyze_asc_weapon(update, context)

    # Броня
    elif command == "fz":
        await handle_armor_command(update, context, "fz")
    elif command == "z":
        await handle_armor_command(update, context, "z")
    elif command == "wfz":
        await handle_armor_command(update, context, "wfz")
    elif command == "wz":
        await handle_armor_command(update, context, "wz")
    elif command == "lfz":
        await handle_armor_command(update, context, "lfz")
    elif command == "lz":
        await handle_armor_command(update, context, "lz")

    # Служебные команды
    elif command == "crhelp":
        await cmd_help(update, context)
    elif command == "reforge":
        await reforge_command(update, context)
    elif command == "conqr":
        await update.message.reply_text(
            text=format_sword_table_text("CONQUEROR_ROLLS", CONQUERORS_BLADE_STATS, "normal"),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=get_weapon_table_keyboard(CALLBACK_PREFIX_CONQR, "normal", update.message.message_id),
            reply_to_message_id=update.message.message_id
        )
    elif command == "doomr":
        await update.message.reply_text(
            text=format_sword_table_text("DOOM_ROLLS", DOOMBRINGER_STATS, "normal"),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=get_weapon_table_keyboard(CALLBACK_PREFIX_DOOMR, "normal", update.message.message_id),
            reply_to_message_id=update.message.message_id
        )
    elif command == "fzr":
        await update.message.reply_text(
            text=format_armor_part_table_text("FURIOUS_ZEUS_ARMOR", FZH_STATS, "helmet"),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=get_armor_table_keyboard(CALLBACK_PREFIX_FZR, "helmet", update.message.message_id),
            reply_to_message_id=update.message.message_id
        )
    elif command == "zr":
        await update.message.reply_text(
            text=format_armor_part_table_text("ZEUS_ARMOR", LZS_STATS, "helmet"),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=get_armor_table_keyboard(CALLBACK_PREFIX_ZR, "helmet", update.message.message_id),
            reply_to_message_id=update.message.message_id
        )
    # Обработка неизвестных команд
    else:
        population = list(UNKNOWN_COMMAND_RESPONSES.keys())
        weights = list(UNKNOWN_COMMAND_RESPONSES.values())
        chosen_phrase = random.choices(population, weights=weights, k=1)[0]

        if chosen_phrase in UNKNOWN_COMMAND_PHOTOS:
            try:
                await update.effective_message.reply_photo(photo=UNKNOWN_COMMAND_PHOTOS[chosen_phrase])
            except Exception:
                await update.effective_message.reply_text(chosen_phrase)
        else:
            await update.effective_message.reply_text(chosen_phrase)


# --- ЗАПУСК ---
def main():
    # Загружаем разрешённые топики при старте
    global ALLOWED_TOPICS
    ALLOWED_TOPICS = load_allowed_topics()
    print(f"Бот запущен с {len(ALLOWED_TOPICS)} настроенными группами")
    app = Application.builder().token(TOKEN).build()

    # 1. Обработчик умного "Да" (текстовые сообщения)
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & smart_da_filter,
            yes_handler
        ),
        group=0
    )
    # 2. Callback для всех кнопок оружия (ASC + старые)
    app.add_handler(
        CallbackQueryHandler(weapon_analysis_callback, pattern="^(asc|wasc|lasc|a|w|l|close):"),
        group=0
    )
    # 3. Callback для этапов ввода брони (Пропустить/Отмена)
    app.add_handler(
        CallbackQueryHandler(
            armor_stage_callback,
            pattern="^(armor_skip|armor_cancel):"
        ),
        group=0
    )
    # 4. Callback для результатов брони (Total/Process/Tablet)
    app.add_handler(
        CallbackQueryHandler(
            armor_results_callback,
            pattern="^armor:"  # ← ВОТ ЭТА СТРОКА ИЗМЕНЕНА
        ),
        group=0
    )
    # 5. UI callback'ы (help, таблицы)
    app.add_handler(
        CallbackQueryHandler(unified_callback_handler),
        group=0
    )
    # === ГРУППА 1: ОСНОВНЫЕ ТЕКСТОВЫЕ КОМАНДЫ ===
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, bang_router),
        group=1
    )
    # === ГРУППА 2: ВВОД ДАННЫХ ДЛЯ БРОНИ ===
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_armor_input
        ),
        group=2
    )
    # === ЗАПУСК БОТА ===
    print("Бот запущен... С новой системой брони!")
    app.run_polling()


if __name__ == "__main__":
    main()