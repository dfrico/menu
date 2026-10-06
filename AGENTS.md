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
   - `category`: exactly one, the main component (beef, chicken, fish, egg, vegetarian…).
     The menu rules use it. Reuse an existing category whenever one fits.
   - `tags`: optional descriptive labels (cuisine, "soup", "quick"…). Reuse existing ones.
   - `combinable`: `true` for dishes that are usually eaten together with another one
     (soups, salads, sides); `false` for full meals like pizza.
   - `ingredients`: generic, lowercase names of what you'd need to have at home:
     `"200 g carne picada de ternera"` becomes `"minced meat"`. Drop quantities and
     brands. Reuse an existing ingredient name if it means the same thing.
     Mark staples (oil, salt, pepper, garlic, flour, common spices) with `"main": false`.
   - `notes`: the recipe URL.
3. Create it:
   ```sh
   curl -s -X POST $MENU_URL/api/dishes -H 'Content-Type: application/json' -d '{
     "name": "Spaghetti bolognese",
     "category": "beef",
     "tags": ["italian"],
     "combinable": false,
     "ingredients": [
       {"name": "minced meat"}, {"name": "pasta"}, {"name": "tomato"},
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
| POST | `/api/dishes` | `{name, category, tags?, combinable?, ingredients?, notes?}` | `ingredients`: strings or `{name, main}` |
| GET/PUT/DELETE | `/api/dishes/<id>` | same as POST | |
| GET | `/api/categories`, `/api/tags`, `/api/ingredients` | | Lists of names |
| POST | `/api/menu/generate` | `{weeks?}` | Replaces the menu |
| POST | `/api/menu/swap` | `{a: slot, b: slot}` | slot = `{week, day, meal}` |
| PUT | `/api/menu/slot` | `{week, day, meal, dish_id}` | `dish_id: null` clears; a dish planned elsewhere swaps |
| PUT | `/api/menu/side` | `{week, day, meal, dish_id}` | Second dish of a meal; both must be combinable. `null` removes |
| PUT | `/api/settings` | `{weeks}` | 1 or 2; keeps week 1 when adding week 2 |

Errors come back as `{"error": "message"}` with status 400 or 404.

## Code

- `config.py`: menu rules (free meals, tag rules, weeks).
- `menu.py`: OR-Tools CP-SAT solver. `solve(dishes, slots, locked)`.
- `db.py`: SQLite schema (with numbered migrations) and all reads/writes. Every write goes through `write()`, which bumps `version`.
- `app.py`: Flask routes. `static/`: the PWA (plain HTML/CSS/JS, no build step).
- Tests: `pytest`.
