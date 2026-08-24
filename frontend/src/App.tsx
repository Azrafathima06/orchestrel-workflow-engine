import { Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/shell/AppShell";
import { Landing } from "@/pages/Landing";
import { Overview } from "@/pages/Overview";
import { RunDetail } from "@/pages/RunDetail";
import { Runs } from "@/pages/Runs";
import { WorkflowDetail } from "@/pages/WorkflowDetail";
import { Workflows } from "@/pages/Workflows";
import { Workers } from "@/pages/Workers";

export function App() {
  return (
    <Routes>
      {/* The marketing/orientation page sits outside AppShell: a first-time
          visitor gets one clear next step rather than a navigation tree for
          a product they have not met yet. */}
      <Route path="/" element={<Landing />} />

      <Route element={<AppShell />}>
        <Route path="/dashboard" element={<Overview />} />
        <Route path="/workflows" element={<Workflows />} />
        <Route path="/workflows/:key" element={<WorkflowDetail />} />
        <Route path="/runs" element={<Runs />} />
        <Route path="/runs/:id" element={<RunDetail />} />
        <Route path="/workers" element={<Workers />} />
      </Route>
    </Routes>
  );
}
