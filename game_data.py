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

# --- TIMELOST WEAPONS ---
TIMELOST_CONQUERORS_BLADE_STATS = {
    1: 6825, 2: 6893.25, 3: 6961.5, 4: 7029.75, 5: 7098.05,
    6: 7166.25, 7: 7234.5, 8: 7302.75, 9: 7371, 10: 7439.25, 11: 7507.5
}

TIMELOST_CONQUERORS_BLADE_LE_STATS = {
    1: 8925.2, 2: 9014.43, 3: 9103.65, 4: 9192.88, 5: 9282.11,
    6: 9371.33, 7: 9460.56, 8: 9549.79, 9: 9639.02, 10: 9728.24, 11: 9817.47
}

# --- CUPID WEAPONS ---
CUPIDS_FURY_STATS = {
    1: 4462.5, 2: 4507.125, 3: 4551.75, 4: 4596.375, 5: 4641,
    6: 4685.625, 7: 4730.25, 8: 4774.875, 9: 4819.5, 10: 4864.125, 11: 4908.75
}

DIFFERENT_PROCENT_CHECK = 4.7619  # Для определения L.E. версии

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

HKR_STATS = { # Heroic Kronax Set (Secret)
    "Helmet": {
        1: 840.0003, 2: 848.40033, 3: 856.80036, 4: 865.20039, 5: 873.60042,
        6: 882.00045, 7: 890.40048, 8: 898.80051, 9: 907.20054, 10: 915.60057, 11: 924.0006
    },
    "Chestplate": {
        1: 840.0003, 2: 848.40033, 3: 856.80036, 4: 865.20039, 5: 873.60042,
        6: 882.00045, 7: 890.40048, 8: 898.80051, 9: 907.20054, 10: 915.60057, 11: 924.0006
    },
    "Leggings": {
        1: 840.0003, 2: 848.40033, 3: 856.80036, 4: 865.20039, 5: 873.60042,
        6: 882.00045, 7: 890.40048, 8: 898.80051, 9: 907.20054, 10: 915.60057, 11: 924.0006
    }
}

KR_STATS = { # Kronax Set (Mythic)
    "Helmet": {
        1: 787.5, 2: 795.375, 3: 803.25, 4: 811.125, 5: 819.0,
        6: 826.875, 7: 834.75, 8: 842.625, 9: 850.5, 10: 858.375, 11: 866.25
    },
    "Chestplate": {
        1: 787.5, 2: 795.375, 3: 803.25, 4: 811.125, 5: 819.0,
        6: 826.875, 7: 834.75, 8: 842.625, 9: 850.5, 10: 858.375, 11: 866.25
    },
    "Leggings": {
        1: 787.5, 2: 795.375, 3: 803.25, 4: 811.125, 5: 819.0,
        6: 826.875, 7: 834.75, 8: 842.625, 9: 850.5, 10: 858.375, 11: 866.25
    }
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

UPGRADE_COSTS = {
    1: 500, 2: 1500, 3: 2750, 4: 4000, 5: 6000, 6: 8000, 7: 10500, 8: 13000, 9: 15500, 10: 18000,
    11: 21000, 12: 24500, 13: 28000, 14: 32000, 15: 35000, 16: 45000, 17: 57500, 18: 70000, 19: 73000, 20: 88000,
    21: 100000, 22: 150000, 23: 250000, 24: 400000, 25: 550000, 26: 700000, 27: 900000, 28: 1100000, 29: 1300000, 30: 1800000,
    31: 2300000, 32: 2800000, 33: 3300000, 34: 3800000, 35: 4300000, 36: 4800000, 37: 5300000, 38: 5800000, 39: 6300000, 40: 6800000,
    41: 7300000, 42: 7800000, 43: 8300000, 44: 8800000, 45: 9300000, 46: 9800000, 47: 10300000, 48: 10800000, 49: 11300000, 50: 11800000,
    51: 12300000, 52: 12800000, 53: 13300000, 54: 13800000, 55: 14300000, 56: 14800000, 57: 15300000, 58: 15800000, 59: 16300000, 60: 16800000,
    61: 17300000, 62: 17800000, 63: 18300000, 64: 18800000, 65: 19300000, 66: 19800000, 67: 20300000, 68: 20800000, 69: 21300000, 70: 21800000,
    71: 22300000, 72: 22800000, 73: 23300000, 74: 23800000, 75: 24300000, 76: 24800000, 77: 25300000, 78: 25800000, 79: 26300000, 80: 26800000,
    81: 27800000, 82: 28800000, 83: 29800000, 84: 30800000, 85: 31800000, 86: 32800000, 87: 33800000, 88: 34800000, 89: 35800000, 90: 36800000,
    91: 37800000, 92: 38800000, 93: 39800000, 94: 40800000, 95: 41800000, 96: 42800000, 97: 43800000, 98: 44800000, 99: 45800000
}

WOODEN_SWORD_BASE = 11550

# Заменить ASC_WEAPON_TYPES на:
ASC_WEAPON_TYPES = {
    'ws': {"name": "Wooden Sword V2", "base_dmg": WOODEN_SWORD_BASE, "fixed_roll": True, "has_rolls": False},  # Оставьте старую базу
    'mb': {"name": "Menta Blade V2", "stats": CONQUERORS_BLADE_STATS, "fixed_roll": False, "min_roll": 6},
    'lk': {"name": "Lightning Katana V2", "stats": CONQUERORS_BLADE_STATS, "fixed_roll": False, "min_roll": 6},
    'me': {"name": "Magma's Edge V2", "stats": CONQUERORS_BLADE_STATS, "fixed_roll": False, "min_roll": 6},
    'at': {"name": "Abyssal Trident", "stats": CONQUERORS_BLADE_STATS, "fixed_roll": False, "min_roll": 6},
    'ad': {"name": "Ascended Daggers", "stats": CONQUERORS_BLADE_STATS, "fixed_roll": False, "min_roll": 6},
    'av': {"name": "Ascended Voidblade", "stats": CONQUERORS_BLADE_STATS, "fixed_roll": False, "min_roll": 6},
}

# --- D. СИСТЕМА СОПОСТАВЛЕНИЯ ДАННЫХ И СТОИМОСТИ ---
ITEMS_MAPPING = {
    # --- ОБЫЧНОЕ ОРУЖИЕ ---
    "cb": {
        "name": "Conqueror's Blade",
        "stats": CONQUERORS_BLADE_STATS,
        "type": "weapon",
        "category": "normal",
        "max_level": 44
    },
    "db": {
        "name": "Doombringer",
        "stats": DOOMBRINGER_STATS,
        "type": "weapon",
        "category": "normal",
        "max_level": 34
    },

    # --- ASC ОРУЖИЕ ---
    "asc_ws": {
        "name": "Wooden Sword V2",
        "stats": {11: WOODEN_SWORD_BASE},
        "type": "asc_weapon",
        "category": "asc",
        "weapon_key": "ws",
        "max_level": 74,
    },
    "asc_mb": {
        "name": "Menta Blade V2",
        "stats": CONQUERORS_BLADE_STATS,
        "type": "asc_weapon",
        "category": "asc",
        "weapon_key": "mb",
        "max_level": 74,
    },
    "asc_lk": {
        "name": "Lightning Katana V2",
        "stats": CONQUERORS_BLADE_STATS,
        "type": "asc_weapon",
        "category": "asc",
        "weapon_key": "lk",
        "max_level": 74,
    },
    "asc_me": {
        "name": "Magma's Edge V2",
        "stats": CONQUERORS_BLADE_STATS,
        "type": "asc_weapon",
        "category": "asc",
        "weapon_key": "me",
        "max_level": 74,
    },
    "asc_at": {
        "name": "Abyssal Trident",
        "stats": CONQUERORS_BLADE_STATS,
        "type": "asc_weapon",
        "category": "asc",
        "weapon_key": "pt",
        "max_level": 74,
    },
    "asc_ad": {
        "name": "Ascended Daggers",
        "stats": DUAL_DAGGERS_V2_STATS,
        "type": "asc_weapon",
        "category": "asc",
        "weapon_key": "dd",
        "max_level": 74,
    },
    "asc_av": {
        "name": "Ascended Voidblade",
        "stats": CONQUERORS_BLADE_STATS,
        "type": "asc_weapon",
        "category": "asc",
        "weapon_key": "av",
        "max_level": 74,
    },

    # --- TIMELOST ОРУЖИЕ ---
    "tl": {
        "name": "Timelost Conqueror's Blade",
        "stats": TIMELOST_CONQUERORS_BLADE_STATS,
        "type": "weapon",
        "category": "tl",
        "max_level": 44
    },
    "tl_le": {
        "name": "Timelost Conqueror's Blade (Limited Edition)",
        "stats": TIMELOST_CONQUERORS_BLADE_LE_STATS,
        "type": "asc_weapon",
        "category": "tl",
        "weapon_key": "tl_le",
        "max_level": 44,
    },

    # --- БРОНЯ ---
    "fzh": {
        "name": "Furious Zeus Set",
        "stats": FZH_STATS,
        "type": "armor_set",
        "category": "armor",
        "max_level": 45
    },
    "lzs": {
        "name": "Zeus Set",
        "stats": LZS_STATS,
        "type": "armor_set",
        "category": "armor",
        "max_level": 34
    },
    "hks": {
        "name": "Heroic Kronax Set",
        "stats": HKR_STATS,
        "type": "armor_set",
        "category": "armor",
        "max_level": 99
    },
    "ks": {
        "name": "Kronax Set",
        "stats": KR_STATS,
        "type": "armor_set",
        "category": "armor",
        "max_level": 44
    },
    "cup": {
        "name": "Cupid's Fury",
        "stats": CUPIDS_FURY_STATS,
        "type": "weapon",
        "category": "cup",
        "max_level": 74
    },
    "cup_sw": {
        "name": "Cupid's Wrath",
        "stats": DOOMBRINGER_STATS,
        "type": "weapon",
        "category": "cup",
        "weapon_key": "cup_sw",
        "max_level": 99
    }
}
# Маппинг частей брони
PART_MAPPING = {
    "helm": "Helmet",
    "chest": "Chestplate",
    "legs": "Leggings"   # ← добавь это
}
