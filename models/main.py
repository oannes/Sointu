import os
import csv
import feedparser
import smtplib
from email.mime.text import MIMEText
from openai import OpenAI
import logging
import json
from datetime import datetime, timedelta
import time
import re

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# ============ ASETUKSET ============
RSS_FEED_URLS = [
    "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET&concepts=18-34837",
    "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET&concepts=18-19274",
    "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET&concepts=18-38033",
    "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET&concepts=18-35138",
    "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET&concepts=18-147345",
    "https://www.hs.fi/rss/tuoreimmat.xml"
]

PROCESSED_FILE = "processed_links.txt"

SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS', 'oma.sahkoposti@gmail.com')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', 'salasana')

RECIPIENT_ADDRESS = os.environ.get('RECIPIENT_ADDRESS', 'johannesreadinglist@gmail.com')
RECIPIENT_ADDRESSES = ["johannesreadinglist@gmail.com", "henrik.vuornos@gmail.com"]

FASTMODEL = "gpt-4o-mini"
GOODMODEL = "gpt-4o"

# ============ FUNKTIOT ============

def generate_gpt_response(identity, prompt, model):
    messages = [
        {"role": "system", "content": identity},
        {"role": "user", "content": prompt},
    ]
    
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=14000,
            temperature=0.7,
            timeout=120
        )
        response_text = completion.choices[0].message.content
        return response_text
    except Exception as e:
        print(f"Error in generate_gpt_response with prompt: {prompt}")
        print(f"Error details: {e}")
        return None

def send_email(subject, body, recipients):
    """Lähettää sähköpostin SMTP:n kautta."""
    if isinstance(recipients, str):  # Allow a single email as a string
        recipients = [recipients]
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = ", ".join(recipients)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg)
        print(f"Sähköposti lähetetty seuraaville osoitteille: {', '.join(recipients)}")
    except Exception as e:
        print(f"Virhe lähettäessä sähköpostia: {e}")

def load_processed_links(file_path):
    """Lue käsitellyt linkit tiedostosta."""
    if not os.path.exists(file_path):
        return set()
    with open(file_path, 'r', encoding='utf-8') as f:
        links = f.read().splitlines()
    # Filter out lines that might be comments (like # Updated on ...)
    return {line for line in links if line and not line.startswith('#')}

def reset_processed_links(file_path):
    """Tyhjennä käsitellyt linkit tiedostosta."""
    open(file_path, 'w').close()

def save_processed_links(file_path, links):
    try:
        # Lue olemassa olevat linkit tiedostosta
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                old = f.read().splitlines()
        else:
            old = []
    except FileNotFoundError:
        old = []

    # Poista kommentti-rivit ja kerää vain varsinaiset linkit
    old = [line for line in old if line and not line.startswith('#')]

    # Merge the old + new link sets
    merged = list(dict.fromkeys(old + list(links)))
    
    # Säilytä vain viimeiset 100 linkkiä
    merged = merged[-100:]
    
    # Lopuksi lisää kommenttirivi aikaleimalla
    merged.append(f"# Updated on {datetime.now().isoformat()}")

    # Tallenna
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write("\n".join(merged))

def load_identity_template(file_path):
    """Lataa identiteettiteksti/tiedotetemplate tiedostosta."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"Virhe: Tiedostoa {file_path} ei löydy.")
        return "You are media assistant to a politician."

def load_tweet_sample(file_path):
    """Lataa tweet sample tiedostosta."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"Virhe: Tiedostoa {file_path} ei löydy.")
        return ""

def parse_all_feeds():
    """
    Pulls articles from all RSS_FEED_URLS. Returns a sorted list of feed entries (newest first).
    """
    all_entries = []
    for rss_url in RSS_FEED_URLS:
        feed = feedparser.parse(rss_url)
        if feed.bozo:
            print(f"RSS-feedin nouto epäonnistui: {rss_url}")
            continue
        all_entries.extend(feed.entries)
    all_entries.sort(key=lambda entry: entry.get("published_parsed", 0), reverse=True)
    return all_entries

def process_politician(
    politician_file, 
    recipient_addresses, 
    old_processed_links, 
    all_entries, 
    tweet_sample_file,    # NEW
    press_sample_file     # NEW
):
    """
    - Skips any article in 'old_processed_links' (from prior runs).
    - Checks new articles with GPT. Possibly sends an email.
    - Returns the set of links that were processed for this politician (in this run).
    """

    newly_processed = set()

    # Load politician JSON
    with open(politician_file, "r", encoding="utf-8") as f:
        profile_text = json.load(f)

    # Load the tweet sample and press release sample for THIS politician
    tweet_example = load_tweet_sample(tweet_sample_file)       # CHANGED
    press_release_example = load_identity_template(press_sample_file)  # CHANGED

    # We'll skip certain substrings
    SKIP_SUBSTRINGS = ["/maailma/", "/urheilu/", "/taide/", "/muistot/"]
    one_hour_ago = time.mktime((datetime.now() - timedelta(hours=1)).timetuple())

    potential_drafts = []

    for entry in all_entries:
        link = entry.link
        title = entry.title
        summary = getattr(entry, 'summary', '')

        # Skip if processed in a previous run
        if link in old_processed_links:
            continue
        
        # Skip undesired paths
        if any(skip in link for skip in SKIP_SUBSTRINGS):
            continue

        # Skip if older than 1 hour
        published_time = entry.get("published_parsed")
        if published_time and time.mktime(published_time) < one_hour_ago:
            continue

        # GPT check
        check_identity = (
             "You are a highly selective media assistant to a politician. "
            "Your job is to identify only the most extraordinary news opportunities for the politician, "
            "whose opinions are provided to you, to make a press release. "
            "You reply with the word INAPPLICABLE unless the news article is an outstanding opportunity for this particular politician "
            "and potential press release from the politician to this piece of news directly aligns with the politician's primary policy focus and is likely to generate "
            "significant positive media attention and public engagement. "
            "If such an rare opportunity exists, you reply RELEVANT [explanation in Finnish]."
        )
        check_prompt = f"""
        Politician profile:
        {profile_text}

        News article:
        Title: {title}
        Summary: {summary}

            "Evaluate the article's relevance to the politician's core priorities and strategic goals 
            on a scale of 1 to 5, where 1 is irrelevant, 2 is moderately relevant, 3 is relevant, 4 is very relevant and 5 is an extraordinary 
            opportunity with extraordinarily high public and media impact. If the score is 1–4, reply INAPPLICABLE. 
            Only reply RELEVANT with a concise justification in Finnish if the score is 5 out of 5, 
            representing a news opportunity that is unmissable and aligns directly with the politician's strategic interests.".
        """

        gpt_check_response = generate_gpt_response(check_identity, check_prompt, FASTMODEL)
        print("\nCheck response:\n", gpt_check_response, "\n")

        # Mark link processed in THIS run, so it won't be shown next run
        newly_processed.add(link)

        # Check if GPT says RELEVANT
        if gpt_check_response and "RELEVANT" in gpt_check_response.upper():
            match = re.search(r'\bRELEVANT\b\s*(.*)', gpt_check_response, re.IGNORECASE | re.DOTALL)
            explanation = match.group(1).strip() if match else "Ei selitystä."

            # Create Press Release
            press_identity = (
                f"You are media assistant to a politician. "
                f"You create press releases in Finnish that are structured similarly to these samples: \n{press_release_example}."
            )
            press_prompt = f"""
            You write this press release because {explanation}.
            Politician profile:
            {profile_text}

            News article:
            Title: {title}
            Summary: {summary}

            Create a press release in Finnish about the politician’s additional comments 
            on this news item. Keep it fairly short but newsworthy.
            """
            press_release = generate_gpt_response(press_identity, press_prompt, GOODMODEL)

            # Create Tweet
            tweet_identity = (
                f"You are media assistant to a politician. You write tweets for them."
                f"You create max 260 character tweets in Finnish that are structured similarly to: \n{tweet_example}"
            )
            tweet_prompt = f"""
            You write this tweet because {explanation}.
            \n\nFollowing a news article '{title}' at {link}, create a tweet the politician can use themself. It needs to focus on one thing and be very concrete, for example a novel policy proposal."
            """
            tweet = generate_gpt_response(tweet_identity, tweet_prompt, GOODMODEL)

            if press_release:
                subject = f"Uusi HOKSNOKKA-tiedote: {title}"
                body = (
                    f"Otsikko: {title}\n"
                    f"Linkki: {link}\n\n"
                    f"Miksi nyt kannattaa reagoida: \n{explanation}\n\n"
                    "- - - - - 8< - - -\n\n"
                    f"Hoksnokka-pressitiedote:\n{press_release}\n"
                    "- - - - - 8< - - -\n\n"
                    f"Some-viesti:\n{tweet}\n\n"
                )
                potential_drafts.append({
                    "subject": subject,
                    "body": body,
                    "explanation": explanation,
                    "link": link,
                    "title": title
                })

    # Decide which draft (if any) we send
    if not potential_drafts:
        print("No potential drafts found.")
        return newly_processed

    list_of_drafts_str = ""
    for i, draft in enumerate(potential_drafts, start=1):
        list_of_drafts_str += (
            f"Draft {i}:\n"
            f"  Title: {draft['title']}\n"
            f"  Explanation: {draft['explanation']}\n\n"
        )

    best_email_identity = (
        "You are media assistant to a politician. "
        "Your job is to make sure the politician does not send unnecessary press releases. "
        "You have been given one or multiple possible press releases along with an 'explanation' for why "
        "they might be relevant. Carefully consider if any explanation is compelling enough. "
        "Only respond with one integer: "
        "   - the number of the best draft (1, 2, 3, ...) if it is worth sending\n"
        "   - or respond with 0 if none are strong enough to justify sending a press release."
        "A press release is worth sending only if a) it brings something new and helpful to the public discussion; b) helps politician significantly to get re-elected; and c) positions politician as a person with brilliant, concrete ideas."
    )
    best_email_prompt = f"""
   We have {len(potential_drafts)} potential explanations to send a press release. Each has:
    - An explanation number
    - A short explanation in Finnish why it might be worth reacting
    Decide which one is the MOST relevant (if any).
    If none of them is excellent, respond with 0.
    {list_of_drafts_str}
    Answer with just one explanation number (e.g. '1' or '0').
    No extra text beyond that single integer.
    """

    best_draft_response = generate_gpt_response(best_email_identity, best_email_prompt, FASTMODEL)
    print("GPT picked press release draft number:\n", best_draft_response)

    if best_draft_response:
        try:
            best_draft_index = int(best_draft_response.strip())
        except ValueError:
            best_draft_index = 0
        if 1 <= best_draft_index <= len(potential_drafts):
            chosen_draft = potential_drafts[best_draft_index - 1]
            send_email(chosen_draft["subject"], chosen_draft["body"], recipient_addresses)
        else:
            print("GPT decided none is worth sending (or invalid).")
    else:
        print("No valid GPT response for best draft. Skipping email send.")

    return newly_processed


def main():
    # 1) Load old processed links
    old_processed_links = load_processed_links(PROCESSED_FILE)
    newly_processed_links = set()

    # 2) Parse feeds once
    all_entries = parse_all_feeds()

    # 3) Iterate over CSV rows
    with open("subscribers.csv", "r", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            politician_file = row["politician_file"].strip()
            emails_raw = row["email_addresses"].strip()
            recipient_addresses = [addr.strip() for addr in emails_raw.split(",")]
            tweet_sample_file = row.get("tweet_sample_file", "").strip()
            press_sample_file = row.get("press_sample_file", "").strip()  

            print(f"\n=== PROCESSING {politician_file} FOR {recipient_addresses} ===\n")
            processed_for_this_pol = process_politician(
                politician_file,
                recipient_addresses,
                old_processed_links,  # we skip if in old links
                all_entries,
                tweet_sample_file,   # pass in the tweet sample
                press_sample_file    # pass in the press release sample
            )
            # Union them
            newly_processed_links |= processed_for_this_pol

    # 4. After all politicians, update the global processed links
    all_processed = old_processed_links | newly_processed_links
    save_processed_links(PROCESSED_FILE, all_processed)
    print("\n=== All done for all politicians. ===\n")

if __name__ == "__main__":
    main()