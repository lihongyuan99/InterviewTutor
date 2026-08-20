import { Link, useLocation, useNavigate } from "react-router";
import { Plus, ChevronDown, ChevronRight, Settings, Archive, Edit2, X, Loader2, Brain, Moon, Sun } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { API_BASE_URL } from "../../lib/api";
import {
  clearDraftTask,
  loadDraftTask,
  makeTaskId,
  saveDraftTask,
} from "../../lib/draftTask";
import { EVENT_TASKS_UPDATED, emitAppEvent } from "../../lib/events";
import { useTheme } from "../../lib/useTheme";
import { notifyError } from "../../lib/toast";

const COMMON_ICONS = [
  { icon: "📚", label: "书本" },
  { icon: "🎯", label: "目标" },
  { icon: "💻", label: "电脑" },
  { icon: "📊", label: "图表" },
  { icon: "🔬", label: "科学" },
  { icon: "📝", label: "笔记" },
  { icon: "🎓", label: "学位" },
  { icon: "📖", label: "开放书" },
  { icon: "🧮", label: "算盘" },
  { icon: "🔢", label: "数字" },
  { icon: "🔤", label: "字母" },
  { icon: "🌳", label: "树" },
  { icon: "🗣️", label: "说话" },
  { icon: "⚛️", label: "原子" },
  { icon: "🐍", label: "蛇" },
  { icon: "💾", label: "磁盘" },
  { icon: "⭐", label: "星星" },
  { icon: "🚀", label: "火箭" },
  { icon: "💡", label: "灯泡" },
  { icon: "🏆", label: "奖杯" },
  { icon: "📈", label: "增长" },
  { icon: "🎨", label: "艺术" },
  { icon: "🎵", label: "音乐" },
  { icon: "🧠", label: "大脑" },
  { icon: "⚡", label: "闪电" },
  { icon: "🔥", label: "火焰" },
  { icon: "💪", label: "力量" },
  { icon: "🌟", label: "闪亮" },
  { icon: "✨", label: "火花" },
];

interface Task {
  id: string;
  title: string;
  icon: string;
  status: "active" | "archived";
  created_at?: string;
  updated_at?: string;
}

const logoUrl = "/img/logo.svg";

export function TaskSidebar({
  onOpenSettings,
  mobileOpen = false,
  onMobileOpenChange,
}: {
  onOpenSettings: () => void;
  mobileOpen?: boolean;
  onMobileOpenChange?: (open: boolean) => void;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [showArchived, setShowArchived] = useState(false);
  const [storedTasks, setStoredTasks] = useState<Task[]>([]);
  const [draftTask, setDraftTask] = useState<Task | null>(() => {
    const draft = loadDraftTask();
    return draft ? { ...draft, status: "active" } : null;
  });
  const [menuState, setMenuState] = useState<{
    visible: boolean;
    x: number;
    y: number;
    task: Task | null;
  }>({
    visible: false,
    x: 0,
    y: 0,
    task: null,
  });
  const [editState, setEditState] = useState<{
    visible: boolean;
    task: Task | null;
    title: string;
    icon: string;
    isSaving: boolean;
  }>({
    visible: false,
    task: null,
    title: "",
    icon: "",
    isSaving: false,
  });

  const loadTasks = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/tasks`);
      if (!response.ok) {
        throw new Error("failed");
      }
      const data = await response.json();
      const tasks = Array.isArray(data.tasks) ? data.tasks : [];
      setStoredTasks(tasks);
    } catch {
      setStoredTasks([]);
    }
  };

  useEffect(() => {
    const refreshTasks = () => {
      void loadTasks();
      const draft = loadDraftTask();
      setDraftTask(draft ? { ...draft, status: "active" } : null);
    };
    void loadTasks();
    {
      const draft = loadDraftTask();
      setDraftTask(draft ? { ...draft, status: "active" } : null);
    }
    window.addEventListener("tasks-updated", refreshTasks);
    return () => {
      window.removeEventListener("tasks-updated", refreshTasks);
    };
  }, []);

  useEffect(() => {
    if (!menuState.visible) return;
    const closeMenu = () => setMenuState((prev) => ({ ...prev, visible: false }));
    window.addEventListener("click", closeMenu);
    window.addEventListener("scroll", closeMenu, true);
    window.addEventListener("resize", closeMenu);
    return () => {
      window.removeEventListener("click", closeMenu);
      window.removeEventListener("scroll", closeMenu, true);
      window.removeEventListener("resize", closeMenu);
    };
  }, [menuState.visible]);

  const isTaskActive = (taskId: string) => {
    return location.pathname === `/task/${taskId}`;
  };

  const activeTaskList = useMemo(() => {
    const merged = storedTasks.filter((item) => item.status === "active");
    if (draftTask && !merged.some((item) => item.id === draftTask.id)) {
      return [draftTask, ...merged];
    }
    return merged;
  }, [storedTasks, draftTask]);
  const archivedTaskList = useMemo(
    () => storedTasks.filter((item) => item.status === "archived"),
    [storedTasks]
  );

  const handleContextMenu = (event: React.MouseEvent, task: Task) => {
    if (draftTask && task.id === draftTask.id) return;
    event.preventDefault();
    setMenuState({
      visible: true,
      x: event.clientX,
      y: event.clientY,
      task,
    });
  };

  const handleArchive = async () => {
    if (!menuState.task) return;
    const exists = storedTasks.some((item) => item.id === menuState.task?.id);
    if (!exists) {
      await fetch(`${API_BASE_URL}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_id: menuState.task.id,
          title: menuState.task.title,
          icon: menuState.task.icon,
          status: "active",
        }),
      });
    }
    await fetch(`${API_BASE_URL}/tasks/${menuState.task.id}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "archived" }),
    });
    setMenuState((prev) => ({ ...prev, visible: false }));
    // 更新本地状态，立即反映变化
    setStoredTasks((prev) =>
      prev.map((t) =>
        t.id === menuState.task?.id ? { ...t, status: "archived" as const } : t
      )
    );
    emitAppEvent(EVENT_TASKS_UPDATED);
  };

  const handleRestore = async () => {
    if (!menuState.task) return;
    const exists = storedTasks.some((item) => item.id === menuState.task?.id);
    if (!exists) {
      await fetch(`${API_BASE_URL}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_id: menuState.task.id,
          title: menuState.task.title,
          icon: menuState.task.icon,
          status: "archived",
        }),
      });
    }
    await fetch(`${API_BASE_URL}/tasks/${menuState.task.id}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "active" }),
    });
    setMenuState((prev) => ({ ...prev, visible: false }));
    // 更新本地状态，立即反映变化
    setStoredTasks((prev) =>
      prev.map((t) =>
        t.id === menuState.task?.id ? { ...t, status: "active" as const } : t
      )
    );
    emitAppEvent(EVENT_TASKS_UPDATED);
  };

  const handleDelete = async () => {
    if (!menuState.task) return;
    const taskId = menuState.task.id;
    if (draftTask && taskId === draftTask.id) {
      clearDraftTask();
      setDraftTask(null);
      setMenuState((prev) => ({ ...prev, visible: false }));
      emitAppEvent(EVENT_TASKS_UPDATED);
      if (location.pathname === `/task/${taskId}`) {
        navigate("/");
      }
      return;
    }
    const exists = storedTasks.some((item) => item.id === taskId);
    if (!exists) {
      await fetch(`${API_BASE_URL}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_id: menuState.task.id,
          title: menuState.task.title,
          icon: menuState.task.icon,
          status: menuState.task.status,
        }),
      });
    }
    await fetch(`${API_BASE_URL}/tasks/${taskId}`, { method: "DELETE" });
    setMenuState((prev) => ({ ...prev, visible: false }));
    emitAppEvent(EVENT_TASKS_UPDATED);
    if (location.pathname === `/task/${taskId}`) {
      const existingDraft = loadDraftTask();
      const nextDraft = existingDraft || {
        id: makeTaskId(),
        title: "新的学习",
        icon: "✨",
      };
      if (!existingDraft) {
        saveDraftTask(nextDraft);
        setDraftTask({ ...nextDraft, status: "active" });
        emitAppEvent(EVENT_TASKS_UPDATED);
      }
      navigate(`/task/${nextDraft.id}`);
    }
  };

  const handleEdit = () => {
    if (!menuState.task) return;
    setEditState({
      visible: true,
      task: menuState.task,
      title: menuState.task.title,
      icon: menuState.task.icon,
      isSaving: false,
    });
    setMenuState((prev) => ({ ...prev, visible: false }));
  };

  const handleSaveEdit = async () => {
    if (!editState.task) return;
    const taskId = editState.task.id;
    setEditState((prev) => ({ ...prev, isSaving: true }));
    try {
      const payload: { title?: string; icon?: string } = {};
      if (editState.title.trim()) {
        payload.title = editState.title.trim();
      }
      if (editState.icon) {
        payload.icon = editState.icon;
      }

      const response = await fetch(`${API_BASE_URL}/tasks/${taskId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || "更新失败");
      }

      // 重新加载任务列表确保数据一致
      await loadTasks();
      emitAppEvent(EVENT_TASKS_UPDATED);
    } catch (error) {
      const message = error instanceof Error ? error.message : "更新任务失败";
      console.error("更新任务失败:", error);
      notifyError(message);
      setEditState((prev) => ({ ...prev, isSaving: false }));
      return;
    }
    setEditState((prev) => ({ ...prev, visible: false, isSaving: false }));
  };

  const handleCancelEdit = () => {
    setEditState((prev) => ({ ...prev, visible: false }));
  };

  const selectIcon = (icon: string) => {
    setEditState((prev) => ({ ...prev, icon }));
  };

  const handleCreateTask = async () => {
    const existingDraft = loadDraftTask();
    if (existingDraft) {
      navigate(`/task/${existingDraft.id}`);
      return;
    }
    const taskId = makeTaskId();
    const nextDraft = {
      id: taskId,
      title: "新的学习",
      icon: "✨",
    };
    saveDraftTask(nextDraft);
    setDraftTask({ ...nextDraft, status: "active" });
    emitAppEvent(EVENT_TASKS_UPDATED);
    navigate(`/task/${taskId}`);
  };
  return (
    <aside
      className={`${
        mobileOpen ? "translate-x-0" : "-translate-x-full"
      } fixed inset-y-0 left-0 z-40 w-[250px] bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 flex flex-col transition-transform duration-200 md:static md:translate-x-0`}
    >
      {/* Brand Logo */}
      <div className="p-6 border-b border-gray-200 dark:border-gray-800 relative">
        <button
          type="button"
          aria-label="关闭导航"
          onClick={() => onMobileOpenChange?.(false)}
          className="absolute top-3 right-3 md:hidden p-1.5 rounded-lg text-gray-500 hover:bg-gray-100"
        >
          <X className="w-5 h-5" />
        </button>
        <div className="flex flex-col items-center text-center gap-3">
          <div className="w-[72px] h-[72px] shrink-0">
            <img src={logoUrl} alt="InterviewTutor" className="w-full h-full" />
          </div>
          <h1 className="text-[26px] font-bold tracking-tight text-gray-900 dark:text-gray-100 leading-none">
            InterviewTutor
          </h1>
          <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
            <span className="h-px w-8 bg-indigo-300/70 dark:bg-indigo-500/60" />
            <span className="tracking-wider">AI 面试训练助手</span>
            <span className="h-px w-8 bg-indigo-300/70 dark:bg-indigo-500/60" />
          </div>
        </div>
      </div>

      {/* New Task Button */}
      <div className="p-4 border-b border-gray-200 dark:border-gray-800">
        <button
          onClick={() => void handleCreateTask()}
          disabled={Boolean(draftTask && location.pathname === `/task/${draftTask.id}`)}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors font-medium disabled:opacity-60 disabled:cursor-not-allowed"
        >
          <Plus className="w-5 h-5" />
          新建学习任务
        </button>
        <Link
          to="/interview"
          className={`mt-2 w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg transition-colors font-medium ${
            location.pathname === "/interview"
              ? "bg-indigo-50 text-indigo-600 dark:bg-indigo-900/40 dark:text-indigo-300"
              : "bg-white dark:bg-gray-800 border border-indigo-200 dark:border-indigo-700 text-indigo-600 dark:text-indigo-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/40"
          }`}
        >
          <Brain className="w-5 h-5" />
          面试训练
        </Link>
      </div>

      {/* Active Learning Tasks */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-4">
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider px-2 mb-2">
            进行中的任务
          </h3>
          <div className="space-y-1">
            {activeTaskList.map((task) => (
              <Link
                key={task.id}
                to={`/task/${task.id}`}
                onContextMenu={(event) => handleContextMenu(event, task)}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all ${
                  isTaskActive(task.id)
                    ? "bg-indigo-50 text-indigo-600 shadow-sm dark:bg-indigo-900/40 dark:text-indigo-300"
                    : "text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
                }`}
              >
                <span className="text-lg">{task.icon}</span>
                <span className="flex-1 text-sm font-medium truncate">
                  {task.title}
                </span>
              </Link>
            ))}
          </div>
        </div>

        {/* Archived Tasks */}
        <div className="p-4 border-t border-gray-200 dark:border-gray-800">
          <button
            onClick={() => setShowArchived(!showArchived)}
            className="w-full flex items-center gap-2 px-2 py-2 text-gray-600 hover:text-gray-900 transition-colors"
          >
            <Archive className="w-4 h-4" />
            <span className="flex-1 text-left text-xs font-semibold uppercase tracking-wider">
              已归档任务
            </span>
            {showArchived ? (
              <ChevronDown className="w-4 h-4" />
            ) : (
              <ChevronRight className="w-4 h-4" />
            )}
          </button>
          {showArchived && (
            <div className="mt-2 space-y-1">
              {archivedTaskList.map((task) => (
                <Link
                  key={task.id}
                  to={`/task/${task.id}`}
                  onContextMenu={(event) => handleContextMenu(event, task)}
                  className="flex items-center gap-3 px-3 py-2 rounded-lg text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                >
                  <span className="text-lg opacity-60">{task.icon}</span>
                  <span className="flex-1 text-sm truncate">{task.title}</span>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Bottom System Settings */}
      <div className="border-t border-gray-200 dark:border-gray-800 p-4 space-y-1">
        <button
          type="button"
          onClick={toggleTheme}
          role="switch"
          aria-checked={theme === "dark"}
          aria-label={theme === "dark" ? "切换到浅色模式" : "切换到深色模式"}
          className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-gray-700 transition-colors hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-800"
        >
          <span className="flex items-center gap-3">
            {theme === "dark" ? (
              <Sun className="w-5 h-5 text-amber-500" />
            ) : (
              <Moon className="w-5 h-5 text-indigo-500" />
            )}
            <span className="text-sm font-medium">
              {theme === "dark" ? "浅色模式" : "深色模式"}
            </span>
          </span>
          <span
            className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-200 ${
              theme === "dark" ? "bg-indigo-500" : "bg-gray-300"
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform duration-200 ${
                theme === "dark" ? "translate-x-4" : "translate-x-0.5"
              }`}
            />
          </span>
        </button>
        <button
          type="button"
          onClick={onOpenSettings}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-gray-700 dark:text-gray-200 transition-colors hover:bg-gray-100 dark:hover:bg-gray-800"
        >
          <Settings className="w-5 h-5 text-gray-500 dark:text-gray-400" />
          <span className="text-sm font-medium">系统设置</span>
        </button>
      </div>

      {menuState.visible && menuState.task && (
        <div
          className="fixed z-50 w-40 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg"
          style={{ top: menuState.y, left: menuState.x }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={handleEdit}
            className="w-full px-3 py-2 text-left text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center gap-2"
          >
            <Edit2 className="w-4 h-4" />
            编辑任务
          </button>
          {menuState.task.status === "archived" ? (
            <button
              onClick={handleRestore}
              className="w-full px-3 py-2 text-left text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
            >
              恢复任务
            </button>
          ) : (
            <button
              onClick={handleArchive}
              className="w-full px-3 py-2 text-left text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
            >
              归档任务
            </button>
          )}
          <button
            onClick={handleDelete}
            className="w-full px-3 py-2 text-left text-sm text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-900/30"
          >
            删除任务
          </button>
        </div>
      )}

      {/* 编辑任务对话框 */}
      {editState.visible && editState.task && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-30">
          <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl w-full max-w-md mx-4 overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">编辑任务</h3>
              <button
                onClick={handleCancelEdit}
                className="text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">
                  任务名称
                </label>
                <input
                  type="text"
                  value={editState.title}
                  onChange={(e) => setEditState((prev) => ({ ...prev, title: e.target.value }))}
                  className="w-full rounded-xl border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 px-4 py-2.5 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  placeholder="输入任务名称..."
                  autoFocus
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">
                  任务图标
                </label>
                <div className="grid grid-cols-8 gap-2 max-h-48 overflow-y-auto p-2 bg-gray-50 dark:bg-gray-700/50 rounded-xl border border-gray-200 dark:border-gray-600">
                  {COMMON_ICONS.map((item) => (
                    <button
                      key={item.icon}
                      type="button"
                      onClick={() => selectIcon(item.icon)}
                      className={`w-10 h-10 flex items-center justify-center text-lg rounded-lg transition-colors ${
                        editState.icon === item.icon
                          ? "bg-indigo-100 dark:bg-indigo-900/50 ring-2 ring-indigo-500"
                          : "hover:bg-gray-200 dark:hover:bg-gray-600"
                      }`}
                      title={item.label}
                    >
                      {item.icon}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-3 px-6 py-4 bg-gray-50 dark:bg-gray-800/50 border-t border-gray-200 dark:border-gray-700">
              <button
                onClick={handleCancelEdit}
                disabled={editState.isSaving}
                className="px-4 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-lg transition-colors disabled:opacity-50"
              >
                取消
              </button>
              <button
                onClick={handleSaveEdit}
                disabled={!editState.title.trim() || editState.isSaving}
                className="px-4 py-2 text-sm text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {editState.isSaving ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    保存中...
                  </>
                ) : (
                  "保存修改"
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
