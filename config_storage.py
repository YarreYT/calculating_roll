import json
import os
from typing import Dict, Any, Optional

# Структура: {group_id: {"topics": {topic_id: "name"}, "allow_non_topic": bool}}
DEFAULT_TOPICS = {
    "-1003188833915": {
        "topics": {
            "97989": "CALCULATE ROLL"
        },
        "allow_non_topic": False
    }
}

ALLOWED_TOPICS_FILE = "allowed_topics.json"
ALLOWED_TOPICS: Dict[str, Dict[str, Any]] = {}


def load_allowed_topics() -> Dict[str, Dict[str, Any]]:
    global ALLOWED_TOPICS

    # Сначала проверяем локальный файл
    if os.path.exists("allowed_topics.local.json"):
        try:
            with open("allowed_topics.local.json", 'r', encoding='utf-8') as f:
                ALLOWED_TOPICS = json.load(f)
            print("✅ Загружены локальные настройки")
            return ALLOWED_TOPICS
        except Exception as e:
            print(f"⚠️ Ошибка загрузки локального файла: {e}")

    # Если локального нет, загружаем основной
    if os.path.exists(ALLOWED_TOPICS_FILE):
        try:
            with open(ALLOWED_TOPICS_FILE, 'r', encoding='utf-8') as f:
                ALLOWED_TOPICS = json.load(f)
            print(f"✅ Загружены дефолтные настройки")
        except Exception as e:
            print(f"⚠️ Ошибка загрузки: {e}, используются значения по умолчанию")
            ALLOWED_TOPICS = DEFAULT_TOPICS.copy()
    else:
        ALLOWED_TOPICS = DEFAULT_TOPICS.copy()
        print("ℹ️ Файл не найден, используются значения по умолчанию")

    return ALLOWED_TOPICS

def save_allowed_topics():
    """Сохраняет текущие разрешённые топики в файл"""
    try:
        with open(ALLOWED_TOPICS_FILE, 'w', encoding='utf-8') as f:
            json.dump(ALLOWED_TOPICS, f, indent=2, ensure_ascii=False)
        print(f"💾 Разрешённые топики сохранены в {ALLOWED_TOPICS_FILE}")
    except Exception as e:
        print(f"❌ Ошибка сохранения топиков: {e}")


def get_group_topics(group_id: str) -> Optional[Dict[str, Any]]:
    """Получает настройки топиков для конкретной группы"""
    return ALLOWED_TOPICS.get(str(group_id))


def add_topic_to_group(group_id: str, topic_id: str, topic_name: str) -> bool:
    """Добавляет топик в список разрешённых для группы"""
    group_id = str(group_id)
    topic_id = str(topic_id)

    if group_id not in ALLOWED_TOPICS:
        ALLOWED_TOPICS[group_id] = {
            "topics": {},
            "allow_non_topic": False
        }

    ALLOWED_TOPICS[group_id]["topics"][topic_id] = topic_name
    save_allowed_topics()
    return True


def remove_topic_from_group(group_id: str, topic_id: str) -> bool:
    """Удаляет конкретный топик из группы"""
    group_id = str(group_id)
    topic_id = str(topic_id)

    if group_id in ALLOWED_TOPICS and topic_id in ALLOWED_TOPICS[group_id]["topics"]:
        del ALLOWED_TOPICS[group_id]["topics"][topic_id]

        # Если топиков больше нет, удаляем запись группы
        if not ALLOWED_TOPICS[group_id]["topics"]:
            del ALLOWED_TOPICS[group_id]

        save_allowed_topics()
        return True
    return False


def clear_all_topics(group_id: str) -> bool:
    """Очищает все топики для группы"""
    group_id = str(group_id)

    if group_id in ALLOWED_TOPICS:
        ALLOWED_TOPICS[group_id]["topics"].clear()
        save_allowed_topics()
        return True
    return False


def set_allow_non_topic(group_id: str, allow: bool):
    """Разрешает/запрещает команды в обычном чате (без топика)"""
    group_id = str(group_id)

    if group_id not in ALLOWED_TOPICS:
        ALLOWED_TOPICS[group_id] = {
            "topics": {},
            "allow_non_topic": allow
        }
    else:
        ALLOWED_TOPICS[group_id]["allow_non_topic"] = allow

    save_allowed_topics()
    return True


def is_topic_allowed(group_id: str, topic_id: Optional[int], is_private_chat: bool = False) -> bool:
    """Проверяет, разрешён ли топик для команд"""
    if is_private_chat:
        return True  # В ЛС всегда разрешено

    group_id = str(group_id)
    if group_id not in ALLOWED_TOPICS:
        return False

    group_data = ALLOWED_TOPICS[group_id]

    # Если топик не указан (обычный чат без топиков)
    if topic_id is None:
        return group_data.get("allow_non_topic", False)

    # Проверяем конкретный топик
    return str(topic_id) in group_data["topics"]