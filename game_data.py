# game_data.py

# --- I. БАЗА ДАННЫХ РОЛЛОВ И ХАРАКТЕРИСТИК ---

# --- A. ОРУЖИЕ (Урон) ---
CONQUERORS_BLADE_STATS = {
    1: 8032.5, 2: 8112.825, 3: 8193.15, 4: 8273.475, 5: 8353.8,
    6: 8434.125, 7: 8514.45, 8: 8594.775, 9: 8675.1, 10: 8755.425, 11: 8835.75
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

reforges = [
    {"name": "Godly", "dmg": "+50%", "crit": "+20%", "knk": "+20%"},
    {"name": "Vicious", "dmg": "+40%", "crit": "-20%", "knk": "0%"},
    {"name": "Mythical", "dmg": "+40%", "crit": "+30%", "knk": "+30%"},
    {"name": "Cruel", "dmg": "+30%", "crit": "0%", "knk": "+20%"},
    {"name": "Frenzied", "dmg": "+30%", "crit": "+20%", "knk": "+20%"},
    {"name": "Ruthless", "dmg": "+30%", "crit": "+10%", "knk": "+20%"},
    {"name": "Furious", "dmg": "+20%", "crit": "0%", "knk": "+30%"},
    {"name": "Legendary", "dmg": "+20%", "crit": "+10%", "knk": "+10%"},
    {"name": "Relentless", "dmg": "+20%", "crit": "+20%", "knk": "+20%"},
    {"name": "Superior", "dmg": "+20%", "crit": "+10%", "knk": "+10%"},
    {"name": "Savage", "dmg": "+10%", "crit": "-10%", "knk": "-10%"},
    {"name": "Dangerous", "dmg": "+10%", "crit": "0%", "knk": "0%"},
    {"name": "Hasty", "dmg": "+10%", "crit": "+20%", "knk": "+10%"},
    {"name": "Mystical", "dmg": "+10%", "crit": "+30%", "knk": "0%"},
    {"name": "Swift", "dmg": "0%", "crit": "+30%", "knk": "0%"},
    {"name": "Precise", "dmg": "0%", "crit": "+20%", "knk": "+10%"},
    {"name": "Murderous", "dmg": "-10%", "crit": "-10%", "knk": "-30%"}
]

WOODEN_SWORD_THRESHOLD_PERCENT = 4.7619
ASC_BASE_UPGRADE_COST = 2917
# --- КОНСТАНТЫ ДЛЯ WOODEN SWORD V2 ---
WOODEN_SWORD_OLD_BASE = 10395
WOODEN_SWORD_BUFF_MULTIPLIER = 1.111111111111858
WOODEN_SWORD_NEW_BASE = WOODEN_SWORD_OLD_BASE * WOODEN_SWORD_BUFF_MULTIPLIER  # БЕЗ ОКРУГЛЕНИЯ

# Заменить ASC_WEAPON_TYPES на:
ASC_WEAPON_TYPES = {
    'ws': {"name": "Wooden Sword V2", "base_dmg": WOODEN_SWORD_OLD_BASE, "fixed_roll": True, "has_rolls": False},  # Оставьте старую базу
    'mb': {"name": "Menta Blade V2", "stats": CONQUERORS_BLADE_STATS, "fixed_roll": False, "min_roll": 6},
    'lk': {"name": "Lightning Katana V2", "stats": CONQUERORS_BLADE_STATS, "fixed_roll": False, "min_roll": 6},
    'me': {"name": "Magma's Edge V2", "stats": CONQUERORS_BLADE_STATS, "fixed_roll": False, "min_roll": 6},
    'pt': {"name": "Poseidon's Trident V2", "stats": CONQUERORS_BLADE_STATS, "fixed_roll": False, "min_roll": 6},
    'dd': {"name": "Dual Daggers V2", "stats": CONQUERORS_BLADE_STATS, "fixed_roll": False, "min_roll": 6},
}

# --- D. СИСТЕМА СОПОСТАВЛЕНИЯ ДАННЫХ И СТОИМОСТИ ---
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
    "asc_ws": {
    "name": "Wooden Sword V2",
    "stats": {11: WOODEN_SWORD_OLD_BASE},
    "type": "asc_weapon",
    "upgrade_cost_lvl1": ASC_BASE_UPGRADE_COST,
    "max_level": 45,
    "weapon_key": "ws"
    },
    "asc_mb": {
        "name": "Menta Blade V2",
        "stats": CONQUERORS_BLADE_STATS,
        "type": "asc_weapon",
        "upgrade_cost_lvl1": ASC_BASE_UPGRADE_COST,
        "max_level": 45,
        "weapon_key": "mb"
    },
    "asc_lk": {
        "name": "Lightning Katana V2",
        "stats": CONQUERORS_BLADE_STATS,
        "type": "asc_weapon",
        "upgrade_cost_lvl1": ASC_BASE_UPGRADE_COST,
        "max_level": 45,
        "weapon_key": "lk"
    },
    "asc_me": {
        "name": "Magma's Edge V2",
        "stats": CONQUERORS_BLADE_STATS,
        "type": "asc_weapon",
        "upgrade_cost_lvl1": ASC_BASE_UPGRADE_COST,
        "max_level": 45,
        "weapon_key": "me"
    },
    "asc_pt": {
        "name": "Poseidon's Trident V2",
        "stats": CONQUERORS_BLADE_STATS,
        "type": "asc_weapon",
        "upgrade_cost_lvl1": ASC_BASE_UPGRADE_COST,
        "max_level": 45,
        "weapon_key": "pt"
    },
    "asc_dd": {
        "name": "Dual Daggers V2",
        "stats": CONQUERORS_BLADE_STATS,
        "type": "asc_weapon",
        "upgrade_cost_lvl1": ASC_BASE_UPGRADE_COST,
        "max_level": 45,
        "weapon_key": "dd"
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
    "legs": "Leggings"   # ← добавь это
}