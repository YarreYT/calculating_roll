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
ALLOWED_THREAD_ID = 97989     # ID топика по умолчанию
ALLOWED_THREAD_NAME = "ROLL" # Название топика по умолчанию
ADMIN_USERNAME = "YarreYT"      # Только этот пользователь может менять настройки

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

GROWTH_RATE = 1 / 21  # Точный коэффициент роста


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def is_allowed_thread(update) -> bool:
    if ALLOWED_THREAD_ID is None:
        return True
    thread_id = update.effective_message.message_thread_id
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


def calculate_weapon_stat_at_level(base_value: float, target_level: int, is_corrupted: bool, reforge_mult: float) -> int:
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

        inferred_base = infer_base_for_weapon(damage, upg_level, is_corrupted, reforge_mult)
        roll = determine_roll(base_stats, inferred_base)
        base_dmg = base_stats[roll]

        current_spent_gold = calculate_gold(b1, upg_level)
        total_max_gold = calculate_gold(b1, max_lvl)
        remaining_gold = max(0, total_max_gold - current_spent_gold)

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

        roll = find_roll_for_armor(base_stats, health, upg_level, is_corrupted)
        base_hp = base_stats[roll]

        current_spent_gold = calculate_gold(b1, upg_level)
        total_max_gold = calculate_gold(b1, max_lvl)
        remaining_gold = max(0, total_max_gold - current_spent_gold)

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
        base_stats = item_info['stats']
        b1 = item_info['upgrade_cost_lvl1']

        base_dmg = base_stats[roll]
        dmg_at_level = calculate_weapon_stat_at_level(base_dmg, target_level, is_corrupted, reforge_mult)

        total_gold = calculate_gold(b1, target_level)

        response = (
            f"📊 <b>Прогноз {item_info['name']}</b>\n\n"
            f"ROLL: <code>{roll}</code>\n"
            f"Reforge: <code>{reforge_name}</code>\n"
            f"Corrupted: <code>{'Да' if is_corrupted else 'Нет'}</code>\n"
            f"Upgrade: <code>{target_level}</code> (Макс: {max_lvl})\n"
            f"Gold to spend: <code>{total_gold:,}</code> 💰\n\n"
            f"DMG: <code>{dmg_at_level:,}</code>"
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

        # Check counts: left 1, right 2 ? Wait, for w_ armor: {roll} > {upg} {y/n}

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

    # Parse
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

    # Calculation
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
            f"ROLL: <code>{roll}</code>\n"
            f"Corrupted: <code>{'Да' if is_corrupted else 'Нет'}</code>\n"
            f"Upgrade: <code>{target_level}</code> (Макс: {max_lvl})\n"
            f"Gold to spend: <code>{total_gold:,}</code> 💰\n\n"
            f"HP: <code>{int(hp_at_level):,}</code>"
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

        # For w_set: {roll1} {roll2} {roll3} > {upg1} {upg2} {upg3} {y/n1} {y/n2} {y/n3}

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

    # Parse left: rolls[0-2]
    for i in range(3):
        try:
            roll = int(left_args[i])
            if not 1 <= roll <= 11:
                errors.append(f"❌ Ролл {rus_names_nominative[i]} ({left_args[i]}) не в 1-11.")
            rolls.append(roll)
        except ValueError:
            errors.append(f"❌ Ролл {rus_names_nominative[i]} ({left_args[i]}) должен быть числом.")

    # Parse right: upgs[0-2], corrs[3-5]
    for i in range(3):
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

    # Calculation
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
        response += f"HP: <code>{int(total_hp):,}</code> ❤️\n"
        response += f"GOLD: <code>{total_gold:,}</code> 💰\n\n"

        response += "<b>📝 ДЕТАЛИ</b>\n"
        for res in results:
            response += (
                f"<b>{res['rus_name']}</b>\n"
                f"ROLL: {res['roll']}/11 | BASE HP: <code>{int(res['base_hp']):,}</code>\n"
                f"UPG: <code>{res['upg']}</code>\n"
                f"Corrupted: <code>{res['corr_text']}</code>\n"
                f"HP: <code>{int(res['hp']):,}</code> ❤️\n"
                f"GOLD: <code>{res['gold']:,}</code> 💰\n"
                f"\n"
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

        # For l_weapon: {roll} {upg} {y/n} [reforge] > {upg} {y/n} [reforge]
        # So left 3 or 4, right 2 or 3

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

    # Defaults
    curr_ref_name = "None"
    curr_ref_mult = 1.0
    des_ref_name = "None"
    des_ref_mult = 1.0

    # Parse left
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

    # Rule
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

    # Calculation
    curr_roll = int(left_args[0])
    curr_upg = int(left_args[1])
    curr_corr = curr_corr_str == 'y'
    des_upg = int(right_args[0])
    des_corr = des_corr_str == 'y'

    try:
        base_stats = item_info['stats']
        base_val = base_stats[curr_roll]
        b1 = item_info['upgrade_cost_lvl1']

        # Current
        curr_stat = calculate_weapon_stat_at_level(base_val, curr_upg, curr_corr, curr_ref_mult)
        curr_spent = calculate_gold(b1, curr_upg)

        # Desired
        des_stat = calculate_weapon_stat_at_level(base_val, des_upg, des_corr, des_ref_mult)
        des_needed = max(0, calculate_gold(b1, des_upg) - curr_spent)

        curr_corr_text = 'Да' if curr_corr else 'Нет'
        des_corr_text = 'Да' if des_corr else 'Нет'

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
            f"<b>ROLL: {curr_roll}/11</b>\n\n"
            f"UPG: <code>{curr_upg}</code> > <code>{des_upg}</code>\n"
            f"Corrupted: <code>{curr_corr_text}</code> > <code>{des_corr_text}</code>\n\n"
            f"HP: <code>{int(curr_stat):,}</code> > <code>{int(des_stat):,}</code> ❤️\n"
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
        curr_corrs.append(corr_str == 'y')

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
        des_corrs.append(corr_str == 'y')

    # Rules for each piece
    for i in range(3):
        if curr_corrs[i] and not des_corrs[i]:
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
            curr_stat = calculate_armor_stat_at_level(base_val, curr_upgs[i], curr_corrs[i], 1.0, "armor")
            curr_spent = calculate_gold(b1, curr_upgs[i])

            # Desired
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
        response += f"HP: <code>{int(curr_total_hp):,}</code> > <code>{int(des_total_hp):,}</code> ❤️\n"
        response += f"GOLD: <code>{curr_total_spent:,}</code> / <code>{des_total_needed:,}</code> 💰\n\n"

        response += "<b>📝 ДЕТАЛИ</b>\n"
        for res in results:
            response += (
                f"<b>{res['rus_name']}</b>\n"
                f"ROLL: {res['roll']}/11 | BASE HP: <code>{int(res['base_val']):,}</code>\n"
                f"UPG: <code>{res['curr_upg']}</code> > <code>{res['des_upg']}</code>\n"
                f"Corrupted: <code>{res['curr_corr_text']}</code> > <code>{res['des_corr_text']}</code>\n"
                f"HP: <code>{int(res['curr_stat']):,}</code> > <code>{int(res['des_stat']):,}</code> ❤️\n"
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
`!conq` / `!doom` / `!asc`
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
`!wconq` / `!wdoom` / `!wasc`
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
`!lconq` / `!ldoom` / `!lasc`
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

async def cmd_reforge(update, context):
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

    # --- 3. ТВОИ ОРИГИНАЛЬНЫЕ КОМАНДЫ (БЕЗ ИЗМЕНЕНИЙ) ---
    if command == "conq":
        await analyze_weapon(update, context, "cb")
    elif command == "asc":
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

    elif command == "wconq":
        await w_analyze_weapon(update, context, "cb")
    elif command == "wasc":
        await w_analyze_weapon(update, context, "menta")
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

    elif command == "lconq":
        await l_analyze_weapon(update, context, "cb")
    elif command == "lasc":
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

    elif command == "crhelp":
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

        # --- ОБРАБОТКА НЕИЗВЕСТНЫХ КОМАНД ---
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

    # Фильтр на "ДА" остается первым и глобальным (группа 0)
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & smart_da_filter,
            yes_handler
        ),
        group=0
    )

    # Все остальные команды через роутер
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bang_router))

    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()