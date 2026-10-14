"""Web server: JSON API under /api and the PWA under /."""
import os
import time

from flask import Flask, Response, g, jsonify, request, send_from_directory

import db
from menu import MenuError

app = Flask(__name__, static_folder="static", static_url_path="")
app.json.sort_keys = False


def conn():
    if "conn" not in g:
        g.conn = db.connect()
    return g.conn


@app.teardown_appcontext
def close_conn(_exc):
    if (c := g.pop("conn", None)) is not None:
        c.close()


@app.errorhandler(ValueError)
@app.errorhandler(MenuError)
def bad_request(e):
    return jsonify(error=str(e)), 400


@app.errorhandler(db.NotFound)
def not_found(e):
    return jsonify(error=str(e)), 404


def body():
    return request.get_json(silent=True) or {}


def ok():
    return jsonify(db.state(conn()))


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/sw.js")
def service_worker():
    # Served with no-cache so app updates are picked up.
    resp = send_from_directory(app.static_folder, "sw.js")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# --- State & live updates ---------------------------------------------------


@app.get("/api/state")
def get_state():
    return ok()


@app.get("/api/events")
def events():
    """Server-sent events: emits the version number whenever data changes."""

    def stream():
        c = db.connect()
        try:
            last, idle = None, 0.0
            while True:
                v = db.version(c)
                if v != last:
                    last, idle = v, 0.0
                    yield f"data: {v}\n\n"
                elif idle >= 15:
                    idle = 0.0
                    yield ": ping\n\n"  # keeps proxies happy, detects closed clients
                time.sleep(1)
                idle += 1
        finally:
            c.close()

    return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})


# --- Menu ---------------------------------------------------------------------


@app.post("/api/menu/generate")
def generate():
    db.generate(conn(), body().get("weeks"))
    return ok()


@app.post("/api/menu/swap")
def swap():
    b = body()
    db.swap(conn(), b.get("a"), b.get("b"))
    return ok()


@app.put("/api/menu/slot")
def set_slot():
    b = body()
    db.set_slot(conn(), b, b.get("dish_id"))
    return ok()


@app.put("/api/menu/side")
def set_side():
    b = body()
    db.set_side(conn(), b, b.get("dish_id"))
    return ok()


@app.put("/api/settings")
def settings():
    if "weeks" in (b := body()):
        db.set_weeks(conn(), b["weeks"])
    return ok()


# --- Shopping -----------------------------------------------------------------


@app.put("/api/shopping")
def set_checked():
    b = body()
    db.set_checked(conn(), b.get("ingredient"), bool(b.get("checked")))
    return ok()


@app.delete("/api/shopping")
def clear_checked():
    db.clear_checked(conn())
    return ok()


# --- Dishes -------------------------------------------------------------------


@app.get("/api/dishes")
def list_dishes():
    return jsonify(db.list_dishes(conn()))


@app.post("/api/dishes")
def create_dish():
    dish_id = db.save_dish(conn(), body())
    return jsonify(db.get_dish(conn(), dish_id)), 201


@app.get("/api/dishes/<int:dish_id>")
def get_dish(dish_id):
    if (dish := db.get_dish(conn(), dish_id)) is None:
        raise db.NotFound("Dish not found.")
    return jsonify(dish)


@app.put("/api/dishes/<int:dish_id>")
def update_dish(dish_id):
    db.save_dish(conn(), body(), dish_id)
    return jsonify(db.get_dish(conn(), dish_id))


@app.delete("/api/dishes/<int:dish_id>")
def delete_dish(dish_id):
    db.delete_dish(conn(), dish_id)
    return "", 204


@app.get("/api/ingredients")
def list_ingredients():
    return jsonify(db.state(conn())["ingredients"])


@app.get("/api/categories")
def list_categories():
    return jsonify(db.state(conn())["categories"])


@app.get("/api/tags")
def list_tags():
    return jsonify(db.state(conn())["tags"])


if __name__ == "__main__":
    # Development server. On the Pi, use gunicorn (see README).
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)), threaded=True)
