"""
Inventory Database
==================
SQLite-backed persistence for household inventory.
Uses aiosqlite for async operations.
Database file: inventory.db in project root.
"""

import time
from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).parent.parent / "inventory.db"

# The 60 default items matching the React component's INITIAL_ITEMS exactly
DEFAULT_ITEMS = [
    # DAILY ESSENTIALS
    {"id": "d1",  "name": "Basmati Rice",        "category": "food",     "qty": 0.8,  "threshold": 1.8,  "unit": "kg",    "dailyUse": 0.60,  "barcode": "8901063021010"},
    {"id": "d2",  "name": "Toor Dal",            "category": "food",     "qty": 0.25, "threshold": 0.30, "unit": "kg",    "dailyUse": 0.10,  "barcode": "8906015980018"},
    {"id": "d3",  "name": "Idli Batter",         "category": "food",     "qty": 0.6,  "threshold": 0.90, "unit": "kg",    "dailyUse": 0.30,  "barcode": "8906003990011"},
    {"id": "d4",  "name": "Potato",              "category": "food",     "qty": 0.5,  "threshold": 0.75, "unit": "kg",    "dailyUse": 0.25,  "barcode": "0000000000001"},
    {"id": "d5",  "name": "Dahi / Curd",         "category": "food",     "qty": 0.3,  "threshold": 0.90, "unit": "kg",    "dailyUse": 0.30,  "barcode": "8901088005148"},
    {"id": "d6",  "name": "Green Chillies",      "category": "food",     "qty": 1,    "threshold": 2,    "unit": "pack",  "dailyUse": 0.20,  "barcode": "0000000000002"},
    {"id": "d7",  "name": "Coriander Leaves",    "category": "food",     "qty": 1,    "threshold": 2,    "unit": "bunch", "dailyUse": 0.50,  "barcode": "0000000000003"},
    {"id": "d8",  "name": "Full Cream Milk",     "category": "food",     "qty": 1.5,  "threshold": 4.5,  "unit": "L",     "dailyUse": 1.50,  "barcode": "6291003015505"},
    {"id": "d9",  "name": "Sugar",               "category": "food",     "qty": 0.18, "threshold": 0.18, "unit": "kg",    "dailyUse": 0.06,  "barcode": "8906015980070"},
    {"id": "d10", "name": "Chai Patti (Tea)",    "category": "food",     "qty": 60,   "threshold": 45,   "unit": "g",     "dailyUse": 15.0,  "barcode": "8901393010014"},
    # GRAINS
    {"id": "1",  "name": "Wheat Atta",           "category": "food",     "qty": 2.0,  "threshold": 0.90, "unit": "kg",    "dailyUse": 0.30,  "barcode": "8901072004001"},
    {"id": "3",  "name": "Poha",                 "category": "food",     "qty": 0.4,  "threshold": 0.15, "unit": "kg",    "dailyUse": 0.05,  "barcode": "8906003180012"},
    {"id": "4",  "name": "Sooji / Rava",         "category": "food",     "qty": 0.5,  "threshold": 0.10, "unit": "kg",    "dailyUse": 0.03,  "barcode": "8906003180029"},
    {"id": "5",  "name": "Besan",                "category": "food",     "qty": 0.4,  "threshold": 0.09, "unit": "kg",    "dailyUse": 0.03,  "barcode": "8901063060019"},
    # DALS
    {"id": "7",  "name": "Moong Dal",            "category": "food",     "qty": 0.5,  "threshold": 0.15, "unit": "kg",    "dailyUse": 0.05,  "barcode": "8906015980025"},
    {"id": "8",  "name": "Chana Dal",            "category": "food",     "qty": 0.4,  "threshold": 0.12, "unit": "kg",    "dailyUse": 0.04,  "barcode": "8906015980032"},
    {"id": "9",  "name": "Masoor Dal",           "category": "food",     "qty": 0,    "threshold": 0.12, "unit": "kg",    "dailyUse": 0.04,  "barcode": "8906015980049"},
    {"id": "10", "name": "Rajma",                "category": "food",     "qty": 0.3,  "threshold": 0.06, "unit": "kg",    "dailyUse": 0.02,  "barcode": "8906015980056"},
    {"id": "11", "name": "Chana (Kabuli)",       "category": "food",     "qty": 1.0,  "threshold": 0.06, "unit": "kg",    "dailyUse": 0.02,  "barcode": "8906015980063"},
    # DAIRY
    {"id": "14", "name": "Paneer",               "category": "food",     "qty": 0.2,  "threshold": 0.08, "unit": "kg",    "dailyUse": 0.028, "barcode": "8901063030025"},
    {"id": "15", "name": "Pure Ghee",            "category": "food",     "qty": 0.3,  "threshold": 0.045, "unit": "kg",   "dailyUse": 0.015, "barcode": "8901063040017"},
    {"id": "16", "name": "Butter",               "category": "food",     "qty": 2,    "threshold": 1,    "unit": "pack",  "dailyUse": 0.07,  "barcode": "8901063110018"},
    # OILS
    {"id": "17", "name": "Sunflower Oil",        "category": "food",     "qty": 0.5,  "threshold": 0.12, "unit": "L",     "dailyUse": 0.04,  "barcode": "8901764100015"},
    {"id": "18", "name": "Mustard Oil",          "category": "food",     "qty": 1.0,  "threshold": 0.045, "unit": "L",    "dailyUse": 0.015, "barcode": "8906007810016"},
    {"id": "19", "name": "Coconut Oil",          "category": "food",     "qty": 0.4,  "threshold": 0.015, "unit": "L",    "dailyUse": 0.005, "barcode": "8906009090018"},
    # SPICES
    {"id": "20", "name": "Turmeric Powder",      "category": "food",     "qty": 50,   "threshold": 15,   "unit": "g",     "dailyUse": 5,     "barcode": "8906013410015"},
    {"id": "21", "name": "Red Chilli Powder",    "category": "food",     "qty": 30,   "threshold": 15,   "unit": "g",     "dailyUse": 5,     "barcode": "8906013410022"},
    {"id": "22", "name": "Coriander Powder",     "category": "food",     "qty": 20,   "threshold": 15,   "unit": "g",     "dailyUse": 5,     "barcode": "8906013410039"},
    {"id": "23", "name": "Garam Masala",         "category": "food",     "qty": 40,   "threshold": 6,    "unit": "g",     "dailyUse": 2,     "barcode": "8906013410046"},
    {"id": "24", "name": "Cumin Seeds (Jeera)",  "category": "food",     "qty": 80,   "threshold": 6,    "unit": "g",     "dailyUse": 2,     "barcode": "8906013410053"},
    {"id": "25", "name": "Mustard Seeds (Rai)",  "category": "food",     "qty": 60,   "threshold": 6,    "unit": "g",     "dailyUse": 2,     "barcode": "8906013410060"},
    {"id": "26", "name": "Hing (Asafoetida)",    "category": "food",     "qty": 1,    "threshold": 1,    "unit": "pack",  "dailyUse": 0.007, "barcode": "8906013410077"},
    {"id": "27", "name": "Curry Leaves",         "category": "food",     "qty": 0,    "threshold": 1,    "unit": "pack",  "dailyUse": 0.15,  "barcode": "8906013410084"},
    {"id": "28", "name": "Dried Red Chillies",   "category": "food",     "qty": 1,    "threshold": 1,    "unit": "pack",  "dailyUse": 0.033, "barcode": "8906013410091"},
    {"id": "29", "name": "Methi Seeds",          "category": "food",     "qty": 50,   "threshold": 6,    "unit": "g",     "dailyUse": 2,     "barcode": "8906013410107"},
    {"id": "30", "name": "Chole/Sambar Masala",  "category": "food",     "qty": 1,    "threshold": 1,    "unit": "pack",  "dailyUse": 0.05,  "barcode": "8906013410114"},
    # ESSENTIALS
    {"id": "32", "name": "Jaggery (Gur)",        "category": "food",     "qty": 0.3,  "threshold": 0.06, "unit": "kg",    "dailyUse": 0.02,  "barcode": "8906015980087"},
    {"id": "33", "name": "Salt (Iodised)",       "category": "food",     "qty": 0.5,  "threshold": 0.06, "unit": "kg",    "dailyUse": 0.02,  "barcode": "8901030007507"},
    {"id": "34", "name": "Tamarind",             "category": "food",     "qty": 100,  "threshold": 15,   "unit": "g",     "dailyUse": 5,     "barcode": "8906013410121"},
    # DRY FRUITS
    {"id": "35", "name": "Cashews (Kaju)",       "category": "food",     "qty": 150,  "threshold": 30,   "unit": "g",     "dailyUse": 10,    "barcode": "8906025180018"},
    {"id": "36", "name": "Almonds (Badam)",      "category": "food",     "qty": 80,   "threshold": 30,   "unit": "g",     "dailyUse": 10,    "barcode": "8906025180025"},
    {"id": "37", "name": "Raisins (Kishmish)",   "category": "food",     "qty": 0,    "threshold": 30,   "unit": "g",     "dailyUse": 10,    "barcode": "8906025180032"},
    # BEVERAGES
    {"id": "39", "name": "Instant Coffee",       "category": "food",     "qty": 50,   "threshold": 15,   "unit": "g",     "dailyUse": 5,     "barcode": "8901030837408"},
    {"id": "40", "name": "Bournvita / Horlicks", "category": "food",     "qty": 0.2,  "threshold": 0.075, "unit": "kg",   "dailyUse": 0.025, "barcode": "8901022015101"},
    # BATHROOM
    {"id": "41", "name": "Toothpaste",           "category": "bathroom", "qty": 2,    "threshold": 1,    "unit": "pack",  "dailyUse": 0.033, "barcode": "8710908537578"},
    {"id": "42", "name": "Shampoo",              "category": "bathroom", "qty": 0,    "threshold": 1,    "unit": "bottle", "dailyUse": 0.033, "barcode": "3614227906808"},
    {"id": "43", "name": "Soap Bar",             "category": "bathroom", "qty": 3,    "threshold": 2,    "unit": "piece", "dailyUse": 0.05,  "barcode": "8901030015502"},
    {"id": "44", "name": "Toilet Cleaner",       "category": "bathroom", "qty": 1,    "threshold": 1,    "unit": "bottle", "dailyUse": 0.05,  "barcode": "8901030011207"},
    {"id": "45", "name": "Conditioner",          "category": "bathroom", "qty": 0.5,  "threshold": 1,    "unit": "bottle", "dailyUse": 0.033, "barcode": "3614227900012"},
    # COSMETICS
    {"id": "46", "name": "Coconut Hair Oil",     "category": "cosmetics", "qty": 1,   "threshold": 1,    "unit": "bottle", "dailyUse": 0.033, "barcode": "8901801012102"},
    {"id": "47", "name": "Face Wash",            "category": "cosmetics", "qty": 1,   "threshold": 1,    "unit": "bottle", "dailyUse": 0.033, "barcode": "8901396005405"},
    {"id": "48", "name": "Moisturiser",          "category": "cosmetics", "qty": 0,   "threshold": 1,    "unit": "bottle", "dailyUse": 0.033, "barcode": "3614225734045"},
    {"id": "49", "name": "Kumkum / Sindoor",     "category": "cosmetics", "qty": 1,   "threshold": 1,    "unit": "pack",   "dailyUse": 0.007, "barcode": "8906029180015"},
    {"id": "50", "name": "Kajal",                "category": "cosmetics", "qty": 2,   "threshold": 1,    "unit": "piece",  "dailyUse": 0.007, "barcode": "8906029180022"},
    # HOUSEHOLD
    {"id": "51", "name": "Dish Wash Bar",        "category": "household", "qty": 2,   "threshold": 2,    "unit": "piece",  "dailyUse": 0.10,  "barcode": "8901030082619"},
    {"id": "52", "name": "Dish Wash Liquid",     "category": "household", "qty": 0.4, "threshold": 0.15, "unit": "bottle", "dailyUse": 0.05,  "barcode": "8901030082626"},
    {"id": "53", "name": "Laundry Detergent",    "category": "household", "qty": 0.5, "threshold": 0.30, "unit": "kg",     "dailyUse": 0.10,  "barcode": "8001090178176"},
    {"id": "54", "name": "Floor Cleaner",        "category": "household", "qty": 0.5, "threshold": 0.15, "unit": "L",      "dailyUse": 0.05,  "barcode": "8901030900019"},
    {"id": "55", "name": "Phenyl",               "category": "household", "qty": 1,   "threshold": 1,    "unit": "bottle", "dailyUse": 0.033, "barcode": "8901030900026"},
    {"id": "56", "name": "Agarbatti (Incense)",  "category": "household", "qty": 2,   "threshold": 1,    "unit": "pack",   "dailyUse": 0.10,  "barcode": "8906017810012"},
    {"id": "57", "name": "Camphor (Kapoor)",     "category": "household", "qty": 0,   "threshold": 1,    "unit": "pack",   "dailyUse": 0.033, "barcode": "8906017810029"},
    {"id": "58", "name": "Garbage Bags",         "category": "household", "qty": 1,   "threshold": 1,    "unit": "roll",   "dailyUse": 0.033, "barcode": "8906037810015"},
    {"id": "59", "name": "Tissue / Napkins",     "category": "household", "qty": 3,   "threshold": 2,    "unit": "pack",   "dailyUse": 0.10,  "barcode": "0037000917007"},
    {"id": "60", "name": "Mosquito Repellent",   "category": "household", "qty": 0,   "threshold": 1,    "unit": "bottle", "dailyUse": 0.033, "barcode": "8901030570018"},
]


async def init_db():
    """Create tables and seed with default items if empty."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS inventory_items (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                category    TEXT NOT NULL DEFAULT 'food',
                qty         REAL NOT NULL DEFAULT 0,
                threshold   REAL NOT NULL DEFAULT 0,
                unit        TEXT NOT NULL DEFAULT 'piece',
                daily_use   REAL NOT NULL DEFAULT 0,
                barcode     TEXT DEFAULT '',
                created_at  TEXT DEFAULT (datetime('now')),
                updated_at  TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS consume_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                dish_name   TEXT,
                item_id     TEXT,
                item_name   TEXT,
                delta       REAL,
                unit        TEXT,
                logged_at   TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.commit()

        cursor = await db.execute("SELECT COUNT(*) FROM inventory_items")
        count = (await cursor.fetchone())[0]
        if count == 0:
            for item in DEFAULT_ITEMS:
                await db.execute("""
                    INSERT INTO inventory_items
                        (id, name, category, qty, threshold, unit, daily_use, barcode)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item["id"], item["name"], item["category"],
                    item["qty"], item["threshold"], item["unit"],
                    item["dailyUse"], item["barcode"]
                ))
            await db.commit()


async def get_all_items() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM inventory_items ORDER BY category, name"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_food_items() -> list[dict]:
    """Returns only food items. Used by Fridge to Fork scan."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM inventory_items WHERE category = 'food' ORDER BY name"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def update_item_qty(item_id: str, new_qty: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE inventory_items
            SET qty = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (max(0, round(new_qty, 3)), item_id))
        await db.commit()


async def adjust_item_qty(item_id: str, delta: float):
    """Atomically adjust qty by delta (positive = add, negative = deduct)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT qty FROM inventory_items WHERE id = ?", (item_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        new_qty = max(0, round(row[0] + delta, 3))
        await db.execute("""
            UPDATE inventory_items
            SET qty = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (new_qty, item_id))
        await db.commit()
        return new_qty


async def upsert_item(item: dict):
    """Add new item or update existing."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO inventory_items
                (id, name, category, qty, threshold, unit, daily_use, barcode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name      = excluded.name,
                category  = excluded.category,
                qty       = excluded.qty,
                threshold = excluded.threshold,
                unit      = excluded.unit,
                daily_use = excluded.daily_use,
                barcode   = excluded.barcode,
                updated_at = datetime('now')
        """, (
            item.get("id") or f"custom_{int(time.time() * 1000)}",
            item["name"], item["category"],
            item["qty"], item["threshold"],
            item["unit"], item.get("dailyUse", item.get("daily_use", 0)),
            item.get("barcode", "")
        ))
        await db.commit()


async def delete_item(item_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM inventory_items WHERE id = ?", (item_id,)
        )
        await db.commit()


async def log_consumption(dish_name: str, items: list[dict]):
    """Log ingredient consumption after cooking."""
    async with aiosqlite.connect(DB_PATH) as db:
        for item in items:
            await db.execute("""
                INSERT INTO consume_log (dish_name, item_id, item_name, delta, unit)
                VALUES (?, ?, ?, ?, ?)
            """, (
                dish_name,
                item.get("itemId", ""),
                item.get("itemName", ""),
                item.get("delta", 0),
                item.get("unit", "")
            ))
        await db.commit()


async def fuzzy_match_items(
    ordered_names: list[str],
    inventory: list[dict]
) -> list[dict]:
    """
    Match Instamart ordered item names to inventory items.
    Returns list of matches with item_id and delta.
    """
    results = []
    name_map = {i["name"].lower(): i["id"] for i in inventory}

    for name in ordered_names:
        name_lower = name.lower()
        matched_id = None

        if name_lower in name_map:
            matched_id = name_map[name_lower]
        else:
            for inv_name, inv_id in name_map.items():
                if name_lower in inv_name or inv_name in name_lower:
                    matched_id = inv_id
                    break

        results.append({
            "name": name,
            "item_id": matched_id,
            "matched": matched_id is not None
        })
    return results
