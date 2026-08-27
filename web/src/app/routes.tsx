import { createBrowserRouter, Navigate } from "react-router";
import { RootLayout } from "./components/RootLayout";
import { TutorSession } from "./components/TutorSession";
import { ChatHistoryPage } from "./components/ChatHistoryPage";
import { DailyNotePage } from "./components/DailyNotePage";
import { TaskNotePage } from "./components/TaskNotePage";
import { ProgressPage } from "./components/ProgressPage";
import { LearnPage } from "./components/LearnPage";
import { GoalCreatePage } from "./components/GoalCreatePage";
import { ResumePage } from "./components/ResumePage";
import { GoalLanding, LegacyInterviewRedirect, LegacyTaskRedirect } from "./components/GoalRouteHelpers";
import { GoalTrainingPage } from "./components/GoalTrainingPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <RootLayout />,
    children: [
      { index: true, element: <GoalLanding /> },
      { path: "goals/new", element: <GoalCreatePage /> },
      { path: "goals/:goalId/workspace", element: <TutorSession /> },
      { path: "goals/:goalId/resume", element: <ResumePage /> },
      { path: "goals/:goalId/learn", element: <LearnPage /> },
      { path: "goals/:goalId/practice", element: <GoalTrainingPage initialMode="practice" /> },
      { path: "goals/:goalId/diagnostic", element: <GoalTrainingPage initialMode="diagnostic" /> },
      { path: "goals/:goalId/mock", element: <GoalTrainingPage initialMode="mock" /> },
      { path: "goals/:goalId/review", element: <GoalTrainingPage initialMode="review" /> },
      { path: "goals/:goalId/progress", element: <ProgressPage /> },
      { path: "goals/:goalId/notes", element: <TaskNotePage /> },
      { path: "history/tasks/:taskId", element: <TutorSession readOnly /> },
      { path: "task/:taskId", element: <LegacyTaskRedirect /> },
      { path: "interview", element: <LegacyInterviewRedirect section="practice" /> },
      { path: "interview/progress", element: <LegacyInterviewRedirect section="progress" /> },
      { path: "interview/learn", element: <LegacyInterviewRedirect section="learn" /> },
      { path: "history/:date", element: <ChatHistoryPage /> },
      { path: "daily-note/:date", element: <DailyNotePage /> },
      { path: "task-note/:taskId", element: <LegacyTaskRedirect /> },
    ],
  },
  { path: "/settings", element: <Navigate to="/?settings=open" replace /> },
]);
