import { useState } from "react";
import { api } from "./api";
import { ModeBanner } from "./components/ui";
import { useAsync, useHashRoute } from "./hooks";
import { Automation } from "./pages/Automation";
import { History } from "./pages/History";
import { Inspect } from "./pages/Inspect";
import { Model } from "./pages/Model";
import { Overview } from "./pages/Overview";

const NAV: { id: string; label: string; hint: string }[] = [
  { id: "overview", label: "Overview", hint: "Line KPIs" },
  { id: "inspect", label: "Inspect", hint: "Upload & analyse" },
  { id: "history", label: "History", hint: "Records" },
  { id: "automation", label: "Automation", hint: "PLC simulator" },
  { id: "model", label: "Model", hint: "Status & metrics" },
];

export function App() {
  const [route, go] = useHashRoute("overview");
  const model = useAsync(api.modelStatus, [], 15000);
  const [historyFocus, setHistoryFocus] = useState<string | null>(null);
  const page = route.split("/")[0];

  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <div>
            <div className="brand-name">Inspection Station</div>
            <div className="brand-sub">Automotive quality</div>
          </div>
        </div>
        <nav aria-label="Main">
          {NAV.map((n) => (
            <a key={n.id} href={`#/${n.id}`} className={page === n.id ? "active" : ""} aria-current={page === n.id ? "page" : undefined}>
              <span>{n.label}</span>
              <small>{n.hint}</small>
            </a>
          ))}
        </nav>
        <div className="rail-foot">
          <div className={`mode-chip mode-${model.data?.mode ?? "none"}`}>{model.data?.mode === "real" ? "REAL MODEL" : model.data?.mode === "demo" ? "DEMO MODE" : model.error ? "BACKEND OFFLINE" : "NO MODEL"}</div>
        </div>
      </aside>
      <main className="main">
        <ModeBanner mode={model.data?.mode} ready={model.data?.ready} reason={model.data?.reason} />
        {model.error && !model.data && <div className="note note-error" role="alert">{model.error}</div>}
        {page === "overview" && <Overview go={go} />}
        {page === "inspect" && <Inspect model={model.data} />}
        {page === "history" && <History key={historyFocus ?? "h"} focusId={historyFocus} />}
        {page === "automation" && <Automation goToInspection={(id) => { setHistoryFocus(id); go("history"); }} />}
        {page === "model" && <Model model={model.data} error={model.error} reload={model.reload} />}
        {!NAV.some((n) => n.id === page) && <div className="note">Unknown page. <a href="#/overview">Go to overview</a></div>}
      </main>
    </div>
  );
}
