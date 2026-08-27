import { useMemo, useState } from "react";
import { useParams } from "react-router";
import {
  Briefcase,
  Crosshair,
  FileText,
  Lightbulb,
  Loader2,
  RefreshCw,
  Target,
} from "lucide-react";
import {
  apiSend,
  deepDiveResume,
  getResume,
  matchResume,
  suggestResume,
  type ProjectQuestionLink,
  type Resume,
  type ResumeMatch,
  type ResumeSuggestion,
} from "../../lib/api";
import { goalKeys, useGoal } from "../../lib/goals";
import { useQueryClient } from "@tanstack/react-query";
import { notifyError, notifySuccess } from "../../lib/toast";
import { ResumeUploader } from "./ResumeUploader";
import { ResumePreview } from "./ResumePreview";
import { GrillPanel } from "./GrillPanel";

type TabKey = "deepdive" | "match" | "suggest";

const SEVERITY_LABEL: Record<string, { text: string; cls: string }> = {
  high: { text: "高", cls: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300" },
  medium: { text: "中", cls: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300" },
  low: { text: "低", cls: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300" },
};

const CATEGORY_LABEL: Record<string, string> = {
  star: "STAR 完整性",
  metrics: "量化成果",
  tech_stack: "技术栈",
  wording: "表述",
  missing: "缺失项",
};

export function ResumePage() {
  const { goalId } = useParams<{ goalId: string }>();
  const { data: goal } = useGoal(goalId);
  const queryClient = useQueryClient();
  const [resume, setResume] = useState<Resume | null>(null);
  const [resumeLoaded, setResumeLoaded] = useState(false);

  const [tab, setTab] = useState<TabKey>("deepdive");
  const [deepDiveLoading, setDeepDiveLoading] = useState(false);
  const [matchLoading, setMatchLoading] = useState(false);
  const [suggestLoading, setSuggestLoading] = useState(false);
  const [questions, setQuestions] = useState<ProjectQuestionLink[]>([]);
  const [workQuestions, setWorkQuestions] = useState<ProjectQuestionLink[]>([]);
  const [match, setMatch] = useState<ResumeMatch | null>(null);
  const [suggestions, setSuggestions] = useState<ResumeSuggestion[]>([]);

  // 若当前目标已关联简历，加载它
  const resumeId = useMemo(() => resume?.resume_id || goal?.resume_id || null, [resume, goal]);

  const loadExisting = async (id: string) => {
    if (resumeLoaded) return;
    try {
      const data = await getResume(id);
      setResume(data);
    } catch {
      // 简历不存在等情况忽略，保持上传区可见
    } finally {
      setResumeLoaded(true);
    }
  };

  // 首次进入且目标已关联简历时加载
  if (goal?.resume_id && !resumeLoaded && !resume) {
    void loadExisting(goal.resume_id);
  }

  const targetRole = goal?.target_role || resume?.target_role || "";
  const targetCompany = goal?.target_companies?.[0] || "";

  // 上传解析成功后，把简历关联到当前目标，并刷新 goal 缓存
  const handleParsed = async (parsed: Resume) => {
    setResume(parsed);
    setResumeLoaded(true);
    setQuestions([]);
    setWorkQuestions([]);
    setMatch(null);
    setSuggestions([]);
    if (goalId) {
      try {
        await apiSend(`/tasks/${goalId}`, "PATCH", { resume_id: parsed.resume_id });
        await queryClient.invalidateQueries({ queryKey: goalKeys.goal(goalId) });
        await queryClient.invalidateQueries({ queryKey: goalKeys.tasks });
      } catch {
        notifyError("简历已解析，但关联到目标失败");
        return;
      }
      notifySuccess("简历已保存到当前目标");
    }
  };

  const runDeepDive = async () => {
    if (!resumeId) return;
    setDeepDiveLoading(true);
    setTab("deepdive");
    try {
      const result = await deepDiveResume(resumeId);
      setQuestions(result.project_questions);
      setWorkQuestions(result.work_questions);
    } catch (error) {
      notifyError(error instanceof Error ? error.message : "深挖失败");
    } finally {
      setDeepDiveLoading(false);
    }
  };

  const runMatch = async () => {
    if (!resumeId) return;
    setMatchLoading(true);
    setTab("match");
    try {
      const result = await matchResume(resumeId, {
        targetRole: targetRole || undefined,
        targetCompany: targetCompany || undefined,
      });
      setMatch(result);
    } catch (error) {
      notifyError(error instanceof Error ? error.message : "匹配分析失败");
    } finally {
      setMatchLoading(false);
    }
  };

  const runSuggest = async () => {
    if (!resumeId) return;
    setSuggestLoading(true);
    setTab("suggest");
    try {
      const result = await suggestResume(resumeId, { targetRole: targetRole || undefined });
      setSuggestions(result.suggestions);
    } catch (error) {
      notifyError(error instanceof Error ? error.message : "生成建议失败");
    } finally {
      setSuggestLoading(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-4 py-6 lg:px-8">
        <header className="mb-6">
          <h1 className="flex items-center gap-2 text-xl font-semibold text-gray-900 dark:text-white">
            <FileText className="h-5 w-5 text-indigo-600" /> 简历分析
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            上传简历后，针对你的项目做面试官视角的深挖拷问、目标公司匹配与优化建议。
          </p>
        </header>

        {/* 上传区 */}
        {!resume ? (
          <ResumeUploader
            targetRole={targetRole || undefined}
            targetCompanies={goal?.target_companies?.join(",") || undefined}
            onParsed={(parsed) => void handleParsed(parsed)}
          />
        ) : (
          <>
            {/* 操作栏 */}
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
                {resume.name || "简历"} · {resume.projects.length} 个项目 · {resume.skills.length} 项技能
              </span>
              <div className="ml-auto flex gap-2">
                <ActionButton
                  icon={Crosshair}
                  label="项目深挖"
                  loading={deepDiveLoading}
                  onClick={() => void runDeepDive()}
                />
                <ActionButton
                  icon={Target}
                  label="匹配分析"
                  loading={matchLoading}
                  onClick={() => void runMatch()}
                />
                <ActionButton
                  icon={Lightbulb}
                  label="优化建议"
                  loading={suggestLoading}
                  onClick={() => void runSuggest()}
                />
                <button
                  onClick={() => setResume(null)}
                  className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
                >
                  <RefreshCw className="h-4 w-4" /> 重新上传
                </button>
              </div>
            </div>

            {/* 分析结果 */}
            {(questions.length > 0 || match || suggestions.length > 0) && (
              <div className="mb-4">
                <nav className="flex gap-1 border-b border-gray-200 dark:border-gray-800">
                  {questions.length > 0 && (
                    <TabButton active={tab === "deepdive"} onClick={() => setTab("deepdive")}>
                      深挖题目（{questions.length}）
                    </TabButton>
                  )}
                  {match && (
                    <TabButton active={tab === "match"} onClick={() => setTab("match")}>
                      匹配分析
                    </TabButton>
                  )}
                  {suggestions.length > 0 && (
                    <TabButton active={tab === "suggest"} onClick={() => setTab("suggest")}>
                      优化建议（{suggestions.length}）
                    </TabButton>
                  )}
                </nav>
              </div>
            )}

            {/* 深挖 */}
            {tab === "deepdive" && (
              <div className="space-y-6">
                {questions.length === 0 && workQuestions.length === 0 && !deepDiveLoading && (
                  <EmptyHint text="点击「项目深挖」，看看面试官会针对你的项目与实习/工作经历问什么。" />
                )}

                {/* 项目经历深挖 */}
                {questions.length > 0 && (
                  <div>
                    <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-800 dark:text-gray-200">
                      <Crosshair className="h-4 w-4 text-indigo-600" />
                      项目经历深挖（{questions.length}）
                    </h3>
                    <div className="space-y-3">
                      {questions.map((q, index) => (
                        <QuestionCard key={`project-${index}`} q={q} index={index} sourceLabel="项目" resumeId={resumeId} goalId={goalId} />
                      ))}
                    </div>
                  </div>
                )}

                {/* 实习/工作经历深挖 */}
                {workQuestions.length > 0 && (
                  <div>
                    <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-800 dark:text-gray-200">
                      <Briefcase className="h-4 w-4 text-indigo-600" />
                      实习 / 工作经历深挖（{workQuestions.length}）
                    </h3>
                    <div className="space-y-3">
                      {workQuestions.map((q, index) => (
                        <QuestionCard key={`work-${index}`} q={q} index={index} sourceLabel="经历" resumeId={resumeId} goalId={goalId} />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* 匹配 */}
            {tab === "match" && match && (
              <div className="space-y-4">
                <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm text-gray-500">综合匹配度</p>
                      <p className="mt-1 text-3xl font-semibold text-gray-900 dark:text-white">
                        {Math.round(match.overall_score * 100)}%
                      </p>
                    </div>
                    <div className="text-right text-sm text-gray-500">
                      <p>目标公司：{match.target_company}</p>
                      {match.target_role && <p>岗位：{match.target_role}</p>}
                    </div>
                  </div>

                  {/* 维度评分条 */}
                  {Object.keys(match.dimension_scores).length > 0 && (
                    <div className="mt-5 space-y-2.5">
                      {Object.entries(match.dimension_scores).map(([dim, score]) => (
                        <div key={dim}>
                          <div className="mb-1 flex items-center justify-between text-xs">
                            <span className="text-gray-600 dark:text-gray-300">{dim}</span>
                            <span className="text-gray-400">{Math.round(score * 100)}%</span>
                          </div>
                          <div className="h-1.5 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
                            <div
                              className="h-full rounded-full bg-indigo-500"
                              style={{ width: `${Math.round(score * 100)}%` }}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="rounded-xl border border-green-200 bg-green-50 p-4 dark:border-green-900 dark:bg-green-950/30">
                    <h3 className="mb-2 text-sm font-semibold text-green-700 dark:text-green-400">匹配亮点</h3>
                    <ul className="space-y-1.5 text-sm text-gray-700 dark:text-gray-300">
                      {match.matched_points.map((p, i) => (
                        <li key={i} className="flex gap-1.5">· {p}</li>
                      ))}
                    </ul>
                  </div>
                  <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950/30">
                    <h3 className="mb-2 text-sm font-semibold text-amber-700 dark:text-amber-400">差距与短板</h3>
                    <ul className="space-y-1.5 text-sm text-gray-700 dark:text-gray-300">
                      {match.gap_points.map((p, i) => (
                        <li key={i} className="flex gap-1.5">· {p}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            )}

            {/* 建议 */}
            {tab === "suggest" && (
              <div className="space-y-3">
                {suggestions.map((s, i) => {
                  const sev = SEVERITY_LABEL[s.severity] || SEVERITY_LABEL.medium;
                  return (
                    <div
                      key={i}
                      className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900"
                    >
                      <div className="flex items-center gap-2">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${sev.cls}`}>
                          {sev.text}优先级
                        </span>
                        <span className="text-xs text-gray-500">{CATEGORY_LABEL[s.category] || s.category}</span>
                        {s.target && <span className="text-xs text-indigo-600 dark:text-indigo-400">→ {s.target}</span>}
                      </div>
                      <p className="mt-2 text-sm leading-6 text-gray-700 dark:text-gray-300">{s.advice}</p>
                    </div>
                  );
                })}
              </div>
            )}

            {/* 简历预览 */}
            <div className="mt-6 border-t border-gray-200 pt-6 dark:border-gray-800">
              <h2 className="mb-3 text-sm font-semibold text-gray-800 dark:text-gray-200">简历内容</h2>
              <ResumePreview resume={resume} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ActionButton({
  icon: Icon,
  label,
  loading,
  onClick,
}: {
  icon: typeof Crosshair;
  label: string;
  loading: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Icon className="h-4 w-4" />}
      {label}
    </button>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`border-b-2 px-3 py-2 text-sm font-medium transition ${
        active
          ? "border-indigo-600 text-indigo-700 dark:text-indigo-400"
          : "border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
      }`}
    >
      {children}
    </button>
  );
}

function QuestionCard({
  q,
  index,
  sourceLabel,
  resumeId,
  goalId,
}: {
  q: ProjectQuestionLink;
  index: number;
  sourceLabel: string;
  resumeId: string | null;
  goalId?: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-semibold text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">
          {index + 1}
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-medium text-gray-900 dark:text-white">{q.question}</p>
          <p className="mt-1 text-xs text-indigo-600 dark:text-indigo-400">
            来自{sourceLabel}「{q.project_name}」
          </p>
          {q.reason && (
            <p className="mt-2 text-sm leading-6 text-gray-600 dark:text-gray-300">
              <span className="font-medium text-gray-500">为什么问这个：</span>
              {q.reason}
            </p>
          )}
          {resumeId && (
            <GrillPanel
              resumeId={resumeId}
              goalId={goalId}
              question={q.question}
              sourceName={q.project_name}
              sourceType={q.source_type === "work" ? "work" : "project"}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function EmptyHint({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed border-gray-300 p-8 text-center text-sm text-gray-400 dark:border-gray-700">
      {text}
    </div>
  );
}
