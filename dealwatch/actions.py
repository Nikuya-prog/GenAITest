from datetime import date, timedelta

TAG = "[DealWatch]"


def task_exists(sf, record):
    """Check if an open DealWatch task already exists for this record."""
    field = "WhatId" if record["type"] == "Opportunity" else "WhoId"
    query = (
        "SELECT Id FROM Task "
        f"WHERE {field} = '{record['id']}' "
        "AND IsClosed = false "
        f"AND Subject LIKE '{TAG}%'"
    )
    return sf.query(query)["totalSize"] > 0


def create_task(sf, record, draft, priority):
    """Create a follow-up Task in Salesforce. Returns the Task ID, or None if skipped."""
    if task_exists(sf, record):
        return None

    high = priority.score >= 70
    due = date.today() + timedelta(days=1 if high else 3)

    task = {
        "Subject": f"{TAG} {draft.task_subject}"[:255],
        "Description": draft.task_description,
        "Status": "Not Started",
        "Priority": "High" if high else "Normal",
        "ActivityDate": due.isoformat(),
    }

    # Opportunities link with WhatId, Leads link with WhoId
    if record["type"] == "Opportunity":
        task["WhatId"] = record["id"]
    else:
        task["WhoId"] = record["id"]

    if not record.get("owner_id"):
        raise ValueError(f"Salesforce owner is missing for record {record['id']}.")
    task["OwnerId"] = record["owner_id"]

    return sf.Task.create(task)["id"]