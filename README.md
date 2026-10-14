# menu

You're planning the meals for the next week or two. You have a list of dishes to choose from, and a set of things you want to eat each week. How do you find a good solution that satisfies all the requirements? A good option is using [Constraint satisfaction problem](https://en.wikipedia.org/wiki/Constraint_satisfaction_problem), or CSP.

This is a small web app (installable on your phone's home screen) that plans the menu, lets you rearrange it by dragging meals around, and keeps a list of dishes with their ingredients. Several people can use it at the same time: changes show up on every open device within a second.

## How it works

- **Dishes** have a name, a category (their main component: `chicken`, `fish`, `vegetarian`…), optional tags (`japanese`, `soup`…) and a list of ingredients. Each one also has:
  - a **role**: *full meal* (pizza), *combinable* (soup, omelette: alone or with another dish) or *side only* (toast: only as a second dish, never planned alone, no category needed),
  - a **season**: all year, summer only or winter only (months in `config.py`),
  - **when it's eaten**: lunch or dinner (required; one or the other),
  - how many meals it **lasts**: 1, or 2 for things you cook once and eat twice (soups, stews). Add and edit them in the *Dishes* tab, or let an agent do it from a recipe URL (see [AGENTS.md](AGENTS.md)).
- **New menu** asks the CSP solver (`menu.py`, using [OR-Tools](https://developers.google.com/optimization)) for a plan where:
  - no dish repeats, except 2-meal dishes, whose leftovers go 1–2 days later,
  - seasonal dishes only appear in their season, and lunch dishes only at lunch, dinner dishes only at dinner,
  - lunch and dinner on the same day have different categories,
  - each week gets a fair share of every category,
  - the rules in `config.py` hold. By default Saturday lunch is left empty (you can still plan it by hand) and Saturday dinner is an `egg` dish; edit `config.py` if that doesn't suit you.
- The menu covers **1 week** by default; switch to 2 weeks in the app (week 1 is kept, week 2 is planned around it).
- **Hold and drag** a meal onto another to swap them. **Tap** a meal to pick a different dish, or to add a second dish (e.g. soup + grilled fish) when neither is a *full meal*.
- **Ingredients** lists what the planned meals need (e.g. "4× patata"), with a tick to mark things as bought, shared between phones.
- **Nutrition** shows this week's meals per food group (fish, vegetables, red meat, chicken, processed meat, legumes…) against weekly goals you can edit, green or red. Food groups come from the ingredients; common foods are classified automatically and the rest are picked once, in the dish editor or in *Ingredient food groups*.
- Everything is stored in a SQLite file (`menu.db`), so the menu survives restarts.

## Running locally

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py               # http://localhost:5001
```

If you have a `dish_list.csv` (`name,category` plus optional `tags`, `ingredients` (both separated by `;`), `role`, `season`, `meal_time` and `portions`; see `dish_list_template.csv`) it's imported automatically the first time. You can import more later with `python db.py import FILE.csv`, and back up your dishes with `python db.py export > dishes.csv`.

Tests: `pip install -r requirements-dev.txt && pytest`.

## Running on a Raspberry Pi

Needs a 64-bit OS (`uname -m` should say `aarch64`); OR-Tools has no 32-bit ARM builds. [uv](https://docs.astral.sh/uv/) provides a recent Python without touching the system one.

On the Pi:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
git init ~/menu && git -C ~/menu config receive.denyCurrentBranch updateInstead
```

From your computer (assuming an SSH host alias `pi`):

```sh
git remote add pi pi:menu
git push pi main
```

Back on the Pi:

```sh
cd ~/menu && git checkout main
~/.local/bin/uv venv -p 3.12 .venv && ~/.local/bin/uv pip install -p .venv/bin/python -r requirements.txt
sudo cp deploy/menu.service /etc/systemd/system/   # edit User/paths if they differ
sudo systemctl enable --now menu
```

The app is then at `http://<hostname>.local` (e.g. `http://dfr-pi.local`). Raspberry Pi OS announces that name on the network with Avahi; if it doesn't resolve, run `sudo apt install avahi-daemon`. If the Pi is connected by both cable and Wi-Fi, Avahi sees its own announcements and renames itself (`dfr-pi-2.local`, …): add `allow-interfaces=eth0` under `[server]` in `/etc/avahi/avahi-daemon.conf` and restart it. As a fallback, give the Pi a fixed IP in your router.

To update: `git push pi <branch>` from your computer, then `ssh pi sudo systemctl restart menu` (and `uv pip install -r requirements.txt` if dependencies changed). Logs: `journalctl -u menu -f`. Your data lives in `~/menu/menu.db`; back it up with `cp`, or export dishes with `.venv/bin/python db.py export`.

### Installing it on your phone

Open the address in Safari (iPhone) or Chrome (Android) and use *Share → Add to Home Screen*. It opens full screen like an app.

Over plain `http://` the app needs the Pi to be reachable. For offline support (opening the last menu without a connection), serve it over HTTPS, e.g. with [Tailscale](https://tailscale.com/kb/1312/serve): `sudo tailscale serve --bg 80`, then use the `https://….ts.net` address.
