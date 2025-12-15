# bot_feature.py

import math
import re  # ### NEW: Для регулярных выражений
import unicodedata  # ### NEW: Для понимания "странных" шрифтов
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
    """Реагирует на 'да', так как фильтрация уже прошла в smart_da_filter."""
    # Проверка на пустое сообщение на всякий случай
    if not update.effective_message:
        return

    # Сразу отвечаем, так как фильтр уже проверил, что это "то самое да"
    await update.effective_message.reply_text("Елда")


async def analyze_weapon(update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    if not is_allowed_thread(update):
        return

    try:
        args = context.args
        if len(args) not in (3, 4):
            await update.message.reply_text(
                f"Формат: !{context.command} <Урон> <Ур.Улучш> <y/n> [Reforge]"
            )
            return

        damage = float(args[0])
        upg_level = int(args[1])
        is_corrupted = args[2].lower() == 'y'

        # --- REFORGE ---
        if len(args) == 4:
            reforge_name = args[3].capitalize()
            if reforge_name not in REFORGE_MODIFIERS:
                await update.message.reply_text("Неизвестный reforge. Используй !reforge")
                return
            reforge_mult = REFORGE_MODIFIERS[reforge_name]
        else:
            reforge_name = "None"
            reforge_mult = 1

        item_info = ITEMS_MAPPING[item_key]
        base_stats = item_info['stats']
        b1 = item_info['upgrade_cost_lvl1']
        max_lvl = item_info['max_level']

        total_dmg_after_reforge = damage / reforge_mult
        corrupted_mult = 1.5 if is_corrupted else 1
        total_dmg = total_dmg_after_reforge / corrupted_mult

        current_spent_gold = calculate_gold(b1, upg_level)
        total_max_gold = calculate_gold(b1, max_lvl)
        remaining_gold = max(0, total_max_gold - current_spent_gold)

        normalized_raw, normalized_floor = normalize_stat(total_dmg, upg_level)
        roll = determine_roll(base_stats, normalized_raw)

        response = (
            f"📊 <b>Анализ {item_info['name']}</b>\n\n"
            f"DMG: <code>{damage:,.1f}</code>\n"
            f"Reforge: <code>{reforge_name}</code>\n"
            f"Corrupted: <code>{'Да' if is_corrupted else 'Нет'}</code>\n"
            f"Upgrade: <code>{upg_level}</code> (Макс: {max_lvl})\n"
            f"Gold spent: <code>{current_spent_gold:,}</code> 💰\n"
            f"Gold left to spend: <code>{remaining_gold:,}</code> 💰\n\n"
            f"BASE DMG: <code>{normalized_floor}</code>\n"
            f"<b>ROLL: {roll}/11</b>"
        )

        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except ValueError:
        await update.message.reply_text("Ошибка: урон и уровень должны быть числами.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


# --- АНАЛИЗ БРОНИ (ОДИНОЧНЫЙ) ---

async def analyze_armor(update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    if not is_allowed_thread(update):
        return

    try:
        command = context.command
        part_key = None
        for key in PART_MAPPING:
            if command.endswith(key):
                part_key = key
                break

        if part_key is None:
            await update.message.reply_text(
                "Не удалось определить часть брони.")
            return

        if len(context.args) != 3:
            await update.message.reply_text(
                f"Формат: !{command} <ХП> <Ур.Улучш> <y/n>"
            )
            return

        health = float(context.args[0])
        upg_level = int(context.args[1])
        is_corrupted = context.args[2].lower() == 'y'

        part_name = PART_MAPPING[part_key]
        russian_part = {
            "Helmet": "Шлем",
            "Chestplate": "Нагрудник",
            "Leggings": "Поножи"
        }[part_name]

        item_info = ITEMS_MAPPING[item_key]
        base_stats = item_info['stats'][part_name]
        b1 = item_info['upgrade_cost_lvl1']
        max_lvl = item_info['max_level']

        total_health = health if not is_corrupted else health / 1.5

        current_spent_gold = calculate_gold(b1, upg_level)
        total_max_gold = calculate_gold(b1, max_lvl)
        remaining_gold = max(0, total_max_gold - current_spent_gold)

        normalized_raw, normalized_floor = normalize_stat(total_health, upg_level)
        roll = determine_roll(base_stats, normalized_raw)

        response = (
            f"🛡️ <b>{item_info['name']} — {russian_part}</b>\n\n"
            f"HP: <code>{health:,.1f}</code>\n"
            f"Corrupted: <code>{'Да' if is_corrupted else 'Нет'}</code>\n"
            f"Upgrade: <code>{upg_level}</code> (Макс: {max_lvl})\n"
            f"Gold spent: <code>{current_spent_gold:,}</code> 💰\n"
            f"Gold left to spend: <code>{remaining_gold:,}</code> 💰\n\n"
            f"BASE HP: <code>{normalized_floor}</code>\n"
            f"<b>ROLL: {roll}/11</b>"
        )

        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except ValueError:
        await update.message.reply_text("Ошибка: ХП и уровень должны быть числами.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


# --- ФУНКЦИЯ: АНАЛИЗ ПОЛНОГО СЕТА ---

async def analyze_full_set(update, context: ContextTypes.DEFAULT_TYPE, item_key: str):
    if not is_allowed_thread(update):
        return

    try:
        args = context.args
        if len(args) != 9:
            await update.message.reply_text(
                f"Формат: !{context.command} <ХП Шлем> <ХП Грудь> <ХП Ноги> <Ур Шлем> <Ур Грудь> <Ур Ноги> <y/n Шлем> <y/n Грудь> <y/n Ноги>"
            )
            return

        item_info = ITEMS_MAPPING[item_key]
        b1 = item_info['upgrade_cost_lvl1']
        max_lvl = item_info['max_level']
        stats_db = item_info['stats']

        parts_order = ["Helmet", "Chestplate", "Leggings"]
        rus_names = ["Шлема", "Нагрудника", "Штанов"]
        rus_names_nominative = ["Шлем", "Нагрудник", "Штаны"]

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
        response += f"TOTAL HEALTH: <code>{total_hp_display:,.1f}</code> ❤️\n\n"

        response += "<b>BASE HP</b>\n"
        for res in results:
            response += f"{res['rus_nom']}: <code>{int(res['base_hp']):,}</code>\n"
        response += "\n"

        response += "<b>🆙 UPG</b>\n"
        for res in results:
            response += f"{res['rus_name']}: <code>{res['lvl']}</code>\n"

        response += "\n<b>💰 GOLD (Spent / Left to spend)</b>\n"
        for res in results:
            response += f"{res['rus_nom']}: <code>{res['spent']:,}</code> / <code>{res['rem']:,}</code>\n"

        response += "\n<b>🎲 ROLL</b>\n"
        for res in results:
            response += f"{res['rus_name']}: <b>{res['roll']}/11</b>\n"

        await update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except ValueError:
        await update.message.reply_text("Ошибка: Проверьте, что ХП и Уровни — это числа.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


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
