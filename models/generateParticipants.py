#generateParticipants.py
import os
import random
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import List, Optional, Tuple, Dict

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Constants
MAX_ROLES = int(os.getenv('NUM_ROLES', 10))
MAX_RETRY_ATTEMPTS = 3
MODEL = "gpt-4o-mini"

class GenderWeights(BaseModel):
    man: float
    woman: float
    other: float

class AgeAttributes(BaseModel):
    age_low: int
    age_high: int

# Define a structured output model using Pydantic
'''class ThemeAttributes(BaseModel):
    age_range: Tuple[int, int] 
    gender_weights: Dict[str, float] #maybe add gender weigths directly
'''
class Persona(BaseModel):
    id: Optional[int] = None
    name: str
    age: int
    gender: str
    orientation: str
    location: str
    mbti_type: str 
    occupation: Optional[str]
    education: Optional[str]
    income_level: Optional[str]
    financial_security: Optional[str]  # Financial security and outlook
    main_concern: Optional[str]  # Current main concern or worry
    source_of_joy: Optional[str]  # Source of joy or motivation
    social_ties: Optional[str]  # Social and community connections
    values_and_beliefs: Optional[str]  # Core personal values and beliefs
    perspective_on_change: Optional[str]  # Perspective on change and security
    daily_routine: Optional[str]  # Typical daily routine and habits
    attitude: Optional[str]
    
MBTI_TYPES = [
    ("ISFJ: You are introverted, sensing, feeling, and judging. You are nurturing, practical, and value harmony.", 0.12),
    ("ESFJ: You are extroverted, sensing, feeling, and judging. You are sociable, caring, and driven by the needs of others.", 0.11),
    ("ISTJ: You are introverted, sensing, thinking, and judging. You are responsible, organized, and value tradition.", 0.11),
    ("ISFP: You are introverted, sensing, feeling, and perceiving. You are artistic, gentle, and live in the moment.", 0.09),
    ("INFP: You are introverted, intuitive, feeling, and perceiving. You are idealistic, empathetic, and value authenticity.", 0.08),
    ("ESTJ: You are extroverted, sensing, thinking, and judging. You are logical, efficient, and enjoy taking charge.", 0.08),
    ("INFJ: You are introverted, intuitive, feeling, and judging. You are visionary, altruistic, and value meaningful connections.", 0.06),
    ("INTJ: You are introverted, intuitive, thinking, and judging. You are strategic, independent, and value competence.", 0.05),
    ("ENFP: You are extroverted, intuitive, feeling, and perceiving. You are enthusiastic, imaginative, and value personal growth.", 0.05),
    ("ESFP: You are extroverted, sensing, feeling, and perceiving. You are energetic, fun-loving, and enjoy living in the present.", 0.05),
    ("ENFJ: You are extroverted, intuitive, feeling, and judging. You are charismatic, inspiring, and enjoy guiding others.", 0.04),
    ("ISTP: You are introverted, sensing, thinking, and perceiving. You are analytical, adaptable, and enjoy hands-on activities.", 0.04),
    ("ESTP: You are extroverted, sensing, thinking, and perceiving. You are adventurous, pragmatic, and thrive in dynamic environments.", 0.04),
    ("INTP: You are introverted, intuitive, thinking, and perceiving. You are curious, logical, and enjoy exploring abstract concepts.", 0.03),
    ("ENTJ: You are extroverted, intuitive, thinking, and judging. You are ambitious and decisive.", 0.03),
    ("ENTP: You are extroverted, intuitive, thinking, and perceiving. You are innovative, witty, and thrive on intellectual challenges.", 0.02)
]

GROUP_ATTITUDE = [
    "Emphasize facts, data, and information. ('What do we know?')",
    "Emphasize feelings, emotions, and intuition. ('How do I feel about this?')",
    "Emphasize risks, weaknesses, and caution. ('What could go wrong?')",
    "Emphasize benefits and positive possibilities. ('What are the advantages?')",
    "Emphasize creativity, new ideas, and alternative solutions. ('What can we create?')",
    "Emphasize process and organization. ('How should we structure this?')"
]

def get_gender_attributes(population_name, location):
    identity = "You return plausible gender weights for a specific group in a location in JSON format. \n***Example*** If population is basketball players and location is Canada, you could reply with gender_weights=man: 0.6, woman: 0.38, other: 0.02; If group is 'retirement planning' and location Florida, you could reply with gender_weights=man: 0.48, woman: 0.48, other: 0.02. Consider carefully the gender weights of stereotypical groups or 10 participants of the selected group."
    prompt = f"Generate a plausible gender weights for a group of '{population_name}' in {location}."
        
    messages = [
        {"role": "system", "content": identity},
        {"role": "user", "content": prompt}
    ]
    
    for _ in range(MAX_RETRY_ATTEMPTS):
        try:
            completion = client.beta.chat.completions.parse(
                model=MODEL,
                messages=messages,
                response_format=GenderWeights  # Use Pydantic model for structured output
            )
            # Extract and return the parsed persona
            #print(completion.choices[0].message.parsed)
            return completion.choices[0].message.parsed
        
        except Exception as e:
            print(f"Error generating bg attributes: {e}")
    
            return GenderWeights(
                gender_weights={"man": 0.49, "woman": 0.49, "other": 0.02})  


def get_age_attributes(population_name, location):
    identity = "You return plausible upper and lower age range for a specific group in a location in JSON format by replying with two numbers in the format of AgeAttributes(BaseModel): age_range: Tuple[int, int]. \n***Example*** If population provided to you is basketball players and location is Canada, you could reply with age range= 7, 38. If group is 'retirement planning' and location Florida, you could reply with age_range=59, 87"
    prompt = f"Generate a plausible age range for a group of '{population_name}' in {location}."
        
    messages = [
        {"role": "system", "content": identity},
        {"role": "user", "content": prompt}
    ]
    
    for _ in range(MAX_RETRY_ATTEMPTS):
        try:
            completion = client.beta.chat.completions.parse(
                model=MODEL,
                messages=messages,
                response_format=AgeAttributes  # Use Pydantic model for structured output
            )
            # Extract and return the parsed persona
            return completion.choices[0].message.parsed
        
        except Exception as e:
            print(f"Error generating bg attributes: {e}")
    
            return AgeAttributes(
                age_range=(15, 75),  # Middle age, suitable for general contexts
                )  

def generate_role(population_name, location, age_attributes=None, gender_weights=None, unique_names=None):

    if age_attributes:
        age = random.randint(age_attributes.age_low, age_attributes.age_high)
    else:
        age = random.randint(18, 65)
    
    if gender_weights:
        gender = random.choices(
            ["man", "woman", "other"],
            weights=[gender_weights.man, gender_weights.woman, gender_weights.other]
        )[0]
    else:
        gender = random.choice(["man", "woman"])

    name = None
    # Fetch the name lists from the session
    if unique_names and gender in unique_names and unique_names[gender]:
        # Pop a name from the list
        name = unique_names[gender].pop(0)
    else:
        name = "Anonymous"

    orientation = random.choices(["heterosexual", "homosexual", "bisexual", "other"], weights=[0.91, 0.06, 0.02, 0.01])[0]
    mbti_type = random.choices([t[0] for t in MBTI_TYPES], weights=[t[1] for t in MBTI_TYPES])[0]

    attitude = random.choice(GROUP_ATTITUDE)
    mbti_type = f"{mbti_type}. In a group discussion, you {attitude}."

    # Get a structured persona from OpenAI
    persona = openai_generate_persona(population_name, age, gender, orientation, location, mbti_type, attitude, name=name)
    persona.age = age
    persona.gender = gender
    persona.orientation = orientation
    persona.mbti_type = mbti_type
    persona.attitude = attitude
    return persona

def openai_generate_persona(population_name, age, gender, orientation, location, mbti_type, attitude, name):
    identity = "You describe detailed personas for a computer game that represent a {population_name} in {location} in JSON format."
    prompt = (
        f"Generate a plausible persona that is '{population_name}' in {location} "
        f"A suggested name for the person is {name}, but you can change this if it is not plausible. The person is {gender}, {orientation}, and {age} years old. The person has an MBTI personality type of {mbti_type} and attitude in group is {attitude}."
        "Consider what motivates the person. Describe each by one paragraph the following details: their occupation, education, income level, their financial outlookm current main concern, what gives them joy, their connections with friends or community, their core values and beliefs, how they feel about change and security, and some aspects of their typical daily routine."
    )
    messages = [
        {"role": "system", "content": identity},
        {"role": "user", "content": prompt}
    ]
    
    for _ in range(MAX_RETRY_ATTEMPTS):
        try:
            completion = client.beta.chat.completions.parse(
                model=MODEL,
                messages=messages,
                temperature=0.9,
                response_format=Persona  # Use Pydantic model for structured output
            )
            # Extract and return the parsed persona
            return completion.choices[0].message.parsed
        except Exception as e:
            print(f"Error generating persona: {e}")
    
    # Return a fallback persona if GPT fails
    return Persona(name="Fallback Persona", age=age, gender=gender, orientation=orientation)


def realistic_age_distribution():
    age_bins = [
        (0, 14, 0.00),
        (15, 24, 0.12),
        (25, 54, 0.39),
        (55, 64, 0.13),
        (65, 74, 0.10),
        (75, 100, 0.09)
    ]
    age_bin = random.choices(age_bins, weights=[b[2] for b in age_bins])[0]
    return random.randint(age_bin[0], age_bin[1])

def generate_age():
    return realistic_age_distribution()


