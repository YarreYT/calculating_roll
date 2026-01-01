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

# --- ИМПОРТ БАЗЫ ДАННЫХ ---
from game_data import (
    REFORGE_MODIFIERS,
    CONQUERORS_BLADE_STATS,
    DOOMBRINGER_STATS,
    FZH_STATS,
    LZS_STATS,
    ITEMS_MAPPING,
    PART_MAPPING
)

# --- КОНФИГУРАЦИЯ ---
TOKEN = '8296615863:AAHWDGuMwqLOaGbLJ9xO9puwp8CDur8LNBQ'
ALLOWED_THREAD_ID = 97989  # ID топика по умолчанию
ALLOWED_THREAD_NAME = "ROLL"  # Название топика по умолчанию
ADMIN_USERNAME = "YarreYT"  # Только этот пользователь может менять настройки

GROWTH_RATE = 1 / 21

# Фразы для тех, кто пишет не в том топике
WRONG_TOPIC_TEXTS = [
    "Я не тут работаю. Понимаю, лень, но я работаю в топике \"{name}\"",
    "Чё ты сюда пишешь, перейди в \"{name}\" и не еби мозги себе и админу",
    "Я не тут работаю, ёпта! Иди в \"{name}\" и там пиши, блять, команды! И начни с `!crhelp` ",
    "Чувак, ну ты чё. Не там пишешь. Пиши на канале \"{name}\"",
    "Долбаёб!!! Не сюда!!!! Иди в \"{name}\"",
    "Да ты тупой что ли, не здесь я работаю! Сука! Иди в \"{name}\"",
    "Да вроде же не глухие и не слепые. Ну, не первый раз же говорю вам ебланам, что с командами идите в \"{name}\"",
    "DURA: Я хуею с этой дуры"
]

WRONG_TOPIC_WEIGHTS = [10, 15, 10, 10, 20, 10, 5, 1]

WRONG_TOPIC_PICS = {
    "DURA": "https://www.meme-arsenal.com/memes/d534debf6f97116896c0cdbc9d68b7f4.jpg"
}

# --- НОВЫЕ КОНСТАНТЫ ДЛЯ НЕИЗВЕСТНЫХ КОМАНД ---
UNKNOWN_COMMAND_RESPONSES = {
    "Такой команды нет, еблан. Напиши !crhelp": 20,
    "Чё ты несёшь? Команды не существует. !crhelp для помощи": 15,
    "Да ты тупой? Такой команды нет. Пиши !crhelp": 15,
    "Не знаю такой команды. Возможно, ты сам её придумал, долбоёб. !crhelp": 10,
    "Я хуею с этой дуры": 1,
}

UNKNOWN_COMMAND_PHOTOS = {
    "Я хуею с этой дуры": "https://www.meme-arsenal.com/memes/450c91d6864f8bbb1a3296a5537d19f7.jpg",
}

# --- КОНСТАНТЫ ДЛЯ ASC ОРУЖИЯ ---
ASC_WEAPON_TYPES = {
    'w': {"name": "Wooden Sword V2", "base_dmg": 10395, "fixed_roll": True, "has_rolls": False},
    'd': {"name": "Dual Daggers V2", "stats": CONQUERORS_BLADE_STATS, "fixed_roll": False, "min_roll": 6},
    't': {"name": "Poseidon's Trident V2", "stats": CONQUERORS_BLADE_STATS, "fixed_roll": False, "min_roll": 6},
    'k': {"name": "Lightning Katana V2", "stats": CONQUERORS_BLADE_STATS, "fixed_roll": False, "min_roll": 6},
    'e': {"name": "Magma's Edge V2", "stats": CONQUERORS_BLADE_STATS, "fixed_roll": False, "min_roll": 6},
    'm': {"name": "Menta Blade V2", "stats": CONQUERORS_BLADE_STATS, "fixed_roll": False, "min_roll": 6},
}

ASC_BASE_UPGRADE_COST = 2917  # Стоимость 1 уровня для всех ASC оружий


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def is_allowed_thread(update) -> bool:
    """
    Проверяет, что сообщение находится в разрешённом топике.
    Работает как для обычных updates, так и для callback_query.
    """
    if ALLOWED_THREAD_ID is None:
        return True

    # Для callback_query (query.message.message_thread_id)
    if hasattr(update, 'callback_query') and update.callback_query and update.callback_query.message:
        thread_id = update.callback_query.message.message_thread_id
    # Для обычного update (update.effective_message.message_thread_id)
    elif hasattr(update, 'effective_message') and update.effective_message:
        thread_id = update.effective_message.message_thread_id
    else:
        return False

    return thread_id is not None and thread_id == ALLOWED_THREAD_ID


def calculate_gold(base_cost: int, upg_level: int) -> int:
    """
    Вычисляет накопленную стоимость золота до определенного уровня.
    Вместо формулы прогрессии используем цикл с округлением каждого шага,
    как это делает игра.
    """
    if upg_level <= 0:
        return 0

    total_spent = 0
    current_cost = float(base_cost)

    # Считаем стоимость для каждого уровня с 1-го до upg_level
    for lvl in range(1, upg_level + 1):
        # Округляем текущую стоимость до целого (как в игре)
        rounded_cost = round(current_cost)
        # Добавляем к общей сумме
        total_spent += rounded_cost
        # Стоимость следующего апгрейда всегда на 30% больше ТЕКУЩЕЙ (округленной)
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

    # клиент делает round, но «в пользу роста» если дробь ≥ 0.45
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
    """Определяет ролл, находя базовое значение, которое ближе всего к inferred_value."""
    best_roll = 1
    best_diff = abs(inferred_value - stats_dict[1])

    for roll in range(2, 12):
        current_diff = abs(inferred_value - stats_dict[roll])
        if current_diff < best_diff:
            best_diff = current_diff
            best_roll = roll

    return best_roll


def clean_args_from_separator(args: list) -> list:
    """Убирает знак '>' из аргументов, если пользователь его написал."""
    return [arg for arg in args if arg != '>']


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
        "Пизда": "https://sun9-48.userapi.com/impg/c844418/v844418142/4f7ef/wk7pnm_dqkY.jpg?size=487x487&quality=96&sign=29e3dacedac2c03eaa320ee2403f8624&type=album",
        "MUDA": "https://www.meme-arsenal.com/memes/e580d8c1ac6e6a7bc1c623bd7ab80dce.jpg",
        "Джигурда": "https://www.meme-arsenal.com/memes/03c918ccc821b8172f09c38ded2b8d57.jpg"
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


# --- ФУНКЦИИ АНАЛИЗА ТЕКУЩЕГО ПРЕДМЕТА (СТАРЫЕ КОМАНДЫ: !conq, !doom, !fzhelm, и т.д.) ---

async def analyze_weapon(update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
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
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    damage = float(args[0])
    upg_level = int(args[1])
    is_corrupted = args[2].lower() == 'y'

    try:
        base_stats = item_info['stats']
        b1 = item_info['upgrade_cost_lvl1']

        inferred_base = infer_base_for_weapon(damage, upg_level, is_corrupted, reforge_mult)
        roll = determine_roll(base_stats, inferred_base)
        base_dmg = base_stats[roll]

        current_spent_gold = calculate_gold(b1, upg_level)
        total_max_gold = calculate_gold(b1, max_lvl)
        remaining_gold = max(0, total_max_gold - current_spent_gold)

        response = (
            f"📊 <b>Анализ {item_info['name']}</b>\n\n"
            f"<b>DMG:</b> <i>{int(damage):,}</i>\n"
            f"<b>Reforge:</b> <i>{reforge_name}</i>\n"
            f"<b>Corrupted:</b> <i>{'Да' if is_corrupted else 'Нет'}</i>\n"
            f"<b>Upgrade:</b> <i>{upg_level}</i> (Макс: {max_lvl})\n"
            f"<b>Gold spent:</b> <i>{current_spent_gold:,}</i> 💰\n"
            f"<b>Gold left to spend:</b> <i>{remaining_gold:,}</i> 💰\n\n"
            f"<b>BASE DMG:</b> <i>{base_dmg:,}</i>\n"
            f"<b>ROLL:</b> <i>{roll}/11</i>"
        )
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")

async def analyze_armor(update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    item_info = ITEMS_MAPPING[item_key]
    max_lvl = item_info['max_level']
    args = context.args
    errors = []

    part_key = None
    for key in PART_MAPPING:
        if command_name.endswith(key):
            part_key = key
            break
    if part_key is None:
        await update.message.reply_text("Не удалось определить часть брони.")
        return

    part_name = PART_MAPPING[part_key]
    russian_part = {"Helmet": "Шлем", "Chestplate": "Нагрудник", "Leggings": "Поножи"}[part_name]

    if len(args) != 3:
        errors.append(f"❌ Неверное количество аргументов ({len(args)}). Ожидается 3.")

    if len(args) == 3:
        try:
            health = float(args[0])
        except ValueError:
            errors.append(f"❌ ХП ({args[0]}) должно быть числом.")

        try:
            upg_level = int(args[1])
            if upg_level > max_lvl or upg_level < 0:
                errors.append(f"❌ Уровень {russian_part} ({upg_level}) не соответствует 0-{max_lvl}.")
        except ValueError:
            errors.append(f"❌ Уровень улучшения ({args[1]}) должен быть числом.")

        is_corrupted_str = args[2].lower()
        if is_corrupted_str not in ('y', 'n'):
            errors.append(f"❌ Статус порчи ({is_corrupted_str}) должен быть 'y' или 'n'.")

    if errors:
        example = f"`{command_name}` {{hp}} {{upg}} {{y/n}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    health = float(args[0])
    upg_level = int(args[1])
    is_corrupted = args[2].lower() == 'y'

    try:
        base_stats = item_info['stats'][part_name]
        b1 = item_info['upgrade_cost_lvl1']

        roll = find_roll_for_armor(base_stats, health, upg_level, is_corrupted)
        base_hp = base_stats[roll]

        current_spent_gold = calculate_gold(b1, upg_level)
        total_max_gold = calculate_gold(b1, max_lvl)
        remaining_gold = max(0, total_max_gold - current_spent_gold)

        response = (
            f"🛡️ <b>{item_info['name']} — {russian_part}</b>\n\n"
            f"<b>HP:</b> <i>{int(health):,}</i>\n"
            f"<b>Corrupted:</b> <i>{'Да' if is_corrupted else 'Нет'}</i>\n"
            f"<b>Upgrade:</b> <i>{upg_level}</i> (Макс: {max_lvl})\n"
            f"<b>Gold spent:</b> <i>{current_spent_gold:,}</i> 💰\n"
            f"<b>Gold left to spend:</b> <i>{remaining_gold:,}</i> 💰\n\n"
            f"<b>BASE HP:</b> <i>{base_hp:,}</i>\n"
            f"<b>ROLL:</b> <i>{roll}/11</i>"
        )
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


async def analyze_full_set(update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args = context.args
    item_info = ITEMS_MAPPING[item_key]
    max_lvl = item_info['max_level']

    parts_order = ["Helmet", "Chestplate", "Leggings"]
    rus_names_nominative = ["Шлем", "Нагрудник", "Штаны"]
    errors = []

    if len(args) != 9:
        errors.append(f"❌ Неверное количество аргументов ({len(args)}). Ожидается 9.")

    if len(args) == 9:
        for i in range(3):
            part_name = rus_names_nominative[i]
            try:
                hp = float(args[i])
            except ValueError:
                errors.append(f"❌ ХП {part_name} ({args[i]}) должно быть числом.")

            try:
                level = int(args[i + 3])
                if level > max_lvl or level < 0:
                    errors.append(f"❌ Уровень {part_name} ({level}) не соответствует 0-{max_lvl}.")
            except ValueError:
                errors.append(f"❌ Уровень {part_name} ({args[i + 3]}) должен быть числом.")

            is_corr_str = args[i + 6].lower()
            if is_corr_str not in ('y', 'n'):
                errors.append(f"❌ Статус порчи {part_name} ({is_corr_str}) должен быть 'y' или 'n'.")

    if errors:
        example = f"`{command_name}` {{hp1}} {{hp2}} {{hp3}} {{upg1}} {{upg2}} {{upg3}} {{y/n1}} {{y/n2}} {{y/n3}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    try:
        b1 = item_info['upgrade_cost_lvl1']
        stats_db = item_info['stats']
        rus_names = ["Шлема", "Нагрудника", "Штанов"]

        total_hp_display = 0.0
        results = []

        for i, part_key in enumerate(parts_order):
            hp = float(args[i])
            level = int(args[i + 3])
            is_corr = args[i + 6].lower() == 'y'
            total_hp_display += hp

            spent = calculate_gold(b1, level)
            total_needed = calculate_gold(b1, max_lvl)
            rem = max(0, total_needed - spent)

            roll = find_roll_for_armor(stats_db[part_key], hp, level, is_corr)
            base_hp = stats_db[part_key][roll]

            results.append({
                "rus_name": rus_names[i],
                "rus_nom": rus_names_nominative[i],
                "lvl": level,
                "spent": spent,
                "rem": rem,
                "roll": roll,
                "base_hp": base_hp
            })

        response = f"🛡️ <b>Анализ сета: {item_info['name']}</b>\n"
        response += f"<b>TOTAL HEALTH:</b> <i>{int(total_hp_display):,}</i> ❤️\n\n"

        response += "<b>BASE HP</b>\n"
        for res in results:
            response += f"<b>{res['rus_nom']}:</b> <i>{int(res['base_hp']):,}</i>\n"
        response += "\n"

        response += "<b>🆙 UPG</b>\n"
        for res in results:
            response += f"<b>{res['rus_nom']}:</b> <i>{res['lvl']}</i>\n"

        response += "\n<b>💰 GOLD (Spent / Left to spend)</b>\n"
        for res in results:
            response += f"<b>{res['rus_nom']}:</b> <i>{res['spent']:,}</i> / <i>{res['rem']:,}</i>\n"

        response += "\n<b>🎲 ROLL</b>\n"
        for res in results:
            response += f"<b>{res['rus_nom']}:</b> <i>{res['roll']}/11</i>\n"

        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


# --- ОБНОВЛЕННЫЕ ФУНКЦИИ ДЛЯ ASC ОРУЖИЯ (НОВЫЕ КОМАНДЫ) ---

async def analyze_weapon_asc(update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args = context.args
    errors = []

    if len(args) not in (4, 5):
        errors.append(f"❌ Неверное количество аргументов ({len(args)}). Ожидается 4 или 5 для ASC оружия.")

    weapon_type = args[0].lower() if len(args) > 0 else None
    if weapon_type not in ASC_WEAPON_TYPES:
        if weapon_type:
            errors.append(f"❌ Неизвестный тип ASC оружия '{weapon_type}'. Используйте: w/d/t/k/e/m")
        else:
            errors.append("❌ Тип ASC оружия не указан. Используйте: w/d/t/k/e/m")

    weapon_info = ASC_WEAPON_TYPES.get(weapon_type, {})
    is_fixed_roll = weapon_info.get("fixed_roll", False)

    reforge_name = "None"
    reforge_mult = 1.0
    if len(args) == 5:
        reforge_input = args[4]
        found_reforge = False
        for k_ref in REFORGE_MODIFIERS:
            if k_ref.lower() == reforge_input.lower():
                reforge_name = k_ref
                reforge_mult = REFORGE_MODIFIERS[k_ref]
                found_reforge = True
                break
        if not found_reforge:
            errors.append(f"❌ Неизвестный Reforge ({reforge_input}), напишите !reforge для списка.")

    if len(args) >= 4 and weapon_type in ASC_WEAPON_TYPES:
        try:
            damage = float(args[1])
        except (ValueError, IndexError):
            errors.append(f"❌ Урон ({args[1]}) должен быть числом.")

        try:
            upg_level = int(args[2])
            if upg_level > 45 or upg_level < 0:
                errors.append(f"❌ Уровень меча ({upg_level}) не соответствует 0-45.")
        except (ValueError, IndexError):
            errors.append(f"❌ Уровень улучшения ({args[2]}) должен быть числом.")

        is_corrupted_str = args[3].lower() if len(args) > 3 else ''
        if is_corrupted_str not in ('y', 'n'):
            errors.append(f"❌ Статус порчи ({is_corrupted_str}) должен быть 'y' или 'n'.")

    if errors:
        example = f"`{command_name}` {{type}} {{dmg}} {{upg}} {{y/n}} {{reforge}}\n(если reforge нет - не пишите)"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example}\n\n**Типы оружия:**\n"
        error_message += "w - Wooden Sword (фикс. урон)\n"
        error_message += "d - Dual Daggers\n"
        error_message += "t - Poseidon's Trident\n"
        error_message += "k - Lightning Katana\n"
        error_message += "e - Magma's Edge\n"
        error_message += "m - Menta Blade V2"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    damage = float(args[1])
    upg_level = int(args[2])
    is_corrupted = args[3].lower() == 'y'

    try:
        if is_fixed_roll:
            base_dmg = weapon_info["base_dmg"]
            roll_text = "У этого типа исключительно 11 ролл"
        else:
            base_stats = weapon_info["stats"]
            inferred_base = infer_base_for_weapon(damage, upg_level, is_corrupted, reforge_mult)
            roll = determine_roll(base_stats, inferred_base)
            base_dmg = base_stats[roll]
            roll_text = f"<b>ROLL:</b> <i>{roll}/11</i>"

        current_spent_gold = calculate_gold(ASC_BASE_UPGRADE_COST, upg_level)
        total_max_gold = calculate_gold(ASC_BASE_UPGRADE_COST, 45)
        remaining_gold = max(0, total_max_gold - current_spent_gold)

        response = (
            f"📊 <b>Анализ {weapon_info['name']}</b>\n\n"
            f"<b>DMG:</b> <i>{int(damage):,}</i>\n"
            f"<b>Reforge:</b> <i>{reforge_name}</i>\n"
            f"<b>Corrupted:</b> <i>{'Да' if is_corrupted else 'Нет'}</i>\n"
            f"<b>Upgrade:</b> <i>{upg_level}</i> (Макс: 45)\n"
            f"<b>Gold spent:</b> <i>{current_spent_gold:,}</i> 💰\n"
            f"<b>Gold left to spend:</b> <i>{remaining_gold:,}</i> 💰\n\n"
            f"<b>BASE DMG:</b> <i>{int(base_dmg):,}</i>\n"
            f"{roll_text}"
        )
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


async def w_analyze_weapon_asc(update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args_raw = context.args
    errors = []

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

        if len(left_args) > 0:
            weapon_type = left_args[0].lower()
            if weapon_type == 'w':
                if len(left_args) != 1:
                    errors.append(f"❌ Для типа 'w' левая часть должна содержать только тип оружия. Формат: w > {{upg}} {{y/n}}")
            else:
                if len(left_args) != 2:
                    errors.append(f"❌ Для типа '{weapon_type}' ожидается тип и ролл (2 аргумента).")

        if len(right_args) not in (2, 3):
            errors.append(f"❌ Правая часть: неверное количество аргументов ({len(right_args)}). Ожидается 2 или 3.")

    if errors:
        example = f"`{command_name}` {{type}} [ролл] > {{upg}} {{y/n}} {{reforge}}\n\nДля Wooden Sword: `{command_name} w > {{upg}} {{y/n}} {{reforge}}`\nДля остальных: `{command_name} {{type}} {{ролл}} > {{upg}} {{y/n}} {{reforge}}`"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example}\n\n**Типы оружия:**\n"
        error_message += "w - Wooden Sword (без ролла)\n"
        error_message += "d - Dual Daggers\n"
        error_message += "t - Poseidon's Trident\n"
        error_message += "k - Lightning Katana\n"
        error_message += "e - Magma's Edge\n"
        error_message += "m - Menta Blade V2"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    weapon_type = left_args[0].lower()
    if weapon_type not in ASC_WEAPON_TYPES:
        await update.message.reply_text(f"❌ Неизвестный тип ASC оружия '{weapon_type}'. Используйте: w/d/t/k/e/m",
                                        parse_mode=ParseMode.MARKDOWN)
        return

    weapon_info = ASC_WEAPON_TYPES[weapon_type]
    is_fixed_roll = weapon_info.get("fixed_roll", False)

    roll = None
    if not is_fixed_roll:
        try:
            roll = int(left_args[1])
            if roll < 6 or roll > 11:
                await update.message.reply_text("❌ У этого типа оружия значения ролла только 6-11",
                                                parse_mode=ParseMode.MARKDOWN)
                return
        except ValueError:
            await update.message.reply_text(f"❌ Ролл ({left_args[1]}) должен быть числом.",
                                            parse_mode=ParseMode.MARKDOWN)
            return

    try:
        target_level = int(right_args[0])
        if target_level > 45 or target_level < 0:
            await update.message.reply_text(f"❌ Уровень ({right_args[0]}) не соответствует 0-45.",
                                            parse_mode=ParseMode.MARKDOWN)
            return
    except ValueError:
        await update.message.reply_text(f"❌ Уровень ({right_args[0]}) должен быть числом.",
                                        parse_mode=ParseMode.MARKDOWN)
        return

    is_corrupted = right_args[1].lower() == 'y'

    reforge_name = "None"
    reforge_mult = 1.0
    if len(right_args) == 3:
        reforge_input = right_args[2]
        found_reforge = False
        for k_ref in REFORGE_MODIFIERS:
            if k_ref.lower() == reforge_input.lower():
                reforge_name = k_ref
                reforge_mult = REFORGE_MODIFIERS[k_ref]
                found_reforge = True
                break
        if not found_reforge:
            await update.message.reply_text(f"❌ Неизвестный Reforge ({reforge_input}), напишите !reforge для списка.",
                                            parse_mode=ParseMode.MARKDOWN)
            return

    try:
        if is_fixed_roll:
            base_dmg = weapon_info["base_dmg"]
            roll_display = "У этого типа исключительно 11 ролл"
        else:
            base_dmg = weapon_info["stats"][roll]
            roll_display = f"{roll}/11"  # УБРАН <code> ТЕГ

        dmg_at_level = calculate_weapon_stat_at_level(base_dmg, target_level, is_corrupted, reforge_mult)
        total_gold = calculate_gold(ASC_BASE_UPGRADE_COST, target_level)

        response = (
            f"📊 <b>Прогноз {weapon_info['name']}</b>\n\n"
            f"<b>ROLL:</b> {roll_display}\n"
            f"<b>Reforge:</b> <i>{reforge_name}</i>\n"
            f"<b>Corrupted:</b> <i>{'Да' if is_corrupted else 'Нет'}</i>\n"
            f"<b>Upgrade:</b> <i>{target_level}</i> (Макс: 45)\n"
            f"<b>Gold to spend:</b> <i>{total_gold:,}</i> 💰\n\n"
            f"<b>DMG:</b> <i>{dmg_at_level:,}</i>"
        )

        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


async def l_analyze_weapon_asc(update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для !lasc с новым форматом: !lasc {type} [ролл] {upg} {y/n} {reforge} > {upg} {y/n} {reforge}
    Для w (Wooden Sword) ролл не нужен: !lasc w {upg} {y/n} {reforge} > {upg} {y/n} {reforge}"""
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args_raw = context.args
    errors = []

    # Проверка разделителя
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

        # Проверяем тип оружия для определения количества аргументов слева
        if len(left_args) > 0:
            weapon_type = left_args[0].lower()
            if weapon_type == 'w':
                # Для Wooden Sword: тип, урон, y/n, [reforge] (3 или 4 аргумента)
                if len(left_args) not in (3, 4):
                    errors.append(
                        f"❌ Для типа 'w' ожидается: тип, урон, y/n, [reforge]. Формат: w {{upg}} {{y/n}} {{reforge}}")
            else:
                # Для остальных типов: тип, ролл, урон, y/n, [reforge] (4 или 5 аргументов)
                if len(left_args) not in (4, 5):
                    errors.append(f"❌ Для типа '{weapon_type}' ожидается: тип, ролл, урон, y/n, [reforge].")

        # Правая часть: 2 или 3 аргумента
        if len(right_args) not in (2, 3):
            errors.append(f"❌ Правая часть: неверное количество аргументов ({len(right_args)}). Ожидается 2 или 3.")

    if errors:
        example = f"`{command_name}` {{type}} [ролл] {{upg}} {{y/n}} {{reforge}} > {{upg}} {{y/n}} {{reforge}}\n\nДля Wooden Sword: `{command_name} w {{upg}} {{y/n}} {{reforge}} > {{upg}} {{y/n}} {{reforge}}`\nДля остальных: `{command_name} {{type}} {{ролл}} {{upg}} {{y/n}} {{reforge}} > {{upg}} {{y/n}} {{reforge}}`"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example}\n\n**Типы оружия:**\n"
        error_message += "w - Wooden Sword (без ролла)\n"
        error_message += "d - Dual Daggers\n"
        error_message += "t - Poseidon's Trident\n"
        error_message += "k - Lightning Katana\n"
        error_message += "e - Magma's Edge\n"
        error_message += "m - Menta Blade V2"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    # Парсинг типа оружия
    weapon_type = left_args[0].lower()
    if weapon_type not in ASC_WEAPON_TYPES:
        await update.message.reply_text(f"❌ Неизвестный тип ASC оружия '{weapon_type}'. Используйте: w/d/t/k/e/m",
                                        parse_mode=ParseMode.MARKDOWN)
        return

    weapon_info = ASC_WEAPON_TYPES[weapon_type]
    is_fixed_roll = weapon_info.get("fixed_roll", False)

    # Смещение индексов в зависимости от наличия ролла
    # Для w: left_args = [type, upg, y/n, reforge(optional)]
    # Для остальных: left_args = [type, roll, upg, y/n, reforge(optional)]
    roll_offset = 0 if is_fixed_roll else 1

    # Парсинг ролла (только для не-w типов)
    curr_roll = None
    if not is_fixed_roll:
        try:
            curr_roll = int(left_args[1])
            if curr_roll < 6 or curr_roll > 11:
                await update.message.reply_text("❌ У этого типа оружия значения ролла только 6-11",
                                                parse_mode=ParseMode.MARKDOWN)
                return
        except ValueError:
            await update.message.reply_text(f"❌ Ролл ({left_args[1]}) должен быть числом.",
                                            parse_mode=ParseMode.MARKDOWN)
            return

    # Парсинг текущего уровня
    try:
        curr_upg = int(left_args[1 + roll_offset])
        if not 0 <= curr_upg <= 45:
            await update.message.reply_text(f"❌ Текущий UPG ({left_args[1 + roll_offset]}) не в 0-45.",
                                            parse_mode=ParseMode.MARKDOWN)
            return
    except ValueError:
        await update.message.reply_text(f"❌ Текущий UPG ({left_args[1 + roll_offset]}) должен быть числом.",
                                        parse_mode=ParseMode.MARKDOWN)
        return

    # Парсинг текущего corrupted
    curr_corr_str = left_args[2 + roll_offset].lower()
    if curr_corr_str not in ('y', 'n'):
        await update.message.reply_text(f"❌ Текущий corrupted ({curr_corr_str}) должен быть 'y' или 'n'.",
                                        parse_mode=ParseMode.MARKDOWN)
        return

    # Reforge левой части
    curr_ref_name = "None"
    curr_ref_mult = 1.0
    if len(left_args) == (4 + roll_offset):
        reforge_input = left_args[3 + roll_offset]
        found = False
        for k in REFORGE_MODIFIERS:
            if k.lower() == reforge_input.lower():
                curr_ref_name = k
                curr_ref_mult = REFORGE_MODIFIERS[k]
                found = True
                break
        if not found:
            await update.message.reply_text(f"❌ Текущий reforge ({reforge_input}) неизвестен.",
                                            parse_mode=ParseMode.MARKDOWN)
            return

    # Парсинг правой части
    try:
        des_upg = int(right_args[0])
        if not 0 <= des_upg <= 45:
            await update.message.reply_text(f"❌ Желаемый UPG ({right_args[0]}) не в 0-45.",
                                            parse_mode=ParseMode.MARKDOWN)
            return
    except ValueError:
        await update.message.reply_text(f"❌ Желаемый UPG ({right_args[0]}) должен быть числом.",
                                        parse_mode=ParseMode.MARKDOWN)
        return

    des_corr_str = right_args[1].lower()
    if des_corr_str not in ('y', 'n'):
        await update.message.reply_text(f"❌ Желаемый corrupted ({des_corr_str}) должен быть 'y' или 'n'.",
                                        parse_mode=ParseMode.MARKDOWN)
        return

    # Reforge правой части
    des_ref_name = "None"
    des_ref_mult = 1.0
    if len(right_args) == 3:
        reforge_input = right_args[2]
        found = False
        for k in REFORGE_MODIFIERS:
            if k.lower() == reforge_input.lower():
                des_ref_name = k
                des_ref_mult = REFORGE_MODIFIERS[k]
                found = True
                break
        if not found:
            await update.message.reply_text(f"❌ Желаемый reforge ({reforge_input}) неизвестен.",
                                            parse_mode=ParseMode.MARKDOWN)
            return

    # Правило: нельзя декорраптить
    if curr_corr_str == 'y' and des_corr_str == 'n':
        await update.message.reply_text("❌ Нельзя декорраптить (y > n запрещено).",
                                        parse_mode=ParseMode.MARKDOWN)
        return

    # --- ЛОГИКА РАСЧЕТА ---
    try:
        if is_fixed_roll:
            base_dmg = weapon_info["base_dmg"]
            roll_display = f"У этого типа исключительно 11 ролл"
        else:
            base_dmg = weapon_info["stats"][curr_roll]
            roll_display = f"{curr_roll}/11"  # УБРАН <code> ТЕГ

        curr_corr = curr_corr_str == 'y'
        des_corr = des_corr_str == 'y'

        # Текущие значения
        curr_stat = calculate_weapon_stat_at_level(base_dmg, curr_upg, curr_corr, curr_ref_mult)
        curr_spent = calculate_gold(ASC_BASE_UPGRADE_COST, curr_upg)

        # Желаемые значения
        des_stat = calculate_weapon_stat_at_level(base_dmg, des_upg, des_corr, des_ref_mult)
        des_needed = max(0, calculate_gold(ASC_BASE_UPGRADE_COST, des_upg) - curr_spent)

        curr_corr_text = 'Да' if curr_corr else 'Нет'
        des_corr_text = 'Да' if des_corr else 'Нет'

        response = (
            f"📊 <b>Анализ {weapon_info['name']}</b>\n"
            f"ROLL: {roll_display}\n\n"
            f"<b>UPG:</b> <i>{curr_upg}</i> > <i>{des_upg}</i>\n"
            f"<b>REFORGE:</b> <i>{curr_ref_name}</i> > <i>{des_ref_name}</i>\n"
            f"<b>Corrupted:</b> <i>{curr_corr_text}</i> > <i>{des_corr_text}</i>\n\n"
            f"<b>DMG:</b> <i>{curr_stat:,}</i> > <i>{des_stat:,}</i> ⚔️\n"
            f"<b>GOLD (Потрачено / Осталось):</b> 💰\n"
            f"       <i>{curr_spent:,}</i> / <i>{des_needed:,}</i>"
        )
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


# --- ФУНКЦИИ ПРОГНОЗИРОВАНИЯ (СТАРЫЕ КОМАНДЫ: !wconq, !wdoom, !wfzhelm, и.т.д.) ---

async def w_analyze_weapon(update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
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
            return

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
        example = f"`{command_name}` {{roll}} > {{upg до {max_lvl}}} {{y/n}} {{reforge}} \n(если reforge нет - не пишите)"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example}"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    roll = int(args[0])
    target_level = int(args[1])
    is_corrupted = args[2].lower() == 'y'

    try:
        base_stats = item_info['stats']
        b1 = item_info['upgrade_cost_lvl1']

        base_dmg = base_stats[roll]
        dmg_at_level = calculate_weapon_stat_at_level(base_dmg, target_level, is_corrupted, reforge_mult)
        total_gold = calculate_gold(b1, target_level)

        response = (
            f"📊 <b>Прогноз {item_info['name']}</b>\n\n"
            f"<b>ROLL:</b> <i>{roll}</i>\n"
            f"<b>Reforge:</b> <i>{reforge_name}</i>\n"
            f"<b>Corrupted:</b> <i>{'Да' if is_corrupted else 'Нет'}</i>\n"
            f"<b>Upgrade:</b> <i>{target_level}</i> (Макс: {max_lvl})\n"
            f"<b>Gold to spend:</b> <i>{total_gold:,}</i> 💰\n\n"
            f"<b>DMG:</b> <i>{dmg_at_level:,}</i>"
        )
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


async def w_analyze_armor(update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args_raw = context.args
    item_info = ITEMS_MAPPING[item_key]
    max_lvl = item_info['max_level']
    errors = []

    part_key = None
    for key in PART_MAPPING:
        if command_name.endswith(key):
            part_key = key
            break
    if part_key is None:
        await update.message.reply_text("Не удалось определить часть брони.")
        return

    part_name = PART_MAPPING[part_key]
    russian_part = {"Helmet": "Шлем", "Chestplate": "Нагрудник", "Leggings": "Поножи"}[part_name]

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
        if len(right_args) != 2:
            errors.append(f"❌ Правая часть: неверное количество аргументов ({len(right_args)}). Ожидается 2.")

    if errors:
        example = f"`{command_name}` {{roll}} > {{upg}} {{y/n}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    try:
        roll = int(left_args[0])
        if not 1 <= roll <= 11:
            errors.append(f"❌ Ролл ({left_args[0]}) не в 1-11.")
    except ValueError:
        errors.append(f"❌ Ролл ({left_args[0]}) должен быть числом.")

    try:
        target_level = int(right_args[0])
        if not 0 <= target_level <= max_lvl:
            errors.append(f"❌ UPG ({right_args[0]}) не в 0-{max_lvl}.")
    except ValueError:
        errors.append(f"❌ UPG ({right_args[0]}) должен быть числом.")

    is_corrupted_str = right_args[1].lower()
    if is_corrupted_str not in ('y', 'n'):
        errors.append(f"❌ Corrupted ({is_corrupted_str}) должен быть 'y' или 'n'.")

    if errors:
        example = f"`{command_name}` {{roll}} > {{upg}} {{y/n}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    roll = int(left_args[0])
    target_level = int(right_args[0])
    is_corrupted = is_corrupted_str == 'y'

    try:
        base_stats = item_info['stats'][part_name]
        b1 = item_info['upgrade_cost_lvl1']

        base_hp = base_stats[roll]
        hp_at_level = calculate_armor_stat_at_level(base_hp, target_level, is_corrupted, 1.0, "armor")
        total_gold = calculate_gold(b1, target_level)

        response = (
            f"🛡️ <b>Прогноз {item_info['name']} — {russian_part}</b>\n\n"
            f"<b>ROLL:</b> <i>{roll}</i>\n"
            f"<b>Corrupted:</b> <i>{'Да' if is_corrupted else 'Нет'}</i>\n"
            f"<b>Upgrade:</b> <i>{target_level}</i> (Макс: {max_lvl})\n"
            f"<b>Gold to spend:</b> <i>{total_gold:,}</i> 💰\n\n"
            f"<b>HP:</b> <i>{int(hp_at_level):,}</i>"
        )
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


async def w_analyze_full_set(update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args_raw = context.args
    item_info = ITEMS_MAPPING[item_key]
    max_lvl = item_info['max_level']
    errors = []

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

        if len(left_args) != 3:
            errors.append(f"❌ Левая часть: неверное количество аргументов ({len(left_args)}). Ожидается 3.")
        if len(right_args) != 6:
            errors.append(f"❌ Правая часть: неверное количество аргументов ({len(right_args)}). Ожидается 6.")

    if errors:
        example = f"`{command_name}` {{roll1}} {{roll2}} {{roll3}} > {{upg1}} {{upg2}} {{upg3}} {{y/n1}} {{y/n2}} {{y/n3}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    parts_order = ["Helmet", "Chestplate", "Leggings"]
    rus_names_nominative = ["Шлем", "Нагрудник", "Штаны"]

    rolls = []
    target_upgs = []
    target_corrs = []

    for i in range(3):
        try:
            roll = int(left_args[i])
            if not 1 <= roll <= 11:
                errors.append(f"❌ Ролл {rus_names_nominative[i]} ({left_args[i]}) не в 1-11.")
            rolls.append(roll)
        except ValueError:
            errors.append(f"❌ Ролл {rus_names_nominative[i]} ({left_args[i]}) должен быть числом.")

        try:
            upg = int(right_args[i])
            if not 0 <= upg <= max_lvl:
                errors.append(f"❌ UPG {rus_names_nominative[i]} ({right_args[i]}) не в 0-{max_lvl}.")
            target_upgs.append(upg)
        except ValueError:
            errors.append(f"❌ UPG {rus_names_nominative[i]} ({right_args[i]}) должен быть числом.")

        corr_str = right_args[i + 3].lower()
        if corr_str not in ('y', 'n'):
            errors.append(f"❌ Corrupted {rus_names_nominative[i]} ({right_args[i + 3]}) должен быть 'y' или 'n'.")
        target_corrs.append(corr_str == 'y')

    if errors:
        example = f"`{command_name}` {{roll1}} {{roll2}} {{roll3}} > {{upg1}} {{upg2}} {{upg3}} {{y/n1}} {{y/n2}} {{y/n3}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    try:
        stats_db = item_info['stats']
        b1 = item_info['upgrade_cost_lvl1']

        total_hp = 0
        total_gold = 0
        results = []

        for i, part_key in enumerate(parts_order):
            base = stats_db[part_key][rolls[i]]
            hp_at_level = calculate_armor_stat_at_level(base, target_upgs[i], target_corrs[i], 1.0, "armor")
            gold_needed = calculate_gold(b1, target_upgs[i])
            total_hp += hp_at_level
            total_gold += gold_needed

            results.append({
                "rus_name": rus_names_nominative[i],
                "roll": rolls[i],
                "base_hp": base,
                "upg": target_upgs[i],
                "corr_text": 'Да' if target_corrs[i] else 'Нет',
                "hp": hp_at_level,
                "gold": gold_needed
            })

        response = f"🛡️ <b>Прогноз {item_info['name']}</b>\n\n"
        response += "<b>🎯 ИТОГИ</b>\n"
        response += f"<b>HP:</b> <i>{int(total_hp):,}</i> ❤️\n"
        response += f"<b>GOLD:</b> <i>{total_gold:,}</i> 💰\n\n"

        response += "<b>📝 ДЕТАЛИ</b>\n"
        for res in results:
            response += (
                f"<b>{res['rus_name']}</b>\n"
                f"<b>ROLL:</b> <i>{res['roll']}/11</i> | <b>BASE HP:</b> <i>{int(res['base_hp']):,}</i>\n"
                f"<b>UPG:</b> <i>{res['upg']}</i>\n"
                f"<b>Corrupted:</b> <i>{res['corr_text']}</i>\n"
                f"<b>HP:</b> <i>{int(res['hp']):,}</i> ❤️\n"
                f"<b>GOLD:</b> <i>{res['gold']:,}</i> 💰\n\n"
            )

        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


# --- L-ФУНКЦИИ (СРАВНЕНИЕ) ---

async def l_analyze_weapon(update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args_raw = context.args
    item_info = ITEMS_MAPPING[item_key]
    max_lvl = item_info['max_level']
    errors = []

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

        if len(left_args) not in (3, 4):
            errors.append(f"❌ Левая часть: неверное количество аргументов ({len(left_args)}). Ожидается 3 или 4.")
        if len(right_args) not in (2, 3):
            errors.append(f"❌ Правая часть: неверное количество аргументов ({len(right_args)}). Ожидается 2 или 3.")

    if errors:
        example = f"`{command_name}` {{roll}} {{upg}} {{y/n}} [reforge] > {{upg}} {{y/n}} [reforge]"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    curr_ref_name = "None"
    curr_ref_mult = 1.0
    des_ref_name = "None"
    des_ref_mult = 1.0

    try:
        curr_roll = int(left_args[0])
        if not 1 <= curr_roll <= 11:
            errors.append(f"❌ Ролл ({left_args[0]}) не в 1-11.")
    except ValueError:
        errors.append(f"❌ Ролл ({left_args[0]}) должен быть числом.")

    try:
        curr_upg = int(left_args[1])
        if not 0 <= curr_upg <= max_lvl:
            errors.append(f"❌ Текущий UPG ({left_args[1]}) не в 0-{max_lvl}.")
    except ValueError:
        errors.append(f"❌ Текущий UPG ({left_args[1]}) должен быть числом.")

    curr_corr_str = left_args[2].lower()
    if curr_corr_str not in ('y', 'n'):
        errors.append(f"❌ Текущий corrupted ({curr_corr_str}) должен быть 'y' или 'n'.")

    if len(left_args) == 4:
        reforge_input = left_args[3]
        found = False
        for k in REFORGE_MODIFIERS:
            if k.lower() == reforge_input.lower():
                curr_ref_name = k
                curr_ref_mult = REFORGE_MODIFIERS[k]
                found = True
                break
        if not found:
            errors.append(f"❌ Текущий reforge ({reforge_input}) неизвестен.")

    try:
        des_upg = int(right_args[0])
        if not 0 <= des_upg <= max_lvl:
            errors.append(f"❌ Желаемый UPG ({right_args[0]}) не в 0-{max_lvl}.")
    except ValueError:
        errors.append(f"❌ Желаемый UPG ({right_args[0]}) должен быть числом.")

    des_corr_str = right_args[1].lower()
    if des_corr_str not in ('y', 'n'):
        errors.append(f"❌ Желаемый corrupted ({des_corr_str}) должен быть 'y' или 'n'.")

    if len(right_args) == 3:
        reforge_input = right_args[2]
        found = False
        for k in REFORGE_MODIFIERS:
            if k.lower() == reforge_input.lower():
                des_ref_name = k
                des_ref_mult = REFORGE_MODIFIERS[k]
                found = True
                break
        if not found:
            errors.append(f"❌ Желаемый reforge ({reforge_input}) неизвестен.")

    if curr_corr_str == 'y' and des_corr_str == 'n':
        errors.append("❌ Нельзя декорраптить (y > n запрещено).")

    if errors:
        example = f"`{command_name}` {{roll}} {{upg}} {{y/n}} [reforge] > {{upg}} {{y/n}} [reforge]"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    curr_roll = int(left_args[0])
    curr_upg = int(left_args[1])
    curr_corr = curr_corr_str == 'y'
    des_upg = int(right_args[0])
    des_corr = des_corr_str == 'y'

    try:
        base_stats = item_info['stats']
        base_val = base_stats[curr_roll]
        b1 = item_info['upgrade_cost_lvl1']

        curr_stat = calculate_weapon_stat_at_level(base_val, curr_upg, curr_corr, curr_ref_mult)
        curr_spent = calculate_gold(b1, curr_upg)

        des_stat = calculate_weapon_stat_at_level(base_val, des_upg, des_corr, des_ref_mult)
        des_needed = max(0, calculate_gold(b1, des_upg) - curr_spent)

        curr_corr_text = 'Да' if curr_corr else 'Нет'
        des_corr_text = 'Да' if des_corr else 'Нет'

        response = (
            f"📊 <b>Анализ {item_info['name']}</b>\n"
            f"<b>ROLL:</b> <i>{curr_roll}/11</i>\n\n"
            f"<b>UPG:</b> <i>{curr_upg}</i> > <i>{des_upg}</i>\n"
            f"<b>REFORGE:</b> <i>{curr_ref_name}</i> > <i>{des_ref_name}</i>\n"
            f"<b>Corrupted:</b> <i>{curr_corr_text}</i> > <i>{des_corr_text}</i>\n\n"
            f"<b>DMG:</b> <i>{curr_stat:,}</i> > <i>{des_stat:,}</i> ⚔️\n"
            f"<b>GOLD (Потрачено / Осталось):</b> 💰\n"
            f"       <i>{curr_spent:,}</i> / <i>{des_needed:,}</i>"
        )
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


async def l_analyze_armor(update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    """Обработчик для сравнения брони: !l[тип_брони] {roll} {upg} {y/n} > {upg} {y/n}"""
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args_raw = context.args
    item_info = ITEMS_MAPPING[item_key]
    max_lvl = item_info['max_level']
    errors = []

    # Determine part
    part_key = None
    for key in PART_MAPPING:
        if command_name.endswith(key):
            part_key = key
            break

    if part_key is None:
        await update.message.reply_text("Не удалось определить часть брони.")
        return

    part_name = PART_MAPPING[part_key]
    russian_part = {"Helmet": "Шлем", "Chestplate": "Нагрудник", "Leggings": "Поножи"}[part_name]

    # Find separator
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

        if len(left_args) != 3:
            errors.append(f"❌ Левая часть: неверное количество аргументов ({len(left_args)}). Ожидается 3.")
        if len(right_args) != 2:
            errors.append(f"❌ Правая часть: неверное количество аргументов ({len(right_args)}). Ожидается 2.")

    if errors:
        example = f"`{command_name}` {{roll}} {{upg}} {{y/n}} > {{upg}} {{y/n}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    # Parse left
    try:
        curr_roll = int(left_args[0])
        if not 1 <= curr_roll <= 11:
            errors.append(f"❌ Текущий ролл ({left_args[0]}) не в 1-11.")
    except ValueError:
        errors.append(f"❌ Текущий ролл ({left_args[0]}) должен быть числом.")

    try:
        curr_upg = int(left_args[1])
        if not 0 <= curr_upg <= max_lvl:
            errors.append(f"❌ Текущий UPG ({left_args[1]}) не в 0-{max_lvl}.")
    except ValueError:
        errors.append(f"❌ Текущий UPG ({left_args[1]}) должен быть числом.")

    curr_corr_str = left_args[2].lower()
    if curr_corr_str not in ('y', 'n'):
        errors.append(f"❌ Текущий corrupted ({curr_corr_str}) должен быть 'y' или 'n'.")

    # Parse right
    try:
        des_upg = int(right_args[0])
        if not 0 <= des_upg <= max_lvl:
            errors.append(f"❌ Желаемый UPG ({right_args[0]}) не в 0-{max_lvl}.")
    except ValueError:
        errors.append(f"❌ Желаемый UPG ({right_args[0]}) должен быть числом.")

    des_corr_str = right_args[1].lower()
    if des_corr_str not in ('y', 'n'):
        errors.append(f"❌ Желаемый corrupted ({des_corr_str}) должен быть 'y' или 'n'.")

    # Rule
    if curr_corr_str == 'y' and des_corr_str == 'n':
        errors.append("❌ Нельзя декорраптить (y > n запрещено).")

    if errors:
        example = f"`{command_name}` {{roll}} {{upg}} {{y/n}} > {{upg}} {{y/n}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    # Calculation
    try:
        base_stats = item_info['stats'][part_name]
        base_val = base_stats[curr_roll]
        b1 = item_info['upgrade_cost_lvl1']

        # Current
        curr_stat = calculate_armor_stat_at_level(base_val, curr_upg, curr_corr_str == 'y', 1.0, "armor")
        curr_spent = calculate_gold(b1, curr_upg)

        # Desired
        des_stat = calculate_armor_stat_at_level(base_val, des_upg, des_corr_str == 'y', 1.0, "armor")
        des_needed = max(0, calculate_gold(b1, des_upg) - curr_spent)

        curr_corr_text = 'Да' if curr_corr_str == 'y' else 'Нет'
        des_corr_text = 'Да' if des_corr_str == 'y' else 'Нет'

        response = (
            f"🛡️ <b>Анализ {item_info['name']} — {russian_part}</b>\n"
            f"<b>ROLL:</b> <i>{curr_roll}/11</i>\n\n"
            f"<b>UPG:</b> <i>{curr_upg}</i> > <i>{des_upg}</i>\n"
            f"<b>Corrupted:</b> <i>{curr_corr_text}</i> > <i>{des_corr_text}</i>\n\n"
            f"<b>HP:</b> <i>{int(curr_stat):,}</i> > <i>{int(des_stat):,}</i> ❤️\n"
            f"<b>GOLD (Потрачено / Осталось):</b> 💰\n"
            f"       <i>{curr_spent:,}</i> / <i>{des_needed:,}</i> "
        )
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


async def l_analyze_full_set(update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args_raw = context.args
    item_info = ITEMS_MAPPING[item_key]
    max_lvl = item_info['max_level']
    errors = []

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

        if len(left_args) != 9:
            errors.append(f"❌ Левая часть: неверное количество аргументов ({len(left_args)}). Ожидается 9.")
        if len(right_args) != 6:
            errors.append(f"❌ Правая часть: неверное количество аргументов ({len(right_args)}). Ожидается 6.")

    if errors:
        example = f"`{command_name}` {{roll1}} {{roll2}} {{roll3}} {{upg1}} {{upg2}} {{upg3}} {{y/n1}} {{y/n2}} {{y/n3}} > {{upg4}} {{upg5}} {{upg6}} {{y/n4}} {{y/n5}} {{y/n6}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    parts_order = ["Helmet", "Chestplate", "Leggings"]
    rus_names_nominative = ["Шлем", "Нагрудник", "Штаны"]

    curr_rolls = []
    curr_upgs = []
    curr_corrs = []
    des_upgs = []
    des_corrs = []

    for i in range(3):
        try:
            roll = int(left_args[i])
            if not 1 <= roll <= 11:
                errors.append(f"❌ Ролл {rus_names_nominative[i]} ({left_args[i]}) не в 1-11.")
            curr_rolls.append(roll)
        except ValueError:
            errors.append(f"❌ Ролл {rus_names_nominative[i]} ({left_args[i]}) должен быть числом.")

        try:
            upg = int(left_args[i + 3])
            if not 0 <= upg <= max_lvl:
                errors.append(f"❌ Текущий UPG {rus_names_nominative[i]} ({left_args[i + 3]}) не в 0-{max_lvl}.")
            curr_upgs.append(upg)
        except ValueError:
            errors.append(f"❌ Текущий UPG {rus_names_nominative[i]} ({left_args[i + 3]}) должен быть числом.")

        corr_str = left_args[i + 6].lower()
        if corr_str not in ('y', 'n'):
            errors.append(f"❌ Текущий corrupted {rus_names_nominative[i]} ({left_args[i + 6]}) должен быть 'y' или 'n'.")
        curr_corrs.append(corr_str == 'y')

    for i in range(3):
        try:
            upg = int(right_args[i])
            if not 0 <= upg <= max_lvl:
                errors.append(f"❌ Желаемый UPG {rus_names_nominative[i]} ({right_args[i]}) не в 0-{max_lvl}.")
            des_upgs.append(upg)
        except ValueError:
            errors.append(f"❌ Желаемый UPG {rus_names_nominative[i]} ({right_args[i]}) должен быть числом.")

        corr_str = right_args[i + 3].lower()
        if corr_str not in ('y', 'n'):
            errors.append(f"❌ Желаемый corrupted {rus_names_nominative[i]} ({right_args[i + 3]}) должен быть 'y' или 'n'.")
        des_corrs.append(corr_str == 'y')

    for i in range(3):
        if curr_corrs[i] and not des_corrs[i]:
            errors.append(f"❌ {rus_names_nominative[i]}: нельзя декорраптить (y > n запрещено).")

    if errors:
        example = f"`{command_name}` {{roll1}} {{roll2}} {{roll3}} {{upg1}} {{upg2}} {{upg3}} {{y/n1}} {{y/n2}} {{y/n3}} > {{upg4}} {{upg5}} {{upg6}} {{y/n4}} {{y/n5}} {{y/n6}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    try:
        stats_db = item_info['stats']
        b1 = item_info['upgrade_cost_lvl1']

        curr_total_hp = 0
        des_total_hp = 0
        curr_total_spent = 0
        des_total_needed = 0
        results = []

        for i, part_key in enumerate(parts_order):
            base_val = stats_db[part_key][curr_rolls[i]]

            curr_stat = calculate_armor_stat_at_level(base_val, curr_upgs[i], curr_corrs[i], 1.0, "armor")
            curr_spent = calculate_gold(b1, curr_upgs[i])

            des_stat = calculate_armor_stat_at_level(base_val, des_upgs[i], des_corrs[i], 1.0, "armor")
            des_needed = max(0, calculate_gold(b1, des_upgs[i]) - curr_spent)

            curr_total_hp += curr_stat
            des_total_hp += des_stat
            curr_total_spent += curr_spent
            des_total_needed += des_needed

            curr_corr_text = 'Да' if curr_corrs[i] else 'Нет'
            des_corr_text = 'Да' if des_corrs[i] else 'Нет'

            results.append({
                "rus_name": rus_names_nominative[i],
                "roll": curr_rolls[i],
                "base_val": base_val,
                "curr_upg": curr_upgs[i],
                "des_upg": des_upgs[i],
                "curr_corr_text": curr_corr_text,
                "des_corr_text": des_corr_text,
                "curr_stat": curr_stat,
                "des_stat": des_stat,
                "curr_spent": curr_spent,
                "des_needed": des_needed
            })

        response = f"🛡️ <b>Анализ {item_info['name']}</b>\n\n"

        response += "<b>🎯 ИТОГИ</b>\n"
        response += f"<b>HP:</b> <i>{int(curr_total_hp):,}</i> > <i>{int(des_total_hp):,}</i> ❤️\n"
        response += f"<b>GOLD:</b> <i>{curr_total_spent:,}</i> / <i>{des_total_needed:,}</i> 💰\n\n"

        response += "<b>📝 ДЕТАЛИ</b>\n"
        for res in results:
            response += (
                f"<b>{res['rus_name']}</b>\n"
                f"<b>ROLL:</b> <i>{res['roll']}/11</i> | <b>BASE HP:</b> <i>{int(res['base_val']):,}</i>\n"
                f"<b>UPG:</b> <i>{res['curr_upg']}</i> > <i>{res['des_upg']}</i>\n"
                f"<b>Corrupted:</b> <i>{res['curr_corr_text']}</i> > <i>{res['des_corr_text']}</i>\n"
                f"<b>HP:</b> <i>{int(res['curr_stat']):,}</i> > <i>{int(res['des_stat']):,}</i> ❤️\n"
                f"<b>GOLD:</b> <i>{res['curr_spent']:,}</i> / <i>{res['des_needed']:,}</i> 💰\n\n"
            )

        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


# --- ТАБЛИЦЫ РОЛЛОВ ---

def fmt(val):
    """Форматирует числа: 8032.5 -> 8,032.5"""
    if val == int(val):
        return f"{int(val):,}"
    return f"{val:,.2f}".rstrip('0').rstrip('.')


def print_rolls_info(title, stats_dict):
    """Вывод для оружия (Ролл | Значение / Коррупт)"""
    header = f"<b>{title}</b>\n(Обычное / Коррупт. значение)\n"
    # Фиксируем ширину заголовка значений, чтобы палки не гуляли
    table_header = f"<code>{'Ролл':<5} | {'Значение / Коррупт'}</code>"

    rows = []
    for roll, val in sorted(stats_dict.items()):
        v_str = f"{fmt(val)} / {fmt(val * 1.5)}"
        # {:<20} гарантирует, что блок с числами всегда будет одной длины
        rows.append(f"<code>{str(roll):<5} | {v_str:<20}</code>")

    return f"{header}\n{table_header}\n" + "\n".join(rows)


def print_armor_info(title, armor_dict):
    """Вывод для брони (Ролл | Шлем | Нагр. | Поножи)"""
    header = f"<b>{title}</b>\n(Обычное/Коррупт. значение)\n\n"
    # Увеличиваем первый слот до 5 символов, остальные по 13
    table_header = f"<code>{'Ролл':<5} | {'Шлем':<13} | {'Нагрудник':<13} | {'Поножи':<13}</code>\n"

    rows = []
    for r in range(1, 12):
        h = f"{fmt(armor_dict['Helmet'][r])}/{fmt(armor_dict['Helmet'][r] * 1.5)}"
        c = f"{fmt(armor_dict['Chestplate'][r])}/{fmt(armor_dict['Chestplate'][r] * 1.5)}"
        l = f"{fmt(armor_dict['Leggings'][r])}/{fmt(armor_dict['Leggings'][r] * 1.5)}"

        # Сборка строки: Ролл (5 симв) + Шлем (13) + Нагр (13) + Поножи (13)
        row = f"<code>{str(r):<5} | {h:<13} | {c:<13} | {l:<13}</code>"
        rows.append(row)

    return header + table_header + "\n".join(rows)

# --- КОНСТАНТЫ ДЛЯ UI МЕНЮ ПОМОЩИ ---
CALLBACK_MAIN = "help_main"
CALLBACK_CURRENT = "help_current"
CALLBACK_W = "help_w"
CALLBACK_L = "help_l"
CALLBACK_CLOSE = "help_close"


# Функции для генерации текста каждой страницы помощи
def get_main_page_text():
    return """Создатель бота - H2O (YarreYT)

*Общие правила:*
(y/n): y - corrupted, n - НЕ corrupted.

*Таблицы роллов:*
`!crhelp` - Показать это меню
`!reforge` - Список множителей Reforge
`!doomr` - Список роллов Дума (Doombringer)
`!conqr` - Список роллов Конки (Conqueror's Blade)
`!fzr` - Список роллов Furious Zeus Set (броня)
`!zr` - Список роллов Zeus Set (броня)"""


def get_current_page_text():
    return """Создатель бота - H2O (YarreYT)

*Общие правила:*
(y/n): y - corrupted, n - НЕ corrupted.

*Анализ текущего предмета(!...)*

*Обычное оружие:*
`!conq` / `!doom` {dmg} {upg} {y/n} {reforge}

*ASC оружие:*
`!asc` {w/d/t/k/e/m} {dmg} {upg} {y/n} {reforge}
 w - Wooden Sword
 d - Dual Daggers 
 t - Poseidon's Trident 
 k - Lightning Katana 
 e - Magma's Edge 
 m - Menta Blade V2 

*Броня:* 
`!fzhelm` / `!fzchest` / `!fzleg` - Furious Zeus Mythic
`!zhelm` / `!zchest` / `!zleg` - Zeus Legendary
 _Формат:_ {hp} {upg} {y/n}

`!fzset` / `!zset`
 _Формат:_ {hp1} {hp2} {hp3} {upg1] {upg2} {upg3} {y/n1} {y/n2} {y/n3}"""


def get_w_page_text():
    return """Создатель бота - H2O (YarreYT)

*Общие правила:*
(y/n): y - corrupted, n - НЕ corrupted.

*Прогноз желаемых результатов(!w...)*

*Обычное оружие:*
`!wconq` / `!wdoom` {ролл} > {upg} {y/n} {reforge}

*ASC оружие:*
`!wasc` {w/d/t/k/e/m} {ролл} > {upg} {y/n} {reforge}
 w - Wooden Sword: ролл писать не нужно !!!
 d - Dual Daggers 
 t - Poseidon's Trident 
 k - Lightning Katana 
 e - Magma's Edge 
 m - Menta Blade V2 

*Броня:*
`!wfzhelm` / `!wfzchest` / `!wfzleg` - Furious Zeus Mythic
`!wzhelm` / `!wzchest` / `!wzleg` - Zeus Legendary 
_Формат:_ {ролл} > {upg} {y/n}

`!wfzset` / `!wzset`
_Формат:_ {ролл1} {ролл2} {ролл3} > {upg1} {upg2} {upg3} {y/n1} {y/n2} {y/n3}"""


def get_l_page_text():
    return """Создатель бота - H2O (YarreYT)

*Общие правила:*
(y/n): y - corrupted, n - НЕ corrupted.

*Сравнение актуальных и желаемых результатов(!l...)*

*Обычное оружие:*
`!lconq` / `!ldoom` {ролл} {upg} {y/n} {reforge} > {upg} {y/n} {reforge}

*ASC оружие:*
`!lasc` {w/d/t/k/e/m} {ролл} {upg} {y/n} {reforge} > {upg} {y/n} {reforge}
 w - Wooden Sword: ролл писать не нужно !!!
 d - Dual Daggers 
 t - Poseidon's Trident 
 k - Lightning Katana 
 e - Magma's Edge 
 m - Menta Blade V2 

*Броня:*
`!lfzhelm` / `!lfzchest` / `!lfzleg` - Furious Zeus Mythic
`!lzhelm` / `!lzchest` / `!lzleg` - Zeus Legendary 
 _Формат:_ {ролл} {upg} {y/n} > {upg} {y/n}

`!lfzset` / `!lzset`
 _Формат:_ {ролл1} {ролл2} {ролл3} {upg1} {upg2} {upg3} {y/n1} {y/n2} {y/n3} > {upg4} {upg5} {upg6} {y/n4} {y/n5} {y/n6}"""


def get_help_keyboard(current_page="main"):
    """Генерация клавиатуры для меню помощи

    Args:
        current_page: Текущая страница ("main", "current", "w", "l")
    """
    # Определяем, какие кнопки должны быть выделены
    main_text = "✓ Main" if current_page == "main" else "Main"
    current_text = "✓ !..." if current_page == "current" else "!..."
    w_text = "✓ !w..." if current_page == "w" else "!w..."
    l_text = "✓ !l..." if current_page == "l" else "!l..."

    keyboard = [
        [InlineKeyboardButton("Свернуть", callback_data=CALLBACK_CLOSE)],
        [
            InlineKeyboardButton(main_text, callback_data=CALLBACK_MAIN),
            InlineKeyboardButton(current_text, callback_data=CALLBACK_CURRENT),
            InlineKeyboardButton(w_text, callback_data=CALLBACK_W),
            InlineKeyboardButton(l_text, callback_data=CALLBACK_L),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


# Обработчик нажатий на кнопки меню помощи
async def help_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    # Проверка топика (работает и для callback'ов)
    if not is_allowed_thread(update):
        return

    await query.answer()  # Убираем "часики" на кнопке

    # Обработка кнопки "Свернуть"
    if query.data == CALLBACK_CLOSE:
        # Удаляем сообщение бота
        await query.message.delete()

        # Пытаемся удалить сообщение пользователя (если есть права)
        if query.message.reply_to_message:
            try:
                await context.bot.delete_message(
                    chat_id=query.message.chat_id,
                    message_id=query.message.reply_to_message.message_id
                )
            except Exception:
                pass  # Не можем удалить - игнорируем
        return

    # Определяем текст и текущую страницу для кнопок
    page_data = {
        CALLBACK_MAIN: ("main", get_main_page_text()),
        CALLBACK_CURRENT: ("current", get_current_page_text()),
        CALLBACK_W: ("w", get_w_page_text()),
        CALLBACK_L: ("l", get_l_page_text()),
    }

    page_info = page_data.get(query.data)
    if not page_info:
        return

    current_page, text = page_info

    # Проверяем, не пытаемся ли мы открыть ту же страницу
    # Извлекаем текущую страницу из текста кнопок в сообщении
    try:
        current_keyboard = query.message.reply_markup.inline_keyboard
        current_buttons = current_keyboard[1]  # Вторая строка с кнопками
        for btn in current_buttons:
            if btn.text.startswith("✓"):
                # Это текущая активная кнопка
                if (btn.callback_data == query.data):
                    # Пользователь нажал на уже активную кнопку, ничего не делаем
                    return
                break
    except (AttributeError, IndexError):
        # Если не удалось определить текущую страницу, продолжаем как обычно
        pass

    # Обновляем сообщение с новым текстом и клавиатурой
    try:
        await query.message.edit_text(
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_help_keyboard(current_page)  # ПЕРЕДАЕМ current_page!
        )
    except Exception as e:
        # Игнорируем все ошибки редактирования (flood control, message not modified и т.д.)
        print(f"Ошибка при редактировании сообщения: {e}")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_thread(update):
        return

    # Отправляем сообщение с главной страницей и клавиатурой
    await update.message.reply_text(
        text=get_main_page_text(),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_help_keyboard("main"),  # Явно указываем "main"
        reply_to_message_id=update.message.message_id
    )


async def cmd_reforge(update, context):
    if not is_allowed_thread(update):
        return

    sorted_reforge = sorted(
        REFORGE_MODIFIERS.items(),
        key=lambda x: x[1],
        reverse=True
    )

    max_len = max(len(name) for name, _ in sorted_reforge)

    output = "✨ <b>Множители Reforge</b> ✨\n\n"
    for name, mult in sorted_reforge:
        output += f"{name.ljust(max_len)} | x<i>{mult}</i>\n"

    await update.message.reply_text(output, parse_mode=ParseMode.HTML)


async def bang_router(update, context: ContextTypes.DEFAULT_TYPE):
    global ALLOWED_THREAD_ID, ALLOWED_THREAD_NAME

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text.startswith("!"):
        return

    # Правильный парсинг: отрезаем '!', делим по пробелам
    parts = text[1:].split()
    if not parts:
        return

    command = parts[0].lower()
    context.args = parts[1:]
    context.command = command

    # --- 1. АДМИН КОМАНДЫ ---
    user = update.effective_user
    if user and user.username == ADMIN_USERNAME:
        if command == "roll_id":
            if len(context.args) < 2:
                await update.message.reply_text("❌ Формат: `!roll_id {id} {название}`")
                return
            try:
                ALLOWED_THREAD_ID = int(context.args[0])
                ALLOWED_THREAD_NAME = " ".join(context.args[1:])
                await update.message.reply_text(f"✅ Топик установлен: <b>{ALLOWED_THREAD_NAME}</b>")
            except ValueError:
                await update.message.reply_text("❌ ID должен быть числом.")
            return

        elif command == "roll_id_clear":
            ALLOWED_THREAD_ID = None
            ALLOWED_THREAD_NAME = "Любой"
            await update.message.reply_text("✅ Ограничение снято.")
            return

    # --- 2. ПРОВЕРКА ТОПИКА ---
    if ALLOWED_THREAD_ID is not None:
        if update.effective_message.message_thread_id != ALLOWED_THREAD_ID:
            chosen = random.choices(WRONG_TOPIC_TEXTS,
                                    weights=WRONG_TOPIC_WEIGHTS, k=1)[0]
            text = chosen.format(name=ALLOWED_THREAD_NAME)

            # Если строка начинается с "KEY:..."
            if ':' in chosen and chosen.split(':', 1)[0] in WRONG_TOPIC_PICS:
                key, _ = chosen.split(':', 1)
                pic_url = WRONG_TOPIC_PICS[key]
                try:
                    await update.effective_message.reply_photo(photo=pic_url)
                    return  # картинка ушла — выходим
                except Exception:
                    pass  # не загрузилось — падём до текстового варианта

            await update.message.reply_text(text)
            return

    # --- 3. ОСНОВНЫЕ КОМАНДЫ ---
    if command == "conq":
        await analyze_weapon(update, context, "cb")
    elif command == "doom":
        await analyze_weapon(update, context, "db")

    elif command in ("fzhelm", "fzchest", "fzleg"):
        await analyze_armor(update, context, "fzh")
    elif command in ("zhelm", "zchest", "zleg"):
        await analyze_armor(update, context, "lzs")

    elif command == "fzset":
        await analyze_full_set(update, context, "fzh")
    elif command == "zset":
        await analyze_full_set(update, context, "lzs")

    # --- 4. ОБНОВЛЕННЫЕ КОМАНДЫ ДЛЯ ASC ОРУЖИЯ ---
    elif command == "asc":
        await analyze_weapon_asc(update, context)
    elif command == "wasc":
        await w_analyze_weapon_asc(update, context)
    elif command == "lasc":
        await l_analyze_weapon_asc(update, context)

    # --- 5. КОМАНДЫ ПРОГНОЗИРОВАНИЯ (ОБЫЧНОЕ ОРУЖИЕ) ---
    elif command == "wconq":
        await w_analyze_weapon(update, context, "cb")
    elif command == "wdoom":
        await w_analyze_weapon(update, context, "db")

    elif command in ("wfzhelm", "wfzchest", "wfzleg"):
        await w_analyze_armor(update, context, "fzh")
    elif command in ("wzhelm", "wzchest", "wzleg"):
        await w_analyze_armor(update, context, "lzs")

    elif command == "wfzset":
        await w_analyze_full_set(update, context, "fzh")
    elif command == "wzset":
        await w_analyze_full_set(update, context, "lzs")

    # --- 6. КОМАНДЫ СРАВНЕНИЯ (ОБЫЧНОЕ ОРУЖИЕ) ---
    elif command == "lconq":
        await l_analyze_weapon(update, context, "cb")
    elif command == "ldoom":
        await l_analyze_weapon(update, context, "db")

    elif command in ("lfzhelm", "lfzchest", "lfzleg"):
        await l_analyze_armor(update, context, "fzh")
    elif command in ("lzhelm", "lzchest", "lzleg"):
        await l_analyze_armor(update, context, "lzs")

    elif command == "lfzset":
        await l_analyze_full_set(update, context, "fzh")
    elif command == "lzset":
        await l_analyze_full_set(update, context, "lzs")

    # --- 7. СЛУЖЕБНЫЕ КОМАНДЫ ---
    elif command == "crhelp":
        await cmd_help(update, context)
    elif command == "reforge":
        await cmd_reforge(update, context)
    elif command == "conqr":
            text = print_rolls_info("Conqueror's Blade — Базовые Урон", CONQUERORS_BLADE_STATS)
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
            return

    elif command == "doomr":
            text = print_rolls_info("Doombringer — Базовые Урон", DOOMBRINGER_STATS)
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
            return

    elif command == "fzr":
            text = print_armor_info("🛡️ Furious Zeus Set (Mythic) — Базовое ХП", FZH_STATS)
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
            return

    elif command == "zr":
            text = print_armor_info("🛡️ Legendary Zeus Set — Базовое ХП", LZS_STATS)
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
            return

    # --- 8. ОБРАБОТКА НЕИЗВЕСТНЫХ КОМАНД ---
    else:
        population = list(UNKNOWN_COMMAND_RESPONSES.keys())
        weights = list(UNKNOWN_COMMAND_RESPONSES.values())
        chosen_phrase = random.choices(population, weights=weights, k=1)[0]

        # ПРОВЕРКА: Если для фразы есть картинка
        if chosen_phrase in UNKNOWN_COMMAND_PHOTOS:
            try:
                # Отправляем ТОЛЬКО фото (без текста)
                await update.effective_message.reply_photo(
                    photo=UNKNOWN_COMMAND_PHOTOS[chosen_phrase]
                )
            except Exception:
                # Если с фото что-то не так, всё же ответим текстом, чтоб бот не молчал
                await update.effective_message.reply_text(chosen_phrase)
        else:
            # Для всех остальных слов — обычный текстовый ответ
            await update.effective_message.reply_text(chosen_phrase)


# --- ЗАПУСК ---
def main():
    app = Application.builder().token(TOKEN).build()

    # Группа 0: самые приоритетные обработчики
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & smart_da_filter,
            yes_handler
        ),
        group=0
    )

    # Обработчик нажатий на inline-кнопки (высокий приоритет)
    app.add_handler(CallbackQueryHandler(help_callback_handler), group=0)

    # Группа 1: все остальные текстовые сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bang_router), group=1)

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()