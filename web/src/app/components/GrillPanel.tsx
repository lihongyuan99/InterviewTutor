import { useState } from "react";
import { Brain, Loader2, Send } from "lucide-react";
import { grillAnswer, grillReview, grillStart, type GrillEvaluation } from "../../lib/api";
import { notifyError } from "../../lib/toast";

const SCORE_LABELS: Array<[keyof GrillEvaluation, string]> = [
  ["correctness", "正确性"],
  ["depth", "深度"],
  ["tradeoff_reasoning", "权衡"],
  ["engineering_evidence", "工程证据"],
  ["clarity", "表达"],
];

interface GrillPanelProps {
  resumeId: string;
  goalId?: string;
  question: string;
  sourceName: string;
  sourceType: string;
}

export function GrillPanel({ resumeId, goalId, question, sourceName, sourceType }: GrillPanelProps) {
  const [sessionId, setSessionId] = useState("");
  const [answer, setAnswer] = useState("");
  const [evaluation, setEvaluation] = useState<GrillEvaluation | null>(null);
  const [feedback, setFeedback] = useState("");
  const [loading, setLoading] = useState(false);
  const [phase, setPhase] = useState<"idle" | "asking" | "reviewing" | "completed">("idle");

  const start = async () => {
    setLoading(true);
    try {
      const data = await grillStart(resumeId, { question, sourceName, sourceType, goalId });
      setSessionId(data.session_id);
      setEvaluation(null);
      setFeedback("");
      setAnswer("");
      setPhase("asking");
    } catch (error) {
      notifyError(error instanceof Error ? error.message : "开始拷打失败");
    } finally {
      setLoading(false);
    }
  };

  const submit = async () => {
    const submitted = answer.trim();
    if (!submitted || !sessionId || loading) return;
    setLoading(true);
    setAnswer("");
    try {
      const data = await grillAnswer(sessionId, submitted);
      if (data.error) throw new Error(data.error);
      setEvaluation(data.evaluation);
      setPhase("reviewing");
    } catch (error) {
      setAnswer(submitted);
      notifyError(error instanceof Error ? error.message : "提交作答失败");
    } finally {
      setLoading(false);
    }
  };

  const finishReview = async () => {
    if (!sessionId || loading) return;
    setLoading(true);
    try {
      const data = await grillReview(sessionId);
      if (data.error) throw new Error(data.error);
      setFeedback(data.feedback);
      setPhase("completed");
    } catch (error) {
      notifyError(error instanceof Error ? error.message : "生成复盘失败");
    } finally {
      setLoading(false);
    }
  };

  if (phase === "idle") {
    return (
      <button
        onClick={() => void start()}
        disabled={loading}
        className="mt-3 flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
      >
        {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Brain className="h-3.5 w-3.5" />}
        拷打这道题
      </button>
    );
  }

  return (
    <div className="mt-3 rounded-xl border border-indigo-100 bg-indigo-50/50 p-3 dark:border-indigo-900/50 dark:bg-indigo-950/20">
      {phase === "asking" && (
        <div>
          <textarea
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submit();
              }
            }}
            placeholder="组织你的回答…（Enter 提交，Shift+Enter 换行）"
            className="min-h-24 w-full resize-y rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm leading-6 text-gray-900 outline-none placeholder:text-gray-400 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
          />
          <div className="mt-2 flex justify-end">
            <button
              disabled={!answer.trim() || loading}
              onClick={() => void submit()}
              className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-40"
            >
              {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
              提交回答
            </button>
          </div>
        </div>
      )}

      {(phase === "reviewing" || phase === "completed") && evaluation && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold text-gray-900 dark:text-white">拷打评分</span>
            <span className="rounded-full bg-indigo-600 px-2.5 py-1 text-xs font-semibold text-white">
              L{evaluation.overall_level}
            </span>
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            {SCORE_LABELS.map(([key, label]) => {
              const value = Number(evaluation[key] || 0);
              return (
                <div key={key}>
                  <div className="mb-1 flex items-center justify-between text-xs text-gray-500">
                    <span>{label}</span>
                    <span className="font-semibold text-gray-700 dark:text-gray-200">{value}/5</span>
                  </div>
                  <div className="h-1 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-800">
                    <div className="h-full rounded-full bg-indigo-500" style={{ width: `${Math.max(0, Math.min(100, value * 20))}%` }} />
                  </div>
                </div>
              );
            })}
          </div>

          {evaluation.strengths?.length > 0 && (
            <p className="text-sm text-gray-600 dark:text-gray-300">
              <span className="font-medium text-gray-800 dark:text-gray-100">做得好：</span>
              {evaluation.strengths.join("、")}
            </p>
          )}
          {evaluation.missing_points?.length > 0 && (
            <p className="text-sm text-gray-600 dark:text-gray-300">
              <span className="font-medium text-amber-600 dark:text-amber-400">缺失点：</span>
              {evaluation.missing_points.join("、")}
            </p>
          )}

          {phase === "reviewing" && (
            <button
              disabled={loading}
              onClick={() => void finishReview()}
              className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Brain className="h-3.5 w-3.5" />}
              查看教练复盘
            </button>
          )}

          {phase === "completed" && feedback && (
            <div className="rounded-lg bg-white p-3 dark:bg-gray-900">
              <div className="text-xs font-semibold text-gray-500">教练复盘</div>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700 dark:text-gray-300">{feedback}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
