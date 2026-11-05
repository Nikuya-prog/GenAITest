import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api.js";

function formatDate(value) {
  if (!value) return "Not yet run";
  return new Date(value).toLocaleString([], {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function StatusPill({ value }) {
  const labels = {
    needs_approval: "Needs review",
    approved: "Task created",
    skipped: "Skipped",
    duplicate: "Existing task",
    failed: "Action failed",
    completed: "Completed",
    running: "Running",
    pending: "Pending approval",
    rejected: "Rejected",
  };
  return <span className={`status-pill status-${value}`}>{labels[value] || value}</span>;
}

function AuthForm({ setupRequired, onAuthenticated, initialMessage }) {
  const [mode, setMode] = useState(setupRequired ? "setup" : "login");
  const [form, setForm] = useState({
    name: "",
    email: "",
    password: "",
    setup_secret: "",
  });
  const [error, setError] = useState("");
  const [message, setMessage] = useState(initialMessage || "");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (initialMessage) setMessage(initialMessage);
  }, [initialMessage]);

  function update(event) {
    setForm({ ...form, [event.target.name]: event.target.value });
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    setBusy(true);
    try {
      if (mode === "setup") {
        const user = await api.post("/auth/bootstrap-manager", form);
        onAuthenticated(user);
      } else if (mode === "signup") {
        await api.post("/auth/register", form);
        setMessage("Check your email for a verification link. A manager can approve your account after you verify.");
        setMode("resend");
      } else if (mode === "resend") {
        const result = await api.post("/auth/resend-verification", { email: form.email });
        setMessage(result.message);
      } else {
        const user = await api.post("/auth/login", form);
        onAuthenticated(user);
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  const title =
    mode === "setup"
      ? "Set up your first manager"
      : mode === "signup"
        ? "Request an account"
        : mode === "resend"
          ? "Resend verification link"
          : "Welcome back";

  return (
    <main className="auth-page">
      <section className="auth-card">
        <Brand />
        <p className="eyebrow">SALES FOLLOW-UP WORKSPACE</p>
        <h1>{title}</h1>
        <p className="muted">
          {mode === "setup"
            ? "Create the first manager account using the private setup secret from the server configuration."
            : mode === "signup"
              ? "Verify your work email first. A manager must then approve your account."
              : mode === "resend"
                ? "Enter the email address you used to request access."
                : "Sign in to review the records that need attention."}
        </p>
        <form className="form-stack" onSubmit={submit}>
          {(mode === "signup" || mode === "setup") && (
            <label>
              Your name
              <input name="name" autoComplete="name" required value={form.name} onChange={update} />
            </label>
          )}
          {mode === "setup" && (
            <label>
              Private setup secret
              <input
                name="setup_secret"
                type="password"
                autoComplete="off"
                required
                value={form.setup_secret}
                onChange={update}
              />
            </label>
          )}
          <label>
            Work email
            <input
              name="email"
              type="email"
              autoComplete="email"
              required
              value={form.email}
              onChange={update}
            />
          </label>
          {mode !== "resend" && <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              minLength={12}
              required
              value={form.password}
              onChange={update}
            />
            {mode !== "login" && <small>Use at least 12 characters.</small>}
          </label>}
          {error && <p className="notice notice-error" role="alert">{error}</p>}
          {message && <p className="notice notice-success" role="status">{message}</p>}
          <button className="button button-primary full-width" disabled={busy}>
            {busy
              ? "Please wait..."
              : mode === "setup"
                ? "Create manager account"
                : mode === "signup"
                  ? "Request account"
                  : mode === "resend"
                    ? "Send verification link"
                    : "Sign in"}
          </button>
        </form>
        {mode !== "setup" && (
          <div className="auth-switch">
            {mode !== "login" && (
              <>
                <button className="text-button" onClick={() => setMode("login")}>Back to sign in</button>
                {" · "}
              </>
            )}
            <button className="text-button" onClick={() => setMode(mode === "login" ? "signup" : "resend")}>
              {mode === "login" ? "Request access" : "Resend verification"}
            </button>
            {mode === "login" && (
              <>
                {" · "}
                <button className="text-button" onClick={() => setMode("resend")}>Resend verification</button>
              </>
            )}
          </div>
        )}
      </section>
    </main>
  );
}

function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">D</span>
      <span>DealWatch</span>
    </div>
  );
}

function RecordCard({ record, selected, onSelect, onAction, busy }) {
  const [subject, setSubject] = useState(record.draft.task_subject);
  const [description, setDescription] = useState(record.draft.task_description);
  const reasons = record.payload.reasons || [];

  useEffect(() => {
    setSubject(record.draft.task_subject);
    setDescription(record.draft.task_description);
  }, [record.draft.task_subject, record.draft.task_description]);

  const amount =
    record.type === "Opportunity" && record.payload.amount != null
      ? `Amount: ${Number(record.payload.amount).toLocaleString()}`
      : null;

  return (
    <article className={`record-card ${selected ? "record-card-selected" : ""}`}>
      <button className="record-summary" onClick={onSelect} aria-expanded={selected}>
        <span className="rank-badge">{record.priority.rank}</span>
        <span className="record-main">
          <span className="record-title">{record.name}</span>
          <span className="record-meta">
            <span className={`type-label type-${record.type.toLowerCase()}`}>{record.type}</span>
            {record.owner_name && <span>Owner: {record.owner_name}</span>}
            {record.payload.stage && <span>{record.payload.stage}</span>}
            {record.payload.company && <span>{record.payload.company}</span>}
            {amount && <span>{amount}</span>}
          </span>
          <span className="record-reason">{reasons.join(" · ") || record.analysis.root_cause}</span>
        </span>
        <span className="record-priority">
          <span className={`risk-label risk-${record.analysis.risk_level.toLowerCase()}`}>
            {record.analysis.risk_level} risk
          </span>
          <span className="score">{record.priority.score}<small>/100</small></span>
        </span>
      </button>

      {selected && (
        <div className="record-details">
          <div className="detail-grid">
            <section>
              <p className="detail-label">Why it needs attention</p>
              <p>{record.analysis.root_cause}</p>
            </section>
            <section>
              <p className="detail-label">Recommended action</p>
              <p>{record.analysis.recommended_action}</p>
            </section>
            <section>
              <p className="detail-label">Priority reason</p>
              <p>{record.priority.reason}</p>
            </section>
            <section>
              <p className="detail-label">Suggested team alert</p>
              <p>{record.draft.alert_message}</p>
            </section>
          </div>
          {record.action_status === "needs_approval" ? (
            <form
              className="task-editor"
              onSubmit={(event) => {
                event.preventDefault();
                onAction("approve", { task_subject: subject, task_description: description });
              }}
            >
              <div>
                <p className="detail-label">Review and edit the Salesforce task</p>
                <p className="muted small-copy">Approving creates this task and assigns it to the record owner.</p>
              </div>
              <label>
                Task subject
                <input maxLength={255} required value={subject} onChange={(event) => setSubject(event.target.value)} />
              </label>
              <label>
                Task description
                <textarea rows={4} required value={description} onChange={(event) => setDescription(event.target.value)} />
              </label>
              <div className="action-row">
                <button className="button button-primary" disabled={busy}>Approve and create task</button>
                <button type="button" className="button button-secondary" disabled={busy} onClick={() => onAction("skip")}>
                  Skip
                </button>
              </div>
            </form>
          ) : (
            <div className="outcome-row">
              <StatusPill value={record.action_status} />
              {record.task_id && <span className="muted">Salesforce task: {record.task_id}</span>}
              {record.email_status && <span className="muted">Email: {record.email_status.replace("_", " ")}</span>}
              {record.action_error && <span className="notice notice-error">{record.action_error}</span>}
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function Dashboard({ latest, onRefresh, onRunScan, scanBusy }) {
  const [selectedId, setSelectedId] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState("");
  const records = latest?.records || [];
  const pendingCount = records.filter((record) => record.action_status === "needs_approval").length;
  const highRiskCount = records.filter((record) => record.analysis.risk_level.toLowerCase() === "high").length;

  async function handleAction(record, action, body) {
    setBusyId(record.item_id);
    setError("");
    try {
      await api.post(`/records/${record.item_id}/${action}`, body);
      await onRefresh();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">YOUR SALES PIPELINE</p>
          <h1>Priority queue</h1>
          <p className="muted">Review at-risk leads and opportunities, then decide what to do next.</p>
        </div>
        <div className="schedule-card">
          <span className="schedule-dot" />
          <div>
            <strong>Automatic scan</strong>
            <span>Weekdays at 9:00 AM · {latest?.schedule?.timezone || "team timezone"}</span>
          </div>
          <button className="button button-primary scan-button" onClick={onRunScan} disabled={scanBusy}>
            {scanBusy ? "Scanning..." : "Scan now"}
          </button>
        </div>
      </div>

      <section className="summary-grid" aria-label="Queue summary">
        <div className="summary-card">
          <span className="summary-label">Records in latest scan</span>
          <strong>{latest?.scan?.record_count ?? 0}</strong>
          <span className="summary-caption">Leads and opportunities</span>
        </div>
        <div className="summary-card summary-card-accent">
          <span className="summary-label">Need your review</span>
          <strong>{pendingCount}</strong>
          <span className="summary-caption">Tasks waiting for approval</span>
        </div>
        <div className="summary-card">
          <span className="summary-label">High risk</span>
          <strong>{highRiskCount}</strong>
          <span className="summary-caption">Ranked by urgency</span>
        </div>
        <div className="summary-card">
          <span className="summary-label">Last scan</span>
          <strong className="summary-date">{formatDate(latest?.scan?.finished_at || latest?.scan?.started_at)}</strong>
          <span className="summary-caption">{latest?.scan?.status || "Waiting for first scan"}</span>
        </div>
      </section>

      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {latest?.scan?.status === "failed" && (
        <p className="notice notice-error" role="alert">
          The latest scan failed: {latest.scan.error_message || "Check the backend logs for details."}
        </p>
      )}

      <section className="queue-section">
        <div className="section-heading">
          <div>
            <h2>Records to review</h2>
            <p className="muted">Sorted from most urgent to least urgent.</p>
          </div>
          <span className="queue-count">{records.length} records</span>
        </div>
        {records.length === 0 ? (
          <div className="empty-state">
            <span className="empty-mark">✓</span>
            <h3>{latest?.scan?.status === "completed" ? "No at-risk records found" : "No scan results yet"}</h3>
            <p className="muted">
              {latest?.scan?.status === "completed"
                ? "The latest scan did not find leads or opportunities that match the current risk rules."
                : "DealWatch will show results after its next scheduled weekday scan."}
            </p>
          </div>
        ) : (
          <div className="record-list">
            {records.map((record) => (
              <RecordCard
                key={record.item_id}
                record={record}
                selected={selectedId === record.item_id}
                onSelect={() => setSelectedId(selectedId === record.item_id ? null : record.item_id)}
                onAction={(action, body) => handleAction(record, action, body)}
                busy={busyId === record.item_id}
              />
            ))}
          </div>
        )}
      </section>
    </>
  );
}

function History({ onLoad }) {
  const [scans, setScans] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/scans/history").then(setScans).catch((requestError) => setError(requestError.message));
  }, []);

  async function openScan(scanId) {
    setError("");
    try {
      const details = await api.get(`/scans/${scanId}`);
      setSelected(details);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">PAST ACTIVITY</p>
          <h1>Scan history</h1>
          <p className="muted">Review previous scans and what happened to each suggested task.</p>
        </div>
      </div>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {scans.length === 0 ? (
        <div className="empty-state"><h3>No scan history yet</h3><p className="muted">Past scans will appear here.</p></div>
      ) : (
        <div className="history-layout">
          <div className="history-list">
            {scans.map((scan) => (
              <button
                key={scan.id}
                className={`history-item ${selected?.id === scan.id ? "history-item-selected" : ""}`}
                onClick={() => openScan(scan.id)}
              >
                <span><strong>{formatDate(scan.started_at)}</strong><StatusPill value={scan.status} /></span>
                <small>{scan.record_count} records · {scan.pending_count} waiting for review</small>
              </button>
            ))}
          </div>
          {selected && (
            <div className="history-detail">
              <h2>Scan details</h2>
              <p className="muted">{formatDate(selected.started_at)}</p>
              {selected.records.length === 0 ? (
                <p className="muted">No records were saved for this scan.</p>
              ) : (
                selected.records.map((record) => (
                  <div className="history-record" key={record.item_id}>
                    <div><strong>{record.name}</strong><span>{record.type} · {record.priority.score}/100</span></div>
                    <StatusPill value={record.action_status} />
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function Registrations({ onChanged }) {
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState({});
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setUsers(await api.get("/admin/registrations"));
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function decide(user, status) {
    try {
      await api.patch(`/admin/users/${user.id}`, {
        status,
        role: roles[user.id] || "rep",
      });
      await load();
      onChanged();
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">TEAM ACCESS</p>
          <h1>Account requests</h1>
          <p className="muted">Approve people before they can see Salesforce records.</p>
        </div>
      </div>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {users.length === 0 ? (
        <div className="empty-state"><h3>All caught up</h3><p className="muted">There are no pending account requests.</p></div>
      ) : (
        <div className="registration-list">
          {users.map((user) => (
            <div className="registration-item" key={user.id}>
              <div><strong>{user.name}</strong><span>{user.email}</span></div>
              <label className="role-select">
                Role
                <select value={roles[user.id] || "rep"} onChange={(event) => setRoles({ ...roles, [user.id]: event.target.value })}>
                  <option value="rep">Sales rep</option>
                  <option value="manager">Manager</option>
                </select>
              </label>
              <div className="action-row">
                <button className="button button-primary" onClick={() => decide(user, "approved")}>Approve</button>
                <button className="button button-secondary" onClick={() => decide(user, "rejected")}>Reject</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default function App() {
  const [user, setUser] = useState(null);
  const [setupRequired, setSetupRequired] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [latest, setLatest] = useState(null);
  const [page, setPage] = useState("queue");
  const [globalError, setGlobalError] = useState("");
  const [authMessage, setAuthMessage] = useState("");
  const [scanBusy, setScanBusy] = useState(false);

  const loadLatest = useCallback(async () => {
    const result = await api.get("/scans/latest");
    setLatest({ scan: result.scan, records: result.records, schedule: result.schedule });
  }, []);

  const loadUserData = useCallback(async (currentUser) => {
    setGlobalError("");
    setUser(currentUser);
    try {
      await loadLatest();
    } catch (requestError) {
      setGlobalError(requestError.message);
    }
  }, [loadLatest]);

  useEffect(() => {
    let active = true;
    const verificationToken = new URLSearchParams(window.location.search).get("verify");
    const verification = verificationToken
      ? api.post("/auth/verify-email", { token: verificationToken })
          .then((result) => {
            if (active) setAuthMessage(result.message);
            window.history.replaceState({}, "", window.location.pathname);
          })
          .catch((requestError) => {
            if (active) setGlobalError(requestError.message);
            window.history.replaceState({}, "", window.location.pathname);
          })
      : Promise.resolve();
    Promise.all([
      api.get("/auth/bootstrap-status"),
      api.get("/auth/me").catch(() => null),
      verification,
    ]).then(([bootstrap, currentUser]) => {
      if (!active) return;
      setSetupRequired(bootstrap.setup_required);
      if (currentUser) loadUserData(currentUser);
    }).catch((requestError) => {
      if (active) setGlobalError(requestError.message);
    }).finally(() => {
      if (active) setAuthChecked(true);
    });
    return () => { active = false; };
  }, [loadUserData]);

  const pendingCount = useMemo(
    () => latest?.records.filter((record) => record.action_status === "needs_approval").length || 0,
    [latest],
  );

  useEffect(() => {
    if (!user) return undefined;
    const timer = window.setInterval(() => {
      loadLatest().catch((requestError) => setGlobalError(requestError.message));
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [user, loadLatest]);

  async function signOut() {
    try {
      await api.post("/auth/logout", {});
      setUser(null);
      setLatest(null);
    } catch (requestError) {
      setGlobalError(requestError.message);
    }
  }

  async function runScanNow() {
    setScanBusy(true);
    setGlobalError("");
    try {
      const result = await api.post("/scans/run", {});
      setLatest({ scan: result.scan, records: result.records, schedule: result.schedule });
    } catch (requestError) {
      setGlobalError(requestError.message);
      try {
        await loadLatest();
      } catch (refreshError) {
        setGlobalError(`${requestError.message} ${refreshError.message}`);
      }
    } finally {
      setScanBusy(false);
    }
  }

  if (!authChecked) {
    return <main className="loading-screen"><Brand /><p>Loading DealWatch...</p></main>;
  }
  if (!user) {
    return (
      <>
        {globalError && <p className="global-error" role="alert">{globalError}</p>}
        <AuthForm setupRequired={setupRequired} onAuthenticated={loadUserData} initialMessage={authMessage} />
      </>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <Brand />
        <div className="topbar-right">
          <span className="user-chip"><span className="avatar">{user.name.slice(0, 1).toUpperCase()}</span><span>{user.name}<small>{user.role}</small></span></span>
          <button className="text-button signout-button" onClick={signOut}>Sign out</button>
        </div>
      </header>
      <div className="app-body">
        <nav className="side-nav" aria-label="Main navigation">
          <button className={page === "queue" ? "nav-link nav-link-active" : "nav-link"} onClick={() => setPage("queue")}>
            <span className="nav-icon">◈</span> Priority queue
            {pendingCount > 0 && <span className="nav-count">{pendingCount}</span>}
          </button>
          <button className={page === "history" ? "nav-link nav-link-active" : "nav-link"} onClick={() => setPage("history")}>
            <span className="nav-icon">◷</span> Scan history
          </button>
          {user.role === "manager" && (
            <button className={page === "team" ? "nav-link nav-link-active" : "nav-link"} onClick={() => setPage("team")}>
              <span className="nav-icon">◎</span> Team access
            </button>
          )}
          <div className="nav-note"><strong>How it works</strong><span>DealWatch finds records needing attention. You decide whether to create each suggested task.</span></div>
        </nav>
        <main className="main-content">
          {globalError && <p className="notice notice-error" role="alert">{globalError}</p>}
          {page === "queue" && (
            <Dashboard
              latest={latest}
              onRefresh={loadLatest}
              onRunScan={runScanNow}
              scanBusy={scanBusy}
            />
          )}
          {page === "history" && <History />}
          {page === "team" && user.role === "manager" && <Registrations onChanged={() => {}} />}
        </main>
      </div>
    </div>
  );
}
