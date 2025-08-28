import json
import numpy as np
from collections import Counter

def simulate_responses_from_logprobs(completion_json, num_simulations=1000):
    """
    Simulate survey responses based on the log probabilities from GPT's completion.
    
    Args:
        completion_json (str): JSON dump of GPT's completion including logprobs.
        num_simulations (int): Number of simulated respondents.
        
    Returns:
        dict: Count of responses for each rating (0-9).
    """
    # Parse the JSON data
    completion_data = json.loads(completion_json)
    
    # Extract logprobs of the last character in the reply
    choices = completion_data["choices"]
    if not choices:
        raise ValueError("No choices found in completion JSON.")
    
    # Get logprobs of the last character
    logprobs = choices[0]["logprobs"]["top_logprobs"][-1]  # Last character's logprobs
    
    # Filter only numeric tokens (0-9)
    numeric_logprobs = {token: prob for token, prob in logprobs.items() if token.isdigit()}
    
    if not numeric_logprobs:
        raise ValueError("No numeric logprobs found.")
    
    # Convert logprobs to probabilities
    tokens = list(numeric_logprobs.keys())
    log_probs = np.array(list(numeric_logprobs.values()), dtype=np.float64)
    probabilities = np.exp(log_probs - np.max(log_probs))  # Normalize logprobs to probabilities
    probabilities /= probabilities.sum()  # Ensure they sum to 1

    # Simulate responses
    simulated_responses = np.random.choice(tokens, size=num_simulations, p=probabilities)
    
    # Count the occurrences of each rating
    response_counts = Counter(simulated_responses)
    return dict(response_counts)

# Example Usage
if __name__ == "__main__":
    # Simulated completion JSON (replace with real GPT response JSON)
    example_completion_json = """
    {
        "choices": [
            {
                "logprobs": {
                    "top_logprobs": [
                        {"0": 0.0, "1": -1.2, "2": -2.3, "3": -3.0, "4": -4.5},
                        {"0": -0.5, "1": -0.7, "2": -1.1, "3": -2.0, "4": -3.0}
                    ]
                }
            }
        ]
    }
    """
    
    # Simulate 1000 responses
    response_distribution = simulate_responses_from_logprobs(example_completion_json, num_simulations=10)
    print("Simulated Response Distribution:", response_distribution)
