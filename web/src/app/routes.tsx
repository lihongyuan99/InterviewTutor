import { createBrowserRouter, Navigate } from "react-router";
import { RootLayout } from "./components/RootLayout";
import { TutorSession } from "./components/TutorSession";
import { ChatHistoryPage } from "./components/ChatHistoryPage";
import { DailyNotePage } from "./components/DailyNotePage";
import { TaskNotePage } from "./components/TaskNotePage";
import { InterviewPage } from "./components/InterviewPage";
import { ProgressPage } from "./components/ProgressPage";
import { LearnPage } from "./components/LearnPage";
import { ensureDraftTask } from "../lib/draftTask";

function DraftIndex() {
  const draft = ensureDraftTask();
  return <Navigate to={`/task/${draft.id}`} replace />;
}

export const router = createBrowserRouter([
  {
    path: "/",
    element: <RootLayout />,
    children: [
      { index: true, element: <DraftIndex /> },
      { path: "task/:taskId", element: <TutorSession /> },
      { path: "interview", element: <InterviewPage /> },
      { path: "interview/progress", element: <ProgressPage /> },
      { path: "interview/learn", element: <LearnPage /> },
      { path: "history/:date", element: <ChatHistoryPage /> },
      { path: "daily-note/:date", element: <DailyNotePage /> },
      { path: "task-note/:taskId", element: <TaskNotePage /> },
    ],
  },
  { path: "/settings", element: <Navigate to="/?settings=open" replace /> },
]);
