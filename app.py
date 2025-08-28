
import os, re, json
from flask import Flask, request, render_template, redirect, url_for, session, flash
from dotenv import load_dotenv
from openai import OpenAI
from flask_babel import Babel, gettext as _t
from flask_babel import get_locale
from models.db_utils import (
    setup_database,
    get_all_populations,
    get_personas_by_population,
    get_personas_by_population_id,
    save_persona_to_db,
    get_or_create_user_session,
    create_run,
    get_latest_run,
    add_chat_message,
    get_chat_by_run,
    save_news_analysis,
    save_population,
    get_run_content,
)

import uuid



load_dotenv()

# Flask setup
app = Flask(__name__)

app.jinja_env.globals.update(_=_t) 


# Luo ja normalisoi DATABASE_URL ENNEN kuin asetat sen app.configiin
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL ei ole asetettu Herokussa.")

# Heroku antaa usein postgres://, SQLAlchemy vaatii postgresql+psycopg2://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)

# Jos käytät Flask-SQLAlchemyä:

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")
app.config['BABEL_DEFAULT_LOCALE'] = 'fi'
app.config['BABEL_SUPPORTED_LOCALES'] = ['fi', 'en']

babel = Babel(app)

@app.before_request
def ensure_sid():
    if 'sid' not in session:
        session['sid'] = uuid.uuid4().hex
    # Päivitä serveripuolen sessio (lang mukaan jos on)
    get_or_create_user_session(session['sid'], session.get('lang'))

def select_locale():
    from flask import request, session
    # session -> ?lang= -> Accept-Language -> default
    if 'lang' in session and session['lang'] in app.config['BABEL_SUPPORTED_LOCALES']:
        return session['lang']
    lang = request.args.get('lang')
    if lang in app.config['BABEL_SUPPORTED_LOCALES']:
        session['lang'] = lang
        return lang
    return request.accept_languages.best_match(app.config['BABEL_SUPPORTED_LOCALES']) or app.config['BABEL_DEFAULT_LOCALE']

# NEW v4 API: pass selector to constructor
babel = Babel(app, locale_selector=select_locale)

@app.get("/lang/<code>")
def set_lang(code):
    if code in app.config['BABEL_SUPPORTED_LOCALES']:
        session['lang'] = code
        # synkkaa DB-istuntoon
        get_or_create_user_session(session['sid'], code)
    return redirect(request.referrer or url_for("index"))

# Imports from your provided modules (now in models/)
from models.generateParticipants import generate_role, get_age_attributes, get_gender_attributes
from models.generateParticipants import Persona
from models.db_utils import get_personas_by_population, save_persona_to_db, setup_database
from models.feedback import calculate_nps
from models import main as news_main


try:
    setup_database()
except Exception as e:
    print("DB setup skipped / failed:", e)

# Helper: extract first integer 0..10 from text
def extract_score(text):
    m = re.search(r"(10|[0-9])\b", text)
    return int(m.group(1)) if m else None

@app.route("/")
def index():
    # Try to read existing populations from DB, else fallback empty
    existing = {}
     try:
        from models.db_utils import get_personas_by_population, get_all_populations
        existing = get_personas_by_population() or {}
        pops = get_all_populations()  # jos näytät listaa
    except Exception:
        existing, pops = {}, []
    return render_template("index.html", existing_populations=existing, pops=pops)

@app.route("/populations")
def populations():
    pops = get_all_populations()
    return render_template("populations.html", pops=pops)

@app.route("/population/<int:pid>")
def show_population(pid):
    personas = get_personas_by_population_id(pid)
    return render_template("population.html", personas=personas)

@app.post("/select_reviewers")
def select_reviewers():
    pop = request.form.get("population_name") or ""
    if not pop:
        flash(_t("Please choose a population or generate a new one."))
        return redirect(url_for("index"))

    try:
        populations = get_personas_by_population() or {}
        persons = populations.get(pop, [])
    except Exception:
        persons = []

    if not persons:
        flash(_t("No personas found for that population. Generate a new one instead."))
        return redirect(url_for("index"))

    population_id = find_population_id_by_name(pop)
    # Luo uusi run tälle istunnolle
    run_id = create_run(session['sid'], population_id, content_text=None)
    session['run_id'] = run_id
    session['population_id'] = population_id  # pieni arvo, ok evästeessä
    return redirect(url_for("submit_content"))

@app.post("/generate_population")
def generate_population():
    name = request.form.get("new_population") or "Generated audience"
    location = request.form.get("location") or "Helsinki"
    try:
        size = max(1, min(20, int(request.form.get("size") or "5")))
    except:
        size = 5

    age_attr = get_age_attributes(name, location)
    gender_attr = get_gender_attributes(name, location)

  # Generoi personat muistiin
    personas, unique_names = [], set()
    for i in range(size):
        p = generate_role(name, location, age_attr, gender_attr, unique_names)
        pdata = (p.model_dump() if hasattr(p, "model_dump")
                 else p.dict() if hasattr(p, "dict")
                 else dict(p))
        personas.append(pdata)

    # Tallenna kaikki kerralla ja luo run
    population_id = save_population(name, location, personas)
    run_id = create_run(session['sid'], population_id, content_text=None)

    # Sessioon vain pienet tunnisteet
    session['population_id'] = population_id
    session['run_id'] = run_id

    flash(_t("Generated %(n)d personas for population '%(name)s'.", n=len(personas), name=name))
    return redirect(url_for("submit_content"))

@app.get("/submit")
def submit_content():
    if 'run_id' not in session:
        return redirect(url_for("index"))
    return render_template("submit.html")

@app.post("/submit")
def submit_content_post():
    if 'run_id' not in session:
        return redirect(url_for("index"))
    content = (request.form.get("content") or "").strip()
    title = (request.form.get("title") or "").strip()
    if not content:
        flash(_t("Please paste your content text."))
        return redirect(url_for("submit_content"))
    update_run_content(session['run_id'], content, title=title)
    return redirect(url_for("chat"))

def find_population_id_by_name(name: str) -> int | None:
    rows = get_all_populations()
    for pid, pname, _loc in rows:
        if pname == name:
            return pid
    return None

# --- Reviewer chat generation ---
def persona_to_identity(role: dict) -> str:
    fields = [
        "name","age","gender","orientation","location","mbti_type","occupation",
        "education","income_level","financial_security","main_concern",
        "source_of_joy","social_ties","values_and_beliefs","perspective_on_change","daily_routine"
    ]
    parts = [f"{k.replace('_',' ').title()}: {role.get(k,'Unknown')}" for k in fields]
    return "You are a persona reviewer. " + "; ".join(parts)

def reviewer_comment(client: OpenAI, role: dict, content: str) -> tuple[str,int|None]:
    locale = str(get_locale()) or 'fi'
    if locale.startswith('fi'):
        identity = "Kerro, miten käyttäjän tuottama sisältö resonoi seuraavaksi kuvatulle persoonalle:" + persona_to_identity(role)
        prompt = ("Lue käyttäjän sisältö ja kirjoita YKSI lyhyt kappale joka kuvaa ensimmäisessä persoonassa sitä, miten kuvattu persoona todennäköisesti suhtautuu viestiin."
                  "Tee vastauksestasi elämänmakuinen ja pyri tarkastelemaan viestiä edustamasi ihmisen eletyn elämän näkökulmista."
                  "Sisällytä yksi numeerinen pisteytys 0–10.\n\n"
                  "KÄYTTÄJÄN SISÄLTÖ:\n" + content)
    else:
        identity = persona_to_identity(role)
        prompt = (
            "Read the user's content below and write ONE short paragraph as this persona reacting to it. "
            "If appropriate, include a single numeric score 0-10 for how convincing it is, in the text.\n\nUSER CONTENT:\n" + content
        )
    try:
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL","gpt-4o-mini"),
            messages=[
                {"role":"system","content":identity},
                {"role":"user","content":prompt}
            ],
            max_tokens=300,
            temperature=0.7,
        )
        text = resp.choices[0].message.content.strip()
    except Exception as e:
        text = f"(fallback) As {role.get('name','Reviewer')}: I have concerns but see some positives."
    score = extract_score(text)
    return text, score

@app.get("/submit")
def submit_content():
    return render_template("submit.html", title="Submit content")

@app.post("/submit")
def submit_content_post():
    content = (request.form.get("content") or "").strip()
    title = (request.form.get("title") or "").strip()
    if not content:
        flash(_t("Please paste your content text."))
        return redirect(url_for("submit_content"))

    population_id = session.get("population_id")
    run_id = create_run(session['sid'], population_id, content_text=content)
    session['run_id'] = run_id
    session['last_title'] = title  # pieni arvo, ok

    return redirect(url_for("chat"))

# --- News compare & suggestions ---
def fetch_news_articles(query: str, max_items: int = 5):
    try:
        from gnews import GNews
        locale = str(get_locale()) or 'fi'
        if locale.startswith('fi'):
            g = GNews(language="fi", country="FI", max_results=max_items)
        else:
            g = GNews(language="en", country="US", max_results=max_items)
        results = g.get_news(query)
        arts = []
        for it in results or []:
            arts.append({
                "title": it.get("title"),
                "publisher": (it.get("publisher") or {}).get("title",""),
                "published": it.get("published date",""),
                "url": it.get("url"),
            })
        return arts
    except Exception as e:
        # fallback: no news
        return []

def suggestions_from_news(user_text: str, articles: list[dict]) -> str:
    locale = str(get_locale()) or 'fi'
    # Use your provided main.generate_gpt_response to create suggestions
    if locale.startswith('fi'):
        identity = "Tehtäväsi on tunnistaa, mihin viimeaikaisiin keskustelunaiheisiin käyttäjän tuottama teksti liittyy"
        prompt = (
          "Tässä käyttäjän viesti:\n"
          f"{user_text}\n\n"
          "Tässä tuoreita aiheeseen liittyviä otsikoita:\n"
          + "\n".join([f"- {a['title']} ({a['publisher']})" for a in articles[:5]]) +
          "\n\nAnna 3–5 konkreettista ehdotusta..."
        )
    else:
        identity = "You are a communications strategist who reads recent news and suggests how to improve a message."
        summarized = "\n".join([f"- {a['title']} ({a['publisher']})" for a in articles[:5]])
        prompt = (
            "Here is the user's message:\n"
            f"{user_text}\n\n"
            "Here are recent related headlines:\n"
            f"{summarized or 'None'}\n\n"
            "Give 3–5 concrete suggestions to better align (or intentionally contrast) the message with the news cycle. "
            "Return plain text bullets."
        )
    try:
        txt = news_main.generate_gpt_response(identity, prompt, os.getenv("OPENAI_MODEL","gpt-4o-mini"))
        if hasattr(txt, "choices"):
            # In case their function returns an OpenAI response object; attempt to extract
            try:
                txt = txt.choices[0].message.content
            except Exception:
                txt = str(txt)
        return txt if isinstance(txt, str) else str(txt)
    except Exception as e:
        return "(suggestions temporarily unavailable)"

@app.get("/chat")
def chat():
    pid = session.get('population_id'); run_id = session.get('run_id')
    if not pid or not run_id:
        return redirect(url_for("index"))

    # Onko chat-viestejä jo?
    msgs = list_chat_messages(run_id)
    if not msgs:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        personas = get_personas_by_population_id(pid)
        # hae runin content DB:stä
        content = get_run_content(run_id)  # apuri, katso kohta 3
        for r in personas:
            txt, sc = reviewer_comment(client, r, content)
            insert_chat_message(run_id, r.get("name","Reviewer"), txt, score=sc)
        msgs = list_chat_messages(run_id)

    return render_template("chat.html", chat=msgs)

@app.get("/compare")
def compare_news():
    run_id = session.get('run_id')
    if not run_id:
        return redirect(url_for("index"))
    content = get_run_content(run_id)
    articles = fetch_news_articles(content[:140])
    suggestions = suggestions_from_news(content, articles)
    save_news_analysis(run_id, {"articles": articles, "suggestions": suggestions})
    return render_template("news_compare.html", articles=articles, suggestions=suggestions)

@app.get("/results")
def results():
    run_id = session.get('run_id')
    if not run_id:
        return redirect(url_for("index"))
    chat = list_chat_messages(run_id)
    scores = [m["score"] for m in chat if m.get("score") is not None]
    avg = round(sum(scores)/len(scores), 2) if scores else None
    summary = "\n".join([m["name"] + ": " + m["text"].split(". ")[0] + "." for m in chat[:5]])
    news = get_news_analysis(run_id) or {}
    return render_template("results.html", avg_score=avg, summary=summary, suggestions=news.get("suggestions",""))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
