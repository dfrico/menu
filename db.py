"""SQLite storage for dishes, ingredients and the current menu.

Every write bumps `version` in the settings table, which clients watch to know
when to refresh (see /api/events in app.py).
"""
from contextlib import contextmanager
from datetime import date, timedelta
import csv
import os
import sqlite3
import sys

import config
import menu

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("MENU_DB", os.path.join(HERE, "menu.db"))
LEGACY_CSV = os.path.join(HERE, "dish_list.csv")


class NotFound(LookupError):
    pass


SCHEMA = """
CREATE TABLE dishes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    tag TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE ingredients (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE dish_ingredients (
    dish_id INTEGER NOT NULL REFERENCES dishes(id) ON DELETE CASCADE,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id),
    main INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (dish_id, ingredient_id)
);
CREATE TABLE menu_slots (
    week INTEGER NOT NULL,
    day TEXT NOT NULL,
    meal TEXT NOT NULL,
    dish_id INTEGER REFERENCES dishes(id) ON DELETE SET NULL,
    PRIMARY KEY (week, day, meal)
);
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(path=None):
    conn = sqlite3.connect(path or DB_PATH, isolation_level=None, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def migrate(conn):
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 1:
        return
    with write(conn, bump=False):
        for stmt in SCHEMA.split(";"):
            if stmt.strip():
                conn.execute(stmt)
        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            [("version", "0"), ("weeks", str(config.DEFAULT_WEEKS)), ("start_date", "")],
        )
        conn.execute("PRAGMA user_version = 1")
    if os.path.exists(LEGACY_CSV):
        import_csv(conn, LEGACY_CSV)


@contextmanager
def write(conn, bump=True):
    """Run a block in a write transaction; bump the version on success."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        if bump:
            conn.execute(
                "UPDATE settings SET value = CAST(value AS INTEGER) + 1 WHERE key = 'version'"
            )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def setting(conn, key):
    return conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()[0]


def set_setting(conn, key, value):
    conn.execute("UPDATE settings SET value = ? WHERE key = ?", (str(value), key))


def version(conn):
    return int(setting(conn, "version"))


# --- Dishes ---------------------------------------------------------------


def list_dishes(conn):
    dishes = {
        r["id"]: {**dict(r), "ingredients": []}
        for r in conn.execute("SELECT id, name, tag, notes FROM dishes ORDER BY name")
    }
    for r in conn.execute(
        """SELECT di.dish_id, i.name, di.main FROM dish_ingredients di
           JOIN ingredients i ON i.id = di.ingredient_id
           ORDER BY di.main DESC, i.name"""
    ):
        dishes[r["dish_id"]]["ingredients"].append({"name": r["name"], "main": bool(r["main"])})
    return list(dishes.values())


def get_dish(conn, dish_id):
    return next((d for d in list_dishes(conn) if d["id"] == dish_id), None)


def _clean_dish(data):
    name = str(data.get("name", "")).strip()
    tag = str(data.get("tag", "")).strip().lower()
    if not name:
        raise ValueError("The dish needs a name.")
    if not tag:
        raise ValueError("The dish needs a tag (e.g. chicken, fish, vegetarian).")
    ingredients = {}
    for item in data.get("ingredients") or []:
        if isinstance(item, str):
            item = {"name": item}
        ing = str(item.get("name", "")).strip().lower()
        if ing:
            ingredients[ing] = bool(item.get("main", True))
    return name, tag, str(data.get("notes") or "").strip(), ingredients


def save_dish(conn, data, dish_id=None):
    """Create (dish_id=None) or replace a dish. Returns its id."""
    name, tag, notes, ingredients = _clean_dish(data)
    with write(conn):
        clash = conn.execute(
            "SELECT id FROM dishes WHERE name = ? AND id IS NOT ?", (name, dish_id)
        ).fetchone()
        if clash:
            raise ValueError(f"A dish called '{name}' already exists.")
        if dish_id is None:
            dish_id = conn.execute(
                "INSERT INTO dishes (name, tag, notes) VALUES (?, ?, ?)", (name, tag, notes)
            ).lastrowid
        else:
            cur = conn.execute(
                "UPDATE dishes SET name = ?, tag = ?, notes = ? WHERE id = ?",
                (name, tag, notes, dish_id),
            )
            if cur.rowcount == 0:
                raise NotFound("Dish not found.")
            conn.execute("DELETE FROM dish_ingredients WHERE dish_id = ?", (dish_id,))
        for ing, main in ingredients.items():
            conn.execute("INSERT OR IGNORE INTO ingredients (name) VALUES (?)", (ing,))
            ing_id = conn.execute("SELECT id FROM ingredients WHERE name = ?", (ing,)).fetchone()[0]
            conn.execute(
                "INSERT INTO dish_ingredients (dish_id, ingredient_id, main) VALUES (?, ?, ?)",
                (dish_id, ing_id, int(main)),
            )
    return dish_id


def delete_dish(conn, dish_id):
    with write(conn):
        if conn.execute("DELETE FROM dishes WHERE id = ?", (dish_id,)).rowcount == 0:
            raise NotFound("Dish not found.")


def import_csv(conn, path):
    """Import dishes from a `name,tag[,ingredients]` CSV (ingredients separated by ';').
    Existing dishes (same name) are skipped. Returns the number imported."""
    existing = {r[0].lower() for r in conn.execute("SELECT name FROM dishes")}
    count = 0
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["name"].strip().lower() in existing:
                continue
            ingredients = [i for i in (row.get("ingredients") or "").split(";") if i.strip()]
            save_dish(conn, {"name": row["name"], "tag": row["tag"], "ingredients": ingredients})
            existing.add(row["name"].strip().lower())
            count += 1
    return count


def export_csv(conn, out):
    writer = csv.writer(out)
    writer.writerow(["name", "tag", "ingredients"])
    for d in list_dishes(conn):
        writer.writerow([d["name"], d["tag"], ";".join(i["name"] for i in d["ingredients"])])


# --- Menu -----------------------------------------------------------------


def _check_slot(conn, slot):
    try:
        week, day, meal = int(slot["week"]), slot["day"], slot["meal"]
    except (KeyError, TypeError, ValueError):
        raise ValueError("A slot needs week, day and meal.")
    if not (1 <= week <= int(setting(conn, "weeks"))) or day not in config.DAYS or meal not in config.MEALS:
        raise ValueError(f"Invalid slot: week {week} {day} {meal}.")
    if (day, meal) in config.FREE_SLOTS:
        raise ValueError(f"{day} {meal.lower()} is a free meal.")
    return week, day, meal


def _slot_dish(conn, slot):
    row = conn.execute(
        "SELECT dish_id FROM menu_slots WHERE week = ? AND day = ? AND meal = ?", slot
    ).fetchone()
    return row[0] if row else None


def _put(conn, slot, dish_id):
    conn.execute(
        "INSERT OR REPLACE INTO menu_slots (week, day, meal, dish_id) VALUES (?, ?, ?, ?)",
        (*slot, dish_id),
    )


def _all_dishes(conn):
    return [(r["id"], r["tag"]) for r in conn.execute("SELECT id, tag FROM dishes")]


def _start_monday(today=None):
    """Monday of this week, or of next week if it's already the weekend."""
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    return monday + timedelta(weeks=1) if today.weekday() >= 5 else monday


def generate(conn, weeks=None):
    with write(conn):
        weeks = int(weeks or setting(conn, "weeks"))
        if not 1 <= weeks <= config.MAX_WEEKS:
            raise ValueError(f"Weeks must be between 1 and {config.MAX_WEEKS}.")
        result = menu.solve(_all_dishes(conn), menu.plan_slots(weeks))
        conn.execute("DELETE FROM menu_slots")
        for slot, dish_id in result.items():
            _put(conn, slot, dish_id)
        set_setting(conn, "weeks", weeks)
        set_setting(conn, "start_date", _start_monday().isoformat())


def set_weeks(conn, weeks):
    """Change the number of planned weeks, keeping the meals already planned."""
    weeks = int(weeks)
    if not 1 <= weeks <= config.MAX_WEEKS:
        raise ValueError(f"Weeks must be between 1 and {config.MAX_WEEKS}.")
    with write(conn):
        rows = conn.execute("SELECT week, day, meal, dish_id FROM menu_slots").fetchall()
        current = {(r["week"], r["day"], r["meal"]): r["dish_id"] for r in rows}
        if current:
            kept = {s: d for s, d in current.items() if s[0] <= weeks and d is not None}
            conn.execute("DELETE FROM menu_slots WHERE week > ?", (weeks,))
            to_fill = [s for s in menu.plan_slots(weeks) if s not in kept]
            for slot, dish_id in menu.solve(_all_dishes(conn), to_fill, locked=kept).items():
                _put(conn, slot, dish_id)
        set_setting(conn, "weeks", weeks)


def swap(conn, a, b):
    with write(conn):
        a, b = _check_slot(conn, a), _check_slot(conn, b)
        da, db_ = _slot_dish(conn, a), _slot_dish(conn, b)
        _put(conn, a, db_)
        _put(conn, b, da)


def set_slot(conn, slot, dish_id):
    """Put a dish in a slot (None clears it). If the dish is already planned
    elsewhere, the two slots swap so no dish appears twice."""
    with write(conn):
        slot = _check_slot(conn, slot)
        if dish_id is not None:
            if not conn.execute("SELECT 1 FROM dishes WHERE id = ?", (dish_id,)).fetchone():
                raise NotFound("Dish not found.")
            other = conn.execute(
                "SELECT week, day, meal FROM menu_slots WHERE dish_id = ?", (dish_id,)
            ).fetchone()
            if other and tuple(other) != slot:
                _put(conn, tuple(other), _slot_dish(conn, slot))
        _put(conn, slot, dish_id)


# --- State ----------------------------------------------------------------


def state(conn):
    """Everything the app needs to render, in one payload."""
    conn.execute("BEGIN")  # consistent snapshot
    try:
        weeks = int(setting(conn, "weeks"))
        return {
            "version": version(conn),
            "weeks": weeks,
            "max_weeks": config.MAX_WEEKS,
            "start_date": setting(conn, "start_date") or None,
            "days": config.DAYS,
            "meals": config.MEALS,
            "free_slots": sorted(config.FREE_SLOTS),
            "tag_rules": config.TAG_RULES,
            "slots_needed": len(menu.plan_slots(weeks)),
            "menu": [
                dict(r)
                for r in conn.execute(
                    "SELECT week, day, meal, dish_id FROM menu_slots WHERE week <= ?", (weeks,)
                )
            ],
            "dishes": list_dishes(conn),
            "tags": [r[0] for r in conn.execute("SELECT DISTINCT tag FROM dishes ORDER BY tag")],
            "ingredients": [r[0] for r in conn.execute("SELECT name FROM ingredients ORDER BY name")],
        }
    finally:
        conn.execute("COMMIT")


if __name__ == "__main__":
    usage = "usage: python db.py import FILE.csv | export"
    conn = connect()
    if sys.argv[1:2] == ["import"] and len(sys.argv) == 3:
        print(f"Imported {import_csv(conn, sys.argv[2])} dishes.")
    elif sys.argv[1:] == ["export"]:
        export_csv(conn, sys.stdout)
    else:
        sys.exit(usage)
