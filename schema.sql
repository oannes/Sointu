-- populations table
CREATE TABLE populations (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT,
    created_at TIMESTAMP DEFAULT now()
);

-- personas table
CREATE TABLE personas (
    id SERIAL PRIMARY KEY,
    population_id INT REFERENCES populations(id) ON DELETE CASCADE,
    name TEXT,
    age INT,
    gender TEXT,
    occupation TEXT,
    education TEXT,
    income_level TEXT,
    financial_security TEXT,
    main_concern TEXT,
    source_of_joy TEXT,
    social_ties TEXT,
    values_and_beliefs TEXT,
    perspective_on_change TEXT,
    daily_routine TEXT
);