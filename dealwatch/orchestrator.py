from detect import run_detection
from agents import analyze_agent, prioritize_agent, draft_agent
from actions import create_task
from notify import send_email_alert
from sf_client import get_sf
from logger import log_action

def main():
    print("\n=== DEALWATCH ===")
    print("Scanning Salesforce...\n")

    # 1. Detect
    records = run_detection()
    if not records:
        print("No at-risk records found.")
        return
    print(f"Found {len(records)} at-risk records.")

    # 2-4. AI agents
    print("Analyzing risks...")
    analysis = analyze_agent(records)

    print("Prioritizing records...")
    priorities = sorted(prioritize_agent(records, analysis), key=lambda p: p.rank)

    print("Drafting recommended actions...")
    drafts = draft_agent(records, analysis)

    draft_map = {d.id: d for d in drafts}
    record_map = {r["id"]: r for r in records}

    # 5. Show the priority queue
    print("\n=== PRIORITY QUEUE ===\n")
    for p in priorities:
        print(f"[{p.rank}] {p.name}")
        print(f"    Score: {p.score}/100")
        print(f"    Reason: {p.reason}")
        draft = draft_map.get(p.id)
        if draft:
            print(f"    Proposed Task: {draft.task_subject}")
            print(f"    Alert: {draft.alert_message}")
        print()

    # 6. Human approval
    while True:
        choice = input(
            f"Enter rank to approve (1-{len(priorities)}), "
            "'all' to approve everything, or 'q' to quit: "
        ).strip().lower()

        if choice == "q":
            print("\nNo actions approved.")
            return
        if choice == "all":
            selected = priorities
            break
        if choice.isdigit():
            selected = [p for p in priorities if p.rank == int(choice)]
            if selected:
                break
        print("Invalid choice. Please try again.")

    # 7. Execute approved actions
    print("\n=== EXECUTING APPROVED ACTIONS ===\n")
    sf = get_sf()

    for p in selected:
        record = record_map.get(p.id)
        draft = draft_map.get(p.id)

        if not record or not draft:
            print(f"Could not prepare {p.name}.")
            continue

        try:
            task_id = create_task(sf, record, draft, p)

            if task_id:
                print(f"✅ Task created for {p.name}")
                print(f"   Task ID: {task_id}")
                print(f"   Subject: [DealWatch] {draft.task_subject}")

                if send_email_alert(sf, record, draft, p):
                    print("   📧 Email alert sent")
                    email_status = "Sent"
                else:
                    print("   ⚠️ Email alert failed")
                    email_status = "Failed"

                log_action(record, p, "Created", task_id, email_status)
            else:
                print(f"⏭️  Skipped {p.name}: an open DealWatch task already exists.")
                log_action(record, p, "Skipped", email_status="Not sent")

        except Exception as e:
            print(f"❌ Failed for {p.name}: {e}")
            log_action(record, p, "Failed", email_status="Not sent", error=str(e))

        print()

    print("Done.")
    print("📝 Actions logged to logs/dealwatch_log.csv")


if __name__ == "__main__":
    main()