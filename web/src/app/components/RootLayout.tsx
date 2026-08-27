import { useEffect, useMemo, useState } from "react";
import { Outlet, useLocation } from "react-router";
import { Menu, PanelRight } from "lucide-react";
import { WorkspaceSidebar } from "./WorkspaceSidebar";
import { WorkspacePanel } from "./WorkspacePanel";
import { SettingsPage } from "./SettingsPage";
import { useGoalPlan, useGoalProgress } from "../../lib/goals";

export interface WorkspaceOutletContext {
  isPanelOpen: boolean;
  setIsPanelOpen: (open: boolean) => void;
}

function goalIdFromPath(pathname: string) {
  return pathname.match(/^\/goals\/([^/]+)\/(?:workspace|resume|learn|practice|diagnostic|mock|review|progress|notes)/)?.[1];
}

export function RootLayout() {
  const location = useLocation();
  const goalId = useMemo(() => goalIdFromPath(location.pathname), [location.pathname]);
  const isGoalRoute = Boolean(goalId);
  const { data: plan, isFetched: planFetched } = useGoalPlan(goalId);
  const { data: progress, isFetched: progressFetched } = useGoalProgress(goalId);
  const hasContext = Boolean(
    plan?.draft_plan
      || plan?.plan?.length
      || plan?.content
      || progress?.total_attempted
      || progress?.review_queue.length,
  );

  const [isPanelOpen, setPanelOpenState] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    if (new URLSearchParams(location.search).get("settings") === "open") {
      setIsSettingsOpen(true);
    }
  }, [location.search]);

  useEffect(() => {
    setMobileNavOpen(false);
    if (!goalId) {
      setPanelOpenState(false);
      return;
    }
    const stored = localStorage.getItem(`interviewtutor.contextPanel.${goalId}`);
    setPanelOpenState(stored === "open");
  }, [goalId, location.pathname]);

  useEffect(() => {
    if (!goalId || !planFetched || !progressFetched) return;
    const key = `interviewtutor.contextPanel.${goalId}`;
    if (localStorage.getItem(key) === null) {
      setPanelOpenState(window.innerWidth >= 1280 && hasContext);
    }
  }, [goalId, hasContext, planFetched, progressFetched]);

  const setIsPanelOpen = (open: boolean) => {
    setPanelOpenState(open);
    if (goalId) localStorage.setItem(`interviewtutor.contextPanel.${goalId}`, open ? "open" : "closed");
  };

  return (
    <div
      className="flex h-screen overflow-hidden bg-[#f7f7f8] dark:bg-gray-950"
      data-goal-context={hasContext ? "available" : "empty"}
      data-context-panel={isPanelOpen ? "open" : "closed"}
    >
      <WorkspaceSidebar
        onOpenSettings={() => setIsSettingsOpen(true)}
        mobileOpen={mobileNavOpen}
        onMobileOpenChange={setMobileNavOpen}
      />

      {mobileNavOpen && (
        <div className="fixed inset-0 z-40 bg-black/35 lg:hidden" onClick={() => setMobileNavOpen(false)} aria-hidden="true" />
      )}
      {isGoalRoute && isPanelOpen && (
        <div className="fixed inset-0 z-40 bg-black/30 xl:hidden" onClick={() => setIsPanelOpen(false)} aria-hidden="true" />
      )}

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="flex h-12 shrink-0 items-center gap-2 border-b border-gray-200 bg-white px-3 dark:border-gray-800 dark:bg-gray-900 lg:hidden">
          <button onClick={() => setMobileNavOpen(true)} className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800" aria-label="打开导航"><Menu className="h-5 w-5" /></button>
          <span className="text-sm font-semibold text-gray-900 dark:text-white">InterviewTutor</span>
          <div className="flex-1" />
          {isGoalRoute && <button onClick={() => setIsPanelOpen(true)} className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800" aria-label="打开目标面板"><PanelRight className="h-5 w-5" /></button>}
        </div>
        <div className="min-h-0 flex-1 overflow-hidden">
          <Outlet context={{ isPanelOpen, setIsPanelOpen } satisfies WorkspaceOutletContext} />
        </div>
      </main>

      {isGoalRoute && goalId && (
        <WorkspacePanel goalId={goalId} open={isPanelOpen} onClose={() => setIsPanelOpen(false)} />
      )}

      <SettingsPage open={isSettingsOpen} onOpenChange={setIsSettingsOpen} />
    </div>
  );
}
