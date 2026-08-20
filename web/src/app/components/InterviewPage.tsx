import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Send,
  RotateCcw,
  Target,
  Brain,
  BarChart3,
  Loader2,
  Sparkles,
  CheckCircle2,
  Lightbulb,
  TrendingUp,
  MessageCircleQuestion,
  AlertCircle,
  CalendarClock,
  BookOpen,
} from "lucide-react";
import { Link, useLocation } from "react-router";
import { MarkdownPreview } from "./MarkdownPreview";
import { API_BASE_URL, apiGet } from "../../lib/api";
import { EVENT_LLM_SETTINGS_UPDATED } from "../../lib/events";

// 维度列表（与后端 _DIMENSION_LABELS 对齐）
const DIMENSIONS: { id: string; label: string }[] = [
  { id: "architecture", label: "架构选型" },
  { id: "tool-management", label: "工具管理" },
  { id: "fault-tolerance", label: "容错与鲁棒性" },
  { id: "memory-context", label: "记忆与上下文" },
  { id: "evaluation", label: "评估与全局观" },
  { id: "multi-agent", label: "多智能体协作" },
  { id: "engineering-pitfalls", label: "工程化踩坑" },
  { id: "prompt-engineering", label: "Prompt 工程" },
  { id: "rag", label: "RAG 与检索" },
  { id: "training", label: "训练与模型" },
  { id: "ai-code-testing", label: "AI 代码测试" },
  { id: "business-ai", label: "业务 AI 工程" },
  { id: "project-deep-dive", label: "简历项目深挖" },
  { id: "agent-concepts", label: "Agent 概念" },
  { id: "engineering", label: "工程实践" },
  { id: "model", label: "模型" },
  { id: "full-stack", label: "全栈工程" },
];

// 公司列表（与知识库「来源」提取的公司对齐）
const COMPANIES: string[] = [
  "腾讯", "字节", "阿里", "淘天", "蚂蚁", "百度", "京东", "美团",
  "快手", "小红书", "拼多多", "滴滴", "携程", "bilibili", "高德", "抖音",
];

// L1-L5 等级描述
const LEVEL_DESCRIPTIONS: Record<number, string> = {
  1: "能复述定义",
  2: "能比较方案",
  3: "能给选择标准",
  4: "能讲工程实践",
  5: "能体系化设计",
};

interface Evaluation {
  overall_level: number;
  correctness: number;
  depth: number;
  tradeoff_reasoning: number;
  engineering_evidence: number;
  clarity: number;
  covered_points: string[];
  missing_points: string[];
  strengths: string[];
  improvement_advice: string[];
  next_followup: string;
  mastery_delta: number;
}

interface ProgressInfo {
  attempts: number;
  best_level: number;
  mastery: number;
  next_review_at: string;
}

interface Message {
  role: "interviewer" | "user";
  content: string;
}

const LEVEL_COLORS: Record<number, string> = {
  1: "bg-red-500",
  2: "bg-orange-500",
  3: "bg-yellow-500",
  4: "bg-lime-500",
  5: "bg-emerald-500",
};

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-slate-500 dark:text-gray-400 w-16 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 bg-slate-200 dark:bg-gray-700 rounded-full overflow-hidden">
        <div
          className={`h-full ${LEVEL_COLORS[value] || "bg-indigo-500"}`}
          style={{ width: `${(value / 5) * 100}%` }}
        />
      </div>
      <span className="text-xs font-semibold text-slate-700 dark:text-gray-200 w-4 text-right">{value}</span>
    </div>
  );
}

export function InterviewPage() {
  const location = useLocation();
  // 从路由 state 预选维度（如从进度页「薄弱维度」跳转而来）
  const presetDimension = (location.state as { dimension?: string } | null)?.dimension;
  const [dimensions, setDimensions] = useState<string[]>(
    presetDimension ? [presetDimension] : ["rag"]
  );
  const [companies, setCompanies] = useState<string[]>([]);
  const [mode, setMode] = useState<"practice" | "review">("practice");
  const [phase, setPhase] = useState<"setup" | "asking" | "reviewing">("setup");
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionId, setSessionId] = useState<string>("");
  const [answer, setAnswer] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [lastEvaluation, setLastEvaluation] = useState<Evaluation | null>(null);
  const [lastProgress, setLastProgress] = useState<ProgressInfo | null>(null);
  const [followup, setFollowup] = useState<string>("");
  const [followupAnswer, setFollowupAnswer] = useState<string>("");
  const [feedback, setFeedback] = useState<string>("");
  const [expertAnswer, setExpertAnswer] = useState<string>("");
  const [gapAnalysis, setGapAnalysis] = useState<string>("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [activeModel, setActiveModel] = useState<{ modelName: string; providerName: string } | null>(null);

  // 输入框自适应高度（最多 160px）
  const autoResizeInput = (el: HTMLTextAreaElement) => {
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, lastEvaluation, feedback, followup]);

  useEffect(() => {
    const fetchActiveModel = async () => {
      try {
        const data = await apiGet<{ modelName: string; providerName: string }>(
          "/llm-settings/active-model",
        );
        setActiveModel(data);
      } catch {
        setActiveModel(null);
      }
    };
    fetchActiveModel();
    const handler = () => fetchActiveModel();
    window.addEventListener(EVENT_LLM_SETTINGS_UPDATED, handler);
    return () => window.removeEventListener(EVENT_LLM_SETTINGS_UPDATED, handler);
  }, []);

  const toggleDimension = (id: string) => {
    setDimensions((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]
    );
  };

  const toggleCompany = (name: string) => {
    setCompanies((prev) =>
      prev.includes(name) ? prev.filter((c) => c !== name) : [...prev, name]
    );
  };

  const resetAll = () => {
    setMessages([]);
    setLastEvaluation(null);
    setLastProgress(null);
    setFollowup("");
    setFollowupAnswer("");
    setFeedback("");
    setExpertAnswer("");
    setGapAnalysis("");
    setSessionId("");
    setAnswer("");
    setError("");
  };

  const startSession = async () => {
    if (mode === "practice" && dimensions.length === 0 && companies.length === 0) {
      setError("请至少选择一个维度或公司");
      return;
    }
    setError("");
    setLoading(true);
    resetAll();

    try {
      const res = await fetch(`${API_BASE_URL}/interview/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dimensions, companies, difficulty: 0, mode }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.detail || `请求失败（${res.status}）`);
      }
      if (data.phase === "completed") {
        setError(data.message || "知识库中没有符合条件的题目");
        setPhase("setup");
        return;
      }
      setSessionId(data.session_id);
      setPhase("asking");
      setMessages([{ role: "interviewer", content: data.question || "" }]);
    } catch (e: any) {
      setError(e.message || "开始训练失败");
      setPhase("setup");
    } finally {
      setLoading(false);
    }
  };

  const submitAnswer = async () => {
    if (!answer.trim()) return;
    const submitted = answer;
    setMessages((prev) => [...prev, { role: "user", content: submitted }]);
    setAnswer("");
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE_URL}/interview/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, answer: submitted }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.detail || `请求失败（${res.status}）`);
      }
      setLastEvaluation(data.evaluation as Evaluation);
      setLastProgress(data.progress as ProgressInfo);
      setFollowup(data.followup || "");
    } catch (e: any) {
      setError(e.message || "提交作答失败");
    } finally {
      setLoading(false);
    }
  };

  const doReview = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/interview/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.detail || `请求失败（${res.status}）`);
      }
      setFeedback(data.feedback || "");
      setExpertAnswer(data.expert_answer || "");
      setGapAnalysis(data.gap_analysis || "");
      setPhase("reviewing");
    } catch (e: any) {
      setError(e.message || "获取复盘失败");
    } finally {
      setLoading(false);
    }
  };

  const nextQuestion = () => {
    resetAll();
    setPhase("setup");
  };

  return (
    <div className="flex flex-col h-full bg-slate-50 dark:bg-gray-950">
      {/* 顶部 Header - 始终固定在顶部 */}
      <header className="shrink-0 bg-white dark:bg-gray-900 border-b border-slate-200 dark:border-gray-800 px-6 py-4">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-500 flex items-center justify-center text-white">
              <Brain className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-800 dark:text-gray-100">面试训练</h1>
              <p className="text-xs text-slate-500 dark:text-gray-400">AI Agent / LLM 应用工程师面试刷题</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Link
              to="/interview/learn"
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/30 hover:bg-emerald-100 dark:hover:bg-emerald-900/50 transition-colors"
            >
              <BookOpen className="w-4 h-4" />
              学习模式
            </Link>
            <Link
              to="/interview/progress"
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium text-indigo-600 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-900/30 hover:bg-indigo-100 dark:hover:bg-indigo-900/50 transition-colors"
            >
              <BarChart3 className="w-4 h-4" />
              学习进度
            </Link>
          </div>
        </div>
      </header>

      {/* 中间滚动区：仅内容滚动，输入区在外层 footer */}
      <main className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-3xl mx-auto w-full px-4 py-6">

          {/* 错误提示 */}
          {error && (
            <div className="mb-4 flex items-start gap-2 p-3 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900/40 text-sm text-red-600 dark:text-red-400">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              {error}
            </div>
          )}

        {/* 设置面板 */}
        {phase === "setup" && (
          <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm border border-slate-200 dark:border-gray-700 p-6">
            <div className="flex items-center gap-2 mb-3">
              <Target className="w-5 h-5 text-indigo-500" />
              <h2 className="text-lg font-semibold text-slate-800 dark:text-gray-100">选择训练方式</h2>
            </div>

            {/* 模式切换 */}
            <div className="grid grid-cols-2 gap-2 mb-5">
              <button
                onClick={() => setMode("practice")}
                className={`px-4 py-3 rounded-xl text-sm font-semibold border transition-colors ${
                  mode === "practice"
                    ? "bg-indigo-50 dark:bg-indigo-900/40 border-indigo-400 dark:border-indigo-600 text-indigo-700 dark:text-indigo-300"
                    : "bg-white dark:bg-gray-800 border-slate-200 dark:border-gray-700 text-slate-600 dark:text-gray-300 hover:border-indigo-300"
                }`}
              >
                <div className="flex items-center justify-center gap-1.5">
                  <Sparkles className="w-4 h-4" />
                  刷新题
                </div>
                <div className="text-xs font-normal text-slate-400 dark:text-gray-500 mt-0.5">随机新题训练</div>
              </button>
              <button
                onClick={() => setMode("review")}
                className={`px-4 py-3 rounded-xl text-sm font-semibold border transition-colors ${
                  mode === "review"
                    ? "bg-amber-50 dark:bg-amber-900/30 border-amber-400 dark:border-amber-600 text-amber-700 dark:text-amber-300"
                    : "bg-white dark:bg-gray-800 border-slate-200 dark:border-gray-700 text-slate-600 dark:text-gray-300 hover:border-amber-300"
                }`}
              >
                <div className="flex items-center justify-center gap-1.5">
                  <CalendarClock className="w-4 h-4" />
                  复习
                </div>
                <div className="text-xs font-normal text-slate-400 dark:text-gray-500 mt-0.5">回顾到期待复习的题</div>
              </button>
            </div>

            {mode === "practice" ? (
              <>
                {/* 维度选择 */}
                <div className="mb-4">
                  <div className="text-sm font-medium text-slate-700 dark:text-gray-200 mb-2">训练维度（可多选）</div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    {DIMENSIONS.map((d) => (
                      <button
                        key={d.id}
                        onClick={() => toggleDimension(d.id)}
                        className={`px-3 py-2 rounded-lg text-sm font-medium border transition-colors ${
                          dimensions.includes(d.id)
                            ? "bg-indigo-50 dark:bg-indigo-900/40 border-indigo-400 dark:border-indigo-600 text-indigo-700 dark:text-indigo-300"
                            : "bg-white dark:bg-gray-800 border-slate-200 dark:border-gray-700 text-slate-600 dark:text-gray-300 hover:border-indigo-300"
                        }`}
                      >
                        {d.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* 公司选择（可选） */}
                <div className="mb-5">
                  <div className="text-sm font-medium text-slate-700 dark:text-gray-200 mb-2">
                    目标公司（可选，定向训练）
                    {companies.length > 0 && (
                      <span className="ml-2 text-xs text-indigo-500">已选 {companies.length} 家</span>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {COMPANIES.map((c) => (
                      <button
                        key={c}
                        onClick={() => toggleCompany(c)}
                        className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
                          companies.includes(c)
                            ? "bg-indigo-500 border-indigo-500 text-white"
                            : "bg-white dark:bg-gray-800 border-slate-200 dark:border-gray-700 text-slate-600 dark:text-gray-300 hover:border-indigo-300"
                        }`}
                      >
                        {c}
                      </button>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <p className="text-sm text-slate-500 dark:text-gray-400 mb-5">
                复习模式将从你之前练过、且已到复习时间的题目中挑选，优先掌握度较低的题。
              </p>
            )}

            <button
              onClick={startSession}
              disabled={loading}
              className={`w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-white font-semibold disabled:opacity-50 transition-colors ${
                mode === "review" ? "bg-amber-500 hover:bg-amber-600" : "bg-indigo-500 hover:bg-indigo-600"
              }`}
            >
              {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Sparkles className="w-5 h-5" />}
              {mode === "review" ? "开始复习" : "开始刷题"}
            </button>
          </div>
        )}

        {/* 对话区 */}
        {(phase === "asking" || phase === "reviewing") && (
          <div className="space-y-4">
            {/* 消息列表 */}
            <div className="space-y-4">
              {messages.map((msg, idx) => (
                <div key={idx} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                  {msg.role === "interviewer" ? (
                    <div className="max-w-[85%] bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-2xl rounded-bl-sm shadow-sm px-4 py-3">
                      <div className="flex items-center gap-2 mb-1">
                        <div className="w-6 h-6 rounded-full bg-indigo-100 dark:bg-indigo-900/40 flex items-center justify-center">
                          <Brain className="w-3.5 h-3.5 text-indigo-500" />
                        </div>
                        <span className="text-xs font-semibold text-indigo-500 dark:text-indigo-300">面试官</span>
                      </div>
                      <MarkdownPreview content={msg.content} />
                    </div>
                  ) : (
                    <div className="max-w-[85%] px-4 py-3 rounded-2xl rounded-br-sm bg-indigo-500 text-white text-sm leading-relaxed whitespace-pre-wrap">
                      {msg.content}
                    </div>
                  )}
                </div>
              ))}

              {/* 评分卡片 */}
              {lastEvaluation && (
                <div className="bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-2xl p-5 shadow-sm">
                  <div className="flex items-center gap-2 mb-1">
                    <BarChart3 className="w-5 h-5 text-indigo-500" />
                    <h3 className="font-semibold text-slate-800 dark:text-gray-100">评分结果</h3>
                  </div>

                  {/* 总分与等级说明 */}
                  <div className="flex items-center gap-4 mt-3 mb-4 p-4 rounded-xl bg-gradient-to-r from-indigo-50 to-white dark:from-indigo-900/40 dark:to-gray-800 border border-indigo-100 dark:border-indigo-800">
                    <div className="flex flex-col items-center">
                      <span className="text-4xl font-bold text-indigo-600 dark:text-indigo-400">
                        L{lastEvaluation.overall_level}
                      </span>
                      <span className="text-xs text-slate-500 dark:text-gray-400 mt-1">总体等级</span>
                    </div>
                    <div className="flex-1">
                      <div className="text-sm font-medium text-slate-700 dark:text-gray-200 mb-1">
                        {LEVEL_DESCRIPTIONS[lastEvaluation.overall_level] || "—"}
                      </div>
                      {lastProgress && (
                        <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-gray-400">
                          <span>掌握度 {Math.round(lastProgress.mastery * 100)}%</span>
                          <span>·</span>
                          <span>历史最佳 L{lastProgress.best_level}</span>
                          <span>·</span>
                          <span>第 {lastProgress.attempts} 次作答</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* 分项评分 */}
                  <div className="space-y-2 mb-4">
                    <ScoreBar label="正确性" value={lastEvaluation.correctness} />
                    <ScoreBar label="深度" value={lastEvaluation.depth} />
                    <ScoreBar label="权衡推理" value={lastEvaluation.tradeoff_reasoning} />
                    <ScoreBar label="工程证据" value={lastEvaluation.engineering_evidence} />
                    <ScoreBar label="表达清晰" value={lastEvaluation.clarity} />
                  </div>

                  {lastEvaluation.strengths.length > 0 && (
                    <div className="mb-3">
                      <div className="flex items-center gap-1 text-sm font-medium text-emerald-600 mb-1">
                        <CheckCircle2 className="w-4 h-4" /> 亮点
                      </div>
                      <ul className="text-sm text-slate-600 dark:text-gray-300 space-y-1 pl-5 list-disc">
                        {lastEvaluation.strengths.map((s, i) => (
                          <li key={i}>{s}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {lastEvaluation.missing_points.length > 0 && (
                    <div className="mb-3">
                      <div className="flex items-center gap-1 text-sm font-medium text-orange-500 mb-1">
                        <Lightbulb className="w-4 h-4" /> 缺失点
                      </div>
                      <ul className="text-sm text-slate-600 dark:text-gray-300 space-y-1 pl-5 list-disc">
                        {lastEvaluation.missing_points.map((s, i) => (
                          <li key={i}>{s}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* 面试官追问（可作答） */}
                  {followup && (
                    <div className="mt-3 p-4 rounded-xl bg-indigo-50 dark:bg-indigo-900/30 border border-indigo-100 dark:border-indigo-800">
                      <div className="flex items-center gap-1.5 text-xs font-semibold text-indigo-600 dark:text-indigo-300 mb-2">
                        <MessageCircleQuestion className="w-4 h-4" /> 面试官追问
                      </div>
                      <p className="text-sm text-slate-700 dark:text-gray-300 mb-3">{followup}</p>
                      {!feedback && (
                        <div className="flex items-end gap-2">
                          <textarea
                            value={followupAnswer}
                            onChange={(e) => setFollowupAnswer(e.target.value)}
                            placeholder="针对追问补充回答（可选）..."
                            className="flex-1 resize-none px-3 py-2 text-sm bg-white dark:bg-gray-800 text-slate-800 dark:text-gray-100 border border-indigo-200 dark:border-indigo-700 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-400"
                            rows={2}
                          />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* 复盘反馈 */}
              {feedback && (
                <div className="bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-2xl p-5 shadow-sm">
                  <div className="flex items-center gap-2 mb-3">
                    <Sparkles className="w-5 h-5 text-indigo-500" />
                    <h3 className="font-semibold text-slate-800 dark:text-gray-100">教练复盘</h3>
                  </div>
                  <MarkdownPreview content={feedback} />

                  {expertAnswer && (
                    <div className="mt-4 p-4 rounded-xl bg-slate-50 dark:bg-gray-900 border border-slate-200 dark:border-gray-700">
                      <div className="text-xs font-semibold text-slate-500 dark:text-gray-400 mb-2">高手答（参考答案）</div>
                      <MarkdownPreview content={expertAnswer} />
                    </div>
                  )}

                  {gapAnalysis && (
                    <div className="mt-3 p-4 rounded-xl bg-amber-50 dark:bg-amber-900/30 border border-amber-100 dark:border-amber-800">
                      <div className="text-xs font-semibold text-amber-600 dark:text-amber-400 mb-2">差距分析</div>
                      <MarkdownPreview content={gapAnalysis} />
                    </div>
                  )}

                  <button
                    onClick={nextQuestion}
                    className="mt-4 w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-indigo-200 dark:border-indigo-700 text-indigo-600 dark:text-indigo-300 font-medium hover:bg-indigo-50 dark:hover:bg-indigo-900/40 transition-colors"
                  >
                    <RotateCcw className="w-4 h-4" />
                    再来一题
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

          <div ref={bottomRef} />
        </div>
      </main>

      {/* 底部 Footer - 始终固定在视口底部 */}
      <footer className="shrink-0 bg-white dark:bg-gray-900 border-t border-slate-200 dark:border-gray-800 px-4 py-3">
        {phase === "asking" && (
          <div className="max-w-3xl mx-auto">
            {!lastEvaluation ? (
              <>
                {/* 主输入容器：聚焦时渐变边框 + 阴影提升 */}
                <div
                  className="relative rounded-2xl border border-indigo-200/80 dark:border-indigo-700/60
                             bg-white/70 dark:bg-gray-800/70 backdrop-blur-sm px-3 py-2.5
                             shadow-[0_8px_24px_-12px_rgba(99,102,241,0.35)] dark:shadow-[0_8px_24px_-12px_rgba(99,102,241,0.5)]
                             focus-within:border-indigo-400 dark:focus-within:border-indigo-400
                             focus-within:shadow-[0_8px_28px_-8px_rgba(99,102,241,0.5)]
                             transition-all"
                >
                  <div className="flex items-end gap-3">
                    {/* 左侧 Logo 图标 */}
                    <div className="w-9 h-9 shrink-0 mb-0.5 rounded-xl overflow-hidden
                                    bg-indigo-100/60 dark:bg-indigo-900/30
                                    ring-1 ring-indigo-200/60 dark:ring-indigo-700/40
                                    flex items-center justify-center">
                      <img src="/img/logo.svg" alt="" className="w-7 h-7" />
                    </div>
                    <textarea
                      ref={inputRef}
                      value={answer}
                      onChange={(e) => {
                        setAnswer(e.target.value);
                        autoResizeInput(e.target);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          submitAnswer();
                        }
                      }}
                      placeholder="写下你对这道题的完整作答..."
                      className="flex-1 resize-none bg-transparent px-1 py-2
                                 text-sm text-slate-800 dark:text-gray-100
                                 placeholder:text-slate-400 dark:placeholder:text-gray-500
                                 focus:outline-none leading-relaxed"
                      rows={1}
                    />
                    <button
                      onClick={submitAnswer}
                      disabled={loading || !answer.trim()}
                      aria-label="提交作答"
                      className="w-10 h-10 flex items-center justify-center rounded-xl text-white
                                 bg-gradient-to-br from-indigo-500 to-violet-600
                                 shadow-lg shadow-indigo-500/30
                                 hover:from-indigo-600 hover:to-violet-700
                                 hover:shadow-xl hover:shadow-indigo-500/40
                                 disabled:opacity-40 disabled:cursor-not-allowed disabled:shadow-none
                                 transition-all duration-200"
                    >
                      {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                {/* 底部辅助行：居中布局 - 快捷键 + 模型徽章 */}
                <div className="mt-3 flex flex-wrap items-center justify-center gap-x-3 gap-y-2 text-xs text-slate-500 dark:text-gray-400">
                  <div className="flex items-center gap-1.5">
                    <Sparkles className="w-3.5 h-3.5 text-indigo-500" />
                    <span>按 Enter 提交，</span>
                    <kbd className="px-1.5 py-0.5 rounded-md bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 font-mono text-[10px] text-slate-600 dark:text-gray-300">
                      Shift + Enter
                    </kbd>
                    <span>换行</span>
                  </div>
                  {activeModel && (
                    <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full
                                    bg-indigo-50/80 dark:bg-indigo-900/30
                                    border border-indigo-200/70 dark:border-indigo-700/50
                                    text-indigo-600 dark:text-indigo-300">
                      <span className="inline-block w-1.5 h-1.5 rounded-full
                                       bg-gradient-to-br from-indigo-500 to-violet-500
                                       shadow-[0_0_6px_rgba(139,92,246,0.6)]" />
                      <span className="font-medium">{activeModel.modelName}</span>
                      <span className="text-indigo-400/80">·</span>
                      <span className="text-indigo-500/80">{activeModel.providerName}</span>
                    </div>
                  )}
                  <div className="flex items-center gap-1.5">
                    <BarChart3 className="w-3.5 h-3.5 text-indigo-500" />
                    <span>基于 L1–L5 标准评分</span>
                  </div>
                </div>
              </>
            ) : (
              /* 评分后：查看复盘的 CTA 按钮浮在底部 */
              <button
                onClick={doReview}
                disabled={loading}
                className="w-full flex items-center justify-center gap-2
                           px-4 py-3 rounded-2xl text-white font-semibold
                           bg-gradient-to-r from-indigo-500 to-violet-600
                           shadow-md shadow-indigo-500/25
                           hover:from-indigo-600 hover:to-violet-700
                           hover:shadow-lg hover:shadow-indigo-500/30
                           disabled:opacity-50 transition-all duration-200"
              >
                {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <TrendingUp className="w-5 h-5" />}
                查看复盘与高手答
              </button>
            )}
          </div>
        )}
      </footer>
    </div>
  );
}
