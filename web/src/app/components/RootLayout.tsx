import { Outlet, useLocation } from "react-router";
import { Menu, PanelRight } from "lucide-react";
import { TaskSidebar } from "./TaskSidebar";
import { SummaryPanel } from "./SummaryPanel";
import { SettingsPage } from "./SettingsPage";
import { useEffect, useState } from "react";

export function RootLayout() {
  const [isPanelOpen, setIsPanelOpen] = useState(true);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [mobilePanelOpen, setMobilePanelOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    if (new URLSearchParams(location.search).get("settings") === "open") {
      setIsSettingsOpen(true);
    }
  }, [location.search]);

  // 路由切换时关闭移动端抽屉
  useEffect(() => {
    setMobileNavOpen(false);
    setMobilePanelOpen(false);
  }, [location.pathname]);

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-950">
      {/* Left Sidebar (desktop inline / mobile drawer) */}
      <TaskSidebar
        onOpenSettings={() => setIsSettingsOpen(true)}
        mobileOpen={mobileNavOpen}
        onMobileOpenChange={setMobileNavOpen}
      />

      {/* Mobile backdrop */}
      {(mobileNavOpen || mobilePanelOpen) && (
        <div
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
          onClick={() => {
            setMobileNavOpen(false);
            setMobilePanelOpen(false);
          }}
          aria-hidden="true"
        />
      )}

      {/* Middle Content Area */}
      <main className="flex-1 overflow-hidden flex flex-col">
        {/* Mobile top bar */}
        <div className="md:hidden flex items-center gap-2 px-3 py-2 border-b border-gray-200 bg-white dark:bg-gray-900 dark:border-gray-800">
          <button
            type="button"
            aria-label="打开导航"
            onClick={() => setMobileNavOpen(true)}
            className="p-2 rounded-lg text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
          >
            <Menu className="w-5 h-5" />
          </button>
          <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            InterviewTutor
          </span>
          <div className="flex-1" />
          {isPanelOpen && (
            <button
              type="button"
              aria-label="打开学习时间线"
              onClick={() => setMobilePanelOpen(true)}
              className="p-2 rounded-lg text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
            >
              <PanelRight className="w-5 h-5" />
            </button>
          )}
        </div>

        <div className="flex-1 overflow-hidden">
          <Outlet context={{ isPanelOpen, setIsPanelOpen }} />
        </div>
      </main>

      {/* Right Summary Panel (desktop inline / mobile drawer) */}
      {isPanelOpen && (
        <SummaryPanel
          mobileOpen={mobilePanelOpen}
          onMobileOpenChange={setMobilePanelOpen}
        />
      )}

      <SettingsPage open={isSettingsOpen} onOpenChange={setIsSettingsOpen} />
    </div>
  );
}
