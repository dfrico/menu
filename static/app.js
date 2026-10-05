'use strict';

// --- Helpers -----------------------------------------------------------------

const $ = (sel, root = document) => root.querySelector(sel);

// Builds an element: h('li', {class: 'x', onclick: fn}, 'text', childEl)
const h = (tag, attrs = {}, ...children) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  el.append(...children.flat().filter(c => c != null && c !== false));
  return el;
};

const parseDate = iso => { const [y, m, d] = iso.split('-').map(Number); return new Date(y, m - 1, d); };
const addDays = (date, n) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + n);
const sameDay = (a, b) => a.toDateString() === b.toDateString();
const fmtDate = date => date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
const slotKey = s => `${s.week}|${s.day}|${s.meal}`;
const slotOf = el => ({ week: Number(el.dataset.week), day: el.dataset.day, meal: el.dataset.meal });
const slotLabel = s => `${s.day} ${s.meal.toLowerCase()}${state.weeks > 1 ? ` · week ${s.week}` : ''}`;

const storage = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode */ } },
};

let toastTimer;
function toast(message, error = false) {
  const el = $('#toast');
  el.textContent = message;
  el.className = error ? 'show error' : 'show';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), error ? 5000 : 2500);
}

// --- API & state -------------------------------------------------------------

let state = null;
let pendingRender = false;

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function setState(next) {
  state = next;
  if (drag) pendingRender = true;
  else render();
}

async function refresh() {
  try {
    setState(await api('GET', '/api/state'));
  } catch {
    toast("Can't reach the server", true);
  }
}

// Runs a write; the server's answer (or a refresh) becomes the new state.
async function act(request, success) {
  try {
    const result = await request();
    if (result && result.version !== undefined) setState(result);
    else await refresh();
    if (success) toast(success);
    return true;
  } catch (e) {
    toast(e.message, true);
    await refresh();
    return false;
  }
}

// Other devices' changes: the server pushes the data version, we refetch.
function listenForChanges() {
  if (!('EventSource' in window)) return;
  const events = new EventSource('/api/events');
  events.onmessage = e => {
    if (!state || Number(e.data) !== state.version) refresh();
  };
}

// --- Rendering ---------------------------------------------------------------

function render() {
  renderMenu();
  renderDishes();
  renderOptions();
  if ($('#picker').open) renderPicker();
}

function renderMenu() {
  document.querySelectorAll('.segmented button').forEach(b =>
    b.setAttribute('aria-pressed', String(Number(b.dataset.weeks) === state.weeks)));

  const dishById = new Map(state.dishes.map(d => [d.id, d]));
  const planned = new Map(state.menu.map(s => [slotKey(s), s.dish_id]));
  const free = new Set(state.free_slots.map(([day, meal]) => `${day}|${meal}`));
  const start = state.start_date ? parseDate(state.start_date) : null;
  const today = new Date();

  const notice = $('#menu-notice');
  const missing = state.slots_needed - state.dishes.length;
  if (missing > 0) {
    notice.textContent = `You have ${state.dishes.length} dishes but ${state.slots_needed} meals to plan. Add at least ${missing} more in Dishes.`;
  } else if (!state.menu.length) {
    notice.textContent = 'No menu yet. Tap “New menu” to plan the week.';
  }
  notice.hidden = !(missing > 0 || !state.menu.length);

  const container = $('#menu');
  container.replaceChildren();
  if (!state.menu.length) return;

  for (let week = 1; week <= state.weeks; week++) {
    const weekStart = start && addDays(start, (week - 1) * 7);
    const range = weekStart && `${fmtDate(weekStart)} – ${fmtDate(addDays(weekStart, 6))}`;
    const title = state.weeks > 1 ? [`Week ${week}`, range].filter(Boolean).join(' · ') : range;
    if (title) container.append(h('h2', { class: 'week-title' }, title));

    state.days.forEach((day, i) => {
      const date = weekStart && addDays(weekStart, i);
      const isToday = date && sameDay(date, today);
      const dayEl = h('div', { class: isToday ? 'day today' : 'day' },
        h('div', { class: 'day-name' },
          day,
          date && h('span', { class: 'date' }, fmtDate(date)),
          isToday && h('span', { class: 'badge' }, 'Today')));

      for (const meal of state.meals) {
        const label = h('span', { class: 'meal-label' }, meal);
        if (free.has(`${day}|${meal}`)) {
          dayEl.append(h('div', { class: 'meal free' }, label, h('span', { class: 'dish-name' }, 'Free')));
          continue;
        }
        const dish = dishById.get(planned.get(slotKey({ week, day, meal })));
        dayEl.append(h('div', {
          class: dish ? 'meal' : 'meal empty',
          dataset: { week, day, meal },
        },
          label,
          h('span', { class: 'dish-name' }, dish ? dish.name : 'Nothing planned'),
          dish && h('span', { class: 'tag' }, dish.tag)));
      }
      container.append(dayEl);
    });
  }
}

function matches(dish, query) {
  if (!query) return true;
  return [dish.name, dish.tag, ...dish.ingredients.map(i => i.name)]
    .some(text => text.toLowerCase().includes(query));
}

function renderDishes() {
  const query = $('#dish-search').value.trim().toLowerCase();
  const dishes = state.dishes.filter(d => matches(d, query));
  const withoutIngredients = state.dishes.filter(d => !d.ingredients.length).length;
  $('#dish-count').textContent = [
    `${state.dishes.length} dishes`,
    withoutIngredients && `${withoutIngredients} without ingredients`,
  ].filter(Boolean).join(' · ');

  $('#dish-list').replaceChildren(...dishes.map(d => h('li', { onclick: () => openEditor(d) },
    h('span', { class: 'info' },
      d.name,
      h('span', { class: 'sub' }, d.ingredients.length
        ? d.ingredients.filter(i => i.main).map(i => i.name).join(', ') || 'only staples'
        : 'No ingredients yet')),
    h('span', { class: 'tag' }, d.tag))));
}

function renderOptions() {
  $('#tag-options').replaceChildren(...state.tags.map(t => h('option', { value: t })));
  $('#ingredient-options').replaceChildren(...state.ingredients.map(i => h('option', { value: i })));
}

// --- Tabs & header -----------------------------------------------------------

function showTab(name) {
  document.querySelectorAll('.tabbar button').forEach(b => {
    if (b.dataset.tab === name) b.setAttribute('aria-current', 'page');
    else b.removeAttribute('aria-current');
  });
  $('#view-menu').hidden = name !== 'menu';
  $('#view-dishes').hidden = name !== 'dishes';
  document.querySelectorAll('.topbar [data-view]').forEach(b => { b.hidden = b.dataset.view !== name; });
  $('#title').textContent = name === 'menu' ? 'Menu' : 'Dishes';
  storage.set('tab', name);
}

document.querySelectorAll('.tabbar button').forEach(b =>
  b.addEventListener('click', () => { showTab(b.dataset.tab); window.scrollTo(0, 0); }));

$('#generate').addEventListener('click', async e => {
  const button = e.currentTarget;
  if (state.menu.length && !confirm('Replace the current menu with a new one?')) return;
  button.disabled = true;
  await act(() => api('POST', '/api/menu/generate', { weeks: state.weeks }), 'New menu ready');
  button.disabled = false;
});

document.querySelectorAll('.segmented button').forEach(b => b.addEventListener('click', () => {
  const weeks = Number(b.dataset.weeks);
  if (weeks === state.weeks) return;
  if (weeks < state.weeks && state.menu.some(s => s.week > weeks)
      && !confirm('Remove week 2 from the menu?')) return;
  act(() => api('PUT', '/api/settings', { weeks }),
    weeks > state.weeks && state.menu.length ? 'Week 2 planned' : null);
}));

// --- Drag and drop -----------------------------------------------------------
// Works with mouse (pointer events) and touch (touch events, hold to start so
// that normal swipes still scroll the page).

const LONG_PRESS_MS = 300;
const MOVE_TOLERANCE = 8;
const EDGE = 80;

let press = null; // finger/mouse is down on a meal, drag not started yet
let drag = null;  // { source, ghost, target, x, y, frame }

const menuEl = $('#menu');
const mealAt = target => target.closest?.('.meal[data-day]');
const moved = (x, y) => press && Math.hypot(x - press.x, y - press.y) > MOVE_TOLERANCE;

function cancelPress() {
  if (!press) return;
  clearTimeout(press.timer);
  press.el.classList.remove('pressing');
  press = null;
}

function startDrag(el, x, y) {
  cancelPress();
  const rect = el.getBoundingClientRect();
  const ghost = el.cloneNode(true);
  ghost.classList.add('drag-ghost');
  ghost.style.width = `${rect.width}px`;
  document.body.append(ghost);
  el.classList.add('drag-source');
  document.body.classList.add('dragging');
  drag = { source: el, ghost, target: null, x, y, frame: requestAnimationFrame(autoScroll) };
  moveDrag(x, y);
  navigator.vibrate?.(15);
}

function moveDrag(x, y) {
  Object.assign(drag, { x, y });
  drag.ghost.style.left = `${x}px`;
  drag.ghost.style.top = `${y}px`;
  const hit = document.elementFromPoint(x, y);
  const target = hit && mealAt(hit);
  const next = target && target !== drag.source ? target : null;
  if (next !== drag.target) {
    drag.target?.classList.remove('drop-target');
    next?.classList.add('drop-target');
    drag.target = next;
  }
}

function autoScroll() {
  if (!drag) return;
  const bottom = window.innerHeight - $('.tabbar').offsetHeight;
  const top = $('.topbar').offsetHeight;
  let dy = 0;
  if (drag.y < top + EDGE) dy = -Math.ceil((top + EDGE - drag.y) / 6);
  else if (drag.y > bottom - EDGE) dy = Math.ceil((drag.y - bottom + EDGE) / 6);
  if (dy) {
    window.scrollBy(0, dy);
    moveDrag(drag.x, drag.y);
  }
  drag.frame = requestAnimationFrame(autoScroll);
}

function endDrag(drop = true) {
  const { source, target, ghost, frame } = drag;
  cancelAnimationFrame(frame);
  ghost.remove();
  source.classList.remove('drag-source');
  target?.classList.remove('drop-target');
  document.body.classList.remove('dragging');
  drag = null;
  if (drop && target) swap(slotOf(source), slotOf(target));
  else if (pendingRender) render();
  pendingRender = false;
}

function swap(a, b) {
  // Show the swap immediately; the server confirms (or we refetch on error).
  const entry = s => state.menu.find(m => slotKey(m) === slotKey(s));
  const ea = entry(a), eb = entry(b);
  if (ea && eb) [ea.dish_id, eb.dish_id] = [eb.dish_id, ea.dish_id];
  render();
  act(() => api('POST', '/api/menu/swap', { a, b }));
}

// Mouse
menuEl.addEventListener('pointerdown', e => {
  if (e.pointerType === 'touch' || e.button !== 0) return;
  const el = mealAt(e.target);
  if (el) press = { el, x: e.clientX, y: e.clientY };
});
window.addEventListener('pointermove', e => {
  if (e.pointerType === 'touch') return;
  if (drag) moveDrag(e.clientX, e.clientY);
  else if (moved(e.clientX, e.clientY)) startDrag(press.el, e.clientX, e.clientY);
});
window.addEventListener('pointerup', e => {
  if (e.pointerType === 'touch') return;
  if (drag) endDrag();
  else if (press) openPicker(press.el);
  press = null;
});

// Touch
menuEl.addEventListener('touchstart', e => {
  cancelPress();
  const el = e.touches.length === 1 && mealAt(e.target);
  if (!el) return;
  const { clientX: x, clientY: y } = e.touches[0];
  press = { el, x, y, timer: setTimeout(() => startDrag(el, x, y), LONG_PRESS_MS) };
  el.classList.add('pressing');
}, { passive: true });

menuEl.addEventListener('touchmove', e => {
  const { clientX: x, clientY: y } = e.touches[0];
  if (drag) {
    if (!e.cancelable) return endDrag(false); // the browser is already scrolling
    e.preventDefault();
    moveDrag(x, y);
  } else if (moved(x, y)) {
    cancelPress(); // it's a scroll, not a press
  }
}, { passive: false });

menuEl.addEventListener('touchend', e => {
  if (drag) {
    e.preventDefault();
    endDrag();
  } else if (press) {
    const el = press.el;
    cancelPress();
    e.preventDefault(); // no emulated mouse click afterwards
    openPicker(el);
  }
});

menuEl.addEventListener('touchcancel', () => {
  cancelPress();
  if (drag) endDrag(false);
});

menuEl.addEventListener('contextmenu', e => { if (mealAt(e.target)) e.preventDefault(); });

// --- Dish picker (tap a meal) ------------------------------------------------

let pickerSlot = null;

function openPicker(el) {
  pickerSlot = slotOf(el);
  $('#picker-title').textContent = slotLabel(pickerSlot);
  $('#picker-search').value = '';
  renderPicker();
  $('#picker').showModal();
}

function renderPicker() {
  const query = $('#picker-search').value.trim().toLowerCase();
  const plannedAt = new Map(state.menu.filter(s => s.dish_id != null).map(s => [s.dish_id, s]));
  const current = state.menu.find(s => slotKey(s) === slotKey(pickerSlot))?.dish_id;
  const dishes = state.dishes
    .filter(d => matches(d, query))
    .sort((a, b) => (b.id === current) - (a.id === current)
      || plannedAt.has(a.id) - plannedAt.has(b.id)
      || a.name.localeCompare(b.name));

  $('#picker-list').replaceChildren(...dishes.map(d => {
    const at = plannedAt.get(d.id);
    return h('li', {
      class: d.id === current ? 'current' : null,
      onclick: () => {
        $('#picker').close();
        if (d.id !== current) act(() => api('PUT', '/api/menu/slot', { ...pickerSlot, dish_id: d.id }));
      },
    },
      h('span', { class: 'info' }, d.name,
        at && h('span', { class: 'sub' }, d.id === current ? 'Current' : `Planned ${slotLabel(at)} · will swap`)),
      h('span', { class: 'tag' }, d.tag));
  }));
}

$('#picker-search').addEventListener('input', renderPicker);
$('#picker-clear').addEventListener('click', () => {
  $('#picker').close();
  act(() => api('PUT', '/api/menu/slot', { ...pickerSlot, dish_id: null }));
});

// --- Dish editor ---------------------------------------------------------------

const form = $('#editor-form');
let editingId = null;
let chips = [];

function openEditor(dish = null) {
  editingId = dish?.id ?? null;
  form.reset();
  form.elements.name.value = dish?.name ?? '';
  form.elements.tag.value = dish?.tag ?? '';
  form.elements.notes.value = dish?.notes ?? '';
  chips = dish ? dish.ingredients.map(i => ({ ...i })) : [];
  $('#editor-title').textContent = dish ? 'Edit dish' : 'Add dish';
  $('#editor-delete').hidden = !dish;
  renderChips();
  $('#editor').showModal();
}

function renderChips() {
  $('#chips').replaceChildren(...chips.map((chip, i) => h('span', {
    class: chip.main ? 'chip' : 'chip staple',
    title: chip.main ? 'Main ingredient (tap to mark as staple)' : 'Staple (tap to mark as main)',
    onclick: () => { chip.main = !chip.main; renderChips(); },
  },
    chip.name,
    h('button', {
      type: 'button',
      'aria-label': `Remove ${chip.name}`,
      onclick: e => { e.stopPropagation(); chips.splice(i, 1); renderChips(); },
    }, '×'))));
}

function addIngredients() {
  const input = $('#ingredient-input');
  for (const name of input.value.split(',').map(s => s.trim().toLowerCase()).filter(Boolean)) {
    if (!chips.some(c => c.name === name)) chips.push({ name, main: true });
  }
  input.value = '';
  renderChips();
}

$('#ingredient-add').addEventListener('click', addIngredients);
$('#ingredient-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); addIngredients(); }
});
$('#ingredient-input').addEventListener('input', e => {
  if (e.target.value.includes(',')) addIngredients();
});

form.addEventListener('submit', async e => {
  e.preventDefault();
  addIngredients();
  const dish = {
    name: form.elements.name.value,
    tag: form.elements.tag.value,
    notes: form.elements.notes.value,
    ingredients: chips,
  };
  const saved = await act(() => editingId == null
    ? api('POST', '/api/dishes', dish)
    : api('PUT', `/api/dishes/${editingId}`, dish), 'Saved');
  if (saved) $('#editor').close();
});

$('#editor-cancel').addEventListener('click', () => $('#editor').close());

$('#editor-delete').addEventListener('click', async () => {
  const name = form.elements.name.value;
  const planned = state.menu.some(s => s.dish_id === editingId);
  if (!confirm(`Delete “${name}”?${planned ? ' It will be removed from the menu.' : ''}`)) return;
  if (await act(() => api('DELETE', `/api/dishes/${editingId}`), 'Deleted')) $('#editor').close();
});

$('#add-dish').addEventListener('click', () => openEditor());
$('#dish-search').addEventListener('input', renderDishes);

// --- Start -----------------------------------------------------------------------

showTab(storage.get('tab') === 'dishes' ? 'dishes' : 'menu');
refresh().then(() => $('.day.today')?.scrollIntoView({ block: 'center' }));
listenForChanges();
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register('/sw.js');
}
