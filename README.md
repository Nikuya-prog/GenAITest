# DealWatch

DealWatch checks Salesforce leads and opportunities that may need follow-up. Gemini explains and ranks the flagged records, and a person reviews each suggested task before the app creates it in Salesforce.

This repository now has a first web-app foundation:

- `dealwatch/` contains the existing Salesforce and Gemini workflow plus the FastAPI web API.
- `frontend/` contains the React browser app.
- SQLite stores app accounts, scan history, and task outcomes. Salesforce remains the source of the lead and opportunity records.
- The API schedules scans for weekdays at 9:00 AM in `TEAM_TIMEZONE`.

## How the parts fit together

1. The React page calls the Python API. It does not connect directly to Salesforce or Gemini.
2. The API reads Salesforce, asks Gemini for analysis and task suggestions, and saves a snapshot of the results.
3. A signed-in sales rep sees records whose Salesforce owner email matches the rep's verified account email. Managers can see all records.
4. An approved user can start an immediate scan from the dashboard or wait for the weekday schedule. They can edit the proposed task, then approve or skip it. Approval creates a Salesforce Task assigned to the record owner and attempts to email that owner.
5. The History page shows past scans and action outcomes.

## Run locally on Windows

Open a terminal in `GenAITest`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and add the Salesforce and Gemini values. Replace the sample `DEALWATCH_SETUP_SECRET` with a long private value. The schedule defaults to `Asia/Manila` and runs at 9:00 AM on weekdays; change `TEAM_TIMEZONE` if the team is in another timezone.

In the first terminal, start the API from the `dealwatch` folder:

```powershell
Set-Location .\dealwatch
python -m uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal, start the React app:

```powershell
Set-Location .\GenAITest\frontend
npm install
npm run dev
```

Open the address printed by Vite (normally `http://localhost:5173`). On the first visit, use the private setup secret to create the first manager account. Later registrations must verify their email through Salesforce email delivery, then a manager must approve them. Managers can choose whether each approved account is a rep or another manager.

The API's interactive documentation is at `http://127.0.0.1:8000/docs`.

## Check the app

Run the backend tests from `GenAITest`:

```powershell
Set-Location .\dealwatch
python -m pytest -q
```

Build the browser app from `GenAITest`:

```powershell
Set-Location .\frontend
npm run build
```

The backend tests use fake Salesforce/email responses; they do not prove that the configured Salesforce organization has the required access.

## Configuration and prerequisites

- Salesforce API access must be enabled for the configured connected app. The account needs permission to query leads, opportunities, owners, and users; create tasks; and use Salesforce's `emailSimple` action.
- Detection uses the custom Salesforce fields `Last_Contact_Date__c` and `Lead_Received_Date__c`.
- The existing lead and opportunity rules use 3 days for uncontacted leads and 14 days for stalled opportunities, and also flag past-due opportunities.
- `GEMINI_API_KEY` is needed for analysis, prioritization, and task drafts.
- `ALERT_EMAIL_FROM` is optional and should be an authorized Salesforce organization-wide email address if used.
- `DATABASE_URL` defaults to a SQLite file in the backend's working directory. Protect and back up that file; it includes Salesforce-derived scan snapshots and user data.
- The scheduler runs inside the API process. Keep exactly one scheduler-enabled API instance until scheduling is moved to a dedicated worker or managed job service.

## Before team deployment

This is an early app foundation, not a production deployment package. Choose and configure the hosting provider, a persistent database, HTTPS, a specific team timezone, and a production secret store. Set `COOKIE_SECURE=true` behind HTTPS. If the frontend and API are on different sites, configure `COOKIE_SAMESITE=none` as well as `COOKIE_SECURE=true`. Configure shared rate-limit storage if running multiple API instances. Public registration sends email through Salesforce, so protect the API from abuse and verify the sender configuration before exposing it to the internet.

Do not put Salesforce or Gemini secrets in the React app. They belong only in the backend's private environment. Do not commit `.env` or the SQLite database.
