import pytest

import app as app_module
import config
import db
import menu

TAGS = {"chicken": 8, "fish": 6, "vegetarian": 8, "beef": 4, "egg": 4}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "LEGACY_CSV", str(tmp_path / "missing.csv"))
    return app_module.app.test_client()


def seed(client, tags=TAGS):
    for tag, n in tags.items():
        for i in range(n):
            r = client.post("/api/dishes", json={"name": f"{tag} {i}", "category": tag})
            assert r.status_code == 201


def slot_tags(state):
    tag_of = {d["id"]: d["category"] for d in state["dishes"]}
    return {(s["week"], s["day"], s["meal"]): tag_of.get(s["dish_id"]) for s in state["menu"]}


def check_rules(state):
    tags = slot_tags(state)
    ids = [s["dish_id"] for s in state["menu"] if s["dish_id"] is not None]
    assert len(ids) == len(set(ids)), "a dish is used twice"
    assert len(ids) == len(menu.plan_slots(state["weeks"]))
    assert len(state["menu"]) == len(menu.all_slots(state["weeks"]))
    assert all(s["dish_id"] is None for s in state["menu"] if (s["day"], s["meal"]) == ("Saturday", "Lunch"))
    for (w, day, meal), tag in tags.items():
        if (day, meal) == ("Saturday", "Dinner"):
            assert tag == "egg"
        if meal == "Lunch" and (w, day, "Dinner") in tags:
            assert tags[(w, day, "Dinner")] != tag, f"same tag on week {w} {day}"


@pytest.mark.parametrize("weeks", [1, 2])
def test_generate_respects_rules(client, weeks):
    seed(client)
    for _ in range(5):
        r = client.post("/api/menu/generate", json={"weeks": weeks})
        assert r.status_code == 200, r.json
        check_rules(r.json)


def test_more_dishes_than_slots(client):
    seed(client, {**TAGS, "pasta": 20})
    r = client.post("/api/menu/generate", json={"weeks": 2})
    assert r.status_code == 200
    check_rules(r.json)


def test_helpful_errors(client):
    seed(client, {"chicken": 3, "fish": 3})
    r = client.post("/api/menu/generate", json={"weeks": 1})
    assert r.status_code == 400 and "Not enough dishes" in r.json["error"]

    seed(client, {"vegetarian": 10})
    r = client.post("/api/menu/generate", json={"weeks": 1})
    assert r.status_code == 400 and "'egg'" in r.json["error"]


def test_menu_persists(client):
    seed(client)
    menu_before = client.post("/api/menu/generate").json["menu"]
    # A fresh connection (as after a restart) sees the same menu.
    assert db.state(db.connect())["menu"] == menu_before


def test_swap_and_set_slot(client):
    seed(client)
    state = client.post("/api/menu/generate").json
    by_slot = {(s["week"], s["day"], s["meal"]): s["dish_id"] for s in state["menu"]}
    a = {"week": 1, "day": "Monday", "meal": "Lunch"}
    b = {"week": 1, "day": "Tuesday", "meal": "Dinner"}
    state = client.post("/api/menu/swap", json={"a": a, "b": b}).json
    after = {(s["week"], s["day"], s["meal"]): s["dish_id"] for s in state["menu"]}
    assert after[(1, "Monday", "Lunch")] == by_slot[(1, "Tuesday", "Dinner")]
    assert after[(1, "Tuesday", "Dinner")] == by_slot[(1, "Monday", "Lunch")]

    # Picking a dish that's already planned elsewhere plans it twice (leftovers).
    repeated = after[(1, "Friday", "Dinner")]
    state = client.put("/api/menu/slot", json={**a, "dish_id": repeated}).json
    final = {(s["week"], s["day"], s["meal"]): s["dish_id"] for s in state["menu"]}
    assert final[(1, "Monday", "Lunch")] == repeated
    assert final[(1, "Friday", "Dinner")] == repeated

    # Saturday lunch is left empty but can be planned by hand.
    saturday = {"week": 1, "day": "Saturday", "meal": "Lunch"}
    state = client.post("/api/menu/swap", json={"a": a, "b": saturday}).json
    final = {(s["week"], s["day"], s["meal"]): s["dish_id"] for s in state["menu"]}
    assert final[(1, "Saturday", "Lunch")] == repeated and final[(1, "Monday", "Lunch")] is None


def test_switch_weeks_keeps_week_one(client):
    seed(client)
    week1 = client.post("/api/menu/generate", json={"weeks": 1}).json["menu"]
    state = client.put("/api/settings", json={"weeks": 2}).json
    assert state["weeks"] == 2
    check_rules(state)
    assert [s for s in state["menu"] if s["week"] == 1] == week1
    state = client.put("/api/settings", json={"weeks": 1}).json
    assert state["menu"] == week1


def test_dish_crud_and_ingredients(client):
    r = client.post(
        "/api/dishes",
        json={
            "name": "Bolognese",
            "category": " Beef ",
            "tags": "Italian, quick",
            "ingredients": ["Minced meat", {"name": "pasta"}, {"name": "olive oil", "main": False}],
        },
    )
    dish = r.json
    assert dish["category"] == "beef"
    assert dish["tags"] == ["italian", "quick"]
    assert (dish["role"], dish["season"], dish["portions"]) == ("main", "all", 1)
    assert {"name": "olive oil", "main": False} in dish["ingredients"]
    assert client.post("/api/dishes", json={"name": "bolognese", "category": "beef"}).status_code == 400
    r = client.post("/api/dishes", json={"name": "x", "category": "japanese, beef"})
    assert r.status_code == 400 and "single category" in r.json["error"]

    r = client.put(f"/api/dishes/{dish['id']}", json={**dish, "ingredients": ["pasta"]})
    assert r.json["ingredients"] == [{"name": "pasta", "main": True}]
    assert "minced meat" in client.get("/api/ingredients").json

    assert client.delete(f"/api/dishes/{dish['id']}").status_code == 204
    assert client.get(f"/api/dishes/{dish['id']}").status_code == 404


def test_deleting_planned_dish_empties_slot(client):
    seed(client)
    state = client.post("/api/menu/generate").json
    dish_id = state["menu"][0]["dish_id"]
    client.delete(f"/api/dishes/{dish_id}")
    state = client.get("/api/state").json
    assert state["menu"][0]["dish_id"] is None


def test_version_bumps_on_write(client):
    v = client.get("/api/state").json["version"]
    seed(client, {"fish": 1})
    assert client.get("/api/state").json["version"] == v + 1


def test_csv_import(client, tmp_path):
    csv_path = tmp_path / "dishes.csv"
    csv_path.write_text("name,tag\nburger,beef\nfalafel wrap,vegetarian\n")
    conn = db.connect()
    assert db.import_csv(conn, str(csv_path)) == 2
    assert db.import_csv(conn, str(csv_path)) == 0

    new_format = tmp_path / "new.csv"
    new_format.write_text(
        "name,category,tags,ingredients,combinable\n"
        "pumpkin soup,vegetarian,soup;autumn,pumpkin;onion,yes\n"
    )
    assert db.import_csv(conn, str(new_format)) == 1
    soup = next(d for d in db.list_dishes(conn) if d["name"] == "pumpkin soup")
    assert soup["tags"] == ["autumn", "soup"] and soup["role"] == "combinable"


def test_migrates_v1_database(tmp_path, monkeypatch):
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(db.SCHEMA_V1)
    old.execute("INSERT INTO settings VALUES ('version', '7'), ('weeks', '1'), ('start_date', '')")
    old.execute("INSERT INTO dishes (name, tag) VALUES ('guiso', 'beef')")
    old.execute("INSERT INTO menu_slots VALUES (1, 'Monday', 'Lunch', 1)")
    old.execute("PRAGMA user_version = 1")
    old.commit()
    old.close()

    conn = db.connect(str(path))
    state = db.state(conn)
    assert state["version"] == 7
    assert state["dishes"][0]["category"] == "beef" and state["dishes"][0]["tags"] == []
    assert state["menu"] == [
        {"week": 1, "day": "Monday", "meal": "Lunch", "dish_id": 1, "side_dish_id": None}
    ]


def test_second_dish(client):
    soup = client.post("/api/dishes", json={"name": "pumpkin soup", "category": "vegetarian", "role": "combinable"}).json
    fish = client.post("/api/dishes", json={"name": "grilled fish", "category": "fish", "combinable": True}).json
    pizza = client.post("/api/dishes", json={"name": "pizza", "category": "vegetarian"}).json
    toast = client.post("/api/dishes", json={"name": "toast", "category": "ignored", "role": "side"}).json
    assert fish["role"] == "combinable" and toast["category"] == ""
    seed(client)
    client.post("/api/menu/generate")
    mon = {"week": 1, "day": "Monday", "meal": "Lunch"}
    tue = {"week": 1, "day": "Tuesday", "meal": "Dinner"}
    meal = lambda st, s: next((m["dish_id"], m["side_dish_id"]) for m in st["menu"]
                              if (m["day"], m["meal"]) == (s["day"], s["meal"]))

    client.put("/api/menu/slot", json={**mon, "dish_id": soup["id"]})
    st = client.put("/api/menu/side", json={**mon, "dish_id": fish["id"]}).json
    assert meal(st, mon) == (soup["id"], fish["id"])

    # Pairing needs two different dishes, neither a full meal.
    assert client.put("/api/menu/side", json={**mon, "dish_id": pizza["id"]}).status_code == 400
    assert client.put("/api/menu/side", json={**mon, "dish_id": soup["id"]}).status_code == 400

    # Swapping moves the whole meal.
    before_tue = meal(st, tue)
    st = client.post("/api/menu/swap", json={"a": mon, "b": tue}).json
    assert meal(st, tue) == (soup["id"], fish["id"]) and meal(st, mon) == before_tue

    # A side-only dish can be the second dish.
    st = client.put("/api/menu/side", json={**tue, "dish_id": toast["id"]}).json
    assert meal(st, tue) == (soup["id"], toast["id"])

    # Replacing the main keeps the second dish if the new one can be paired...
    st = client.put("/api/menu/slot", json={**tue, "dish_id": fish["id"]}).json
    assert meal(st, tue) == (fish["id"], toast["id"])
    mon = tue

    # ...and drops it if the new dish is a full meal.
    st = client.put("/api/menu/slot", json={**mon, "dish_id": pizza["id"]}).json
    assert meal(st, mon) == (pizza["id"], None)

    # Generating a new menu starts without second dishes.
    st = client.post("/api/menu/generate").json
    assert all(m["side_dish_id"] is None for m in st["menu"])


def test_side_dishes_are_never_planned_alone(client):
    seed(client)
    for i in range(10):
        client.post("/api/dishes", json={"name": f"toast {i}", "role": "side"})
    sides = {d["id"] for d in client.get("/api/dishes").json if d["role"] == "side"}
    for _ in range(3):
        st = client.post("/api/menu/generate", json={"weeks": 2}).json
        assert not sides & {m["dish_id"] for m in st["menu"]}
    assert "" not in st["categories"]


def test_leftovers(client):
    seed(client, {"chicken": 4, "fish": 3, "vegetarian": 2, "beef": 2, "egg": 1})
    soups = [
        client.post("/api/dishes", json={"name": f"soup {i}", "category": "soup", "portions": "2"}).json
        for i in range(2)
    ]
    for _ in range(5):
        st = client.post("/api/menu/generate", json={"weeks": 1}).json
        check_rules_with_leftovers(st)
        days = {s["id"]: sorted(menu.day_number((m["week"], m["day"], m["meal"]))
                                for m in st["menu"] if m["dish_id"] == s["id"]) for s in soups}
        for planned in days.values():
            assert len(planned) in (0, 2)
            if planned:
                assert 1 <= planned[1] - planned[0] <= config.LEFTOVERS_MAX_GAP_DAYS


def check_rules_with_leftovers(state):
    portions = {d["id"]: d["portions"] for d in state["dishes"]}
    ids = [m["dish_id"] for m in state["menu"] if m["dish_id"] is not None]
    for dish_id in set(ids):
        assert ids.count(dish_id) == portions[dish_id]


def test_seasons(client, monkeypatch):
    from datetime import date

    seed(client)
    gazpacho = client.post("/api/dishes", json={"name": "gazpacho", "category": "vegetarian", "season": "summer"}).json
    soup = client.post("/api/dishes", json={"name": "soup", "category": "vegetarian", "season": "winter"}).json
    assert db.season_on(date(2026, 7, 1)) == "summer" and db.season_on(date(2026, 10, 1)) is None

    for start, banned in [(date(2026, 7, 6), soup), (date(2027, 1, 4), gazpacho)]:
        monkeypatch.setattr(db, "_start_monday", lambda today=None, start=start: start)
        for _ in range(5):
            st = client.post("/api/menu/generate", json={"weeks": 2}).json
            assert banned["id"] not in {m["dish_id"] for m in st["menu"]}


def test_migrates_v2_combinable_to_role(tmp_path):
    import sqlite3

    path = tmp_path / "v2.db"
    old = sqlite3.connect(path)
    for schema in db.MIGRATIONS[:2]:
        old.executescript(schema)
    old.execute("INSERT INTO settings VALUES ('version', '1'), ('weeks', '1'), ('start_date', '')")
    old.execute("INSERT INTO dishes (name, category, combinable) VALUES ('soup', 'veg', 1), ('pizza', 'comfort', 0)")
    old.execute("PRAGMA user_version = 2")
    old.commit()
    old.close()

    roles = {d["name"]: (d["role"], d["season"], d["portions"]) for d in db.list_dishes(db.connect(str(path)))}
    assert roles == {"soup": ("combinable", "all", 1), "pizza": ("main", "all", 1)}
