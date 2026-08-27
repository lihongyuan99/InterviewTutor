import { Navigate, useParams } from "react-router";
import { LAST_ACTIVE_GOAL_KEY, useGoal, useTasks } from "../../lib/goals";

function LoadingRoute() {
  return <div className="flex h-full items-center justify-center text-sm text-gray-500">正在加载目标…</div>;
}

export function GoalLanding() {
  const { data: tasks, isLoading } = useTasks();
  if (isLoading) return <LoadingRoute />;
  const goals = (tasks || []).filter((item) => item.kind === "interview_goal" && item.status === "active");
  const remembered = localStorage.getItem(LAST_ACTIVE_GOAL_KEY);
  const goal = goals.find((item) => item.id === remembered) || goals[0];
  return <Navigate to={goal ? `/goals/${goal.id}/workspace` : "/goals/new"} replace />;
}

export function LegacyTaskRedirect() {
  const { taskId } = useParams();
  const { data, isLoading } = useGoal(taskId);
  if (isLoading) return <LoadingRoute />;
  if (!data) return <Navigate to="/goals/new" replace />;
  return (
    <Navigate
      to={data.kind === "interview_goal" ? `/goals/${data.id}/workspace` : `/history/tasks/${data.id}`}
      replace
    />
  );
}

export function LegacyInterviewRedirect({ section }: { section: "practice" | "learn" | "progress" }) {
  const { data: tasks, isLoading } = useTasks();
  if (isLoading) return <LoadingRoute />;
  const goals = (tasks || []).filter((item) => item.kind === "interview_goal" && item.status === "active");
  const remembered = localStorage.getItem(LAST_ACTIVE_GOAL_KEY);
  const goal = goals.find((item) => item.id === remembered) || goals[0];
  return <Navigate to={goal ? `/goals/${goal.id}/${section}` : "/goals/new"} replace />;
}
