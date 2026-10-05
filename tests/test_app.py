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
            r = client.post("/api/dishes", json={"name": f"{tag} {i}", "tag": tag})
            assert r.status_code == 201


def slot_tags(state):
    tag_of = {d["id"]: d["tag"] for d in state["dishes"]}
    return {(s["week"], s["day"], s["meal"]): tag_of.get(s["dish_id"]) for s in state["menu"]}


def check_rules(state):
    tags = slot_tags(state)
    ids = [s["dish_id"] for s in state["menu"]]
    assert len(ids) == len(set(ids)), "a dish is used twice"
    assert len(ids) == len(menu.plan_slots(state["weeks"]))
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

    # Setting a dish that's already planned elsewhere swaps the two.
    moved = after[(1, "Friday", "Dinner")]
    state = client.put("/api/menu/slot", json={**a, "dish_id": moved}).json
    final = {(s["week"], s["day"], s["meal"]): s["dish_id"] for s in state["menu"]}
    assert final[(1, "Monday", "Lunch")] == moved
    assert final[(1, "Friday", "Dinner")] == after[(1, "Monday", "Lunch")]

    free = {"week": 1, "day": "Saturday", "meal": "Lunch"}
    assert client.post("/api/menu/swap", json={"a": a, "b": free}).status_code == 400


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
            "tag": " Beef ",
            "ingredients": ["Minced meat", {"name": "pasta"}, {"name": "olive oil", "main": False}],
        },
    )
    dish = r.json
    assert dish["tag"] == "beef"
    assert {"name": "olive oil", "main": False} in dish["ingredients"]
    assert client.post("/api/dishes", json={"name": "bolognese", "tag": "beef"}).status_code == 400

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
