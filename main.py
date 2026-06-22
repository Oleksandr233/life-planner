from datetime import date, timedelta
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import SQLModel, Field, Session, create_engine, select


# --- Модели ---
class Goal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    horizon: str
    done: bool = False


class Habit(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    goal_id: int | None = Field(default=None, foreign_key="goal.id")
    streak: int = 0
    last_done: date | None = None


class Wallet(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    coins: int = 0


# НОВОЕ: текущая включённая тема
class Settings(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    active_theme: str = "default"


# НОВОЕ: купленные темы (по строке на тему)
class ThemeUnlock(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    key: str


# --- База данных ---
engine = create_engine("sqlite:///habits.db")
SQLModel.metadata.create_all(engine)

# кошелёк и настройки должны существовать (по одной строке с id=1)
with Session(engine) as session:
    if session.get(Wallet, 1) is None:
        session.add(Wallet(id=1, coins=0))
    if session.get(Settings, 1) is None:
        session.add(Settings(id=1, active_theme="default"))
    session.commit()

app = FastAPI()

HORIZONS = ["Сегодня", "Эта неделя", "Этот месяц", "Этот год"]

# Темы: название, цена и два цвета (фон и текст)
THEMES = {
    "default": {"name": "Светлая", "price": 0,   "bg": "#ffffff", "fg": "#222222"},
    "dark":    {"name": "Тёмная",  "price": 10,  "bg": "#1e1e2e", "fg": "#e6e6e6"},
    "forest":  {"name": "Лес",     "price": 50,  "bg": "#1b3a2b", "fg": "#d8f3dc"},
    "sunset":  {"name": "Закат",   "price": 100, "bg": "#3a1c2b", "fg": "#ffd9c0"},
}


def habit_view(habit, today):
    done = habit.last_done == today
    alive = habit.last_done in (today, today - timedelta(days=1))
    streak = habit.streak if alive else 0
    mark = "✅" if done else "⬜"
    return mark, streak, done


@app.get("/", response_class=HTMLResponse)
def home():
    today = date.today()
    with Session(engine) as session:
        goals = session.exec(select(Goal)).all()
        habits = session.exec(select(Habit)).all()
        coins = session.get(Wallet, 1).coins
        active = session.get(Settings, 1).active_theme
        unlocked = {u.key for u in session.exec(select(ThemeUnlock)).all()}
    unlocked.add("default")

    theme = THEMES.get(active, THEMES["default"])
    goal_title_by_id = {g.id: g.title for g in goals}

    # --- Цели по горизонтам ---
    goals_html = ""
    for h in HORIZONS:
        items = ""
        for goal in goals:
            if goal.horizon != h:
                continue
            gmark = "✅" if goal.done else "⬜"
            linked = [hb for hb in habits if hb.goal_id == goal.id]
            sub = ""
            for hb in linked:
                mark, streak, _ = habit_view(hb, today)
                fire = f" 🔥{streak}" if streak else ""
                sub += f"<li style='margin-left:20px'>↳ {mark} {hb.name}{fire}</li>"
            items += f"""
            <li>{gmark} <b>{goal.title}</b>
                <form action="/goals/{goal.id}/toggle" method="post" style="display:inline">
                    <button type="submit">выполнено</button>
                </form>
                <ul>{sub}</ul>
            </li>"""
        if items == "":
            items = "<li><i>пока пусто</i></li>"
        goals_html += f"<h3>{h}</h3><ul>{items}</ul>"

    goal_options = '<option value="">— без цели —</option>'
    for g in goals:
        goal_options += f'<option value="{g.id}">{g.title}</option>'

    # --- Привычки ---
    habits_html = ""
    for habit in habits:
        mark, streak, done = habit_view(habit, today)
        fire = f" 🔥{streak}" if streak else ""
        serves = goal_title_by_id.get(habit.goal_id, "не привязана")
        if done:
            action = "<small>сделано сегодня</small>"
        else:
            action = f"""<form action="/habits/{habit.id}/done" method="post" style="display:inline">
                <button type="submit">выполнить</button>
            </form>"""
        habits_html += f"<li>{mark} {habit.name}{fire} <small>(цель: {serves})</small> {action}</li>"

    # --- Магазин тем ---
    shop_html = ""
    for key, t in THEMES.items():
        if key == active:
            status = "<b>включена</b>"
        elif key in unlocked:
            status = f"""<form action="/shop/activate/{key}" method="post" style="display:inline">
                <button type="submit">включить</button></form>"""
        else:
            status = f"""<form action="/shop/buy/{key}" method="post" style="display:inline">
                <button type="submit">купить за {t['price']} 💰</button></form>"""
        shop_html += f"<li>{t['name']} — {status}</li>"

    page = f"""
    <html>
    <head>
        <title>Планировщик жизни</title>
        <style>
            * {{ box-sizing: border-box; }}
            body {{
                background: {theme['bg']};
                color: {theme['fg']};
                font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
                line-height: 1.5;
                margin: 0;
                padding: 24px;
            }}
            .container {{ max-width: 640px; margin: 0 auto; }}
            h1 {{ font-size: 22px; margin: 26px 0 12px; }}
            h2 {{ font-size: 16px; margin: 0 0 12px; }}
            h3 {{
                font-size: 12px; opacity: 0.6;
                text-transform: uppercase; letter-spacing: 0.5px;
                margin: 14px 0 4px;
            }}
            .card {{
                background: rgba(128,128,128,0.10);
                border: 1px solid rgba(128,128,128,0.22);
                border-radius: 14px;
                padding: 16px 18px;
                margin-bottom: 16px;
            }}
            ul {{ list-style: none; padding: 0; margin: 0; }}
            li {{ padding: 5px 0; }}
            button {{
                background: #6c5ce7; color: #fff;
                border: none; border-radius: 8px;
                padding: 7px 12px; font-size: 13px; cursor: pointer;
            }}
            button:hover {{ background: #5a4bd1; }}
            input, select {{
                padding: 8px 10px; border-radius: 8px;
                border: 1px solid rgba(128,128,128,0.35);
                background: transparent; color: inherit;
                margin: 0 6px 6px 0;
            }}
            .coins {{
                display: inline-block;
                background: rgba(128,128,128,0.15);
                border-radius: 999px;
                padding: 8px 18px; font-size: 18px; font-weight: 600;
            }}
            small {{ opacity: 0.65; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="coins">💰 {coins} монет</div>

            <h1>Мои цели</h1>
            <div class="card">{goals_html}</div>

            <div class="card">
                <h2>Добавить цель</h2>
                <form action="/goals" method="post">
                    <input name="title" placeholder="Название цели" required>
                    <select name="horizon">
                        <option>Сегодня</option>
                        <option>Эта неделя</option>
                        <option>Этот месяц</option>
                        <option>Этот год</option>
                    </select>
                    <button type="submit">добавить цель</button>
                </form>
            </div>

            <h1>Мои привычки</h1>
            <div class="card"><ul>{habits_html}</ul></div>

            <div class="card">
                <h2>Добавить привычку</h2>
                <form action="/habits" method="post">
                    <input name="name" placeholder="Название привычки" required>
                    <select name="goal_id">{goal_options}</select>
                    <button type="submit">добавить</button>
                </form>
            </div>

            <h1>🛍 Магазин тем</h1>
            <div class="card"><ul>{shop_html}</ul></div>
        </div>
    </body>
    </html>
    """
    return page


# --- Привычки ---
@app.post("/habits")
def create_habit(name: str = Form(), goal_id: str = Form("")):
    gid = int(goal_id) if goal_id else None
    with Session(engine) as session:
        session.add(Habit(name=name, goal_id=gid))
        session.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/habits/{habit_id}/done")
def complete_habit(habit_id: int):
    today = date.today()
    with Session(engine) as session:
        habit = session.get(Habit, habit_id)
        if habit and habit.last_done != today:
            if habit.last_done == today - timedelta(days=1):
                habit.streak += 1
            else:
                habit.streak = 1
            habit.last_done = today
            reward = 10 + habit.streak
            wallet = session.get(Wallet, 1)
            wallet.coins += reward
            session.add(habit)
            session.add(wallet)
            session.commit()
    return RedirectResponse("/", status_code=303)


# --- Цели ---
@app.post("/goals")
def create_goal(title: str = Form(), horizon: str = Form()):
    with Session(engine) as session:
        session.add(Goal(title=title, horizon=horizon))
        session.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/goals/{goal_id}/toggle")
def toggle_goal(goal_id: int):
    with Session(engine) as session:
        goal = session.get(Goal, goal_id)
        if goal:
            goal.done = not goal.done
            session.add(goal)
            session.commit()
    return RedirectResponse("/", status_code=303)


# --- Магазин ---
@app.post("/shop/buy/{key}")
def buy_theme(key: str):
    if key not in THEMES:
        return RedirectResponse("/", status_code=303)
    price = THEMES[key]["price"]
    with Session(engine) as session:
        unlocked = {u.key for u in session.exec(select(ThemeUnlock)).all()}
        wallet = session.get(Wallet, 1)
        if key not in unlocked and wallet.coins >= price:   # хватает и ещё не куплена
            wallet.coins -= price
            session.add(ThemeUnlock(key=key))
            session.add(wallet)
            session.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/shop/activate/{key}")
def activate_theme(key: str):
    with Session(engine) as session:
        unlocked = {u.key for u in session.exec(select(ThemeUnlock)).all()}
        unlocked.add("default")
        if key in THEMES and key in unlocked:
            settings = session.get(Settings, 1)
            settings.active_theme = key
            session.add(settings)
            session.commit()
    return RedirectResponse("/", status_code=303)