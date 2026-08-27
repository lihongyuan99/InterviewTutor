import { useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  BarChart3,
  BookOpen,
  Brain,
  ChevronDown,
  ChevronRight,
  Dumbbell,
  FileText,
  MessageSquare,
  MoreHorizontal,
  Moon,
  Plus,
  RotateCcw,
  Settings,
  Sparkles,
  Sun,
  Target,
  Trash2,
  X,
} from "lucide-react";
import { apiSend } from "../../lib/api";
import { goalKeys, rememberActiveGoal, useTasks, type GoalTask } from "../../lib/goals";
import { useTheme } from "../../lib/useTheme";
import { notifyError } from "../../lib/toast";

function goalIdFromPath(pathname: string) {
  return pathname.match(/^\/goals\/([^/]+)\/(?:workspace|resume|learn|practice|diagnostic|mock|review|progress|notes)(?:\/|$)/)?.[1] || "";
}

const goalSections = [
  { id: "workspace", label: "工作区", icon: MessageSquare },
  { id: "resume", label: "简历分析", icon: FileText },
  { id: "learn", label: "知识学习", icon: BookOpen },
  { id: "practice", label: "刷题训练", icon: Dumbbell },
  { id: "diagnostic", label: "能力诊断", icon: Sparkles },
  { id: "mock", label: "模拟面试", icon: Brain },
  { id: "review", label: "复习队列", icon: RotateCcw },
  { id: "progress", label: "学习进度", icon: BarChart3 },
];

export function WorkspaceSidebar({
  onOpenSettings,
  mobileOpen,
  onMobileOpenChange,
}: {
  onOpenSettings: () => void;
  mobileOpen: boolean;
  onMobileOpenChange: (open: boolean) => void;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { theme, toggleTheme } = useTheme();
  const { data: tasks = [] } = useTasks();
  const goalId = goalIdFromPath(location.pathname);
  const [archivedOpen, setArchivedOpen] = useState(false);
  const [menuId, setMenuId] = useState<string | null>(null);
  const [editing, setEditing] = useState<GoalTask | null>(null);
  const [editRole, setEditRole] = useState("");
  const [editCompanies, setEditCompanies] = useState("");
  const [saving, setSaving] = useState(false);

  const goals = useMemo(
    () => tasks.filter((item) => item.kind === "interview_goal" && item.status === "active"),
    [tasks],
  );
  const archivedGoals = useMemo(
    () => tasks.filter((item) => item.kind === "interview_goal" && item.status === "archived"),
    [tasks],
  );

  const invalidate = async (id?: string) => {
    await queryClient.invalidateQueries({ queryKey: goalKeys.tasks });
    if (id) await queryClient.invalidateQueries({ queryKey: goalKeys.goal(id) });
  };

  const openEdit = (goal: GoalTask) => {
    setMenuId(null);
    setEditing(goal);
    setEditRole(goal.target_role || "");
    setEditCompanies(goal.target_companies.join("、"));
  };

  const saveEdit = async () => {
    if (!editing || !editRole.trim()) return;
    setSaving(true);
    try {
      await apiSend(`/tasks/${editing.id}`, "PATCH", {
        target_role: editRole.trim(),
        target_companies: editCompanies.split(/[，,、]/).map((item) => item.trim()).filter(Boolean),
      });
      await invalidate(editing.id);
      setEditing(null);
    } catch (error) {
      notifyError(error instanceof Error ? error.message : "更新目标失败");
    } finally {
      setSaving(false);
    }
  };

  const archiveGoal = async (goal: GoalTask) => {
    setMenuId(null);
    try {
      await apiSend(`/tasks/${goal.id}/status`, "PATCH", { status: "archived" });
      await invalidate(goal.id);
      if (goal.id === goalId) navigate("/", { replace: true });
    } catch (error) {
      notifyError(error instanceof Error ? error.message : "归档失败");
    }
  };

  const restoreGoal = async (goal: GoalTask) => {
    setMenuId(null);
    try {
      await apiSend(`/tasks/${goal.id}/status`, "PATCH", { status: "active" });
      await invalidate(goal.id);
      rememberActiveGoal(goal.id);
      navigate(`/goals/${goal.id}/workspace`);
      closeMobile();
    } catch (error) {
      notifyError(error instanceof Error ? error.message : "恢复失败");
    }
  };

  const deleteGoal = async (goal: GoalTask) => {
    setMenuId(null);
    if (!window.confirm(`确定删除“${goal.title}”吗？该操作不可撤销。`)) return;
    try {
      await apiSend(`/tasks/${goal.id}`, "DELETE");
      await invalidate(goal.id);
      if (goal.id === goalId) navigate("/", { replace: true });
    } catch (error) {
      notifyError(error instanceof Error ? error.message : "删除失败");
    }
  };

  const closeMobile = () => onMobileOpenChange(false);

  return (
    <>
      <aside
        className={`${mobileOpen ? "translate-x-0" : "-translate-x-full"} fixed inset-y-0 left-0 z-50 flex w-[232px] flex-col border-r border-gray-200 bg-[#f5f5f6] transition-transform duration-200 dark:border-gray-800 dark:bg-gray-950 lg:static lg:translate-x-0`}
      >
        <div className="flex h-14 shrink-0 items-center gap-2.5 border-b border-gray-200 px-4 dark:border-gray-800">
          <img src="/img/logo.svg" alt="" className="h-7 w-7" />
          <span className="text-sm font-semibold tracking-tight text-gray-900 dark:text-gray-100">InterviewTutor</span>
          <button onClick={closeMobile} className="ml-auto rounded-lg p-1 text-gray-500 lg:hidden" aria-label="关闭导航">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-3">
          <Link
            to="/goals/new"
            onClick={closeMobile}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            <Plus className="h-4 w-4" /> 新建面试目标
          </Link>
        </div>

        <div className="flex-1 overflow-y-auto px-2 pb-3">
          {goalId && (
            <div className="mb-4">
              <div className="px-2 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-gray-400">当前目标</div>
              <nav className="space-y-0.5">
                {goalSections.map((item) => {
                  const Icon = item.icon;
                  const href = `/goals/${goalId}/${item.id}`;
                  const active = location.pathname === href;
                  return (
                    <Link
                      key={item.id}
                      to={href}
                      onClick={() => {
                        rememberActiveGoal(goalId);
                        closeMobile();
                      }}
                      className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition ${active ? "bg-white font-medium text-gray-950 shadow-sm dark:bg-gray-800 dark:text-white" : "text-gray-600 hover:bg-white/70 hover:text-gray-950 dark:text-gray-300 dark:hover:bg-gray-900"}`}
                    >
                      <Icon className={`h-4 w-4 ${active ? "text-indigo-600" : "text-gray-400"}`} />
                      {item.label}
                    </Link>
                  );
                })}
              </nav>
            </div>
          )}

          <div className="px-2 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-gray-400">最近目标</div>
          <div className="space-y-0.5">
            {goals.map((goal) => {
              const active = goal.id === goalId;
              return (
                <div key={goal.id} className="group relative">
                  <Link
                    to={`/goals/${goal.id}/workspace`}
                    onClick={() => {
                      rememberActiveGoal(goal.id);
                      closeMobile();
                    }}
                    className={`flex items-center gap-2 rounded-lg py-2 pl-2.5 pr-8 text-sm ${active ? "bg-indigo-50 text-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-200" : "text-gray-600 hover:bg-white/70 dark:text-gray-300 dark:hover:bg-gray-900"}`}
                  >
                    <Target className={`h-4 w-4 shrink-0 ${active ? "text-indigo-600" : "text-gray-400"}`} />
                    <span className="truncate">{goal.title}</span>
                  </Link>
                  <button
                    onClick={() => setMenuId(menuId === goal.id ? null : goal.id)}
                    className="absolute right-1.5 top-1.5 rounded-md p-1 text-gray-400 opacity-70 hover:bg-gray-200 hover:text-gray-700 hover:opacity-100 focus:opacity-100 dark:hover:bg-gray-700"
                    aria-label={`管理 ${goal.title}`}
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </button>
                  {menuId === goal.id && (
                    <div className="absolute right-1 top-9 z-20 w-36 overflow-hidden rounded-xl border border-gray-200 bg-white py-1 shadow-xl dark:border-gray-700 dark:bg-gray-800">
                      <button onClick={() => openEdit(goal)} className="w-full px-3 py-2 text-left text-xs text-gray-700 hover:bg-gray-50 dark:text-gray-200 dark:hover:bg-gray-700">编辑目标</button>
                      <button onClick={() => void archiveGoal(goal)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-gray-700 hover:bg-gray-50 dark:text-gray-200 dark:hover:bg-gray-700"><Archive className="h-3.5 w-3.5" />归档</button>
                      <button onClick={() => void deleteGoal(goal)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/30"><Trash2 className="h-3.5 w-3.5" />删除</button>
                    </div>
                  )}
                </div>
              );
            })}
            {goals.length === 0 && <div className="px-2.5 py-3 text-xs text-gray-400">还没有面试目标</div>}
          </div>

          <div className="mt-4 border-t border-gray-200 pt-3 dark:border-gray-800">
              <button onClick={() => setArchivedOpen(!archivedOpen)} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-xs font-medium text-gray-500 hover:bg-white/70 dark:hover:bg-gray-900">
                <Archive className="h-4 w-4" /> 已归档目标
                <span className="ml-auto text-[10px] text-gray-400">{archivedGoals.length}</span>
                {archivedOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              </button>
              {archivedOpen && (
                <div className="mt-1 space-y-0.5">
                  {archivedGoals.map((goal) => (
                    <div key={goal.id} className="group relative">
                      <Link to={`/goals/${goal.id}/workspace`} onClick={closeMobile} className="flex items-center gap-2 rounded-lg py-2 pl-2.5 pr-8 text-xs text-gray-500 hover:bg-white/70 dark:text-gray-400 dark:hover:bg-gray-900">
                        <span className="truncate">{goal.icon} {goal.title}</span>
                      </Link>
                      <button
                        onClick={() => setMenuId(menuId === goal.id ? null : goal.id)}
                        className="absolute right-1.5 top-1.5 rounded-md p-1 text-gray-400 opacity-70 hover:bg-gray-200 hover:text-gray-700 hover:opacity-100 focus:opacity-100 dark:hover:bg-gray-700"
                        aria-label={`管理已归档目标 ${goal.title}`}
                      >
                        <MoreHorizontal className="h-3.5 w-3.5" />
                      </button>
                      {menuId === goal.id && (
                        <div className="absolute right-1 top-9 z-20 w-36 overflow-hidden rounded-xl border border-gray-200 bg-white py-1 shadow-xl dark:border-gray-700 dark:bg-gray-800">
                          <button onClick={() => void restoreGoal(goal)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-gray-700 hover:bg-gray-50 dark:text-gray-200 dark:hover:bg-gray-700"><RotateCcw className="h-3.5 w-3.5" />恢复目标</button>
                          <button onClick={() => void deleteGoal(goal)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/30"><Trash2 className="h-3.5 w-3.5" />删除</button>
                        </div>
                      )}
                    </div>
                  ))}
                  {archivedGoals.length === 0 && <div className="px-2.5 py-2 text-xs text-gray-400">暂无已归档目标</div>}
                </div>
              )}
            </div>
        </div>

        <div
          data-testid="workspace-sidebar-footer"
          className="workspace-bottom-dock flex shrink-0 flex-col justify-center border-t border-gray-200 p-2 dark:border-gray-800"
        >
          <button onClick={toggleTheme} className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-gray-600 hover:bg-white/70 dark:text-gray-300 dark:hover:bg-gray-900">
            {theme === "dark" ? <Sun className="h-4 w-4 text-amber-500" /> : <Moon className="h-4 w-4 text-gray-400" />}
            {theme === "dark" ? "浅色模式" : "深色模式"}
          </button>
          <button onClick={onOpenSettings} className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-gray-600 hover:bg-white/70 dark:text-gray-300 dark:hover:bg-gray-900">
            <Settings className="h-4 w-4 text-gray-400" /> 系统设置
          </button>
        </div>
      </aside>

      {editing && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/35 p-4" onClick={() => setEditing(null)}>
          <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-2xl dark:bg-gray-900" onClick={(event) => event.stopPropagation()}>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">编辑面试目标</h2>
            <div className="mt-4 space-y-4">
              <label className="block text-sm text-gray-600 dark:text-gray-300">目标岗位<input value={editRole} onChange={(event) => setEditRole(event.target.value)} className="workspace-input mt-1.5" /></label>
              <label className="block text-sm text-gray-600 dark:text-gray-300">目标公司<input value={editCompanies} onChange={(event) => setEditCompanies(event.target.value)} className="workspace-input mt-1.5" /></label>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button onClick={() => setEditing(null)} className="rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800">取消</button>
              <button disabled={saving} onClick={() => void saveEdit()} className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">{saving ? "保存中…" : "保存"}</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
