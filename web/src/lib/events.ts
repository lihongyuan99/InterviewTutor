/**
 * window 事件总线的事件名常量，避免散落的魔法字符串。
 */

/** 任务列表增删改后触发 */
export const EVENT_TASKS_UPDATED = "tasks-updated";
/** 任务计划/笔记更新后触发 */
export const EVENT_TASK_PLAN_UPDATED = "task-plan-updated";
/** 对话时间线更新后触发 */
export const EVENT_TIMELINE_UPDATED = "timeline-updated";
/** 请求 AI 生成学习计划（detail: { taskId }） */
export const EVENT_REQUEST_PLAN = "request-plan";
/** LLM 模型设置更新后触发（detail: 新设置对象） */
export const EVENT_LLM_SETTINGS_UPDATED = "llm-settings-updated";

export function emitAppEvent(name: string, detail?: unknown): void {
  if (detail === undefined) {
    window.dispatchEvent(new Event(name));
  } else {
    window.dispatchEvent(new CustomEvent(name, { detail }));
  }
}
