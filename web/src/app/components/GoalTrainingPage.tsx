import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useOutletContext, useParams } from "react-router";
import {
  ArrowLeft,
  BarChart3,
  Brain,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Loader2,
  PanelRight,
  RotateCcw,
  Send,
  Sparkles,
  Square,
  Target,
} from "lucide-react";
import { apiGet, apiSend } from "../../lib/api";
import {
  goalKeys,
  rememberActiveGoal,
  useGoal,
  type InterviewReport,
} from "../../lib/goals";
import type { WorkspaceOutletContext } from "./RootLayout";

export type GoalTrainingMode = "practice" | "diagnostic" | "mock" | "review";

interface DimensionInfo {
  id: string;
  label: string;
  count: number;
}

const MODE_COPY: Record<GoalTrainingMode, { title: string; intro: string; cta: string }> = {
  practice: {
    title: "专项刷题",
    intro: "选择一个或多个能力维度，逐题获得评分、追问和复盘。",
    cta: "开始刷题",
  },
  diagnostic: {
    title: "能力诊断",
    intro: "连续 3 题覆盖不同维度，建立当前目标的初始能力基线。",
    cta: "开始 3 题诊断",
  },
  mock: {
    title: "模拟面试",
    intro: "连续作答，过程不展示评分、专家答案或缺失点，结束后统一生成报告。",
    cta: "开始模拟面试",
  },
  review: {
    title: "复习队列",
    intro: "优先复习当前目标下已经到期、掌握度较低的题目。",
    cta: "开始复习",
  },
};

interface Evaluation {
  overall_level: number;
  correctness: number;
  depth: number;
  tradeoff_reasoning: number;
  engineering_evidence: number;
  clarity: number;
  strengths: string[];
  missing_points: string[];
  improvement_advice: string[];
  next_followup?: string;
}

interface ProgressInfo {
  attempts: number;
  best_level: number;
  mastery: number;
  next_review_at: string;
}

interface QuestionResult {
  question_id: string;
  question: string;
  answer: string;
  overall_level: number;
  scores: Record<string, number>;
  strengths: string[];
  missing_points: string[];
}

type FullReport = InterviewReport & { question_results?: QuestionResult[] };

interface SessionView {
  session_id: string;
  goal_id: string | null;
  mode: GoalTrainingMode;
  phase: string;
  round: number;
  question_count: number;
  question: string | null;
  answered_count: number;
  report?: FullReport | null;
}

interface AnswerResponse {
  error?: string;
  phase: string;
  round?: number;
  question_count?: number;
  question?: string;
  evaluation?: Evaluation;
  progress?: ProgressInfo;
  followup?: string | null;
  report?: FullReport;
  message?: string;
}

interface CompletedRound {
  question: string;
  answer: string;
  evaluation?: Evaluation;
}

const SCORE_LABELS: Array<[keyof Evaluation, string]> = [
  ["correctness", "正确性"],
  ["depth", "深度"],
  ["tradeoff_reasoning", "权衡"],
  ["engineering_evidence", "工程证据"],
  ["clarity", "表达"],
];

function sessionStorageKey(goalId: string, mode: GoalTrainingMode) {
  return `interviewtutor.training.${goalId}.${mode}`;
}

function ScoreRows({ values }: { values: Record<string, number> | Evaluation }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {SCORE_LABELS.map(([key, label]) => {
        const value = Number(values[key] || 0);
        return (
          <div key={key}>
            <div className="mb-1 flex items-center justify-between text-xs text-gray-500">
              <span>{label}</span><span className="font-semibold text-gray-700 dark:text-gray-200">{value}/5</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
              <div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.max(0, Math.min(100, value * 20))}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function BriefEvaluation({ evaluation }: { evaluation: Evaluation }) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white">
          <CheckCircle2 className="h-4 w-4 text-emerald-500" /> 本题简评
        </div>
        <span className="rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300">L{evaluation.overall_level}</span>
      </div>
      <div className="mt-4"><ScoreRows values={evaluation} /></div>
      {evaluation.strengths?.length > 0 && <p className="mt-4 text-sm text-gray-600 dark:text-gray-300"><span className="font-medium text-gray-800 dark:text-gray-100">做得好：</span>{evaluation.strengths.join("、")}</p>}
      {evaluation.improvement_advice?.length > 0 && <p className="mt-2 text-sm text-gray-600 dark:text-gray-300"><span className="font-medium text-gray-800 dark:text-gray-100">下一步：</span>{evaluation.improvement_advice.join("、")}</p>}
    </div>
  );
}

function ReportCard({ report, onPropose, proposing, proposed }: {
  report: FullReport;
  onPropose: () => void;
  proposing: boolean;
  proposed: boolean;
}) {
  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-900">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-xs font-medium uppercase tracking-wider text-gray-400">{report.mode === "mock" ? "模拟面试报告" : "能力诊断报告"}</div>
            <h2 className="mt-1 text-2xl font-semibold text-gray-950 dark:text-white">总体 L{report.overall_level}</h2>
            <p className="mt-1 text-sm text-gray-500">完成 {report.answered_count}/{report.question_count} 题{report.completed ? "" : " · 未完整完成"}</p>
          </div>
          <div className="rounded-xl bg-indigo-50 p-3 text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300"><BarChart3 className="h-6 w-6" /></div>
        </div>
        <div className="mt-6"><ScoreRows values={report.scores} /></div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">优势</h3>
          {report.strengths.length ? <ul className="mt-3 space-y-2 text-sm text-gray-600 dark:text-gray-300">{report.strengths.map((item) => <li key={item}>• {item}</li>)}</ul> : <p className="mt-3 text-sm text-gray-400">继续积累训练证据后会更准确。</p>}
        </div>
        <div className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">主要缺失点</h3>
          {report.missing_points.length ? <ul className="mt-3 space-y-2 text-sm text-gray-600 dark:text-gray-300">{report.missing_points.map((item) => <li key={item}>• {item}</li>)}</ul> : <p className="mt-3 text-sm text-gray-400">本轮未识别出明确缺失点。</p>}
        </div>
      </div>

      {report.question_results && report.question_results.length > 0 && (
        <div className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">逐题摘要</h3>
          <div className="mt-3 divide-y divide-gray-100 dark:divide-gray-800">
            {report.question_results.map((item, index) => (
              <details key={`${item.question_id}-${index}`} className="py-3">
                <summary className="cursor-pointer text-sm font-medium text-gray-800 dark:text-gray-200">{index + 1}. {item.question} <span className="ml-2 text-xs text-indigo-600">L{item.overall_level}</span></summary>
                <p className="mt-2 whitespace-pre-wrap text-sm text-gray-500 dark:text-gray-400">你的回答：{item.answer}</p>
                {item.missing_points.length > 0 && <p className="mt-2 text-xs text-gray-500">缺失点：{item.missing_points.join("、")}</p>}
              </details>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-2xl border border-indigo-100 bg-indigo-50/60 p-5 dark:border-indigo-900/60 dark:bg-indigo-950/20">
        <div className="flex items-start gap-3">
          <ClipboardList className="mt-0.5 h-5 w-5 text-indigo-600" />
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white">让训练结果回流到计划</h3>
            <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">先生成调整草案，正式计划只有在你确认后才会更新。</p>
            <button disabled={proposing || proposed} onClick={onPropose} className="mt-3 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
              {proposed ? "调整草案已生成" : proposing ? "正在生成草案…" : "生成计划调整建议"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function GoalTrainingPage({ initialMode }: { initialMode: GoalTrainingMode }) {
  const { goalId = "" } = useParams<{ goalId: string }>();
  const location = useLocation();
  const queryClient = useQueryClient();
  const { isPanelOpen, setIsPanelOpen } = useOutletContext<WorkspaceOutletContext>();
  const { data: goal } = useGoal(goalId);
  const presetDimension = (location.state as { dimension?: string } | null)?.dimension;
  const [availableDimensions, setAvailableDimensions] = useState<DimensionInfo[]>([]);
  const [dimensionsLoading, setDimensionsLoading] = useState(true);
  const [dimensions, setDimensions] = useState<string[]>(presetDimension ? [presetDimension] : []);
  const [questionCount, setQuestionCount] = useState<3 | 5 | 8>(5);
  const [phase, setPhase] = useState<"setup" | "asking" | "reviewing" | "completed">("setup");
  const [sessionId, setSessionId] = useState("");
  const [question, setQuestion] = useState("");
  const [round, setRound] = useState(1);
  const [total, setTotal] = useState(initialMode === "diagnostic" ? 3 : initialMode === "mock" ? 5 : 1);
  const [answer, setAnswer] = useState("");
  const [completedRounds, setCompletedRounds] = useState<CompletedRound[]>([]);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [progress, setProgress] = useState<ProgressInfo | null>(null);
  const [followup, setFollowup] = useState("");
  const [reviewResult, setReviewResult] = useState<{ feedback: string; expert_answer: string; gap_analysis: string } | null>(null);
  const [report, setReport] = useState<FullReport | null>(null);
  const [restoredCount, setRestoredCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [error, setError] = useState("");
  const [proposing, setProposing] = useState(false);
  const [proposed, setProposed] = useState(false);
  const answerRef = useRef<HTMLTextAreaElement>(null);
  const copy = MODE_COPY[initialMode];
  const storageKey = useMemo(() => sessionStorageKey(goalId, initialMode), [goalId, initialMode]);

  useEffect(() => {
    if (goalId) rememberActiveGoal(goalId);
  }, [goalId]);

  useEffect(() => {
    let cancelled = false;
    const loadDimensions = async () => {
      setDimensionsLoading(true);
      try {
        const items = await apiGet<DimensionInfo[]>("/knowledge/dimensions");
        if (!cancelled) setAvailableDimensions(items || []);
      } catch {
        if (!cancelled) setAvailableDimensions([]);
      } finally {
        if (!cancelled) setDimensionsLoading(false);
      }
    };
    void loadDimensions();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const restore = async () => {
      setRestoring(true);
      const stored = localStorage.getItem(storageKey);
      if (!stored) {
        setRestoring(false);
        return;
      }
      try {
        const session = await apiGet<SessionView>(`/interview/session/${encodeURIComponent(stored)}`);
        if (cancelled || session.goal_id !== goalId || session.mode !== initialMode) return;
        setSessionId(session.session_id);
        setRound(session.round || 1);
        setTotal(session.question_count || 1);
        setRestoredCount(session.answered_count || 0);
        if (session.phase === "awaiting_answer" && session.question) {
          setQuestion(session.question);
          setPhase("asking");
        } else if (session.phase === "completed" && session.report) {
          setReport(session.report);
          setPhase("completed");
        } else {
          localStorage.removeItem(storageKey);
        }
      } catch {
        localStorage.removeItem(storageKey);
      } finally {
        if (!cancelled) setRestoring(false);
      }
    };
    void restore();
    return () => { cancelled = true; };
  }, [goalId, initialMode, storageKey]);

  const invalidateTrainingData = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: goalKeys.progress(goalId) }),
      queryClient.invalidateQueries({ queryKey: goalKeys.reports(goalId) }),
    ]);
  };

  const reset = () => {
    localStorage.removeItem(storageKey);
    setPhase("setup");
    setSessionId("");
    setQuestion("");
    setRound(1);
    setTotal(initialMode === "diagnostic" ? 3 : initialMode === "mock" ? questionCount : 1);
    setAnswer("");
    setCompletedRounds([]);
    setEvaluation(null);
    setProgress(null);
    setFollowup("");
    setReviewResult(null);
    setReport(null);
    setRestoredCount(0);
    setError("");
    setProposed(false);
  };

  const start = async () => {
    setLoading(true);
    setError("");
    setCompletedRounds([]);
    setEvaluation(null);
    setReport(null);
    try {
      const data = await apiSend<SessionView & { message?: string; dimension?: string }>("/interview/start", "POST", {
        goal_id: goalId,
        mode: initialMode,
        dimensions,
        companies: [],
        difficulty: 0,
        question_count: initialMode === "mock" ? questionCount : initialMode === "diagnostic" ? 3 : 1,
      });
      if (data.phase === "completed" || !data.question) {
        setError(data.message || "当前筛选下暂无可用题目");
        return;
      }
      setSessionId(data.session_id);
      setQuestion(data.question);
      setRound(data.round || 1);
      setTotal(data.question_count || 1);
      setPhase("asking");
      localStorage.setItem(storageKey, data.session_id);
      requestAnimationFrame(() => answerRef.current?.focus());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "开始训练失败");
    } finally {
      setLoading(false);
    }
  };

  const submit = async () => {
    const submitted = answer.trim();
    if (!submitted || !sessionId || loading) return;
    setLoading(true);
    setError("");
    setAnswer("");
    try {
      const data = await apiSend<AnswerResponse>("/interview/answer", "POST", { session_id: sessionId, answer: submitted });
      if (data.error) throw new Error(data.error);

      if (initialMode === "practice" || initialMode === "review") {
        setCompletedRounds([{ question, answer: submitted, evaluation: data.evaluation }]);
        setEvaluation(data.evaluation || null);
        setProgress(data.progress || null);
        setFollowup(data.followup || "");
        setPhase("reviewing");
        await invalidateTrainingData();
        return;
      }

      setCompletedRounds((items) => [...items, { question, answer: submitted, evaluation: data.evaluation }]);
      if (data.report) {
        setReport(data.report);
        setPhase("completed");
        localStorage.removeItem(storageKey);
        await invalidateTrainingData();
        void proposePlan();
      } else if (data.question) {
        setQuestion(data.question);
        setRound(data.round || round + 1);
        setTotal(data.question_count || total);
        setEvaluation(initialMode === "diagnostic" ? data.evaluation || null : null);
        setProgress(data.progress || null);
        requestAnimationFrame(() => answerRef.current?.focus());
      }
    } catch (caught) {
      setAnswer(submitted);
      setError(caught instanceof Error ? caught.message : "提交作答失败");
    } finally {
      setLoading(false);
    }
  };

  const finishReview = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await apiSend<{ error?: string; feedback: string; expert_answer: string; gap_analysis: string }>("/interview/review", "POST", { session_id: sessionId });
      if (data.error) throw new Error(data.error);
      setReviewResult(data);
      setPhase("completed");
      localStorage.removeItem(storageKey);
      await invalidateTrainingData();
      void proposePlan();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生成复盘失败");
    } finally {
      setLoading(false);
    }
  };

  const endEarly = async () => {
    if (!sessionId || loading) return;
    setLoading(true);
    setError("");
    try {
      const data = await apiSend<{ phase: string; report: FullReport | null; error?: string }>("/interview/session/end", "POST", { session_id: sessionId });
      if (data.error) throw new Error(data.error);
      localStorage.removeItem(storageKey);
      if (data.report) {
        setReport(data.report);
        setPhase("completed");
        await invalidateTrainingData();
        void proposePlan();
      } else {
        reset();
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "结束会话失败");
    } finally {
      setLoading(false);
    }
  };

  const proposePlan = async () => {
    setProposing(true);
    setError("");
    try {
      await apiSend("/agent/task-plan/propose", "POST", { task_id: goalId, source: "progress" });
      await queryClient.invalidateQueries({ queryKey: goalKeys.plan(goalId) });
      setProposed(true);
      setIsPanelOpen(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生成计划建议失败");
    } finally {
      setProposing(false);
    }
  };

  if (restoring) {
    return <div className="flex h-full items-center justify-center bg-[#f7f7f8] text-sm text-gray-500 dark:bg-gray-950"><Loader2 className="mr-2 h-4 w-4 animate-spin" />恢复训练会话…</div>;
  }

  return (
    <div className="flex h-full flex-col bg-[#f7f7f8] dark:bg-gray-950">
      <header className="shrink-0 border-b border-gray-200 bg-white px-4 py-3 dark:border-gray-800 dark:bg-gray-900 sm:px-6">
        <div className="mx-auto flex max-w-5xl items-center gap-3">
          <Link to={`/goals/${goalId}/workspace`} className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800" aria-label="返回工作区"><ArrowLeft className="h-4 w-4" /></Link>
          <div className="min-w-0">
            <div className="flex items-center gap-1 text-xs text-gray-400"><span className="truncate">{goal?.title || "面试目标"}</span><ChevronRight className="h-3 w-3" /><span>{copy.title}</span></div>
            <h1 className="truncate text-base font-semibold text-gray-950 dark:text-white">{copy.title}</h1>
          </div>
          <div className="flex-1" />
          <button onClick={() => setIsPanelOpen(!isPanelOpen)} className="hidden rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 lg:block" aria-label="目标面板"><PanelRight className="h-4 w-4" /></button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
        <div className="mx-auto max-w-4xl">
          {phase === "setup" && (
            <div className="mx-auto max-w-2xl">
              <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-900 sm:p-8">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600 dark:bg-indigo-950/40 dark:text-indigo-300">
                  {initialMode === "mock" ? <Target className="h-5 w-5" /> : initialMode === "review" ? <RotateCcw className="h-5 w-5" /> : <Brain className="h-5 w-5" />}
                </div>
                <h2 className="mt-5 text-2xl font-semibold text-gray-950 dark:text-white">{copy.title}</h2>
                <p className="mt-2 text-sm leading-6 text-gray-500 dark:text-gray-400">{copy.intro}</p>

                {initialMode === "practice" && (
                  <div className="mt-6">
                    <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-400">训练维度（可多选；不选则覆盖全部）</div>
                    {dimensionsLoading ? (
                      <div className="flex items-center gap-2 py-3 text-xs text-gray-400"><Loader2 className="h-4 w-4 animate-spin" />加载训练维度…</div>
                    ) : availableDimensions.length === 0 ? (
                      <div className="rounded-xl bg-gray-50 px-4 py-3 text-xs text-gray-500 dark:bg-gray-800/60 dark:text-gray-400">暂无可用训练维度，请先同步知识库。</div>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        {availableDimensions.map(({ id, label }) => (
                          <button key={id} onClick={() => setDimensions((items) => items.includes(id) ? items.filter((item) => item !== id) : [...items, id])} className={`rounded-full border px-3 py-1.5 text-xs transition ${dimensions.includes(id) ? "border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-300" : "border-gray-200 bg-white text-gray-500 hover:border-gray-300 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-400"}`}>{label}</button>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {initialMode === "mock" && (
                  <div className="mt-6">
                    <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-400">题目数量</div>
                    <div className="grid grid-cols-3 gap-2">
                      {([3, 5, 8] as const).map((count) => <button key={count} onClick={() => setQuestionCount(count)} className={`rounded-xl border px-3 py-3 text-sm ${questionCount === count ? "border-indigo-300 bg-indigo-50 font-semibold text-indigo-700 dark:border-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300" : "border-gray-200 text-gray-600 dark:border-gray-700 dark:text-gray-300"}`}>{count} 题{count === 5 && <span className="ml-1 text-[10px] text-gray-400">默认</span>}</button>)}
                    </div>
                    <div className="mt-4 rounded-xl bg-amber-50 px-3 py-2.5 text-xs leading-5 text-amber-800 dark:bg-amber-950/30 dark:text-amber-200">面试过程中不会出现评分或参考答案。提前结束时，至少完成 1 题才会生成未完整报告。</div>
                  </div>
                )}

                {initialMode === "diagnostic" && <div className="mt-6 rounded-xl bg-gray-50 px-4 py-3 text-sm text-gray-600 dark:bg-gray-800/60 dark:text-gray-300">系统会优先选择尚未训练或掌握度最低的不同维度，每题后仅显示简要评分。</div>}

                {error && <div className="mt-4 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-950/30 dark:text-red-300">{error}</div>}
                <button disabled={loading} onClick={() => void start()} className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
                  {loading ? <><Loader2 className="h-4 w-4 animate-spin" />正在准备题目…</> : <>{copy.cta}<ChevronRight className="h-4 w-4" /></>}
                </button>
              </div>
            </div>
          )}

          {(phase === "asking" || phase === "reviewing") && (
            <div className="space-y-4">
              <div className="flex items-center gap-3 text-xs text-gray-500">
                <span className="font-medium text-gray-700 dark:text-gray-200">第 {round} / {total} 题</span>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-800"><div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.min(100, ((phase === "reviewing" ? round : round - 1) / total) * 100)}%` }} /></div>
                {(initialMode === "diagnostic" || initialMode === "mock") && <button disabled={loading} onClick={() => void endEarly()} className="flex items-center gap-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"><Square className="h-3 w-3" />提前结束</button>}
              </div>

              {restoredCount > 0 && <div className="rounded-xl border border-gray-200 bg-white px-4 py-3 text-xs text-gray-500 dark:border-gray-800 dark:bg-gray-900">已恢复会话；此前完成的 {restoredCount} 题已计入进度。</div>}
              {initialMode === "diagnostic" && evaluation && phase === "asking" && <BriefEvaluation evaluation={evaluation} />}

              <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-800 dark:bg-gray-900 sm:p-7">
                <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-indigo-600"><Sparkles className="h-3.5 w-3.5" />面试官</div>
                <p className="whitespace-pre-wrap text-base leading-7 text-gray-900 dark:text-gray-100">{question}</p>
              </div>

              {phase === "asking" && (
                <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm dark:border-gray-800 dark:bg-gray-900">
                  <textarea ref={answerRef} value={answer} onChange={(event) => setAnswer(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submit(); } }} placeholder="组织你的回答…（Enter 提交，Shift+Enter 换行）" className="min-h-32 w-full resize-y bg-transparent px-2 py-2 text-sm leading-6 text-gray-900 outline-none placeholder:text-gray-400 dark:text-gray-100" />
                  <div className="flex items-center justify-between border-t border-gray-100 pt-3 dark:border-gray-800">
                    <span className="px-2 text-xs text-gray-400">回答会写入当前目标的独立进度</span>
                    <button disabled={!answer.trim() || loading} onClick={() => void submit()} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40">{loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}提交回答</button>
                  </div>
                </div>
              )}

              {phase === "reviewing" && evaluation && (
                <>
                  <BriefEvaluation evaluation={evaluation} />
                  {progress && <div className="rounded-xl border border-gray-200 bg-white px-4 py-3 text-xs text-gray-500 dark:border-gray-800 dark:bg-gray-900">当前掌握度 {Math.round(progress.mastery * 100)}% · 最佳 L{progress.best_level} · 已练 {progress.attempts} 次</div>}
                  {followup && <div className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"><div className="text-xs font-semibold text-gray-400">针对缺失点的追问</div><p className="mt-2 text-sm leading-6 text-gray-700 dark:text-gray-200">{followup}</p></div>}
                  {error && <div className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-950/30 dark:text-red-300">{error}</div>}
                  <button disabled={loading} onClick={() => void finishReview()} className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">{loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Brain className="h-4 w-4" />}查看专家答案与复盘</button>
                </>
              )}
              {error && phase === "asking" && <div className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-950/30 dark:text-red-300">{error}</div>}
            </div>
          )}

          {phase === "completed" && (
            <div className="space-y-4">
              {report && <ReportCard report={report} onPropose={() => void proposePlan()} proposing={proposing} proposed={proposed} />}
              {!report && reviewResult && (
                <div className="space-y-4">
                  {evaluation && <BriefEvaluation evaluation={evaluation} />}
                  <div className="rounded-2xl border border-gray-200 bg-white p-6 dark:border-gray-800 dark:bg-gray-900"><h2 className="text-sm font-semibold text-gray-900 dark:text-white">教练复盘</h2><p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-gray-600 dark:text-gray-300">{reviewResult.feedback}</p></div>
                  <details className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"><summary className="cursor-pointer text-sm font-semibold text-gray-900 dark:text-white">查看专家答案与差距分析</summary><p className="mt-4 whitespace-pre-wrap text-sm leading-7 text-gray-600 dark:text-gray-300">{reviewResult.expert_answer}</p>{reviewResult.gap_analysis && <p className="mt-4 border-t border-gray-100 pt-4 text-sm leading-7 text-gray-500 dark:border-gray-800 dark:text-gray-400">{reviewResult.gap_analysis}</p>}</details>
                </div>
              )}
              {error && <div className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-950/30 dark:text-red-300">{error}</div>}
              <div className="flex flex-wrap gap-2">
                <button onClick={reset} className="flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"><RotateCcw className="h-4 w-4" />再来一轮</button>
                <Link to={`/goals/${goalId}/progress`} className="flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"><BarChart3 className="h-4 w-4" />查看目标进度</Link>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
