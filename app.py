
import os, re, random
from datetime import datetime
from datetime import timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash

# Use your original package structure (no broad fallbacks)
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

def _(s): return s  # i18n shim

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret")

# Initialize DB once
setup_database()

# ---------------- Real Participants (DT files) ----------------
REAL_USERS_DIR = os.environ.get("REAL_USERS_DIR", "./DT")

def _ensure_dir(path: str):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

# Very small YAML front-matter parser: ---\nkey: val\n...\n---\n<body>
def _parse_front_matter(text: str) -> tuple[dict, str]:
    meta, body = {}, text
    if text.lstrip().startswith("---"):
        parts = text.lstrip().split("\n", 1)[1].split("\n---", 1)
        if len(parts) == 2:
            header, rest = parts
            for line in header.splitlines():
                line = line.strip()
                if not line or line.startswith("#"): 
                    continue
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            # Remove first trailing newline if present
            body = rest.lstrip("\n")
    return meta, body

def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def _write_text(path: str, s: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)

def _slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9\-_]+", "_", name.strip())
    return re.sub(r"_+", "_", s).strip("_").lower() or "participant"

def list_dt_files() -> list[dict]:
    """Return [{'filename', 'name', 'profile'} ...] for all DTs in REAL_USERS_DIR."""
    _ensure_dir(REAL_USERS_DIR)
    out = []
    for fn in os.listdir(REAL_USERS_DIR):
        if not fn.lower().endswith((".txt", ".md")):
            continue
        path = os.path.join(REAL_USERS_DIR, fn)
        try:
            raw = _read_text(path)
            meta, body = _parse_front_matter(raw)
            name = meta.get("name") or os.path.splitext(fn)[0]
            profile = meta.get("profile", "")
            out.append({"filename": fn, "name": name, "profile": profile, "path": path})
        except Exception:
            continue
    # stable order: by name then filename
    out.sort(key=lambda x: (x["name"].lower(), x["filename"].lower()))
    return out

def read_dt_file(filename: str) -> dict | None:
    """Return {'meta': {...}, 'body': '...', 'raw': '...', 'path': '...'} or None."""
    path = os.path.join(REAL_USERS_DIR, filename)
    if not os.path.isfile(path):
        return None
    raw = _read_text(path)
    meta, body = _parse_front_matter(raw)
    return {"meta": meta, "body": body, "raw": raw, "path": path}

def create_dt_file(name: str, profile: str, body: str) -> str:
    """Create a new DT file with YAML front matter. Returns the filename."""
    _ensure_dir(REAL_USERS_DIR)
    slug = _slugify(name)
    # Ensure uniqueness
    base = f"{slug}.md"
    fn = base
    i = 2
    while os.path.exists(os.path.join(REAL_USERS_DIR, fn)):
        fn = f"{slug}-{i}.md"; i += 1
    front = ["---", f"name: {name}", f"profile: {profile}", "---", ""]
    _write_text(os.path.join(REAL_USERS_DIR, fn), "\n".join(front) + body.strip() + "\n")
    return fn

# --- helpers to make plain-text DTs work well ---
_FIRST_SENTENCE_NAME_RE = re.compile(
    r"You\s+are\s+(?P<name>[A-Za-zÅÄÖåäö\- ]+)\s*,?\s+(?:a|an)?\s*[^.]*?\s+aged\s+\d{1,3}",
    re.IGNORECASE
)

def _infer_name_from_body(body: str, default_name: str) -> str:
    m = _FIRST_SENTENCE_NAME_RE.search(body or "")
    if m:
        return m.group("name").strip()
    # fallback: first word before comma or first 2 words
    head = (body or "").split(".", 1)[0]
    if "," in head:
        return head.split(",")[0].strip() or default_name
    return default_name

def prepare_gpt_contexts(run_text: str, selected_filenames: list[str]) -> list[dict]:
    """
    For each selected DT file, build a payload ready to send to GPT:
    - messages: [ {'role':'system','content':DT}, {'role':'user','content':run_text} ]
    - name: display label
    - filename: the DT filename
    """
    contexts = []
    for fn in selected_filenames:
        dt = read_dt_file(fn)  # returns {'meta':{}, 'body':..., 'raw':..., 'path':...}
        if not dt:
            continue

        meta, body, raw = dt.get("meta", {}), dt.get("body", ""), dt.get("raw", "")
        # Prefer explicit 'name' if you later add YAML front-matter; otherwise infer from body
        display_name = meta.get("name") or _infer_name_from_body(body, os.path.splitext(fn)[0])

        # If you want to add optional per-run “header” before the DT, do it here:
        # header = f"Context for this review: The following participant description remains authoritative.\n"
        # dt_text_for_system = header + raw
        dt_text_for_system = raw  # DT text already starts with "You are ...", which is ideal as a system prompt

        messages = [
            {"role": "system", "content": dt_text_for_system},
            {"role": "user", "content": run_text},
        ]

        contexts.append({
            "name": display_name,
            "filename": fn,
            "messages": messages,
            # keep 'content' too if your caller expects it:
            "content": raw,
        })
    return contexts

# ---------------- Helpers ----------------
def get_sid():
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

def fetch_news_articles(query: str, max_items: int = 6):
    """Optional dependency. No crash if gnews is missing."""
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
    query = " ".join(topics[:3])
    articles = fetch_news_articles(query, 6)
    negativity = any(k in text.lower() for k in ["irtisan", "hinta", "kriisi", "ongel", "vuoto", "riita", "koh"])
    positivity = any(k in text.lower() for k in ["paranee", "kasvu", "uusi", "lanse", "ennätys", "yhteistyö"])
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

# ---- Robust coercion for population rows (fix for tuple/dict/Row) ----
def _coerce_population_name(row) -> str:
    # SQLAlchemy Row: try mapping first
    m = getattr(row, "_mapping", None)
    if m and isinstance(m, dict):
        for key in ("name", "population_name", "pname"):
            if key in m and m[key]:
                return str(m[key])
    # dict row
    if isinstance(row, dict):
        for key in ("name", "population_name", "pname"):
            if key in row and row[key]:
                return str(row[key])
    # tuple/list row: (id, name, ...)
    if isinstance(row, (list, tuple)):
        if len(row) >= 2:
            return str(row[1])
        if len(row) == 1:
            return str(row[0])
    # object with .name attr
    if hasattr(row, "name"):
        try:
            val = getattr(row, "name")
            if val:
                return str(val)
        except Exception:
            pass
    # fallback
    return str(row)

def _get_population_names() -> list[str]:
    rows = get_all_populations() or []
    names = []
    for r in rows:
        nm = _coerce_population_name(r).strip()
        if nm and nm not in names:
            names.append(nm)
    return names

def _parse_published_dt(val):
    if not val:
        return None
    s = str(val)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    # last resort: try fromisoformat (may raise)
    try:
        return datetime.fromisoformat(s.replace("Z",""))
    except Exception:
        return None

def rank_articles(articles: list, topics: list[str]) -> list:
    """Pick and order the most relevant articles, preferring the last 14 days and topic overlap."""
    now = datetime.utcnow()
    horizon = now - timedelta(days=14)
    scored = []
    tset = [t.lower() for t in (topics or [])]
    for a in (articles or []):
        title = (a.get("title") or "").lower()
        score = sum(1 for t in tset if t and t in title)
        dt = _parse_published_dt(a.get("published"))
        # Filter out clearly old items when we can parse a date
        if dt and dt < horizon:
            continue
        # Prefer newer if available
        recency_bonus = 0
        if dt:
            recency_bonus = max(0, (dt - horizon).total_seconds() / (14 * 24 * 3600))  # 0..1
        scored.append((score + recency_bonus, a))
    scored.sort(key=lambda x: (-x[0], (x[1].get("published") or ""), (x[1].get("title") or "")))
    return [a for _, a in scored]

def summarize_topic_resonance(topics: list[str], snapshot: dict, text: str) -> str:
    """Lightweight heuristic summary for now (you can swap this to a GPT call later)."""
    tone = snapshot.get("tone") or "neutraali"
    tops = ", ".join(topics[:3]) if topics else "—"
    lines = []
    if tone == "myönteinen":
        lines.append("Kokonaiskuva: Mediasää on myönteinen — mahdollisuus vahvistaa viestin ydinteemoja.")
    elif tone == "kielteinen":
        lines.append("Kokonaiskuva: Mediasää on kriittinen — suosittelen rajaamaan lupauksia ja tuomaan todisteet näkyviin.")
    else:
        lines.append("Kokonaiskuva: Mediasää on neutraali — viesti voi omia agendan selkeällä kulmalla.")
    lines.append(f"Keskeiset teemat: {tops}")
    if topics:
        lines.append(f"Resonanssi: viesti osuu teemoihin '{topics[0]}' ja '{topics[1]}' (jos mainittu), "
                     "mutta varmista, että ingressi sanoo asian suoraan ensimmäisessä virkkeessä.")
    lines.append("Nopea parannus: lisää 1 konkreettinen datapiste ja CTA viimeiseen kappaleeseen.")
    return "\n".join(lines)

def estimate_resonance(text: str, pop_name: str, snapshot: dict):
    base = 60 + int(snapshot["sentiment"] * 30) + min(snapshot["volume"] // 30, 10)
    biases = {
        "Toimittajat": -5,
        "Pk-yrityspäättäjät": -2,
        "Sijoittajat": -3,
        "Korkeakoulutetut 25–44": +2,
        "Kriittinen kansalaisyleisö": -8,
        "Koko Suomi 18–65": 0,
    }
    score = max(0, min(100, base + biases.get(pop_name, 0)))
    decision = "GO" if score >= 70 else ("TWEAK" if score >= 50 else "NO-GO")
    conf = min(0.95, 0.4 + 0.01 * snapshot["volume"] + 0.03 * len(snapshot["topics"]))
    return score, decision, round(conf, 2)

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

# ---------------- Routes ----------------
@app.get("/")
def index():
    participants = list_dt_files()
    return render_template("index.html", _=_, title="Sointu", participants=participants)

@app.post("/analyze")
def analyze():

    # NEW: selected DTs from the form (file names)
    selected_dt_files = request.form.getlist("participants")  # list of filenames

    # Optionally persist choice for results page / next steps
    session["selected_dt_files"] = selected_dt_files

    # Prepare GPT contexts now (so you can call your GPT layer where you want)
    # You can also stash this into DB if preferred.
    # Read inputs BEFORE using them anywhere
    title = (request.form.get("title") or "").strip()
    content = (request.form.get("content") or "").strip()
    if not content:
        flash(_("Syötä sisältö ensin."))
        return redirect(url_for("index"))

    # Keep your original calling style (positional args) to avoid signature drift
    sid = get_sid()
    lang = (session.get("lang") or "fi").lower()
    get_or_create_user_session(sid, lang)
    gpt_contexts = prepare_gpt_contexts(content, selected_dt_files)
    session["gpt_contexts_count"] = len(gpt_contexts)

    run_id = create_run(sid, None, content_text=content, title=title or None)
    snapshot = build_mediasaa_snapshot(content)
    save_news_analysis(run_id, snapshot)

    target_audiences = []
    if selected_dt_files:
        # Use the DT “name” from file meta for display/scoring label
        for fn in selected_dt_files:
            dt = read_dt_file(fn)
            display_name = (dt and (dt["meta"].get("name") or fn)) or fn
            target_audiences.append(display_name)
    else:
        pops = _get_population_names() or [
            "Toimittajat","Pk-yrityspäättäjät","Sijoittajat",
            "Korkeakoulutetut 25–44","Kriittinen kansalaisyleisö","Koko Suomi 18–65"
        ]
        target_audiences = pops

    results = []
    for name in target_audiences:
        s, d, c = estimate_resonance(content, name, snapshot)
        results.append({"name": name, "score": s, "decision": d, "confidence": c})
    results.sort(key=lambda r: r["score"])

    session["current_run_id"] = run_id
    return redirect(url_for("results"))

@app.post("/participants/new")
def create_participant():
    name = (request.form.get("p_name") or "").strip()
    profile = (request.form.get("p_profile") or "").strip()
    body = (request.form.get("p_body") or "").strip()
    if not name or not body:
        flash(_("Anna vähintään nimi ja DT-teksti."))
        return redirect(url_for("index"))
    fn = create_dt_file(name, profile, body)
    flash(_("Luotu osallistuja: ") + name + f" ({fn})")
    return redirect(url_for("index"))

@app.get("/results")
def results():
    selected_dt_files = session.get("selected_dt_files") or []
    run_id = session.get("current_run_id")
    if not run_id:
        return redirect(url_for("index"))

    # 1) Load data from DB, not from session
    snapshot = get_news_analysis(run_id) or {}
    user_text = (get_run_content(run_id) or "").strip()
    target_audiences = []  # ensure defined for both branches

    # 2) Topics & news ranking
    topics = snapshot.get("topics", [])
    all_articles = snapshot.get("articles", []) or []

    # require this helper earlier in the file:
    # from datetime import timedelta
    # def rank_articles(...):  # already added in earlier step
    sorted_articles = rank_articles(all_articles, topics)

    show_more = request.args.get("more") == "1"
    articles_display = sorted_articles if show_more else sorted_articles[:3]
    has_more = len(sorted_articles) > 3

    # 3) Lightweight GPT-style summary (heuristic stub)
    # def summarize_topic_resonance(...):  # already added in earlier step
    topic_resonance = summarize_topic_resonance(topics, snapshot, user_text)

    # 4) Recompute population results on the fly (no session storage)
    if selected_dt_files:
        # Use the DT “name” from file meta for display/scoring label
        for fn in selected_dt_files:
            dt = read_dt_file(fn)
            display_name = (dt and (dt["meta"].get("name") or fn)) or fn
            target_audiences.append(display_name)
    else:
        pops = _get_population_names() or [
            "Toimittajat","Pk-yrityspäättäjät","Sijoittajat",
            "Korkeakoulutetut 25–44","Kriittinen kansalaisyleisö","Koko Suomi 18–65"
        ]
        target_audiences = pops

    results = []
    for name in target_audiences:
        s, d, c = estimate_resonance(user_text, name, snapshot)
        results.append({"name": name, "score": s, "decision": d, "confidence": c})
    results.sort(key=lambda r: r["score"])

    return render_template(
        "results.html",
        _=_,
        title="Sointu",
        user_text=user_text,
        topics=topics,
        articles=articles_display,
        has_more=has_more,
        show_more=show_more,
        topic_resonance=topic_resonance,
        snapshot=snapshot,
        results=results,
        selected_dt_files=selected_dt_files,
        gpt_contexts_count=session.get("gpt_contexts_count", 0),
    )

@app.post("/populations/new")
def add_population():
    name = (request.form.get("new_population") or "").strip()
    if not name:
        flash(_("Anna populaation nimi."))
        return redirect(url_for("results"))

    existing = [n.lower() for n in _get_population_names()]
    if name.lower() in existing:
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
    save_population(name, "FI", personas)

    # Rerun scoring
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

@app.get("/set_lang/<code>")
def set_lang(code):
    code = (code or "fi").lower()
    session["lang"] = code
    try:
        sid = session.get("sid")
        if sid:
            get_or_create_user_session(sid, code)
    except Exception:
        # non-fatal: still keep it in cookie-session
        pass
    flash(_("Kielivalinta tallennettu: ") + code.upper())
    return redirect(request.referrer or url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
