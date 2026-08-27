import { useState } from "react";
import { useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Building2, CalendarDays, Target, UserRound } from "lucide-react";
import { apiSend } from "../../lib/api";
import { goalKeys, rememberActiveGoal, type ExperienceLevel, type GoalTask } from "../../lib/goals";

function makeGoalId() {
  return `task_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

export function GoalCreatePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [role, setRole] = useState("");
  const [companies, setCompanies] = useState("");
  const [interviewDate, setInterviewDate] = useState("");
  const [level, setLevel] = useState<ExperienceLevel | "">("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const createGoal = async () => {
    const targetRole = role.trim();
    if (!targetRole) {
      setError("请先填写目标岗位");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const goal = await apiSend<GoalTask>("/tasks", "POST", {
        task_id: makeGoalId(),
        kind: "interview_goal",
        target_role: targetRole,
        target_companies: companies.split(/[，,]/).map((item) => item.trim()).filter(Boolean),
        interview_date: interviewDate || null,
        experience_level: level || null,
        icon: "🎯",
        status: "active",
      });
      rememberActiveGoal(goal.id);
      await queryClient.invalidateQueries({ queryKey: goalKeys.tasks });
      queryClient.setQueryData(goalKeys.goal(goal.id), goal);
      navigate(`/goals/${goal.id}/workspace`, { replace: true, state: { newGoal: true } });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建面试目标失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto bg-[#f7f7f8] px-5 py-10 dark:bg-gray-950">
      <div className="mx-auto max-w-2xl">
        <div className="mb-8">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-600 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-300">
            <Target className="h-3.5 w-3.5 text-indigo-600" /> 新建面试目标
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-gray-950 dark:text-white">你准备什么岗位的面试？</h1>
          <p className="mt-2 text-sm leading-6 text-gray-500 dark:text-gray-400">
            先建立一个持续目标，后续的学习、训练、计划和复习都会归入这里。
          </p>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-900">
          <label className="block">
            <span className="mb-2 flex items-center gap-2 text-sm font-medium text-gray-800 dark:text-gray-200">
              <UserRound className="h-4 w-4 text-gray-400" /> 目标岗位 <span className="text-indigo-600">*</span>
            </span>
            <input
              autoFocus
              value={role}
              onChange={(event) => setRole(event.target.value)}
              placeholder="例如：AI Agent 应用工程师"
              className="workspace-input"
              onKeyDown={(event) => {
                if (event.key === "Enter") void createGoal();
              }}
            />
          </label>

          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            <label className="block">
              <span className="mb-2 flex items-center gap-2 text-sm font-medium text-gray-800 dark:text-gray-200">
                <Building2 className="h-4 w-4 text-gray-400" /> 目标公司
              </span>
              <input
                value={companies}
                onChange={(event) => setCompanies(event.target.value)}
                placeholder="字节、阿里（可选）"
                className="workspace-input"
              />
            </label>
            <label className="block">
              <span className="mb-2 flex items-center gap-2 text-sm font-medium text-gray-800 dark:text-gray-200">
                <CalendarDays className="h-4 w-4 text-gray-400" /> 面试日期
              </span>
              <input
                type="date"
                value={interviewDate}
                onChange={(event) => setInterviewDate(event.target.value)}
                className="workspace-input"
              />
            </label>
          </div>

          <label className="mt-5 block">
            <span className="mb-2 block text-sm font-medium text-gray-800 dark:text-gray-200">当前水平</span>
            <select
              value={level}
              onChange={(event) => setLevel(event.target.value as ExperienceLevel | "")}
              className="workspace-input"
            >
              <option value="">稍后补充</option>
              <option value="beginner">入门：正在建立知识框架</option>
              <option value="intermediate">进阶：已有项目经验</option>
              <option value="advanced">资深：准备高阶与系统设计</option>
            </select>
          </label>

          {error && <div className="mt-4 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-950/30 dark:text-red-300">{error}</div>}

          <button
            type="button"
            disabled={saving}
            onClick={() => void createGoal()}
            className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? "正在创建…" : "创建面试目标"}
            {!saving && <ArrowRight className="h-4 w-4" />}
          </button>
          <p className="mt-3 text-center text-xs text-gray-400">创建后由你选择生成计划、能力诊断或直接提问，不会自动调用模型。</p>
        </div>
      </div>
    </div>
  );
}
