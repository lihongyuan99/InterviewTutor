import { Link, useNavigate, useOutletContext, useParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  BookOpen,
  Building2,
  CalendarDays,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Circle,
  Loader2,
  MessageCircleQuestion,
  PanelRightClose,
  PanelRightOpen,
  Send,
  Sparkles,
  Square,
  Target,
  XCircle,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { MarkdownPreview } from "./MarkdownPreview";
import { API_BASE_URL, ENABLE_STREAMING, apiSend } from "../../lib/api";
import { clearDraftTask, loadDraftTask } from "../../lib/draftTask";
import { normalizePlanSteps, type TaskPlan } from "../../lib/plan";
import { EVENT_REQUEST_PLAN } from "../../lib/events";
import { apiGet } from "../../lib/api";
import { goalKeys, rememberActiveGoal, useGoal } from "../../lib/goals";
import { ModelSwitcher } from "./ModelSwitcher";

interface ReplyMetrics {
  elapsed_ms: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  llm_calls: number;
}

type ProcessStepStatus = "pending" | "active" | "complete" | "stopped" | "error";
type ReplyProcessState = "running" | "complete" | "stopped" | "error";

interface ProcessStep {
  id: "analyze" | "modules" | "compose";
  label: string;
  detail?: string;
  status: ProcessStepStatus;
}

interface ReplyProcess {
  state: ReplyProcessState;
  expanded: boolean;
  steps: ProcessStep[];
}

interface Message {
  id: string;
  role: "user" | "assistant" | "divider";
  content: string;
  timestamp: string;
  planProposal?: TaskPlan;
  planConfirmed?: boolean;
  planError?: string;
  suggestedReplies?: string[];
  metrics?: ReplyMetrics;
  process?: ReplyProcess;
}

interface OutletContext {
  isPanelOpen: boolean;
  setIsPanelOpen: (open: boolean) => void;
}

interface HistorySession {
  session_id: string;
  task_id: string;
  topic: string;
  last_updated: string;
  message_count: number;
}

interface TaskSessionsResponse {
  task_id: string;
  sessions: HistorySession[];
}

interface SessionMessage {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  metrics?: ReplyMetrics;
}

interface SessionMessagesResponse {
  session_id: string;
  task_id: string;
  topic: string;
  last_updated: string;
  messages: SessionMessage[];
}

interface StreamEvent {
  event: "start" | "delta" | "done" | "error" | "interrupted" | "intent" | "node" | "progress";
  data: Record<string, any>;
}

const SUMMARY_TRIGGER = "\u751f\u6210\u5b66\u4e60\u603b\u7ed3";

const MODULE_LABELS: Record<string, string> = {
  tutor_answer: "知识讲解",
  judge: "回答评估",
  inquiry: "引导追问",
  summary: "生成总结",
  plan: "制定学习计划",
  concluding: "整理学习笔记",
};

function createInitialReplyProcess(): ReplyProcess {
  return {
    state: "running",
    expanded: true,
    steps: [
      { id: "analyze", label: "理解问题", status: "active" },
      { id: "compose", label: "组织回复", status: "pending" },
    ],
  };
}

function processAfterAnalysis(process: ReplyProcess | undefined, modulesValue: unknown): ReplyProcess {
  const current = process ?? createInitialReplyProcess();
  const rawModules = Array.isArray(modulesValue)
    ? modulesValue.filter((item): item is string => typeof item === "string")
    : [];
  const moduleLabels = rawModules
    .map((moduleName) => MODULE_LABELS[moduleName])
    .filter((label): label is string => Boolean(label));
  const hasModules = rawModules.length > 0;

  return {
    ...current,
    state: "running",
    steps: [
      { id: "analyze", label: "理解问题", status: "complete" },
      ...(hasModules
        ? [{
            id: "modules" as const,
            label: "调用教学模块",
            detail: moduleLabels.length > 0 ? moduleLabels.join("、") : "处理学习请求",
            status: "active" as const,
          }]
        : []),
      {
        id: "compose",
        label: "组织回复",
        status: hasModules ? "pending" : "active",
      },
    ],
  };
}

function processForGenericProgress(process: ReplyProcess | undefined): ReplyProcess {
  const current = process ?? createInitialReplyProcess();
  const hasDetailedProgress = current.steps.some(
    (step) => step.id === "modules" || (step.id === "compose" && step.status === "active"),
  );
  if (hasDetailedProgress) {
    return current;
  }
  return processAfterAnalysis(current, ["unknown"]);
}

function processForComposition(process: ReplyProcess | undefined): ReplyProcess {
  const current = process ?? createInitialReplyProcess();
  return {
    ...current,
    state: "running",
    steps: current.steps.map((step) => ({
      ...step,
      status: step.id === "compose" ? "active" : "complete",
    })),
  };
}

function completeReplyProcess(process: ReplyProcess | undefined): ReplyProcess {
  const current = process ?? createInitialReplyProcess();
  return {
    ...current,
    state: "complete",
    expanded: false,
    steps: current.steps.map((step) => ({ ...step, status: "complete" })),
  };
}

function finishReplyProcess(
  process: ReplyProcess | undefined,
  state: "stopped" | "error",
): ReplyProcess {
  const current = process ?? createInitialReplyProcess();
  const terminalStatus: ProcessStepStatus = state === "stopped" ? "stopped" : "error";
  let markedTerminal = false;
  const steps = current.steps.map((step) => {
    if (!markedTerminal && step.status === "active") {
      markedTerminal = true;
      return { ...step, status: terminalStatus };
    }
    return step;
  });

  return {
    ...current,
    state,
    expanded: true,
    steps,
  };
}

function stopReplyMessage(message: Message): Message {
  return {
    ...message,
    content: message.content.includes("[已停止生成]")
      ? message.content
      : `${message.content}${message.content ? "\n\n" : ""}[已停止生成]`,
    process: finishReplyProcess(message.process, "stopped"),
  };
}

function processTitle(process: ReplyProcess): string {
  if (process.state === "complete") return `已完成 ${process.steps.length} 个步骤`;
  if (process.state === "stopped") return "生成已停止";
  if (process.state === "error") return "处理失败";
  const activeStep = process.steps.find((step) => step.status === "active");
  return activeStep ? `正在${activeStep.label}` : "正在处理请求";
}

function ProcessStatusIcon({ status }: { status: ProcessStepStatus }) {
  if (status === "active") {
    return <Loader2 className="h-4 w-4 shrink-0 animate-spin text-indigo-500" aria-hidden="true" />;
  }
  if (status === "complete") {
    return <CheckCircle className="h-4 w-4 shrink-0 text-emerald-500" aria-hidden="true" />;
  }
  if (status === "stopped") {
    return <Square className="h-3.5 w-3.5 shrink-0 text-amber-500" aria-hidden="true" />;
  }
  if (status === "error") {
    return <XCircle className="h-4 w-4 shrink-0 text-red-500" aria-hidden="true" />;
  }
  return <Circle className="h-3.5 w-3.5 shrink-0 text-gray-300 dark:text-gray-600" aria-hidden="true" />;
}

function ReplyProcessCard({
  messageId,
  process,
  onToggle,
}: {
  messageId: string;
  process: ReplyProcess;
  onToggle: () => void;
}) {
  const panelId = `reply-process-${messageId}`;
  const summaryStatus: ProcessStepStatus =
    process.state === "running" ? "active" : process.state;

  return (
    <div className="mb-3 w-full overflow-hidden rounded-xl border border-indigo-100 bg-indigo-50/60 dark:border-indigo-800/70 dark:bg-indigo-950/30">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={process.expanded}
        aria-controls={panelId}
        className="flex w-full items-center gap-2.5 px-4 py-3 text-left text-sm font-medium text-gray-700 transition-colors hover:bg-indigo-100/60 dark:text-gray-200 dark:hover:bg-indigo-900/30"
      >
        <ProcessStatusIcon status={summaryStatus} />
        <span className="flex-1">{processTitle(process)}</span>
        {process.expanded ? (
          <ChevronDown className="h-4 w-4 text-gray-400" aria-hidden="true" />
        ) : (
          <ChevronRight className="h-4 w-4 text-gray-400" aria-hidden="true" />
        )}
      </button>
      {process.expanded && (
        <div id={panelId} className="space-y-2.5 border-t border-indigo-100 px-4 py-3 dark:border-indigo-800/70">
          {process.steps.map((step) => (
            <div key={step.id} className="flex items-start gap-2.5 text-sm">
              <ProcessStatusIcon status={step.status} />
              <div className="min-w-0">
                <div className="text-gray-700 dark:text-gray-200">{step.label}</div>
                {step.detail && (
                  <div className="mt-0.5 text-gray-500 dark:text-gray-400">{step.detail}</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function formatTime(date = new Date()) {
  return date.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function normalizeReplyMetrics(value: unknown): ReplyMetrics | undefined {
  if (!value || typeof value !== "object") return undefined;
  const raw = value as Record<string, unknown>;
  const numberValue = (key: string) => {
    const parsed = Number(raw[key]);
    return Number.isFinite(parsed) ? Math.max(0, Math.round(parsed)) : 0;
  };
  return {
    elapsed_ms: numberValue("elapsed_ms"),
    input_tokens: numberValue("input_tokens"),
    output_tokens: numberValue("output_tokens"),
    total_tokens: numberValue("total_tokens"),
    llm_calls: numberValue("llm_calls"),
  };
}

function formatElapsed(elapsedMs: number) {
  if (elapsedMs < 1000) return `${elapsedMs} ms`;
  const seconds = elapsedMs / 1000;
  return `${seconds < 10 ? seconds.toFixed(1) : seconds.toFixed(0)} 秒`;
}

function formatTokens(tokens: number) {
  return Math.max(0, Math.round(tokens)).toLocaleString("zh-CN");
}

function makeMessage(role: "user" | "assistant", content: string): Message {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role,
    content,
    timestamp: formatTime(),
  };
}

function createChatSessionId(taskId: string): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  const date = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return `${taskId}__${date}__${time}`;
}

export function TutorSession({ readOnly = false }: { readOnly?: boolean }) {
  const { taskId, goalId } = useParams<{ taskId: string; goalId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const routeTaskId = goalId || taskId;
  const rawTaskId = routeTaskId ? (routeTaskId.startsWith("task_") ? routeTaskId.slice(5) : routeTaskId) : "";
  const currentTaskId = goalId
    ? goalId
    : taskId
      ? (taskId.startsWith("task_") ? taskId : `task_${taskId}`)
      : "task_default";
  const { data: goal } = useGoal(currentTaskId === "task_default" ? undefined : currentTaskId);
  const context = useOutletContext<OutletContext>();
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isSummarizing, setIsSummarizing] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [confirmingPlanId, setConfirmingPlanId] = useState<string | null>(null);
  const [taskTitleDisplay, setTaskTitleDisplay] = useState("学习任务");
  const [isStopping, setIsStopping] = useState(false);
  const [showAcceptNoteButton, setShowAcceptNoteButton] = useState(false);
  const [isAcceptingNote, setIsAcceptingNote] = useState(false);
  const [latestSummary, setLatestSummary] = useState("");
  const [draftTask, setDraftTask] = useState<{ id: string; title: string; icon: string } | null>(() =>
    loadDraftTask()
  );
  const [planStatus, setPlanStatus] = useState<string | null>(null);
  const summaryAssistantIdRef = useRef<string | null>(null);
  const summaryBufferRef = useRef<string>("");
  const activeAssistantIdRef = useRef<string | null>(null);
  const activeSessionIdRef = useRef<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const isComposingRef = useRef(false);
  const compositionEndedAtRef = useRef(0);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const [isGeneratingGoalPlan, setIsGeneratingGoalPlan] = useState(false);

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);

  useEffect(() => () => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
  }, []);

  const updateAssistantMessage = (
    assistantId: string,
    updater: (message: Message) => Message,
  ) => {
    setMessages((prev) =>
      prev.map((message) =>
        message.id === assistantId ? updater(message) : message
      )
    );
  };

  const toggleReplyProcess = (assistantId: string) => {
    updateAssistantMessage(assistantId, (message) =>
      message.process
        ? {
            ...message,
            process: {
              ...message.process,
              expanded: !message.process.expanded,
            },
          }
        : message
    );
  };

  const readStreamResponse = async (
    response: Response,
    assistantId: string,
    signal: AbortSignal,
  ): Promise<{ sessionId?: string; isConcluded?: boolean; planProposal?: TaskPlan | null; planStatus?: string | null; suggestedReplies?: string[]; metrics?: ReplyMetrics }> => {
    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("流式响应不可读");
    }

    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let finalSessionId: string | undefined;
    let finalConcluded = false;
    let finalPlan: TaskPlan | null = null;
    let finalPlanStatus: string | null | undefined;
    let finalSuggestedReplies: string[] | undefined;
    let finalMetrics: ReplyMetrics | undefined;
    let interrupted = false;
    let receivedDone = false;

    while (true) {
      if (signal.aborted) {
        await reader.cancel().catch(() => undefined);
        throw new DOMException("The operation was aborted", "AbortError");
      }
      const { value, done } = await reader.read();
      if (signal.aborted) {
        await reader.cancel().catch(() => undefined);
        throw new DOMException("The operation was aborted", "AbortError");
      }
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let idx = buffer.indexOf("\n");
      while (idx >= 0) {
        const line = buffer.slice(0, idx).trim();
        buffer = buffer.slice(idx + 1);
        if (line) {
          const evt = JSON.parse(line) as StreamEvent;
          if (evt.event === "start") {
            if (evt.data?.session_id) {
              finalSessionId = String(evt.data.session_id);
              activeSessionIdRef.current = finalSessionId;
              setActiveSessionId(finalSessionId);
            }
          } else if (evt.event === "intent") {
            const intentStatus = String(evt.data?.status ?? "");
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              process:
                intentStatus === "analyzed"
                  ? processAfterAnalysis(message.process, evt.data?.modules)
                  : message.process ?? createInitialReplyProcess(),
            }));
          } else if (evt.event === "progress") {
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              process: Array.isArray(evt.data?.modules)
                ? processAfterAnalysis(message.process, evt.data.modules)
                : processForGenericProgress(message.process),
            }));
          } else if (evt.event === "node") {
            if (evt.data?.status === "processing") {
              updateAssistantMessage(assistantId, (message) => ({
                ...message,
                process: processForComposition(message.process),
              }));
            }
          } else if (evt.event === "delta") {
            const delta = String(evt.data?.text ?? "");
            if (delta) {
              updateAssistantMessage(assistantId, (message) => ({
                ...message,
                content: message.content + delta,
                process: processForComposition(message.process),
              }));
              if (summaryAssistantIdRef.current === assistantId) {
                summaryBufferRef.current += delta;
              }
            }
          } else if (evt.event === "interrupted") {
            interrupted = true;
            updateAssistantMessage(assistantId, stopReplyMessage);
          } else if (evt.event === "done") {
            receivedDone = true;
            if (evt.data?.session_id) {
              finalSessionId = String(evt.data.session_id);
            }
            finalConcluded = Boolean(evt.data?.is_concluded);
            if (evt.data?.plan_proposal) {
              finalPlan = evt.data.plan_proposal as TaskPlan;
            }
            if (typeof evt.data?.plan_status !== "undefined") {
              finalPlanStatus = evt.data.plan_status as string | null;
            }
            if (Array.isArray(evt.data?.suggested_replies)) {
              finalSuggestedReplies = evt.data.suggested_replies.map((item: any) => String(item));
            }
            finalMetrics = normalizeReplyMetrics(evt.data?.metrics);
            updateAssistantMessage(assistantId, (message) => ({
              ...message,
              metrics: finalMetrics ?? message.metrics,
              process: completeReplyProcess(message.process),
            }));
            // 如果是总结完成，显示接受笔记更新按钮
            if (finalConcluded) {
              setShowAcceptNoteButton(true);
            }
          } else if (evt.event === "error") {
            const err = evt.data?.message || "流式响应失败";
            throw new Error(String(err));
          }
        }
        idx = buffer.indexOf("\n");
      }
    }

    // 如果被中断，不要返回正常的完成状态
    if (interrupted) {
      return { sessionId: finalSessionId, isConcluded: false, planProposal: null };
    }
    if (!receivedDone) {
      throw new Error("流式响应提前结束");
    }

    return { sessionId: finalSessionId, isConcluded: finalConcluded, planProposal: finalPlan, planStatus: finalPlanStatus, suggestedReplies: finalSuggestedReplies, metrics: finalMetrics };
  };

  const fallbackSendMessage = async (
    messageText: string,
    assistantId: string,
    sessionId: string,
    signal?: AbortSignal,
  ) => {
    const planHint = false;
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        task_id: currentTaskId,
        session_id: sessionId,
        message: messageText,
        topic: taskTitleDisplay,
        plan_hint: planHint,
      }),
      signal,
    });

    const data = await response.json();
    if (!response.ok) {
      const detail = data?.detail || `请求失败（${response.status}）`;
      throw new Error(detail);
    }

    const replyText = data?.reply || "抱歉，我暂时没有生成有效回复。";

    if (messageText === SUMMARY_TRIGGER) {
      setLatestSummary(replyText);
    }
    if (data?.session_id) {
      activeSessionIdRef.current = data.session_id;
      setActiveSessionId(data.session_id);
    }
    if (typeof data?.plan_status !== "undefined") {
      setPlanStatus(data.plan_status ?? null);
    }
    const suggestedReplies = Array.isArray(data?.suggested_replies)
      ? data.suggested_replies.map((item: any) => String(item))
      : undefined;
    const metrics = normalizeReplyMetrics(data?.metrics);
    updateAssistantMessage(assistantId, (message) => ({
      ...message,
      content: replyText,
      planProposal: data?.plan_proposal
        ? data.plan_proposal as TaskPlan
        : message.planProposal,
      suggestedReplies: suggestedReplies ?? message.suggestedReplies,
      metrics: metrics ?? message.metrics,
      process: completeReplyProcess(message.process),
    }));

    // 如果是总结请求，重置 isSummarizing 状态并显示接受笔记更新按钮
    if (data?.is_concluded) {
      setIsSummarizing(false);
      setShowAcceptNoteButton(true);
    } else {
      // 备用逻辑：如果用户发送的是SUMMARY_TRIGGER，也显示按钮
      if (messageText === SUMMARY_TRIGGER) {
        setShowAcceptNoteButton(true);
      }
    }
  };

  // Provide default values if context is undefined
  const isPanelOpen = context?.isPanelOpen ?? true;
  const setIsPanelOpen = context?.setIsPanelOpen ?? (() => {});

  const isDraftTask = Boolean(draftTask && currentTaskId === draftTask.id);
  const isPlanActive = Boolean(
    planStatus && ["await_confirm", "await_plan_confirm", "await_exit_confirm", "collecting"].includes(planStatus)
  );
  const isPlanPaused = planStatus === "paused";
  const currentDate = new Date().toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
  });
  useEffect(() => {
    if (goalId) rememberActiveGoal(goalId);
  }, [goalId]);
  useEffect(() => {
    let cancelled = false;
    const fallbackTitle = taskId ? "学习任务" : "欢迎使用 InterviewTutor";

    if (goal) {
      setTaskTitleDisplay(goal.title);
      return () => {
        cancelled = true;
      };
    }

    if (isDraftTask) {
      setTaskTitleDisplay(draftTask?.title || "新的学习");
      return () => {
        cancelled = true;
      };
    }

    const loadTaskTitle = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/notes/task?task_id=${currentTaskId}`);
        if (!response.ok) {
          throw new Error("failed");
        }
        const data = await response.json();
        const resolved = data?.taskTitle || fallbackTitle;
        if (!cancelled) {
          setTaskTitleDisplay(resolved);
        }
      } catch {
        if (!cancelled) {
          setTaskTitleDisplay(fallbackTitle);
        }
      }
    };

    void loadTaskTitle();
    return () => {
      cancelled = true;
    };
  }, [currentTaskId, rawTaskId, taskId, goal]);
  useEffect(() => {
    let isCancelled = false;

    const loadHistory = async () => {
      setIsLoadingHistory(true);
      setErrorText(null);

      if (isDraftTask) {
        setActiveSessionId(null);
        setPlanStatus(null);
        setMessages([]);
        setIsLoadingHistory(false);
        return;
      }

      try {
        const sessionsResp = await fetch(`${API_BASE_URL}/history/tasks/${currentTaskId}/sessions`);
        if (!sessionsResp.ok) {
          throw new Error(`读取任务会话失败（${sessionsResp.status}）`);
        }

        const sessionsData: TaskSessionsResponse = await sessionsResp.json();
        const latestSession = sessionsData.sessions?.[0];

        if (!latestSession) {
          if (!isCancelled) {
            setActiveSessionId(null);
            setMessages([]);
          }
          return;
        }

        const messageResp = await fetch(`${API_BASE_URL}/history/sessions/${latestSession.session_id}/messages`);
        if (!messageResp.ok) {
          throw new Error(`读取会话消息失败（${messageResp.status}）`);
        }

        const messageData: SessionMessagesResponse = await messageResp.json();
        const historyMessages: Message[] = (messageData.messages || []).map((item) => ({
          id: item.message_id || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          role: item.role,
          content: item.content,
          timestamp: item.timestamp ? item.timestamp.slice(11, 16) : formatTime(),
          metrics: normalizeReplyMetrics(item.metrics),
        }));

        let draftPlan: TaskPlan | null = null;
        try {
          const planResp = await fetch(`${API_BASE_URL}/notes/task?task_id=${currentTaskId}`);
          if (planResp.ok) {
            const planData = await planResp.json();
            if (planData?.draft_plan && typeof planData.draft_plan === "object") {
              draftPlan = planData.draft_plan as TaskPlan;
            }
            if (typeof planData?._plan_session?.status !== "undefined") {
              setPlanStatus(planData._plan_session.status as string);
            } else {
              setPlanStatus(null);
            }
          }
        } catch {
          draftPlan = null;
          setPlanStatus(null);
        }

        if (!readOnly && draftPlan && historyMessages.length > 0) {
          const revIdx = [...historyMessages].reverse().findIndex((msg) => msg.role === "assistant");
          if (revIdx >= 0) {
            const idx = historyMessages.length - 1 - revIdx;
            if (!historyMessages[idx].planProposal) {
              historyMessages[idx] = { ...historyMessages[idx], planProposal: draftPlan };
            }
          } else {
            const draftMsg = makeMessage("assistant", "学习计划已加载，继续调整即可。");
            draftMsg.planProposal = draftPlan;
            historyMessages.push(draftMsg);
          }
        } else if (!readOnly && draftPlan && historyMessages.length === 0) {
          const draftMsg = makeMessage("assistant", "学习计划已加载，继续调整即可。");
          draftMsg.planProposal = draftPlan;
          historyMessages.push(draftMsg);
        }


        if (!isCancelled) {
          setActiveSessionId(messageData.session_id);
          setMessages(
            historyMessages.length > 0
              ? historyMessages
              : []
          );
        }
      } catch (error) {
        if (!isCancelled) {
          const message = error instanceof Error ? error.message : "读取历史失败";
          setErrorText(message);
          setActiveSessionId(null);
          setMessages([]);
        }
      } finally {
        if (!isCancelled) {
          setIsLoadingHistory(false);
        }
      }
    };

    void loadHistory();
    return () => {
      isCancelled = true;
    };
  }, [currentTaskId, readOnly]);

  useEffect(() => {
    return () => {
      const draft = loadDraftTask();
      if (draft && draft.id === currentTaskId) {
        clearDraftTask();
      }
    };
  }, [currentTaskId]);

  const ensureDraftTaskCreated = async () => {
    const draft = loadDraftTask();
    if (!draft || draft.id !== currentTaskId) return;
    try {
      const response = await fetch(`${API_BASE_URL}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_id: draft.id,
          title: draft.title || "新的学习",
          icon: draft.icon || "✨",
          status: "active",
        }),
      });
      if (response.ok) {
        clearDraftTask();
        setDraftTask(null);
        await queryClient.invalidateQueries({ queryKey: goalKeys.tasks });
      }
    } catch {
      // ignore creation failures
    }
  };

  const sendMessage = async (text?: string) => {
    const messageText = text !== undefined ? text : inputText.trim();
    if (readOnly || !messageText || isSending) return;

    if (isDraftTask) {
      await ensureDraftTaskCreated();
    }

    const assistantId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    activeAssistantIdRef.current = assistantId;
    const requestSessionId = activeSessionIdRef.current || activeSessionId || createChatSessionId(currentTaskId);
    activeSessionIdRef.current = requestSessionId;
    setActiveSessionId(requestSessionId);

    setErrorText(null);
    setMessages((prev) => [
      ...prev,
      makeMessage("user", messageText),
      {
        id: assistantId,
        role: "assistant",
        content: "",
        timestamp: formatTime(),
        process: createInitialReplyProcess(),
      },
    ]);
    setInputText("");
    setIsSending(true);

    // 如果是生成学习总结的消息，先隐藏按钮
    if (messageText === SUMMARY_TRIGGER) {
      setShowAcceptNoteButton(false);
    }

    // 创建 AbortController 用于取消请求
    const controller = new AbortController();
    abortControllerRef.current = controller;

    if (messageText === SUMMARY_TRIGGER) {
      summaryAssistantIdRef.current = assistantId;
      summaryBufferRef.current = "";
      setLatestSummary("");
    }

    try {
      if (!ENABLE_STREAMING) {
        await fallbackSendMessage(messageText, assistantId, requestSessionId, controller.signal);
        return;
      }

      const response = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          task_id: currentTaskId,
          session_id: requestSessionId,
          message: messageText,
          topic: taskTitleDisplay,
          plan_hint: false,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`请求失败（${response.status}）`);
      }

      const streamResult = await readStreamResponse(response, assistantId, controller.signal);
      if (streamResult.sessionId) {
        activeSessionIdRef.current = streamResult.sessionId;
        setActiveSessionId(streamResult.sessionId);
      }
      if (typeof streamResult.planStatus !== "undefined") {
        setPlanStatus(streamResult.planStatus ?? null);
      }
      updateAssistantMessage(assistantId, (message) => ({
        ...message,
        planProposal: streamResult.planProposal ?? message.planProposal,
        suggestedReplies:
          streamResult.suggestedReplies && streamResult.suggestedReplies.length > 0
            ? streamResult.suggestedReplies
            : message.suggestedReplies,
        metrics: streamResult.metrics ?? message.metrics,
      }));
      // 如果总结完成，重置 isSummarizing 状态并显示按钮
      if (streamResult.isConcluded) {
        setIsSummarizing(false);
        setShowAcceptNoteButton(true);
      } else {
        // 备用逻辑：如果用户发送的是SUMMARY_TRIGGER，也显示按钮
        if (messageText === SUMMARY_TRIGGER) {
          setShowAcceptNoteButton(true);
        }
      }
      if (summaryAssistantIdRef.current === assistantId) {
        setLatestSummary(summaryBufferRef.current);
      }
    } catch {
      if (controller.signal.aborted) {
        updateAssistantMessage(assistantId, stopReplyMessage);
        return;
      }
      try {
        await fallbackSendMessage(messageText, assistantId, requestSessionId, controller.signal);
      } catch (fallbackError) {
        if (controller.signal.aborted) {
          updateAssistantMessage(assistantId, stopReplyMessage);
          return;
        }
        const failureMessage = fallbackError instanceof Error
          ? fallbackError.message
          : "网络异常，请稍后重试。";
        const failureText = `接口调用失败：${failureMessage}`;
        setErrorText(failureMessage);
        updateAssistantMessage(assistantId, (message) => ({
          ...message,
          content: message.content
            ? `${message.content}\n\n${failureText}`
            : failureText,
          process: finishReplyProcess(message.process, "error"),
        }));
      }
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
      if (activeAssistantIdRef.current === assistantId) {
        setIsSending(false);
        activeAssistantIdRef.current = null;
      }

      await queryClient.invalidateQueries({ queryKey: goalKeys.timeline(currentTaskId) });
    }
  };

  useEffect(() => {
    const handleRequestPlan = (event: Event) => {
      const detail = (event as CustomEvent).detail as { taskId?: string } | undefined;
      if (detail?.taskId && detail.taskId !== currentTaskId) {
        return;
      }
      if (isSending) return;
      void sendMessage("帮我生成一份学习计划。");
    };
    window.addEventListener(EVENT_REQUEST_PLAN, handleRequestPlan);
    return () => {
      window.removeEventListener(EVENT_REQUEST_PLAN, handleRequestPlan);
    };
  }, [currentTaskId, isSending]);
  const handleStopGeneration = async () => {
    if (isStopping) return;
    const controller = abortControllerRef.current;
    if (!controller && !isSending) return;

    setIsStopping(true);

    const assistantId = activeAssistantIdRef.current;
    if (assistantId) {
      updateAssistantMessage(assistantId, stopReplyMessage);
      activeAssistantIdRef.current = null;
    }

    controller?.abort();
    abortControllerRef.current = null;
    setIsSummarizing(false);

    const sessionId = activeSessionIdRef.current || activeSessionId;
    if (sessionId) {
      const interruptController = new AbortController();
      const timeoutId = window.setTimeout(() => interruptController.abort(), 1500);
      try {
        await fetch(`${API_BASE_URL}/chat/interrupt`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            session_id: sessionId,
          }),
          signal: interruptController.signal,
        });
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          console.error("中断请求失败:", error);
        }
      } finally {
        window.clearTimeout(timeoutId);
      }
    }

    setIsStopping(false);
    setIsSending(false);
    window.requestAnimationFrame(() => inputRef.current?.focus());
  };

  const handleEndSession = async () => {
    if (isSummarizing) return; // 防止重复点击

    // 添加分割线
    const dividerMessage: Message = {
      id: `${Date.now()}-divider`,
      role: "divider",
      content: `-------------------${SUMMARY_TRIGGER}-------------------`,
      timestamp: formatTime(),
    };
    setMessages((prev) => [...prev, dividerMessage]);

    setIsSummarizing(true);
    setShowAcceptNoteButton(false); // 重置按钮状态
    await sendMessage(SUMMARY_TRIGGER);
    // 注意：isSummarizing 会在总结完成后由 stream 结果自动重置
  };

  const handleAcceptNoteUpdate = async () => {
    setIsAcceptingNote(true);
    setShowAcceptNoteButton(false);
    try {
      if (!latestSummary.trim()) {
        throw new Error("Summary content is empty");
      }
      const taskSummaryResp = await fetch(`${API_BASE_URL}/notes/task`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          task_id: currentTaskId,
          content: latestSummary,
        }),
      });

      if (!taskSummaryResp.ok) {
        throw new Error(`Failed to update task note: ${taskSummaryResp.status}`);
      }

      await queryClient.invalidateQueries({ queryKey: goalKeys.plan(currentTaskId) });

      if (planStatus && ["await_confirm", "await_plan_confirm", "await_exit_confirm", "collecting", "paused"].includes(planStatus)) {
        await applyPlanSessionAction("exit");
        setPlanStatus(null);
      }

      // 显示成功提示
      const successMessage: Message = {
        id: `${Date.now()}-note-accepted`,
        role: "assistant",
        content: "✅ 已将任务学习总结更新到任务笔记。点击右上角【任务笔记】按钮查看。",
        timestamp: formatTime(),
      };
      setMessages((prev) => [...prev, successMessage]);
    } catch (error) {
      const message = error instanceof Error ? error.message : "更新失败";
      const errorMessage: Message = {
        id: `${Date.now()}-note-error`,
        role: "assistant",
        content: `❌ 更新笔记失败：${message}`,
        timestamp: formatTime(),
      };
      setMessages((prev) => [...prev, errorMessage]);
      setShowAcceptNoteButton(true);
    } finally {
      setIsAcceptingNote(false);
    }
  };

  const confirmPlanUpdate = async (messageId: string, plan: TaskPlan) => {
    setConfirmingPlanId(messageId);
    setMessages((prev) =>
      prev.map((m) => (m.id === messageId ? { ...m, planError: undefined } : m))
    );
    try {
      // 确认学习计划（后端会自动更新任务笔记）
      const response = await fetch(`${API_BASE_URL}/agent/task-plan/confirm`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          task_id: currentTaskId,
          plan,
        }),
      });
      if (!response.ok) {
        throw new Error(`请求失败（${response.status}）`);
      }

      setMessages((prev) =>
        prev.map((m) =>
          m.id === messageId ? { ...m, planConfirmed: true } : m
        )
      );

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: goalKeys.plan(currentTaskId) }),
        queryClient.invalidateQueries({ queryKey: goalKeys.timeline(currentTaskId) }),
      ]);
    } catch (error) {
      const message = error instanceof Error ? error.message : "更新失败";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === messageId ? { ...m, planError: message } : m
        )
      );
    } finally {
      setConfirmingPlanId(null);
    }
  };

  const applyPlanSessionAction = async (action: "resume" | "exit") => {
    try {
      const response = await fetch(`${API_BASE_URL}/agent/task-plan/session`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          task_id: currentTaskId,
          action,
        }),
      });
      if (response.ok) {
        const data = await response.json();
        const status = typeof data?.status === "string" ? data.status : null;
        setPlanStatus(status === "idle" ? null : status);
      }
    } catch {
      // ignore; keep local state unchanged
    }
  };

  const handleResumePlan = async () => {
    setPlanStatus("collecting");
    await applyPlanSessionAction("resume");
    setMessages((prev) => [
      ...prev,
      makeMessage("assistant", "好的，我们继续调整学习计划。请告诉我你想修改哪些内容。"),
    ]);
  };

  const handleExitPlan = async () => {
    setPlanStatus(null);
    await applyPlanSessionAction("exit");
    setMessages((prev) => [
      ...prev,
      makeMessage("assistant", "好的，已结束学习计划规划。如需再规划，随时告诉我。"),
    ]);
  };

  const handleGenerateGoalPlan = async () => {
    if (!goalId || isGeneratingGoalPlan) return;
    setIsGeneratingGoalPlan(true);
    setErrorText(null);
    try {
      const result = await apiSend<{ proposal: TaskPlan }>("/agent/task-plan/propose", "POST", {
        task_id: currentTaskId,
        source: "goal_setup",
      });
      const planMessage = makeMessage(
        "assistant",
        "我已根据岗位、公司、面试日期和当前水平生成一版计划草案。确认后才会写入正式计划。",
      );
      planMessage.planProposal = result.proposal;
      setMessages([planMessage]);
      await queryClient.invalidateQueries({ queryKey: goalKeys.plan(currentTaskId) });
      setIsPanelOpen(true);
    } catch (caught) {
      setErrorText(caught instanceof Error ? caught.message : "生成计划草案失败");
    } finally {
      setIsGeneratingGoalPlan(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-[#f7f7f8] dark:bg-gray-950">
      {/* Header */}
      <div className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 px-4 py-3 sm:px-6">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-1 text-[11px] text-gray-400">
              <span>{readOnly ? "历史学习" : "面试目标"}</span><ChevronRight className="h-3 w-3" /><span>{readOnly ? "只读记录" : "工作区"}</span>
            </div>
            <h1 className="mt-0.5 truncate text-xl font-semibold text-gray-900 dark:text-gray-100">{taskTitleDisplay}</h1>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
              {goal?.target_companies?.map((company) => <span key={company} className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-1 dark:bg-gray-800"><Building2 className="h-3 w-3" />{company}</span>)}
              {goal?.interview_date && <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-1 dark:bg-gray-800"><CalendarDays className="h-3 w-3" />{goal.interview_date}</span>}
              {!goal?.target_companies?.length && !goal?.interview_date && <span>{currentDate}</span>}
              {readOnly && <span className="rounded-full bg-amber-50 px-2 py-1 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">只读</span>}
            </div>
            {isPlanActive && (
              <div className="mt-2 inline-flex items-center gap-2 rounded-full bg-indigo-50 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 text-xs font-medium px-3 py-1">
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse" />
                计划调整中
              </div>
            )}
            {isPlanPaused && (
              <div className="mt-2 inline-flex items-center gap-2 rounded-full bg-amber-50 text-amber-700 text-xs font-medium px-3 py-1">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                计划已挂起，等待继续
              </div>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {!readOnly && <Link to={`/goals/${currentTaskId}/notes`} className="flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-sm text-gray-500 hover:bg-gray-100 hover:text-gray-800 dark:text-gray-300 dark:hover:bg-gray-800"><BookOpen className="h-4 w-4" /><span className="hidden sm:inline">笔记</span></Link>}
            {!readOnly && <button onClick={handleEndSession} disabled={isSummarizing} className="flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-sm text-gray-500 hover:bg-gray-100 hover:text-gray-800 disabled:opacity-50 dark:text-gray-300 dark:hover:bg-gray-800"><CheckCircle className="h-4 w-4" /><span className="hidden sm:inline">总结本次学习</span></button>}
            {!readOnly && <button onClick={() => setIsPanelOpen(!isPanelOpen)} className="hidden rounded-lg p-2 text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800 lg:inline-flex" aria-label="目标面板">{isPanelOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}</button>}
          </div>
        </div>
      </div>

      {/* Chat Messages Area */}
      <div className="flex-1 overflow-y-auto bg-gray-50 dark:bg-gray-950 p-6">
        <div className="max-w-4xl mx-auto relative min-h-[60vh]">
          {!isLoadingHistory && !errorText && messages.length === 0 && !readOnly && (
            <div className="flex min-h-[58vh] items-center justify-center">
              <div className="w-full max-w-2xl">
                <div className="text-center">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-600 dark:bg-indigo-950/40 dark:text-indigo-300"><Target className="h-6 w-6" /></div>
                  <h2 className="mt-4 text-xl font-semibold text-gray-900 dark:text-white">从一个下一步开始</h2>
                  <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">所有问答、训练证据、计划和复习进度都会归入“{taskTitleDisplay}”。</p>
                </div>
                <div className="mt-6 grid gap-3 sm:grid-cols-3">
                  <button onClick={() => void handleGenerateGoalPlan()} disabled={isGeneratingGoalPlan} className="group rounded-2xl border border-gray-200 bg-white p-4 text-left shadow-sm hover:border-indigo-200 hover:bg-indigo-50/30 disabled:opacity-50 dark:border-gray-800 dark:bg-gray-900 dark:hover:border-indigo-900">
                    <Sparkles className="h-5 w-5 text-indigo-600" /><div className="mt-3 text-sm font-semibold text-gray-900 dark:text-white">{isGeneratingGoalPlan ? "正在生成…" : "生成学习计划"}</div><div className="mt-1 text-xs leading-5 text-gray-400">先生成草案，确认后写入</div>
                  </button>
                  <button onClick={() => navigate(`/goals/${currentTaskId}/diagnostic`)} className="group rounded-2xl border border-gray-200 bg-white p-4 text-left shadow-sm hover:border-indigo-200 hover:bg-indigo-50/30 dark:border-gray-800 dark:bg-gray-900 dark:hover:border-indigo-900">
                    <Brain className="h-5 w-5 text-indigo-600" /><div className="mt-3 text-sm font-semibold text-gray-900 dark:text-white">开始能力诊断</div><div className="mt-1 text-xs leading-5 text-gray-400">连续 3 题建立能力基线</div>
                  </button>
                  <button onClick={() => inputRef.current?.focus()} className="group rounded-2xl border border-gray-200 bg-white p-4 text-left shadow-sm hover:border-indigo-200 hover:bg-indigo-50/30 dark:border-gray-800 dark:bg-gray-900 dark:hover:border-indigo-900">
                    <MessageCircleQuestion className="h-5 w-5 text-indigo-600" /><div className="mt-3 text-sm font-semibold text-gray-900 dark:text-white">直接向教练提问</div><div className="mt-1 text-xs leading-5 text-gray-400">从当前最关心的问题开始</div>
                  </button>
                </div>
              </div>
            </div>
          )}
          {!isLoadingHistory && !errorText && messages.length === 0 && readOnly && <div className="flex min-h-[50vh] items-center justify-center text-sm text-gray-400">该历史学习没有可展示的对话记录。</div>}

          <div className="relative z-10 space-y-6">
            {isLoadingHistory && (
              <div className="space-y-4">
                <div className="flex justify-end">
                  <div className="h-10 w-2/5 animate-pulse rounded-2xl bg-gray-200" />
                </div>
                <div className="flex justify-start">
                  <div className="h-24 w-3/5 animate-pulse rounded-2xl bg-gray-200" />
                </div>
                <div className="flex justify-start">
                  <div className="h-16 w-1/2 animate-pulse rounded-2xl bg-gray-200" />
                </div>
              </div>
            )}

            {errorText && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {errorText}
              </div>
            )}

            {messages.map((message, messageIndex) => {
            const isLastAssistant =
              message.role === "assistant" &&
              messageIndex === messages.length - 1;
            // 渲染分割线
            if (message.role === "divider") {
              return (
                <div
                  key={message.id}
                  className="flex justify-center items-center py-4"
                >
                  <div className="flex items-center gap-4 w-full max-w-2xl">
                    <div className="flex-1 h-px bg-gradient-to-r from-transparent via-gray-300 to-transparent"></div>
                    <span className="text-gray-400 text-sm font-medium whitespace-nowrap">
                      {message.content}
                    </span>
                    <div className="flex-1 h-px bg-gradient-to-r from-transparent via-gray-300 to-transparent"></div>
                  </div>
                </div>
              );
            }

            return (
              <div
                key={message.id}
                className={`flex ${
                  message.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                <div
                  className={message.role === "user"
                    ? "max-w-[82%] rounded-2xl rounded-tr-sm bg-indigo-600 px-4 py-3 text-white shadow-sm"
                    : "w-full max-w-3xl px-0 py-1 text-gray-800 dark:text-gray-100"}
                >
                  {/* Message Content with Markdown Support */}
                  {message.role === "user" ? (
                    <p>{message.content}</p>
                  ) : (
                    <div className="relative">
                      {message.process && (
                        <ReplyProcessCard
                          messageId={message.id}
                          process={message.process}
                          onToggle={() => toggleReplyProcess(message.id)}
                        />
                      )}
                      {message.content && <MarkdownPreview content={message.content} />}
                      {isLastAssistant && isSending && message.content && (
                        <span
                          className="inline-block w-[2px] h-[1.1em] ml-1 rounded-full bg-indigo-400 align-text-bottom"
                          style={{ animation: "cursor-breathe 1.1s ease-in-out infinite" }}
                          aria-hidden="true"
                        />
                      )}
                    </div>
                  )}

                  {/* Timestamp */}
                  <div className={`mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs ${message.role === "user" ? "text-indigo-200" : "text-gray-400 dark:text-gray-500"}`}>
                    <span>{message.timestamp}</span>
                    {message.role === "assistant" && message.metrics && (
                      <details className="relative">
                        <summary className="cursor-pointer list-none hover:text-gray-600 dark:hover:text-gray-300">回复详情</summary>
                        <div className="absolute left-0 top-6 z-20 w-64 rounded-xl border border-gray-200 bg-white p-3 text-xs leading-5 text-gray-500 shadow-xl dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300">
                          <div>耗时 {formatElapsed(message.metrics.elapsed_ms)}</div>
                          <div>Token {formatTokens(message.metrics.total_tokens)}（输入 {formatTokens(message.metrics.input_tokens)} / 输出 {formatTokens(message.metrics.output_tokens)}）</div>
                          <div>{message.metrics.llm_calls} 次模型调用</div>
                        </div>
                      </details>
                    )}
                  </div>

                  {message.role === "assistant" &&
                    !readOnly &&
                    message.suggestedReplies &&
                    message.suggestedReplies.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {message.suggestedReplies.map((item, idx) => (
                          <button
                            key={`${message.id}-suggest-${idx}`}
                            onClick={() => void sendMessage(item)}
                            disabled={isSending}
                            className="rounded-full border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 px-3 py-1 text-xs text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-600 disabled:opacity-50"
                          >
                            {item}
                          </button>
                        ))}
                      </div>
                    )}

                  {message.role === "assistant" && !readOnly && message.planProposal && (
                    <div className="mt-3 border-t border-gray-200 dark:border-gray-700 pt-3">
                      <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-2">详细学习计划（确认后更新）</div>
                      <div className="space-y-2 text-sm text-gray-700 dark:text-gray-300">
                        <div className="font-medium text-gray-900 dark:text-gray-100">
                          {message.planProposal.taskTitle || "学习计划"}
                        </div>
                        {message.planProposal.overallSummary && (
                          <div className="text-xs text-gray-600 dark:text-gray-400">
                            {message.planProposal.overallSummary}
                          </div>
                        )}
                        <div className="text-xs text-gray-500 dark:text-gray-400">
                          {(message.planProposal.totalDays ?? 0) > 0 && (
                            <span>{message.planProposal.totalDays} 天</span>
                          )}
                          {(message.planProposal.totalHours ?? 0) > 0 && (
                            <span> · {message.planProposal.totalHours} 小时</span>
                          )}
                        </div>
                        {normalizePlanSteps(message.planProposal).length > 0 && (
                          <ul className="text-xs text-gray-700 dark:text-gray-300 space-y-1">
                            {normalizePlanSteps(message.planProposal).map((step, idx) => (
                              <li key={idx}>• {step}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                      <div className="mt-3 flex items-center gap-3">
                        <button
                          onClick={() =>
                            void confirmPlanUpdate(message.id, message.planProposal as TaskPlan)
                          }
                          disabled={message.planConfirmed || confirmingPlanId === message.id}
                          className="px-3 py-1.5 text-xs font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
                        >
                          {confirmingPlanId === message.id ? "更新中..." : "确认更新学习计划"}
                        </button>
                        {message.planConfirmed && (
                          <span className="text-xs text-emerald-600">已更新</span>
                        )}
                        {message.planError && (
                          <span className="text-xs text-red-600">{message.planError}</span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {/* 接受笔记更新按钮 */}
          {showAcceptNoteButton && !readOnly && (
            <div className="flex justify-center py-4">
              <button
                onClick={handleAcceptNoteUpdate}
                disabled={isAcceptingNote}
                className="flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-xl hover:from-indigo-700 hover:to-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg hover:shadow-xl"
              >
                <CheckCircle className="w-5 h-5" />
                <span className="font-medium">{isAcceptingNote ? "更新中..." : "接受笔记更新"}</span>
              </button>
            </div>
          )}
          </div>
        </div>
      </div>

      {/* Chat Input Footer */}
      {!readOnly && <div
        data-testid="workspace-chat-footer"
        className="workspace-bottom-dock flex shrink-0 items-center border-t border-gray-200 bg-white px-4 dark:border-gray-800 dark:bg-gray-900"
      >
        <div className="mx-auto w-full max-w-4xl">
          {(isPlanActive || isPlanPaused) && (
            <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
              <span>
                {isPlanPaused ? "计划已挂起，可继续调整或结束计划。" : "当前处于计划调整中，可随时结束计划。"}
              </span>
              {isPlanPaused && (
                <button
                  onClick={() => void handleResumePlan()}
                  disabled={isSending}
                  className="px-2.5 py-1 rounded-full bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  继续调整
                </button>
              )}
              <button
                onClick={() => void handleExitPlan()}
                disabled={isSending}
                className="px-2.5 py-1 rounded-full border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50"
              >
                结束计划
              </button>
            </div>
          )}
          <div className="relative rounded-2xl border border-indigo-200/80 dark:border-indigo-700/60 bg-white/70 dark:bg-gray-800/70 backdrop-blur-sm px-3 py-2.5 shadow-[0_8px_24px_-12px_rgba(99,102,241,0.35)] dark:shadow-[0_8px_24px_-12px_rgba(99,102,241,0.5)] transition-all focus-within:border-indigo-400 dark:focus-within:border-indigo-400 focus-within:shadow-[0_8px_28px_-8px_rgba(99,102,241,0.5)]">
            <div className="flex items-end gap-3">
              <div className="w-9 h-9 shrink-0 mb-0.5 rounded-xl overflow-hidden bg-indigo-100/60 dark:bg-indigo-900/30 ring-1 ring-indigo-200/60 dark:ring-indigo-700/40 flex items-center justify-center">
                <img src="/img/logo.svg" alt="" className="w-7 h-7" />
              </div>
              <textarea
                ref={inputRef}
                placeholder="输入你的问题或想法..."
                rows={1}
                value={inputText}
                onChange={(event) => setInputText(event.target.value)}
                onCompositionStart={() => {
                  isComposingRef.current = true;
                }}
                onCompositionEnd={() => {
                  isComposingRef.current = false;
                  compositionEndedAtRef.current = Date.now();
                }}
                onKeyDown={(event) => {
                  if (event.key !== "Enter" || event.shiftKey) return;
                  const nativeEvent = event.nativeEvent;
                  const isImeSelecting = isComposingRef.current
                    || nativeEvent.isComposing
                    || nativeEvent.keyCode === 229
                    || Date.now() - compositionEndedAtRef.current < 150;
                  if (isImeSelecting) return;
                  event.preventDefault();
                  void sendMessage();
                }}
                disabled={isSending}
                className="h-10 min-h-10 max-h-10 flex-1 resize-none overflow-y-auto border-none bg-transparent px-1 py-2 leading-6 text-gray-900 outline-none placeholder:text-gray-400 dark:text-gray-100 dark:placeholder:text-gray-500"
              />
              {isSending ? (
                <button
                  onClick={handleStopGeneration}
                  disabled={isStopping}
                  className="p-2.5 bg-red-500 text-white rounded-xl hover:bg-red-600 transition-colors flex-shrink-0 shadow-md shadow-red-500/30 disabled:cursor-wait disabled:opacity-70"
                  aria-label={isStopping ? "正在停止生成" : "停止生成"}
                >
                  {isStopping ? <Loader2 className="h-5 w-5 animate-spin" /> : <Square className="w-5 h-5" />}
                </button>
              ) : (
                <button
                  onClick={() => void sendMessage()}
                  disabled={isSending || !inputText.trim()}
                  className="p-2.5 rounded-xl text-white transition-all flex-shrink-0 bg-gradient-to-br from-indigo-500 to-violet-500 hover:from-indigo-600 hover:to-violet-600 shadow-md shadow-indigo-500/40 hover:shadow-lg hover:shadow-indigo-500/50 disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none"
                  aria-label="发送消息"
                >
                  <Send className="w-5 h-5" />
                </button>
              )}
            </div>
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-center gap-x-3 gap-y-2 text-xs text-gray-500 dark:text-gray-400">
            <div className="flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
              <span>按 Enter 发送，</span>
              <kbd className="px-1.5 py-0.5 rounded-md bg-indigo-50 dark:bg-indigo-900/40 border border-indigo-200/80 dark:border-indigo-700/60 text-indigo-600 dark:text-indigo-300 text-[10px] font-medium leading-none">
                Shift + Enter
              </kbd>
              <span>换行</span>
            </div>
            <ModelSwitcher disabled={isSending} />
          </div>
        </div>
      </div>}
    </div>
  );
}
