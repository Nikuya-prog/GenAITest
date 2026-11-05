import os
import json
import time
from typing import List
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from detect import run_detection

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")


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

#---------- New Batching Function ----------
BATCH_SIZE = 20
BATCH_PAUSE = 2


def in_batches(items):
    for i in range(0, len(items), BATCH_SIZE):
        yield items[i:i + BATCH_SIZE]


def run_batched(records, fn):
    results = []
    batches = list(in_batches(records))

    for i, batch in enumerate(batches, start=1):
        if len(batches) > 1:
            print(f"   Batch {i}/{len(batches)} ({len(batch)} records)")

        results += fn(batch)

        if i < len(batches):
            time.sleep(BATCH_PAUSE)

    return results


# ---------- Agents ----------
def _analyze_batch(records):
    prompt = (
        "You are a sales pipeline analyst. Analyze ONLY the Salesforce data provided. "
        "Do not assume or invent any information that is not explicitly present. "
        "For each at-risk Salesforce record, explain the root cause, assign a risk level "
        "(High, Medium, or Low), and recommend one action. "
        "For opportunities, consider amount, stage, and detected risk reasons. "
        "For leads, use only company, status, and detected risk reasons. "
        "Return exactly one item per record using the same id.\n\n"
        f"Records:\n{json.dumps(records, indent=2)}"
    )

    return ask(prompt, AnalysisList)


def _prioritize_batch(records, analysis):
    prompt = (
        "You are a sales manager. Score each at-risk record from 1 to 100 for urgency. "
        "Use ONLY the Salesforce data and analysis provided. "
        "Do not invent missing information. "
        "Use this scoring guide:\n"
        "- 80-100: High risk opportunity with large amount, or stalled AND overdue\n"
        "- 60-79: Opportunity stalled OR overdue with moderate amount\n"
        "- 40-59: Medium risk lead, or low-amount opportunity\n"
        "- 1-39: Low risk lead or minor issue\n"
        "More days stalled or overdue should increase the score. "
        "Set rank to 0 because Python will assign final ranks later. "
        "Return exactly one item per record using the same id.\n\n"
        f"Records:\n{json.dumps(records, indent=2)}\n\n"
        f"Analysis:\n{json.dumps([a.model_dump() for a in analysis], indent=2)}"
    )

    return ask(prompt, PriorityList)


def _draft_batch(records, analysis):
    prompt = (
        "You are a sales assistant. "
        "Use ONLY the Salesforce data and analysis provided. "
        "Do not invent missing customer details, lead source, contact history, "
        "decision-makers, or other facts. "
        "For each record, write a follow-up Salesforce Task and a short "
        "professional alert for the sales team. "
        "Return exactly one item per record using the same id.\n\n"
        f"Records:\n{json.dumps(records, indent=2)}\n\n"
        f"Analysis:\n{json.dumps([a.model_dump() for a in analysis], indent=2)}"
    )

    return ask(prompt, DraftList)


# ---------- Public agents ----------

def analyze_agent(records):
    return run_batched(records, _analyze_batch)


def prioritize_agent(records, analysis):
    analysis_map = {a.id: a for a in analysis}

    def fn(batch):
        batch_analysis = [
            analysis_map[r["id"]]
            for r in batch
            if r["id"] in analysis_map
        ]

        return _prioritize_batch(batch, batch_analysis)

    priorities = run_batched(records, fn)

    # Highest score becomes rank 1 across ALL batches
    priorities.sort(key=lambda p: p.score, reverse=True)

    for i, p in enumerate(priorities, start=1):
        p.rank = i

    return priorities


def draft_agent(records, analysis):
    analysis_map = {a.id: a for a in analysis}

    def fn(batch):
        batch_analysis = [
            analysis_map[r["id"]]
            for r in batch
            if r["id"] in analysis_map
        ]

        return _draft_batch(batch, batch_analysis)

    return run_batched(records, fn)


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














        