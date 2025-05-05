import requests


GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent"
API_KEY = "AIzaSyBtd3hYeceadQoc89Om0ydZlqNmctZZyZM"

def parse_resume_text(text):
    prompt = f"Extract profile summary, skills, projects, and experience from the following resume:\n\n{text}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    response = requests.post(f"{GEMINI_API_URL}?key={API_KEY}", json=payload)
    response.raise_for_status()
    return response.json()["candidates"][0]["content"]["parts"][0]["text"]
