import sys
import os
import requests
import json
import datetime
from dotenv import load_dotenv
load_dotenv()
def log_rca(report_data):
    reports = []
    try:
        with open("rca_reports.json", "r") as f:
            reports = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    reports.append(report_data)
    with open("rca_reports.json", "w") as f:
        json.dump(reports, f, indent=4)

def generate_rca(pod_name, terminated_at, recovery_seconds):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("Error: GROQ_API_KEY environment variable not set.")
        return

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {
                "role": "system",
                "content": "You are an SRE assistant. Generate a brief Root Cause Analysis report."
            },
            {
                "role": "user",
                "content": f"Pod {pod_name} was terminated at {terminated_at}. Recovery took {recovery_seconds} seconds. Generate a short RCA report with: what happened, likely cause, recovery summary, and one recommendation."
            }
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        report_content = data['choices'][0]['message']['content']
        print("\n--- ROOT CAUSE ANALYSIS REPORT ---")
        print(report_content)
        print("----------------------------------\n")
        
        # Log RCA
        log_rca({
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pod_name": pod_name,
            "report": report_content
        })
    except requests.exceptions.RequestException as e:
        print(f"Error calling Groq API: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python rca.py <pod_name> <terminated_at> <recovery_seconds>")
        sys.exit(1)

    generate_rca(sys.argv[1], sys.argv[2], sys.argv[3])