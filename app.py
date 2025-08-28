
import os, re, json
from flask import Flask, request, render_template, redirect, url_for, session, flash
from dotenv import load_dotenv
from openai import OpenAI
from flask_babel import get_locale, Babel, _

load_dotenv()

# Flask setup
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")
app.config['BABEL_DEFAULT_LOCALE'] = 'fi'
app.config['BABEL_SUPPORTED_LOCALES'] = ['fi', 'en']
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

babel = Babel(app)

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
    from flask import redirect, request, session, url_for
    if code in app.config['BABEL_SUPPORTED_LOCALES']:
        session['lang'] = code
    return redirect(request.referrer or url_for("index"))

# Imports from your provided modules (now in models/)
from models.generateParticipants import generate_role, get_age_attributes, get_gender_attributes
from models.generateParticipants import Persona
from models.db_utils import get_personas_by_population, save_persona_to_db, setup_database
from models.feedback import calculate_nps
from models import main as news_main

# Optional: initialize DB structure if DATABASE_URL is present
if os.getenv("DATABASE_URL"):
    try:
        setup_database()
    except Exception as e:
        print("DB setup skipped / failed:", e)

# Helper: extract first integer 0..10 from text
def extract_score(text):
    m = re.search(r"(10|[0-9])\b", text)
    return int(m.group(1)) if m else None

def ensure_state():
    session.setdefault("population_name", None)
    session.setdefault("reviewers", [])   # list of dicts
    session.setdefault("user_content", "")
    session.setdefault("chat", [])        # list of {name,text,score}
    session.setdefault("news", {"articles": [], "suggestions": ""})

@app.route("/")
def index():
    ensure_state()
    # Try to read existing populations from DB, else fallback empty
    existing = {}
    try:
        existing = get_personas_by_population() or {}
    except Exception as e:
        existing = {}
    return render_template("index.html", existing_populations=existing, title="Sointu — Select reviewers")

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
    ensure_state()
    pop = request.form.get("population_name") or ""
    if not pop:
        flash(_("Please choose a population or generate a new one."))
        return redirect(url_for("index"))
    # Load persons from DB
    try:
        populations = get_personas_by_population() or {}
        persons = populations.get(pop, [])
    except Exception as e:
        persons = []
    if not persons:
        flash(_("No personas found for that population. Generate a new one instead."))
        return redirect(url_for("index"))
    session["population_name"] = pop
    session["reviewers"] = persons
    return redirect(url_for("submit_content"))

@app.post("/generate_population")
def generate_population():
    ensure_state()
    name = request.form.get("new_population") or "Generated audience"
    location = request.form.get("location") or "Helsinki"
    try:
        size = max(1, min(20, int(request.form.get("size") or "5")))
    except:
        size = 5

    # Precompute attribute priors
    age_attr = get_age_attributes(name, location)
    gender_attr = get_gender_attributes(name, location)

    reviewers = []
    unique_names = set()
    for _ in range(size):
        persona = generate_role(name, location, age_attr, gender_attr, unique_names)
        reviewers.append(persona.dict() if hasattr(persona, "dict") else dict(persona))

        # Try to persist if DB is available
        try:
            save_persona_to_db(reviewers[-1], name)
        except Exception:
            pass

    session["population_name"] = name
    session["reviewers"] = reviewers
    flash(_(f"Generated {len(reviewers)} personas for population '{name}'."))
    return redirect(url_for("submit_content"))

@app.get("/submit")
def submit_content():
    ensure_state()
    return render_template("submit.html", title="Submit content")

@app.post("/submit")
def submit_content_post():
    ensure_state()
    session["user_content"] = (request.form.get("content") or "").strip()
    session["user_title"] = (request.form.get("title") or "").strip()
    if not session["user_content"]:
        flash(_("Please paste your content text."))
        return redirect(url_for("submit_content"))
    return redirect(url_for("chat"))

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

@app.get("/chat")
def chat():
    ensure_state()
    if not session["reviewers"] or not session.get("user_content"):
        return redirect(url_for("index"))
    # Generate one comment per reviewer (idempotent per session)
    if not session["chat"]:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        comments = []
        for r in session["reviewers"]:
            txt, sc = reviewer_comment(client, r, session["user_content"])
            comments.append({"name": r.get("name","Reviewer"), "text": txt, "score": sc})
        session["chat"] = comments
    return render_template("chat.html", chat=session["chat"], title="Reviewer chat")

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

@app.get("/compare")
def compare_news():
    ensure_state()
    if not session.get("user_content"): return redirect(url_for("submit_content"))
    articles = fetch_news_articles(session["user_content"][:140])
    sugg = suggestions_from_news(session["user_content"], articles)
    session["news"] = {"articles": articles, "suggestions": sugg}
    return render_template("news_compare.html", articles=articles, suggestions=sugg, title="News compare")

@app.get("/results")
def results():
    ensure_state()
    # average score
    scores = [c.get("score") for c in session.get("chat",[]) if c.get("score") is not None]
    avg = round(sum(scores)/len(scores), 2) if scores else None
    # Quick summary: join first sentences
    summary = "\n".join([c["name"] + ": " + c["text"].split(". ")[0] + "." for c in session.get("chat",[])[:5]])
    return render_template("results.html",
                           avg_score=avg,
                           summary=summary,
                           suggestions=session.get("news",{}).get("suggestions",""),
                           title="Results")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
