import { useState } from "react";
import { CaseList } from "./components/CaseList.jsx";
import { CaseWorkspace } from "./components/CaseWorkspace.jsx";
import { Sidebar } from "./components/Sidebar.jsx";
import { cases } from "./data.js";

export function App() {
  const [view, setView] = useState("workspace");
  const [activeCase, setActiveCase] = useState(cases[0]);

  function openCase(item) {
    setActiveCase(item);
    setView("workspace");
  }

  const navView = view === "review" ? "review" : "cases";

  return (
    <div className="app-shell">
      <Sidebar activeView={navView} onNavigate={setView} />
      <div className="app-main">
        {view === "workspace" ? (
          <CaseWorkspace caseItem={activeCase} onBack={() => setView("cases")} />
        ) : (
          <CaseList reviewOnly={view === "review"} onOpenCase={openCase} />
        )}
      </div>
    </div>
  );
}
