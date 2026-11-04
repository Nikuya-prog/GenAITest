import os
import json
from dotenv import load_dotenv

load_dotenv()
EMAIL_TO = os.getenv("ALERT_EMAIL_TO")
EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM")


def send_email_alert(sf, record, draft, priority):
    """Send the alert email through Salesforce. Returns True if sent."""
    if not EMAIL_TO:
        print("   ⚠️ ALERT_EMAIL_TO is missing in .env")
        return False

    body = (
        f"{draft.alert_message}\n\n"
        f"Record:   {record['type']}: {record['name']}\n"
        f"Priority: #{priority.rank} (score {priority.score})\n"
        f"Task:     {draft.task_subject}\n\n"
        f"Details:\n{draft.task_description}\n\n"
        "— Sent automatically by DealWatch"
    )

    email_input = {
        "emailAddresses": EMAIL_TO,
        "emailSubject": f"DealWatch Alert: {record['name']}",
        "emailBody": body,
    }

    # Send as "DealWatch" if an org-wide address is set
    if EMAIL_FROM:
        email_input["senderType"] = "OrgWideEmailAddress"
        email_input["senderAddress"] = EMAIL_FROM

    payload = {"inputs": [email_input]}
    try:
        result = sf.restful(
            "actions/standard/emailSimple",
            method="POST",
            data=json.dumps(payload),
        )
        if result[0].get("isSuccess"):
            return True
        print(f"   ⚠️ Email error: {result[0].get('errors')}")
        return False
    except Exception as e:
        print(f"   ⚠️ Email error: {e}")
        return False