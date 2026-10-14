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

# v3: a dish's role replaces the combinable flag ('main': a full meal,
# 'combinable': alone or paired, 'side': only as a second dish, no category
# needed); dishes can be seasonal and last more than one meal.
SCHEMA_V3 = """
ALTER TABLE dishes ADD COLUMN role TEXT NOT NULL DEFAULT 'main';
UPDATE dishes SET role = 'combinable' WHERE combinable = 1;
ALTER TABLE dishes DROP COLUMN combinable;
ALTER TABLE dishes ADD COLUMN season TEXT NOT NULL DEFAULT 'all';
ALTER TABLE dishes ADD COLUMN portions INTEGER NOT NULL DEFAULT 1;
"""

# v4: dishes can be lunch-only or dinner-only.
SCHEMA_V4 = """
ALTER TABLE dishes ADD COLUMN meal_time TEXT NOT NULL DEFAULT 'any';
"""

# v5: every dish is either lunch or dinner. Dishes that were "any" become
# unset ('') until someone picks; until then they can go in either meal.
SCHEMA_V5 = """
UPDATE dishes SET meal_time = '' WHERE meal_time = 'any';
"""

# v6: ingredients ticked off in the Ingredients tab (bought).
SCHEMA_V6 = """
CREATE TABLE shopping_checked (
    ingredient TEXT PRIMARY KEY COLLATE NOCASE
);
"""

MIGRATIONS = [SCHEMA_V1, SCHEMA_V2, SCHEMA_V3, SCHEMA_V4, SCHEMA_V5, SCHEMA_V6]

ROLES = ("main", "combinable", "side")
SEASONS = ("all", "summer", "winter")
MEAL_TIMES = ("lunch", "dinner")


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
        r["id"]: {**dict(r), "tags": [], "ingredients": []}
        for r in conn.execute(
            """SELECT id, name, category, role, season, meal_time, portions, notes
               FROM dishes ORDER BY name"""
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


def _clean_dish(data, allow_unset_meal_time=False):
    name = str(data.get("name", "")).strip()
    # "tag" is the old name of "category"; "combinable" the old form of "role".
    category = str(data.get("category") or data.get("tag") or "").strip().lower()
    role = data.get("role") or ("combinable" if data.get("combinable") else "main")
    season = data.get("season") or "all"
    meal_time = str(data.get("meal_time") or "").strip().lower()
    try:
        portions = int(data.get("portions") or 1)
    except (TypeError, ValueError):
        raise ValueError("A dish lasts 1 or 2 meals.")
    if not name:
        raise ValueError("The dish needs a name.")
    if role not in ROLES:
        raise ValueError(f"Role must be one of: {', '.join(ROLES)}.")
    if season not in SEASONS:
        raise ValueError(f"Season must be one of: {', '.join(SEASONS)}.")
    if meal_time not in MEAL_TIMES and not (allow_unset_meal_time and not meal_time):
        raise ValueError("Choose whether the dish is for lunch or dinner.")
    if portions not in (1, 2):
        raise ValueError("A dish lasts 1 or 2 meals.")
    if role == "side":
        category = ""  # sides are never planned on their own
    elif not category:
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
        "role": role,
        "season": season,
        "meal_time": meal_time,
        "portions": portions,
        "notes": str(data.get("notes") or "").strip(),
        "ingredients": ingredients,
    }


def save_dish(conn, data, dish_id=None, allow_unset_meal_time=False):
    """Create (dish_id=None) or replace a dish. Returns its id."""
    dish = _clean_dish(data, allow_unset_meal_time)
    name = dish["name"]
    fields = (
        name, dish["category"], dish["role"], dish["season"], dish["meal_time"],
        dish["portions"], dish["notes"],
    )
    with write(conn):
        clash = conn.execute(
            "SELECT id FROM dishes WHERE name = ? AND id IS NOT ?", (name, dish_id)
        ).fetchone()
        if clash:
            raise ValueError(f"A dish called '{name}' already exists.")
        if dish_id is None:
            dish_id = conn.execute(
                """INSERT INTO dishes (name, category, role, season, meal_time, portions, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                fields,
            ).lastrowid
        else:
            cur = conn.execute(
                """UPDATE dishes SET name = ?, category = ?, role = ?, season = ?, meal_time = ?,
                   portions = ?, notes = ? WHERE id = ?""",
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
    optionally `tags`, `ingredients` (both separated by ';'), `role`
    (main/combinable/side), `season` (all/summer/winter), `meal_time`
    (lunch/dinner; left unset if missing) and `portions` (1/2).
    Existing dishes (same name) are skipped. Returns the number imported."""
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
                "role": (row.get("role") or "").strip().lower() or None,
                "combinable": (row.get("combinable") or "").strip().lower() in ("1", "yes", "true", "y"),
                "season": (row.get("season") or "").strip().lower() or None,
                "meal_time": (row.get("meal_time") or "").strip().lower() or None,
                "portions": int(row.get("portions") or 1),
            }, allow_unset_meal_time=True)
            existing.add(row["name"].strip().lower())
            count += 1
    return count


def export_csv(conn, out):
    writer = csv.writer(out)
    writer.writerow(
        ["name", "category", "tags", "ingredients", "role", "season", "meal_time", "portions"]
    )
    for d in list_dishes(conn):
        writer.writerow([
            d["name"],
            d["category"],
            ";".join(d["tags"]),
            ";".join(i["name"] for i in d["ingredients"]),
            d["role"],
            d["season"],
            d["meal_time"],
            d["portions"],
        ])


# --- Menu -----------------------------------------------------------------


def _check_slot(conn, slot):
    try:
        week, day, meal = int(slot["week"]), slot["day"], slot["meal"]
    except (KeyError, TypeError, ValueError):
        raise ValueError("A slot needs week, day and meal.")
    if not (1 <= week <= int(setting(conn, "weeks"))) or day not in config.DAYS or meal not in config.MEALS:
        raise ValueError(f"Invalid slot: week {week} {day} {meal}.")
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


def _add_empty_slots(conn, weeks):
    """Rows for meals the generator leaves empty, so they can be planned by hand."""
    conn.executemany(
        "INSERT OR IGNORE INTO menu_slots (week, day, meal) VALUES (?, ?, ?)",
        menu.all_slots(weeks),
    )


def _role(conn, dish_id):
    row = conn.execute("SELECT role FROM dishes WHERE id = ?", (dish_id,)).fetchone()
    if row is None:
        raise NotFound("Dish not found.")
    return row[0]


def plannable_dishes(conn):
    """Dishes the solver may plan on their own (everything but sides)."""
    return [
        menu.Dish(r["id"], r["category"], r["portions"])
        for r in conn.execute("SELECT id, category, portions FROM dishes WHERE role != 'side'")
    ]


def season_on(day):
    if day.month in config.SUMMER_MONTHS:
        return "summer"
    if day.month in config.WINTER_MONTHS:
        return "winter"
    return None  # in between: anything goes


def _allowed(conn, start):
    """allowed(slot, dish_id) for the solver: seasonal dishes only in their
    season, lunch-only / dinner-only dishes only at that meal."""
    dishes = {r["id"]: r for r in conn.execute("SELECT id, season, meal_time FROM dishes")}

    def allowed(slot, dish_id):
        dish = dishes[dish_id]
        now = season_on(start + timedelta(days=menu.day_number(slot)))
        in_season = dish["season"] == "all" or now is None or dish["season"] == now
        # Unset (legacy) dishes may go in either meal until someone picks.
        right_meal = not dish["meal_time"] or dish["meal_time"] == slot[2].lower()
        return in_season and right_meal

    return allowed


def _start_monday(today=None):
    """Monday of this week, or of next week if it's already the weekend."""
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    return monday + timedelta(weeks=1) if today.weekday() >= 5 else monday


def generate(conn, weeks=None):
    with write(conn):
        try:
            weeks = int(weeks or setting(conn, "weeks"))
        except (TypeError, ValueError):
            raise ValueError(f"Weeks must be between 1 and {config.MAX_WEEKS}.")
        if not 1 <= weeks <= config.MAX_WEEKS:
            raise ValueError(f"Weeks must be between 1 and {config.MAX_WEEKS}.")
        start = _start_monday()
        result = menu.solve(
            plannable_dishes(conn), menu.plan_slots(weeks), allowed=_allowed(conn, start)
        )
        conn.execute("DELETE FROM menu_slots")
        conn.execute("DELETE FROM shopping_checked")  # new menu, new shopping
        for slot, dish_id in result.items():
            _put(conn, slot, dish_id)
        _add_empty_slots(conn, weeks)
        set_setting(conn, "weeks", weeks)
        set_setting(conn, "start_date", start.isoformat())


def set_weeks(conn, weeks):
    """Change the number of planned weeks, keeping the meals already planned."""
    try:
        weeks = int(weeks)
    except (TypeError, ValueError):
        raise ValueError(f"Weeks must be between 1 and {config.MAX_WEEKS}.")
    if not 1 <= weeks <= config.MAX_WEEKS:
        raise ValueError(f"Weeks must be between 1 and {config.MAX_WEEKS}.")
    with write(conn):
        rows = conn.execute("SELECT week, day, meal, dish_id FROM menu_slots").fetchall()
        current = {(r["week"], r["day"], r["meal"]): r["dish_id"] for r in rows}
        if current:
            kept = {s: d for s, d in current.items() if s[0] <= weeks and d is not None}
            conn.execute("DELETE FROM menu_slots WHERE week > ?", (weeks,))
            to_fill = [s for s in menu.plan_slots(weeks) if s not in kept]
            start = date.fromisoformat(setting(conn, "start_date") or _start_monday().isoformat())
            try:
                result = menu.solve(
                    plannable_dishes(conn), to_fill, locked=kept, allowed=_allowed(conn, start)
                )
            except menu.MenuError as e:
                raise menu.MenuError(
                    f"{e} Week 1 stays as it is when adding week 2; tap “New menu” to plan "
                    "both weeks from scratch."
                )
            for slot, dish_id in result.items():
                _put(conn, slot, dish_id)
            _add_empty_slots(conn, weeks)
        set_setting(conn, "weeks", weeks)


def swap(conn, a, b):
    """Swap two whole meals (main and second dish)."""
    with write(conn):
        a, b = _check_slot(conn, a), _check_slot(conn, b)
        meal_a, meal_b = _slot_meal(conn, a), _slot_meal(conn, b)
        _put(conn, a, *meal_b)
        _put(conn, b, *meal_a)


def set_slot(conn, slot, dish_id):
    """Put a dish in a slot (None clears the meal). The same dish may be
    planned more than once (leftovers). The second dish is kept if the new
    dish can be paired."""
    with write(conn):
        slot = _check_slot(conn, slot)
        _, side = _slot_meal(conn, slot)
        if dish_id is None:
            _put(conn, slot, None, None)
            return
        keep_side = _role(conn, dish_id) != "main" and side != dish_id
        _put(conn, slot, dish_id, side if keep_side else None)


def set_side(conn, slot, dish_id):
    """Set the second dish of a meal (None removes it). Neither dish can be a
    full meal (role 'main')."""
    with write(conn):
        slot = _check_slot(conn, slot)
        main, _ = _slot_meal(conn, slot)
        if dish_id is not None:
            if main is None:
                raise ValueError("Pick the main dish first.")
            if dish_id == main:
                raise ValueError("Pick a different dish.")
            if "main" in (_role(conn, main), _role(conn, dish_id)):
                raise ValueError("Full meals can't be combined with another dish.")
        _put(conn, slot, main, dish_id)


# --- Shopping ---------------------------------------------------------------


def set_checked(conn, ingredient, checked):
    """Tick an ingredient off (bought) or untick it."""
    ingredient = str(ingredient or "").strip().lower()
    if not ingredient:
        raise ValueError("Which ingredient?")
    with write(conn):
        if checked:
            conn.execute("INSERT OR IGNORE INTO shopping_checked VALUES (?)", (ingredient,))
        else:
            conn.execute("DELETE FROM shopping_checked WHERE ingredient = ?", (ingredient,))


def clear_checked(conn):
    with write(conn):
        conn.execute("DELETE FROM shopping_checked")


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
            "category_rules": config.CATEGORY_RULES,
            "summer_months": sorted(config.SUMMER_MONTHS),
            "winter_months": sorted(config.WINTER_MONTHS),
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
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT category FROM dishes WHERE category != '' ORDER BY category"
                )
            ],
            "tags": [r[0] for r in conn.execute("SELECT DISTINCT tag FROM dish_tags ORDER BY tag")],
            "ingredients": [r[0] for r in conn.execute("SELECT name FROM ingredients ORDER BY name")],
            "checked": [r[0] for r in conn.execute("SELECT ingredient FROM shopping_checked")],
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
