/**
 * 学习计划相关的共享类型与工具函数。
 */

export interface TaskPlan {
  task_id?: string;
  taskTitle?: string;
  taskIcon?: string;
  startDate?: string;
  totalDays?: number;
  totalHours?: number;
  progress?: number;
  overallSummary?: string;
  coreKnowledge?: string[];
  masteryLevel?: { topic: string; level: number }[];
  milestones?: { date: string; achievement: string }[];
  plan?: string[] | string;
  planChecklist?: { [key: string]: boolean };
  _plan_sig?: string;
}

/**
 * 将计划步骤归一化为字符串数组。
 * 兼容数组与字符串两种形态；字符串按换行、分号、逗号切分
 * （统一此前 TutorSession 按分号、SummaryPanel 按逗号的不一致行为）。
 */
export function normalizePlanSteps(plan?: TaskPlan | { plan?: unknown } | null): string[] {
  if (!plan) return [];
  const raw = (plan as { plan?: unknown }).plan;
  if (Array.isArray(raw)) {
    const steps = raw.map((item) => String(item).trim()).filter(Boolean);
    if (steps.length > 0) return steps;
  }
  if (typeof raw === "string") {
    const steps = raw
      .split(/\r?\n|[；;，,]+/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (steps.length > 0) return steps;
  }
  const summary = (plan as TaskPlan).overallSummary;
  if (summary) {
    return [summary];
  }
  return [];
}
