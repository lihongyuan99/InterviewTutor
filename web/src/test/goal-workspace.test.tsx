import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Outlet, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GoalCreatePage } from "../app/components/GoalCreatePage";
import { GoalLanding } from "../app/components/GoalRouteHelpers";
import { LearnPage } from "../app/components/LearnPage";
import { TutorSession } from "../app/components/TutorSession";
import { WorkspacePanel } from "../app/components/WorkspacePanel";
import { WorkspaceSidebar } from "../app/components/WorkspaceSidebar";
import { goalKeys, LAST_ACTIVE_GOAL_KEY, type GoalTask } from "../lib/goals";

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } },
  });
}

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  }));
}

const goal: GoalTask = {
  id: "task_goal",
  title: "字节 · AI Agent 工程师",
  icon: "🎯",
  status: "active",
  kind: "interview_goal",
  target_role: "AI Agent 工程师",
  target_companies: ["字节"],
  interview_date: "2026-09-01",
  experience_level: "intermediate",
  resume_id: null,
};

describe("goal workspace", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/tasks") && init?.method === "POST") return jsonResponse(goal);
      if (url.includes("/tasks/task_old")) return jsonResponse({ ...goal, id: "task_old", title: "旧学习", kind: "legacy_learning", target_role: null, target_companies: [], interview_date: null, experience_level: null });
      if (url.includes("/history/tasks/task_old/sessions")) return jsonResponse({ task_id: "task_old", sessions: [] });
      if (url.includes("/settings/llm")) return jsonResponse({
        active_provider_id: "deepseek",
        providers: [{ id: "deepseek", name: "DeepSeek", active_model: "Deepseek-v4-flash" }],
      });
      if (url.includes("/notes/task")) return jsonResponse({ task_id: "task_goal", plan: ["正式步骤"], draft_plan: null });
      if (url.includes("/history/tasks/task_goal/timeline")) return jsonResponse({ timeline: [] });
      if (url.includes("/interview/progress")) return jsonResponse({ goal_id: "task_goal", review_queue: [], total_attempted: 0, average_mastery: 0, dimension_stats: [], wrong_questions: [], weak_dimensions: [] });
      if (url.includes("/interview/reports")) return jsonResponse({ reports: [] });
      return jsonResponse({});
    }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("validates the required role and creates an interview goal", async () => {
    const user = userEvent.setup();
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/goals/new"]}>
          <Routes>
            <Route path="/goals/new" element={<GoalCreatePage />} />
            <Route path="/goals/:goalId/workspace" element={<div>目标已创建</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: /创建面试目标/ }));
    expect(screen.getByText("请先填写目标岗位")).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("例如：AI Agent 应用工程师"), "AI Agent 工程师");
    await user.click(screen.getByRole("button", { name: /创建面试目标/ }));
    expect(await screen.findByText("目标已创建")).toBeInTheDocument();

    const request = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({ kind: "interview_goal", target_role: "AI Agent 工程师" });
  });

  it("shows exactly the three goal-directed entrances in an empty workspace", async () => {
    const client = makeClient();
    client.setQueryData(goalKeys.goal(goal.id), goal);
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[`/goals/${goal.id}/workspace`]}>
          <Routes>
            <Route element={<Outlet context={{ isPanelOpen: false, setIsPanelOpen: vi.fn() }} />}>
              <Route path="/goals/:goalId/workspace" element={<TutorSession />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("button", { name: /生成学习计划/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /开始能力诊断/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /直接向教练提问/ })).toBeInTheDocument();
    expect(await screen.findByText("Deepseek-v4-flash")).toBeInTheDocument();
    expect(screen.queryByText("回复设置")).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes("/agent/task-plan/propose"))).toBe(false);
  });

  it("does not send when Enter is confirming an IME composition", async () => {
    const client = makeClient();
    client.setQueryData(goalKeys.goal(goal.id), goal);
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[`/goals/${goal.id}/workspace`]}>
          <Routes>
            <Route element={<Outlet context={{ isPanelOpen: false, setIsPanelOpen: vi.fn() }} />}>
              <Route path="/goals/:goalId/workspace" element={<TutorSession />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const input = await screen.findByPlaceholderText("输入你的问题或想法...");
    expect(screen.getByTestId("workspace-chat-footer")).toHaveClass("workspace-bottom-dock");
    fireEvent.change(input, { target: { value: "正在输入拼音" } });
    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", keyCode: 229 });
    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", keyCode: 13 });

    expect(input).toHaveValue("正在输入拼音");
    expect(vi.mocked(fetch).mock.calls.some(([request]) => String(request).includes("/chat"))).toBe(false);
  });

  it("guards IME Enter in knowledge learning and still sends a normal Enter", async () => {
    const client = makeClient();
    client.setQueryData(goalKeys.goal(goal.id), goal);
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[`/goals/${goal.id}/learn`]}>
          <Routes>
            <Route element={<Outlet context={{ isPanelOpen: false, setIsPanelOpen: vi.fn() }} />}>
              <Route path="/goals/:goalId/learn" element={<LearnPage />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const input = await screen.findByPlaceholderText(/向面试知识库提问/);
    expect(screen.getByTestId("workspace-learn-footer")).toHaveClass("workspace-bottom-dock");
    expect(screen.getByTestId("knowledge-input-icon")).toHaveClass("text-emerald-600");
    const knowledgeModelSwitcher = await screen.findByRole("button", {
      name: /当前模型：Deepseek-v4-flash.*点击切换模型/,
    });
    expect(knowledgeModelSwitcher).toHaveClass(
      "border-emerald-200/80",
      "bg-emerald-50/80",
      "text-emerald-700",
    );
    fireEvent.change(input, { target: { value: "正在输入拼音" } });
    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", keyCode: 229 });
    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", keyCode: 13 });

    const askWasCalled = () => vi.mocked(fetch).mock.calls.some(
      ([request]) => String(request).includes("/interview/ask/stream"),
    );
    expect(input).toHaveValue("正在输入拼音");
    expect(askWasCalled()).toBe(false);

    await new Promise((resolve) => window.setTimeout(resolve, 160));
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", keyCode: 13 });
    await waitFor(() => expect(askWasCalled()).toBe(true));
  });

  it("aborts the active request and notifies the server when stopping a reply", async () => {
    const client = makeClient();
    client.setQueryData(goalKeys.goal(goal.id), goal);
    const defaultFetch = vi.mocked(fetch).getMockImplementation();
    let streamSignal: AbortSignal | undefined;

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/chat/stream")) {
        streamSignal = init?.signal as AbortSignal;
        return new Promise<Response>((_resolve, reject) => {
          streamSignal?.addEventListener(
            "abort",
            () => reject(new DOMException("The operation was aborted", "AbortError")),
            { once: true },
          );
        });
      }
      if (url.includes("/chat/interrupt")) return jsonResponse({ status: "interrupted" });
      return defaultFetch!(input, init);
    });

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[`/goals/${goal.id}/workspace`]}>
          <Routes>
            <Route element={<Outlet context={{ isPanelOpen: false, setIsPanelOpen: vi.fn() }} />}>
              <Route path="/goals/:goalId/workspace" element={<TutorSession />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const user = userEvent.setup();
    const input = await screen.findByPlaceholderText("输入你的问题或想法...");
    await user.type(input, "请解释 RAG");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    await user.click(await screen.findByRole("button", { name: "停止生成" }));

    await waitFor(() => expect(streamSignal?.aborted).toBe(true));
    await waitFor(() => expect(screen.getByRole("button", { name: "发送消息" })).toBeInTheDocument());
    expect(input).not.toBeDisabled();
    expect(screen.getByText("[已停止生成]")).toBeInTheDocument();

    const streamCall = vi.mocked(fetch).mock.calls.find(([request]) => String(request).includes("/chat/stream"));
    const interruptCall = vi.mocked(fetch).mock.calls.find(([request]) => String(request).includes("/chat/interrupt"));
    const sessionId = JSON.parse(String(streamCall?.[1]?.body)).session_id;
    expect(sessionId).toMatch(/^task_goal__\d{8}__\d{6}$/);
    expect(JSON.parse(String(interruptCall?.[1]?.body))).toEqual({ session_id: sessionId });
  });

  it("opens the remembered active goal from the landing route", async () => {
    const client = makeClient();
    client.setQueryData(goalKeys.tasks, [goal, { ...goal, id: "task_other", title: "其他目标" }]);
    localStorage.setItem(LAST_ACTIVE_GOAL_KEY, goal.id);
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route path="/" element={<GoalLanding />} />
            <Route path="/goals/:goalId/workspace" element={<div>最近目标工作区</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("最近目标工作区")).toBeInTheDocument();
  });

  it("lists archived interview goals under 已归档目标 and can restore them", async () => {
    const client = makeClient();
    const user = userEvent.setup();
    const archivedGoal = { ...goal, id: "task_archived", title: "已归档 Agent 目标", status: "archived" as const };
    const defaultFetch = vi.mocked(fetch).getMockImplementation();
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/tasks") && !init?.method) {
        return jsonResponse({ tasks: [goal, archivedGoal] });
      }
      return defaultFetch!(input, init);
    });
    client.setQueryData(goalKeys.tasks, [goal, archivedGoal]);
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <WorkspaceSidebar onOpenSettings={vi.fn()} mobileOpen onMobileOpenChange={vi.fn()} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.queryByText("历史学习")).not.toBeInTheDocument();
    expect(screen.getByTestId("workspace-sidebar-footer")).toHaveClass("workspace-bottom-dock");
    await user.click(screen.getByRole("button", { name: /已归档目标/ }));
    expect(screen.getByText(/已归档 Agent 目标/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "管理已归档目标 已归档 Agent 目标" }));
    await user.click(screen.getByRole("button", { name: "恢复目标" }));

    await waitFor(() => {
      const restoreCall = vi.mocked(fetch).mock.calls.find(([request]) => String(request).includes("/tasks/task_archived/status"));
      expect(restoreCall?.[1]?.method).toBe("PATCH");
      expect(JSON.parse(String(restoreCall?.[1]?.body))).toEqual({ status: "active" });
    });
  });

  it("keeps legacy learning read-only and removes all editing input", async () => {
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/history/tasks/task_old"]}>
          <Routes>
            <Route element={<Outlet context={{ isPanelOpen: false, setIsPanelOpen: vi.fn() }} />}>
              <Route path="/history/tasks/:taskId" element={<TutorSession readOnly />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findAllByText("只读")).not.toHaveLength(0);
    await waitFor(() => expect(screen.queryByPlaceholderText("输入你的问题或想法...")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /总结本次学习/ })).not.toBeInTheDocument();
  });

  it.each(["确认更新", "暂不采用"])("supports plan proposal action: %s", async (action) => {
    const client = makeClient();
    client.setQueryData(goalKeys.goal(goal.id), goal);
    client.setQueryData(goalKeys.plan(goal.id), { task_id: goal.id, plan: ["正式步骤"], draft_plan: { plan: ["草案步骤"] } });
    client.setQueryData(goalKeys.progress(goal.id), { goal_id: goal.id, review_queue: [], total_attempted: 1, average_mastery: 0.4, dimension_stats: [], wrong_questions: [], weak_dimensions: [] });
    client.setQueryData(goalKeys.timeline(goal.id), []);
    client.setQueryData(goalKeys.reports(goal.id), []);
    const onClose = vi.fn();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <WorkspacePanel goalId={goal.id} open onClose={onClose} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "计划" }));
    fireEvent.click(screen.getByRole("button", { name: action }));

    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls.map(([input, init]) => [String(input), init?.method]);
      expect(calls.some(([url]) => url.includes(action === "确认更新" ? "/agent/task-plan/confirm" : "/agent/task-plan/proposal/reject"))).toBe(true);
    });
  });
});
