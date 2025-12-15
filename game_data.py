# game_data.py

# --- I. БАЗА ДАННЫХ РОЛЛОВ И ХАРАКТЕРИСТИК ---

# --- A. ОРУЖИЕ (Урон) ---
CONQUERORS_BLADE_STATS = {
    1: 8032, 2: 8112, 3: 8193, 4: 8273, 5: 8353,
    6: 8434, 7: 8514, 8: 8594, 9: 8675, 10: 8755, 11: 8835
}

DOOMBRINGER_STATS = {
    1: 6300, 2: 6363, 3: 6426, 4: 6489, 5: 6552,
    6: 6615, 7: 6678, 8: 6741, 9: 6804, 10: 6867, 11: 6930
}

# --- B. БРОНЯ (ХП) ---
FZH_STATS = { # Mythic Zeus Set (Furious)
    "Helmet": {1: 787, 2: 795, 3: 803, 4: 811, 5: 818, 6: 826, 7: 834, 8: 842, 9: 850, 10: 858, 11: 866},
    "Chestplate": {1: 708, 2: 715, 3: 722, 4: 729, 5: 736, 6: 743, 7: 750, 8: 758, 9: 765, 10: 772, 11: 779},
    "Leggings": {1: 682, 2: 689, 3: 696, 4: 702, 5: 709, 6: 716, 7: 723, 8: 730, 9: 737, 10: 743, 11: 750}
}

LZS_STATS = { # Legendary Zeus Set
    "Helmet": {1: 577, 2: 583, 3: 589, 4: 594, 5: 600, 6: 606, 7: 612, 8: 617, 9: 623, 10: 629, 11: 635},
    "Chestplate": {1: 603, 2: 609, 3: 615, 4: 621, 5: 627, 6: 633, 7: 639, 8: 646, 9: 652, 10: 658, 11: 664},
    "Leggings": FZH_STATS["Leggings"]
}

# --- C. МОДИФИКАТОРЫ REFORGE ---
REFORGE_MODIFIERS = {
    "Vicious": 1.4, "Cruel": 1.3, "Savage": 1.1, "Dangerous": 1.1, "Frenzied": 1.3,
    "Furious": 1.2, "Legendary": 1.2, "Hasty": 1.1, "Swift": 1.0, "Relentless": 1.2,
    "Percise": 1.0, "Superior": 1.2, "Godly": 1.5, "Ruthless": 1.3, "Murderous": 0.9,
    "Mystical": 1.1, "Mythical": 1.4
}

# --- D. СИСТЕМА СОПОСТАВЛЕНИЯ ДАННЫХ И СТОИМОСТИ ---
# ДОБАВЛЕНО: max_level для каждого предмета
ITEMS_MAPPING = {
    "cb": {
        "name": "Conqueror's Blade",
        "stats": CONQUERORS_BLADE_STATS,
        "type": "weapon",
        "upgrade_cost_lvl1": 2535,
        "max_level": 45
    },
    "db": {
        "name": "Doombringer",
        "stats": DOOMBRINGER_STATS,
        "type": "weapon",
        "upgrade_cost_lvl1": 2112,
        "max_level": 34
    },
    "fzh": {
        "name": "Furious Zeus Set (Mythic)",
        "stats": FZH_STATS,
        "type": "armor_set",
        "upgrade_cost_lvl1": 2535,
        "max_level": 45
    },
    "lzs": {
        "name": "Legendary Zeus Set",
        "stats": LZS_STATS,
        "type": "armor_set",
        "upgrade_cost_lvl1": 2112,
        "max_level": 34
    },
}

# Маппинг частей брони
PART_MAPPING = {
    "helm": "Helmet",
    "chest": "Chestplate",
    "leg": "Leggings"
}