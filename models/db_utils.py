#db_utils.py

import os
import psycopg2
from dotenv import load_dotenv
from contextlib import contextmanager
from .generateParticipants import Persona
import json
from sqlalchemy import create_engine


engine = create_engine(os.environ["DATABASE_URL"])

# Load environment variables
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

@contextmanager
def get_db_connection():
    """Context manager for database connection."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()

def setup_database():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS populations (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                location TEXT,
                created_at TIMESTAMP DEFAULT now()
            );
        """)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS personas (
                id SERIAL PRIMARY KEY,
                population_id INT REFERENCES populations(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                age INTEGER NOT NULL,
                gender TEXT NOT NULL,
                orientation TEXT NOT NULL,
                location TEXT NOT NULL,
                mbti_type TEXT NOT NULL,
                occupation TEXT,
                education TEXT,
                income_level TEXT,
                financial_security TEXT,
                main_concern TEXT,
                source_of_joy TEXT,
                social_ties TEXT,
                values_and_beliefs TEXT,
                perspective_on_change TEXT,
                daily_routine TEXT,
            )
        ''')
        # New table for discussion data
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS discussions (
                id SERIAL PRIMARY KEY,
                population TEXT NOT NULL,
                discussion_data JSONB NOT NULL
            )
        ''')

        # New table for NPS results
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS nps_results (
                id SERIAL PRIMARY KEY,
                population TEXT NOT NULL,
                nps_data JSONB NOT NULL
            )
        ''')
        conn.commit()

def save_population(name, location, personas):
    with get_connection() as conn:
        with conn.cursor() as cur:
            # create population
            cur.execute(
                "INSERT INTO populations (name, location) VALUES (%s, %s) RETURNING id",
                (name, location)
            )
            population_id = cur.fetchone()[0]

            # insert personas
            for p in personas:
                cur.execute("""
                    INSERT INTO personas (
                        population_id, name, age, gender, occupation, education,
                        income_level, financial_security, main_concern, source_of_joy,
                        social_ties, values_and_beliefs, perspective_on_change, daily_routine
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    population_id, p.name, p.age, p.gender, p.occupation, p.education,
                    p.income_level, p.financial_security, p.main_concern, p.source_of_joy,
                    p.social_ties, p.values_and_beliefs, p.perspective_on_change, p.daily_routine
                ))
        conn.commit()
    return population_id

def get_all_populations():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, location FROM populations ORDER BY created_at DESC")
            return cur.fetchall()

def get_personas_by_population_id(population_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM personas WHERE population_id=%s", (population_id,))
            return cur.fetchall()

def save_discussion_data_to_db(population, discussion_data):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO discussions (population, discussion_data)
            VALUES (%s, %s)
            RETURNING id
        ''', (population, json.dumps(discussion_data)))
        discussion_id = cursor.fetchone()[0]
        conn.commit()
    return discussion_id

def get_discussion_data_from_db(discussion_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT discussion_data FROM discussions WHERE id = %s
        ''', (discussion_id,))
        result = cursor.fetchone()
    if result:
        return result[0]
    else:
        return None

#### **For `nps_results`:**

# db_utils.py

def save_nps_results_to_db(population, nps_results):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO nps_results (population, nps_data)
            VALUES (%s, %s)
            RETURNING id
        ''', (population, json.dumps(nps_results)))
        nps_id = cursor.fetchone()[0]
        conn.commit()
    return nps_id

def get_nps_results_from_db(nps_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT nps_data FROM nps_results WHERE id = %s
        ''', (nps_id,))
        result = cursor.fetchone()
    if result:
        return result[0]
    else:
        return None
    
def save_persona_to_db(persona, population_name):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Ensure persona is a dictionary
        if isinstance(persona, Persona):
            persona = persona.model_dump()


        cursor.execute('''
            INSERT INTO personas (
                name, age, gender, orientation, location, mbti_type,
                occupation, education, income_level, financial_security,
                main_concern, source_of_joy, social_ties, values_and_beliefs,
                perspective_on_change, daily_routine, population
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            persona.get("name"),
            persona.get("age"),
            persona.get("gender"),
            persona.get("orientation"),
            persona.get("location"),
            persona.get("mbti_type"),
            persona.get("occupation"),
            persona.get("education"),
            persona.get("income_level"),
            persona.get("financial_security"),
            persona.get("main_concern"),
            persona.get("source_of_joy"),
            persona.get("social_ties"),
            persona.get("values_and_beliefs"),
            persona.get("perspective_on_change"),
            persona.get("daily_routine"),
            population_name
        ))
        assigned_id = cursor.fetchone()[0]
        conn.commit()
    return assigned_id

def get_personas_by_population():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT population, name, age, gender, orientation, location, mbti_type,
                   occupation, education, income_level, financial_security,
                   main_concern, source_of_joy, social_ties, values_and_beliefs,
                   perspective_on_change, daily_routine
            FROM personas
        ''')
        rows = cursor.fetchall()

        # Organize results by population
        populations = {}
        for row in rows:
            population = row[0]
            persona = {
                "name": row[1],
                "age": row[2],
                "gender": row[3],
                "orientation": row[4],
                "location": row[5],
                "mbti_type": row[6],
                "occupation": row[7],
                "education": row[8],
                "income_level": row[9],
                "financial_security": row[10],
                "main_concern": row[11],
                "source_of_joy": row[12],
                "social_ties": row[13],
                "values_and_beliefs": row[14],
                "perspective_on_change": row[15],
                "daily_routine": row[16]
            }
            if population not in populations:
                populations[population] = []
            populations[population].append(persona)

        return populations

def print_personas_from_db(fields=["name", "age", "location", "occupation"]):
    """Prints specified fields from personas in the database."""
    field_names = ", ".join(fields)
    query = f"SELECT {field_names} FROM personas"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
    
    print("Generated Personas:")
    for row in rows:
        print(", ".join(f"{field}: {value}" for field, value in zip(fields, row)))
