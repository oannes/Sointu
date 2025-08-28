import os
import json
import uuid
from contextlib import contextmanager
from dotenv import load_dotenv

from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, BigInteger, Text, DateTime,
    ForeignKey, func, select, String
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.dialects.postgresql import JSONB

# If you use Pydantic Persona elsewhere
try:
    from .generateParticipants import Persona  # optional typing aid
except Exception:
    Persona = dict  # fallback

# --- Environment / Engine / Session ---
load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]

# Heroku antaa usein postgres://, muutetaan SQLAlchemylle sopivaksi:
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base(metadata=MetaData(schema=None))  # default public schema

# --- Models ---
class Population(Base):
    __tablename__ = "populations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False, index=True, unique=True)
    location = Column(Text)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    personas = relationship("PersonaRow", back_populates="population", cascade="all, delete-orphan")


class PersonaRow(Base):
    __tablename__ = "personas"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    population_id = Column(Integer, ForeignKey("populations.id", ondelete="CASCADE"), index=True)

    # Core attributes (NOT NULL -> anna vähintään tyhjät arvot tallennettaessa)
    name = Column(Text, nullable=False)
    age = Column(Integer, nullable=False)
    gender = Column(Text, nullable=False)
    orientation = Column(Text, nullable=False)
    location = Column(Text, nullable=False)
    mbti_type = Column(Text, nullable=False)

    # Optional attributes
    occupation = Column(Text)
    education = Column(Text)
    income_level = Column(Text)
    financial_security = Column(Text)
    main_concern = Column(Text)
    source_of_joy = Column(Text)
    social_ties = Column(Text)
    values_and_beliefs = Column(Text)
    perspective_on_change = Column(Text)
    daily_routine = Column(Text)

    population = relationship("Population", back_populates="personas")


class Discussion(Base):
    __tablename__ = "discussions"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    population = Column(Text, nullable=False)  # string key preserved
    discussion_data = Column(JSONB, nullable=False)


class NpsResult(Base):
    __tablename__ = "nps_results"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    population = Column(Text, nullable=False)  # string key preserved
    nps_data = Column(JSONB, nullable=False)


# --- New models to keep state server-side ---
class UserSession(Base):
    __tablename__ = "user_sessions"
    id = Column(String, primary_key=True)  # uuid hex
    lang = Column(Text, default="en", nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class Run(Base):
    __tablename__ = "runs"
    id = Column(String, primary_key=True)  # uuid hex
    session_id = Column(String, ForeignKey("user_sessions.id", ondelete="CASCADE"), nullable=False)
    population_id = Column(Integer, ForeignKey("populations.id", ondelete="SET NULL"))
    content_text = Column(Text)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    session = relationship("UserSession")
    population = relationship("Population")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    persona_id = Column(Integer, ForeignKey("personas.id", ondelete="SET NULL"), nullable=True)
    author = Column(Text, nullable=False)  # 'persona' / 'system' / 'user' / tms.
    text = Column(Text, nullable=False)
    score = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    run = relationship("Run")
    persona = relationship("PersonaRow")


class NewsAnalysis(Base):
    __tablename__ = "news_analysis"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    result_json = Column(JSONB, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    run = relationship("Run")


# --- Session helper ---
@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# --- Schema management ---
def setup_database():
    """Create all tables idempotently."""
    Base.metadata.create_all(engine)


# --- Utility: get or create a Population by name ---
def _get_or_create_population(session, name: str, location: str | None = None) -> Population:
    pop = session.execute(select(Population).where(Population.name == name)).scalar_one_or_none()
    if pop:
        if location and not pop.location:
            pop.location = location
        return pop
    pop = Population(name=name, location=location)
    session.add(pop)
    session.flush()
    return pop


# --- Public API ---

def save_population(name, location, personas):
    """
    Create a population and insert given personas (list of objects/dicts).
    Returns population_id.
    """
    with get_session() as s:
        pop = _get_or_create_population(s, name=name, location=location)
        for p in personas:
            pdict = (
                p.model_dump() if hasattr(p, "model_dump")
                else (p.dict() if hasattr(p, "dict") else dict(p))
            )
            s.add(PersonaRow(
                population_id=pop.id,
                name=pdict.get("name") or "",
                age=int(pdict.get("age")) if pdict.get("age") is not None else 0,
                gender=pdict.get("gender") or "",
                orientation=pdict.get("orientation") or "",
                location=pdict.get("location") or "",
                mbti_type=pdict.get("mbti_type") or "",
                occupation=pdict.get("occupation"),
                education=pdict.get("education"),
                income_level=pdict.get("income_level"),
                financial_security=pdict.get("financial_security"),
                main_concern=pdict.get("main_concern"),
                source_of_joy=pdict.get("source_of_joy"),
                social_ties=pdict.get("social_ties"),
                values_and_beliefs=pdict.get("values_and_beliefs"),
                perspective_on_change=pdict.get("perspective_on_change"),
                daily_routine=pdict.get("daily_routine"),
            ))
        s.flush()
        return pop.id


def get_all_populations():
    """Return list of (id, name, location) ordered by created_at DESC."""
    with get_session() as s:
        rows = s.execute(
            select(Population.id, Population.name, Population.location)
            .order_by(Population.created_at.desc())
        ).all()
        return rows


def get_personas_by_population_id(population_id):
    """Return all persona dicts for a population_id."""
    with get_session() as s:
        rows = s.execute(
            select(PersonaRow).where(PersonaRow.population_id == population_id)
        ).scalars().all()
        return [{
            "id": r.id,
            "population_id": r.population_id,
            "name": r.name,
            "age": r.age,
            "gender": r.gender,
            "orientation": r.orientation,
            "location": r.location,
            "mbti_type": r.mbti_type,
            "occupation": r.occupation,
            "education": r.education,
            "income_level": r.income_level,
            "financial_security": r.financial_security,
            "main_concern": r.main_concern,
            "source_of_joy": r.source_of_joy,
            "social_ties": r.social_ties,
            "values_and_beliefs": r.values_and_beliefs,
            "perspective_on_change": r.perspective_on_change,
            "daily_routine": r.daily_routine,
        } for r in rows]


def save_discussion_data_to_db(population, discussion_data):
    with get_session() as s:
        row = Discussion(population=population, discussion_data=discussion_data)
        s.add(row)
        s.flush()
        return row.id


def get_discussion_data_from_db(discussion_id):
    with get_session() as s:
        row = s.get(Discussion, discussion_id)
        return row.discussion_data if row else None


def save_nps_results_to_db(population, nps_results):
    with get_session() as s:
        row = NpsResult(population=population, nps_data=nps_results)
        s.add(row)
        s.flush()
        return row.id


def get_nps_results_from_db(nps_id):
    with get_session() as s:
        row = s.get(NpsResult, nps_id)
        return row.nps_data if row else None


def save_persona_to_db(persona, population_name):
    """Save a single persona under population_name. Returns persona id."""
    with get_session() as s:
        pop = _get_or_create_population(s, name=population_name, location=None)
        if hasattr(persona, "model_dump"):
            pdata = persona.model_dump()
        elif hasattr(persona, "dict"):
            pdata = persona.dict()
        else:
            pdata = dict(persona)

        row = PersonaRow(
            population_id=pop.id,
            name=pdata.get("name") or "",
            age=int(pdata.get("age")) if pdata.get("age") is not None else 0,
            gender=pdata.get("gender") or "",
            orientation=pdata.get("orientation") or "",
            location=pdata.get("location") or "",
            mbti_type=pdata.get("mbti_type") or "",
            occupation=pdata.get("occupation"),
            education=pdata.get("education"),
            income_level=pdata.get("income_level"),
            financial_security=pdata.get("financial_security"),
            main_concern=pdata.get("main_concern"),
            source_of_joy=pdata.get("source_of_joy"),
            social_ties=pdata.get("social_ties"),
            values_and_beliefs=pdata.get("values_and_beliefs"),
            perspective_on_change=pdata.get("perspective_on_change"),
            daily_routine=pdata.get("daily_routine"),
        )
        s.add(row)
        s.flush()
        return row.id


def get_personas_by_population():
    """Return dict: { population_name: [ persona_dict, ... ], ... }"""
    with get_session() as s:
        rows = s.execute(
            select(
                Population.name.label("population"),
                PersonaRow.name,
                PersonaRow.age,
                PersonaRow.gender,
                PersonaRow.orientation,
                PersonaRow.location,
                PersonaRow.mbti_type,
                PersonaRow.occupation,
                PersonaRow.education,
                PersonaRow.income_level,
                PersonaRow.financial_security,
                PersonaRow.main_concern,
                PersonaRow.source_of_joy,
                PersonaRow.social_ties,
                PersonaRow.values_and_beliefs,
                PersonaRow.perspective_on_change,
                PersonaRow.daily_routine,
            ).join(PersonaRow, PersonaRow.population_id == Population.id)
        ).all()

        populations: dict[str, list[dict]] = {}
        for row in rows:
            pop_name = row.population
            persona = {
                "name": row.name,
                "age": row.age,
                "gender": row.gender,
                "orientation": row.orientation,
                "location": row.location,
                "mbti_type": row.mbti_type,
                "occupation": row.occupation,
                "education": row.education,
                "income_level": row.income_level,
                "financial_security": row.financial_security,
                "main_concern": row.main_concern,
                "source_of_joy": row.source_of_joy,
                "social_ties": row.social_ties,
                "values_and_beliefs": row.values_and_beliefs,
                "perspective_on_change": row.perspective_on_change,
                "daily_routine": row.daily_routine,
            }
            populations.setdefault(pop_name, []).append(persona)
        return populations


# --- Server-side session helpers (ORM versions) ---

def get_or_create_user_session(sid: str, lang: str | None = None):
    with get_session() as s:
        us = s.get(UserSession, sid)
        if not us:
            us = UserSession(id=sid, lang=lang or "en")
            s.add(us)
            s.flush()
        else:
            if lang:
                us.lang = lang
        return us.id

def create_run(sid: str, population_id: int | None, content_text: str | None):
    run_id = uuid.uuid4().hex
    with get_session() as s:
        r = Run(id=run_id, session_id=sid, population_id=population_id, content_text=content_text)
        s.add(r)
        s.flush()
        return r.id

def get_latest_run(sid: str):
    with get_session() as s:
        r = s.execute(
            select(Run).where(Run.session_id == sid).order_by(Run.created_at.desc()).limit(1)
        ).scalars().first()
        if not r:
            return None
        return {"id": r.id, "population_id": r.population_id, "content_text": r.content_text}

def add_chat_message(run_id: str, author: str, text: str, score: int | None = None, persona_id: int | None = None):
    with get_session() as s:
        m = ChatMessage(run_id=run_id, author=author, text=text, score=score, persona_id=persona_id)
        s.add(m)
        s.flush()
        return m.id

def get_chat_by_run(run_id: str):
    with get_session() as s:
        rows = s.execute(
            select(ChatMessage.author, ChatMessage.text, ChatMessage.score)
            .where(ChatMessage.run_id == run_id)
            .order_by(ChatMessage.created_at.asc())
        ).all()
        return [{"name": r.author, "text": r.text, "score": r.score} for r in rows]

def save_news_analysis(run_id: str, result_json: dict):
    with get_session() as s:
        na = NewsAnalysis(run_id=run_id, result_json=result_json)
        s.add(na)
        s.flush()
        return na.id