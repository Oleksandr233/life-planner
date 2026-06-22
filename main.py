import os
import bcrypt
from datetime import date, timedelta
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import SQLModel, Field, Session, create_engine, select
from starlette.middleware.sessions import SessionMiddleware


# --- Модели ---
class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    coins: int = 0
    active_theme: str = "default"


class Goal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    title: str
    horizon: str
    done: bool = False


class Habit(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str
    goal_id: int | None = Field(default=None, foreign_key="goal.id")
    streak: int = 0
    last_done: date | None = None


class ThemeUnlock(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    key: str


# --- База данных ---
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///habits.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SQLModel.metadata.create_all(engine)

app = FastAPI()
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

HORIZONS = ["Сегодня", "Эта неделя", "Этот месяц", "Этот год"]

THEMES = {
    "default": {"name": "Светлая", "price": 0,   "bg": "#ffffff", "fg": "#222222"},
    "dark":    {"name": "Тёмная",  "price": 10,  "bg": "#1e1e2e", "fg": "#e6e6e6"},
    "forest":  {"name": "Лес",     "price": 50,  "bg": "#1b3a2b", "fg": "#d8f3dc"},
    "sunset":  {"name": "Закат",   "price": 100, "bg": "#3a1c2b", "fg": "#ffd9c0"},
}


# --- Помощники ---
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def current_user(request: Request, session: Session):
    uid = request.session.get("user_id")
    if uid is None:
        return None
    return session.get(User, uid)


def habit_view(habit, today):
    done = habit.last_done == today
    alive = habit.last_done in (today, today - timedelta(days=1))
    streak = habit.streak if alive else 0
    mark = "✅" if done else "⬜"
    return mark, streak, done


def auth_page(title: str, action: str) -> str:
    return f"""
    <html><head><title>{title}</title></head>
    <body style="font-family: sans-serif; max-width: 360px; margin: 40px auto;">
      <h1>{title}</h1>
      <form action="{action}" method="post">
        <p><input name="username" placeholder="Имя пользователя" required style="width:100%;padding:8px"></p>
        <p><input name="password" type="password" placeholder="Пароль" required style="width:100%;padding:8px"></p>
        <button type="submit" style="padding:8px 16px">{title}</button>
      </form>
      <p><a href="/login">Войти</a> · <a href="/register">Регистрация</a></p>
    </body></html>
    """


# --- Главная ---
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    today = date.today()
    with Session(engine) as session:
        user = current_user(request, session)
        if user is None:
            return HTMLResponse("""
            <html><head><title>Планировщик жизни</title></head>
            <body style="font-family:sans-serif; max-width:360px; margin:40px auto; text-align:center">
              <h1>Планировщик жизни</h1>
              <p>Цели, привычки и немного игры, чтобы их держать.</p>
              <p><a href="/register">Регистрация</a> · <a href="/login">Войти</a></p>
            </body></html>
            """)

        goals = session.exec(select(Goal).where(Goal.user_id == user.id)).all()
        habits = session.exec(select(Habit).where(Habit.user_id == user.id)).all()
        unlocked = {u.key for u in session.exec(
            select(ThemeUnlock).where(ThemeUnlock.user_id == user.id)).all()}
        coins = user.coins
        active = user.active_theme
        username = user.username

    unlocked.add("default")
    theme = THEMES.get(active, THEMES["default"])
    goal_title_by_id = {g.id: g.title for g in goals}
    who = f"Вы вошли как <b>{username}</b> · <a href='/logout'>выйти</a>"

    # --- Цели по горизонтам, с привычками под каждой ---
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
                            <form action="/goals/{goal.id}/rename" method="post" style="display:inline">
                                <input name="title" placeholder="новое название" required>
                                <button type="submit">переименовать</button>
                            </form>
                            <form action="/goals/{goal.id}/delete" method="post" style="display:inline"
                                  onsubmit="return confirm('Удалить цель? Её привычки останутся, но станут без цели.')">
                                <button type="submit">удалить</button>
                            </form>
                            <ul>{sub}</ul>
                        </li>"""
        if items == "":
            items = "<li><i>пока пусто</i></li>"
        goals_html += f"<h3>{h}</h3><ul>{items}</ul>"

    goal_options = '<option value="">— без цели —</option>'
    for g in goals:
        goal_options += f'<option value="{g.id}">{g.title}</option>'

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
        controls = f"""
                <form action="/habits/{habit.id}/rename" method="post" style="display:inline">
                    <input name="name" placeholder="новое название" required>
                    <button type="submit">переименовать</button>
                </form>
                <form action="/habits/{habit.id}/delete" method="post" style="display:inline"
                      onsubmit="return confirm('Удалить привычку?')">
                    <button type="submit">удалить</button>
                </form>"""
        habits_html += f"<li>{mark} {habit.name}{fire} <small>(цель: {serves})</small> {action} {controls}</li>"

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
                background: {theme['bg']}; color: {theme['fg']};
                font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
                line-height: 1.5; margin: 0; padding: 24px;
            }}
            .container {{ max-width: 640px; margin: 0 auto; }}
            h1 {{ font-size: 22px; margin: 26px 0 12px; }}
            h2 {{ font-size: 16px; margin: 0 0 12px; }}
            h3 {{ font-size: 12px; opacity: 0.6; text-transform: uppercase; letter-spacing: 0.5px; margin: 14px 0 4px; }}
            .card {{ background: rgba(128,128,128,0.10); border: 1px solid rgba(128,128,128,0.22);
                     border-radius: 14px; padding: 16px 18px; margin-bottom: 16px; }}
            ul {{ list-style: none; padding: 0; margin: 0; }}
            li {{ padding: 5px 0; }}
            button {{ background: #6c5ce7; color: #fff; border: none; border-radius: 8px;
                      padding: 7px 12px; font-size: 13px; cursor: pointer; }}
            button:hover {{ background: #5a4bd1; }}
            input, select {{ padding: 8px 10px; border-radius: 8px; border: 1px solid rgba(128,128,128,0.35);
                             background: transparent; color: inherit; margin: 0 6px 6px 0; }}
            .coins {{ display: inline-block; background: rgba(128,128,128,0.15); border-radius: 999px;
                      padding: 8px 18px; font-size: 18px; font-weight: 600; }}
            small {{ opacity: 0.65; }}
            a {{ color: inherit; }}
        </style>
    </head>
    <body>
        <div class="container">
            <p style="text-align:right">{who}</p>
            <div class="coins">💰 {coins} монет</div>

            <h1>Мои цели</h1>
            <div class="card">{goals_html}</div>

            <div class="card">
                <h2>Добавить цель</h2>
                <form action="/goals" method="post">
                    <input name="title" placeholder="Название цели" required>
                    <select name="horizon">
                        <option>Сегодня</option><option>Эта неделя</option>
                        <option>Этот месяц</option><option>Этот год</option>
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


# --- Цели ---
@app.post("/goals")
def create_goal(request: Request, title: str = Form(), horizon: str = Form()):
    with Session(engine) as session:
        user = current_user(request, session)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        session.add(Goal(user_id=user.id, title=title, horizon=horizon))
        session.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/goals/{goal_id}/toggle")
def toggle_goal(request: Request, goal_id: int):
    with Session(engine) as session:
        user = current_user(request, session)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        goal = session.get(Goal, goal_id)
        if goal and goal.user_id == user.id:        # только своё
            goal.done = not goal.done
            session.add(goal)
            session.commit()
    return RedirectResponse("/", status_code=303)


# --- Привычки ---
@app.post("/habits")
def create_habit(request: Request, name: str = Form(), goal_id: str = Form("")):
    gid = int(goal_id) if goal_id else None
    with Session(engine) as session:
        user = current_user(request, session)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        # цель должна существовать И быть своей
        if gid is not None:
            goal = session.get(Goal, gid)
            if goal is None or goal.user_id != user.id:
                gid = None
        session.add(Habit(user_id=user.id, name=name, goal_id=gid))
        session.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/habits/{habit_id}/done")
def complete_habit(request: Request, habit_id: int):
    today = date.today()
    with Session(engine) as session:
        user = current_user(request, session)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        habit = session.get(Habit, habit_id)
        if habit and habit.user_id == user.id and habit.last_done != today:
            if habit.last_done == today - timedelta(days=1):
                habit.streak += 1
            else:
                habit.streak = 1
            habit.last_done = today
            user.coins += 10 + habit.streak       # монеты — на пользователя
            session.add(habit)
            session.add(user)
            session.commit()
    return RedirectResponse("/", status_code=303)


# --- Магазин ---
@app.post("/shop/buy/{key}")
def buy_theme(request: Request, key: str):
    if key not in THEMES:
        return RedirectResponse("/", status_code=303)
    with Session(engine) as session:
        user = current_user(request, session)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        already = session.exec(select(ThemeUnlock).where(
            ThemeUnlock.user_id == user.id, ThemeUnlock.key == key)).first()
        price = THEMES[key]["price"]
        if already is None and user.coins >= price:
            user.coins -= price
            session.add(ThemeUnlock(user_id=user.id, key=key))
            session.add(user)
            session.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/shop/activate/{key}")
def activate_theme(request: Request, key: str):
    with Session(engine) as session:
        user = current_user(request, session)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        owned = key == "default" or session.exec(select(ThemeUnlock).where(
            ThemeUnlock.user_id == user.id, ThemeUnlock.key == key)).first() is not None
        if key in THEMES and owned:
            user.active_theme = key
            session.add(user)
            session.commit()
    return RedirectResponse("/", status_code=303)


# --- Удаление и редактирование ---
@app.post("/goals/{goal_id}/delete")
def delete_goal(request: Request, goal_id: int):
    with Session(engine) as session:
        user = current_user(request, session)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        goal = session.get(Goal, goal_id)
        if goal and goal.user_id == user.id:
            # сначала отвязываем привычки этой цели, чтобы не было «призрачных» ссылок
            linked = session.exec(select(Habit).where(Habit.goal_id == goal.id)).all()
            for hb in linked:
                hb.goal_id = None
                session.add(hb)
            session.delete(goal)
            session.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/goals/{goal_id}/rename")
def rename_goal(request: Request, goal_id: int, title: str = Form()):
    with Session(engine) as session:
        user = current_user(request, session)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        goal = session.get(Goal, goal_id)
        if goal and goal.user_id == user.id and title.strip():
            goal.title = title.strip()
            session.add(goal)
            session.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/habits/{habit_id}/delete")
def delete_habit(request: Request, habit_id: int):
    with Session(engine) as session:
        user = current_user(request, session)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        habit = session.get(Habit, habit_id)
        if habit and habit.user_id == user.id:
            session.delete(habit)
            session.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/habits/{habit_id}/rename")
def rename_habit(request: Request, habit_id: int, name: str = Form()):
    with Session(engine) as session:
        user = current_user(request, session)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        habit = session.get(Habit, habit_id)
        if habit and habit.user_id == user.id and name.strip():
            habit.name = name.strip()
            session.add(habit)
            session.commit()
    return RedirectResponse("/", status_code=303)


# --- Аккаунты ---
@app.get("/register", response_class=HTMLResponse)
def register_page():
    return auth_page("Регистрация", "/register")


@app.post("/register")
def register(request: Request, username: str = Form(), password: str = Form()):
    with Session(engine) as session:
        exists = session.exec(select(User).where(User.username == username)).first()
        if exists:
            return HTMLResponse("Имя уже занято. <a href='/register'>назад</a>", status_code=400)
        user = User(username=username, password_hash=hash_password(password))
        session.add(user)
        session.commit()
        session.refresh(user)
        request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return auth_page("Вход", "/login")


@app.post("/login")
def login(request: Request, username: str = Form(), password: str = Form()):
    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == username)).first()
        if user is None or not verify_password(password, user.password_hash):
            return HTMLResponse("Неверное имя или пароль. <a href='/login'>назад</a>", status_code=400)
        request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)