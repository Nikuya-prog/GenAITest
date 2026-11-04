from detect import run_detection
from agents import analyze_agent, prioritize_agent, draft_agent


def main():
    print("\n=== DEALWATCH ===")
    print("Scanning Salesforce...\n")

    # 1. Detect
    records = run_detection()

    if not records:
        print("No at-risk records found.")
        return

    print(f"Found {len(records)} at-risk records.")

    # 2. Analyze
    print("Analyzing risks...")
    analysis = analyze_agent(records)

    # 3. Prioritize
    print("Prioritizing records...")
    priorities = prioritize_agent(records, analysis)
    priorities = sorted(priorities, key=lambda p: p.rank)

    # 4. Draft
    print("Drafting recommended actions...")
    drafts = draft_agent(records, analysis)

    # Easy lookup by Salesforce ID
    draft_map = {d.id: d for d in drafts}
    record_map = {r["id"]: r for r in records}

    # 5. Display ranked queue
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
            "Enter rank to approve (1-5), "
            "'all' to approve everything, or 'q' to quit: "
        ).strip().lower()

        if choice == "q":
            print("\nNo actions approved.")
            return

        if choice == "all":
            selected = priorities
            break

        if choice.isdigit():
            rank = int(choice)

            selected = [p for p in priorities if p.rank == rank]

            if selected:
                break

        print("Invalid choice. Please try again.")

    # 7. Show approved actions
    print("\n=== APPROVED ACTIONS ===\n")

    for p in selected:
        record = record_map.get(p.id)
        draft = draft_map.get(p.id)

        if not record or not draft:
            print(f"Could not prepare {p.name}.")
            continue

        print(f"APPROVED: {p.name}")
        print(f"Type: {record['type']}")
        print(f"Salesforce ID: {p.id}")
        print(f"Task: {draft.task_subject}")
        print(f"Description: {draft.task_description}")
        print(f"Alert: {draft.alert_message}")
        print()

    print("Approval complete.")
    print("No Salesforce records were changed.")


if __name__ == "__main__":
    main()