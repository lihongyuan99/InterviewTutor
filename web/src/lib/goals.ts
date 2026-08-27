import { useQuery } from "@tanstack/react-query";
import { apiGet } from "./api";
import type { TaskPlan } from "./plan";

export type TaskKind = "interview_goal" | "legacy_learning";
export type ExperienceLevel = "beginner" | "intermediate" | "advanced";

export interface GoalTask {
  id: string;
  title: string;
  icon: string;
  status: "active" | "archived";
  kind: TaskKind;
  target_role: string | null;
  target_companies: string[];
  interview_date: string | null;
  experience_level: ExperienceLevel | null;
  resume_id: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface GoalProgress {
  goal_id: string | null;
  review_queue: Array<Record<string, any>>;
  total_attempted: number;
  average_mastery: number;
  dimension_stats: Array<{
    dimension: string;
    dimension_label: string;
    count: number;
    avg_mastery: number;
    avg_level: number;
  }>;
  wrong_questions: Array<Record<string, any>>;
  weak_dimensions: Array<{
    dimension: string;
    dimension_label: string;
    count: number;
    avg_mastery: number;
    avg_level: number;
  }>;
}

export interface TimelineItem {
  id: string;
  date: string;
  display_date: string;
  key_learnings: string[];
  review_areas: string[];
  session_count: number;
  message_count: number;
  last_updated: string;
}

export interface InterviewReport {
  report_id: string;
  session_id: string;
  goal_id: string | null;
  mode: "diagnostic" | "mock";
  completed: boolean;
  question_count: number;
  answered_count: number;
  overall_level: number;
  scores: Record<string, number>;
  strengths: string[];
  missing_points: string[];
  study_recommendations: string[];
  plan_adjustment_points: string[];
  created_at: string;
}

export type GoalPlan = TaskPlan & {
  task_id?: string;
  content?: string;
  userNotes?: string;
  planChecklist?: Record<string, boolean>;
  draft_plan?: TaskPlan | null;
  updated_at?: string;
};

export const goalKeys = {
  tasks: ["tasks"] as const,
  goal: (id: string) => ["goal", id] as const,
  plan: (id: string) => ["plan", id] as const,
  timeline: (id: string) => ["timeline", id] as const,
  progress: (id: string) => ["progress", id] as const,
  reports: (id: string) => ["reports", id] as const,
};

export function useTasks() {
  return useQuery({
    queryKey: goalKeys.tasks,
    queryFn: async () => (await apiGet<{ tasks: GoalTask[] }>("/tasks")).tasks,
    staleTime: 10_000,
  });
}

export function useGoal(goalId?: string) {
  return useQuery({
    queryKey: goalKeys.goal(goalId || "missing"),
    queryFn: () => apiGet<GoalTask>(`/tasks/${encodeURIComponent(goalId || "")}`),
    enabled: Boolean(goalId),
    staleTime: 10_000,
  });
}

export function useGoalPlan(goalId?: string) {
  return useQuery({
    queryKey: goalKeys.plan(goalId || "missing"),
    queryFn: () => apiGet<GoalPlan>(`/notes/task?task_id=${encodeURIComponent(goalId || "")}`),
    enabled: Boolean(goalId),
    staleTime: 5_000,
  });
}

export function useGoalTimeline(goalId?: string) {
  return useQuery({
    queryKey: goalKeys.timeline(goalId || "missing"),
    queryFn: async () => (
      await apiGet<{ timeline: TimelineItem[] }>(
        `/history/tasks/${encodeURIComponent(goalId || "")}/timeline`,
      )
    ).timeline,
    enabled: Boolean(goalId),
    staleTime: 5_000,
  });
}

export function useGoalProgress(goalId?: string) {
  return useQuery({
    queryKey: goalKeys.progress(goalId || "missing"),
    queryFn: () => apiGet<GoalProgress>(
      `/interview/progress?goal_id=${encodeURIComponent(goalId || "")}`,
    ),
    enabled: Boolean(goalId),
    staleTime: 5_000,
  });
}

export function useGoalReports(goalId?: string) {
  return useQuery({
    queryKey: goalKeys.reports(goalId || "missing"),
    queryFn: async () => (
      await apiGet<{ reports: InterviewReport[] }>(
        `/interview/reports?goal_id=${encodeURIComponent(goalId || "")}`,
      )
    ).reports,
    enabled: Boolean(goalId),
    staleTime: 5_000,
  });
}

export const LAST_ACTIVE_GOAL_KEY = "interviewtutor.lastActiveGoalId";

export function rememberActiveGoal(goalId: string) {
  localStorage.setItem(LAST_ACTIVE_GOAL_KEY, goalId);
}
