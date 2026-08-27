import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useOutletContext, useParams } from "react-router";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  Brain,
  CalendarClock,
  ChevronRight,
  ClipboardList,
  Loader2,
  PanelRight,
  RotateCcw,
  Target,
} from "lucide-react";
import { apiSend } from "../../lib/api";
import { goalKeys, useGoal, useGoalProgress, useGoalReports } from "../../lib/goals";
import type { WorkspaceOutletContext } from "./RootLayout";

interface WrongQuestion {
  question_id: string;
  question: string;
  dimension: string;
  dimension_label: string;
  best_level: number;
  mastery: number;
  attempts: number;
  missing_points: string[];
}

function StatCard({ label, value, hint, icon }: { label: string; value: string; hint: string; icon: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900">
      <div className="flex items-start justify-between gap-3">
        <div><div className="text-xs font-medium text-gray-400">{label}</div><div className="mt-1 text-2xl font-semibold text-gray-950 dark:text-white">{value}</div></div>
        <div className="rounded-xl bg-gray-50 p-2.5 text-indigo-600 dark:bg-gray-800 dark:text-indigo-300">{icon}</div>
      </div>
      <div className="mt-3 text-xs text-gray-400">{hint}</div>
    </div>
  );
}

export function ProgressPage() {
  const { goalId = "" } = useParams<{ goalId: string }>();
  const queryClient = useQueryClient();
  const { isPanelOpen, setIsPanelOpen } = useOutletContext<WorkspaceOutletContext>();
  const { data: goal } = useGoal(goalId);
  const { data, isLoading, error } = useGoalProgress(goalId);
  const { data: reports = [] } = useGoalReports(goalId);
  const [proposing, setProposing] = useState(false);
  const [proposalDone, setProposalDone] = useState(false);
  const [proposalError, setProposalError] = useState("");

  const proposePlan = async () => {
    setProposing(true);
    setProposalError("");
    try {
      await apiSend("/agent/task-plan/propose", "POST", { task_id: goalId, source: "progress" });
      await queryClient.invalidateQueries({ queryKey: goalKeys.plan(goalId) });
      setProposalDone(true);
      setIsPanelOpen(true);
    } catch (caught) {
      setProposalError(caught instanceof Error ? caught.message : "生成建议失败");
    } finally {
      setProposing(false);
    }
  };

  if (isLoading) {
    return <div className="flex h-full items-center justify-center bg-[#f7f7f8] text-sm text-gray-500 dark:bg-gray-950"><Loader2 className="mr-2 h-4 w-4 animate-spin" />加载目标进度…</div>;
  }

  if (error || !data) {
    return <div className="flex h-full items-center justify-center bg-[#f7f7f8] px-5 text-sm text-red-500 dark:bg-gray-950">{error instanceof Error ? error.message : "进度加载失败"}</div>;
  }

  const weak = data.weak_dimensions;
  const wrongQuestions = data.wrong_questions as unknown as WrongQuestion[];
  const latestReport = reports[0];
  const maxCount = Math.max(1, ...data.dimension_stats.map((item) => item.count));

  return (
    <div className="flex h-full flex-col bg-[#f7f7f8] dark:bg-gray-950">
      <header className="shrink-0 border-b border-gray-200 bg-white px-4 py-4 dark:border-gray-800 dark:bg-gray-900 sm:px-6">
        <div className="mx-auto flex max-w-6xl items-center gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-1 text-xs text-gray-400"><Link to={`/goals/${goalId}/workspace`} className="truncate hover:text-gray-700">{goal?.title || "面试目标"}</Link><ChevronRight className="h-3 w-3" /><span>目标进度</span></div>
            <h1 className="mt-0.5 text-xl font-semibold text-gray-950 dark:text-white">能力与复习进度</h1>
          </div>
          <div className="flex-1" />
          <Link to={`/goals/${goalId}/review`} className="hidden items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200 sm:flex"><RotateCcw className="h-4 w-4" />复习队列</Link>
          <button onClick={() => setIsPanelOpen(!isPanelOpen)} className="hidden rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 lg:block" aria-label="目标面板"><PanelRight className="h-4 w-4" /></button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
        <div className="mx-auto max-w-6xl space-y-6">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="已训练题目" value={String(data.total_attempted)} hint="仅统计当前面试目标" icon={<Target className="h-5 w-5" />} />
            <StatCard label="平均掌握度" value={`${Math.round(data.average_mastery * 100)}%`} hint="跨当前目标内全部维度" icon={<Brain className="h-5 w-5" />} />
            <StatCard label="待复习" value={String(data.review_queue.length)} hint="已到复习时间的题目" icon={<CalendarClock className="h-5 w-5" />} />
            <StatCard label="面试报告" value={String(reports.length)} hint={latestReport ? `最近一次 L${latestReport.overall_level}` : "还没有诊断或模拟报告"} icon={<BarChart3 className="h-5 w-5" />} />
          </div>

          {data.total_attempted === 0 ? (
            <div className="rounded-2xl border border-dashed border-gray-300 bg-white px-6 py-12 text-center dark:border-gray-700 dark:bg-gray-900">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600 dark:bg-indigo-950/40 dark:text-indigo-300"><Brain className="h-6 w-6" /></div>
              <h2 className="mt-4 text-lg font-semibold text-gray-900 dark:text-white">先建立能力基线</h2>
              <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-gray-500">完成 3 题诊断后，这里会展示维度掌握度、缺失点、复习队列和计划调整建议。</p>
              <Link to={`/goals/${goalId}/diagnostic`} className="mt-5 inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700">开始能力诊断<ArrowRight className="h-4 w-4" /></Link>
            </div>
          ) : (
            <>
              <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.7fr)]">
                <section className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900 sm:p-6">
                  <div className="flex items-center gap-2"><BarChart3 className="h-5 w-5 text-indigo-600" /><h2 className="text-base font-semibold text-gray-900 dark:text-white">能力维度</h2></div>
                  <div className="mt-5 space-y-5">
                    {data.dimension_stats.map((item) => (
                      <div key={item.dimension}>
                        <div className="mb-2 flex items-center justify-between gap-3 text-sm"><span className="font-medium text-gray-700 dark:text-gray-200">{item.dimension_label}<span className="ml-2 text-xs font-normal text-gray-400">{item.count} 题</span></span><span className="text-xs text-gray-500"><span className="mr-2 rounded bg-indigo-50 px-1.5 py-0.5 font-semibold text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300">L{item.avg_level}</span>{Math.round(item.avg_mastery * 100)}%</span></div>
                        <div className="flex items-center gap-3"><div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800"><div className="h-full rounded-full bg-indigo-500" style={{ width: `${item.avg_mastery * 100}%` }} /></div><div className="h-2 w-14 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800"><div className="h-full rounded-full bg-gray-300 dark:bg-gray-600" style={{ width: `${(item.count / maxCount) * 100}%` }} /></div></div>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900 sm:p-6">
                  <div className="flex items-center gap-2"><AlertTriangle className="h-5 w-5 text-amber-500" /><h2 className="text-base font-semibold text-gray-900 dark:text-white">优先补强</h2></div>
                  {weak.length > 0 ? <div className="mt-4 space-y-3">{weak.slice(0, 5).map((item, index) => <Link key={item.dimension} to={`/goals/${goalId}/practice`} state={{ dimension: item.dimension }} className="flex items-center gap-3 rounded-xl border border-gray-100 p-3 hover:border-indigo-200 hover:bg-indigo-50/40 dark:border-gray-800 dark:hover:border-indigo-900 dark:hover:bg-indigo-950/20"><span className="flex h-7 w-7 items-center justify-center rounded-full bg-amber-50 text-xs font-semibold text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">{index + 1}</span><div className="min-w-0 flex-1"><div className="truncate text-sm font-medium text-gray-800 dark:text-gray-200">{item.dimension_label}</div><div className="text-xs text-gray-400">掌握 {Math.round(item.avg_mastery * 100)}%</div></div><ChevronRight className="h-4 w-4 text-gray-300" /></Link>)}</div> : <p className="mt-4 text-sm text-gray-400">暂无明显薄弱维度。</p>}
                </section>
              </div>

              {wrongQuestions.length > 0 && (
                <section className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900 sm:p-6">
                  <h2 className="text-base font-semibold text-gray-900 dark:text-white">高价值错题与缺失点</h2>
                  <div className="mt-4 divide-y divide-gray-100 dark:divide-gray-800">{wrongQuestions.slice(0, 8).map((item) => <div key={item.question_id} className="py-4 first:pt-0 last:pb-0"><div className="flex flex-wrap items-start justify-between gap-2"><p className="max-w-3xl text-sm font-medium leading-6 text-gray-800 dark:text-gray-200">{item.question}</p><span className="rounded-full bg-red-50 px-2 py-1 text-[11px] text-red-600 dark:bg-red-950/30 dark:text-red-300">掌握 {Math.round(item.mastery * 100)}%</span></div><p className="mt-1.5 text-xs text-gray-400">{item.dimension_label} · 最佳 L{item.best_level} · {item.attempts} 次</p>{item.missing_points.length > 0 && <p className="mt-2 text-xs leading-5 text-gray-500">缺失点：{item.missing_points.join("、")}</p>}</div>)}</div>
                </section>
              )}
            </>
          )}

          {reports.length > 0 && (
            <section className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900 sm:p-6">
              <h2 className="text-base font-semibold text-gray-900 dark:text-white">诊断与模拟历史</h2>
              <div className="mt-4 divide-y divide-gray-100 dark:divide-gray-800">{reports.map((report) => <details key={report.report_id} className="py-4 first:pt-0 last:pb-0"><summary className="flex cursor-pointer list-none items-center gap-3"><span className={`rounded-lg px-2 py-1 text-xs font-medium ${report.mode === "mock" ? "bg-violet-50 text-violet-700 dark:bg-violet-950/40 dark:text-violet-300" : "bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300"}`}>{report.mode === "mock" ? "模拟" : "诊断"}</span><div className="min-w-0 flex-1"><div className="text-sm font-medium text-gray-800 dark:text-gray-200">总体 L{report.overall_level} · {report.answered_count}/{report.question_count} 题</div><div className="text-xs text-gray-400">{new Date(report.created_at).toLocaleString("zh-CN")}{report.completed ? "" : " · 未完整完成"}</div></div><ChevronRight className="h-4 w-4 text-gray-300" /></summary><div className="mt-3 grid gap-3 rounded-xl bg-gray-50 p-4 text-xs text-gray-600 dark:bg-gray-800/60 dark:text-gray-300 sm:grid-cols-2"><div><span className="font-medium text-gray-800 dark:text-gray-100">优势：</span>{report.strengths.join("、") || "暂无"}</div><div><span className="font-medium text-gray-800 dark:text-gray-100">缺失点：</span>{report.missing_points.join("、") || "暂无"}</div></div></details>)}</div>
            </section>
          )}

          {data.total_attempted > 0 && (
            <section className="rounded-2xl border border-indigo-100 bg-indigo-50/60 p-5 dark:border-indigo-900/60 dark:bg-indigo-950/20">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center"><ClipboardList className="h-6 w-6 shrink-0 text-indigo-600" /><div className="flex-1"><h2 className="text-sm font-semibold text-gray-900 dark:text-white">根据真实训练证据调整计划</h2><p className="mt-1 text-sm text-gray-600 dark:text-gray-300">先生成草案，在右侧“计划”中确认或拒绝，不会直接覆盖正式计划。</p>{proposalError && <p className="mt-1 text-xs text-red-500">{proposalError}</p>}</div><button disabled={proposing || proposalDone} onClick={() => void proposePlan()} className="shrink-0 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">{proposalDone ? "草案已生成" : proposing ? "生成中…" : "生成调整建议"}</button></div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
