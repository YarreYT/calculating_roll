import math
import re
import unicodedata
import random
import asyncio

from game_data import reforges
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
    WOODEN_SWORD_BASE,
    DUAL_DAGGERS_V2_STATS,
    TIMELOST_CONQUERORS_BLADE_STATS,
    TIMELOST_CONQUERORS_BLADE_LE_STATS,
    HKR_STATS,
    KR_STATS,
    CUPIDS_FURY_STATS,
    UPGRADE_COSTS
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
CALLBACK_PREFIX_TL = "tl"
CALLBACK_PREFIX_WTL = "wtl"
CALLBACK_PREFIX_LTL = "ltl"

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
    "Да вроде же не глухие и не слепые. Ну, не первый раз же говорю вам, ебланам, что с командами идите в разрешённый чат",
    "DURA"
]
WRONG_TOPIC_WEIGHTS = [10, 15, 10, 10, 20, 10, 5, 1]

WRONG_TOPIC_PICS = {
    "DURA": "https://www.meme-arsenal.com/memes/b3a99bda20d951c2d825115d62330e97.jpg"
}
# --- НОВЫЕ КОНСТАНТЫ ДЛЯ НЕИЗВЕСТНЫХ КОМАНД ---
UNKNOWN_COMMAND_RESPONSES = {
    "Такой команды нет, еблан. Напиши !crhelp": 20,
    "Чёрный... Ой, то есть такой команды нет. !crhelp": 15,
    "Да ты тупой? Такой команды нет. Пиши !crhelp": 15,
    "Не знаю такой команды. Возможно, ты сам её придумал, долбаёб. !crhelp": 10,
    "Я хуею с этой дуры": 1,
}
UNKNOWN_COMMAND_PHOTOS = {
    "Я хуею с этой дуры": "https://www.meme-arsenal.com/memes/450c91d6864f8bbb1a3296a5537d19f7.jpg",
}


def is_allowed_thread(update) -> bool:
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


def calculate_gold(upg_level: int) -> int:
    """
    Новая система: фиксированные стоимости из UPGRADE_COSTS.
    Считает общее количество золота от уровня 1 до upg_level.
    """
    if upg_level <= 0:
        return 0

    total = 0
    for level in range(1, upg_level + 1):
        total += UPGRADE_COSTS.get(level, 0)

    return total


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
    return raw


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
    return [arg for arg in args if arg != '>']


ASC_WEAPON_KEYS = ['ws', 'mb', 'lk', 'me', 'at', 'ad', 'av']
ASC_WEAPON_SHORT_NAMES = {
    'ws': 'W.S.',
    'mb': 'M.B.',
    'lk': 'L.K.',
    'me': 'M.E.',
    'at': 'A.T.',
    'ad': 'A.D.',
    'av': 'A.V.'
}

DUAL_DAGGERS_THRESHOLD_PERCENT = 4.7619


def find_base_damage_for_asc(dmg: float, level: int, is_corrupted: bool, reforge_mult: float) -> tuple:
    """
    Определяет базовый урон для ASC оружия.
    Returns: (base_dmg, roll, weapon_type) где weapon_type: 'ws', 'ad' или 'regular'

    Логика: 3 группы значений (Wooden Sword, Dual Daggers, 5 одинаковых мечей)
    """
    inferred_base = infer_base_for_weapon(dmg, level, is_corrupted, reforge_mult)

    # 1. Wooden Sword V2 - фиксированный ролл 11
    ws_base = WOODEN_SWORD_BASE
    diff_ws = abs(ws_base - inferred_base)

    # 2. Dual Daggers V2 - ищем ближайший ролл 6-11
    best_roll_ad = 6
    best_diff_ad = float('inf')

    for roll in range(6, 12):
        diff = abs(DUAL_DAGGERS_V2_STATS[roll] - inferred_base)
        if diff < best_diff_ad:
            best_diff_ad = diff
            best_roll_ad = roll

    ad_base = DUAL_DAGGERS_V2_STATS[best_roll_ad]

    # 3. Остальные 5 мечей (M.B., L.K., M.E., A.T., A.V.) - одинаковые базы = Conqueror's Blade
    best_roll_regular = 6
    best_diff_regular = float('inf')

    for roll in range(6, 12):
        diff = abs(CONQUERORS_BLADE_STATS[roll] - inferred_base)
        if diff < best_diff_regular:
            best_diff_regular = diff
            best_roll_regular = roll

    regular_base = CONQUERORS_BLADE_STATS[best_roll_regular]

    # Сравниваем 3 кандидатов
    diffs = [
        (diff_ws, ws_base, 11, "ws"),
        (best_diff_ad, ad_base, best_roll_ad, "ad"),
        (best_diff_regular, regular_base, best_roll_regular, "regular")
    ]

    # Сортируем по расстоянию и берём минимальное
    diffs.sort(key=lambda x: x[0])
    _, base_dmg, roll, weapon_type = diffs[0]

    return base_dmg, roll, weapon_type


def find_timelost_type(inferred_base: float) -> tuple:
    """
    Определяет тип Timelost оружия по принципу ближайшего соседа.
    Returns: (item_key, roll, base_dmg, is_le)
    """
    # Ищем ближайший ролл в обычном Timelost
    best_roll_tl = 1
    best_diff_tl = float('inf')

    for roll in range(1, 12):
        diff = abs(TIMELOST_CONQUERORS_BLADE_STATS[roll] - inferred_base)
        if diff < best_diff_tl:
            best_diff_tl = diff
            best_roll_tl = roll

    # Ищем ближайший ролл в L.E. версии
    best_roll_le = 1
    best_diff_le = float('inf')

    for roll in range(1, 12):
        diff = abs(TIMELOST_CONQUERORS_BLADE_LE_STATS[roll] - inferred_base)
        if diff < best_diff_le:
            best_diff_le = diff
            best_roll_le = roll

    # Получаем базовые значения победителей
    tl_base = TIMELOST_CONQUERORS_BLADE_STATS[best_roll_tl]
    le_base = TIMELOST_CONQUERORS_BLADE_LE_STATS[best_roll_le]

    # Сравниваем кто ближе к inferred_base
    if best_diff_le <= best_diff_tl:
        # LE ближе (или равно)
        return "tl_le", best_roll_le, le_base, True
    else:
        # Обычный TL ближе
        return "tl", best_roll_tl, tl_base, False

def find_cupid_type(inferred_base: float) -> tuple:
    """
    Определяет тип Cupid оружия (Fury vs Wrath) по принципу ближайшего соседа.
    Returns: (item_key, roll, base_dmg, is_wrath)
    """
    # Ищем ближайший ролл в Cupid's Fury (Mythic)
    best_roll_fury = 1
    best_diff_fury = float('inf')

    for roll in range(1, 12):
        diff = abs(CUPIDS_FURY_STATS[roll] - inferred_base)
        if diff < best_diff_fury:
            best_diff_fury = diff
            best_roll_fury = roll

    # Ищем ближайший ролл в Cupid's Wrath (Secret = Doombringer)
    best_roll_wrath = 1
    best_diff_wrath = float('inf')

    for roll in range(1, 12):
        diff = abs(DOOMBRINGER_STATS[roll] - inferred_base)
        if diff < best_diff_wrath:
            best_diff_wrath = diff
            best_roll_wrath = roll

    # Получаем базовые значения
    fury_base = CUPIDS_FURY_STATS[best_roll_fury]
    wrath_base = DOOMBRINGER_STATS[best_roll_wrath]

    # Сравниваем кто ближе
    if best_diff_wrath <= best_diff_fury:
        # Wrath ближе (или равно)
        return "cup_sw", best_roll_wrath, wrath_base, True
    else:
        # Fury ближе
        return "cup", best_roll_fury, fury_base, False

def determine_weapon_type(item_key: str, damage: float, level: int, corrupted: bool, reforge_mult: float) -> dict:
    """
    Определяет реальный тип оружия и параметры по принципу ближайшего соседа.
    """
    result = {
        "item_key": item_key,
        "display_key": item_key,
        "roll": None,
        "base_dmg": None,
        "is_le": False,
        "is_ws": False,
        "is_ad": False,
        "is_wrath": False,
        "active_weapon": None,
        "weapon_category": "normal"
    }

    item_info = ITEMS_MAPPING.get(item_key)
    if not item_info:
        return result

    category = item_info.get("category", "normal")
    result["weapon_category"] = category

    if category == "tl":
        # Timelost - ближайший сосред между TL и LE
        inferred_base = infer_base_for_weapon(damage, level, corrupted, reforge_mult)
        detected_key, roll, base_dmg, is_le = find_timelost_type(inferred_base)
        result["item_key"] = detected_key
        result["display_key"] = detected_key
        result["roll"] = roll
        result["base_dmg"] = base_dmg
        result["is_le"] = is_le

    elif category == "asc":
        # ASC - ближайший сосред между 3 группами (WS, AD, 5 мечей)
        base_dmg, roll, weapon_type = find_base_damage_for_asc(damage, level, corrupted, reforge_mult)
        result["roll"] = roll
        result["base_dmg"] = base_dmg

        if weapon_type == "ws":
            result["is_ws"] = True
            result["active_weapon"] = "ws"
            result["item_key"] = "asc_ws"
            result["display_key"] = "asc_ws"
        elif weapon_type == "ad":
            result["is_ad"] = True
            result["active_weapon"] = "ad"
            result["item_key"] = "asc_ad"
            result["display_key"] = "asc_ad"
        else:
            # Один из 5 мечей - выбираем случайно для UI
            chosen = random.choice(["mb", "lk", "me", "at", "av"])
            result["active_weapon"] = chosen
            result["item_key"] = f"asc_{chosen}"
            result["display_key"] = result["item_key"]

    elif category == "cup":
        # Cupid - ближайший сосред между Fury и Wrath
        inferred_base = infer_base_for_weapon(damage, level, corrupted, reforge_mult)
        detected_key, roll, base_dmg, is_wrath = find_cupid_type(inferred_base)
        result["item_key"] = detected_key
        result["display_key"] = detected_key
        result["roll"] = roll
        result["base_dmg"] = base_dmg
        result["is_wrath"] = is_wrath

    else:
        # Обычное оружие (Conq, Doom и т.д.)
        base_stats = item_info['stats']
        inferred_base = infer_base_for_weapon(damage, level, corrupted, reforge_mult)
        roll = determine_roll(base_stats, inferred_base)
        result["roll"] = roll
        result["base_dmg"] = base_stats[roll]

    return result

async def _send_error(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      error_message: str, _) -> bool:
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

def generate_total_page(item_info, dmg, upg, corr, reforge_name, reforge_mult, roll, base_dmg,
                        weapon_category="normal"):
    """Универсальная Total страница для всех типов оружия"""
    max_lvl = item_info['max_level']

    spent = calculate_gold(upg)
    total_needed = calculate_gold(max_lvl)
    remaining = max(0, total_needed - spent)

    # Форматирование roll/base в зависимости от типа
    if weapon_category == "asc" and item_info.get("weapon_key") == "ws":
        roll_text = "11/11"
        base_text = f"{WOODEN_SWORD_BASE:,.2f}"
    else:
        roll_text = f"{roll}/11"
        base_text = f"{base_dmg:,.2f}" if isinstance(base_dmg, float) and base_dmg != int(
            base_dmg) else f"{int(base_dmg):,}"

    return (
        f"📊 <b>Анализ {item_info['name']}</b>\n\n"
        f"<b>ROLL:</b> <i>{roll_text}</i> | <b>BASE:</b> <i>{base_text}</i>\n\n"
        f"<b>DMG:</b> <i>{int(dmg):,}</i>\n\n"
        f"<b>Reforge:</b> <i>{reforge_name}</i> (x{reforge_mult:.2f})\n"
        f"<b>Corrupted:</b> <i>{'Да' if corr else 'Нет'}</i>\n"
        f"<b>Upgrade:</b> <i>{upg}/{max_lvl}</i>\n\n"
        f"<b>💰 ЗОЛОТО 💰</b>\n"
        f"<i>       Потрачено:</i> <b>{spent:,}</b>\n"
        f"<i>       Осталось:</i> <b>{remaining:,}</b> до {max_lvl} уровня"
    )

def generate_process_page(item_info, dmg, upg, corr, reforge_name, reforge_mult, roll, base_dmg,
                          weapon_category="normal"):
    """Универсальная Process страница"""
    base_stats = item_info['stats']
    is_ws = weapon_category == "asc" and item_info.get("weapon_key") == "ws"

    steps = []
    steps.append(f"🧮 <b>Детальные вычисления {item_info['name']}</b>\n")

    current = float(dmg)

    # Шаг 1: Reforge
    if reforge_mult != 1.0:
        steps.append(f"<b>1. Убираем Reforge ({reforge_name} ×{reforge_mult:.2f}):</b>")
        steps.append(f"<i>  {current:,.2f} ÷ {reforge_mult:.2f} = {current / reforge_mult:,.2f}</i>")
        current = current / reforge_mult
        steps.append("")
    else:
        steps.append("<b>1. Reforge: Нет (×1.00)</b>\n")

    # Шаг 2: Corrupted
    if corr:
        steps.append("<b>2. Убираем Corrupted (×1.5):</b>")
        steps.append(f"<i>  {current:,.2f} ÷ 1.50 = {current / 1.5:,.2f}</i>")
        current = current / 1.5
        steps.append("")
    else:
        steps.append("<b>2. Corrupted: Нет (×1.00)</b>\n")

    # Шаг 3: Фактор роста
    growth_factor = 1 + GROWTH_RATE * upg
    steps.append("<b>3. Расчёт базового урона:</b>")
    steps.append(f"<i>  Фактор роста = 1 + {upg} × 0.047619 = {growth_factor:.10f}</i>")
    steps.append(f"<i>  {current:,.2f} ÷ {growth_factor:.10f} = {current / growth_factor:,.2f}</i>")
    inferred_base = current / growth_factor
    steps.append("")

    # Шаг 4: Определение ролла
    if is_ws:
        # Wooden Sword - только показываем базу
        steps.append(f"<b>4. Wooden Sword V2:</b>")
        steps.append(f"<i>  Базовый урон: {WOODEN_SWORD_BASE:,.2f}</i>")
        steps.append("")
        steps.append(f"<i>  11 roll - {WOODEN_SWORD_BASE:8,.2f} ≈ {inferred_base:.2f} ←</i>")
        steps.append("")
        steps.append(f"<b>✓ BASE DMG: {WOODEN_SWORD_BASE:,.0f}</b>")
    else:
        steps.append(f"<b>4. Определение ролла:</b>")
        steps.append(f"<i>  Инференс: {inferred_base:.2f}</i>")
        steps.append("")

        # Определяем диапазон роллов для отображения
        if weapon_category == "asc":
            roll_range = range(6, 12)  # ASC: 6-11
        else:
            roll_range = range(1, 12)  # Обычные/TL: 1-11

        for r in roll_range:
            val = base_stats[r]
            symbol = "←" if r == roll else "  "
            comparison = "&gt;" if val < inferred_base else "&lt;"
            steps.append(f"<i>  {r:2} roll - {val:8,.2f} {comparison} {inferred_base:.2f} {symbol}</i>")

        steps.append("")
        display_roll = 11 if is_ws else roll
        steps.append(f"<b>✓ Выбран ролл:</b> <i>{display_roll}/11</i>\n")
        steps.append(f"<b>✓ BASE DMG:</b> <i>{base_dmg:,.2f}</i>")

    return "\n".join(steps)


def generate_tablet_page(item_info, roll, corr, reforge_mult, reforge_name, weapon_category="normal"):
    """Универсальная Tablet страница"""
    from game_data import UPGRADE_COSTS  # Импорт таблицы стоимостей

    max_lvl = item_info['max_level']

    # Определяем базовый урон и ролл для отображения
    is_ws = weapon_category == "asc" and item_info.get("weapon_key") == "ws"
    if is_ws:
        actual_roll = 11
        base_dmg = WOODEN_SWORD_BASE
    else:
        actual_roll = roll
        base_dmg = item_info['stats'][roll]

    header = f"{'UPG':<5} | {'Gold Cost':<11} | {'DMG':<12}"
    separator = "-" * len(header)
    rows = [header, separator]

    for level in range(0, max_lvl + 1):
        # Стоимость текущего уровня (0 для уровня 0, т.к нет апгрейда)
        level_cost = UPGRADE_COSTS.get(level, 0) if level > 0 else 0

        dmg = calculate_weapon_stat_at_level(base_dmg, level, corr, reforge_mult)
        rows.append(f"{level:<5} | {level_cost:<11,} | {int(dmg):<12,}")

    table_content = "\n".join(rows)
    title_line = f"{item_info['name']} | ROLL {actual_roll}/11 | {'CORRUPTED' if corr else 'NORMAL'} | {reforge_name}"

    clean_name = item_info['name'].replace(' ', '_').replace("'", '').upper()
    block_name = f"{clean_name}_TABLET"
    return f"```{block_name}\n{title_line}\n\n{table_content}\n```"


def generate_forecast_total_page(item_info, roll, upg, corr, reforge_name, reforge_mult,
                                 weapon_category="normal", display_upg=None):
    """Универсальная Forecast Total страница"""
    max_lvl = item_info['max_level']

    # 🔥 Если передан display_upg (уровень который ввёл юзер), используем его для отображения
    # А upg используем для реальных расчётов (уже ограниченный)
    show_upg = display_upg if display_upg is not None else upg

    # Определяем базовый урон
    is_ws = weapon_category == "asc" and item_info.get("weapon_key") == "ws"
    if is_ws:
        base_dmg = WOODEN_SWORD_BASE
        display_roll = 11
    else:
        base_dmg = item_info['stats'][roll]
        display_roll = roll

    # 🔥 Расчёты по ОГРАНИЧЕННОМУ уровню (upg)
    target_dmg = calculate_weapon_stat_at_level(base_dmg, upg, corr, reforge_mult)
    gold_needed = calculate_gold(upg)

    base_text = f"{base_dmg:,.2f}" if isinstance(base_dmg, float) and base_dmg != int(
        base_dmg) else f"{int(base_dmg):,}"

    # 🔥 Показываем реальный расчётный уровень, и если он отличается от введённого - показываем введённый
    if show_upg != upg:
        level_display = f"{upg}/{max_lvl} <i>(введено {show_upg}, но игнорируется из-за лимита улучшений данного типа оружия)</i>"
    else:
        level_display = f"{upg}/{max_lvl}"

    return (
        f"📊 <b>Прогноз {item_info['name']}</b>\n\n"
        f"<b>ROLL:</b> <i>{display_roll}/11</i> | <b>BASE:</b> <i>{base_text}</i>\n\n"
        f"<b>DMG:</b> <i>{(target_dmg):,.0f}</i> ⚔️\n\n"
        f"<b>Reforge:</b> <i>{reforge_name}</i> (x{reforge_mult:.2f})\n"
        f"<b>Corrupted:</b> <i>{'Да' if corr else 'Нет'}</i>\n"
        f"<b>Upgrade:</b> <i>{level_display}</i>\n\n"
        f"<b>💰 ЗОЛОТО 💰</b>\n"
        f"<i>       Нужно:</i> <b>{gold_needed:,}</b> до {upg} уровня💰"
    )

def generate_forecast_process_page(item_info, roll, upg, corr, reforge_name, reforge_mult, weapon_category="normal"):
    """Универсальная Forecast Process страница"""
    is_ws = weapon_category == "asc" and item_info.get("weapon_key") == "ws"

    if is_ws:
        base_dmg = WOODEN_SWORD_BASE
    else:
        base_dmg = item_info['stats'][roll]

    steps = []
    steps.append(f"🧮 <b>Детальные вычисления {item_info['name']}</b>\n")

    # Шаг 1: База
    steps.append(f"<b>1. Базовый урон{' (ролл ' + str(roll) + ')' if not is_ws else ''}:</b>")
    steps.append(f"<i>  {base_dmg:,.2f}</i>\n")

    # Шаг 2: Рост
    growth_factor = 1 + GROWTH_RATE * upg
    base_value = base_dmg * growth_factor
    steps.append("<b>2. Расчет общего урона:</b>")
    steps.append(f"<i>  Фактор роста = 1 + {upg} × 0.047619 = {growth_factor:.10f}</i>")
    steps.append(f"<i>  {base_dmg:,.2f} × {growth_factor:.10f} = {base_value:,.2f}</i>\n")

    # Шаг 3: Corrupted
    if corr:
        corr_value = base_value * 1.5
        steps.append("<b>3. Умножаем на Corrupted (×1.5):</b>")
        steps.append(f"<i>  {base_value:,.2f} × 1.50 = {corr_value:,.2f}</i>\n")
        final_dmg = corr_value
    else:
        final_dmg = base_value
        steps.append("<b>3. Corrupted: Нет (×1.00)</b>\n")

    # Шаг 4: Reforge
    if reforge_mult != 1.0:
        ref_value = final_dmg * reforge_mult
        steps.append(f"<b>4. Умножаем на Reforge ({reforge_name} ×{reforge_mult:.2f}):</b>")
        steps.append(f"<i>  {final_dmg:,.2f} × {reforge_mult:.2f} = {ref_value:,.2f}</i>\n")
        final_dmg = ref_value
    else:
        steps.append("<b>4. Reforge: Нет (×1.00)</b>\n")

    steps.append(f"<b>✓ Итоговый урон = {(final_dmg):,.2f}</b>")

    return "\n".join(steps)


def generate_compare_total_page(item_info, roll, curr_upg, curr_corr, curr_ref_mult, curr_ref_name,
                                des_upg, des_corr, des_ref_mult, des_ref_name, weapon_category="normal",
                                has_two_rolls=False, roll2=None,
                                display_curr_upg=None, display_des_upg=None):  # <-- новые параметры
    """Универсальная Compare Total страница"""
    is_ws = weapon_category == "asc" and item_info.get("weapon_key") == "ws"

    if is_ws:
        base_dmg = WOODEN_SWORD_BASE
        display_roll = 11
    else:
        base_dmg = item_info['stats'][roll]
        display_roll = roll

    if has_two_rolls and roll2:
        base_dmg2 = item_info['stats'][roll2] if not is_ws else WOODEN_SWORD_BASE
    else:
        base_dmg2 = base_dmg

    # 🔥 Расчёты по ОГРАНИЧЕННЫМ уровням (curr_upg, des_upg)
    curr_dmg = calculate_weapon_stat_at_level(base_dmg, curr_upg, curr_corr, curr_ref_mult)
    des_dmg = calculate_weapon_stat_at_level(base_dmg2, des_upg, des_corr, des_ref_mult)

    curr_spent = calculate_gold(curr_upg)
    des_gold = calculate_gold(des_upg)

    add_gold = 0
    if not has_two_rolls:
        add_gold = max(0, des_gold - curr_spent)

    if has_two_rolls:
        spent_roll1 = curr_spent
        remaining_roll1 = max(0, calculate_gold(item_info['max_level']) - spent_roll1)
        spent_roll2 = des_gold
        remaining_roll2 = max(0, calculate_gold(item_info['max_level']) - spent_roll2)

    upg_diff = des_upg - curr_upg
    dmg_diff = des_dmg - curr_dmg
    ref_mult_diff = des_ref_mult - curr_ref_mult

    corr_diff_text = ""
    if not curr_corr and des_corr:
        corr_diff_text = " (активируется)"
    elif curr_corr and not des_corr:
        corr_diff_text = " ❌ (невозможно)"

    dmg_sign = "+" if dmg_diff >= 0 else ""
    pct_sign = "+" if dmg_diff >= 0 else ""

    # 🔥 Для отображения используем оригинальные значения если переданы
    show_curr_upg = display_curr_upg if display_curr_upg is not None else curr_upg
    show_des_upg = display_des_upg if display_des_upg is not None else des_upg

    max_lvl = item_info['max_level']

    # Форматирование уровней с указанием введённых значений если они отличаются
    if show_curr_upg != curr_upg:
        curr_level_str = f"{curr_upg}/{max_lvl} <i>(введено {show_curr_upg})</i>"
    else:
        curr_level_str = f"{curr_upg}/{max_lvl}"

    if show_des_upg != des_upg:
        des_level_str = f"{des_upg}/{max_lvl} <i>(введено {show_des_upg})</i>"
    else:
        des_level_str = f"{des_upg}/{max_lvl}"

    base_text = f"{base_dmg:,.2f}" if isinstance(base_dmg, float) and base_dmg != int(
        base_dmg) else f"{int(base_dmg):,}"

    if has_two_rolls:
        title = f"📊 <b>Сравнение {item_info['name']}</b>"
        if not is_ws:
            roll_text = f"{roll}/11 → {roll2}/11 | "
        else:
            roll_text = f"11/11 → Что ты там сравнивать собрался? А??\n\n"
        diff_base_dmg = base_dmg2 - base_dmg
        base_text = f"{base_dmg} → {base_dmg2} (+{diff_base_dmg:,.2f})"
    else:
        title = f"📊 <b>Сравнение {item_info['name']}</b>"
        roll_text = f"{display_roll}/11 | "

    result = (
        f"{title}\n\n"
        f"<b>ROLL:</b> <i>{roll_text}</i><b>BASE:</b> <i>{base_text}</i>\n\n"
        f"<b>DMG:</b> <i>{int(curr_dmg):,}</i> ➜ <i>{int(des_dmg):,} ({dmg_sign}{(dmg_diff):,.2f}) ({pct_sign}{dmg_diff / curr_dmg * 100:.1f}%)</i>\n\n"
        f"<b>UPG:</b> <i>{curr_level_str}</i> ➜ <i>{des_level_str} (+{upg_diff})</i>\n"
        f"<b>Reforge:</b> <i>{curr_ref_name}</i> (x{curr_ref_mult:.2f}) ➜ <i>{des_ref_name}</i> (x{des_ref_mult:.2f}) {f'(+{ref_mult_diff:.2f})' if ref_mult_diff != 0 else ''}\n"
        f"<b>Corrupted:</b> <i>{'Да' if curr_corr else 'Нет'}</i> ➜ "
        f"<i>{'Да' if des_corr else 'Нет'}{corr_diff_text}</i>\n\n"
    )

    if not has_two_rolls:
        result += (
            f"<b>💰 ЗОЛОТО 💰</b>\n"
            f"<i>       Потрачено:</i> <b>{curr_spent:,}</b>\n"
            f"<i>       Осталось:</i> <b>{add_gold:,}</b> до {des_upg} уровня"
        )
    else:
        if not is_ws:
            result += (
                f"<b>💰 ЗОЛОТО ДЛЯ {roll} РОЛЛА:</b> 💰\n"
                f"<i>       Потрачено:</i> <b>{spent_roll1:,}</b>\n"
                f"<i>       Осталось:</i> <b>{remaining_roll1:,}</b> до {max_lvl} уровня\n\n"
                f"<b>💰 ЗОЛОТО ДЛЯ {roll2} РОЛЛА:</b> 💰\n"
                f"<i>       Потрачено:</i> <b>{spent_roll2:,}</b>\n"
                f"<i>       Осталось:</i> <b>{remaining_roll2:,}</b> до {max_lvl} уровня\n\n"
            )
        else:
            result += (
                f"<b>💰 ЗОЛОТО:</b> 💰\n"
                f"<i>       Потрачено:</i> <b>{curr_spent:,}</b>\n"
                f"<i>       Осталось:</i> <b>{add_gold:,}</b> до {des_upg} уровня"
            )

    return result

def generate_compare_process_page(item_info, roll, upg, corr, reforge_mult, reforge_name, state,
                                  weapon_category="normal"):
    """Универсальная Compare Process страница"""
    is_ws = weapon_category == "asc" and item_info.get("weapon_key") == "ws"

    if is_ws:
        base_dmg = WOODEN_SWORD_BASE
    else:
        base_dmg = item_info['stats'][roll]

    steps = []
    steps.append(f"🧮 <b>Детальные вычисления {item_info['name']} ({state})</b>\n")

    # Шаг 1: База
    steps.append(f"<b>1. Базовый урон{' (ролл ' + str(roll) + ')' if not is_ws else ''}:</b>")
    steps.append(f"<i>  {base_dmg:,.2f}</i>\n")

    # Шаг 2: Рост
    growth_factor = 1 + GROWTH_RATE * upg
    base_value = base_dmg * growth_factor
    steps.append("<b>2. Применяем фактор роста:</b>")
    steps.append(f"<i>  Фактор = 1 + {upg} × 0.047619 = {growth_factor:.10f}</i>")
    steps.append(f"<i>  {base_dmg:,.2f} × {growth_factor:.10f} = {base_value:,.2f}</i>\n")

    # Шаг 3: Corrupted
    if corr:
        corr_value = base_value * 1.5
        steps.append("<b>3. Умножаем на Corrupted (×1.5):</b>")
        steps.append(f"<i>  {base_value:,.2f} × 1.50 = {corr_value:,.2f}</i>\n")
        final = corr_value
    else:
        final = base_value
        steps.append("<b>3. Corrupted: Нет (×1.00)</b>\n")

    # Шаг 4: Reforge
    if reforge_mult != 1.0:
        ref_value = final * reforge_mult
        steps.append(f"<b>4. Умножаем на Reforge ({reforge_name} ×{reforge_mult:.2f}):</b>")
        steps.append(f"<i>  {final:,.2f} × {reforge_mult:.2f} = {ref_value:,.2f}</i>\n")
        final = ref_value
    else:
        steps.append("<b>4. Reforge: Нет (×1.00)</b>\n")

    steps.append(f"<b>✓ Итоговый урон = {(final):,.2f}</b>")

    return "\n".join(steps)


def generate_weapon_analysis_keyboard(item_key, current_page, dmg, upg, corr, reforge_name,
                                      user_msg_id, weapon_category="normal", roll=None,
                                      is_ws=False, is_ad=False, active_weapon=None,
                                      is_wrath=False):  # 🔧 Новый параметр
    """Универсальная клавиатура для анализа оружия"""
    corr_str = 'y' if corr else 'n'
    ref_str = reforge_name if reforge_name != "None" else "None"

    # Определяем префикс callback'а
    prefix = weapon_category

    if weapon_category == "asc":
        # ASC клавиатура - без изменений
        if is_ws:
            base = f"{prefix}:ws:{{}}:{int(dmg)}:{upg}:{corr_str}:{ref_str}:11:0:{user_msg_id}"
            total_txt = "✓ Total" if current_page == "total" else "Total"
            proc_txt = "✓ Process" if current_page == "process" else "Process"
            tabl_txt = "✓ Tablet" if current_page == "tablet" else "Tablet"

            keyboard = [
                [InlineKeyboardButton(total_txt, callback_data=base.format("total")),
                 InlineKeyboardButton(proc_txt, callback_data=base.format("process")),
                 InlineKeyboardButton(tabl_txt, callback_data=base.format("tablet"))],
                [InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")]
            ]
            return InlineKeyboardMarkup(keyboard)

        elif is_ad:
            ad_roll = roll if roll else 6

            base = f"{prefix}:ad:{{}}:{int(dmg)}:{upg}:{corr_str}:{ref_str}:{ad_roll}:0:{user_msg_id}"
            total_txt = "✓ Total" if current_page == "total" else "Total"
            proc_txt = "✓ Process" if current_page == "process" else "Process"
            tabl_txt = "✓ Tablet" if current_page == "tablet" else "Tablet"

            keyboard = [
                [InlineKeyboardButton(total_txt, callback_data=base.format("total")),
                 InlineKeyboardButton(proc_txt, callback_data=base.format("process")),
                 InlineKeyboardButton(tabl_txt, callback_data=base.format("tablet"))],
                [InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")]
            ]
            return InlineKeyboardMarkup(keyboard)

        else:
            buttons = []
            for w_key in ['mb', 'lk', 'me', 'at', 'av']:
                short = ASC_WEAPON_SHORT_NAMES[w_key]

                base = f"{prefix}:asc_{w_key}:{{}}:{int(dmg)}:{upg}:{corr_str}:{ref_str}:{roll}:0:{user_msg_id}"
                total_btn = InlineKeyboardButton(
                    f"{'✓ ' if current_page == 'total' and active_weapon == w_key else ''}{short} Total",
                    callback_data=base.format("total"))
                proc_btn = InlineKeyboardButton(
                    f"{'✓ ' if current_page == 'process' and active_weapon == w_key else ''}{short} Process",
                    callback_data=base.format("process"))
                buttons.append([total_btn, proc_btn])

            tab_base = f"{prefix}:mb:tablet:{int(dmg)}:{upg}:{corr_str}:{ref_str}:{roll}:0:{user_msg_id}"

            tab_btn = InlineKeyboardButton(
                f"{'✓ ' if current_page == 'tablet' and active_weapon == 'mb' else ''}Tablet",
                callback_data=tab_base
            )
            buttons.append([tab_btn, InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")])
            return InlineKeyboardMarkup(buttons)

    elif weapon_category == "tl":
        # TL клавиатура - без изменений
        is_le = 1 if "tl_le" in item_key else 0
        base = f"{prefix}:{item_key}:{{}}:{int(dmg)}:{upg}:{corr_str}:{ref_str}:{roll}:{is_le}:{user_msg_id}"

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

    elif weapon_category == "cup":
        # 🔧 ИСПРАВЛЕНИЕ: Только одна панель в зависимости от определённого типа
        if is_wrath:
            # Только Wrath
            base = f"{prefix}:cup_sw:{{}}:{int(dmg)}:{upg}:{corr_str}:{ref_str}:{roll}:1:{user_msg_id}"
            total_txt = "✓ Total" if current_page == "total" else "Total"
            proc_txt = "✓ Process" if current_page == "process" else "Process"
            tabl_txt = "✓ Tablet" if current_page == "tablet" else "Tablet"

            keyboard = [
                [InlineKeyboardButton(total_txt, callback_data=base.format("total")),
                 InlineKeyboardButton(proc_txt, callback_data=base.format("process")),
                 InlineKeyboardButton(tabl_txt, callback_data=base.format("tablet"))],
                [InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")]
            ]
        else:
            # Только Fury
            base = f"{prefix}:cup:{{}}:{int(dmg)}:{upg}:{corr_str}:{ref_str}:{roll}:0:{user_msg_id}"
            total_txt = "✓ Total" if current_page == "total" else "Total"
            proc_txt = "✓ Process" if current_page == "process" else "Process"
            tabl_txt = "✓ Tablet" if current_page == "tablet" else "Tablet"

            keyboard = [
                [InlineKeyboardButton(total_txt, callback_data=base.format("total")),
                 InlineKeyboardButton(proc_txt, callback_data=base.format("process")),
                 InlineKeyboardButton(tabl_txt, callback_data=base.format("tablet"))],
                [InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")]
            ]
        return InlineKeyboardMarkup(keyboard)

    else:
        # Обычное оружие
        base = f"{prefix}:{item_key}:{{}}:{int(dmg)}:{upg}:{corr_str}:{ref_str}:{roll}:0:{user_msg_id}"

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


def generate_weapon_forecast_keyboard(item_key, current_page, roll, upg, corr, reforge_name,
                                      user_msg_id, weapon_category="normal", original_roll=None,
                                      active_weapon=None):
    """Универсальная клавиатура для прогноза оружия"""
    corr_str = 'y' if corr else 'n'
    ref_str = reforge_name if reforge_name != "None" else "None"
    prefix = weapon_category

    if weapon_category == "asc":
        buttons = []
        orig_roll = original_roll if original_roll is not None else roll

        for w_key in ASC_WEAPON_KEYS:
            short = ASC_WEAPON_SHORT_NAMES[w_key]
            weapon_roll = 11 if w_key == 'ws' else orig_roll
            dummy_dmg = 0

            base = f"w{prefix}:{w_key}:{{}}:{dummy_dmg}:{weapon_roll}:{upg}:{corr_str}:{ref_str}:{orig_roll}:{user_msg_id}"

            total_btn = InlineKeyboardButton(
                f"{'✓ ' if current_page == 'total' and active_weapon == w_key else ''}{short} Total",
                callback_data=base.format("total"))
            proc_btn = InlineKeyboardButton(
                f"{'✓ ' if current_page == 'process' and active_weapon == w_key else ''}{short} Process",
                callback_data=base.format("process"))
            buttons.append([total_btn, proc_btn])

        buttons.append([InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")])
        return InlineKeyboardMarkup(buttons)

    elif weapon_category == "tl":
        # TL прогноз - две панели (TL и LE) с галочками
        dummy_dmg = 0

        base_tl = f"w{prefix}:tl:{{}}:{dummy_dmg}:{roll}:{upg}:{corr_str}:{ref_str}:{roll}:{user_msg_id}"
        base_le = f"w{prefix}:tl_le:{{}}:{dummy_dmg}:{roll}:{upg}:{corr_str}:{ref_str}:{roll}:{user_msg_id}"

        tl_total = "✓ TL Total" if current_page == "tt" else "TL Total"
        tl_proc = "✓ TL Process" if current_page == "tp" else "TL Process"
        le_total = "✓ L.E. Total" if current_page == "lt" else "L.E. Total"
        le_proc = "✓ L.E. Process" if current_page == "lp" else "L.E. Process"

        keyboard = [
            [
                InlineKeyboardButton(tl_total, callback_data=base_tl.format("tt")),
                InlineKeyboardButton(tl_proc, callback_data=base_tl.format("tp")),
            ],
            [
                InlineKeyboardButton(le_total, callback_data=base_le.format("lt")),
                InlineKeyboardButton(le_proc, callback_data=base_le.format("lp")),
            ],
            [InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")]
        ]
        return InlineKeyboardMarkup(keyboard)

    elif weapon_category == "cup":
        # Cupid прогноз - две панели (Fury и Wrath) с галочками
        dummy_dmg = 0

        base_fury = f"w{prefix}:cup:{{}}:{dummy_dmg}:{roll}:{upg}:{corr_str}:{ref_str}:{roll}:{user_msg_id}"
        base_wrath = f"w{prefix}:cup_sw:{{}}:{dummy_dmg}:{roll}:{upg}:{corr_str}:{ref_str}:{roll}:{user_msg_id}"

        fury_total = "✓ Fury Total" if current_page == "ft" else "Fury Total"
        fury_proc = "✓ Fury Process" if current_page == "fuP" else "Fury Process"
        wrath_total = "✓ Wrath Total" if current_page == "wt" else "Wrath Total"
        wrath_proc = "✓ Wrath Process" if current_page == "wrP" else "Wrath Process"

        keyboard = [
            [
                InlineKeyboardButton(fury_total, callback_data=base_fury.format("ft")),
                InlineKeyboardButton(fury_proc, callback_data=base_fury.format("fuP")),
            ],
            [
                InlineKeyboardButton(wrath_total, callback_data=base_wrath.format("wt")),
                InlineKeyboardButton(wrath_proc, callback_data=base_wrath.format("wrP")),
            ],
            [InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")]
        ]
        return InlineKeyboardMarkup(keyboard)

    else:
        # Обычное оружие
        base = f"w{prefix}:{item_key}:{{}}:{roll}:{upg}:{corr_str}:{ref_str}:{user_msg_id}"

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
                                     des_upg, des_corr, des_ref, user_msg_id,
                                     weapon_category="normal", original_roll=None, active_weapon=None,
                                     has_two_rolls=False, roll2=None):
    """Универсальная клавиатура для сравнения оружия"""
    curr_corr_str = 'y' if curr_corr else 'n'
    des_corr_str = 'y' if des_corr else 'n'
    curr_ref_str = curr_ref if curr_ref != "None" else "None"
    des_ref_str = des_ref if des_ref != "None" else "None"
    prefix = weapon_category

    # Формат callback для двух роллов включает оба ролла
    if has_two_rolls:
        roll_param = f"{roll}_{roll2}"
    else:
        roll_param = str(roll)

    if weapon_category == "asc":
        buttons = []
        orig_roll = original_roll if original_roll is not None else roll

        for w_key in ASC_WEAPON_KEYS:
            short = ASC_WEAPON_SHORT_NAMES[w_key]
            weapon_roll = 11 if w_key == 'ws' else orig_roll
            dummy_dmg = 0

            base = f"l{prefix}:{w_key}:{{}}:{dummy_dmg}:{weapon_roll}:{curr_upg}:{curr_corr_str}:{curr_ref_str}:{des_upg}:{des_corr_str}:{des_ref_str}:{orig_roll}:{user_msg_id}"

            if has_two_rolls:
                base += f":1:{roll2}"  # флаг has_two_rolls=1 и roll2
            else:
                base += ":0:0"  # флаг has_two_rolls=0

            is_active = (active_weapon == w_key)

            # Текст кнопок в зависимости от режима
            if has_two_rolls:
                total_btn = InlineKeyboardButton(
                    f"{'✓ ' if current_page == 'total' and is_active else ''}{short} Total",
                    callback_data=base.format("total"))
                first_btn = InlineKeyboardButton(
                    f"{'✓ ' if current_page == 'fp' and is_active else ''}< 1-st Process",
                    callback_data=base.format("fp"))
                second_btn = InlineKeyboardButton(
                    f"{'✓ ' if current_page == 'sp' and is_active else ''}< 2-nd Process",
                    callback_data=base.format("sp"))
                buttons.append([total_btn, first_btn, second_btn])
            else:
                total_btn = InlineKeyboardButton(
                    f"{'✓ ' if current_page == 'total' and is_active else ''}{short} Total",
                    callback_data=base.format("total"))
                actual_btn = InlineKeyboardButton(
                    f"{'✓ ' if current_page == 'ap' and is_active else ''}< Actual Process",
                    callback_data=base.format("fp"))
                wished_btn = InlineKeyboardButton(
                    f"{'✓ ' if current_page == 'wp' and is_active else ''}< Wished Process",
                    callback_data=base.format("sp"))
                buttons.append([total_btn, actual_btn, wished_btn])

        buttons.append([InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")])
        return InlineKeyboardMarkup(buttons)

    elif weapon_category == "tl":
        # TL сравнение с галочками
        dummy_dmg = 0

        base_tl = f"l{prefix}:tl:{{}}:{dummy_dmg}:{roll_param}:{curr_upg}:{curr_corr_str}:{curr_ref_str}:{des_upg}:{des_corr_str}:{des_ref_str}:{roll}:{user_msg_id}"
        base_le = f"l{prefix}:tl_le:{{}}:{dummy_dmg}:{roll_param}:{curr_upg}:{curr_corr_str}:{curr_ref_str}:{des_upg}:{des_corr_str}:{des_ref_str}:{roll}:{user_msg_id}"

        if has_two_rolls:
            tl_total = "✓ TL Total" if current_page == "tt" else "TL Total"
            tl_first = "✓ < 1-st Process" if current_page == "tf" else "< 1-st Process"
            tl_second = "✓ < 2-nd Process" if current_page == "ts" else "< 2-nd Process"
            le_total = "✓ L.E. Total" if current_page == "lt" else "L.E. Total"
            le_first = "✓ < 1-st Process" if current_page == "lf" else "< 1-st Process"
            le_second = "✓ < 2-nd Process" if current_page == "ls" else "< 2-nd Process"

            keyboard = [
                [
                    InlineKeyboardButton(tl_total, callback_data=base_tl.format("tt")),
                    InlineKeyboardButton(tl_first, callback_data=base_tl.format("tf")),
                    InlineKeyboardButton(tl_second, callback_data=base_tl.format("ts")),
                ],
                [
                    InlineKeyboardButton(le_total, callback_data=base_le.format("lt")),
                    InlineKeyboardButton(le_first, callback_data=base_le.format("lf")),
                    InlineKeyboardButton(le_second, callback_data=base_le.format("ls")),
                ],
                [InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")]
            ]
        else:
            tl_total = "✓ TL Total" if current_page == "tt" else "TL Total"
            tl_actual = "✓ < Actual Process" if current_page == "ta" else "< Actual Process"
            tl_wished = "✓ < Wished Process" if current_page == "tw" else "< Wished Process"
            le_total = "✓ L.E. Total" if current_page == "lt" else "L.E. Total"
            le_actual = "✓ < Actual Process" if current_page == "la" else "< Actual Process"
            le_wished = "✓ < Wished Process" if current_page == "lw" else "< Wished Process"

            keyboard = [
                [
                    InlineKeyboardButton(tl_total, callback_data=base_tl.format("tt")),
                    InlineKeyboardButton(tl_actual, callback_data=base_tl.format("ta")),
                    InlineKeyboardButton(tl_wished, callback_data=base_tl.format("tw")),
                ],
                [
                    InlineKeyboardButton(le_total, callback_data=base_le.format("lt")),
                    InlineKeyboardButton(le_actual, callback_data=base_le.format("la")),
                    InlineKeyboardButton(le_wished, callback_data=base_le.format("lw")),
                ],
                [InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")]
            ]
        return InlineKeyboardMarkup(keyboard)

    elif weapon_category == "cup":
        # Cupid сравнение с галочками
        dummy_dmg = 0

        base_fury = f"l{prefix}:cup:{{}}:{dummy_dmg}:{roll_param}:{curr_upg}:{curr_corr_str}:{curr_ref_str}:{des_upg}:{des_corr_str}:{des_ref_str}:{roll}:{user_msg_id}"
        base_wrath = f"l{prefix}:cup_sw:{{}}:{dummy_dmg}:{roll_param}:{curr_upg}:{curr_corr_str}:{curr_ref_str}:{des_upg}:{des_corr_str}:{des_ref_str}:{roll}:{user_msg_id}"

        if has_two_rolls:
            fury_total = "✓ Fury Total" if current_page == "ft" else "Fury Total"
            fury_first = "✓ < 1-st Process" if current_page == "ff" else "< 1-st Process"
            fury_second = "✓ < 2-nd Process" if current_page == "fs" else "< 2-nd Process"
            wrath_total = "✓ Wrath Total" if current_page == "wt" else "Wrath Total"
            wrath_first = "✓ < 1-st Process" if current_page == "wf" else "< 1-st Process"
            wrath_second = "✓ < 2-nd Process" if current_page == "w2" else "< 2-nd Process"

            keyboard = [
                [
                    InlineKeyboardButton(fury_total, callback_data=base_fury.format("ft")),
                    InlineKeyboardButton(fury_first, callback_data=base_fury.format("ff")),
                    InlineKeyboardButton(fury_second, callback_data=base_fury.format("fs")),
                ],
                [
                    InlineKeyboardButton(wrath_total, callback_data=base_wrath.format("wt")),
                    InlineKeyboardButton(wrath_first, callback_data=base_wrath.format("wf")),
                    InlineKeyboardButton(wrath_second, callback_data=base_wrath.format("w2")),
                ],
                [InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")]
            ]
        else:
            fury_total = "✓ Fury Total" if current_page == "ft" else "Fury Total"
            fury_actual = "✓ < Actual Process" if current_page == "fa" else "< Actual Process"
            fury_wished = "✓ < Wished Process" if current_page == "fw" else "< Wished Process"
            wrath_total = "✓ Wrath Total" if current_page == "wt" else "Wrath Total"
            wrath_actual = "✓ < Actual Process" if current_page == "wa" else "< Actual Process"
            wrath_wished = "✓ < Wished Process" if current_page == "ww" else "< Wished Process"

            keyboard = [
                [
                    InlineKeyboardButton(fury_total, callback_data=base_fury.format("ft")),
                    InlineKeyboardButton(fury_actual, callback_data=base_fury.format("fa")),
                    InlineKeyboardButton(fury_wished, callback_data=base_fury.format("fw")),
                ],
                [
                    InlineKeyboardButton(wrath_total, callback_data=base_wrath.format("wt")),
                    InlineKeyboardButton(wrath_actual, callback_data=base_wrath.format("wa")),
                    InlineKeyboardButton(wrath_wished, callback_data=base_wrath.format("ww")),
                ],
                [InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")]
            ]
        return InlineKeyboardMarkup(keyboard)

    else:
        # Обычное оружие
        base = f"l{prefix}:{item_key}:{{}}:{roll_param}:{curr_upg}:{curr_corr_str}:{curr_ref_str}:{des_upg}:{des_corr_str}:{des_ref_str}:{user_msg_id}"

        if has_two_rolls:
            total_text = "✓ Total" if current_page == "total" else "Total"
            first_process_text = "✓ 1-st Process" if current_page == "fp" else "1-st Process"
            second_process_text = "✓ 2-nd Process" if current_page == "sp" else "2-nd Process"

            keyboard = [
                [
                    InlineKeyboardButton(total_text, callback_data=base.format("total")),
                    InlineKeyboardButton(first_process_text, callback_data=base.format("fp")),
                    InlineKeyboardButton(second_process_text, callback_data=base.format("sp")),
                ],
                [InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")]
            ]
        else:
            total_text = "✓ Total" if current_page == "total" else "Total"
            actual_process_text = "✓ Actual Process" if current_page == "ap" else "Actual Process"
            wished_process_text = "✓ Wished Process" if current_page == "wp" else "Wished Process"

            keyboard = [
                [
                    InlineKeyboardButton(total_text, callback_data=base.format("total")),
                    InlineKeyboardButton(actual_process_text, callback_data=base.format("ap")),
                    InlineKeyboardButton(wished_process_text, callback_data=base.format("wp")),
                ],
                [InlineKeyboardButton("Свернуть", callback_data=f"close:{user_msg_id}")]
            ]
        return InlineKeyboardMarkup(keyboard)

async def analyze_weapon(update: Update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    """Универсальная функция анализа оружия (!conq, !doom, !asc, !tl, !cup)"""
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

        item_info = ITEMS_MAPPING.get(item_key)
        # Для Cupid временно используем максимальный (99) для базовой проверки
        max_lvl = 99 if item_info and item_info.get("category") == "cup" else (item_info['max_level'] if item_info else 45)

        try:
            upg_level = int(args[1])
            if upg_level > max_lvl or upg_level < 0:
                errors.append(f"❌ Уровень оружия ({upg_level}) не соответствует 0-{max_lvl}.")
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
        weapon_info = determine_weapon_type(item_key, damage, upg_level, is_corrupted, reforge_mult)
        real_item_key = weapon_info["item_key"]
        item_info = ITEMS_MAPPING[real_item_key]
        is_wrath = weapon_info.get("is_wrath", False)

        # 🔧 ВАЛИДАЦИЯ: Проверяем соответствие уровня типу оружия
        if weapon_info["weapon_category"] == "cup":
            detected_max_level = item_info['max_level']

            if upg_level > detected_max_level:
                # Пытался наебать систему
                type_name = "Cupid's Fury" if not weapon_info["is_wrath"] else "Cupid's Wrath"

                error_message = (
                    f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
                    f"❌ Несоответствие данных!\n\n"
                    f"По урону {damage:,.0f} это **{type_name}** (макс. ур. {detected_max_level})\n"
                    f"Но ты указал уровень **{upg_level}**\n\n"
                    f"Наебать пытался? Пиздабол."
                )
                if await _send_error(update, context, error_message, ""):
                    return

        # Определяем флаги для UI
        is_ws = weapon_info.get("is_ws", False)
        is_ad = weapon_info.get("is_ad", False)

        active_weapon = None
        if weapon_info["weapon_category"] == "asc":
            if is_ws:
                active_weapon = "ws"
            elif is_ad:
                active_weapon = "ad"
            else:
                active_weapon = real_item_key.replace("asc_", "") if real_item_key.startswith("asc_") else "mb"

        # Генерируем ответ
        text = generate_total_page(
            item_info, damage, upg_level, is_corrupted,
            reforge_name, reforge_mult,
            weapon_info["roll"], weapon_info["base_dmg"],
            weapon_info["weapon_category"]
        )

        keyboard = generate_weapon_analysis_keyboard(
            item_key=real_item_key,
            current_page="total",
            dmg=damage,
            upg=upg_level,
            corr=is_corrupted,
            reforge_name=reforge_name,
            user_msg_id=update.message.message_id,
            weapon_category=weapon_info["weapon_category"],
            roll=weapon_info["roll"],
            is_ws=is_ws,
            is_ad=is_ad,
            active_weapon=active_weapon,
            is_wrath=is_wrath
        )

        await update.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            reply_to_message_id=update.message.message_id
        )
    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


async def w_analyze_weapon(update: Update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    """Универсальная функция прогноза оружия (!wconq, !wdoom, !wasc, !wtl, !wcup)"""
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

    item_info = ITEMS_MAPPING.get(item_key)
    is_asc = item_info.get("category") == "asc" if item_info else False
    is_cup = item_info.get("category") == "cup" if item_info else False
    min_roll = 6 if is_asc else 1

    # Парсинг roll
    if not errors:
        try:
            roll = int(left_args[0])
            if not min_roll <= roll <= 11:
                errors.append(f"❌ Ролл ({roll}) должен быть в диапазоне {min_roll}-11.")
        except ValueError:
            errors.append(f"❌ Ролл ({left_args[0]}) должен быть числом.")

    # Парсинг правой части
    # 🔥 Для Cupid позволяем ввод до 99
    if is_cup:
        max_input_level = 99
    else:
        max_input_level = item_info['max_level'] if item_info else 45

    if not errors:
        try:
            target_level = int(right_args[0])
            if target_level > max_input_level or target_level < 0:
                errors.append(f"❌ Уровень оружия ({target_level}) не соответствует 0-{max_input_level}.")
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
        error_message += f"{example} \n(Ролл: 1-11 для обычных/TL, 6-11 для ASC)"
        if await _send_error(update, context, error_message, example):
            return

    roll = int(left_args[0])
    target_level = int(right_args[0])
    is_corrupted = is_corrupted_str == 'y'

    try:
        category = item_info.get("category", "normal") if item_info else "normal"

        active_weapon = None
        if category == "asc":
            active_weapon = random.choice(["mb", "lk", "me", "at", "ad", "ws"])
            real_item_key = f"asc_{active_weapon}"
            weapon_roll = 11 if active_weapon == "ws" else roll
        elif category == "tl":
            real_item_key = "tl"
            weapon_roll = roll
        elif category == "cup":
            # 🔥 Определяем тип на основе уровня
            if target_level > 74:
                real_item_key = "cup_sw"  # Wrath
                weapon_roll = roll
            else:
                real_item_key = "cup"  # Fury
                weapon_roll = roll
        else:
            real_item_key = item_key
            weapon_roll = roll

        real_item_info = ITEMS_MAPPING[real_item_key]

        # 🔥 ГЛАВНОЕ: Реально ограничиваем уровень для расчётов!
        actual_max = real_item_info['max_level']
        calc_level = min(target_level, actual_max)

        # 🔥 Передаём calc_level для реальных расчётов, и target_level для отображения
        text = generate_forecast_total_page(
            real_item_info, weapon_roll, calc_level, is_corrupted,
            reforge_name, reforge_mult, category, target_level  # <-- передаём оба
        )

        if category == "tl":
            current_page = "tt"
        elif category == "cup":
            current_page = "ft" if real_item_key == "cup" else "wt"
        else:
            current_page = "total"

        keyboard = generate_weapon_forecast_keyboard(
            item_key=real_item_key,
            current_page=current_page,
            roll=roll,
            upg=target_level,  # Для callback'ов сохраняем оригинал
            corr=is_corrupted,
            reforge_name=reforge_name,
            user_msg_id=update.message.message_id,
            weapon_category=category,
            original_roll=roll,
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


async def l_analyze_weapon(update: Update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    """Универсальная функция сравнения оружия (!lconq, !ldoom, !lasc, !ltl)"""
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args_raw = context.args
    errors = []

    item_info = ITEMS_MAPPING.get(item_key)
    is_asc = item_info.get("category") == "asc" if item_info else False
    is_cup = item_info.get("category") == "cup" if item_info else False
    min_roll = 6 if is_asc else 1
    max_roll = 11
    # 🔥 Для Cupid разрешаем ввод до 99 (Wrath max), реальное ограничение применяется позже
    max_lvl = 99 if is_cup else (item_info['max_level'] if item_info else 45)

    # === НОВЫЙ ПАРСИНГ: Определяем режим (1 или 2 ролла) ===

    # Ищем позиции разделителей
    minus_idx = -1
    first_gt_idx = -1
    second_gt_idx = -1

    for idx, arg in enumerate(args_raw):
        if arg == '-' and minus_idx == -1:
            minus_idx = idx
        elif arg == '>':
            if first_gt_idx == -1:
                first_gt_idx = idx
            elif second_gt_idx == -1:
                second_gt_idx = idx

    # Определяем режим
    has_two_rolls = False

    # Если первый разделитель > и после него есть число, и потом -, то это два ролла
    if first_gt_idx != -1 and minus_idx != -1:
        # Проверяем: после первого > должно быть число (roll2)
        if first_gt_idx + 1 < len(args_raw):
            potential_roll2 = args_raw[first_gt_idx + 1]
            if potential_roll2.isdigit() or (potential_roll2.startswith('-') and potential_roll2[1:].isdigit()):
                # И после этого числа должен быть -
                if minus_idx == first_gt_idx + 2:
                    has_two_rolls = True

    # Если первый разделитель -, то это один ролл
    if minus_idx != -1 and (first_gt_idx == -1 or minus_idx < first_gt_idx):
        has_two_rolls = False

    # Проверяем наличие обязательных разделителей
    if minus_idx == -1:
        errors.append("❌ Обязательный разделитель '-' не найден.")

    if has_two_rolls and second_gt_idx == -1:
        errors.append("❌ Для двух роллов нужен второй разделитель '>'.")
    elif not has_two_rolls and first_gt_idx == -1:
        errors.append("❌ Обязательный разделитель '>' не найден.")

    # === ПАРСИНГ РОЛЛОВ ===
    roll1 = None
    roll2 = None

    if not errors:
        if has_two_rolls:
            # Формат: roll1 > roll2 - ...
            # roll1 должен быть до первого >
            if first_gt_idx == 0:
                errors.append("❌ Не указан roll1 до знака >.")
            else:
                try:
                    roll1 = int(args_raw[0])
                    if not min_roll <= roll1 <= max_roll:
                        errors.append(f"❌ Roll1 ({roll1}) должен быть в диапазоне {min_roll}-{max_roll}.")
                except ValueError:
                    errors.append(f"❌ Roll1 ({args_raw[0]}) должен быть числом.")

            # roll2 между > и -
            try:
                roll2 = int(args_raw[first_gt_idx + 1])
                if not min_roll <= roll2 <= max_roll:
                    errors.append(f"❌ Roll2 ({roll2}) должен быть в диапазоне {min_roll}-{max_roll}.")
            except (ValueError, IndexError):
                errors.append(f"❌ Roll2 должен быть числом между > и -.")

            # Проверка: roll1 < roll2
            if roll1 is not None and roll2 is not None and roll1 >= roll2:
                errors.append(f"❌ Roll1 ({roll1}) должен быть меньше Roll2 ({roll2}).")
        else:
            # Формат: roll1 - ...
            try:
                roll1 = int(args_raw[0])
                if not min_roll <= roll1 <= max_roll:
                    errors.append(f"❌ Roll ({roll1}) должен быть в диапазоне {min_roll}-{max_roll}.")
                roll2 = roll1  # Один и тот же ролл
            except ValueError:
                errors.append(f"❌ Roll ({args_raw[0]}) должен быть числом.")

    # === ПАРСИНГ СОСТОЯНИЙ ===
    curr_upg = curr_corr = curr_ref_name = curr_ref_mult = None
    des_upg = des_corr = des_ref_name = des_ref_mult = None

    if not errors:
        if has_two_rolls:
            # Часть между - и вторым >
            mid_start = minus_idx + 1
            mid_end = second_gt_idx if second_gt_idx != -1 else len(args_raw)
            mid_part = args_raw[mid_start:mid_end]

            # Часть после второго >
            right_part = args_raw[second_gt_idx + 1:] if second_gt_idx != -1 else []
        else:
            # Часть между - и >
            mid_start = minus_idx + 1
            mid_end = first_gt_idx if first_gt_idx != -1 else len(args_raw)
            mid_part = args_raw[mid_start:mid_end]

            # Часть после >
            right_part = args_raw[first_gt_idx + 1:] if first_gt_idx != -1 else []

        # Парсим текущее состояние (mid_part)
        if len(mid_part) not in (2, 3):
            errors.append(f"❌ Текущее состояние: ожидается 2 или 3 аргумента, получено {len(mid_part)}.")
        else:
            try:
                curr_upg = int(mid_part[0])
                if not 0 <= curr_upg <= max_lvl:
                    errors.append(f"❌ Текущий уровень ({curr_upg}) не в 0-{max_lvl}.")
            except ValueError:
                errors.append(f"❌ Текущий уровень ({mid_part[0]}) должен быть числом.")

            curr_corr_str = mid_part[1].lower()
            if curr_corr_str not in ('y', 'n'):
                errors.append(f"❌ Текущий corrupted ({mid_part[1]}) должен быть 'y' или 'n'.")
            curr_corr = curr_corr_str == 'y'

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

        # Парсим желаемое состояние (right_part)
        if len(right_part) not in (2, 3):
            errors.append(f"❌ Желаемое состояние: ожидается 2 или 3 аргумента, получено {len(right_part)}.")
        else:
            try:
                des_upg = int(right_part[0])
                if not 0 <= des_upg <= max_lvl:
                    errors.append(f"❌ Желаемый уровень ({des_upg}) не в 0-{max_lvl}.")
            except ValueError:
                errors.append(f"❌ Желаемый уровень ({right_part[0]}) должен быть числом.")

            des_corr_str = right_part[1].lower()
            if des_corr_str not in ('y', 'n'):
                errors.append(f"❌ Желаемый corrupted ({right_part[1]}) должен быть 'y' или 'n'.")
            des_corr = des_corr_str == 'y'

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

    # === СТРОГИЕ ПРОВЕРКИ ДЛЯ ОДНОГО РОЛЛА ===
    if not errors and not has_two_rolls:
        # 1. Нельзя декорраптить
        if curr_corr and not des_corr:
            errors.append("❌ Нельзя декорраптить (y → n запрещено).")

        # 2. Нельзя понижать уровень
        if des_upg < curr_upg:
            errors.append(f"❌ Нельзя понижать уровень ({curr_upg} → {des_upg} запрещено).")

        # 3. Нельзя удалять зачарование
        if curr_ref_name != "None" and des_ref_name == "None":
            errors.append("❌ Нельзя удалять зачарование (reforge → None запрещено).")

    # === ОБРАБОТКА ОШИБОК ===
    if errors:
        if has_two_rolls:
            example = f"`{command_name}` {{roll1}} > {{roll2}} - {{upg1}} {{y/n1}} [reforge1] > {{upg2}} {{y/n2}} [reforge2]"
        else:
            example = f"`{command_name}` {{roll}} - {{upg1}} {{y/n1}} [reforge1] > {{upg2}} {{y/n2}} [reforge2]"

        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n" + example
        error_message += f"\n(Ролл: {min_roll}-{max_roll})"
        if await _send_error(update, context, error_message, example):
            return

    try:
        category = item_info.get("category", "normal") if item_info else "normal"

        active_weapon = None
        if category == "asc":
            active_weapon = random.choice(["mb", "lk", "me", "at", "ad", "ws"])
            real_item_key = f"asc_{active_weapon}"
            weapon_roll = 11 if active_weapon == "ws" else roll1
        elif category == "tl":
            real_item_key = "tl"
            weapon_roll = roll1
        elif category == "cup":
            # 🔥 Определяем тип на основе максимального уровня из ввода
            max_input_level = max(des_upg, curr_upg)
            if max_input_level > 74:
                real_item_key = "cup_sw"  # Wrath
                weapon_roll = roll1
            else:
                real_item_key = "cup"  # Fury
                weapon_roll = roll1
        else:
            real_item_key = item_key
            weapon_roll = roll1

        real_item_info = ITEMS_MAPPING[real_item_key]

        # 🔥 ГЛАВНОЕ: Реально ограничиваем уровни для расчётов!
        actual_max = real_item_info['max_level']
        calc_curr_upg = min(curr_upg, actual_max)
        calc_des_upg = min(des_upg, actual_max)

        # Генерируем текст с реальными ограниченными уровнями
        text = generate_compare_total_page(
            real_item_info, weapon_roll,
            calc_curr_upg, curr_corr, curr_ref_mult, curr_ref_name,
            calc_des_upg, des_corr, des_ref_mult, des_ref_name,
            category, has_two_rolls, roll2 if has_two_rolls else None,
            curr_upg, des_upg  # <-- передаём оригиналы для отображения
        )

        if category == "tl":
            current_page = "tt"
        elif category == "cup":
            current_page = "ft" if real_item_key == "cup" else "wt"
        else:
            current_page = "total"

        keyboard = generate_weapon_compare_keyboard(
            item_key=real_item_key,
            current_page=current_page,
            roll=roll1,
            curr_upg=curr_upg,  # Оригинальные для callback'ов
            curr_corr=curr_corr,
            curr_ref=curr_ref_name,
            des_upg=des_upg,
            des_corr=des_corr,
            des_ref=des_ref_name,
            user_msg_id=update.message.message_id,
            weapon_category=category,
            original_roll=roll1,
            active_weapon=active_weapon,
            has_two_rolls=has_two_rolls,
            roll2=roll2 if has_two_rolls else None
        )

        await update.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            reply_to_message_id=update.message.message_id
        )
    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчёте: {e}")

async def weapon_analysis_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Единый обработчик callback'ов для всего оружия"""
    query = update.callback_query

    # ==================== БЛОК 1: ПРОВЕРКА ВЛАДЕЛЬЦА ====================
    if not check_message_ownership(query):
        await query.answer("Это не ваше сообщение!", show_alert=True)
        return

    await query.answer()

    # ==================== БЛОК 2: ОБРАБОТКА ЗАКРЫТИЯ ====================
    if "close" in query.data:
        try:
            parts = query.data.split(":")
            if len(parts) >= 2:
                user_msg_id = int(parts[-1])
                await query.message.delete()
                await context.bot.delete_message(
                    chat_id=query.message.chat.id,
                    message_id=user_msg_id
                )
            return
        except Exception as e:
            print(f"Ошибка при закрытии: {e}")
            return

    # ==================== БЛОК 3: ПАРСИНГ БАЗОВЫХ ПАРАМЕТРОВ ====================
    data_parts = query.data.split(":")
    if len(data_parts) < 4:
        await query.answer("Ошибка формата", show_alert=True)
        return

    prefix = data_parts[0]
    raw_item_key = data_parts[1]  # cb, db, ws, ad, asc_mb, tl, tl_le, cup, cup_sw и т.д.
    page = data_parts[2]

    # ==================== БЛОК 4: ОПРЕДЕЛЕНИЕ ТИПА КОМАНДЫ ====================
    category = "normal"
    command_type = "analyze"

    if prefix.startswith("w"):
        command_type = "forecast"
        category = prefix[1:]  # wnormal -> normal, wtl -> tl, wcup -> cup
    elif prefix.startswith("l"):
        command_type = "compare"
        category = prefix[1:]  # lnormal -> normal, ltl -> tl, lcup -> cup
    else:
        category = prefix  # normal, tl, asc, cup

    # 🔧 ИСПРАВЛЕНИЕ: Определяем специальные типы ДО маппинга
    is_ws = (raw_item_key == "ws")
    is_ad = (raw_item_key == "ad")
    is_cup_sw = (raw_item_key == "cup_sw")

    # 🔧 ИСПРАВЛЕНИЕ: Мапим raw_item_key в реальный item_key для ITEMS_MAPPING
    if category == "asc":
        if is_ws:
            item_key = "asc_ws"
        elif is_ad:
            item_key = "asc_ad"
        elif raw_item_key.startswith("asc_"):
            item_key = raw_item_key
        else:
            item_key = f"asc_{raw_item_key}"
    elif category == "cup":
        # Cupid: cup или cup_sw
        item_key = "cup_sw" if is_cup_sw else "cup"
    else:
        item_key = raw_item_key

    # ==================== БЛОК 5: ОБРАБОТКА ANALYZE ====================
    if command_type == "analyze":
        if len(data_parts) < 9:
            await query.answer("Ошибка: неверный формат данных", show_alert=True)
            return

        dmg = float(data_parts[3])
        upg = int(data_parts[4])
        corr = data_parts[5] == 'y'
        reforge_name = data_parts[6]
        roll = int(data_parts[7])
        # data_parts[8] - is_le для tl, is_wrath для cup, или 0 для остальных
        is_special = bool(int(data_parts[8])) if len(data_parts) > 8 else False
        user_msg_id = int(data_parts[9]) if len(data_parts) > 9 else int(data_parts[-1])

        reforge_mult = REFORGE_MODIFIERS.get(reforge_name, 1.0)

        # Получаем item_info
        item_info = ITEMS_MAPPING[item_key]

        # Определяем base_dmg в зависимости от типа
        if is_ws:
            base_dmg = WOODEN_SWORD_BASE
        elif is_ad:
            base_dmg = DUAL_DAGGERS_V2_STATS.get(roll, DUAL_DAGGERS_V2_STATS[6])
        elif category == "cup" and is_cup_sw:
            base_dmg = DOOMBRINGER_STATS[roll]
        elif category == "cup":
            base_dmg = CUPIDS_FURY_STATS[roll]
        else:
            base_dmg = item_info['stats'][roll]

        # Определяем active_weapon для UI (только для ASC)
        active_weapon = None
        is_wrath = False  # 🔧 Для Cupid в callback

        if category == "asc":
            if is_ws:
                active_weapon = "ws"
            elif is_ad:
                active_weapon = "ad"
            else:
                active_weapon = item_key.replace("asc_", "") if item_key.startswith("asc_") else "mb"
        elif category == "cup":
            # 🔧 Для Cupid определяем is_wrath из callback данных
            is_wrath = is_cup_sw  # is_cup_sw определено выше

        # Генерируем текст в зависимости от страницы
        if page == "total":
            text = generate_total_page(item_info, dmg, upg, corr, reforge_name, reforge_mult,
                                       roll, base_dmg, category)
            parse_mode = ParseMode.HTML
        elif page == "process":
            text = generate_process_page(item_info, dmg, upg, corr, reforge_name, reforge_mult,
                                         roll, base_dmg, category)
            parse_mode = ParseMode.HTML
        elif page == "tablet":
            text = generate_tablet_page(item_info, roll, corr, reforge_mult, reforge_name, category)
            parse_mode = ParseMode.MARKDOWN_V2
        else:
            await query.answer("Неизвестная страница", show_alert=True)
            return

        # Генерируем клавиатуру
        keyboard = generate_weapon_analysis_keyboard(
            item_key=raw_item_key,
            current_page=page,
            dmg=dmg,
            upg=upg,
            corr=corr,
            reforge_name=reforge_name,
            user_msg_id=user_msg_id,
            weapon_category=category,
            roll=roll,
            is_ws=is_ws,
            is_ad=is_ad,
            active_weapon=active_weapon,
            is_wrath=is_wrath  # 🔧 Передаём is_wrath
        )

    # ==================== БЛОК 6: ОБРАБОТКА FORECAST ====================
    elif command_type == "forecast":
        reforge_name = data_parts[6] if category in ("normal", "tl", "cup") else data_parts[7]
        reforge_mult = REFORGE_MODIFIERS.get(reforge_name, 1.0)

        # --- Обычное оружие (normal) ---
        if category == "normal":
            # Формат: wnormal:cb:total:roll:upg:corr:reforge:user_msg_id
            roll = int(data_parts[3])
            upg = int(data_parts[4])
            corr = data_parts[5] == 'y'
            user_msg_id = int(data_parts[-1])
            item_info = ITEMS_MAPPING[item_key]

            if page == "total":
                text = generate_forecast_total_page(item_info, roll, upg, corr, reforge_name, reforge_mult, category)
            elif page == "process":
                text = generate_forecast_process_page(item_info, roll, upg, corr, reforge_name, reforge_mult, category)
            else:
                await query.answer("Неизвестная страница", show_alert=True)
                return

            keyboard = generate_weapon_forecast_keyboard(
                item_key, page, roll, upg, corr, reforge_name, user_msg_id, category
            )
            parse_mode = ParseMode.HTML

        # --- Timelost (tl) ---
        elif category == "tl":
            # Формат: wtl:tl:tl_total:dmg:roll:upg:corr:reforge:orig_roll:user_msg_id
            _tl_page_map = {"tt": ("total", "tl"), "tp": ("process", "tl"),
                              "lt": ("total", "tl_le"), "lp": ("process", "tl_le")}
            real_page, _tl_key = _tl_page_map.get(page, ("total", "tl"))
            tl_item_key = _tl_key
            item_info = ITEMS_MAPPING[tl_item_key]

            roll = int(data_parts[4])
            upg = int(data_parts[5])
            corr = data_parts[6] == 'y'
            reforge_name = data_parts[7]  # ← ИСПРАВЛЕНО: было [6], должно быть [7]
            reforge_mult = REFORGE_MODIFIERS.get(reforge_name, 1.0)
            user_msg_id = int(data_parts[-1])

            if real_page == "total":
                text = generate_forecast_total_page(item_info, roll, upg, corr, reforge_name, reforge_mult, category)
            elif real_page == "process":
                text = generate_forecast_process_page(item_info, roll, upg, corr, reforge_name, reforge_mult, category)
            else:
                await query.answer("Неизвестная страница", show_alert=True)
                return

            keyboard = generate_weapon_forecast_keyboard(
                tl_item_key, page, roll, upg, corr, reforge_name, user_msg_id, category, roll
            )
            parse_mode = ParseMode.HTML

        # --- Cupid (cup) - НОВОЕ ---
        elif category == "cup":
            # Формат: wcup:cup:fury_total:dmg:roll:upg:corr:reforge:orig_roll:user_msg_id
            _cup_page_map = {"ft": ("total", "cup"), "fuP": ("process", "cup"),
                              "wt": ("total", "cup_sw"), "wrP": ("process", "cup_sw")}
            real_page, _cup_key = _cup_page_map.get(page, ("total", "cup"))
            cup_item_key = _cup_key
            item_info = ITEMS_MAPPING[cup_item_key]

            roll = int(data_parts[4])
            upg_raw = int(data_parts[5])
            corr = data_parts[6] == 'y'
            reforge_name = data_parts[7]  # ← ИСПРАВЛЕНО: было [6], должно быть [7]
            reforge_mult = REFORGE_MODIFIERS.get(reforge_name, 1.0)
            user_msg_id = int(data_parts[-1])

            # 🔥 Обрезаем уровень до максимума конкретного оружия (Fury max=74, Wrath max=99)
            actual_max = item_info['max_level']
            upg = min(upg_raw, actual_max)
            display_upg = upg_raw if upg_raw != upg else None

            if real_page == "total":
                text = generate_forecast_total_page(item_info, roll, upg, corr, reforge_name, reforge_mult, category, display_upg)
            elif real_page == "process":
                text = generate_forecast_process_page(item_info, roll, upg, corr, reforge_name, reforge_mult, category)
            else:
                await query.answer("Неизвестная страница", show_alert=True)
                return

            keyboard = generate_weapon_forecast_keyboard(
                cup_item_key, page, roll, upg_raw, corr, reforge_name, user_msg_id, category, roll
            )
            parse_mode = ParseMode.HTML

        # --- ASC (asc) ---
        else:
            weapon_roll = int(data_parts[4])
            upg = int(data_parts[5])
            corr = data_parts[6] == 'y'
            orig_roll = int(data_parts[8])
            user_msg_id = int(data_parts[9])

            item_info = ITEMS_MAPPING[item_key]

            if page == "total":
                text = generate_forecast_total_page(item_info, weapon_roll, upg, corr, reforge_name, reforge_mult,
                                                    category)
            elif page == "process":
                text = generate_forecast_process_page(item_info, weapon_roll, upg, corr, reforge_name, reforge_mult,
                                                      category)
            else:
                await query.answer("Неизвестная страница", show_alert=True)
                return

            active_weapon = item_key.replace("asc_", "")
            keyboard = generate_weapon_forecast_keyboard(
                item_key, page, orig_roll, upg, corr, reforge_name, user_msg_id, category, orig_roll, active_weapon
            )
            parse_mode = ParseMode.HTML

    # ==================== БЛОК 7: ОБРАБОТКА COMPARE ====================
    else:  # command_type == "compare"

        # --- Определяем режим (1 или 2 ролла) ---
        has_two_rolls = False
        roll2 = None

        # --- Обычное оружие (normal) ---
        if category == "normal":
            # Формат: lnormal:cb:total:roll:curr_upg:curr_corr:curr_ref:des_upg:des_corr:des_ref:user_msg_id
            # ИЛИ с двумя роллами: lnormal:cb:total:roll1_roll2:...

            roll_param = data_parts[3]
            has_two_rolls = '_' in roll_param

            if has_two_rolls:
                roll1_str, roll2_str = roll_param.split('_')
                roll = int(roll1_str)
                roll2 = int(roll2_str)
            else:
                roll = int(roll_param)

            curr_upg = int(data_parts[4])
            curr_corr = data_parts[5] == 'y'
            curr_ref = data_parts[6]
            des_upg = int(data_parts[7])
            des_corr = data_parts[8] == 'y'
            des_ref = data_parts[9]
            user_msg_id = int(data_parts[-1])

            item_info = ITEMS_MAPPING[item_key]

            curr_ref_mult = REFORGE_MODIFIERS.get(curr_ref, 1.0)
            des_ref_mult = REFORGE_MODIFIERS.get(des_ref, 1.0)

            # Генерируем текст
            if page == "total":
                text = generate_compare_total_page(item_info, roll, curr_upg, curr_corr, curr_ref_mult, curr_ref,
                                                   des_upg, des_corr, des_ref_mult, des_ref, category, has_two_rolls,
                                                   roll2)
            elif page == "ap" or page == "fp":
                text = generate_compare_process_page(item_info, roll, curr_upg, curr_corr, curr_ref_mult, curr_ref,
                                                     "Actual" if not has_two_rolls else "1-st", category)
            elif page == "wp" or page == "sp":
                calc_roll = roll2 if has_two_rolls and roll2 else roll
                text = generate_compare_process_page(item_info, calc_roll, des_upg, des_corr, des_ref_mult, des_ref,
                                                     "Wished" if not has_two_rolls else "2-nd", category)
            else:
                await query.answer("Неизвестная страница", show_alert=True)
                return

            keyboard = generate_weapon_compare_keyboard(
                item_key, page, roll, curr_upg, curr_corr, curr_ref,
                des_upg, des_corr, des_ref, user_msg_id, category, roll,
                None, has_two_rolls, roll2
            )
            parse_mode = ParseMode.HTML

        # --- Timelost (tl) ---
        elif category == "tl":
            # Формат: ltl:tl:tl_total:roll_param:curr_upg:curr_corr:curr_ref:des_upg:des_corr:des_ref:orig_roll:user_msg_id

            roll_param = data_parts[4]
            has_two_rolls = '_' in roll_param

            if has_two_rolls:
                roll1_str, roll2_str = roll_param.split('_')
                roll = int(roll1_str)
                roll2 = int(roll2_str)
            else:
                roll = int(roll_param)

            _ltl_map = {
                "tt": ("total",  "tl"),    "ta": ("actual",  "tl"),    "tw": ("wished",  "tl"),
                "tf": ("first",  "tl"),    "ts": ("second",  "tl"),
                "lt": ("total",  "tl_le"), "la": ("actual",  "tl_le"), "lw": ("wished",  "tl_le"),
                "lf": ("first",  "tl_le"), "ls": ("second",  "tl_le"),
            }
            real_page, _tl_key = _ltl_map.get(page, ("total", "tl"))
            tl_item_key = _tl_key
            item_info = ITEMS_MAPPING[tl_item_key]

            curr_upg = int(data_parts[5])
            curr_corr = data_parts[6] == 'y'
            curr_ref = data_parts[7]
            des_upg = int(data_parts[8])
            des_corr = data_parts[9] == 'y'
            des_ref = data_parts[10]
            user_msg_id = int(data_parts[-1])

            curr_ref_mult = REFORGE_MODIFIERS.get(curr_ref, 1.0)
            des_ref_mult = REFORGE_MODIFIERS.get(des_ref, 1.0)

            # Генерируем текст
            if real_page == "total":
                text = generate_compare_total_page(item_info, roll, curr_upg, curr_corr, curr_ref_mult, curr_ref,
                                                   des_upg, des_corr, des_ref_mult, des_ref, category, has_two_rolls,
                                                   roll2)
            elif real_page == "actual" or real_page == "first":
                text = generate_compare_process_page(item_info, roll, curr_upg, curr_corr, curr_ref_mult, curr_ref,
                                                     "Actual" if not has_two_rolls else "1-st", category)
            elif real_page == "wished" or real_page == "second":
                calc_roll = roll2 if has_two_rolls and roll2 else roll
                text = generate_compare_process_page(item_info, calc_roll, des_upg, des_corr, des_ref_mult, des_ref,
                                                     "Wished" if not has_two_rolls else "2-nd", category)
            else:
                await query.answer("Неизвестная страница", show_alert=True)
                return

            keyboard = generate_weapon_compare_keyboard(
                tl_item_key, page, roll, curr_upg, curr_corr, curr_ref,
                des_upg, des_corr, des_ref, user_msg_id, category, roll,
                None, has_two_rolls, roll2
            )
            parse_mode = ParseMode.HTML

        # --- Cupid (cup) - НОВОЕ ---
        elif category == "cup":
            # Формат: lcup:cup:fury_total:roll_param:curr_upg:curr_corr:curr_ref:des_upg:des_corr:des_ref:orig_roll:user_msg_id

            roll_param = data_parts[4]
            has_two_rolls = '_' in roll_param

            if has_two_rolls:
                roll1_str, roll2_str = roll_param.split('_')
                roll = int(roll1_str)
                roll2 = int(roll2_str)
            else:
                roll = int(roll_param)

            _lcup_map = {
                "ft": ("total",  "cup"),    "fa": ("actual",  "cup"),    "fw": ("wished",  "cup"),
                "ff": ("first",  "cup"),    "fs": ("second",  "cup"),
                "wt": ("total",  "cup_sw"), "wa": ("actual",  "cup_sw"), "ww": ("wished",  "cup_sw"),
                "wf": ("first",  "cup_sw"), "w2":("second",  "cup_sw"),
            }
            real_page, _cup_key = _lcup_map.get(page, ("total", "cup"))
            cup_item_key = _cup_key
            item_info = ITEMS_MAPPING[cup_item_key]

            curr_upg_raw = int(data_parts[5])
            curr_corr = data_parts[6] == 'y'
            curr_ref = data_parts[7]
            des_upg_raw = int(data_parts[8])
            des_corr = data_parts[9] == 'y'
            des_ref = data_parts[10]
            user_msg_id = int(data_parts[-1])

            curr_ref_mult = REFORGE_MODIFIERS.get(curr_ref, 1.0)
            des_ref_mult = REFORGE_MODIFIERS.get(des_ref, 1.0)

            # 🔥 Обрезаем уровни до максимума конкретного оружия (Fury max=74, Wrath max=99)
            actual_max = item_info['max_level']
            curr_upg = min(curr_upg_raw, actual_max)
            des_upg = min(des_upg_raw, actual_max)
            display_curr = curr_upg_raw if curr_upg_raw != curr_upg else None
            display_des = des_upg_raw if des_upg_raw != des_upg else None

            # Генерируем текст
            if real_page == "total":
                text = generate_compare_total_page(item_info, roll, curr_upg, curr_corr, curr_ref_mult, curr_ref,
                                                   des_upg, des_corr, des_ref_mult, des_ref, category, has_two_rolls,
                                                   roll2, display_curr, display_des)
            elif real_page == "actual" or real_page == "first":
                text = generate_compare_process_page(item_info, roll, curr_upg, curr_corr, curr_ref_mult, curr_ref,
                                                     "Actual" if not has_two_rolls else "1-st", category)
            elif real_page == "wished" or real_page == "second":
                calc_roll = roll2 if has_two_rolls and roll2 else roll
                text = generate_compare_process_page(item_info, calc_roll, des_upg, des_corr, des_ref_mult, des_ref,
                                                     "Wished" if not has_two_rolls else "2-nd", category)
            else:
                await query.answer("Неизвестная страница", show_alert=True)
                return

            keyboard = generate_weapon_compare_keyboard(
                cup_item_key, page, roll, curr_upg_raw, curr_corr, curr_ref,
                des_upg_raw, des_corr, des_ref, user_msg_id, category, roll,
                None, has_two_rolls, roll2
            )
            parse_mode = ParseMode.HTML

        # --- ASC (asc) ---
        else:  # category == "asc"
            # Формат: lasc:mb:total:dmg:weapon_roll:curr_upg:curr_corr:curr_ref:des_upg:des_corr:des_ref:orig_roll:user_msg_id:has_two_rolls:roll2

            weapon_roll = int(data_parts[4])
            curr_upg = int(data_parts[5])
            curr_corr = data_parts[6] == 'y'
            curr_ref = data_parts[7]
            des_upg = int(data_parts[8])
            des_corr = data_parts[9] == 'y'
            des_ref = data_parts[10]
            orig_roll = int(data_parts[11])
            user_msg_id = int(data_parts[12])

            # Проверяем наличие флага двух роллов
            if len(data_parts) >= 15:
                has_two_rolls = data_parts[13] == "1"
                roll2 = int(data_parts[14]) if has_two_rolls else None
            else:
                has_two_rolls = False
                roll2 = None

            curr_ref_mult = REFORGE_MODIFIERS.get(curr_ref, 1.0)
            des_ref_mult = REFORGE_MODIFIERS.get(des_ref, 1.0)
            item_info = ITEMS_MAPPING[item_key]

            # Генерируем текст
            if page == "total":
                text = generate_compare_total_page(item_info, weapon_roll, curr_upg, curr_corr, curr_ref_mult, curr_ref,
                                                   des_upg, des_corr, des_ref_mult, des_ref, category, has_two_rolls,
                                                   roll2)
            elif page == "ap" or page == "fp":
                text = generate_compare_process_page(item_info, weapon_roll, curr_upg, curr_corr, curr_ref_mult,
                                                     curr_ref,
                                                     "Actual" if not has_two_rolls else "1-st", category)
            elif page == "wp" or page == "sp":
                calc_roll = roll2 if has_two_rolls and roll2 else weapon_roll
                text = generate_compare_process_page(item_info, calc_roll, des_upg, des_corr, des_ref_mult, des_ref,
                                                     "Wished" if not has_two_rolls else "2-nd", category)
            else:
                await query.answer("Неизвестная страница", show_alert=True)
                return

            active_weapon = item_key.replace("asc_", "") if item_key.startswith("asc_") else None

            keyboard = generate_weapon_compare_keyboard(
                item_key, page, orig_roll, curr_upg, curr_corr, curr_ref,
                des_upg, des_corr, des_ref, user_msg_id, category, orig_roll,
                active_weapon, has_two_rolls, roll2
            )
            parse_mode = ParseMode.HTML

    # ==================== БЛОК 8: ОТПРАВКА РЕЗУЛЬТАТА ====================
    try:
        await query.message.edit_text(text, parse_mode=parse_mode, reply_markup=keyboard)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            await query.answer()
        else:
            raise
    except Exception as e:
        print(f"Ошибка в weapon_analysis_callback: {e}")
        import traceback
        traceback.print_exc()
        await query.answer("Произошла ошибка при обработке", show_alert=True)

import base64
import struct

def pack_armor_data_compact(armor_data: dict, command: str) -> str:
    """Ультракомпактная упаковка данных брони: бинарные данные + base64"""
    parts = ['helm', 'chest', 'legs']
    result_bytes = bytearray()

    # Определяем тип команды (0-3) для маппинга fz/z/hk/k
    cmd_types = {'fz': 0, 'z': 1, 'hk': 2, 'k': 3,
                 'wfz': 0, 'wz': 1, 'whk': 2, 'wk': 3,
                 'lfz': 0, 'lz': 1, 'lhk': 2, 'lk': 3}
    cmd_type = cmd_types.get(command, 0)

    # Magic byte: тип команды (2 бита) + флаги наличия данных (3 бита)
    has_data_flags = 0
    data_bytes = bytearray()

    for i, part in enumerate(parts):
        data = armor_data.get(part)
        if data:
            has_data_flags |= (1 << i)  # Устанавливаем бит наличия данных (0,1,2)

            if command in ['fz', 'z', 'hk', 'k']:
                # Анализ: hp (сжато до 2 байт), upg (1 байт), corrupted (1 байт)
                hp = int(data['hp'])
                upg = data['upg']
                corrupted = 1 if data['corrupted'] else 0

                # HP храним напрямую в uint16 (макс HP брони ~8000, влезает без деления)
                hp_compressed = min(65535, max(0, hp))
                data_bytes.extend(struct.pack('>HB', hp_compressed, upg))
                data_bytes.append(corrupted)

            elif command in ['wfz', 'wz', 'whk', 'wk']:
                # Прогноз: roll (1), upg (1), corrupted (1)
                roll = data['roll']
                upg = data['upg']
                corrupted = 1 if data['corrupted'] else 0
                data_bytes.extend([roll, upg, corrupted])

            else:  # l-команды
                has_two = data.get('has_two_rolls', False)
                r1 = data['roll1']
                r2 = data['roll2'] if has_two else r1
                u1 = data['upg1']
                c1 = 1 if data['corrupted1'] else 0
                u2 = data['upg2']
                c2 = 1 if data['corrupted2'] else 0

                # Формат: [flags][r1][r2 если два][u1][u2][c1c2]
                flags = 1 if has_two else 0

                if has_two:
                    data_bytes.extend([flags, r1, r2, u1, u2, (c1 << 1) | c2])
                else:
                    data_bytes.extend([flags, r1, u1, u2, (c1 << 1) | c2])

    # Собираем: magic (тип + флаги) + данные
    magic = cmd_type | (has_data_flags << 2)
    result_bytes.append(magic)
    result_bytes.extend(data_bytes)

    # Base64 URL-safe без padding
    encoded = base64.urlsafe_b64encode(bytes(result_bytes)).rstrip(b'=').decode('ascii')
    return encoded


def unpack_armor_data_compact(data_str: str, command: str) -> dict:
    """Распаковка ультракомпактных данных брони"""
    armor_data = {'helm': None, 'chest': None, 'legs': None}

    if not data_str:
        return armor_data

    # Добавляем padding обратно
    padding = 4 - len(data_str) % 4
    if padding != 4:
        data_str += '=' * padding

    try:
        decoded = base64.urlsafe_b64decode(data_str)
    except Exception:
        return armor_data

    if len(decoded) < 1:
        return armor_data

    magic = decoded[0]
    has_data_flags = (magic >> 2) & 0x07  # 3 бита

    parts = ['helm', 'chest', 'legs']
    idx = 1

    for i, part in enumerate(parts):
        if not (has_data_flags & (1 << i)):
            continue

        try:
            if command in ['fz', 'z', 'hk', 'k']:
                if idx + 3 >= len(decoded):
                    break
                hp_compressed, upg = struct.unpack('>HB', decoded[idx:idx + 3])
                corrupted = decoded[idx + 3]
                idx += 4

                armor_data[part] = {
                    'hp': hp_compressed,
                    'upg': upg,
                    'corrupted': bool(corrupted)
                }

            elif command in ['wfz', 'wz', 'whk', 'wk']:
                if idx + 2 >= len(decoded):
                    break
                roll, upg, corrupted = decoded[idx], decoded[idx + 1], decoded[idx + 2]
                idx += 3

                armor_data[part] = {
                    'roll': roll,
                    'upg': upg,
                    'corrupted': bool(corrupted)
                }

            else:  # l-команды
                if idx >= len(decoded):
                    break

                flags = decoded[idx]
                has_two = bool(flags & 1)
                idx += 1

                if has_two:
                    if idx + 4 >= len(decoded):
                        break
                    r1, r2, u1, u2 = decoded[idx:idx + 4]
                    c_packed = decoded[idx + 4]
                    idx += 5
                    c1, c2 = (c_packed >> 1) & 1, c_packed & 1

                    armor_data[part] = {
                        'roll1': r1, 'roll2': r2,
                        'upg1': u1, 'upg2': u2,
                        'corrupted1': bool(c1), 'corrupted2': bool(c2),
                        'has_two_rolls': True
                    }
                else:
                    if idx + 3 >= len(decoded):
                        break
                    r1, u1, u2 = decoded[idx:idx + 3]
                    c_packed = decoded[idx + 3]
                    idx += 4
                    c1, c2 = (c_packed >> 1) & 1, c_packed & 1

                    armor_data[part] = {
                        'roll1': r1, 'roll2': r1,
                        'upg1': u1, 'upg2': u2,
                        'corrupted1': bool(c1), 'corrupted2': bool(c2),
                        'has_two_rolls': False
                    }
        except Exception:
            continue

    return armor_data

# --- АНАЛИЗ ОРУЖИЯ И ОБРАБОТЧИК "ДА" ---

class FilterSmartDa(filters.UpdateFilter):
    def filter(self, update):
        if not update.message or not update.message.text:
            return False
        text = unicodedata.normalize('NFKC', update.message.text)
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
        "Чехарда": 10, "MUDA": 1, "Балда": 10
    }
    # Прямые ссылки на изображения
    photo_urls = {
        "Пизда": "https://sun9-48.userapi.com/impg/c844418/v844418142/4f7ef/wk7pnm_dqkY.jpg?size=487x487&quality=96&sign=29e3dacedac2c03eaa320ee2403f8624&type=album ",
        "MUDA": "https://www.meme-arsenal.com/memes/e580d8c1ac6e6a7bc1c623bd7ab80dce.jpg ",
        "Джигурда": "https://www.meme-arsenal.com/memes/03c918ccc821b8172f09c38ded2b8d57.jpg ",
        "Балда": "https://www.meme-arsenal.com/memes/b5896035badfb0387000474e6526488c.jpg"
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


def generate_armor_part_page(item_info: dict, armor_data: dict, command: str, part: str) -> str:
    """Универсальная Total страница для брони (!fz, !wfz, !lfz и т.д.)"""
    part_names = {'helm': 'Шлем', 'chest': 'Нагрудник', 'legs': 'Штаны'}
    part_keys = {'helm': 'Helmet', 'chest': 'Chestplate', 'legs': 'Leggings'}

    data = armor_data.get(part)
    if not data:
        return "❌ Нет данных для этой части брони"

    part_key = part_keys[part]
    base_stats = item_info['stats'][part_key]
    part_name = part_names[part]
    armor_name = item_info['name']

    # === РАСЧЁТ TOTAL HP (если все 3 части заполнены) ===
    total_hp_all_parts = None
    if all(armor_data.values()):
        total_hp_all_parts = 0
        for p in ['helm', 'chest', 'legs']:
            d = armor_data[p]
            pk = part_keys[p]
            bs = item_info['stats'][pk]

            if command in ['fz', 'z', 'hk', 'k']:
                # Анализ - используем hp напрямую
                total_hp_all_parts += d['hp']
            elif command in ['wfz', 'wz', 'whk', 'wk']:
                # Прогноз - используем roll
                base_hp_p = bs[d['roll']]
                total_hp_all_parts += calculate_armor_stat_at_level(base_hp_p, d['upg'], d['corrupted'], 1.0, "armor")
            else:  # l-команды
                use_roll = d.get('roll2', d.get('roll1', 1))
                base_hp_p = bs[use_roll]
                total_hp_all_parts += calculate_armor_stat_at_level(base_hp_p, d['upg2'], d['corrupted2'], 1.0, "armor")

    # Формируем строку TOTAL HP для вставки
    total_hp_line = f"<b>TOTAL HP:</b> <i>{int(total_hp_all_parts):,}</i> ❤️" if total_hp_all_parts is not None else ""
    total_hp_str = f"{total_hp_line}\n\n" if total_hp_all_parts is not None else "\n"

    # === АНАЛИЗ ТЕКУЩЕГО (!fz, !z, !hk, !k) ===
    if command in ['fz', 'z', 'hk', 'k']:
        hp = data['hp']
        upg = data['upg']
        corrupted = data['corrupted']

        roll = find_roll_for_armor(base_stats, hp, upg, corrupted)
        base_hp = base_stats[roll]

        spent = calculate_gold(upg)
        total_needed = calculate_gold(item_info['max_level'])
        remaining = max(0, total_needed - spent)

        max_lvl = item_info['max_level']
        return (
            f"📊 <b>Анализ {armor_name} — {part_name}</b> 🛡️\n\n"
            f"<b>ROLL:</b> <i>{roll}/11</i> | <b>BASE HP:</b> <i>{base_hp:,.2f}</i>\n\n"
            f"<b>HP:</b> <i>{int(hp):,}</i> ❤️\n"
            f"{total_hp_str}"
            f"<b>Corrupted:</b> <i>{'Да' if corrupted else 'Нет'}</i>\n"
            f"<b>Upgrade:</b> <i>{upg}/{max_lvl}</i>\n\n"
            f"<b>💰 ЗОЛОТО 💰</b>\n"
            f"<i>       Потрачено:</i> <b>{spent:,}</b>\n"
            f"<i>       Осталось:</i> <b>{remaining:,}</b> до {max_lvl} уровня"
        )

    # === ПРОГНОЗ (!wfz, !wz, !whk, !wk) ===
    elif command in ['wfz', 'wz', 'whk', 'wk']:
        roll = data['roll']
        upg = data['upg']
        corrupted = data['corrupted']

        base_hp = base_stats[roll]
        hp_at_target = calculate_armor_stat_at_level(base_hp, upg, corrupted, 1.0, "armor")

        max_lvl = item_info['max_level']
        if upg >= max_lvl:
            gold_needed = 0
        else:
            gold_needed = calculate_gold(upg)

        return (
            f"📊 <b>Прогноз {armor_name} — {part_name}</b> 🛡️\n\n"
            f"<b>ROLL:</b> <i>{roll}/11</i> | <b>BASE HP:</b> <i>{base_hp:,.2f}</i>\n\n"
            f"<b>HP:</b> <i>{int(hp_at_target):,}</i> ❤️\n"
            f"{total_hp_str}"
            f"<b>Corrupted:</b> <i>{'Да' if corrupted else 'Нет'}</i>\n"
            f"<b>Upgrade:</b> <i>{upg}/{max_lvl}</i>\n\n"
            f"<b>💰 ЗОЛОТО 💰</b>\n"
            f"<i>       Нужно:</i> <b>{gold_needed:,}</b> до {upg} уровня"
        )

    # === СРАВНЕНИЕ (!lfz, !lz, !lhk, !lk) ===
    elif command in ['lfz', 'lz', 'lhk', 'lk']:
        roll1 = data['roll1']
        roll2 = data['roll2']
        upg1 = data['upg1']
        corrupted1 = data['corrupted1']
        upg2 = data['upg2']
        corrupted2 = data['corrupted2']
        has_two_rolls = data.get('has_two_rolls', False)

        base_hp1 = base_stats[roll1]
        base_hp2 = base_stats[roll2] if has_two_rolls else base_hp1

        curr_hp = calculate_armor_stat_at_level(base_hp1, upg1, corrupted1, 1.0, "armor")
        des_hp = calculate_armor_stat_at_level(base_hp2, upg2, corrupted2, 1.0, "armor")

        max_lvl = item_info['max_level']

        # 🔧 ИСПРАВЛЕНО: Расчёт золота в одном месте с проверкой max уровня
        curr_spent = calculate_gold(upg1)

        # Если upg2 >= max_lvl — считаем как полную стоимость до максимума
        if upg2 >= max_lvl:
            des_gold = calculate_gold(max_lvl)
        else:
            des_gold = calculate_gold(upg2)

        # Дополнительное золото только для одного ролла
        add_gold = 0
        if not has_two_rolls:
            add_gold = max(0, des_gold - curr_spent)

        # Для двух роллов - считаем отдельно для каждого
        if has_two_rolls:
            # Ролл 1: текущее состояние
            spent_roll1 = curr_spent
            remaining_roll1 = max(0, calculate_gold(max_lvl) - spent_roll1)

            # Ролл 2: желаемое состояние
            spent_roll2 = des_gold
            remaining_roll2 = max(0, calculate_gold(max_lvl) - spent_roll2)

        upg_diff = upg2 - upg1
        hp_diff = des_hp - curr_hp
        hp_sign = "+" if hp_diff >= 0 else ""
        pct_sign = "+" if hp_diff >= 0 else ""

        # Текст для corrupted
        corr_diff_text = ""
        if not corrupted1 and corrupted2:
            corr_diff_text = " (активируется)"
        elif corrupted1 and not corrupted2:
            corr_diff_text = " ❌ (невозможно)"

        # Заголовок в зависимости от режима
        if has_two_rolls:
            title = f"📊 <b>Сравнение {armor_name} — {part_name}</b>"
            roll_text = f"{roll1}/11 → {roll2}/11"
            diff_base_hp = base_hp2 - base_hp1
            base_text = f"{base_hp1:,.2f} → {base_hp2:,.2f} (+{diff_base_hp:,.2f})"
        else:
            title = f"📊 <b>Сравнение {armor_name} — {part_name}</b>"
            roll_text = f"{roll1}/11"
            base_text = f"{base_hp1:,.2f}"

        result = (
            f"{title}\n\n"
            f"<b>ROLL:</b> <i>{roll_text}</i> | <b>BASE HP:</b> <i>{base_text}</i>\n\n"
            f"<b>HP:</b> <i>{int(curr_hp):,} ❤️</i> ➜ <i>{int(des_hp):,} ❤️ ({hp_sign}{(hp_diff):,.2f}) ({pct_sign}{hp_diff / curr_hp * 100:.1f}%)</i>\n"
            f"{total_hp_str}"
            f"<b>UPG:</b> <i>{upg1}/{max_lvl}</i> ➜ <i>{upg2}/{max_lvl} (+{upg_diff})</i>\n"
            f"<b>Corrupted:</b> <i>{'Да' if corrupted1 else 'Нет'}</i> ➜ "
            f"<i>{'Да' if corrupted2 else 'Нет'}{corr_diff_text}</i>\n\n"
        )

        # Дополнительное золото только для одного ролла
        if not has_two_rolls:
            result += (
                f"<b>💰 ЗОЛОТО 💰</b>\n"
                f"<i>       Потрачено:</i> <b>{curr_spent:,}</b>\n"
                f"<i>       Осталось:</i> <b>{add_gold:,}</b> до {upg2} уровня"
            )
        else:
            # Для двух роллов - показываем детально для каждого
            result += (
                f"<b>💰 ЗОЛОТО ДЛЯ {roll1} РОЛЛА:</b> 💰\n"
                f"<i>       Потрачено:</i> <b>{spent_roll1:,}</b>\n"
                f"<i>       Осталось:</i> <b>{remaining_roll1:,}</b> до {max_lvl} уровня\n\n"
                f"<b>💰 ЗОЛОТО ДЛЯ {roll2} РОЛЛА:</b> 💰\n"
                f"<i>       Потрачено:</i> <b>{spent_roll2:,}</b>\n"
                f"<i>       Осталось:</i> <b>{remaining_roll2:,}</b> до {max_lvl} уровня"
            )

        return result


def generate_armor_process_page(item_info: dict,
                                armor_data: dict,
                                command: str,
                                part: str,
                                page_type: str = "process") -> str:
    print(f"[PROC_PAGE] Генерация: cmd={command}, part={part}, type={page_type}")

    part_names = {STAGE_HELMET: 'Шлем', STAGE_CHEST: 'Нагрудник', STAGE_LEGS: 'Штаны'}
    part_keys = {STAGE_HELMET: 'Helmet', STAGE_CHEST: 'Chestplate', STAGE_LEGS: 'Leggings'}

    if part not in armor_data or armor_data[part] is None:
        print(f"[PROC_PAGE] ❌ Нет данных для {part}")
        return "❌ Нет данных для этой части брони"

    data = armor_data[part]
    part_key = part_keys[part]
    base_stats = item_info['stats'][part_key]

    print(f"[PROC_PAGE] Данные: {data}")
    print(f"[PROC_PAGE] Part key: {part_key}")

    steps = [f"🧮 <b>Детальные вычисления {item_info['name']} — {part_names[part]}</b>\n"]

    if command in ('fz', 'z', 'hk', 'k') and page_type == "process":
        # Анализ текущего состояния — ОБРАТНЫЙ РАСЧЁТ
        hp = data['hp']
        upg = data['upg']
        corrupted = data['corrupted']

        steps.append(f"<b>1. Финальное HP:</b>")
        steps.append(f"<i>  {hp:,.2f}</i>\n")

        # Убираем Corrupted
        if corrupted:
            steps.append("<b>2. Убираем Corrupted (×1.5):</b>")
            before_corr = hp / 1.5
            steps.append(f"<i>  {hp:,.2f} ÷ 1.50 = {before_corr:,.2f}</i>\n")
        else:
            before_corr = hp
            steps.append("<b>2. Corrupted: Нет (×1.00)</b>\n")

        # Убираем фактор роста
        growth_factor = 1 + 0.047619047619 * upg
        steps.append("<b>3. Расчёт базового HP:</b>")
        steps.append(f"<i>  Фактор роста = 1 + {upg} × 0.047619 = {growth_factor:.10f}</i>")
        inferred_base = before_corr / growth_factor
        steps.append(f"<i>  {before_corr:,.2f} ÷ {growth_factor:.10f} = {inferred_base:,.2f}</i>\n")

        # Находим ролл
        steps.append("<b>4. Определение ролла:</b>")
        steps.append(f"<i>  Инференс: {inferred_base:.2f}</i>")
        steps.append("")

        # Ищем ближайший ролл к inferred_base
        best_roll = 1
        min_diff = float('inf')
        for r in range(1, 12):
            val = base_stats[r]
            diff = abs(val - inferred_base)
            if diff < min_diff:
                min_diff = diff
                best_roll = r

        roll = best_roll
        base_hp = base_stats[roll]

        for r in range(1, 12):
            val = base_stats[r]
            symbol = "←" if r == roll else "  "
            comparison = "&gt;" if val < inferred_base else "&lt;"
            steps.append(f"<i>  {r:2} roll - {val:8,.2f} {comparison} {inferred_base:.2f} {symbol}</i>")

        steps.append("")
        steps.append(f"<b>✓ Выбран ролл:</b> <i>{roll}/11</i>\n")
        steps.append(f"<b>✓ BASE HP:</b> <i>{base_hp:,.2f}</i>")

        print(f"[PROC_PAGE] ✅ Страница сгенерирована, длина: {len(''.join(steps))}")
        return "\n".join(steps)

    elif command in ['wfz', 'wz', 'whk', 'wk']:
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

        steps.append(f"<b>✓ Итоговое HP = {final_hp:,.2f}</b>")
        print(f"[PROC_PAGE] ✅ Страница сгенерирована, длина: {len(''.join(steps))}")
        return "\n".join(steps)


    elif command in ['lfz', 'lz', 'lhk', 'lk']:
        roll1 = data['roll1']
        roll2 = data['roll2']
        upg1 = data['upg1']
        corrupted1 = data['corrupted1']
        upg2 = data['upg2']
        corrupted2 = data['corrupted2']
        has_two_rolls = data.get('has_two_rolls', False)
        base_hp1 = base_stats[roll1]
        base_hp2 = base_stats[roll2] if has_two_rolls else base_hp1

        is_actual = page_type in ["ap", "fp", "fp"]
        is_wished = page_type in ["wp", "sp", "sp"]

        if is_actual:
            display_name = "Текущее состояние" if not has_two_rolls else "1-ая броня"

            display_roll = roll1
            base_hp = base_hp1
            upg = upg1
            corrupted = corrupted1

            steps.append(f"<b>🔸{display_name}</b>\n")
            steps.append(f"<b>1. Базовое HP (ролл {display_roll}):</b>")
            steps.append(f"<i>  {base_hp:,.2f}</i>\n")
            growth_factor = 1 + 0.047619047619 * upg
            base_value = base_hp * growth_factor
            steps.append("<b>2. Применяем фактор роста:</b>")
            steps.append(f"<i>  Фактор = 1 + {upg} × 0.047619 = {growth_factor:.10f}</i>")
            steps.append(f"<i>  {base_hp:,.2f} × {growth_factor:.10f} = {base_value:,.2f}</i>\n")

            if corrupted:
                corr_value = base_value * 1.5
                steps.append("<b>3. Умножаем на Corrupted (×1.5):</b>")
                steps.append(f"<i>  {base_value:,.2f} × 1.50 = {corr_value:,.2f}</i>\n")
                final_hp = corr_value

            else:
                final_hp = base_value
                steps.append("<b>3. Corrupted: Нет (×1.00)</b>\n")
            steps.append(f"<b>✓ Итоговое HP = {final_hp:,.2f}</b>")
            print(f"[PROC_PAGE] ✅ Страница сгенерирована, длина: {len(''.join(steps))}")
            return "\n".join(steps)

        elif is_wished:
            # 🔹 Желаемое состояние (или 2-е оружие при двух роллах)
            display_name = "Желаемое состояние" if not has_two_rolls else "2-ая броня"

            display_roll = roll2
            base_hp = base_hp2
            upg = upg2
            corrupted = corrupted2

            steps.append(f"<b>🔹{display_name}</b>\n")
            steps.append(f"<b>1. Базовое HP (ролл {display_roll}):</b>")
            steps.append(f"<i>  {base_hp:,.2f}</i>\n")
            growth_factor = 1 + 0.047619047619 * upg
            base_value = base_hp * growth_factor
            steps.append("<b>2. Применяем фактор роста:</b>")
            steps.append(f"<i>  Фактор = 1 + {upg} × 0.047619 = {growth_factor:.10f}</i>")
            steps.append(f"<i>  {base_hp:,.2f} × {growth_factor:.10f} = {base_value:,.2f}</i>\n")

            if corrupted:
                corr_value = base_value * 1.5
                steps.append("<b>3. Умножаем на Corrupted (×1.5):</b>")
                steps.append(f"<i>  {base_value:,.2f} × 1.50 = {corr_value:,.2f}</i>\n")
                final_hp = corr_value

            else:
                final_hp = base_value
                steps.append("<b>3. Corrupted: Нет (×1.00)</b>\n")
            steps.append(f"<b>✓ Итоговое HP = {final_hp:,.2f}</b>")
            print(f"[PROC_PAGE] ✅ Страница сгенерирована, длина: {len(''.join(steps))}")
            return "\n".join(steps)


def generate_armor_tablet_page(item_info, armor_data, part):
    """Универсальная Tablet страница для брони"""
    from game_data import UPGRADE_COSTS

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

    for level in range(0, item_info['max_level'] + 1):
        # Стоимость текущего уровня
        level_cost = UPGRADE_COSTS.get(level, 0) if level > 0 else 0

        hp = calculate_armor_stat_at_level(base_hp, level, corrupted, 1.0, "armor")
        rows.append(f"{level:<5} | {level_cost:<11,} | {hp:<12.2f}")

    table_content = "\n".join(rows)
    title_line = f"{item_info['name']} — {part_names[part]} | ROLL {roll}/11 | {'CORRUPTED' if corrupted else 'NORMAL'}"

    clean_name = item_info['name'].replace(' ', '_').replace("'", '').upper()
    block_name = f"{clean_name}_{part_key.upper()}_TABLET"
    return f"```{block_name}\n{title_line}\n\n{table_content}\n```"

def generate_armor_results_keyboard(command: str, armor_data: dict, user_msg_id: int,
                                    current_page: str = "total", current_part: str = None) -> InlineKeyboardMarkup:
    """Генерация клавиатуры с УЛЬТРАКОРОТКИМИ callback"""
    print(f"\n[GEN_KEY] === НОВАЯ ГЕНЕРАЦИЯ ===")
    print(f"[GEN_KEY] cmd={command}, page={current_page}, part={current_part}, msg_id={user_msg_id}")

    buttons = []
    parts_order = ['helm', 'chest', 'legs']
    part_names = {'helm': 'Шлем', 'chest': 'Нагрудник', 'legs': 'Штаны'}

    # Упаковываем данные
    packed_data = pack_armor_data_compact(armor_data, command)

    for part in parts_order:
        if armor_data.get(part) is None:
            print(f"[GEN_KEY] Пропуск {part} - нет данных")
            continue

        part_data = armor_data[part]
        is_current = (part == current_part)

        # Определяем has_two_rolls
        has_two_rolls = False
        if command in ['lfz', 'lz', 'lhk', 'lk']:
            has_two_rolls = part_data.get('has_two_rolls', False) or \
                            (part_data.get('roll1') != part_data.get('roll2'))

        print(f"[GEN_KEY] {part}: current={is_current}, two_rolls={has_two_rolls}")

        # Формируем кнопки
        part_buttons = []

        # Total всегда есть
        total_text = f"{'✓ ' if is_current and current_page == 'total' else ''}{part_names[part]} Total"
        # КОРОТКИЙ callback: a:lhk:helm:t:2024:packed
        cb_total = f"a:{command}:{part}:t:{user_msg_id}:{packed_data}"
        part_buttons.append(InlineKeyboardButton(total_text, callback_data=cb_total))
        print(f"[GEN_KEY] Total callback: {len(cb_total.encode('utf-8'))} bytes")

        if command in ['fz', 'z', 'hk', 'k']:
            # Анализ - Process и Tablet
            proc_text = f"{'✓ ' if is_current and current_page == 'process' else ''}< Process"
            tab_text = f"{'✓ ' if is_current and current_page == 'tablet' else ''}< Tablet"

            cb_proc = f"a:{command}:{part}:p:{user_msg_id}:{packed_data}"
            cb_tab = f"a:{command}:{part}:b:{user_msg_id}:{packed_data}"

            part_buttons.append(InlineKeyboardButton(proc_text, callback_data=cb_proc))
            part_buttons.append(InlineKeyboardButton(tab_text, callback_data=cb_tab))

        elif command in ['wfz', 'wz', 'whk', 'wk']:
            # Прогноз - только Process
            proc_text = f"{'✓ ' if is_current and current_page == 'process' else ''}< Process"
            cb_proc = f"a:{command}:{part}:p:{user_msg_id}:{packed_data}"
            part_buttons.append(InlineKeyboardButton(proc_text, callback_data=cb_proc))

        elif command in ['lfz', 'lz', 'lhk', 'lk']:
            # Сравнение - Actual/Wished или 1st/2nd
            if has_two_rolls:
                first_text = f"{'✓ ' if is_current and current_page == 'fp' else ''}< 1st Process"
                second_text = f"{'✓ ' if is_current and current_page == 'sp' else ''}< 2nd Process"

                cb_first = f"a:{command}:{part}:f:{user_msg_id}:{packed_data}"
                cb_second = f"a:{command}:{part}:s:{user_msg_id}:{packed_data}"

                part_buttons.append(InlineKeyboardButton(first_text, callback_data=cb_first))
                part_buttons.append(InlineKeyboardButton(second_text, callback_data=cb_second))
            else:
                actual_text = f"{'✓ ' if is_current and current_page == 'ap' else ''}< Actual Process"
                wished_text = f"{'✓ ' if is_current and current_page == 'wp' else ''}< Wished Process"

                cb_actual = f"a:{command}:{part}:a:{user_msg_id}:{packed_data}"
                cb_wished = f"a:{command}:{part}:w:{user_msg_id}:{packed_data}"

                part_buttons.append(InlineKeyboardButton(actual_text, callback_data=cb_actual))
                part_buttons.append(InlineKeyboardButton(wished_text, callback_data=cb_wished))

        buttons.append(part_buttons)

        # Проверяем размеры
        for btn in part_buttons:
            size = len(btn.callback_data.encode('utf-8'))
            if size > 64:
                print(f"⚠️ ПЕРЕПОЛНЕНИЕ: {size} bytes!")

    # Кнопка закрытия - КОРОТКИЙ формат
    close_cb = f"a:c:::{user_msg_id}"  # c = close
    buttons.append([InlineKeyboardButton("Свернуть", callback_data=close_cb)])

    # Итоговая проверка
    max_size = max(len(btn.callback_data.encode('utf-8'))
                   for row in buttons for btn in row)
    print(f"[GEN_KEY] Макс размер callback: {max_size}/64 bytes")
    print(f"[GEN_KEY] === ГЕНЕРАЦИЯ ЗАВЕРШЕНА ===\n")

    return InlineKeyboardMarkup(buttons)

ARMOR_STATUS_NONE = "none"      # Ничего (серый)
ARMOR_STATUS_EDITING = "editing"  # Редактируется (желтый)
ARMOR_STATUS_SAVED = "saved"      # Записано (зеленый)

# Эмодзи статусов
STATUS_EMOJI = {
    ARMOR_STATUS_NONE: "⚪",
    ARMOR_STATUS_EDITING: "🟡",
    ARMOR_STATUS_SAVED: "🟢"
}

ARMOR_PART_NAMES = {
    STAGE_HELMET: "Шлем",
    STAGE_CHEST: "Нагрудник",
    STAGE_LEGS: "Штаны"
}

ARMOR_COMMAND_NAMES = {
    'fz': 'Furious Zeus Set',
    'z': 'Legendary Zeus Set',
    'hk': 'Heroic Kronax Set',
    'k': 'Kronax Set',
    'wfz': 'Furious Zeus Set',
    'wz': 'Legendary Zeus Set',
    'whk': 'Heroic Kronax Set',
    'wk': 'Kronax Set',
    'lfz': 'Furious Zeus Set',
    'lz': 'Legendary Zeus Set',
    'lhk': 'Heroic Kronax Set',
    'lk': 'Kronax Set'
}

def get_armor_input_prompt(command: str, selected_part: str, max_level: int) -> str:
    """Генерирует текст приглашения для ввода данных брони"""
    armor_name = ARMOR_COMMAND_NAMES.get(command, 'Броня')
    selected_name = ARMOR_PART_NAMES.get(selected_part, 'Неизвестно')

    text = f"🛡️ <b>Ввод данных для брони — {armor_name}</b>\n\n"
    text += f"Выберите часть брони: <b>{selected_name}</b>\n\n"
    text += "<b>ВВОДИТЕ АРГУМЕНТЫ БЕЗ ВВОДА КОМАНДЫ ПО НОВОЙ</b>\n"
    text += "<i>Пример написания:</i>\n\n"

    # Примеры ввода в зависимости от команды и части
    examples = {
        'fz': {
            STAGE_HELMET: "<b>{hp} {upg} {y/n}</b>\n<i>(3279 32 y)</i>",
            STAGE_CHEST: "<b>{hp} {upg} {y/n}</b>\n<i>(2895 31 y)</i>",
            STAGE_LEGS: "<b>{hp} {upg} {y/n}</b>\n<i>(2788 31 y)</i>"
        },
        'z': {
            STAGE_HELMET: "<b>{hp} {upg} {y/n}</b>\n<i>(1678 16 y)</i>",
            STAGE_CHEST: "<b>{hp} {upg} {y/n}</b>\n<i>(1006 14 n)</i>",
            STAGE_LEGS: "<b>{hp} {upg} {y/n}</b>\n<i>(2337 26 y)</i>"
        },
        'hk': {
            STAGE_HELMET: "<b>{hp} {upg} {y/n}</b>\n<i>(1131 7 n)</i>",
            STAGE_CHEST: "<b>{hp} {upg} {y/n}</b>\n<i>(3370 32 y)</i>",
            STAGE_LEGS: "<b>{hp} {upg} {y/n}</b>\n<i>(2574 18 y)</i>"
        },
        'k': {
            STAGE_HELMET: "<b>{hp} {upg} {y/n}</b>\n<i>(1226 9 n)</i>",
            STAGE_CHEST: "<b>{hp} {upg} {y/n}</b>\n<i>(1500 19 n)</i>",
            STAGE_LEGS: "<b>{hp} {upg} {y/n}</b>\n<i>(2639 25 y)</i>"
        },
        'wfz': {
            STAGE_HELMET: "<b>{roll} > {upg} {y/n}</b>\n<i>(6 > 21 n)</i>",
            STAGE_CHEST: "<b>{roll} > {upg} {y/n}</b>\n<i>(7 > 32 y)</i>",
            STAGE_LEGS: "<b>{roll} > {upg} {y/n}</b>\n<i>(11 > 45 y)</i>"
        },
        'wz': {
            STAGE_HELMET: "<b>{roll} > {upg} {y/n}</b>\n<i>(6 > 21 n)</i>",
            STAGE_CHEST: "<b>{roll} > {upg} {y/n}</b>\n<i>(7 > 32 y)</i>",
            STAGE_LEGS: "<b>{roll} > {upg} {y/n}</b>\n<i>(11 > 34 y)</i>"
        },
        'whk': {
            STAGE_HELMET: "<b>{roll} > {upg} {y/n}</b>\n<i>(6 > 21 n)</i>",
            STAGE_CHEST: "<b>{roll} > {upg} {y/n}</b>\n<i>(7 > 32 y)</i>",
            STAGE_LEGS: "<b>{roll} > {upg} {y/n}</b>\n<i>(11 > 44 y)</i>"
        },
        'wk': {
            STAGE_HELMET: "<b>{roll} > {upg} {y/n}</b>\n<i>(6 > 21 n)</i>",
            STAGE_CHEST: "<b>{roll} > {upg} {y/n}</b>\n<i>(7 > 32 y)</i>",
            STAGE_LEGS: "<b>{roll} > {upg} {y/n}</b>\n<i>(11 > 45 y)</i>"
        },
        # === L-КОМАНДЫ: ДВЕ ФОРМУЛЫ ===
        'lfz': {
            STAGE_HELMET: (
                "<b>Формула 1 (один ролл):</b>\n"
                "<code>{roll} - {upg1} {y/n1} > {upg2} {y/n2}</code>\n"
                "<i>Пример: 8 - 21 n > 45 y</i>\n\n"
                "<b>Формула 2 (два ролла):</b>\n"
                "<b>{roll1} > {roll2} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 6 > 8 - 21 n > 45 y</i>"
            ),
            STAGE_CHEST: (
                "<b>Формула 1 (один ролл):</b>\n"
                "<code>{roll} - {upg1} {y/n1} > {upg2} {y/n2}</code>\n"
                "<i>Пример: 1 - 35 y > 40 y</i>\n\n"
                "<b>Формула 2 (два ролла):</b>\n"
                "<b>{roll1} > {roll2} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 1 > 11 - 35 y > 40 y</i>"
            ),
            STAGE_LEGS: (
                "<b>Формула 1 (один ролл):</b>\n"
                "<code>{roll} - {upg1} {y/n1} > {upg2} {y/n2}</code>\n"
                "<i>Пример: 11 - 40 y > 45 y</i>\n\n"
                "<b>Формула 2 (два ролла):</b>\n"
                "<b>{roll1} > {roll2} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 6 > 11 - 40 y > 45 y</i>"
            )
        },
        'lz': {
            STAGE_HELMET: (
                "<b>Формула 1 (один ролл):</b>\n"
                "<code>{roll} - {upg1} {y/n1} > {upg2} {y/n2}</code>\n"
                "<i>Пример: 8 - 21 n > 34 y</i>\n\n"
                "<b>Формула 2 (два ролла):</b>\n"
                "<b>{roll1} > {roll2} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 6 > 8 - 21 n > 34 y</i>"
            ),
            STAGE_CHEST: (
                "<b>Формула 1 (один ролл):</b>\n"
                "<b>{roll} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 1 - 23 y > 30 y</i>\n\n"
                "<b>Формула 2 (два ролла):</b>\n"
                "<b>{roll1} > {roll2} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 1 > 11 - 32 y > 34 y</i>"
            ),
            STAGE_LEGS: (
                "<b>Формула 1 (один ролл):</b>\n"
                "<b>{roll} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 11 - 12 n > 28 y</i>\n\n"
                "<b>Формула 2 (два ролла):</b>\n"
                "<b>{roll1} > {roll2} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 6 > 11 - 15 n > 25 y</i>"
            )
        },
        'lhk': {
            STAGE_HELMET: (
                "<b>Формула 1 (один ролл):</b>\n"
                "<b>{roll} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 8 - 21 n > 44 y</i>\n\n"
                "<b>Формула 2 (два ролла):</b>\n"
                "<b>{roll1} > {roll2} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 6 > 8 - 21 n > 44 y</i>"
            ),
            STAGE_CHEST: (
                "<b>Формула 1 (один ролл):</b>\n"
                "<b>{roll} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 1 - 35 y > 40 y</i>\n\n"
                "<b>Формула 2 (два ролла):</b>\n"
                "<b>{roll1} > {roll2} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 1 > 11 - 35 y > 40 y</i>"
            ),
            STAGE_LEGS: (
                "<b>Формула 1 (один ролл):</b>\n"
                "<b>{roll} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 11 - 40 y > 44 y</i>\n\n"
                "<b>Формула 2 (два ролла):</b>\n"
                "<b>{roll1} > {roll2} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 6 > 11 - 40 y > 44 y</i>"
            )
        },
        'lk': {
            STAGE_HELMET: (
                "<b>Формула 1 (один ролл):</b>\n"
                "<b>{roll} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 8 - 21 n > 45 y</i>\n\n"
                "<b>Формула 2 (два ролла):</b>\n"
                "<b>{roll1} > {roll2} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 6 > 8 - 21 n > 45 y</i>"
            ),
            STAGE_CHEST: (
                "<b>Формула 1 (один ролл):</b>\n"
                "<b>{roll} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 1 - 35 y > 40 y</i>\n\n"
                "<b>Формула 2 (два ролла):</b>\n"
                "<b>{roll1} > {roll2} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 1 > 11 - 35 y > 40 y</i>"
            ),
            STAGE_LEGS: (
                "<b>Формула 1 (один ролл):</b>\n"
                "<b>{roll} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 11 - 40 y > 45 y</i>\n\n"
                "<b>Формула 2 (два ролла):</b>\n"
                "<b>{roll1} > {roll2} - {upg1} {y/n1} > {upg2} {y/n2}</b>\n"
                "<i>Пример: 6 > 11 - 40 y > 45 y</i>"
            )
        }
    }

    example_text = examples.get(command, {}).get(selected_part, "<b>{данные}</b>")
    text += example_text

    # Добавляем условности
    if command in ['fz', 'z', 'hk', 'k']:
        text += f"\n\n<i>Ролл определяется автоматически</i>"
        text += f"\n<i>Макс. уровень: {max_level}</i>"
    elif command in ['wfz', 'wz', 'whk', 'wk']:
        text += f"\n\n<i>Диапазон роллов: 1-11</i>"
        text += f"\n<i>Макс. уровень: {max_level}</i>"
    elif command in ['lfz', 'lz', 'lhk', 'lk']:
        text += f"\n\n<b>⚠️ Важно:</b>"
        text += f"\n<i>• Диапазон роллов: 1-11</i>"
        text += f"\n<i>• Макс. уровень: {max_level}</i>"
        text += f"\n\n<b>Ограничения для одного ролла:</b>"
        text += f"\n<i>• Нельзя декорраптить (y → n)</i>"
        text += f"\n<i>• Нельзя upg2 должен быть больше upg1</i>"
        text += f"\n<i>• Два ролла = разные предметы, ограничения сняты</i>"

    return text


def get_armor_parts_keyboard(command: str, user_id: int, selected_part: str = None) -> InlineKeyboardMarkup:
    """Генерирует клавиатуру выбора частей брони"""
    if user_id not in user_armor_data:
        return None

    user_data = user_armor_data[user_id]
    parts_status = user_data.get('parts_status', {
        STAGE_HELMET: ARMOR_STATUS_NONE,
        STAGE_CHEST: ARMOR_STATUS_NONE,
        STAGE_LEGS: ARMOR_STATUS_NONE
    })

    buttons = []

    # Кнопки частей брони
    for part in [STAGE_HELMET, STAGE_CHEST, STAGE_LEGS]:
        part_name = ARMOR_PART_NAMES[part]
        status = parts_status.get(part, ARMOR_STATUS_NONE)

        # Если эта часть сейчас выбрана — показываем как редактируется
        if selected_part == part:
            display_status = ARMOR_STATUS_EDITING
            display_text = f"{STATUS_EMOJI[display_status]} {part_name} [Редактируется]"
        else:
            display_status = status
            if status == ARMOR_STATUS_NONE:
                display_text = f"{STATUS_EMOJI[display_status]} {part_name} [Ничего]"
            elif status == ARMOR_STATUS_SAVED:
                display_text = f"{STATUS_EMOJI[display_status]} {part_name} [Записано]"
            else:
                display_text = f"{STATUS_EMOJI[display_status]} {part_name} [Редактируется]"

        callback_data = f"armor_part:{part}:{user_id}"
        buttons.append([InlineKeyboardButton(display_text, callback_data=callback_data)])

    # Кнопки управления
    control_buttons = []
    control_buttons.append(InlineKeyboardButton("✅ Завершить", callback_data=f"armor_finish:{user_id}"))
    control_buttons.append(InlineKeyboardButton("❌ Отменить", callback_data=f"armor_cancel:{user_id}"))
    buttons.append(control_buttons)

    return InlineKeyboardMarkup(buttons)


async def handle_armor_command(update: Update, context: ContextTypes.DEFAULT_TYPE, command: str):
    """Обработчик команд брони (!fz, !z, !hk, !k, !wfz, и т.д.)"""
    if not is_allowed_thread(update):
        return

    user_id = update.effective_user.id

    # Проверка на активную сессию
    if user_id in user_armor_data:
        error_message = "🛑 **Вы уже начали сессию ввода данных для брони.**\n"
        error_message += "Закончите текущую сессию, нажав «Завершить» или «Отменить»."
        if await _send_error(update, context, error_message, ""):
            return

    # Определяем item_key
    item_key_map = {
        'fz': 'fzh', 'wfz': 'fzh', 'lfz': 'fzh',
        'z': 'lzs', 'wz': 'lzs', 'lz': 'lzs',
        'hk': 'hks', 'whk': 'hks', 'lhk': 'hks',
        'k': 'ks', 'wk': 'ks', 'lk': 'ks',
    }
    item_key = item_key_map.get(command, 'fzh')
    item_info = ITEMS_MAPPING[item_key]
    max_level = item_info['max_level']

    # Инициализируем данные пользователя
    user_armor_data[user_id] = {
        'command': command,
        'data': {STAGE_HELMET: None, STAGE_CHEST: None, STAGE_LEGS: None},
        'parts_status': {STAGE_HELMET: ARMOR_STATUS_NONE, STAGE_CHEST: ARMOR_STATUS_NONE,
                         STAGE_LEGS: ARMOR_STATUS_NONE},
        'selected_part': None,  # Ничего не выбрано изначально
        'item_key': item_key,
        'max_level': max_level,
        'user_msg_id': update.message.message_id,
        'chat_id': update.effective_chat.id,
        'thread_id': update.effective_message.message_thread_id,
        'bot_msg_id': None
    }

    # Отправляем начальное сообщение (ничего не выбрано)
    armor_name = ARMOR_COMMAND_NAMES.get(command, 'Броня')
    text = f"🛡️ <b>Ввод данных для брони — {armor_name}</b>\n\n"
    text += "Выберите часть брони: <b>Ничего</b>\n\n"
    text += "Нажмите на часть брони, чтобы ввести для неё данные."

    keyboard = get_armor_parts_keyboard(command, user_id, None)

    bot_msg = await update.message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        reply_to_message_id=update.message.message_id
    )

    user_armor_data[user_id]['bot_msg_id'] = bot_msg.message_id


async def armor_part_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора части брони"""
    query = update.callback_query
    await query.answer()

    if not is_allowed_thread(update):
        return

    # Парсим callback_data: armor_part:{part}:{user_id}
    data_parts = query.data.split(":")
    if len(data_parts) != 3:
        return

    part = data_parts[1]
    user_id = int(data_parts[2])

    # Проверка владельца
    if user_id != update.effective_user.id:
        await query.answer("Это не ваша сессия!", show_alert=True)
        return

    if user_id not in user_armor_data:
        await query.answer("Сессия устарела", show_alert=True)
        return

    user_data = user_armor_data[user_id]
    command = user_data['command']
    max_level = user_data['max_level']

    # Устанавливаем выбранную часть
    user_data['selected_part'] = part

    # Генерируем приглашение для ввода
    text = get_armor_input_prompt(command, part, max_level)
    keyboard = get_armor_parts_keyboard(command, user_id, part)

    try:
        await query.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        print(f"Ошибка при редактировании сообщения брони: {e}")


async def armor_finish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатия Завершить"""
    query = update.callback_query
    await query.answer()

    if not is_allowed_thread(update):
        return

    # Парсим callback_data: armor_finish:{user_id}
    data_parts = query.data.split(":")
    if len(data_parts) != 2:
        return

    user_id = int(data_parts[1])

    # Проверка владельца
    if user_id != update.effective_user.id:
        await query.answer("Это не ваша сессия!", show_alert=True)
        return

    if user_id not in user_armor_data:
        await query.answer("Сессия уже завершена", show_alert=True)
        return

    user_data = user_armor_data[user_id]
    armor_data = user_data['data']

    # Проверяем, записана ли хотя бы одна часть
    has_any_data = any(armor_data[part] is not None for part in [STAGE_HELMET, STAGE_CHEST, STAGE_LEGS])

    # === КРИТИЧНО: Гарантируем удаление сессии в любом случае ===
    try:
        if not has_any_data:
            # СНАЧАЛА отправляем гневное сообщение как ОТВЕТ на команду пользователя
            insults = [
                "Ну и, что ты решил делать? Ты нихуя не написал, пиши команду заново!",
                "Нету данных - нет конфетки, пошёл нахуй! Если тебе не надо ещё раз писать ебаную команду",
                "Ахахаххаах, ебать. Пиши заново, ебанько) Без данных тебя даже в дурку не примут",
                "Еблан, ты вкурсе что ты нихуя не ввёл нигде? Пиши заново, блять",
                "ЧМО ЕБАНОЕ, НАХУЙ ЕБЁШЬ МОЗГИ? ТЫ ВСЁ СКИПНУЛ НИХУЯ НЕ НАПИСАВ И РАДИ ЧЕГО? ЗАНОВО!",
                "Я бы желал вам, месье, дать по еблищу, но мне жаль, что я цифровая моделька. Имейте совесть, не ебите мозг даже мне, и админу. Если вам ненадо вводить, не пишите ебаную команду, сука!",
                "Это что-то типа: \"ХУЕСОСЫ ЕБАНЫЕ! О, кнопка Завершить\" Уёбок. Пиши заново"
            ]

            try:
                insult_msg = await context.bot.send_message(
                    chat_id=user_data['chat_id'],
                    message_thread_id=user_data.get('thread_id'),
                    text=random.choice(insults),
                    reply_to_message_id=user_data['user_msg_id']  # ОТВЕТ на команду
                )

                # ТЕПЕРЬ удаляем сообщения: сначала бота, потом пользователя
                try:
                    await query.message.delete()  # Сообщение бота с кнопками
                except:
                    pass

                try:
                    await context.bot.delete_message(
                        chat_id=user_data['chat_id'],
                        message_id=user_data['user_msg_id']  # Команда пользователя
                    )
                except:
                    pass

                # Удаляем гневное сообщение через 5 секунд
                async def delete_insult_after_delay():
                    await asyncio.sleep(5)
                    try:
                        await context.bot.delete_message(
                            chat_id=user_data['chat_id'],
                            message_id=insult_msg.message_id
                        )
                    except:
                        pass

                asyncio.create_task(delete_insult_after_delay())

            except Exception as e:
                print(f"Не удалось отправить гневное сообщение: {e}")
                # Если не получилось отправить ответ, просто удаляем сообщение бота
                try:
                    await query.message.delete()
                except:
                    pass

        else:
            # Генерируем результаты
            await generate_armor_results(update, context, user_id, from_callback=True)

    except Exception as e:
        print(f"Ошибка в armor_finish_callback: {e}")
        import traceback
        traceback.print_exc()
        try:
            await query.message.reply_text("❌ Произошла ошибка при обработке.")
        except:
            pass
    finally:
        # ГАРАНТИРОВАННО удаляем сессию
        if user_id in user_armor_data:
            del user_armor_data[user_id]

async def armor_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатия Отменить"""
    query = update.callback_query
    await query.answer()

    # Парсим callback_data: armor_cancel:{user_id}
    data_parts = query.data.split(":")
    if len(data_parts) != 2:
        return

    user_id = int(data_parts[1])

    # Проверка владельца
    if user_id != update.effective_user.id:
        await query.answer("Это не ваша сессия!", show_alert=True)
        return

    if user_id not in user_armor_data:
        await query.answer("Сессия уже завершена", show_alert=True)
        return

    user_data = user_armor_data[user_id]

    # Удаляем сообщения
    try:
        await query.message.delete()
        await context.bot.delete_message(
            chat_id=user_data['chat_id'],
            message_id=user_data['user_msg_id']
        )
    except:
        pass

    del user_armor_data[user_id]


async def handle_armor_command(update: Update, context: ContextTypes.DEFAULT_TYPE, command: str):
    """Обработчик команд брони (!fz, !z, !hk, !k, !wfz, и т.д.)"""
    if not is_allowed_thread(update):
        return

    user_id = update.effective_user.id

    # Проверка на активную сессию
    if user_id in user_armor_data:
        user_data = user_armor_data[user_id]
        error_message = "🛑 **Вы уже начали сессию ввода данных для брони.**\n"
        error_message += "Закончите текущую сессию, нажав «Завершить» или «Отменить»."

        # Удаляем сообщение пользователя (новую команду)
        try:
            await update.message.delete()
        except Exception:
            pass

        # Отправляем ошибку как reply на сообщение бота с активной сессией
        try:
            msg = await context.bot.send_message(
                chat_id=user_data['chat_id'],
                message_thread_id=user_data.get('thread_id'),
                text=error_message,
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=user_data['bot_msg_id']  # Ответ на сессию бота
            )

            # Удаляем сообщение об ошибке через 3 секунды
            async def delete_error_after_delay():
                await asyncio.sleep(3)
                try:
                    await msg.delete()
                except:
                    pass

            asyncio.create_task(delete_error_after_delay())

        except Exception as e:
            print(f"Ошибка при отправке сообщения о сессии: {e}")
        return

    # Определяем item_key
    item_key_map = {
        'fz': 'fzh', 'wfz': 'fzh', 'lfz': 'fzh',
        'z': 'lzs', 'wz': 'lzs', 'lz': 'lzs',
        'hk': 'hks', 'whk': 'hks', 'lhk': 'hks',
        'k': 'ks', 'wk': 'ks', 'lk': 'ks',
    }
    item_key = item_key_map.get(command, 'fzh')
    item_info = ITEMS_MAPPING[item_key]
    max_level = item_info['max_level']

    # Инициализируем данные пользователя
    user_armor_data[user_id] = {
        'command': command,
        'data': {STAGE_HELMET: None, STAGE_CHEST: None, STAGE_LEGS: None},
        'parts_status': {STAGE_HELMET: ARMOR_STATUS_NONE, STAGE_CHEST: ARMOR_STATUS_NONE,
                         STAGE_LEGS: ARMOR_STATUS_NONE},
        'selected_part': None,  # Ничего не выбрано изначально
        'item_key': item_key,
        'max_level': max_level,
        'user_msg_id': update.message.message_id,
        'chat_id': update.effective_chat.id,
        'bot_msg_id': None
    }

    # Отправляем начальное сообщение (ничего не выбрано)
    armor_name = ARMOR_COMMAND_NAMES.get(command, 'Броня')
    text = f"🛡️ <b>Ввод данных для брони — {armor_name}</b>\n\n"
    text += "Выберите часть брони: <b>Ничего</b>\n\n"
    text += "Нажмите на часть брони, чтобы ввести для неё данные."

    keyboard = get_armor_parts_keyboard(command, user_id, None)

    bot_msg = await update.message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        reply_to_message_id=update.message.message_id
    )

    user_armor_data[user_id]['bot_msg_id'] = bot_msg.message_id


async def handle_armor_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ввода данных пользователем"""
    # ИСПРАВЛЕНО: убран неверный global, используем правильную переменную _error_msgs
    # global _err_queue  ← УДАЛИТЬ ЭТО

    if not is_allowed_thread(update):
        return

    text = update.message.text.strip()
    if text.startswith('!'):
        return  # Пусть bang_router разбирается

    user_id = update.effective_user.id
    if user_id not in user_armor_data:
        return  # Не наш диалог — игнорируем

    user_data = user_armor_data[user_id]

    # Проверяем, выбрана ли часть для редактирования
    selected_part = user_data.get('selected_part')
    if not selected_part:
        # Ничего не выбрано — игнорируем или показываем подсказку
        return

    command = user_data['command']
    max_level = user_data['max_level']
    parts = text.split()

    # Валидация в зависимости от типа команды
    errors = []
    stage_data = None

    if command in ('fz', 'z', 'hk', 'k'):
        if len(parts) != 3:
            errors.append(f"❌ Неверное количество аргументов ({len(parts)}). Ожидается 3.")
        else:
            try:
                hp = float(parts[0])
            except ValueError:
                errors.append(f"❌ HP ({parts[0]}) должен быть числом.")
            try:
                upg = int(parts[1])
                if not 0 <= upg <= max_level:
                    errors.append(f"❌ UPG ({upg}) должен быть в диапазоне 0-{max_level}.")
            except ValueError:
                errors.append(f"❌ UPG ({parts[1]}) должен быть числом.")
            if parts[2].lower() not in ('y', 'n'):
                errors.append(f"❌ Corrupted ({parts[2]}) должен быть 'y' или 'n'.")

            if not errors:
                stage_data = {
                    'hp': float(parts[0]),
                    'upg': int(parts[1]),
                    'corrupted': parts[2].lower() == 'y'
                }

    elif command in ('wfz', 'wz', 'whk', 'wk'):
        if len(parts) != 4 or parts[1] != '>':
            errors.append("❌ Неверный формат. Ожидается: {roll} > {upg} {y/n}")
        else:
            try:
                roll = int(parts[0])
                if not 1 <= roll <= 11:
                    errors.append(f"❌ Roll ({roll}) должен быть в диапазоне 1-11.")
            except ValueError:
                errors.append(f"❌ Roll ({parts[0]}) должен быть числом.")
            try:
                upg = int(parts[2])
                if not 0 <= upg <= max_level:
                    errors.append(f"❌ UPG ({upg}) должен быть в диапазоне 0-{max_level}.")
            except ValueError:
                errors.append(f"❌ UPG ({parts[2]}) должен быть числом.")
            if parts[3].lower() not in ('y', 'n'):
                errors.append(f"❌ Corrupted ({parts[3]}) должен быть 'y' или 'n'.")

            if not errors:
                stage_data = {
                    'roll': int(parts[0]),
                    'upg': int(parts[2]),
                    'corrupted': parts[3].lower() == 'y'
                }

    elif command in ('lfz', 'lz', 'lhk', 'lk'):
        # Ищем позиции разделителей
        minus_idx = -1
        first_gt_idx = -1
        second_gt_idx = -1

        for idx, arg in enumerate(parts):
            if arg == '-' and minus_idx == -1:
                minus_idx = idx
            elif arg == '>':
                if first_gt_idx == -1:
                    first_gt_idx = idx
                elif second_gt_idx == -1:
                    second_gt_idx = idx
        # Определяем режим
        has_two_rolls = False
        # Если первый разделитель > и после него есть число, и потом -, то это два ролла
        if first_gt_idx != -1 and minus_idx != -1:
            # Проверяем: после первого > должно быть число (roll2)
            if first_gt_idx + 1 < len(parts):
                potential_roll2 = parts[first_gt_idx + 1]
                try:
                    int(potential_roll2)  # Проверяем, что это число
                    # И после этого числа должен быть -
                    if minus_idx == first_gt_idx + 2:
                        has_two_rolls = True
                except ValueError:
                    pass
        # Если первый разделитель -, то это один ролл
        if minus_idx != -1 and (first_gt_idx == -1 or minus_idx < first_gt_idx):
            has_two_rolls = False
        # Проверяем наличие обязательных разделителей
        if minus_idx == -1:
            errors.append("❌ Обязательный разделитель '-' не найден.")
        if has_two_rolls and second_gt_idx == -1:
            errors.append("❌ Для двух роллов нужен второй разделитель '>'.")
        elif not has_two_rolls and first_gt_idx == -1:
            errors.append("❌ Обязательный разделитель '>' не найден.")

        # === ПАРСИНГ РОЛЛОВ ===
        roll1 = None
        roll2 = None
        if not errors:
            if has_two_rolls:
                # Формат: roll1 > roll2 - upg1 y/n1 > upg2 y/n2
                # roll1 должен быть до первого >
                if first_gt_idx == 0:
                    errors.append("❌ Не указан roll1 до знака >.")
                else:
                    try:
                        roll1 = int(parts[0])
                        if not 1 <= roll1 <= 11:
                            errors.append(f"❌ Roll1 ({roll1}) должен быть в диапазоне 1-11.")
                    except ValueError:
                        errors.append(f"❌ Roll1 ({parts[0]}) должен быть числом.")
                # roll2 между > и -
                try:
                    roll2 = int(parts[first_gt_idx + 1])
                    if not 1 <= roll2 <= 11:
                        errors.append(f"❌ Roll2 ({roll2}) должен быть в диапазоне 1-11.")
                except (ValueError, IndexError):
                    errors.append(f"❌ Roll2 должен быть числом между > и -.")
                # Проверка: roll1 < roll2
                if roll1 is not None and roll2 is not None and roll1 >= roll2:
                    errors.append(f"❌ Roll1 ({roll1}) должен быть меньше Roll2 ({roll2}).")
            else:
                # Формат: roll1 - upg1 y/n1 > upg2 y/n2
                try:
                    roll1 = int(parts[0])
                    if not 1 <= roll1 <= 11:
                        errors.append(f"❌ Roll ({roll1}) должен быть в диапазоне 1-11.")
                    roll2 = roll1  # Один и тот же ролл
                except ValueError:
                    errors.append(f"❌ Roll ({parts[0]}) должен быть числом.")

        # === ПАРСИНГ СОСТОЯНИЙ ===
        if not errors:
            if has_two_rolls:
                # Часть между - и вторым >
                mid_start = minus_idx + 1
                mid_end = second_gt_idx if second_gt_idx != -1 else len(parts)
                mid_part = parts[mid_start:mid_end]
                # Часть после второго >
                right_part = parts[second_gt_idx + 1:] if second_gt_idx != -1 else []
            else:
                # Часть между - и >
                mid_start = minus_idx + 1
                mid_end = first_gt_idx if first_gt_idx != -1 else len(parts)
                mid_part = parts[mid_start:mid_end]
                # Часть после >
                right_part = parts[first_gt_idx + 1:] if first_gt_idx != -1 else []

            # Парсим текущее состояние (mid_part: upg1 y/n1)
            if len(mid_part) != 2:
                errors.append(f"❌ Текущее состояние: ожидается 2 аргумента (upg y/n), получено {len(mid_part)}.")
            else:
                try:
                    upg1 = int(mid_part[0])
                    if not 0 <= upg1 <= max_level:
                        errors.append(f"❌ Текущий уровень ({upg1}) не в 0-{max_level}.")
                except ValueError:
                    errors.append(f"❌ Текущий уровень ({mid_part[0]}) должен быть числом.")
                if mid_part[1].lower() not in ('y', 'n'):
                    errors.append(f"❌ Текущий corrupted ({mid_part[1]}) должен быть 'y' или 'n'.")
                corrupted1 = mid_part[1].lower() == 'y'
            # Парсим желаемое состояние (right_part: upg2 y/n2)
            if len(right_part) != 2:
                errors.append(f"❌ Желаемое состояние: ожидается 2 аргумента (upg y/n), получено {len(right_part)}.")
            else:
                try:
                    upg2 = int(right_part[0])
                    if not 0 <= upg2 <= max_level:
                        errors.append(f"❌ Желаемый уровень ({upg2}) не в 0-{max_level}.")
                except ValueError:
                    errors.append(f"❌ Желаемый уровень ({right_part[0]}) должен быть числом.")
                if right_part[1].lower() not in ('y', 'n'):
                    errors.append(f"❌ Желаемый corrupted ({right_part[1]}) должен быть 'y' или 'n'.")
                corrupted2 = right_part[1].lower() == 'y'

        # === СТРОГИЕ ПРОВЕРКИ ДЛЯ ОДНОГО РОЛЛА ===
        if not errors and not has_two_rolls:
            # 1. Нельзя декорраптить
            if corrupted1 and not corrupted2:
                errors.append("❌ Нельзя декорраптить (y → n запрещено).")
            # 2. Нельзя понижать уровень
            if upg2 < upg1:
                errors.append(f"❌ Нельзя понижать уровень ({upg1} → {upg2} запрещено).")

        # Сохраняем данные
        if not errors:
            stage_data = {
                'roll1': roll1,
                'roll2': roll2 if has_two_rolls else roll1,
                'upg1': upg1,
                'corrupted1': corrupted1,
                'upg2': upg2,
                'corrupted2': corrupted2,
                'has_two_rolls': has_two_rolls
            }

    # Обработка ошибок
    if errors:
        errors_str = '\n'.join(errors)

        # Формируем пример для текущей команды и части
        example_map = {
            'fz': '{hp} {upg} {y/n}',
            'z': '{hp} {upg} {y/n}',
            'hk': '{hp} {upg} {y/n}',
            'k': '{hp} {upg} {y/n}',
            'wfz': '{roll} > {upg} {y/n}',
            'wz': '{roll} > {upg} {y/n}',
            'whk': '{roll} > {upg} {y/n}',
            'wk': '{roll} > {upg} {y/n}',
            'lfz': '{roll} - {upg1} {y/n1} > {upg2} {y/n2}',
            'lz': '{roll} - {upg1} {y/n1} > {upg2} {y/n2}',
            'lhk': '{roll} - {upg1} {y/n1} > {upg2} {y/n2}',
            'lk': '{roll} - {upg1} {y/n1} > {upg2} {y/n2}'
        }
        example = example_map.get(command, '{аргументы}')

        error_text = (
            f"🛑 **Обнаружены ошибки формата для `!{command}`:**\n"
            f"{errors_str}\n\n"
            f"**Пример написания:**\n{example}"
        )

        chat_id = update.effective_chat.id
        thread_id = update.effective_message.message_thread_id

        # Удаляем сообщение игрока
        try:
            await update.message.delete()
        except Exception:
            pass

        # Отправляем ошибку
        try:
            msg = await context.bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=error_text,
                parse_mode=ParseMode.MARKDOWN
            )
            # ИСПРАВЛЕНО: используем _error_msgs вместо _err_queue
            _error_msgs.setdefault(user_id, deque()).append(msg.message_id)
        except Exception:
            return

        # 3-секундный таймер на удаление
        async def _del_batch():
            await asyncio.sleep(3)
            # ИСПРАВЛЕНО: используем _error_msgs вместо _err_queue
            msgs = _error_msgs.pop(user_id, deque())
            for mid in msgs:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass

        # ИСПРАВЛЕНО: используем _error_msgs вместо _err_queue
        if len(_error_msgs.get(user_id, deque())) == 1:
            asyncio.create_task(_del_batch())
        return

    # Сохраняем данные
    user_data['data'][selected_part] = stage_data
    user_data['parts_status'][selected_part] = ARMOR_STATUS_SAVED

    # Сбрасываем выбор (чтобы показать общее меню)
    user_data['selected_part'] = None

    # Удаляем сообщение пользователя
    await update.message.delete()

    # Обновляем сообщение бота
    armor_name = ARMOR_COMMAND_NAMES.get(command, 'Броня')
    text = f"🛡️ <b>Ввод данных для брони — {armor_name}</b>\n\n"
    text += "Выберите часть брони: <b>Ничего</b>\n\n"
    text += "Нажмите на часть брони, чтобы ввести для неё данные."

    # Показываем какие части уже заполнены
    saved_parts = []
    for part in [STAGE_HELMET, STAGE_CHEST, STAGE_LEGS]:
        if user_data['parts_status'][part] == ARMOR_STATUS_SAVED:
            saved_parts.append(ARMOR_PART_NAMES[part])

    if saved_parts:
        text += f"\n\n<b>Заполнено:</b> {', '.join(saved_parts)}"

    keyboard = get_armor_parts_keyboard(command, user_id, None)

    try:
        await context.bot.edit_message_text(
            chat_id=user_data['chat_id'],
            message_id=user_data['bot_msg_id'],
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        print(f"Ошибка при обновлении сообщения брони: {e}")


async def armor_results_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user

    print(f"\n{'=' * 60}")
    print(f"[ARMOR_CB] === НОВЫЙ CALLBACK ===")
    print(f"[ARMOR_CB] Raw data: {query.data}")
    print(f"[ARMOR_CB] User: {user.id}")

    # Проверка владельца
    if not check_message_ownership(query):
        print(f"[ARMOR_CB] ❌ Не владелец")
        await query.answer("Не ваше сообщение!", show_alert=True)
        return

    await query.answer()

    # Парсинг
    parts = query.data.split(":")
    print(f"[ARMOR_CB] Разобрано: {parts}")

    if len(parts) < 5:
        print(f"[ARMOR_CB] ❌ Слишком коротко: {len(parts)} частей")
        return

    # Закрытие
    if parts[1] == "c":
        try:
            msg_id = int(parts[4])
            await query.message.delete()
            await context.bot.delete_message(query.message.chat.id, msg_id)
            print(f"[ARMOR_CB] ✅ Закрыто")
        except Exception as e:
            print(f"[ARMOR_CB] ❌ Ошибка закрытия: {e}")
        return

    # Проверка префикса
    if parts[0] != "a":
        print(f"[ARMOR_CB] ❌ Неверный префикс: {parts[0]}")
        return

    # Распаковка
    command = parts[1]
    part = parts[2]
    page_code = parts[3]

    try:
        user_msg_id = int(parts[4])
    except ValueError:
        print(f"[ARMOR_CB] ❌ Неверный msg_id: {parts[4]}")
        return

    # packed_data - всё после 5-й позиции
    if len(parts) > 5:
        packed_data = ":".join(parts[5:])
    else:
        print(f"[ARMOR_CB] ❌ Нет packed_data")
        return

    print(f"[ARMOR_CB] cmd={command}, part={part}, page={page_code}, msg_id={user_msg_id}")
    print(f"[ARMOR_CB] packed: {packed_data[:50]}... ({len(packed_data)} chars)")

    # Распаковка
    armor_data = unpack_armor_data_compact(packed_data, command)
    print(f"[ARMOR_CB] Распаковано: {armor_data}")

    if not armor_data or armor_data.get(part) is None:
        print(f"[ARMOR_CB] ❌ Нет данных для {part}")
        await query.answer("Нет данных", show_alert=True)
        return

    # Определяем страницу
    page_map = {
        't': 'total', 'p': 'process', 'b': 'tablet',
        'a': 'ap', 'w': 'wp',
        'f': 'fp', 's': 'sp'
    }
    page_full = page_map.get(page_code, page_code)
    print(f"[ARMOR_CB] Полная страница: {page_full}")

    # Получаем item_info
    item_key_map = {
        'fz': 'fzh', 'wfz': 'fzh', 'lfz': 'fzh',
        'z': 'lzs', 'wz': 'lzs', 'lz': 'lzs',
        'hk': 'hks', 'whk': 'hks', 'lhk': 'hks',
        'k': 'ks', 'wk': 'ks', 'lk': 'ks',
    }
    item_key = item_key_map.get(command, 'fzh')

    try:
        item_info = ITEMS_MAPPING[item_key]
    except KeyError:
        print(f"[ARMOR_CB] ❌ Не найден {item_key}")
        return

    # Генерация текста
    try:
        if page_full == "total":
            text = generate_armor_part_page(item_info, armor_data, command, part)
        elif page_full in ["process", "ap", "wp", "fp", "sp"]:
            text = generate_armor_process_page(item_info, armor_data, command, part, page_full)
        elif page_full == "tablet":
            text = generate_armor_tablet_page(item_info, armor_data, part)
        else:
            print(f"[ARMOR_CB] ❌ Неизвестная страница: {page_full}")
            return
    except Exception as e:
        print(f"[ARMOR_CB] ❌ Ошибка генерации: {e}")
        import traceback
        traceback.print_exc()
        return

    # Генерация клавиатуры
    try:
        keyboard = generate_armor_results_keyboard(command, armor_data, user_msg_id, page_full, part)
    except Exception as e:
        print(f"[ARMOR_CB] ❌ Ошибка клавиатуры: {e}")
        return

    # Отправка
    try:
        await query.message.edit_text(
            text=text,
            parse_mode=ParseMode.HTML if page_full != "tablet" else ParseMode.MARKDOWN_V2,
            reply_markup=keyboard
        )
        print(f"[ARMOR_CB] ✅ Успешно обновлено!")
    except Exception as e:
        print(f"[ARMOR_CB] ❌ Ошибка отправки: {e}")

    print(f"{'=' * 60}\n")

async def generate_armor_results(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int,
                                 from_callback: bool = False):
    """Генерация результатов для брони"""
    if user_id not in user_armor_data:
        return

    user_data = user_armor_data[user_id]

    try:
        command = user_data['command']
        item_key = user_data['item_key']
        item_info = ITEMS_MAPPING[item_key]
        armor_data = user_data['data']
        chat_id = user_data['chat_id']
        user_msg_id = user_data['user_msg_id']
        bot_msg_id = user_data.get('bot_msg_id')

        # Удаляем сообщение бота с интерфейсом
        if from_callback:
            try:
                await update.callback_query.message.delete()
            except:
                pass
        else:
            if bot_msg_id:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=bot_msg_id)
                except:
                    pass

        # Находим первую заполненную часть для показа
        first_part = None
        for part in [STAGE_HELMET, STAGE_CHEST, STAGE_LEGS]:
            if armor_data[part] is not None:
                first_part = part
                break

        if not first_part:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Нет данных для отображения.",
                reply_to_message_id=user_msg_id
            )
            return

        # Генерируем клавиатуру и текст для первой части
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

                # 🔧 ИСПРАВЛЕНИЕ: Учитываем разные форматы данных
                if command in ['fz', 'z', 'hk', 'k']:
                    # Анализ - используем hp напрямую
                    total_hp += data['hp']
                elif command in ['wfz', 'wz', 'whk', 'wk']:
                    # Прогноз - используем roll
                    base_hp = base_stats[data['roll']]
                    total_hp += calculate_armor_stat_at_level(base_hp, data['upg'], data['corrupted'], 1.0, "armor")
                else:  # l-команды
                    # 🔧 ИСПРАВЛЕНИЕ: Для l-команд используем roll2 (желаемый ролл)
                    # Если has_two_rolls, то roll2 может отличаться от roll1
                    use_roll = data.get('roll2', data.get('roll1', 1))
                    base_hp = base_stats[use_roll]
                    total_hp += calculate_armor_stat_at_level(base_hp, data['upg2'], data['corrupted2'], 1.0, "armor")

        # Отправляем результат
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                reply_to_message_id=user_msg_id
            )
        except Exception as e:
            # Если reply_to_message_id не работает, отправляем без него
            print(f"Ошибка reply_to_message_id: {e}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )

    except Exception as e:
        print(f"Ошибка в generate_armor_results: {e}")
        import traceback
        traceback.print_exc()
        try:
            await context.bot.send_message(
                chat_id=user_data['chat_id'],
                text=f"❌ Ошибка при генерации результатов: {e}",
                reply_to_message_id=user_data.get('user_msg_id')
            )
        except:
            pass
    finally:
        # ГАРАНТИРОВАННО удаляем сессию в любом случае!
        if user_id in user_armor_data:
            del user_armor_data[user_id]

# --- ТАБЛИЦЫ РОЛЛОВ ---

async def format_sword_table(update, title, stats_dict):
    header = f"{'Roll':<5} | {'Normal':<10} | {'Corrupted':<12}"
    sep = "-" * len(header)
    rows = [header, sep]

    for level in range(1, 12):
        val = stats_dict.get(level, 0)
        corr = val * 1.5

        # Убираем .0
        v_str = f"{val:g}"
        c_str = f"{corr:g}"

        rows.append(f"{level:<5} | {v_str:<10} | {c_str:<12}")

    res = "\n".join(rows)
    await update.message.reply_text(f"```{title}\n{res}\n```", parse_mode=ParseMode.MARKDOWN_V2)

async def format_armor_table(update, title, stats_dict):
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

# Константы для !ascr
CALLBACK_PREFIX_ASCR = "ascr"
CALLBACK_ASCR_FOUR = "four"
CALLBACK_ASCR_AD = "ad"
CALLBACK_ASCR_WS = "ws"


def format_asc_table_text(title, stats_dict, mode="normal", show_corrupted=False):
    """Форматирование таблицы для ASC оружия - упрощено для Wooden Sword"""

    if title == "WOODEN_SWORD_V2":
        # Для Wooden Sword - только одна строка с роллом 11
        header = f"{'ROLL':<5} | {'Base DMG':<10} | {'Corrupted DMG':<13}"
        sep = "-" * len(header)

        base_value = WOODEN_SWORD_BASE  # 11550 напрямую
        corrupted_value = base_value * 1.5

        rows = [
            header,
            sep,
            f"{11:<5} | {base_value:<10,} | {corrupted_value:<13,}"
        ]

        table_content = "\n".join(rows)
        return f"```{title}\n\n{table_content}\n```"

    # Для остальных - без изменений
    if show_corrupted:
        header = f"{'ROLL':<5} | {'Base DMG':<10} | {'Corrupted DMG':<13}"
        sep = "-" * len(header)
        rows = [header, sep]

        start_roll = 6

        for roll in range(start_roll, 12):
            if roll in stats_dict:
                base_value = stats_dict[roll]
                corrupted_value = base_value * 1.5
                rows.append(f"{roll:<5} | {base_value:<10,} | {corrupted_value:<13,}")
    else:
        header = f"{'Roll':<5} | {'Value':<12}"
        sep = "-" * len(header)
        rows = [header, sep]

        start_roll = 6

        for roll in range(start_roll, 12):
            if roll in stats_dict:
                val = stats_dict[roll]
                if mode == "corrupted":
                    val = val * 1.5

                formatted_val = f"{val:g}"
                rows.append(f"{roll:<5} | {formatted_val:<12}")

    mode_text = "Обычный" if mode == "normal" else "Corrupted"
    table_content = "\n".join(rows)

    return f"```{title}\n{mode_text}\n\n{table_content}\n```"


def format_five_asc_table():
    """Таблица для 4 мечей (M.B., L.K., M.E., P.T.)"""
    header = f"{'ROLL':<5} | {'Base DMG':<10} | {'Corrupted DMG':<13}"
    sep = "-" * len(header)
    rows = [header, sep]

    for roll in range(6, 12):
        base_value = CONQUERORS_BLADE_STATS[roll]
        corrupted_value = base_value * 1.5
        rows.append(f"{roll:<5} | {base_value:<10,} | {corrupted_value:<13,}")

    table_content = "\n".join(rows)
    return f"```5_ASC_WEAPONS\n\n{table_content}\n```"


def get_asc_table_keyboard(current_page="four", user_message_id=None):
    """Клавиатура для !ascr"""

    def make_callback(action):
        base = f"{CALLBACK_PREFIX_ASCR}:{action}"
        return f"{base}:{user_message_id}" if user_message_id else base

    four_text = "✓ 5 ASC" if current_page == "four" else "5 ASC"
    ad_text = "✓ A.D" if current_page == "ad" else "A.D"
    ws_text = "✓ W.S" if current_page == "ws" else "W.S"

    # Добавляем user_message_id в callback
    close_callback = f"{CALLBACK_PREFIX_ASCR}:close"
    if user_message_id:
        close_callback += f":{user_message_id}"

    keyboard = [
        [
            InlineKeyboardButton(four_text, callback_data=make_callback(CALLBACK_ASCR_FOUR)),
            InlineKeyboardButton(ad_text, callback_data=make_callback(CALLBACK_ASCR_AD)),
            InlineKeyboardButton(ws_text, callback_data=make_callback(CALLBACK_ASCR_WS)),
        ],
        [InlineKeyboardButton("Свернуть", callback_data=close_callback)]
    ]
    return InlineKeyboardMarkup(keyboard)

async def asc_table_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды !ascr"""
    if not is_allowed_thread(update):
        return

    text = format_five_asc_table()
    keyboard = get_asc_table_keyboard("four", update.message.message_id)

    try:
        await update.message.reply_text(
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=keyboard,
            reply_to_message_id=update.message.message_id,
            disable_web_page_preview=True
        )
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}", reply_to_message_id=update.message.message_id)


# --- КОНСТАНТЫ ДЛЯ !cupr ---
CALLBACK_PREFIX_CUPR = "cupr"
CALLBACK_CUPR_FURY = "fury"
CALLBACK_CUPR_WRATH = "wrath"


def format_cup_table_text(current_page="fury"):
    """Форматирование таблицы роллов Cupid"""

    if current_page == "wrath":
        # Cupid's Wrath (Secret)
        stats = DOOMBRINGER_STATS
        title = "CUPIDS_WRATH"
        subtitle = "Secret"
    else:
        # Cupid's Fury (Mythic)
        stats = CUPIDS_FURY_STATS
        title = "CUPIDS_FURY"
        subtitle = "Mythic"

    # Заголовок с 3 колонками: Roll | Base DMG | Corrupted
    header = f"{'ROLL':<5} | {'Base DMG':<10} | {'Corrupted DMG':<13}"
    sep = "-" * len(header)
    rows = [header, sep]

    for roll in range(1, 12):
        base_value = stats[roll]
        corrupted_value = base_value * 1.5

        # Форматируем числа с разделителями тысяч
        base_str = f"{base_value:,.2f}"
        corr_str = f"{corrupted_value:,.2f}"

        rows.append(f"{roll:<5} | {base_str:<10} | {corr_str:<13}")

    table_content = "\n".join(rows)

    return f"```{title}\n{subtitle}\n\n{table_content}\n```"


def get_cup_table_keyboard(current_page="fury", user_message_id=None):
    """Клавиатура для !cupr"""

    def make_callback(action):
        base = f"{CALLBACK_PREFIX_CUPR}:{action}"
        return f"{base}:{user_message_id}" if user_message_id else base

    fury_text = "✓ Fury" if current_page == "fury" else "Fury"
    wrath_text = "✓ Wrath" if current_page == "wrath" else "Wrath"

    # Формируем callback_data
    close_callback = f"{CALLBACK_PREFIX_CUPR}:close"
    if user_message_id:
        close_callback += f":{user_message_id}"

    keyboard = [
        [
            InlineKeyboardButton(fury_text, callback_data=make_callback(CALLBACK_CUPR_FURY)),
            InlineKeyboardButton(wrath_text, callback_data=make_callback(CALLBACK_CUPR_WRATH)),
        ],
        [InlineKeyboardButton("Свернуть", callback_data=close_callback)]
    ]
    return InlineKeyboardMarkup(keyboard)


async def cup_table_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды !cupr"""
    if not is_allowed_thread(update):
        return

    text = format_cup_table_text("fury")
    keyboard = get_cup_table_keyboard("fury", update.message.message_id)

    try:
        await update.message.reply_text(
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=keyboard,
            reply_to_message_id=update.message.message_id,
            disable_web_page_preview=True
        )
    except Exception as e:
        await update.message.reply_text(
            f"Ошибка при отправке таблицы: {e}",
            reply_to_message_id=update.message.message_id
        )

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
Версия бота - 1.0.3v РЕЛИЗ

*Общие правила:*
(y/n): y - corrupted, n - НЕ corrupted.

*ВЕБ-ВЕРСИЯ ЭТОГО ЖЕ БОТА, МЕЖДУНАРОДНАЯ:*
https://yarreyt.github.io/EDUCRB/

*Таблицы роллов:*
`!crhelp` - Показать это меню
`!reforge` - Список множителей Reforge
`!doomr` - Список роллов Дума (Doombringer)
`!conqr` - Список роллов Конки (Conqueror's Blade)
`!ascr` - Список роллов всех Ascended оружий
`!tlr` - Список роллов для TL конков (TimeLost Conqueror's Blade)
`!cupr` - Список роллов всех Cupid оружий
`!fzr` - Список роллов Furious Zeus Set 
`!zr` - Список роллов Zeus Set 
`!hkr` - Список роллов Heroic Kronax Set
`!kr` - Список роллов Kronax Set

*Команды для владельца групп:*
`!roll_id` {ID топика} {Название}
`!roll_id_clear` {ID топика} - если написать без айди, то бот очистит все топики
`!roll_allow` - для обычных групп без топиков
`!roll_deny` - удалить доступ к чату обычной группы
`!roll_status` - показать настройки бота в группе

"""

def get_instruction_page_text():
    return """Создатель бота - H2O (YarreYT)

*1. Объяснения аргументов для команд:*

`{roll}` - _индекс предмета, означающий множитель базового урона. В игре для практически всех оружий роллов от 1 до 11, за исключением Ascended оружий с КРАФТА, у которых может быть только от 6 до 11. Чтобы узнать ролл вашего предмета, основные для этого команды в разделе_ *"!..."*
`{dmg/hp}` - _значение урона/здоровья на предмете, который у вас отображается в игре_
`{upg}` - _значение уровня улучшений на предмете, до которого вы дошли в игре. В игре для редкости Legendary доступные уровни улучшения 0-34, а для редкости Mythical 0-45, и Ascended - 0-44_
`{y/n}` - _значение состояние вашего предмета._
(y - ваш предмет Corrupted; n - ваш предмет НЕ Corrupted)
`{reforge}` - _значение зачарования вашего предмета, который вы смогли получить у кузнеца. Требуется ознакомиться со списком зачарований командой_ *"!reforge"*
`"-"` и `">"` - _не менее важные символы для ввода. О них не нужно забывать. Визуально выглядит круто и вполне уместно_

*Вкратце о аргументах*
`{roll}` - все редкости: 0-11; у Ascended с крафта - 6-11
`{upg}` - легендарная редкость: 0-34; у Mythical 0-45, у Ascended - 0-44
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

*Все виды Ascended оружий:*
`!asc` {dmg} {upg} {y/n} {reforge}

*Все виды TL Conqueror's Blades:*
`!tl` {dmg} {upg} {y/n} {reforge}

*Cupid's Fury/Wrath оружия*
`!cup` {dmg} {upg} {y/n} {reforge}

*Броня:* 
`!fz` / `!z` / `!hk` / `!k`

По выбору части брони, вводить:
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

*Все виды Ascended оружий:*
`!wasc` {ролл} > {upg} {y/n} {reforge}

*Все виды TL Conqueror's Blades:*
`!wtl` {ролл} > {upg} {y/n} {reforge}

*Cupid's Fury/Wrath оружия*
`!wcup` {ролл} > {upg} {y/n} {reforge}

*Броня:* 
`!wfz` / `!wz` / `!whk` / `!wk`

По выбору части брони, вводить:
{roll} > {upg} {y/n}
"""

def get_l_page_text():
    return """Создатель бота - H2O (YarreYT)

*Общие правила:*
(y/n): y - corrupted, n - НЕ corrupted.

*Прогноз и сравнение актуальных и желаемых характеристик предмета (!l...)*

*Оружие:*
`!lconq` / `!ldoom` / `!lasc` / `!ltl` / `!lcup`

`Формула 1`: *{ролл} - {upg1} {y/n1} {reforge1} > {upg2} {y/n2} {reforge2}*
- для сравнения одного оружия с разными характеристиками
`Формула 2`: *{ролл1} > {ролл2} - {upg1} {y/n1} {reforge1} > {upg2} {y/n2} {reforge2}*
- для сравнения двух одинаковых оружий, с разными роллами и разными характеристиками

*Броня:* 
`!lfz` / `!lz` / `!lhk` / `!lk`

По выбору части брони, вводить:
`Формула 1`: *{ролл} - {upg1} {y/n1} > {upg2} {y/n2}*
- для сравнения одной брони с разными характеристиками
`Формула 2`: *{ролл1} > {ролл2} - {upg1} {y/n1} > {upg2} {y/n2}*
- для сравнения двух одинаковых броней, с разными роллами и разными характеристиками
"""

def get_help_keyboard(current_page="main", user_message_id=None):

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


# --- КОНСТАНТЫ ДЛЯ !tlr ---
CALLBACK_PREFIX_TLR = "tlr"
CALLBACK_TLR_NORMAL = "normal"
CALLBACK_TLR_LE = "le"
CALLBACK_PREFIX_HKRR = "hkrr"
CALLBACK_PREFIX_KRR = "krr"

def format_tl_table_text(current_page="normal"):
    """Форматирование таблицы роллов Timelost"""

    if current_page == "le":
        # Limited Edition (Ascended)
        stats = TIMELOST_CONQUERORS_BLADE_LE_STATS
        title = "TIMELOST_CONQUERORS_BLADE_LE"
        subtitle = "Limited Edition (Ascended)"
    else:
        # Обычный (Mythical)
        stats = TIMELOST_CONQUERORS_BLADE_STATS
        title = "TIMELOST_CONQUERORS_BLADE"
        subtitle = "Mythical"

    # Заголовок с 3 колонками: Roll | Base DMG | Corrupted
    header = f"{'ROLL':<5} | {'Base DMG':<10} | {'Corrupted DMG':<13}"
    sep = "-" * len(header)
    rows = [header, sep]

    for roll in range(1, 12):
        base_value = stats[roll]
        corrupted_value = base_value * 1.5

        # Форматируем числа с разделителями тысяч
        base_str = f"{base_value:,.2f}"
        corr_str = f"{corrupted_value:,.2f}"

        rows.append(f"{roll:<5} | {base_str:<10} | {corr_str:<13}")

    table_content = "\n".join(rows)

    return f"```{title}\n{subtitle}\n\n{table_content}\n```"

def get_tl_table_keyboard(current_page="normal", user_message_id=None):
    """Клавиатура для !tlr"""

    def make_callback(action):
        base = f"{CALLBACK_PREFIX_TLR}:{action}"
        return f"{base}:{user_message_id}" if user_message_id else base

    normal_text = "✓ Timelost" if current_page == "normal" else "Timelost"
    le_text = "✓ Timelost L.E." if current_page == "le" else " Timelost L.E."

    # Формируем callback_data
    close_callback = f"{CALLBACK_PREFIX_TLR}:close"
    if user_message_id:
        close_callback += f":{user_message_id}"

    keyboard = [
        [
            InlineKeyboardButton(normal_text, callback_data=make_callback(CALLBACK_TLR_NORMAL)),
            InlineKeyboardButton(le_text, callback_data=make_callback(CALLBACK_TLR_LE)),
        ],
        [InlineKeyboardButton("Свернуть", callback_data=close_callback)]
    ]
    return InlineKeyboardMarkup(keyboard)

async def tl_table_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды !tlr"""
    if not is_allowed_thread(update):
        return

    text = format_tl_table_text("normal")
    keyboard = get_tl_table_keyboard("normal", update.message.message_id)

    try:
        await update.message.reply_text(
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=keyboard,
            reply_to_message_id=update.message.message_id,
            disable_web_page_preview=True
        )
    except Exception as e:
        await update.message.reply_text(
            f"Ошибка при отправке таблицы: {e}",
            reply_to_message_id=update.message.message_id
        )

# Обработчик нажатий на кнопки меню помощи
async def unified_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    # 🛑 ПРОВЕРКА ВЛАДЕЛЬЦА
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

    # Безопасное получение user_message_id
    user_message_id = None
    if len(data_parts) > 2:
        try:
            user_message_id = int(data_parts[2])
        except (ValueError, IndexError):
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
            "instruction": get_instruction_page_text(),
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

    # Табличные команды (conqr, doomr, fzr, zr)
    if prefix in (CALLBACK_PREFIX_CONQR, CALLBACK_PREFIX_DOOMR, CALLBACK_PREFIX_FZR, CALLBACK_PREFIX_ZR, "hkrr", "krr"):
        if prefix in (CALLBACK_PREFIX_CONQR, CALLBACK_PREFIX_DOOMR):
            title = "CONQUEROR_ROLLS" if prefix == CALLBACK_PREFIX_CONQR else "DOOM_ROLLS"
            stats_dict = CONQUERORS_BLADE_STATS if prefix == CALLBACK_PREFIX_CONQR else DOOMBRINGER_STATS
            format_func = format_sword_table_text
            keyboard_func = get_weapon_table_keyboard
        elif prefix == "hkrr":
            title = "HEROIC_KRONAX_ARMOR"
            stats_dict = HKR_STATS
            format_func = format_armor_part_table_text
            keyboard_func = get_armor_table_keyboard
        elif prefix == "krr":
            title = "KRONAX_ARMOR"
            stats_dict = KR_STATS
            format_func = format_armor_part_table_text
            keyboard_func = get_armor_table_keyboard
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

        # === НОВЫЙ ОБРАБОТЧИК ДЛЯ !ascr ===
    if prefix == CALLBACK_PREFIX_ASCR:
        # Закрытие
        if action == CALLBACK_TABLE_CLOSE or action == "close":
            await query.message.delete()
            if user_message_id:
                try:
                    await context.bot.delete_message(
                        chat_id=query.message.chat_id,
                        message_id=user_message_id
                    )
                except:
                    pass
            return

        # Генерация таблиц
        if action == CALLBACK_ASCR_FOUR:
            text = format_five_asc_table()
        elif action == CALLBACK_ASCR_AD:
            stats = ITEMS_MAPPING["asc_ad"]["stats"]
            text = format_asc_table_text("DUAL_DAGGERS_V2", stats, "normal", show_corrupted=True)
        elif action == CALLBACK_ASCR_WS:
            stats = {11: WOODEN_SWORD_BASE}
            text = format_asc_table_text("WOODEN_SWORD_V2", stats, "normal", show_corrupted=True)
        else:
            await query.answer("Неизвестное действие", show_alert=True)
            return

        keyboard = get_asc_table_keyboard(action, user_message_id)
        await query.message.edit_text(
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        return

    # === ОБРАБОТЧИК ДЛЯ !tlr ===
    if prefix == CALLBACK_PREFIX_TLR:
         # Закрытие
        if action == "close":
            await query.message.delete()
            if user_message_id:
                try:
                    await context.bot.delete_message(
                        chat_id=query.message.chat_id,
                        message_id=user_message_id
                    )
                except:
                    pass
            return

        # Переключение страниц
        if action in (CALLBACK_TLR_NORMAL, CALLBACK_TLR_LE):
            text = format_tl_table_text(action)
            keyboard = get_tl_table_keyboard(action, user_message_id)

            try:
                await query.message.edit_text(
                    text=text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=keyboard,
                    disable_web_page_preview=True
                )
            except Exception as e:
                print(f"Ошибка при редактировании tlr: {e}")
            return

    # === ОБРАБОТЧИК ДЛЯ !cupr ===
    if prefix == CALLBACK_PREFIX_CUPR:
        # Закрытие
        if action == "close":
            await query.message.delete()
            if user_message_id:
                try:
                    await context.bot.delete_message(
                        chat_id=query.message.chat_id,
                        message_id=user_message_id
                    )
                except:
                    pass
            return

        # Переключение страниц
        if action in (CALLBACK_CUPR_FURY, CALLBACK_CUPR_WRATH):
            text = format_cup_table_text(action)
            keyboard = get_cup_table_keyboard(action, user_message_id)

            try:
                await query.message.edit_text(
                    text=text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=keyboard,
                    disable_web_page_preview=True
                )
            except Exception as e:
                print(f"Ошибка при редактировании cupr: {e}")
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

async def reforge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    if command in ("conq", "doom", "asc", "tl", "cup"):  # 🔧 Добавлен "cup"
        await analyze_weapon(update, context,
                             "cb" if command == "conq" else
                             "db" if command == "doom" else
                             "asc_ws" if command == "asc" else
                             "tl" if command == "tl" else "cup")

    # Прогноз оружия
    elif command in ("wconq", "wdoom", "wasc", "wtl", "wcup"):
        await w_analyze_weapon(update, context,
                               "cb" if command == "wconq" else
                               "db" if command == "wdoom" else
                               "asc_ws" if command == "wasc" else
                               "tl" if command == "wtl" else "cup")

    # Сравнение оружия
    elif command in ("lconq", "ldoom", "lasc", "ltl", "lcup"):
        await l_analyze_weapon(update, context,
                               "cb" if command == "lconq" else
                               "db" if command == "ldoom" else
                               "asc_ws" if command == "lasc" else
                               "tl" if command == "ltl" else "cup")

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
    elif command in ('k',):
        await handle_armor_command(update, context, 'k')
    elif command in ('hk',):
        await handle_armor_command(update, context, 'hk')
    elif command == 'wk':
        await handle_armor_command(update, context, 'wk')
    elif command == 'whk':
        await handle_armor_command(update, context, 'whk')
    elif command == 'lk':
        await handle_armor_command(update, context, 'lk')
    elif command == 'lhk':
        await handle_armor_command(update, context, 'lhk')

    # Служебные команды
    elif command == "crhelp":
        await cmd_help(update, context)
    elif command == "reforge":
        await reforge_command(update, context)
    elif command == "tlr":
        await tl_table_command(update, context)
        return
    elif command == "cupr":
        await cup_table_command(update, context)
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
    elif command == "ascr":
        await asc_table_command(update, context)
        return
    elif command == 'kr':
        await update.message.reply_text(
            text=format_armor_part_table_text("KRONAX_ARMOR", KR_STATS, "helmet"),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=get_armor_table_keyboard("krr", "helmet", update.message.message_id),
            reply_to_message_id=update.message.message_id
        )
    elif command == 'hkr':
        await update.message.reply_text(
            text=format_armor_part_table_text("HEROIC_KRONAX_ARMOR", HKR_STATS, "helmet"),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=get_armor_table_keyboard("hkrr", "helmet", update.message.message_id),
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

def main():
    global ALLOWED_TOPICS
    ALLOWED_TOPICS = load_allowed_topics()
    print(f"Бот запущен с {len(ALLOWED_TOPICS)} настроенными группами")
    app = Application.builder().token(TOKEN).build()

    # 1. Обработчик умного "Да"
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & smart_da_filter,
            yes_handler
        ),
        group=0
    )

    # 2. ЕДИНЫЙ Callback для всего оружия (вместо множества отдельных)
    # Форматы: normal:*, tl:*, asc:*, wnormal:*, wtl:*, wasc:*, lnormal:*, ltl:*, lasc:*
    app.add_handler(
        CallbackQueryHandler(
            weapon_analysis_callback,
            pattern="^(normal|tl|asc|cup|wnormal|wtl|wasc|wcup|lnormal|ltl|lasc|lcup|close):"
        ),
        group=0
    )

    # 3. Callback для этапов ввода брони
    app.add_handler(
        CallbackQueryHandler(armor_part_callback, pattern="^armor_part:"),
        group=0
    )
    app.add_handler(
        CallbackQueryHandler(armor_finish_callback, pattern="^armor_finish:"),
        group=0
    )
    app.add_handler(
        CallbackQueryHandler(armor_cancel_callback, pattern="^armor_cancel:"),
        group=0
    )

    # 4. Callback для результатов брони
    app.add_handler(
        CallbackQueryHandler(armor_results_callback, pattern="^a:"),
        group=0
    )

    # 5. UI callback'и (help, таблицы, ascr, tlr)
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

    print("Бот запущен... С унифицированной системой оружия!")
    app.run_polling()

if __name__ == "__main__":
    main()
