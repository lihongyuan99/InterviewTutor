/**
 * 统一的 API 访问层。
 * 后端固定运行在 127.0.0.1:8001，可通过 VITE_API_BASE_URL 覆盖。
 */
export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8001/api/v1";

export const ENABLE_STREAMING: boolean =
  (import.meta.env.VITE_ENABLE_STREAMING ?? "true").toString().toLowerCase() !== "false";

/** 从错误响应体中提取可读信息 */
export async function extractErrorMessage(response: Response): Promise<string> {
  try {
    const data = await response.json();
    if (data && typeof data.detail === "string" && data.detail.trim()) {
      return data.detail;
    }
  } catch {
    // 非 JSON 响应，忽略
  }
  return `请求失败（${response.status}）`;
}

/** 统一 fetch 封装：非 2xx 时抛出带后端 detail 的 Error */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  return response;
}

/** GET JSON 便捷方法 */
export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init);
  return (await response.json()) as T;
}

/** 简历结构化数据（与后端 app/resume/models.py 对齐） */
export interface ResumeEducation {
  school: string;
  degree: string;
  major: string;
  start: string;
  end: string;
  highlights: string[];
}
export interface ResumeWork {
  company: string;
  role: string;
  start: string;
  end: string;
  description: string;
  tech_stack: string[];
  metrics: string[];
  highlights: string[];
}
export interface ResumeProject {
  name: string;
  role: string;
  period: string;
  description: string;
  tech_stack: string[];
  metrics: string[];
  highlights: string[];
}
export interface ResumeSkill {
  name: string;
  level: string;
  category: string;
}
export interface Resume {
  resume_id: string;
  user_id: string;
  source_file: string;
  source_type: string;
  raw_text: string;
  name: string;
  contact: string;
  target_role: string;
  target_companies: string[];
  summary: string;
  educations: ResumeEducation[];
  works: ResumeWork[];
  projects: ResumeProject[];
  skills: ResumeSkill[];
  honors: string[];
  mapped_dimensions: string[];
  created_at: string;
  updated_at: string;
}

export interface ResumeUploadResult {
  resume_id: string;
  source_type: string;
  source_file: string;
  resume: Resume;
}

/** 上传简历文件并解析 */
export async function uploadResume(
  file: File,
  opts: { targetRole?: string; targetCompanies?: string } = {},
): Promise<ResumeUploadResult> {
  const form = new FormData();
  form.append("file", file);
  if (opts.targetRole) form.append("target_role", opts.targetRole);
  if (opts.targetCompanies) form.append("target_companies", opts.targetCompanies);
  const response = await fetch(`${API_BASE_URL}/resume/upload`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  return (await response.json()) as ResumeUploadResult;
}

/** 删除简历 */
export async function deleteResume(resumeId: string): Promise<{ status: string; resume_id: string }> {
  return apiSend(`/resume/${resumeId}`, "DELETE");
}

/** 读取结构化简历 */
export async function getResume(resumeId: string): Promise<Resume> {
  return apiGet(`/resume/${encodeURIComponent(resumeId)}`);
}

export interface ProjectQuestionLink {
  project_name: string;
  question_id: string;
  dimension: string;
  question: string;
  score: number;
  reason: string;
  source_type: string;
}

export interface ResumeMatch {
  target_role: string;
  target_company: string;
  overall_score: number;
  dimension_scores: Record<string, number>;
  matched_points: string[];
  gap_points: string[];
  company_focus: string[];
}

export interface ResumeSuggestion {
  category: string;
  severity: string;
  target: string;
  advice: string;
}

/** 深挖：简历项目 + 实习/工作经历 → 面试官最可能追问的题目 */
export async function deepDiveResume(
  resumeId: string,
  opts: { projectNames?: string[]; limit?: number } = {},
): Promise<{
  resume_id: string;
  project_questions: ProjectQuestionLink[];
  work_questions: ProjectQuestionLink[];
}> {
  return apiSend("/resume/deep-dive", "POST", {
    resume_id: resumeId,
    project_names: opts.projectNames || null,
    limit: opts.limit || 3,
  });
}

/** 匹配度分析：简历 vs 目标公司 */
export async function matchResume(
  resumeId: string,
  opts: { targetRole?: string; targetCompany?: string } = {},
): Promise<ResumeMatch> {
  return apiSend("/resume/match", "POST", {
    resume_id: resumeId,
    target_role: opts.targetRole || "",
    target_company: opts.targetCompany || "",
  });
}

/** 优化建议 */
export async function suggestResume(
  resumeId: string,
  opts: { targetRole?: string } = {},
): Promise<{ resume_id: string; suggestions: ResumeSuggestion[] }> {
  return apiSend("/resume/suggest", "POST", {
    resume_id: resumeId,
    target_role: opts.targetRole || "",
  });
}

// ---- 深挖题「拷打」闭环 ----

export interface GrillEvaluation {
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
  mastery_delta?: number;
}

/** 开启深挖题拷打会话 */
export async function grillStart(
  resumeId: string,
  opts: { question: string; sourceName: string; sourceType: string; goalId?: string },
): Promise<{ session_id: string; phase: string; question: string; source_name: string; source_type: string }> {
  return apiSend("/resume/grill/start", "POST", {
    resume_id: resumeId,
    question: opts.question,
    source_name: opts.sourceName,
    source_type: opts.sourceType,
    goal_id: opts.goalId || null,
  });
}

/** 提交作答，现场评分 + 追问 */
export async function grillAnswer(
  sessionId: string,
  answer: string,
): Promise<{ session_id: string; phase: string; evaluation: GrillEvaluation; error?: string }> {
  return apiSend("/resume/grill/answer", "POST", { session_id: sessionId, answer });
}

/** 教练复盘 */
export async function grillReview(
  sessionId: string,
): Promise<{ session_id: string; phase: string; feedback: string; evaluation: GrillEvaluation; error?: string }> {
  return apiSend("/resume/grill/review", "POST", { session_id: sessionId });
}

/** 发送 JSON 的便捷方法（POST/PUT/PATCH/DELETE） */
export async function apiSend<T = unknown>(
  path: string,
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  body?: unknown,
  init?: RequestInit,
): Promise<T> {
  const response = await apiFetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    ...init,
  });
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}
