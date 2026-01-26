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

# --- НОВЫЕ КОНСТАНТЫ ДЛЯ DUAL DAGGERS V2 ---
DUAL_DAGGERS_V2_STATS = {
    6: 5126.44,
    7: 5175.298,
    8: 5224.156,
    9: 5273.014,
    10: 5321.872,
    11: 5370.73
}

# --- B. БРОНЯ (ХП) ---
FZH_STATS = { # Mythic Zeus Set (Furious)
    "Helmet": {
        1: 787.5, 2: 795.375, 3: 803.25, 4: 811.125, 5: 819.0,
        6: 826.875, 7: 834.75, 8: 842.625, 9: 850.5, 10: 858.375, 11: 866.25
    },
    "Chestplate": {
        1: 708.85, 2: 715.9074, 3: 722.9648, 4: 730.0222, 5: 737.0796,
        6: 744.137, 7: 751.1944, 8: 758.2518, 9: 765.3092, 10: 772.3666, 11: 779.424
    },
    "Leggings": {
        1: 682.5, 2: 689.317, 3: 696.134, 4: 702.951, 5: 709.768,
        6: 716.585, 7: 723.402, 8: 730.219, 9: 737.036, 10: 743.853, 11: 750.67
    }
}

LZS_STATS = { # Legendary Zeus Set
    "Helmet": {1: 577.5, 2: 583.275, 3: 589.05, 4: 594.825, 5: 600.6, 6: 606.375, 7: 612.15, 8: 617.925, 9: 623.7, 10: 629.475, 11: 635.25},
    "Chestplate": {1: 603.75, 2: 609.7875, 3: 615.825, 4: 621.8625, 5: 627.9, 6: 633.9375, 7: 639.975, 8: 646.0125, 9: 652.05, 10: 658.0875, 11: 664.125},
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
        "stats": DUAL_DAGGERS_V2_STATS,
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