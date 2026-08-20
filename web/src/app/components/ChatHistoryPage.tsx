import { useEffect, useState } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router";
import { ArrowLeft, Calendar, Clock, Download, Share2 } from "lucide-react";
import { MarkdownPreview } from "./MarkdownPreview";
import { API_BASE_URL } from "../../lib/api";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
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

interface SessionMessageItem {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

interface SessionMessagesResponse {
  session_id: string;
  task_id: string;
  topic: string;
  last_updated: string;
  messages: SessionMessageItem[];
}

const dateTitles: { [key: string]: string } = {
  "2026-03-02": "掌握随机森林算法",
  "2026-03-01": "决策树基础复习",
  "2026-02-29": "集成学习方法",
  "2026-02-28": "特征工程实践",
};

export function ChatHistoryPage() {
  const { date } = useParams<{ date: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const taskIdFromQuery = searchParams.get("task_id") || "task_default";
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [taskTitle, setTaskTitle] = useState("学习记录");
  const [isLoading, setIsLoading] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);

  const getDateFromSessionId = (sessionId: string) => {
    const parts = sessionId.split("__");
    if (parts.length < 2) return "";
    const raw = parts[1];
    if (raw.length !== 8 || !/^\d{8}$/.test(raw)) return "";
    return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  };

  useEffect(() => {
    if (!date) {
      setMessages([]);
      return;
    }

    let cancelled = false;

    const loadHistory = async () => {
      setIsLoading(true);
      setErrorText(null);
      try {
        const sessionsResp = await fetch(`${API_BASE_URL}/history/tasks/${taskIdFromQuery}/sessions`);
        if (!sessionsResp.ok) {
          throw new Error(`读取会话列表失败（${sessionsResp.status}）`);
        }

        const sessionsData: TaskSessionsResponse = await sessionsResp.json();
        const sameDaySessions = (sessionsData.sessions || []).filter((session) => {
          const byUpdated = session.last_updated?.startsWith(date);
          const byIdDate = getDateFromSessionId(session.session_id) === date;
          return Boolean(byUpdated || byIdDate);
        });

        if (sameDaySessions.length === 0) {
          if (!cancelled) {
            setTaskTitle(dateTitles[date] || "学习记录");
            setMessages([]);
          }
          return;
        }

        const historyResponses = await Promise.all(
          sameDaySessions.map(async (session) => {
            const resp = await fetch(`${API_BASE_URL}/history/sessions/${session.session_id}/messages`);
            if (!resp.ok) {
              throw new Error(`读取会话消息失败（${resp.status}）`);
            }
            const data: SessionMessagesResponse = await resp.json();
            return { session, data };
          })
        );

        const mergedMessages: ChatMessage[] = historyResponses
          .flatMap(({ data }) => data.messages || [])
          .map((item, index) => ({
            id: item.message_id || `history-${index}`,
            role: item.role,
            content: item.content,
            timestamp: item.timestamp ? item.timestamp.slice(11, 16) : "--:--",
          }));

        if (!cancelled) {
          setTaskTitle(historyResponses[0]?.data.topic || dateTitles[date] || "学习记录");
          setMessages(mergedMessages);
        }
      } catch (error) {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : "读取历史记录失败";
          setErrorText(message);
          setMessages([]);
          setTaskTitle(dateTitles[date] || "学习记录");
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    void loadHistory();
    return () => {
      cancelled = true;
    };
  }, [date, taskIdFromQuery]);

  // 格式化日期显示
  const formatDate = (dateStr: string) => {
    if (!dateStr) return "";
    const [year, month, day] = dateStr.split("-");
    return `${year}年${month}月${day}日`;
  };

  return (
    <div className="h-full flex flex-col bg-gray-50 dark:bg-gray-950">
      {/* Header */}
      <div className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 px-6 py-4">
        <div className="max-w-5xl mx-auto">
          <button
            onClick={() => navigate(-1)}
            className="flex items-center gap-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 mb-3 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
            <span className="text-sm font-medium">返回</span>
          </button>
          
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <div className="p-2 bg-indigo-100 dark:bg-indigo-900/40 rounded-lg">
                  <Calendar className="w-5 h-5 text-indigo-600 dark:text-indigo-300" />
                </div>
                <div>
                  <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
                    {taskTitle}
                  </h1>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mt-0.5">
                    {date && formatDate(date)} 的学习记录
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-500 mt-1">任务：{taskIdFromQuery}</p>
                </div>
              </div>
            </div>

            {/* Action Buttons */}
            <div className="flex items-center gap-3">
              <button className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
                <Share2 className="w-4 h-4 text-gray-600 dark:text-gray-400" />
                <span className="text-sm font-medium text-gray-700 dark:text-gray-200">分享</span>
              </button>
              <button className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors">
                <Download className="w-4 h-4" />
                <span className="text-sm font-medium">导出记录</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Chat History Content */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-5xl mx-auto">
          {isLoading && (
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 mb-4 text-sm text-gray-600 dark:text-gray-300">
              正在加载历史记录...
            </div>
          )}

          {errorText && (
            <div className="bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-200 dark:border-red-900/40 p-4 mb-4 text-sm text-red-700 dark:text-red-400">
              {errorText}
            </div>
          )}

          {/* Session Info Card */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 mb-6 shadow-sm">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-indigo-50 dark:bg-indigo-900/40 rounded-xl">
                  <Clock className="w-6 h-6 text-indigo-600 dark:text-indigo-300" />
                </div>
                <div>
                  <h3 className="font-semibold text-gray-900 dark:text-gray-100">学习时长</h3>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                    约 {messages.length > 0 ? Math.ceil(messages.length * 2.5) : 0} 分钟
                  </p>
                </div>
              </div>
              <div className="text-right">
                <h3 className="font-semibold text-gray-900 dark:text-gray-100">对话轮次</h3>
                <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                  {messages.length} 条消息
                </p>
              </div>
            </div>
          </div>

          {/* Messages */}
          {messages.length === 0 ? (
            <div className="text-center py-12">
              <div className="w-16 h-16 bg-gray-100 dark:bg-gray-800 rounded-full flex items-center justify-center mx-auto mb-4">
                <Calendar className="w-8 h-8 text-gray-400 dark:text-gray-500" />
              </div>
              <p className="text-gray-500 dark:text-gray-400">暂无此日期的学习记录</p>
            </div>
          ) : (
            <div className="space-y-6">
              {messages.map((message, index) => (
                <div key={message.id}>
                  {/* Time Marker for first message or when time gap is significant */}
                  {index === 0 && (
                    <div className="flex items-center justify-center mb-6">
                      <div className="px-4 py-1.5 bg-gray-100 dark:bg-gray-800 rounded-full text-xs font-medium text-gray-600 dark:text-gray-300">
                        {message.timestamp}
                      </div>
                    </div>
                  )}

                  <div
                    className={`flex ${
                      message.role === "user" ? "justify-end" : "justify-start"
                    }`}
                  >
                    <div
                      className={`max-w-[75%] ${
                        message.role === "user"
                          ? "bg-indigo-600 text-white rounded-2xl rounded-tr-sm"
                          : "bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl rounded-tl-sm"
                      } px-5 py-4 shadow-sm`}
                    >
                      {/* Message Content with Markdown Support */}
                      <MarkdownPreview
                        content={message.content}
                        invert={message.role === "user"}
                      />
                      
                      {/* Timestamp */}
                      <div
                        className={`text-xs mt-2 ${
                          message.role === "user"
                            ? "text-indigo-200"
                            : "text-gray-400 dark:text-gray-500"
                        }`}
                      >
                        {message.timestamp}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
