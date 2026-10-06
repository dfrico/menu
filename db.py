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


SCHEMA_V1 = """
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

# v2: one category per dish (used by the menu rules) plus free tags; dishes can
# be marked combinable, and a meal can have a second (side) dish.
SCHEMA_V2 = """
ALTER TABLE dishes RENAME COLUMN tag TO category;
ALTER TABLE dishes ADD COLUMN combinable INTEGER NOT NULL DEFAULT 0;
CREATE TABLE dish_tags (
    dish_id INTEGER NOT NULL REFERENCES dishes(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (dish_id, tag)
);
ALTER TABLE menu_slots ADD COLUMN side_dish_id INTEGER REFERENCES dishes(id) ON DELETE SET NULL;
"""

MIGRATIONS = [SCHEMA_V1, SCHEMA_V2]


def connect(path=None):
    conn = sqlite3.connect(path or DB_PATH, isolation_level=None, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def _user_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn):
    if _user_version(conn) == len(MIGRATIONS):
        return
    with write(conn, bump=False):
        current = _user_version(conn)  # re-read: another connection may have migrated
        for version_, schema in enumerate(MIGRATIONS[current:], start=current + 1):
            for stmt in schema.split(";"):
                if stmt.strip():
                    conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {version_}")
        if current == 0:
            conn.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                [("version", "0"), ("weeks", str(config.DEFAULT_WEEKS)), ("start_date", "")],
            )
    if current == 0 and os.path.exists(LEGACY_CSV):
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
        r["id"]: {**dict(r), "combinable": bool(r["combinable"]), "tags": [], "ingredients": []}
        for r in conn.execute(
            "SELECT id, name, category, combinable, notes FROM dishes ORDER BY name"
        )
    }
    for r in conn.execute("SELECT dish_id, tag FROM dish_tags ORDER BY tag"):
        dishes[r["dish_id"]]["tags"].append(r["tag"])
    for r in conn.execute(
        """SELECT di.dish_id, i.name, di.main FROM dish_ingredients di
           JOIN ingredients i ON i.id = di.ingredient_id
           ORDER BY di.main DESC, i.name"""
    ):
        dishes[r["dish_id"]]["ingredients"].append({"name": r["name"], "main": bool(r["main"])})
    return list(dishes.values())


def get_dish(conn, dish_id):
    return next((d for d in list_dishes(conn) if d["id"] == dish_id), None)


def _names(value, sep=","):
    """A list of names, or a single string of names separated by `sep`."""
    if isinstance(value, str):
        value = value.split(sep)
    return list(dict.fromkeys(n for n in (str(v).strip().lower() for v in value or []) if n))


def _clean_dish(data):
    name = str(data.get("name", "")).strip()
    # "tag" is the old name of "category".
    category = str(data.get("category") or data.get("tag") or "").strip().lower()
    if not name:
        raise ValueError("The dish needs a name.")
    if not category:
        raise ValueError("The dish needs a category (e.g. chicken, fish, vegetarian).")
    if "," in category:
        raise ValueError("A dish has a single category; put the rest in tags.")
    ingredients = {}
    for item in data.get("ingredients") or []:
        if isinstance(item, str):
            item = {"name": item}
        ing = str(item.get("name", "")).strip().lower()
        if ing:
            ingredients[ing] = bool(item.get("main", True))
    return {
        "name": name,
        "category": category,
        "tags": _names(data.get("tags")),
        "combinable": bool(data.get("combinable")),
        "notes": str(data.get("notes") or "").strip(),
        "ingredients": ingredients,
    }


def save_dish(conn, data, dish_id=None):
    """Create (dish_id=None) or replace a dish. Returns its id."""
    dish = _clean_dish(data)
    name = dish["name"]
    fields = (name, dish["category"], int(dish["combinable"]), dish["notes"])
    with write(conn):
        clash = conn.execute(
            "SELECT id FROM dishes WHERE name = ? AND id IS NOT ?", (name, dish_id)
        ).fetchone()
        if clash:
            raise ValueError(f"A dish called '{name}' already exists.")
        if dish_id is None:
            dish_id = conn.execute(
                "INSERT INTO dishes (name, category, combinable, notes) VALUES (?, ?, ?, ?)",
                fields,
            ).lastrowid
        else:
            cur = conn.execute(
                "UPDATE dishes SET name = ?, category = ?, combinable = ?, notes = ? WHERE id = ?",
                (*fields, dish_id),
            )
            if cur.rowcount == 0:
                raise NotFound("Dish not found.")
            conn.execute("DELETE FROM dish_ingredients WHERE dish_id = ?", (dish_id,))
            conn.execute("DELETE FROM dish_tags WHERE dish_id = ?", (dish_id,))
        conn.executemany(
            "INSERT INTO dish_tags (dish_id, tag) VALUES (?, ?)",
            [(dish_id, t) for t in dish["tags"]],
        )
        for ing, main in dish["ingredients"].items():
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
    """Import dishes from a CSV with columns `name,category` (or `tag`) and
    optionally `tags`, `ingredients` (both separated by ';') and `combinable`
    (yes/no). Existing dishes (same name) are skipped. Returns the number imported."""
    existing = {r[0].lower() for r in conn.execute("SELECT name FROM dishes")}
    count = 0
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["name"].strip().lower() in existing:
                continue
            save_dish(conn, {
                "name": row["name"],
                "category": row.get("category") or row.get("tag"),
                "tags": _names(row.get("tags"), ";"),
                "ingredients": _names(row.get("ingredients"), ";"),
                "combinable": (row.get("combinable") or "").strip().lower() in ("1", "yes", "true", "y"),
            })
            existing.add(row["name"].strip().lower())
            count += 1
    return count


def export_csv(conn, out):
    writer = csv.writer(out)
    writer.writerow(["name", "category", "tags", "ingredients", "combinable"])
    for d in list_dishes(conn):
        writer.writerow([
            d["name"],
            d["category"],
            ";".join(d["tags"]),
            ";".join(i["name"] for i in d["ingredients"]),
            "yes" if d["combinable"] else "no",
        ])


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


def _slot_meal(conn, slot):
    """(dish_id, side_dish_id) planned in a slot."""
    row = conn.execute(
        "SELECT dish_id, side_dish_id FROM menu_slots WHERE week = ? AND day = ? AND meal = ?",
        slot,
    ).fetchone()
    return tuple(row) if row else (None, None)


def _put(conn, slot, dish_id, side_dish_id=None):
    conn.execute(
        """INSERT OR REPLACE INTO menu_slots (week, day, meal, dish_id, side_dish_id)
           VALUES (?, ?, ?, ?, ?)""",
        (*slot, dish_id, side_dish_id),
    )


def _combinable(conn, dish_id):
    row = conn.execute("SELECT combinable FROM dishes WHERE id = ?", (dish_id,)).fetchone()
    if row is None:
        raise NotFound("Dish not found.")
    return bool(row[0])


def _all_dishes(conn):
    return [(r["id"], r["category"]) for r in conn.execute("SELECT id, category FROM dishes")]


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
    """Swap two whole meals (main and second dish)."""
    with write(conn):
        a, b = _check_slot(conn, a), _check_slot(conn, b)
        meal_a, meal_b = _slot_meal(conn, a), _slot_meal(conn, b)
        _put(conn, a, *meal_b)
        _put(conn, b, *meal_a)


def set_slot(conn, slot, dish_id):
    """Put a dish in a slot (None clears the meal). If the dish is already
    planned elsewhere, the two meals swap so no dish appears twice."""
    with write(conn):
        slot = _check_slot(conn, slot)
        main, side = _slot_meal(conn, slot)
        if dish_id is None:
            _put(conn, slot, None, None)
            return
        combinable = _combinable(conn, dish_id)
        other = conn.execute(
            "SELECT week, day, meal FROM menu_slots WHERE dish_id = ?", (dish_id,)
        ).fetchone()
        if other and tuple(other) != slot:
            # The dish moves here with its second dish; this meal moves there.
            _, other_side = _slot_meal(conn, tuple(other))
            _put(conn, tuple(other), main, side)
            _put(conn, slot, dish_id, other_side)
        else:
            keep_side = combinable and side != dish_id
            _put(conn, slot, dish_id, side if keep_side else None)


def set_side(conn, slot, dish_id):
    """Set the second dish of a meal (None removes it). Both dishes must be
    marked as combinable."""
    with write(conn):
        slot = _check_slot(conn, slot)
        main, _ = _slot_meal(conn, slot)
        if dish_id is not None:
            if main is None:
                raise ValueError("Pick the main dish first.")
            if dish_id == main:
                raise ValueError("Pick a different dish.")
            if not (_combinable(conn, main) and _combinable(conn, dish_id)):
                raise ValueError("Only dishes marked as combinable can share a meal.")
        _put(conn, slot, main, dish_id)


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
            "category_rules": config.CATEGORY_RULES,
            "slots_needed": len(menu.plan_slots(weeks)),
            "menu": [
                dict(r)
                for r in conn.execute(
                    "SELECT week, day, meal, dish_id, side_dish_id FROM menu_slots WHERE week <= ?",
                    (weeks,),
                )
            ],
            "dishes": list_dishes(conn),
            "categories": [
                r[0] for r in conn.execute("SELECT DISTINCT category FROM dishes ORDER BY category")
            ],
            "tags": [r[0] for r in conn.execute("SELECT DISTINCT tag FROM dish_tags ORDER BY tag")],
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
