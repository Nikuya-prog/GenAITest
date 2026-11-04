import os
import json
from dotenv import load_dotenv

load_dotenv()
EMAIL_TO = ",".join(
    e.strip() for e in os.getenv("ALERT_EMAIL_TO", "").split(",") if e.strip()
)
EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM")


def _send(sf, subject, body):
    """Send one email through Salesforce. Returns True if sent."""
    if not EMAIL_TO:
        print("   ⚠️ ALERT_EMAIL_TO is missing in .env")
        return False

    email_input = {
        "emailAddresses": EMAIL_TO,
        "emailSubject": subject,
        "emailBody": body,
    }
    remaining = sf.limits()["SingleEmail"]["Remaining"]
    recipients = len(EMAIL_TO.split(","))
    if remaining < recipients:
        print(f"   ⚠️ Daily email limit reached ({remaining} left, need {recipients}). Try again tomorrow.")
        return False

    try:
        remaining = sf.limits()["SingleEmail"]["Remaining"]
        recipients = len(EMAIL_TO.split(","))
        if remaining < recipients:
            print(f"   ⚠️ Daily email limit reached ({remaining} left, need {recipients}). Try again tomorrow.")
            return False
    except Exception:
        pass  # if the limit check fails, still try to send
    
    if EMAIL_FROM:
        email_input["senderType"] = "OrgWideEmailAddress"
        email_input["senderAddress"] = EMAIL_FROM

    try:
        result = sf.restful(
            "actions/standard/emailSimple",
            method="POST",
            data=json.dumps({"inputs": [email_input]}),
        )
        if result[0].get("isSuccess"):
            return True
        print(f"   ⚠️ Email error: {result[0].get('errors')}")
        return False
    except Exception as e:
        print(f"   ⚠️ Email error: {e}")
        return False


def send_email_alert(sf, record, draft, priority):
    """Individual alert for one approved record."""
    body = (
        f"{draft.alert_message}\n\n"
        f"Record:   {record['type']}: {record['name']}\n"
        f"Priority: #{priority.rank} (score {priority.score})\n"
        f"Task:     {draft.task_subject}\n\n"
        f"Details:\n{draft.task_description}\n\n"
        "— Sent automatically by DealWatch"
    )
    return _send(sf, f"DealWatch Alert: {record['name']}", body)


def send_digest_email(sf, items):
    """One summary email for many records. items = list of (record, draft, priority)."""
    items = sorted(items, key=lambda x: x[2].rank)
    lines = [f"DealWatch created {len(items)} follow-up task(s):\n"]

    for record, draft, priority in items:
        lines.append(
            f"#{priority.rank}  {record['name']} ({record['type']}) — score {priority.score}\n"
            f"    {draft.alert_message}\n"
            f"    Task: {draft.task_subject}\n"
        )

    lines.append("— Sent automatically by DealWatch")
    return _send(sf, f"DealWatch Summary: {len(items)} at-risk record(s)", "\n".join(lines))