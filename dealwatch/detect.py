from datetime import date, timedelta
from sf_client import get_sf

# Rule settings
STALLED_DAYS = 14   # no contact for 14+ days
LEAD_DAYS = 3       # lead not contacted within 3 days


def detect_opportunities(sf):
    today = date.today()
    stalled_cutoff = (today - timedelta(days=STALLED_DAYS)).isoformat()
    today_str = today.isoformat()

    query = (
        "SELECT Id, Name, StageName, Amount, CloseDate, Last_Contact_Date__c "
        "FROM Opportunity "
        "WHERE IsClosed = false "
        f"AND (Last_Contact_Date__c <= {stalled_cutoff} OR CloseDate < {today_str})"
    )
    records = sf.query(query)["records"]

    flagged = []
    for o in records:
        reasons = []
        last_contact = o["Last_Contact_Date__c"]
        if last_contact and last_contact <= stalled_cutoff:
            days = (today - date.fromisoformat(last_contact)).days
            reasons.append(f"Stalled ({days} days no contact)")
        if o["CloseDate"] < today_str:
            days = (today - date.fromisoformat(o["CloseDate"])).days
            reasons.append(f"Overdue ({days} days past close date)")
        flagged.append({
            "type": "Opportunity",
            "id": o["Id"],
            "name": o["Name"],
            "stage": o["StageName"],
            "amount": o["Amount"],
            "reasons": reasons,
        })
    return flagged


def detect_leads(sf):
    today = date.today()
    lead_cutoff = (today - timedelta(days=LEAD_DAYS)).isoformat()

    query = (
        "SELECT Id, Name, Company, Status, Lead_Received_Date__c "
        "FROM Lead "
        "WHERE Status = 'Open - Not Contacted' "
        f"AND Lead_Received_Date__c <= {lead_cutoff}"
    )
    records = sf.query(query)["records"]

    flagged = []
    for l in records:
        days = (today - date.fromisoformat(l["Lead_Received_Date__c"])).days
        flagged.append({
            "type": "Lead",
            "id": l["Id"],
            "name": l["Name"],
            "company": l["Company"],
            "reasons": [f"Neglected ({days} days not contacted)"],
        })
    return flagged


def run_detection():
    sf = get_sf()
    return detect_opportunities(sf) + detect_leads(sf)


if __name__ == "__main__":
    results = run_detection()
    print(f"At-risk records found: {len(results)}\n")
    for r in results:
        print(f"[{r['type']}] {r['name']} -> {', '.join(r['reasons'])}")