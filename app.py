import os, re, random
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash

# Reuse your DB helper layer
from models.db_utils import (
    setup_database,
    get_all_populations,
    save_population,
    get_or_create_user_session,
    create_run,
    save_news_analysis,
    get_news_analysis,
    get_run_content,
)

# -------------- i18n shim --------------
def _(s): return s

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret")

# Ensure DB is initialized
setup_database()

# -------------- Helpers --------------
def get_sid():
    """Stable, anonymous session id for tying runs to a user."""
    if "sid" not in session:
        import uuid
        session["sid"] = uuid.uuid4().hex
    return session["sid"]

def extract_topics(text, k=6):
    words = re.findall(r"[A-Za-zÅÄÖåäö\-]{3,}", text.lower())
    stop = set((
        "the and for with this that from into your our you are was were been have has had not over under about "
        "when where which whose while shall will would could should may might can just very really more less than "
        "also only many much most least quite such like across per each any some every new old high low cost price "
        "impact climate data customer investor employee yritys asiakkaat markkina"
    ).split())
    freq = {}
    for w in words:
        if w in stop: 
            continue
        freq[w] = freq.get(w, 0) + 1
    topics = sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:k]
    return [t[0] for t in topics] or ["viesti", "kampanja"]

def fetch_news_articles(query: str, max_items: int = 5):
    """Try gnews if available; otherwise return empty list (MVP keeps working offline)."""
    try:
        from gnews import GNews
        g = GNews(language="fi", country="FI", max_results=max_items)
        results = g.get_news(query)
        arts = []
        for it in results or []:
            arts.append({
                "title": it.get("title"),
                "publisher": (it.get("publisher") or {}).get("title",""),
                "published": it.get("published date") or "",
                "url": it.get("url"),
            })
        return arts
    except Exception:
        return []

def build_mediasaa_snapshot(text: str) -> dict:
    topics = extract_topics(text, 6)
    # Query by top 2–3 topics joined for broader coverage
    query = " ".join(topics[:3])
    articles = fetch_news_articles(query, 6)
    # Heuristic sentiment/tone from keyword hints if no analyzer is present
    negativity = any(k in text.lower() for k in ["irtisan", "hinta", "kriisi", "ongel", "vuoto", "riita", "koh"])
    positivity = any(k in text.lower() for k in ["paranee", "kasvu", "uusi", "lanse", "ennätys", "yhteistyö"])
    # If we have articles, volume = len; otherwise synthetic 40–180
    volume = len(articles) if articles else random.randint(40, 180)
    sval = 0.0
    if negativity and not positivity: sval = -0.2
    if positivity and not negativity: sval = 0.2
    if positivity and negativity: sval = 0.0
    tone = "myönteinen" if sval > 0.1 else ("neutraali" if sval > -0.1 else "kielteinen")
    return {
        "query": query,
        "topics": topics,
        "sentiment": sval,
        "tone": tone,
        "volume": volume,
        "articles": articles,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }

def estimate_resonance(text: str, pop_name: str, snapshot: dict):
    """Population-level score -> decision & confidence (simple, explainable MVP)."""
    base = 60 + int(snapshot["sentiment"] * 30) + min(snapshot["volume"] // 30, 10)
    # Light, interpretable biases per preset name
    biases = {
        "Toimittajat": -5,
        "Pk-yrityspäättäjät": -2,
        "Sijoittajat": -3,
        "Korkeakoulutetut 25–44": +2,
        "Kriittinen kansalaisyleisö": -8,
        "Koko Suomi 18–65": 0,
    }
    score = max(0, min(100, base + biases.get(pop_name, 0)))
    if score >= 70: decision = "GO"
    elif score >= 50: decision = "TWEAK"
    else: decision = "NO-GO"
    conf = min(0.95, 0.4 + 0.01 * snapshot["volume"] + 0.03 * len(snapshot["topics"]))
    conf = round(conf, 2)
    return score, decision, conf

def tips_for_population(text: str, pop_name: str, snapshot: dict):
    top = snapshot.get("topics", [])[:3]
    tips = []
    if snapshot.get("tone") == "kielteinen":
        tips.append("Tunnista tämän hetken kriittinen kehys ja vastaa siihen alussa selkeästi.")
    if any(t in ("hinta","kustannus","inflaatio") for t in top):
        tips.append("Kerro konkreettinen euromääräinen hyöty/kustannusvaikutus kohderyhmälle.")
    if any(t in ("vastuullisuus","esg","ympäristö") for t in top):
        tips.append("Lisää todennettava mittari (lähde + luku) vastuullisuusväitteiden tueksi.")
    if pop_name.lower().startswith("toimittajat"):
        tips.append("Lisää datapiste ja linkki tausta-aineistoon (media briefing / FAQ).")
    if pop_name.lower().startswith("pk-"):
        tips.append("Korosta aikaa säästävää hyötyä ja riskit (mitä jos ei toimita?).")
    if pop_name.lower().startswith("sijoittajat"):
        tips.append("Avaa kassavirran/katteen mekanismi yhdellä luvulla.")
    if not tips:
        tips = ["Tiivistä ingressi kahteen virkkeeseen.", "Lisää selkeä CTA viimeiseen kappaleeseen."]
    return tips[:3]

# -------------- Routes --------------
@app.get("/")
def index():
    return render_template("index.html", _=_, title="Sointu")

@app.post("/analyze")
def analyze():
    title = (request.form.get("title") or "").strip()
    content = (request.form.get("content") or "").strip()
    if not content:
        flash(_("Syötä sisältö ensin."))
        return redirect(url_for("index"))

    sid = get_sid()
    lang = "fi"
    get_or_create_user_session(sid=sid, lang=lang)

    # Persist run & snapshot
    run_id = create_run(sid=sid, population_id=None, content_text=content, title=title or None)
    snapshot = build_mediasaa_snapshot(content)
    save_news_analysis(run_id, snapshot)

    # Load populations (DB) or fallback to a minimal list
    pops = [p["name"] for p in (get_all_populations() or [])]
    if not pops:
        pops = ["Toimittajat","Pk-yrityspäättäjät","Sijoittajat","Korkeakoulutetut 25–44","Kriittinen kansalaisyleisö","Koko Suomi 18–65"]

    # Score each population
    results = []
    for name in pops:
        s, d, c = estimate_resonance(content, name, snapshot)
        results.append({"name": name, "score": s, "decision": d, "confidence": c})
    results.sort(key=lambda r: r["score"])  # worst first

    # Stash in session for display
    session["current_run_id"] = run_id
    session["results"] = results
    return redirect(url_for("results"))

@app.get("/results")
def results():
    run_id = session.get("current_run_id")
    if not run_id:
        return redirect(url_for("index"))
    snapshot = get_news_analysis(run_id) or {}
    results = session.get("results", [])
    return render_template("results.html", _=_, snapshot=snapshot, results=results, title="Sointu")

@app.post("/populations/new")
def add_population():
    # Create a new population with 3 stub personas (fits your DB signature)
    name = (request.form.get("new_population") or "").strip()
    if not name:
        flash(_("Anna populaation nimi."))
        return redirect(url_for("results"))
    # Avoid duplicates (case-insensitive)
    existing = [p["name"] for p in (get_all_populations() or [])]
    if name.lower() in [e.lower() for e in existing]:
        flash(_("Populaatio on jo olemassa."))
        return redirect(url_for("results"))

    personas = [
        {"name": "Alex", "age": 35, "gender": "other", "orientation": "", "location": "FI",
         "mbti_type": "", "occupation": "", "education": "", "income_level": "", "financial_security": "",
         "main_concern": "", "source_of_joy": "", "social_ties": "", "values_and_beliefs": "",
         "perspective_on_change": "", "daily_routine": ""},
        {"name": "Mia", "age": 29, "gender": "female", "orientation": "", "location": "FI",
         "mbti_type": "", "occupation": "", "education": "", "income_level": "", "financial_security": "",
         "main_concern": "", "source_of_joy": "", "social_ties": "", "values_and_beliefs": "",
         "perspective_on_change": "", "daily_routine": ""},
        {"name": "Jussi", "age": 48, "gender": "male", "orientation": "", "location": "FI",
         "mbti_type": "", "occupation": "", "education": "", "income_level": "", "financial_security": "",
         "main_concern": "", "source_of_joy": "", "social_ties": "", "values_and_beliefs": "",
         "perspective_on_change": "", "daily_routine": ""},
    ]
    # save_population(name, location, personas)
    save_population(name=name, location="FI", personas=personas)

    # Re-score with the new population included
    run_id = session.get("current_run_id")
    snapshot = get_news_analysis(run_id) or {}
    content = (get_run_content(run_id) or "") if run_id else ""
    pops = [p["name"] for p in (get_all_populations() or [])]
    results = []
    for n in pops:
        s, d, c = estimate_resonance(content, n, snapshot)
        results.append({"name": n, "score": s, "decision": d, "confidence": c})
    results.sort(key=lambda r: r["score"])
    session["results"] = results
    return redirect(url_for("results"))

@app.get("/suggestions/<path:pop_name>")
def pop_suggestions(pop_name):
    run_id = session.get("current_run_id")
    if not run_id:
        return redirect(url_for("index"))
    snapshot = get_news_analysis(run_id) or {}
    content = (get_run_content(run_id) or "")
    tips = tips_for_population(content, pop_name, snapshot)
    return render_template("suggestions.html", _=_, pop_name=pop_name, tips=tips, title="Sointu")

# Keep route name compatible with your header links
@app.get("/set_lang/<code>")
def set_lang(code):
    flash(_("Kielivalinta tallennettu: ") + code.upper())
    return redirect(request.referrer or url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
