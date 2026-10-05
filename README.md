# menu

You're planning the meals for the next week or two. You have a list of dishes to choose from, and a set of things you want to eat each week. How do you find a good solution that satisfies all the requirements? A good option is using [Constraint satisfaction problem](https://en.wikipedia.org/wiki/Constraint_satisfaction_problem), or CSP.

This is a small web app (installable on your phone's home screen) that plans the menu, lets you rearrange it by dragging meals around, and keeps a list of dishes with their ingredients. Several people can use it at the same time: changes show up on every open device within a second.

## How it works

- **Dishes** have a name, a tag (their main component: `chicken`, `fish`, `vegetarian`…) and a list of ingredients. Add and edit them in the *Dishes* tab, or let an agent do it from a recipe URL (see [AGENTS.md](AGENTS.md)).
- **New menu** asks the CSP solver (`menu.py`, using [OR-Tools](https://developers.google.com/optimization)) for a plan where:
  - no dish repeats,
  - lunch and dinner on the same day have different tags,
  - each week gets a fair share of every tag,
  - the rules in `config.py` hold. By default Saturday lunch is free and Saturday dinner is an `egg` dish; edit `config.py` if that doesn't suit you.
- The menu covers **1 week** by default; switch to 2 weeks in the app (week 1 is kept, week 2 is planned around it).
- **Hold and drag** a meal onto another to swap them. **Tap** a meal to pick a different dish.
- Everything is stored in a SQLite file (`menu.db`), so the menu survives restarts.

## Running locally

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py               # http://localhost:5001
```

If you have a `dish_list.csv` (`name,tag[,ingredients]`, ingredients separated by `;`; see `dish_list_template.csv`) it's imported automatically the first time. You can import more later with `python db.py import FILE.csv`, and back up your dishes with `python db.py export > dishes.csv`.

Tests: `pip install -r requirements-dev.txt && pytest`.

## Running on a Raspberry Pi

Needs a 64-bit OS (`uname -m` should say `aarch64`); OR-Tools has no 32-bit ARM builds.

```sh
git clone <this repo> ~/menu && cd ~/menu
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
scp dish_list.csv pi:~/menu/   # optional, from wherever your list is
sudo cp deploy/menu.service /etc/systemd/system/   # edit User/paths if they differ
sudo systemctl enable --now menu
```

The app is then at `http://<hostname>.local` (e.g. `http://dfr-pi.local`). Raspberry Pi OS announces that name on the network with Avahi; if it doesn't resolve, run `sudo apt install avahi-daemon`. As a fallback, give the Pi a fixed IP in your router.

To update: `git pull && sudo systemctl restart menu`. Logs: `journalctl -u menu -f`.

### Installing it on your phone

Open the address in Safari (iPhone) or Chrome (Android) and use *Share → Add to Home Screen*. It opens full screen like an app.

Over plain `http://` the app needs the Pi to be reachable. For offline support (opening the last menu without a connection), serve it over HTTPS, e.g. with [Tailscale](https://tailscale.com/kb/1312/serve): `sudo tailscale serve --bg 80`, then use the `https://….ts.net` address.
