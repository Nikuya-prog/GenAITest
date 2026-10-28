import os
import json
from typing import List
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from detect import run_detection

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")


# ---------- Output schemas ----------
class Analysis(BaseModel):
    id: str
    name: str
    risk_level: str = Field(description="High, Medium, or Low")
    root_cause: str = Field(description="Short explanation of why it is at risk")
    recommended_action: str


class AnalysisList(BaseModel):
    items: List[Analysis]


class Priority(BaseModel):
    id: str
    name: str
    rank: int = Field(description="1 = most urgent")
    score: int = Field(description="Urgency score from 1 to 100")
    reason: str


class PriorityList(BaseModel):
    items: List[Priority]


class Draft(BaseModel):
    id: str
    name: str
    task_subject: str = Field(description="Salesforce Task subject, max 80 characters")
    task_description: str
    alert_message: str = Field(description="Short chat alert for the sales team")


class DraftList(BaseModel):
    items: List[Draft]


# ---------- Helper ----------
def ask(prompt, schema):
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.2,
        ),
    )
    return response.parsed.items


# ---------- Agents ----------
def analyze_agent(records):
    prompt = (
        "You are a sales pipeline analyst. For each at-risk Salesforce record below, "
        "explain the root cause, assign a risk level, and recommend one action. "
        "Consider the amount, stage, and how many days are involved.\n\n"
        f"Records:\n{json.dumps(records, indent=2)}"
    )
    return ask(prompt, AnalysisList)


def prioritize_agent(records, analysis):
    prompt = (
        "You are a sales manager. Rank these at-risk records from most to least urgent. "
        "Weigh deal amount, risk level, and days overdue or without contact. "
        "Each record gets a unique rank.\n\n"
        f"Records:\n{json.dumps(records, indent=2)}\n\n"
        f"Analysis:\n{json.dumps([a.model_dump() for a in analysis], indent=2)}"
    )
    return ask(prompt, PriorityList)


def draft_agent(records, analysis):
    prompt = (
        "You are a sales assistant. For each record, write a follow-up Salesforce Task "
        "and a short, professional alert message for the sales team.\n\n"
        f"Records:\n{json.dumps(records, indent=2)}\n\n"
        f"Analysis:\n{json.dumps([a.model_dump() for a in analysis], indent=2)}"
    )
    return ask(prompt, DraftList)


# ---------- Test run ----------
if __name__ == "__main__":
    records = run_detection()
    print(f"Detected {len(records)} at-risk records\n")

    analysis = analyze_agent(records)
    print("=== ANALYZE ===")
    for a in analysis:
        print(f"{a.name} | {a.risk_level} | {a.root_cause}")

    priorities = sorted(prioritize_agent(records, analysis), key=lambda p: p.rank)
    print("\n=== PRIORITIZE ===")
    for p in priorities:
        print(f"#{p.rank} {p.name} (score {p.score}) - {p.reason}")

    drafts = draft_agent(records, analysis)
    print("\n=== DRAFT ===")
    for d in drafts:
        print(f"{d.name}\n  Task: {d.task_subject}\n  Alert: {d.alert_message}\n")