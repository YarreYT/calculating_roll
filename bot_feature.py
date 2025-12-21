# bot_feature.py (ФИНАЛЬНО ИСПРАВЛЕННЫЙ: Улучшенная, комплексная обработка ошибок для всех команд)

import math
import re
import unicodedata
import random

from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters
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
ALLOWED_THREAD_ID = 97989  # None = работает везде


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def is_allowed_thread(update) -> bool:
    if ALLOWED_THREAD_ID is None:
        return True
    thread_id = update.effective_message.message_thread_id
    return thread_id is not None and thread_id == ALLOWED_THREAD_ID


def calculate_gold(base_cost: int, upg_level: int) -> int:
    """
    Вычисляет накопленную стоимость золота до определенного уровня.
    Формула: S = b1 * (q^n - 1) / (q - 1), где q = 1.3
    """
    if upg_level <= 0:
        return 0
    return round(base_cost * (math.pow(1.3, upg_level) - 1) / 0.3)


def normalize_stat(raw_stat: float, upg_level: int) -> tuple[float, int]:
    index_upg = upg_level * 4.762 + 100
    normalized_raw = (raw_stat / index_upg) * 100
    return normalized_raw, math.floor(normalized_raw)


def determine_roll(stats_dict: dict, normalized_raw: float) -> int:
    """Определяет ролл, находя базовое значение, которое ближе всего к normalized_raw."""
    best_roll = 1
    best_diff = abs(normalized_raw - stats_dict[1])

    for roll in range(2, 12):
        current_diff = abs(normalized_raw - stats_dict[roll])
        if current_diff < best_diff:
            best_diff = current_diff
            best_roll = roll

    return best_roll


def calculate_stat_at_level(base_value: int, target_level: int) -> float:
    """
    Обратная формула нормализации:
    Raw = (Base / 100) * (Level * 4.762 + 100)
    """
    multiplier = (target_level * 4.762 + 100) / 100
    return base_value * multiplier


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
    """Реагирует на 'да', выбирая ответ с учетом весов (приоритетов)."""
    if not update.effective_message:
        return

    # Список слов и их «веса» (вероятность)
    # Чем выше число, тем чаще выпадает слово
    options = {
        "Елда": 20,          # Повышенный шанс
        "ПИЗДА": 1,         # Повышенный шанс
        "Джигурда": 20,      # Повышенный шанс
        "Звезда": 5,        # Обычный шанс
        "Поезда": 5,        # Обычный шанс
        "Дабудидабуда": 10,  # Обычный шанс
        "Борода": 5,         # Обычный шанс
        "Слобода": 5,
        "Узда": 5,
        "Вода": 5
    }

    population = list(options.keys())
    weights = list(options.values())

    # random.choices возвращает список, поэтому берем [0] элемент
    text_to_send = random.choices(population, weights=weights, k=1)[0]

    await update.effective_message.reply_text(text_to_send)


# --- ФУНКЦИИ АНАЛИЗА ТЕКУЩЕГО ПРЕДМЕТА (СТАРЫЕ КОМАНДЫ: !conq, !doom, !fzhelm, и т.д.) ---

async def analyze_weapon(update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    item_info = ITEMS_MAPPING[item_key]
    max_lvl = item_info['max_level']
    args = context.args
    errors = []

    # Defaults for reforge
    reforge_name = "None"
    reforge_mult = 1.0

    # 1. Check argument count (3 or 4)
    if len(args) not in (3, 4):
        errors.append(f"❌ Неверное количество аргументов ({len(args)}). Ожидается 3 или 4.")

    # Proceed with validation only if count is potentially correct (3 or 4)
    if len(args) in (3, 4):

        # 2. Damage parsing
        try:
            damage = float(args[0])
        except ValueError:
            errors.append(f"❌ Урон ({args[0]}) должен быть числом.")

        # 3. Level parsing and validation
        upg_level = -1
        try:
            upg_level = int(args[1])
            if upg_level > max_lvl or upg_level < 0:
                errors.append(f"❌ Уровень меча ({upg_level}) не соответствует 0-{max_lvl}.")
        except ValueError:
            errors.append(f"❌ Уровень улучшения ({args[1]}) должен быть числом.")

        # 4. Corrupted status validation
        is_corrupted_str = args[2].lower()
        if is_corrupted_str not in ('y', 'n'):
            errors.append(f"❌ Статус порчи ({is_corrupted_str}) должен быть 'y' или 'n'.")

        # 5. Reforge validation
        if len(args) == 4:
            reforge_input = args[3]
            found_reforge = False
            for k_ref in REFORGE_MODIFIERS:
                if k_ref.lower() == reforge_input.lower():
                    reforge_name = k_ref
                    reforge_mult = REFORGE_MODIFIERS[k_ref]
                    found_reforge = True
                    break

            if not found_reforge:
                errors.append(f"❌ Неизвестный Reforge ({reforge_input}), напишите !reforge для списка.")

    # Check for errors before proceeding to calculation
    if errors:
        example = f"`{command_name}` {{dmg}} {{upg}} {{y/n}} {{reforge}} \n(если reforge нет - не пишите)"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    # --- CALCULATION LOGIC (only if no errors) ---
    damage = float(args[0])
    upg_level = int(args[1])
    is_corrupted = args[2].lower() == 'y'

    try:
        base_stats = item_info['stats']
        b1 = item_info['upgrade_cost_lvl1']

        total_dmg_after_reforge = damage / reforge_mult
        corrupted_mult = 1.5 if is_corrupted else 1
        total_dmg = total_dmg_after_reforge / corrupted_mult

        current_spent_gold = calculate_gold(b1, upg_level)
        total_max_gold = calculate_gold(b1, max_lvl)
        remaining_gold = max(0, total_max_gold - current_spent_gold)

        normalized_raw, normalized_floor = normalize_stat(total_dmg, upg_level)
        roll = determine_roll(base_stats, normalized_raw)
        base_dmg = base_stats[roll]

        response = (
            f"📊 <b>Анализ {item_info['name']}</b>\n\n"
            f"DMG: <code>{int(damage):,}</code>\n"
            f"Reforge: <code>{reforge_name}</code>\n"
            f"Corrupted: <code>{'Да' if is_corrupted else 'Нет'}</code>\n"
            f"Upgrade: <code>{upg_level}</code> (Макс: {max_lvl})\n"
            f"Gold spent: <code>{current_spent_gold:,}</code> 💰\n"
            f"Gold left to spend: <code>{remaining_gold:,}</code> 💰\n\n"
            f"BASE DMG: <code>{base_dmg:,}</code>\n"
            f"<b>ROLL: {roll}/11</b>"
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

    # Determine part name
    part_key = None
    for key in PART_MAPPING:
        if command_name.endswith(key):
            part_key = key
            break

    if part_key is None:
        await update.message.reply_text("Не удалось определить часть брони.")
        return

    part_name = PART_MAPPING[part_key]
    russian_part = {
        "Helmet": "Шлем",
        "Chestplate": "Нагрудник",
        "Leggings": "Поножи"
    }[part_name]

    # 1. Check argument count (3)
    if len(args) != 3:
        errors.append(f"❌ Неверное количество аргументов ({len(args)}). Ожидается 3.")

    # Proceed with validation only if count is 3
    if len(args) == 3:
        # 2. Health parsing
        try:
            health = float(args[0])
        except ValueError:
            errors.append(f"❌ ХП ({args[0]}) должно быть числом.")

        # 3. Level parsing and validation
        upg_level = -1
        try:
            upg_level = int(args[1])
            if upg_level > max_lvl or upg_level < 0:
                errors.append(f"❌ Уровень {russian_part} ({upg_level}) не соответствует 0-{max_lvl}.")
        except ValueError:
            errors.append(f"❌ Уровень улучшения ({args[1]}) должен быть числом.")

        # 4. Corrupted status validation
        is_corrupted_str = args[2].lower()
        if is_corrupted_str not in ('y', 'n'):
            errors.append(f"❌ Статус порчи ({is_corrupted_str}) должен быть 'y' или 'n'.")

    # Check for errors before proceeding to calculation
    if errors:
        example = f"`{command_name}` {{hp}} {{upg}} {{y/n}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    # --- CALCULATION LOGIC (only if no errors) ---
    health = float(args[0])
    upg_level = int(args[1])
    is_corrupted = args[2].lower() == 'y'

    try:
        base_stats = item_info['stats'][part_name]
        b1 = item_info['upgrade_cost_lvl1']

        total_health = health if not is_corrupted else health / 1.5

        current_spent_gold = calculate_gold(b1, upg_level)
        total_max_gold = calculate_gold(b1, max_lvl)
        remaining_gold = max(0, total_max_gold - current_spent_gold)

        normalized_raw, normalized_floor = normalize_stat(total_health, upg_level)
        roll = determine_roll(base_stats, normalized_raw)
        base_hp = base_stats[roll]

        response = (
            f"🛡️ <b>{item_info['name']} — {russian_part}</b>\n\n"
            f"HP: <code>{int(health):,}</code>\n"
            f"Corrupted: <code>{'Да' if is_corrupted else 'Нет'}</code>\n"
            f"Upgrade: <code>{upg_level}</code> (Макс: {max_lvl})\n"
            f"Gold spent: <code>{current_spent_gold:,}</code> 💰\n"
            f"Gold left to spend: <code>{remaining_gold:,}</code> 💰\n\n"
            f"BASE HP: <code>{base_hp:,}</code>\n"
            f"<b>ROLL: {roll}/11</b>"
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

    # 1. Check argument count (9)
    if len(args) != 9:
        errors.append(f"❌ Неверное количество аргументов ({len(args)}). Ожидается 9.")

    if len(args) == 9:
        for i in range(3):
            part_name = rus_names_nominative[i]

            # Check HP
            try:
                hp = float(args[i])
            except ValueError:
                errors.append(f"❌ ХП {part_name} ({args[i]}) должно быть числом.")

            # Check Level
            level = -1
            try:
                level = int(args[i + 3])
                if level > max_lvl or level < 0:
                    errors.append(f"❌ Уровень {part_name} ({level}) не соответствует 0-{max_lvl}.")
            except ValueError:
                errors.append(f"❌ Уровень {part_name} ({args[i + 3]}) должен быть числом.")

            # Check Corrupted
            is_corr_str = args[i + 6].lower()
            if is_corr_str not in ('y', 'n'):
                errors.append(f"❌ Статус порчи {part_name} ({is_corr_str}) должен быть 'y' или 'n'.")

    # Check for errors before proceeding to calculation
    if errors:
        example = f"`{command_name}` {{hp1}} {{hp2}} {{hp3}} {{upg1}} {{upg2}} {{upg3}} {{y/n1}} {{y/n2}} {{y/n3}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    # --- CALCULATION LOGIC (only if no errors) ---
    try:
        b1 = item_info['upgrade_cost_lvl1']
        stats_db = item_info['stats']

        rus_names = ["Шлема", "Нагрудника", "Штанов"]  # Родительный падеж для отображения

        total_hp_display = 0.0
        results = []

        for i, part_key in enumerate(parts_order):
            hp = float(args[i])
            level = int(args[i + 3])
            is_corr = args[i + 6].lower() == 'y'

            total_hp_display += hp
            calc_hp = hp if not is_corr else hp / 1.5

            spent = calculate_gold(b1, level)
            total_needed = calculate_gold(b1, max_lvl)
            rem = max(0, total_needed - spent)

            norm_raw, _ = normalize_stat(calc_hp, level)
            roll = determine_roll(stats_db[part_key], norm_raw)
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
        response += f"TOTAL HEALTH: <code>{int(total_hp_display):,}</code> ❤️\n\n"

        response += "<b>BASE HP</b>\n"
        for res in results:
            response += f"{res['rus_nom']}: <code>{int(res['base_hp']):,}</code>\n"
        response += "\n"

        response += "<b>🆙 UPG</b>\n"
        for res in results:
            response += f"{res['rus_nom']}: <code>{res['lvl']}</code>\n"

        response += "\n<b>💰 GOLD (Spent / Left to spend)</b>\n"
        for res in results:
            response += f"{res['rus_nom']}: <code>{res['spent']:,}</code> / <code>{res['rem']:,}</code>\n"

        response += "\n<b>🎲 ROLL</b>\n"
        for res in results:
            response += f"{res['rus_nom']}: <b>{res['roll']}/11</b>\n"

        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


# --- ФУНКЦИИ ПРОГНОЗИРОВАНИЯ (НОВЫЕ КОМАНДЫ: !wconq, !wdoom, !wfzhelm, и.т.д.) ---

async def w_analyze_weapon(update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args_raw = context.args
    item_info = ITEMS_MAPPING[item_key]
    max_lvl = item_info['max_level']
    errors = []

    # Defaults for reforge
    reforge_name = "None"
    reforge_mult = 1.0

    # 1. Check raw argument count (4 or 5)
    if len(args_raw) not in (4, 5):
        errors.append(f"❌ Неверное количество аргументов ({len(args_raw)}). Ожидается 4 или 5 (с разделителем '>').")

    # 2. Separator check
    if len(args_raw) >= 2:
        if args_raw[1] != '>':
            errors.append(f"❌ Неправильный разделитель ({args_raw[1]}), ожидается '>'.")

    # Clean arguments (removes '>')
    args = clean_args_from_separator(args_raw)

    # Check count again without separator (3 or 4)
    if len(args) not in (3, 4):
        if len(args_raw) in (4, 5) and args_raw[1] == '>':
            pass
        elif not errors:
            errors.append(f"❌ Неверное количество параметров ({len(args)}) после разделителя (ожидается 3 или 4).")

    # Proceed with validation only if clean count is potentially correct (3 or 4)
    if len(args) in (3, 4):

        # 3. Roll parsing and validation
        roll = -1
        try:
            roll = int(args[0])
            if not (1 <= roll <= 11):
                errors.append(f"❌ Значение ролла ({roll}) не соответствует 1-11.")
        except ValueError:
            errors.append(f"❌ Ролл ({args[0]}) должен быть числом.")

        # 4. Level parsing and validation
        target_level = -1
        try:
            target_level = int(args[1])
            if target_level > max_lvl or target_level < 0:
                errors.append(f"❌ Уровень меча ({target_level}) не соответствует 0-{max_lvl}.")
        except ValueError:
            errors.append(f"❌ Уровень улучшения ({args[1]}) должен быть числом.")

        # 5. Corrupted status validation
        is_corrupted_str = args[2].lower()
        if is_corrupted_str not in ('y', 'n'):
            errors.append(f"❌ Статус порчи ({is_corrupted_str}) должен быть 'y' или 'n'.")

        # 6. Reforge validation
        if len(args) == 4:
            reforge_input = args[3]
            found_reforge = False
            for k_ref in REFORGE_MODIFIERS:
                if k_ref.lower() == reforge_input.lower():
                    reforge_name = k_ref
                    reforge_mult = REFORGE_MODIFIERS[k_ref]
                    found_reforge = True
                    break

            if not found_reforge:
                errors.append(f"❌ Неизвестный Reforge ({reforge_input}), напишите !reforge для списка.")

    # Check for errors before proceeding to calculation
    if errors:
        example = f"`{command_name}` {{roll}} > {{upg до {max_lvl}}} {{y/n}} {{reforge}} \n(если reforge нет - не пишите)"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example}"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    # --- CALCULATION LOGIC (only if no errors) ---
    roll = int(args[0])
    target_level = int(args[1])
    is_corrupted = args[2].lower() == 'y'

    try:
        base_stats_db = item_info['stats']
        base_dmg_at_roll = base_stats_db[roll]

        dmg_at_level = calculate_stat_at_level(base_dmg_at_roll, target_level)

        corr_mult = 1.5 if is_corrupted else 1.0
        final_dmg_raw = dmg_at_level * corr_mult * reforge_mult
        final_dmg = math.floor(final_dmg_raw)

        b1 = item_info['upgrade_cost_lvl1']
        total_gold_needed = calculate_gold(b1, target_level)

        corrupted_text = 'Да' if is_corrupted else 'Нет'

        response = (
            f"📊 <b>Анализ {item_info['name']}</b>\n"
            f"<b>ROLL: {roll}/11</b>\n\n"
            f"Reforge: <code>{reforge_name}</code>\n"
            f"UPG: <code>{target_level}</code>\n"
            f"Corrupted: <code>{corrupted_text}</code>\n"
            f"Базовый <code>{int(base_dmg_at_roll):,}</code> -> Желаемый <code>{final_dmg:,}</code> ⚔️\n"
            f"Нужно потратить <code>{total_gold_needed:,}</code> 💰"
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

    # Determine part name (needed for error message)
    part_key = None
    for key in PART_MAPPING:
        if command_name.endswith(key):
            part_key = key
            break

    if part_key is None:
        await update.message.reply_text("Не удалось определить часть брони.")
        return

    part_name = PART_MAPPING[part_key]
    russian_part = {
        "Helmet": "Шлем", "Chestplate": "Нагрудник", "Leggings": "Поножи"
    }[part_name]

    # 1. Check raw argument count (4)
    if len(args_raw) != 4:
        errors.append(f"❌ Неверное количество аргументов ({len(args_raw)}). Ожидается 4 (с разделителем '>').")

    # 2. Separator check
    if len(args_raw) >= 2:
        if args_raw[1] != '>':
            errors.append(f"❌ Неправильный разделитель ({args_raw[1]}), ожидается '>'.")

    # Clean arguments (removes '>')
    args = clean_args_from_separator(args_raw)

    # Check count again without separator (3)
    if len(args) != 3:
        if len(args_raw) == 4 and args_raw[1] == '>':
            pass
        elif not errors:
            errors.append(f"❌ Неверное количество параметров ({len(args)}) после разделителя (ожидается 3).")

    # Proceed with validation only if clean count is potentially correct (3)
    if len(args) == 3:

        # 3. Roll parsing and validation
        roll = -1
        try:
            roll = int(args[0])
            if not (1 <= roll <= 11):
                errors.append(f"❌ Значение ролла ({roll}) не соответствует 1-11.")
        except ValueError:
            errors.append(f"❌ Ролл ({args[0]}) должен быть числом.")

        # 4. Level parsing and validation
        target_level = -1
        try:
            target_level = int(args[1])
            if target_level > max_lvl or target_level < 0:
                errors.append(f"❌ Уровень {russian_part} ({target_level}) не соответствует 0-{max_lvl}.")
        except ValueError:
            errors.append(f"❌ Уровень улучшения ({args[1]}) должен быть числом.")

        # 5. Corrupted status validation
        is_corrupted_str = args[2].lower()
        if is_corrupted_str not in ('y', 'n'):
            errors.append(f"❌ Статус порчи ({is_corrupted_str}) должен быть 'y' или 'n'.")

    # Check for errors before proceeding to calculation
    if errors:
        example = f"`{command_name}` {{roll}} > {{upg до {max_lvl}}} {{y/n}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    # --- CALCULATION LOGIC (only if no errors) ---
    roll = int(args[0])
    target_level = int(args[1])
    is_corrupted = args[2].lower() == 'y'

    try:
        base_stats_db = item_info['stats'][part_name]
        base_hp_at_roll = base_stats_db[roll]

        hp_at_level = calculate_stat_at_level(base_hp_at_roll, target_level)
        corr_mult = 1.5 if is_corrupted else 1.0
        final_hp_raw = hp_at_level * corr_mult
        final_hp = math.floor(final_hp_raw)

        b1 = item_info['upgrade_cost_lvl1']
        total_gold_needed = calculate_gold(b1, target_level)

        corrupted_text = 'Да' if is_corrupted else 'Нет'

        response = (
            f"🛡️ <b>{item_info['name']} — {russian_part}</b>\n"
            f"<b>ROLL: {roll}/11</b>\n\n"
            f"UPG: <code>{target_level}</code>\n"
            f"Corrupted: <code>{corrupted_text}</code>\n"
            f"Базовое <code>{int(base_hp_at_roll):,}</code> -> Желаемое <code>{final_hp:,}</code> ❤️\n"
            f"Нужно потратить <code>{total_gold_needed:,}</code> 💰"
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
    b1 = item_info['upgrade_cost_lvl1']
    stats_db = item_info['stats']

    parts_order = ["Helmet", "Chestplate", "Leggings"]
    rus_names_nominative = ["Шлем", "Нагрудник", "Штаны"]
    errors = []

    # 1. Check raw argument count (10)
    if len(args_raw) != 10:
        errors.append(
            f"❌ Неверное количество аргументов ({len(args_raw)}). Ожидается 10 (3 ролла, 1 разделитель '>', 3 уровня, 3 статуса).")

    # 2. Separator check
    if len(args_raw) >= 4:
        if args_raw[3] != '>':
            errors.append(f"❌ Неправильный разделитель ({args_raw[3]}), ожидается '>'.")

    # Clean arguments (removes '>')
    args = clean_args_from_separator(args_raw)

    # Check count again without separator (9)
    if len(args) != 9:
        if len(args_raw) == 10 and args_raw[3] == '>':
            pass
        elif not errors:
            errors.append(f"❌ Неверное количество параметров ({len(args)}) после разделителя (ожидается 9).")

    # Proceed with validation only if clean count is potentially correct (9)
    if len(args) == 9:
        # args[0-2] = Rolls, args[3-5] = Levels, args[6-8] = Y/N

        for i in range(3):
            part_name = rus_names_nominative[i]

            # 3. Roll parsing and validation
            roll = -1
            try:
                roll = int(args[i])
                if not (1 <= roll <= 11):
                    errors.append(f"❌ Значение ролла {part_name} ({roll}) не соответствует 1-11.")
            except ValueError:
                errors.append(f"❌ Ролл {part_name} ({args[i]}) должен быть числом.")

            # 4. Level parsing and validation
            level = -1
            try:
                level = int(args[i + 3])
                if level > max_lvl or level < 0:
                    errors.append(f"❌ Уровень {part_name} ({level}) не соответствует 0-{max_lvl}.")
            except ValueError:
                errors.append(f"❌ Уровень {part_name} ({args[i + 3]}) должен быть числом.")

            # 5. Corrupted status validation
            is_corr_str = args[i + 6].lower()
            if is_corr_str not in ('y', 'n'):
                errors.append(f"❌ Статус порчи {part_name} ({is_corr_str}) должен быть 'y' или 'n'.")

    # Check for errors before proceeding to calculation
    if errors:
        example = f"`{command_name}` {{roll1}} {{roll2}} {{roll3}} > {{upg1}} {{upg2}} {{upg3}} {{y/n1}} {{y/n2}} {{y/n3}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    # --- CALCULATION LOGIC (only if no errors) ---
    try:
        rus_names = ["Шлема", "Нагрудника", "Штанов"]  # Родительный падеж для отображения

        results = []
        total_hp_projected = 0
        total_gold = 0

        for i in range(3):
            roll = int(args[i])
            level = int(args[i + 3])
            is_corr = args[i + 6].lower() == 'y'
            part_key = parts_order[i]

            base_val = stats_db[part_key][roll]
            val_at_lvl = calculate_stat_at_level(base_val, level)
            final_val_raw = val_at_lvl * (1.5 if is_corr else 1.0)
            final_val = math.floor(final_val_raw)

            gold = calculate_gold(b1, level)

            total_hp_projected += final_val
            total_gold += gold

            results.append({
                "name": rus_names_nominative[i],
                "roll": roll,
                "lvl": level,
                "base": base_val,
                "final": final_val,
                "gold": gold,
                "is_corr": is_corr
            })

        response = f"🛡️ <b>Прогноз сета: {item_info['name']}</b>\n\n"

        response += "<b>🎯 ИТОГИ</b>\n"
        response += f"HP: <code>{total_hp_projected:,}</code> ❤️\n"
        response += f"Gold: <code>{total_gold:,}</code> 💰\n\n"

        response += "<b>📝 ДЕТАЛИ</b>\n"
        for res in results:
            corr_status_text = 'Да' if res['is_corr'] else 'Нет'
            response += (
                f"<b>{res['name']}</b>\n"
                f"ROLL: {res['roll']}/11 | UPG: <code>{res['lvl']}</code> | Corrupted: <code>{corr_status_text}</code>\n"
                f"Нужно потратить (золото): <code>{res['gold']:,}</code> 💰\n"
                f"Базовое <code>{int(res['base']):,}</code> -> Желаемое <code>{res['final']:,}</code> ❤️\n"
                f"\n"
            )
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


# --- НОВЫЕ ФУНКЦИИ СРАВНЕНИЯ (КОМАНДЫ: !lconq, !ldoom, и.т.д.) ---

async def l_analyze_weapon(update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    if not is_allowed_thread(update):
        return

    command_name = "!" + context.command
    args_raw = context.args
    item_info = ITEMS_MAPPING[item_key]
    max_lvl = item_info['max_level']
    errors = []

    # Find separator index
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

        # Check counts: left 3 or 4, right 2 or 3
        left_len = len(left_args)
        right_len = len(right_args)
        if left_len not in (3, 4):
            errors.append(f"❌ Левая часть: неверное количество аргументов ({left_len}). Ожидается 3 или 4.")
        if right_len not in (2, 3):
            errors.append(f"❌ Правая часть: неверное количество аргументов ({right_len}). Ожидается 2 или 3.")

    if errors:
        example = f"`{command_name}` {{roll}} {{upg}} {{y/n}} {{reforge}} > {{upg}} {{y/n}} {{reforge}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    # Parse left (current)
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

    curr_ref_name = "None"
    curr_ref_mult = 1.0
    if len(left_args) == 4:
        ref_input = left_args[3].lower()
        found = False
        for k, v in REFORGE_MODIFIERS.items():
            if k.lower() == ref_input:
                curr_ref_name = k
                curr_ref_mult = v
                found = True
                break
        if not found:
            errors.append(f"❌ Текущий reforge ({left_args[3]}) неизвестен.")

    # Parse right (desired)
    try:
        des_upg = int(right_args[0])
        if not 0 <= des_upg <= max_lvl:
            errors.append(f"❌ Желаемый UPG ({right_args[0]}) не в 0-{max_lvl}.")
    except ValueError:
        errors.append(f"❌ Желаемый UPG ({right_args[0]}) должен быть числом.")

    des_corr_str = right_args[1].lower()
    if des_corr_str not in ('y', 'n'):
        errors.append(f"❌ Желаемый corrupted ({des_corr_str}) должен быть 'y' или 'n'.")

    des_ref_name = "None"
    des_ref_mult = 1.0
    if len(right_args) == 3:
        ref_input = right_args[2].lower()
        found = False
        for k, v in REFORGE_MODIFIERS.items():
            if k.lower() == ref_input:
                des_ref_name = k
                des_ref_mult = v
                found = True
                break
        if not found:
            errors.append(f"❌ Желаемый reforge ({right_args[2]}) неизвестен.")

    # Corrupted rule
    if curr_corr_str == 'y' and des_corr_str == 'n':
        errors.append("❌ Нельзя декорраптить (y > n запрещено).")

    if len(left_args) == 4 and len(right_args) == 2:
            errors.append("❌ Нельзя удалить reforge (присутствует в текущем, отсутствует в желаемом).")

    if errors:
        example = f"`{command_name}` {{roll}} {{upg}} {{y/n}} {{reforge}} > {{upg}} {{y/n}} {{reforge}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    # Calculation
    try:
        base_stats = item_info['stats']
        base_val = base_stats[curr_roll]
        b1 = item_info['upgrade_cost_lvl1']

        # Current
        curr_stat_raw = calculate_stat_at_level(base_val, curr_upg) * (
            1.5 if curr_corr_str == 'y' else 1.0) * curr_ref_mult
        curr_stat = math.floor(curr_stat_raw)
        curr_spent = calculate_gold(b1, curr_upg)
        total_max = calculate_gold(b1, max_lvl)
        curr_left = max(0, total_max - curr_spent)

        # Desired
        des_stat_raw = calculate_stat_at_level(base_val, des_upg) * (1.5 if des_corr_str == 'y' else 1.0) * des_ref_mult
        des_stat = math.floor(des_stat_raw)
        des_needed = max(0, calculate_gold(b1, des_upg) - curr_spent)

        curr_corr_text = 'Да' if curr_corr_str == 'y' else 'Нет'
        des_corr_text = 'Да' if des_corr_str == 'y' else 'Нет'

        response = (
            f"📊 <b>Анализ {item_info['name']}</b>\n"
            f"<b>ROLL: {curr_roll}/11</b>\n\n"
            f"UPG: <code>{curr_upg}</code> > <code>{des_upg}</code>\n"
            f"REFORGE: <code>{curr_ref_name}</code> > <code>{des_ref_name}</code>\n"
            f"Corrupted: <code>{curr_corr_text}</code> > <code>{des_corr_text}</code>\n\n"
            f"DMG: <code>{curr_stat:,}</code> > <code>{des_stat:,}</code> ⚔️\n"
            f"GOLD (Потрачено / Осталось): 💰\n"
            f"       <code>{curr_spent:,}</code> / <code>{des_needed:,}</code>"
        )
        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


async def l_analyze_armor(update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
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

        # Check counts: left 3, right 2
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
        curr_stat_raw = calculate_stat_at_level(base_val, curr_upg) * (1.5 if curr_corr_str == 'y' else 1.0)
        curr_stat = math.floor(curr_stat_raw)
        curr_spent = calculate_gold(b1, curr_upg)

        # Desired
        des_stat_raw = calculate_stat_at_level(base_val, des_upg) * (1.5 if des_corr_str == 'y' else 1.0)
        des_stat = math.floor(des_stat_raw)
        des_needed = max(0, calculate_gold(b1, des_upg) - curr_spent)

        curr_corr_text = 'Да' if curr_corr_str == 'y' else 'Нет'
        des_corr_text = 'Да' if des_corr_str == 'y' else 'Нет'

        response = (
            f"🛡️ <b>Анализ {item_info['name']} — {russian_part}</b>\n"
            f"<b>ROLL: {curr_roll}/11</b>\n\n"
            f"UPG: <code>{curr_upg}</code> > <code>{des_upg}</code>\n"
            f"Corrupted: <code>{curr_corr_text}</code> > <code>{des_corr_text}</code>\n\n"
            f"HP: <code>{curr_stat:,}</code> > <code>{des_stat:,}</code> ❤️\n"
            f"GOLD (Потрачено / Осталось): 💰\n"
            f"       <code>{curr_spent:,}</code> / <code>{des_needed:,} </code> "
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

        # Check counts: left 9, right 6
        if len(left_args) != 9:
            errors.append(f"❌ Левая часть: неверное количество аргументов ({len(left_args)}). Ожидается 9.")
        if len(right_args) != 6:
            errors.append(f"❌ Правая часть: неверное количество аргументов ({len(right_args)}). Ожидается 6.")

    if errors:
        example = f"`{command_name}` {{roll1}} {{roll2}} {{roll3}} {{upg1}} {{upg2}} {{upg3}} {{y/n1}} {{y/n2}} {{y/n3}} > {{upg1}} {{upg2}} {{upg3}} {{y/n1}} {{y/n2}} {{y/n3}}"
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

    # Parse left: rolls[0-2], upgs[3-5], corrs[6-8]
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
            errors.append(
                f"❌ Текущий corrupted {rus_names_nominative[i]} ({left_args[i + 6]}) должен быть 'y' или 'n'.")
        curr_corrs.append(corr_str)

    # Parse right: upgs[0-2], corrs[3-5]
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
            errors.append(
                f"❌ Желаемый corrupted {rus_names_nominative[i]} ({right_args[i + 3]}) должен быть 'y' или 'n'.")
        des_corrs.append(corr_str)

    # Rules for each piece
    for i in range(3):
        if curr_corrs[i] == 'y' and des_corrs[i] == 'n':
            errors.append(f"❌ {rus_names_nominative[i]}: нельзя декорраптить (y > n запрещено).")

    if errors:
        example = f"`{command_name}` {{roll1}} {{roll2}} {{roll3}} {{upg1}} {{upg2}} {{upg3}} {{y/n1}} {{y/n2}} {{y/n3}} > {{upg1}} {{upg2}} {{upg3}} {{y/n1}} {{y/n2}} {{y/n3}}"
        error_message = f"🛑 **Обнаружены ошибки формата для {command_name}:**\n"
        error_message += "\n".join(errors)
        error_message += "\n\n**Пример написания:**\n"
        error_message += f"{example} \n(Макс. ур: {max_lvl})"
        await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
        return

    # Calculation
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

            # Current
            curr_stat_raw = calculate_stat_at_level(base_val, curr_upgs[i]) * (1.5 if curr_corrs[i] == 'y' else 1.0)
            curr_stat = math.floor(curr_stat_raw)
            curr_spent = calculate_gold(b1, curr_upgs[i])

            # Desired
            des_stat_raw = calculate_stat_at_level(base_val, des_upgs[i]) * (1.5 if des_corrs[i] == 'y' else 1.0)
            des_stat = math.floor(des_stat_raw)
            des_needed = max(0, calculate_gold(b1, des_upgs[i]) - curr_spent)

            curr_total_hp += curr_stat
            des_total_hp += des_stat
            curr_total_spent += curr_spent
            des_total_needed += des_needed

            curr_corr_text = 'Да' if curr_corrs[i] == 'y' else 'Нет'
            des_corr_text = 'Да' if des_corrs[i] == 'y' else 'Нет'

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
        response += f"HP: <code>{curr_total_hp:,}</code> > <code>{des_total_hp:,}</code> ❤️\n"
        response += f"GOLD: <code>{curr_total_spent:,}</code> / <code>{des_total_needed:,}</code> 💰\n\n"

        response += "<b>📝 ДЕТАЛИ</b>\n"
        for res in results:
            response += (
                f"<b>{res['rus_name']}</b>\n"
                f"ROLL: {res['roll']}/11 | BASE HP: <code>{res['base_val']:,}</code>\n"
                f"UPG: <code>{res['curr_upg']}</code> > <code>{res['des_upg']}</code>\n"
                f"Corrupted: <code>{res['curr_corr_text']}</code> > <code>{res['des_corr_text']}</code>\n"
                f"HP: <code>{res['curr_stat']:,}</code> > <code>{res['des_stat']:,}</code> ❤️\n"
                f"GOLD: <code>{res['curr_spent']:,}</code> / <code>{res['des_needed']:,}</code> 💰\n"
                f"\n"
            )

        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"Непредвиденная ошибка при расчете: {e}")


# --- ТАБЛИЦЫ РОЛЛОВ ---

async def print_rolls_info(update, _context, item_name: str, stats: dict, type_str: str):
    if not is_allowed_thread(update):
        return

    output = f"<b>{item_name} — Базовые {type_str}</b>\n\n<code>"
    output += "Ролл | Значение\n"

    max_len = max(len(f"{v:,.2f}" if isinstance(v, float) else f"{v:,}") for v in stats.values())

    for roll in sorted(stats):
        value = f"{stats[roll]:,.2f}" if isinstance(stats[roll], float) else f"{stats[roll]:,}"
        output += f"{roll:>2}   | {value.rjust(max_len)}\n"

    output += "</code>"
    await update.message.reply_text(output, parse_mode=ParseMode.HTML)


async def print_armor_rolls(update, _context, set_name: str, stats: dict):
    if not is_allowed_thread(update):
        return

    output = f"🛡️ <b>{set_name} — Базовое ХП</b>\n\n<code>"
    output += "Ролл | Шлем | Нагрудник | Поножи\n"

    for roll in range(1, 12):
        output += (
            f"{roll:>2}   | "
            f"{stats['Helmet'][roll]:>4} | "
            f"{stats['Chestplate'][roll]:>9} | "
            f"{stats['Leggings'][roll]:>6}\n"
        )

    output += "</code>"
    await update.message.reply_text(output, parse_mode=ParseMode.HTML)


# --- СПРАВОЧНЫЕ ТЕКСТЫ И КОМАНДА ПОМОЩИ (ДОБАВЛЕНО) ---

HELP_TEXT = """
*Создатель бота:* H2O (@YarreYT)

*Общие правила:*
КОМАНДЫ: (y/n): y - corrupted, n - НЕ corrupted.

*1. Таблицы роллов*

`!crhelp` - Показать эту справку
`!reforge` - Список множителей Reforge
`!doomr` - Список роллов Дума (Doombringer)
`!conqr` - Список роллов Конки (Conqueror's Blade)
`!fzr` - Список роллов Furious Zeus Set (броня)
`!zr` - Список роллов Zeus Set (броня)

*2. Проверка текущего предмета !.. (Анализ ролла)*

*Мечи*
`!conq` / `!doom` / `!menta`
  _Формат:_ {урон} {upg} {y/n} {reforge}

*Частичная проверка брони* 
`!fzhelm` / `!fzchest` / `!fzleg` - Furious Zeus Mythic
`!zhelm` / `!zchest` / `!zleg` - Zeus Legendary
  _Формат:_ {хп} {upg} {y/n}

*Проверка фулл сета* 
`!fzset` / `!zset`
  _Формат:_ {хп шлема} {хп нагрудника} {хп штанов} {ур. улучш. шлема} {ур. улучш. нагрудника} {ур. улучш. штанов} {y/n шлем?} {y/n нагрудник?} {y/n штаны?}

*3. Калькулятор желаемых результатов !w.. (Анализ результата)*

*Оружие* 
`!wconq` / `!wdoom` / `!wmenta`
  _Формат:_ {ролл} > {желаемый ур. улучшения} {y/n} [reforge]

*Элементы брони*
`!wfzhelm` / `!wfzchest` / `!wfzleg` - Furious Zeus Mythic
`!wzhelm` / `!wzchest` / `!wzleg` - Zeus Legendary 
  _Формат:_ {ролл} > {желаемый ур. улучшения} {y/n}

*Набор брони* 
`!wfzset` / `!wzset`
  _Формат:_ {ролл1} {ролл2} {ролл3} > {upg1} {upg2} {upg3} {y/n1} {y/n2} {y/n3}

*4. Сравнение текущего и желаемого !l.. (Анализ желаемых результатов)*

*Оружие* 
`!lconq` / `!ldoom` / `!lmenta`
  _Формат:_ {ролл} {upg} {y/n} [reforge] > {upg} {y/n} [reforge]

*Элементы брони*
`!lfzhelm` / `!lfzchest` / `!lfzleg` - Furious Zeus Mythic
`!lzhelm` / `!lzchest` / `!lzleg` - Zeus Legendary 
  _Формат:_ {ролл} {upg} {y/n} > {upg} {y/n}

*Набор брони* 
`!lfzset` / `!lzset`
  _Формат:_ {ролл1} {ролл2} {ролл3} {upg1} {upg2} {upg3} {y/n1} {y/n2} {y/n3} > {upg1} {upg2} {upg3} {y/n1} {y/n2} {y/n3}
"""


async def cmd_help(update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_thread(update):
        return

    # Use simple, safe Markdown formatting to avoid the BadRequest error.
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)


# --- РОУТЕР ДЛЯ !КОМАНД ---

async def cmd_reforge(update, _context):
    if not is_allowed_thread(update):
        return

    sorted_reforge = sorted(
        REFORGE_MODIFIERS.items(),
        key=lambda x: x[1],
        reverse=True
    )

    max_len = max(len(name) for name, _ in sorted_reforge)

    output = "✨ <b>Множители Reforge</b> ✨\n\n<code>"
    for name, mult in sorted_reforge:
        output += f"{name.ljust(max_len)} | x{mult}\n"
    output += "</code>"

    await update.message.reply_text(output, parse_mode=ParseMode.HTML)


async def bang_router(update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text.startswith("!"):
        return

    parts = text[1:].split()
    command = parts[0].lower()
    context.args = parts[1:]
    context.command = command

    # --- СТАРЫЕ КОМАНДЫ (АНАЛИЗ ТЕКУЩЕГО) ---
    if command == "conq":
        await analyze_weapon(update, context, "cb")
    elif command == "menta":
        await analyze_weapon(update, context, "menta")
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

    # --- НОВЫЕ КОМАНДЫ (ПРОГНОЗ ПО РОЛЛУ - W) ---
    elif command == "wconq":
        await w_analyze_weapon(update, context, "cb")
    elif command == "wmenta":
        await w_analyze_weapon(update, context, "menta")
    elif command == "wdoom":
        await w_analyze_weapon(update, context, "db")

    # Броня FZH (Furious)
    elif command in ("wfzhelm", "wfzchest", "wfzleg"):
        await w_analyze_armor(update, context, "fzh")
    # Броня LZS (Zeus)
    elif command in ("wzhelm", "wzchest", "wzleg"):
        await w_analyze_armor(update, context, "lzs")

    # Сеты
    elif command == "wfzset":
        await w_analyze_full_set(update, context, "fzh")
    elif command == "wzset":
        await w_analyze_full_set(update, context, "lzs")

    # --- L-КОМАНДЫ (СРАВНЕНИЕ) ---
    elif command == "lconq":
        await l_analyze_weapon(update, context, "cb")
    elif command == "lmenta":
        await l_analyze_weapon(update, context, "menta")
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

    # --- СПРАВОЧНЫЕ ---
    elif command == "crhelp":  # ДОБАВЛЕНО/ИЗМЕНЕНО: теперь обрабатывает !crhelp
        await cmd_help(update, context)
    elif command == "reforge":
        await cmd_reforge(update, context)
    elif command == "conqr":
        await print_rolls_info(update, context, "Conqueror's Blade", CONQUERORS_BLADE_STATS, "Урон")
    elif command == "doomr":
        await print_rolls_info(update, context, "Doombringer", DOOMBRINGER_STATS, "Урон")
    elif command == "fzr":
        await print_armor_rolls(update, context, "Furious Zeus Set (Mythic)", FZH_STATS)
    elif command == "zr":
        await print_armor_rolls(update, context, "Legendary Zeus Set", LZS_STATS)


# --- ЗАПУСК ---

def main():
    app = Application.builder().token(TOKEN).build()

    # ### NEW: Используем наш новый умный фильтр smart_da_filter
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & smart_da_filter,
            yes_handler
        ),
        group=0
    )

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bang_router))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()