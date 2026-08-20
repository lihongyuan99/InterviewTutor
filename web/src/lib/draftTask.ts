/**
 * 草稿任务（尚未落库的新任务）的 localStorage 读写，统一入口。
 */

export const TASK_DRAFT_KEY = "task_draft";

export interface DraftTask {
  id: string;
  title: string;
  icon: string;
}

export function makeTaskId(): string {
  return `task_${Date.now().toString(36)}`;
}

export function loadDraftTask(): DraftTask | null {
  try {
    const raw = localStorage.getItem(TASK_DRAFT_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (data && typeof data.id === "string") {
      return {
        id: data.id,
        title: typeof data.title === "string" && data.title ? data.title : "新的学习",
        icon: typeof data.icon === "string" && data.icon ? data.icon : "✨",
      };
    }
  } catch {
    // 忽略损坏的本地数据
  }
  return null;
}

export function saveDraftTask(task: DraftTask): void {
  try {
    localStorage.setItem(
      TASK_DRAFT_KEY,
      JSON.stringify({ id: task.id, title: task.title, icon: task.icon }),
    );
  } catch {
    // 忽略存储异常
  }
}

export function clearDraftTask(): void {
  try {
    localStorage.removeItem(TASK_DRAFT_KEY);
  } catch {
    // 忽略存储异常
  }
}

/** 确保存在草稿任务；没有则创建一个并返回 */
export function ensureDraftTask(): DraftTask {
  const existing = loadDraftTask();
  if (existing) return existing;
  const draft: DraftTask = { id: makeTaskId(), title: "新的学习", icon: "✨" };
  saveDraftTask(draft);
  return draft;
}
