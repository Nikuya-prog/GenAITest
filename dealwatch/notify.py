import os
import json
from dotenv import load_dotenv

load_dotenv()
EMAIL_TO = ",".join(
    e.strip() for e in os.getenv("ALERT_EMAIL_TO", "").split(",") if e.strip()
)
EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM")


def send_email_alert(sf, record, draft, priority, recipient=None):
    """Send the alert email through Salesforce. Returns True if sent."""
    email_to = recipient if recipient is not None else EMAIL_TO
    if not email_to:
        print("   ⚠️ ALERT_EMAIL_TO is missing in .env")
        return False

    email_input = {
        "emailAddresses": email_to,
        "emailSubject": f"DealWatch Alert: {record['name']}",
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


def send_verification_email(sf, recipient, verification_url):
    """Send an account verification link through Salesforce."""
    email_input = {
        "emailAddresses": recipient,
        "emailSubject": "Verify your DealWatch account",
        "emailBody": (
            "Use the link below to verify your email address and continue your DealWatch "
            "account request. The link expires in 24 hours.\n\n"
            f"{verification_url}\n\n"
            "If you did not request a DealWatch account, you can ignore this email."
        ),
    }
    if EMAIL_FROM:
        email_input["senderType"] = "OrgWideEmailAddress"
        email_input["senderAddress"] = EMAIL_FROM

    result = sf.restful(
        "actions/standard/emailSimple",
        method="POST",
        data=json.dumps({"inputs": [email_input]}),
    )
    if result and result[0].get("isSuccess"):
        return True
    print(f"   ⚠️ Verification email error: {result[0].get('errors') if result else 'No response'}")
    return False