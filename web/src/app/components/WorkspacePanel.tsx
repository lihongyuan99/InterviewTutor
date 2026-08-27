import { useMemo, useState } from "react";
import { Link } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  BookOpen,
  CalendarDays,
  Check,
  ChevronRight,
  ClipboardList,
  Clock3,
  FileText,
  Loader2,
  Target,
  X,
} from "lucide-react";
import { apiSend } from "../../lib/api";
import { goalKeys, useGoal, useGoalPlan, useGoalProgress, useGoalReports, useGoalTimeline } from "../../lib/goals";
import { normalizePlanSteps, type TaskPlan } from "../../lib/plan";

type PanelTab = "overview" | "plan" | "activity" | "notes";

const tabs: Array<{ id: PanelTab; label: string }> = [
  { id: "overview", label: "概览" },
  { id: "plan", label: "计划" },
  { id: "activity", label: "动态" },
  { id: "notes", label: "笔记" },
];

export function WorkspacePanel({ goalId, open, onClose }: { goalId: string; open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<PanelTab>("overview");
  const [activityDate, setActivityDate] = useState("");
  const [working, setWorking] = useState(false);
  const { data: goal } = useGoal(goalId);
  const { data: plan, isLoading: planLoading } = useGoalPlan(goalId);
  const { data: progress } = useGoalProgress(goalId);
  const { data: timeline = [] } = useGoalTimeline(goalId);
  const { data: reports = [] } = useGoalReports(goalId);
  const steps = normalizePlanSteps(plan);
  const checklist = plan?.planChecklist || {};
  const completed = steps.filter((_, index) => checklist[String(index)]).length;
  const completion = steps.length ? Math.round((completed / steps.length) * 100) : 0;
  const nextStepIndex = steps.findIndex((_, index) => !checklist[String(index)]);
  const upcomingSteps = nextStepIndex >= 0 ? steps.slice(nextStepIndex, nextStepIndex + 3) : [];

  const activityItems = useMemo(() => {
    const days = timeline.map((item) => ({
      id: `day-${item.date}`,
      date: item.last_updated || item.date,
      title: item.display_date,
      detail: [item.key_learnings[0], item.review_areas[0], `${item.session_count} 个会话 · ${item.message_count} 条消息`].filter(Boolean).join(" · "),
      kind: "day" as const,
      href: `/history/${item.date}?task_id=${goalId}`,
    }));
    const mocks = reports.map((item) => ({
      id: item.report_id,
      date: item.created_at,
      title: item.mode === "mock" ? "完成模拟面试" : "完成能力诊断",
      detail: `${item.answered_count} 题 · L${item.overall_level || 0}${item.completed ? "" : " · 提前结束"}`,
      kind: "report" as const,
      href: `/goals/${goalId}/progress?report=${item.report_id}`,
    }));
    return [...days, ...mocks]
      .filter((item) => !activityDate || item.date.slice(0, 10) === activityDate)
      .sort((a, b) => b.date.localeCompare(a.date));
  }, [activityDate, goalId, reports, timeline]);

  const refreshPlan = async () => {
    await queryClient.invalidateQueries({ queryKey: goalKeys.plan(goalId) });
    await queryClient.invalidateQueries({ queryKey: goalKeys.goal(goalId) });
    await queryClient.invalidateQueries({ queryKey: goalKeys.tasks });
  };

  const proposePlan = async (source: "goal_setup" | "progress") => {
    setWorking(true);
    try {
      await apiSend("/agent/task-plan/propose", "POST", { task_id: goalId, source });
      await refreshPlan();
      setTab("plan");
    } finally {
      setWorking(false);
    }
  };

  const confirmProposal = async () => {
    if (!plan?.draft_plan) return;
    setWorking(true);
    try {
      await apiSend("/agent/task-plan/confirm", "POST", { task_id: goalId, plan: plan.draft_plan });
      await refreshPlan();
    } finally {
      setWorking(false);
    }
  };

  const rejectProposal = async () => {
    setWorking(true);
    try {
      await apiSend("/agent/task-plan/proposal/reject", "POST", { task_id: goalId });
      await refreshPlan();
    } finally {
      setWorking(false);
    }
  };

  return (
    <aside
      className={`${open ? "translate-x-0 xl:static" : "translate-x-full xl:hidden"} fixed inset-y-0 right-0 z-50 flex w-[296px] flex-col border-l border-gray-200 bg-white transition-transform duration-200 dark:border-gray-800 dark:bg-gray-900 xl:translate-x-0`}
    >
      <div className="flex h-14 shrink-0 items-center border-b border-gray-200 px-4 dark:border-gray-800">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-gray-900 dark:text-white">目标上下文</div>
          <div className="truncate text-[11px] text-gray-400">{goal?.title || "加载中…"}</div>
        </div>
        <button onClick={onClose} className="ml-auto rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800" aria-label="关闭目标面板">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="grid shrink-0 grid-cols-4 border-b border-gray-200 px-2 dark:border-gray-800">
        {tabs.map((item) => (
          <button
            key={item.id}
            onClick={() => setTab(item.id)}
            className={`border-b-2 px-1 py-2.5 text-xs transition ${tab === item.id ? "border-indigo-600 font-medium text-indigo-700 dark:text-indigo-300" : "border-transparent text-gray-500 hover:text-gray-800 dark:text-gray-400"}`}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {tab === "overview" && (
          <div className="space-y-4">
            {plan?.draft_plan && <button onClick={() => setTab("plan")} className="flex w-full items-center gap-3 rounded-xl border border-indigo-200 bg-indigo-50 p-3 text-left dark:border-indigo-800 dark:bg-indigo-950/30"><ClipboardList className="h-4 w-4 shrink-0 text-indigo-600" /><div className="min-w-0 flex-1"><div className="text-xs font-semibold text-indigo-800 dark:text-indigo-200">有一份计划调整草案待确认</div><div className="mt-0.5 truncate text-[11px] text-gray-500">查看建议后再决定是否更新正式计划</div></div><ChevronRight className="h-4 w-4 text-indigo-400" /></button>}
            <div className="rounded-2xl border border-gray-200 p-4 dark:border-gray-700">
              <div className="flex items-center justify-between text-xs text-gray-500">
                <span>学习计划</span><span>{completed} / {steps.length || 0}</span>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
                <div className="h-full rounded-full bg-indigo-600 transition-all" style={{ width: `${completion}%` }} />
              </div>
              <div className="mt-3 text-2xl font-semibold text-gray-900 dark:text-white">{completion}%</div>
              {upcomingSteps.length > 0 && <div className="mt-3 space-y-1.5">{upcomingSteps.map((step, index) => <div key={`${step}-${index}`} className={`flex gap-2 text-xs leading-5 ${index === 0 ? "font-medium text-gray-700 dark:text-gray-200" : "text-gray-400"}`}><span>{index === 0 ? "当前" : `后续 ${index}`}</span><span className="min-w-0 flex-1">{step}</span></div>)}</div>}
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-xl bg-gray-50 p-3 dark:bg-gray-800/70"><div className="text-[11px] text-gray-400">已练题目</div><div className="mt-1 text-lg font-semibold text-gray-900 dark:text-white">{progress?.total_attempted || 0}</div></div>
              <div className="rounded-xl bg-gray-50 p-3 dark:bg-gray-800/70"><div className="text-[11px] text-gray-400">待复习</div><div className="mt-1 text-lg font-semibold text-gray-900 dark:text-white">{progress?.review_queue.length || 0}</div></div>
            </div>

            {(progress?.weak_dimensions.length || 0) > 0 && (
              <div>
                <div className="mb-2 flex items-center gap-2 text-xs font-medium text-gray-700 dark:text-gray-200"><Target className="h-3.5 w-3.5 text-amber-500" />薄弱维度</div>
                <div className="flex flex-wrap gap-1.5">
                  {progress?.weak_dimensions.slice(0, 4).map((item) => (
                    <span key={item.dimension} className="rounded-full bg-amber-50 px-2 py-1 text-[11px] text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">{item.dimension_label} {Math.round(item.avg_mastery * 100)}%</span>
                  ))}
                </div>
                <button disabled={working} onClick={() => void proposePlan("progress")} className="mt-3 flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-700 disabled:opacity-50">基于薄弱项调整计划 <ArrowRight className="h-3 w-3" /></button>
              </div>
            )}

            {steps.length === 0 && (
              <button disabled={working} onClick={() => void proposePlan("goal_setup")} className="flex w-full items-center justify-center gap-2 rounded-xl border border-indigo-200 bg-indigo-50 px-3 py-2.5 text-xs font-medium text-indigo-700 hover:bg-indigo-100 disabled:opacity-50 dark:border-indigo-800 dark:bg-indigo-950/30 dark:text-indigo-300">
                {working ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardList className="h-4 w-4" />} 生成学习计划草案
              </button>
            )}
          </div>
        )}

        {tab === "plan" && (
          <div>
            {plan?.draft_plan && (
              <div className="mb-4 rounded-2xl border border-indigo-200 bg-indigo-50/70 p-3 dark:border-indigo-800 dark:bg-indigo-950/30">
                <div className="text-xs font-semibold text-indigo-800 dark:text-indigo-200">AI 建议的计划调整</div>
                <div className="mt-2 space-y-1 text-xs leading-5 text-gray-600 dark:text-gray-300">
                  {normalizePlanSteps(plan.draft_plan).slice(0, 4).map((step, index) => <div key={index}>• {step}</div>)}
                </div>
                <div className="mt-3 flex gap-2">
                  <button disabled={working} onClick={() => void confirmProposal()} className="rounded-lg bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50">确认更新</button>
                  <button disabled={working} onClick={() => void rejectProposal()} className="rounded-lg px-2.5 py-1.5 text-xs text-gray-600 hover:bg-white dark:text-gray-300 dark:hover:bg-gray-800">暂不采用</button>
                </div>
              </div>
            )}
            {planLoading ? (
              <div className="flex items-center gap-2 text-xs text-gray-400"><Loader2 className="h-4 w-4 animate-spin" />加载计划…</div>
            ) : steps.length ? (
              <div className="space-y-2">
                {steps.map((step, index) => {
                  const checked = Boolean(checklist[String(index)]);
                  const current = !checked && steps.slice(0, index).every((_, prior) => checklist[String(prior)]);
                  return <div key={index} className={`flex gap-2 rounded-xl border p-2.5 text-xs leading-5 ${current ? "border-indigo-200 bg-indigo-50/60 dark:border-indigo-800 dark:bg-indigo-950/20" : "border-gray-100 dark:border-gray-800"}`}><span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${checked ? "bg-emerald-500 text-white" : "border border-gray-300 text-transparent dark:border-gray-600"}`}><Check className="h-3 w-3" /></span><span className={checked ? "text-gray-400 line-through" : "text-gray-700 dark:text-gray-200"}>{step}</span></div>;
                })}
              </div>
            ) : (
              <div className="py-8 text-center text-xs text-gray-400"><ClipboardList className="mx-auto mb-2 h-6 w-6" />还没有学习计划</div>
            )}
          </div>
        )}

        {tab === "activity" && (
          <div className="space-y-1">
            <label className="mb-3 flex items-center gap-2 rounded-xl border border-gray-200 px-3 py-2 text-xs text-gray-500 dark:border-gray-700"><CalendarDays className="h-3.5 w-3.5" /><span>按日期筛选</span><input type="date" value={activityDate} onChange={(event) => setActivityDate(event.target.value)} className="min-w-0 flex-1 bg-transparent text-right text-xs outline-none" />{activityDate && <button onClick={() => setActivityDate("")} className="text-indigo-600">清除</button>}</label>
            {activityItems.length ? activityItems.map((item, index) => (
              <Link key={item.id} to={item.href} className="group flex gap-3 rounded-xl px-2 py-3 hover:bg-gray-50 dark:hover:bg-gray-800/70">
                <div className="relative flex w-5 justify-center"><span className={`mt-1.5 h-2 w-2 rounded-full ${item.kind === "report" ? "bg-indigo-500" : "bg-emerald-500"}`} />{index < activityItems.length - 1 && <span className="absolute bottom-[-14px] top-4 w-px bg-gray-200 dark:bg-gray-700" />}</div>
                <div className="min-w-0 flex-1"><div className="text-xs font-medium text-gray-800 dark:text-gray-100">{item.title}</div><div className="mt-1 line-clamp-2 text-[11px] leading-4 text-gray-500">{item.detail}</div></div>
                <ChevronRight className="mt-0.5 h-3.5 w-3.5 text-gray-300 group-hover:text-gray-500" />
              </Link>
            )) : <div className="py-8 text-center text-xs text-gray-400"><Activity className="mx-auto mb-2 h-6 w-6" />完成一次学习或训练后，动态会出现在这里</div>}
          </div>
        )}

        {tab === "notes" && (
          <div>
            <div className="rounded-2xl border border-gray-200 p-4 dark:border-gray-700">
              <div className="flex items-center gap-2 text-xs font-medium text-gray-700 dark:text-gray-200"><FileText className="h-4 w-4 text-gray-400" />任务笔记</div>
              <div className="mt-3 line-clamp-6 whitespace-pre-wrap text-xs leading-5 text-gray-500">{plan?.userNotes || plan?.content || "还没有笔记。学习结束后可以生成总结，也可以手动记录。"}</div>
              <Link to={`/goals/${goalId}/notes`} className="mt-3 flex items-center gap-1 text-xs font-medium text-indigo-600">打开完整笔记 <ArrowRight className="h-3 w-3" /></Link>
            </div>
            <div className="mt-4 space-y-2 text-[11px] text-gray-500">
              {goal?.interview_date && <div className="flex items-center gap-2"><CalendarDays className="h-3.5 w-3.5" />面试日期 {goal.interview_date}</div>}
              {plan?.updated_at && <div className="flex items-center gap-2"><Clock3 className="h-3.5 w-3.5" />最近更新 {new Date(plan.updated_at).toLocaleString("zh-CN")}</div>}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
