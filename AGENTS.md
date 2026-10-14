# Notes for agents

## Adding a dish from a recipe

The app runs on the home network; the examples use
`MENU_URL=http://dfr-pi.local`. When asked to add a recipe (e.g. from a URL):

1. Read the recipe and fetch what already exists, so you reuse names instead of creating near-duplicates:
   ```sh
   curl -s $MENU_URL/api/categories   # e.g. ["beef","chicken","egg","fish","vegetarian"]
   curl -s $MENU_URL/api/tags         # e.g. ["japanese","quick","soup"]
   curl -s $MENU_URL/api/ingredients  # e.g. ["minced meat","pasta","tomato",...]
   ```
2. Build the dish:
   - `name`: short dish name, in the language the existing dishes use.
   - `role`: `"main"` for a full meal eaten on its own (pizza, lentils), `"combinable"`
     for dishes eaten alone or with another (soups, omelettes), `"side"` for things that
     are only ever a second dish (toast).
   - `category`: exactly one, the main component (beef, chicken, fish, egg, vegetarian…).
     The menu rules use it. Reuse an existing category whenever one fits. Not needed for sides.
   - `tags`: optional descriptive labels (cuisine, "soup", "quick"…). Reuse existing ones.
   - `season`: `"all"`, `"summer"` (salads, cold soups) or `"winter"` (hot soups, stews).
   - `meal_time`: required, `"lunch"` or `"dinner"`.
   - `portions`: `2` if one batch is eaten twice (soups, stews), otherwise `1`.
   - `ingredients`: generic, lowercase names of what you'd need to have at home:
     `"200 g carne picada de ternera"` becomes `"minced meat"`. Drop quantities and
     brands. Reuse an existing ingredient name if it means the same thing.
     Mark staples (oil, salt, pepper, garlic, flour, common spices) with `"main": false`.
     For an ingredient that's new to the app, add its `food_group` (used by the Nutrition
     tab): `red_meat`, `chicken`, `processed_meat` (ham, bacon, chorizo…), `oily_fish`,
     `white_fish`, `seafood`, `legumes`, `vegetables` or `other` (not tracked: pasta, cheese,
     potato, egg, oil…). Check `GET /api/food-group?ingredient=<name>` first: common foods
     are classified automatically.
   - `notes`: the recipe URL.
3. Create it:
   ```sh
   curl -s -X POST $MENU_URL/api/dishes -H 'Content-Type: application/json' -d '{
     "name": "Spaghetti bolognese",
     "category": "beef",
     "tags": ["italian"],
     "role": "main",
     "season": "all",
     "meal_time": "dinner",
     "portions": 2,
     "ingredients": [
       {"name": "minced meat", "food_group": "red_meat"}, {"name": "pasta"}, {"name": "tomato"},
       {"name": "olive oil", "main": false}
     ],
     "notes": "https://example.com/bolognese"
   }'
   ```
   A 400 response with `"A dish called ... already exists"` means it's already there;
   use `PUT /api/dishes/<id>` to update it instead (the body replaces the whole dish).

## API

| Method | Path | Body | Notes |
|---|---|---|---|
| GET | `/api/state` | | Everything the app renders: menu, dishes, settings, `version` |
| GET | `/api/events` | | Server-sent events; emits `version` on every change |
| GET | `/api/dishes` | | |
| POST | `/api/dishes` | `{name, category, role?, season?, meal_time?, portions?, tags?, ingredients?, notes?}` | `ingredients`: strings or `{name, main}` |
| GET/PUT/DELETE | `/api/dishes/<id>` | same as POST | |
| GET | `/api/categories`, `/api/tags`, `/api/ingredients` | | Lists of names |
| POST | `/api/menu/generate` | `{weeks?}` | Replaces the menu |
| POST | `/api/menu/swap` | `{a: slot, b: slot}` | slot = `{week, day, meal}` |
| PUT | `/api/menu/slot` | `{week, day, meal, dish_id}` | `dish_id: null` clears. The same dish may be planned twice (leftovers) |
| PUT | `/api/menu/side` | `{week, day, meal, dish_id}` | Second dish of a meal; neither can have role `main`. `null` removes |
| PUT | `/api/settings` | `{weeks}` | 1 or 2; keeps week 1 when adding week 2 |
| PUT | `/api/shopping` | `{ingredient, checked}` | Tick an ingredient as bought; `DELETE` unticks all |
| GET | `/api/food-group?ingredient=<name>` | | The ingredient's group, or the built-in guess (`null` if unknown) |
| PUT | `/api/ingredients/<name>` | `{food_group}` | Reclassify an ingredient |
| PUT | `/api/goals` | `{goals: [{food_group, kind, target}]}` | Weekly goals; `kind`: max/min/track/off; `food_group` may also be `fish` |

Errors come back as `{"error": "message"}` with status 400 or 404.

## Code

- `foods.py`: food groups, default nutrition goals, and the built-in list of common foods.
- `config.py`: menu rules (meals left unplanned, category rules, seasons, leftovers, weeks).
- `menu.py`: OR-Tools CP-SAT solver. `solve(dishes, slots, locked, allowed)`.
- `db.py`: SQLite schema (with numbered migrations) and all reads/writes. Every write goes through `write()`, which bumps `version`.
- `app.py`: Flask routes. `static/`: the PWA (plain HTML/CSS/JS, no build step).
- Tests: `pytest`.
