import { useEffect, useState } from "react";
import { Link } from "react-router";
import {
  ArrowLeft,
  Brain,
  BarChart3,
  TrendingUp,
  CalendarClock,
  Loader2,
  Target,
  AlertTriangle,
  BookX,
} from "lucide-react";
import { API_BASE_URL } from "../../lib/api";

interface DimensionStat {
  dimension: string;
  dimension_label: string;
  count: number;
  avg_mastery: number;
  avg_level: number;
}

interface ReviewItem {
  question_id: string;
  attempts: number;
  best_level: number;
  mastery: number;
  next_review_at: string;
}

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

interface ProgressData {
  review_queue: ReviewItem[];
  total_attempted: number;
  average_mastery: number;
  dimension_stats: DimensionStat[];
  wrong_questions: WrongQuestion[];
  weak_dimensions: DimensionStat[];
}

function StatCard({
  icon,
  label,
  value,
  sub,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  color: string;
}) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-2xl border border-slate-200 dark:border-gray-700 shadow-sm p-5 flex items-center gap-4">
      <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${color}`}>{icon}</div>
      <div>
        <div className="text-xs text-slate-500 dark:text-gray-400">{label}</div>
        <div className="text-2xl font-bold text-slate-800 dark:text-gray-100">{value}</div>
        {sub && <div className="text-xs text-slate-400 dark:text-gray-500">{sub}</div>}
      </div>
    </div>
  );
}

export function ProgressPage() {
  const [data, setData] = useState<ProgressData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const res = await fetch(`${API_BASE_URL}/interview/progress`);
        if (!res.ok) {
          throw new Error(`请求失败（${res.status}）`);
        }
        setData(await res.json());
      } catch (e: any) {
        setError(e.message || "加载进度失败");
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, []);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center bg-slate-50 dark:bg-gray-950">
        <Loader2 className="w-6 h-6 text-indigo-500 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center bg-slate-50 dark:bg-gray-950">
        <div className="text-sm text-red-500 dark:text-red-400">{error}</div>
      </div>
    );
  }

  const stats = data || {
    review_queue: [],
    total_attempted: 0,
    average_mastery: 0,
    dimension_stats: [],
    wrong_questions: [],
    weak_dimensions: [],
  };
  const masteryPct = Math.round(stats.average_mastery * 100);
  const maxCount = Math.max(1, ...stats.dimension_stats.map((d) => d.count));

  return (
    <div className="h-full bg-slate-50 dark:bg-gray-950 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-4 py-6">
        {/* 顶部 */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-500 flex items-center justify-center text-white">
              <Brain className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-800 dark:text-gray-100">学习进度</h1>
              <p className="text-xs text-slate-500 dark:text-gray-400">面试训练掌握度与复习计划</p>
            </div>
          </div>
          <Link
            to="/interview"
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium text-slate-600 dark:text-gray-300 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 hover:bg-slate-100 dark:hover:bg-gray-700 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            返回训练
          </Link>
        </div>

        {/* 统计卡片 */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          <StatCard
            icon={<Target className="w-6 h-6 text-white" />}
            label="已练习题目"
            value={String(stats.total_attempted)}
            color="bg-indigo-500"
          />
          <StatCard
            icon={<TrendingUp className="w-6 h-6 text-white" />}
            label="平均掌握度"
            value={`${masteryPct}%`}
            color="bg-emerald-500"
          />
          <StatCard
            icon={<CalendarClock className="w-6 h-6 text-white" />}
            label="待复习"
            value={String(stats.review_queue.length)}
            color="bg-amber-500"
          />
        </div>

        {/* 薄弱维度 */}
        {stats.weak_dimensions.length > 0 && (
          <div className="bg-white dark:bg-gray-800 rounded-2xl border border-amber-200 dark:border-amber-900/50 shadow-sm p-6 mb-6">
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle className="w-5 h-5 text-amber-500" />
              <h2 className="font-semibold text-slate-800 dark:text-gray-100">薄弱维度</h2>
              <span className="text-xs text-slate-400 dark:text-gray-500">掌握度低于 60%</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {stats.weak_dimensions.map((d) => (
                <Link
                  key={d.dimension}
                  to={`/interview`}
                  state={{ dimension: d.dimension }}
                  className="flex items-center gap-2 px-3 py-2 rounded-xl bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-800 text-sm font-medium text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/50 transition-colors"
                >
                  {d.dimension_label}
                  <span className="text-xs text-amber-500">
                    掌握 {Math.round(d.avg_mastery * 100)}%
                  </span>
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* 错题本 */}
        {stats.wrong_questions.length > 0 && (
          <div className="bg-white dark:bg-gray-800 rounded-2xl border border-slate-200 dark:border-gray-700 shadow-sm p-6 mb-6">
            <div className="flex items-center gap-2 mb-4">
              <BookX className="w-5 h-5 text-red-500" />
              <h2 className="font-semibold text-slate-800 dark:text-gray-100">错题本</h2>
              <span className="text-xs text-slate-400 dark:text-gray-500">L1-L2 需重点巩固</span>
            </div>
            <div className="space-y-3">
              {stats.wrong_questions.map((w) => (
                <div
                  key={w.question_id}
                  className="p-4 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/40"
                >
                  <div className="flex items-start gap-3">
                    <div className="w-8 h-8 rounded-lg bg-red-100 text-red-500 flex items-center justify-center text-sm font-bold shrink-0">
                      L{w.best_level}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-slate-800 dark:text-gray-100 leading-snug">
                        {w.question}
                      </div>
                      <div className="text-xs text-slate-500 dark:text-gray-400 mt-1">
                        {w.dimension_label} · 掌握 {Math.round(w.mastery * 100)}% · 已练 {w.attempts} 次
                      </div>
                      {w.missing_points.length > 0 && (
                        <div className="mt-2 text-xs text-slate-500 dark:text-gray-400">
                          <span className="text-red-400 dark:text-red-300">缺失点：</span>
                          {w.missing_points.join("、")}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 能力维度分布 */}
        <div className="bg-white dark:bg-gray-800 rounded-2xl border border-slate-200 dark:border-gray-700 shadow-sm p-6 mb-6">
          <div className="flex items-center gap-2 mb-4">
            <BarChart3 className="w-5 h-5 text-indigo-500" />
            <h2 className="font-semibold text-slate-800 dark:text-gray-100">能力维度分布</h2>
          </div>

          {stats.dimension_stats.length === 0 ? (
            <div className="text-center py-10 text-sm text-slate-400 dark:text-gray-500">
              还没有练习记录，去
              <Link to="/interview" className="text-indigo-500 hover:underline mx-1">
                开始刷题
              </Link>
              吧
            </div>
          ) : (
            <div className="space-y-4">
              {stats.dimension_stats.map((d) => (
                <div key={d.dimension}>
                  <div className="flex items-center justify-between text-sm mb-1.5">
                    <span className="font-medium text-slate-700 dark:text-gray-200">
                      {d.dimension_label}
                      <span className="text-xs text-slate-400 dark:text-gray-500 ml-2">练 {d.count} 题</span>
                    </span>
                    <span className="flex items-center gap-2 text-xs text-slate-500 dark:text-gray-400">
                      <span className="px-1.5 py-0.5 rounded bg-indigo-50 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-300 font-semibold">
                        L{d.avg_level}
                      </span>
                      掌握 {Math.round(d.avg_mastery * 100)}%
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex-1 h-2 bg-slate-100 dark:bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-indigo-400 to-indigo-600 rounded-full transition-all"
                        style={{ width: `${d.avg_mastery * 100}%` }}
                      />
                    </div>
                    <div className="w-16 h-2 bg-slate-100 dark:bg-gray-700 rounded-full overflow-hidden shrink-0">
                      <div
                        className="h-full bg-slate-300 rounded-full"
                        style={{ width: `${(d.count / maxCount) * 100}%` }}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 待复习队列 */}
        {stats.review_queue.length > 0 && (
          <div className="bg-white dark:bg-gray-800 rounded-2xl border border-slate-200 dark:border-gray-700 shadow-sm p-6">
            <div className="flex items-center gap-2 mb-4">
              <CalendarClock className="w-5 h-5 text-amber-500" />
              <h2 className="font-semibold text-slate-800 dark:text-gray-100">待复习题目</h2>
            </div>
            <div className="space-y-2">
              {stats.review_queue.map((item, idx) => (
                <div
                  key={item.question_id}
                  className="flex items-center gap-3 p-3 rounded-xl bg-slate-50 dark:bg-gray-900 border border-slate-100 dark:border-gray-700"
                >
                  <div className="w-6 h-6 rounded-full bg-amber-100 text-amber-600 flex items-center justify-center text-xs font-semibold shrink-0">
                    {idx + 1}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-slate-700 dark:text-gray-300 truncate">
                      题 {item.question_id.split("-").pop()?.slice(0, 12)}
                    </div>
                    <div className="text-xs text-slate-400 dark:text-gray-500">
                      最佳 L{item.best_level} · 已练 {item.attempts} 次
                    </div>
                  </div>
                  <span className="text-xs text-slate-500 dark:text-gray-400 shrink-0">
                    {item.next_review_at.slice(5, 16)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
