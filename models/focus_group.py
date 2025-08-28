from flask import Flask, request, jsonify
import random
import os
from .db_utils import get_personas_by_population
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# Initialize OpenAI client
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
client = OpenAI(api_key=OPENAI_API_KEY)

@app.route('/get_reply', methods=['POST'])
def get_reply():
    data = request.json
    population_name = data.get('population')  # Get the specified population
    previous_messages = data.get('previous_messages', [])

    # Retrieve all personas by population from the database
    populations = get_personas_by_population()
    
    # Ensure the specified population exists
    if population_name not in populations:
        return jsonify({"error": "Specified population not found"}), 404

    # Select a random persona from the specified population group
    role = random.choice(populations[population_name])

    # Construct persona description for GPT prompt
    role_description = (
        f"Name: {role.get('name', 'Unknown')}, Age: {role.get('age', 'Unknown')}, Gender: {role.get('gender', 'Unknown')}, "
        f"Orientation: {role.get('orientation', 'Unknown')}, Location: {role.get('location', 'Unknown')}, MBTI Type: {role.get('mbti_type', 'Unknown')}, "
        f"Occupation: {role.get('occupation', 'Unknown')}, Education: {role.get('education', 'Unknown')}, Income Level: {role.get('income_level', 'Unknown')}, "
        f"Financial Security: {role.get('financial_security', 'Unknown')}, Main Concern: {role.get('main_concern', 'Unknown')}, "
        f"Source of Joy: {role.get('source_of_joy', 'Unknown')}, Social Ties: {role.get('social_ties', 'Unknown')}, "
        f"Values and Beliefs: {role.get('values_and_beliefs', 'Unknown')}, Perspective on Change: {role.get('perspective_on_change', 'Unknown')}, "
        f"Daily Routine: {role.get('daily_routine', 'Unknown')}"
    )

    # Prepare the prompt for GPT
    prompt = (
        f"{role_description}\n"
        "You are talking in a room with people you don't know. You discuss with a style that is typical to you.\n"
        "Recent discussion to which you reply to:\n"
        + "\n".join(previous_messages[-5:])  # Only send the last 5 messages
        + "\nYour reply:"
    )

    try:
        # Make the OpenAI API call
        response = client.Completion.create(
            model="gpt-4",
            prompt=prompt,
            max_tokens=50,
            stop=["\n"]
        )
        reply = response.choices[0].text.strip()
        return jsonify({"reply": reply, "persona_name": persona['name']})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
