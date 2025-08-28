# Sointu

This is a simple Flask application designed to be deployed on Heroku.
It returns a friendly greeting at the root URL (`/`).

## Structure

- `app.py` — the main Flask application. It defines a single route `/` that returns "Hello, Sointu!".
- `requirements.txt` — lists the Python dependencies (`Flask` and `gunicorn`) required by the application.
- `Procfile` — tells Heroku how to run the application using `gunicorn`.
- `runtime.txt` — specifies the Python runtime version for Heroku.

## Deployment

1. Push the code to GitHub.
2. Create a Heroku app (region: EU) and link it to your GitHub repository.
3. Enable automatic deploys or manually trigger a deploy from the `main` branch.

Your app should be up and running on Heroku once the deployment finishes.
