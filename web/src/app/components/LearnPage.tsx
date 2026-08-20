import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import {
  ArrowLeft,
  Send,
  BookOpen,
  Loader2,
  ChevronRight,
  Quote,
  Sparkles,
  RotateCcw,
  X,
  ExternalLink,
  FileText,
} from "lucide-react";
import { MarkdownPreview } from "./MarkdownPreview";
import { API_BASE_URL, apiGet } from "../../lib/api";
import { EVENT_LLM_SETTINGS_UPDATED } from "../../lib/events";

interface Citation {
  question_id: string;
  question: string;
  dimension: string;
  dimension_label: string;
  source_file: string;
  score: number;
}

interface QAMessage {
  role: "user" | "tutor";
  content: string;
  citations?: Citation[];
}

interface SourceModalState {
  open: boolean;
  loading: boolean;
  sourceFile: string;
  title: string;
  content: string;
  heading: string;
  error: string;
}

// 预置示例问题，降低使用门槛
const EXAMPLE_QUESTIONS = [
  "什么是 GraphRAG，和传统 RAG 有什么区别？",
  "Agent 的记忆系统应该怎么设计？",
  "ReAct 和 Plan-and-Execute 怎么选？",
  "多 Agent 之间怎么通信协作？",
];

/**
 * 将正文中的引用标注 [1]、[2] 等替换为 <sup> 上角标（配合 rehype-raw 渲染）。
 * 跳过 ``` 围栏代码块内的内容，避免误伤数组索引等。
 */
function toSuperscript(text: string): string {
  const lines = text.split("\n");
  let inFence = false;
  const out = lines.map((line) => {
    if (line.trim().startsWith("```")) {
      inFence = !inFence;
      return line;
    }
    if (inFence) return line;
    // 替换行内 [数字] 为上角标；排除 markdown 链接 [text](url) 与图片 ![alt](url)
    return line.replace(
      /\[(\d{1,3})\](?!\()/g,
      '<sup class="cite-sup">[$1]</sup>',
    );
  });
  return out.join("\n");
}

export function LearnPage() {
  const [messages, setMessages] = useState<QAMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState<"retrieving" | "generating">("retrieving");
  const [error, setError] = useState("");
  const [sourceModal, setSourceModal] = useState<SourceModalState>({
    open: false,
    loading: false,
    sourceFile: "",
    title: "",
    content: "",
    heading: "",
    error: "",
  });
  const bottomRef = useRef<HTMLDivElement>(null);
  const sourceContentRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [activeModel, setActiveModel] = useState<{ modelName: string; providerName: string } | null>(null);

  // 输入框自适应高度（最多 160px）
  const autoResizeInput = (el: HTMLTextAreaElement) => {
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  useEffect(() => {
    const fetchActiveModel = async () => {
      try {
        const data = await apiGet<{ modelName: string; providerName: string }>(
          "/llm-settings/active-model",
        );
        setActiveModel(data);
      } catch {
        setActiveModel(null);
      }
    };
    fetchActiveModel();
    const handler = () => fetchActiveModel();
    window.addEventListener(EVENT_LLM_SETTINGS_UPDATED, handler);
    return () => window.removeEventListener(EVENT_LLM_SETTINGS_UPDATED, handler);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const ask = async (query: string) => {
    if (!query.trim() || loading) return;
    const submitted = query.trim();
    setMessages((prev) => [...prev, { role: "user", content: submitted }]);
    setInput("");
    setLoading(true);
    setStage("retrieving");
    setError("");

    try {
      const res = await fetch(`${API_BASE_URL}/interview/ask/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: submitted }),
      });
      if (!res.ok || !res.body) {
        throw new Error(`请求失败（${res.status}）`);
      }

      // 解析 SSE 流
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let streamedText = "";
      let citations: Citation[] = [];
      let done = false;

      while (!done) {
        const { value, done: readerDone } = await reader.read();
        if (readerDone) break;
        buffer += decoder.decode(value, { stream: true });

        // 按空行切分 SSE 事件
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";

        for (const evt of events) {
          const line = evt.trim();
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          let data: any;
          try {
            data = JSON.parse(payload);
          } catch {
            continue;
          }

          switch (data.type) {
            case "stage":
              setStage(data.stage === "generating" ? "generating" : "retrieving");
              break;
            case "token":
              streamedText += data.content || "";
              setMessages((prev) => {
                const next = [...prev];
                // 实时更新最后一条 tutor 消息（流式追加）
                const last = next[next.length - 1];
                if (last && last.role === "tutor") {
                  last.content = streamedText;
                } else {
                  next.push({ role: "tutor", content: streamedText });
                }
                return next;
              });
              break;
            case "done":
              citations = data.citations || [];
              streamedText = data.answer || streamedText;
              done = true;
              break;
            case "error":
              throw new Error(data.message || "生成失败");
          }
        }
      }

      // 最终落盘：写入完整答案与引用
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last && last.role === "tutor") {
          last.content = streamedText;
          last.citations = citations;
        } else {
          next.push({ role: "tutor", content: streamedText, citations });
        }
        return next;
      });
    } catch (e: any) {
      setError(e.message || "提问失败");
    } finally {
      setLoading(false);
    }
  };

  const reset = () => {
    setMessages([]);
    setError("");
  };

  const openSource = async (c: Citation) => {
    setSourceModal({
      open: true,
      loading: true,
      sourceFile: c.source_file,
      title: c.question,
      content: "",
      heading: "",
      error: "",
    });
    try {
      const res = await fetch(
        `${API_BASE_URL}/interview/source?source_file=${encodeURIComponent(c.source_file)}&question=${encodeURIComponent(c.question)}`,
      );
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.detail || `加载失败（${res.status}）`);
      }
      setSourceModal((prev) => ({
        ...prev,
        loading: false,
        content: data.content || "",
        heading: data.heading || "",
      }));
    } catch (e: any) {
      setSourceModal((prev) => ({
        ...prev,
        loading: false,
        error: e.message || "加载来源失败",
      }));
    }
  };

  const closeSource = () => {
    setSourceModal((prev) => ({ ...prev, open: false }));
  };

  // 内容渲染完成后，定位并高亮目标题目标题
  useEffect(() => {
    if (!sourceModal.open || sourceModal.loading || !sourceModal.heading) return;

    const container = sourceContentRef.current;
    if (!container) return;

    // 从 heading（如 "## Q：xxx"）中去掉 # 前缀，保留 "Q：xxx"，
    // 与 ReactMarkdown 渲染出的标题文本（含 Q：）一致。
    const targetText = sourceModal.heading
      .replace(/^#{1,6}\s*/, "")
      .trim();

    if (!targetText) return;

    // 轮询查找目标标题：大文件 ReactMarkdown 渲染可能较慢，需多次尝试
    let attempts = 0;
    const maxAttempts = 30;
    let resolved = false;

    const tryScroll = () => {
      if (resolved) return;
      attempts += 1;

      const headings = Array.from(
        container.querySelectorAll<HTMLElement>("h1, h2, h3"),
      );
      // 精确匹配优先，找不到再宽松包含匹配
      let target: HTMLElement | undefined = headings.find(
        (h) => (h.textContent || "").trim() === targetText,
      );
      if (!target) {
        target = headings.find((h) =>
          (h.textContent || "").trim().includes(targetText),
        );
      }
      if (!target) {
        target = headings.find((h) =>
          targetText.includes((h.textContent || "").trim()),
        );
      }

      if (target) {
        resolved = true;
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        target.classList.add(
          "bg-amber-100",
          "dark:bg-amber-900/40",
          "rounded",
          "px-2",
          "-mx-2",
        );
        return;
      }

      if (attempts < maxAttempts) {
        setTimeout(tryScroll, 100);
      }
    };

    const timer = setTimeout(tryScroll, 100);

    return () => {
      resolved = true;
      clearTimeout(timer);
    };
  }, [sourceModal.open, sourceModal.loading, sourceModal.heading, sourceModal.content]);

  return (
    <div className="flex flex-col h-full bg-slate-50 dark:bg-gray-950">
      {/* 顶部 Header - 始终固定在顶部 */}
      <header className="shrink-0 bg-white dark:bg-gray-900 border-b border-slate-200 dark:border-gray-800 px-6 py-4">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500 flex items-center justify-center text-white">
              <BookOpen className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-800 dark:text-gray-100">学习模式</h1>
              <p className="text-xs text-slate-500 dark:text-gray-400">自由提问，基于知识库检索讲解（带引用）</p>
            </div>
          </div>
          <Link
            to="/interview"
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium text-slate-600 dark:text-gray-300 bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 hover:bg-slate-100 dark:hover:bg-gray-700 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            返回刷题
          </Link>
        </div>
      </header>

      {/* 中间滚动区：仅消息内容滚动，输入区在外层 */}
      <main className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-3xl mx-auto w-full px-4 py-6">
          {/* 错误提示 */}
          {error && (
            <div className="mb-4 p-3 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900/40 text-sm text-red-600 dark:text-red-400">
              {error}
            </div>
          )}

          {/* 消息列表 */}
          <div className="space-y-4">
            {messages.length === 0 && (
              <div className="text-center py-16">
                <div className="w-16 h-16 mx-auto rounded-2xl bg-emerald-50 dark:bg-emerald-900/30 flex items-center justify-center mb-4">
                  <BookOpen className="w-8 h-8 text-emerald-500" />
                </div>
                <h2 className="text-lg font-semibold text-slate-700 dark:text-gray-200 mb-2">
                  向面试知识库提问
                </h2>
                <p className="text-sm text-slate-500 dark:text-gray-400 mb-6">
                  系统会检索 485 道面试题中的相关知识，为你生成带引用的讲解。
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {EXAMPLE_QUESTIONS.map((q) => (
                    <button
                      key={q}
                      onClick={() => ask(q)}
                      className="text-left px-4 py-3 rounded-xl bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 text-sm text-slate-600 dark:text-gray-300 hover:border-emerald-300 dark:hover:border-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-900/30 transition-colors"
                    >
                      <Sparkles className="w-3.5 h-3.5 text-emerald-500 inline mr-1.5" />
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, idx) => (
              <div key={idx} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                {msg.role === "user" ? (
                  <div className="max-w-[85%] px-4 py-3 rounded-2xl rounded-br-sm bg-emerald-500 text-white text-sm leading-relaxed whitespace-pre-wrap">
                    {msg.content}
                  </div>
                ) : (
                  <div className="max-w-[85%] bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 rounded-2xl rounded-bl-sm shadow-sm px-4 py-3">
                    <div className="flex items-center gap-2 mb-2">
                      <div className="w-6 h-6 rounded-full bg-emerald-100 dark:bg-emerald-900/40 flex items-center justify-center">
                        <BookOpen className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                      </div>
                      <span className="text-xs font-semibold text-emerald-600 dark:text-emerald-400">学习导师</span>
                    </div>
                    <MarkdownPreview content={toSuperscript(msg.content)} enableRawHtml />

                    {/* 引用来源 */}
                    {msg.citations && msg.citations.length > 0 && (
                      <div className="mt-3 pt-3 border-t border-slate-100 dark:border-gray-700">
                        <div className="text-xs font-medium text-slate-400 dark:text-gray-500 mb-2 flex items-center gap-1">
                          <Quote className="w-3.5 h-3.5" />
                          参考来源（{msg.citations.length}）
                        </div>
                        <div className="space-y-2">
                          {msg.citations.map((c, i) => (
                            <button
                              key={c.question_id}
                              onClick={() => openSource(c)}
                              className="w-full flex items-start gap-2 p-2 rounded-lg bg-slate-50 dark:bg-gray-900 hover:bg-slate-100 dark:hover:bg-gray-700 transition-colors text-left group"
                            >
                              <span className="text-xs font-semibold text-emerald-500 shrink-0 mt-0.5">
                                [{i + 1}]
                              </span>
                              <div className="flex-1 min-w-0">
                                <div className="text-sm text-slate-700 dark:text-gray-300 leading-snug group-hover:text-emerald-600 dark:group-hover:text-emerald-400 transition-colors">
                                  {c.question}
                                </div>
                                <div className="text-xs text-slate-400 dark:text-gray-500 mt-0.5 flex items-center gap-1">
                                  <span>{c.dimension_label} · 相关度 {Math.round(c.score * 100)}%</span>
                                  <ExternalLink className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                                </div>
                              </div>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}

            {/* loading 指示 */}
            {loading && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 px-4 py-3 rounded-2xl bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 text-sm text-slate-500 dark:text-gray-400">
                  <Loader2 className="w-4 h-4 animate-spin text-emerald-500" />
                  {stage === "retrieving" ? "正在检索知识库..." : "正在生成讲解..."}
                </div>
              </div>
            )}
          </div>

          <div ref={bottomRef} />
        </div>
      </main>

      {/* 底部输入栏 - 始终固定在底部，自然落在 flex-col 末尾 */}
      <footer className="shrink-0 bg-white dark:bg-gray-900 border-t border-slate-200 dark:border-gray-800 px-4 py-3">
        <div className="max-w-3xl mx-auto">
          {/* 主输入容器：聚焦时渐变边框 + 阴影提升 */}
          <div
            className="relative rounded-2xl border border-emerald-200/80 dark:border-emerald-700/50
                       bg-white/70 dark:bg-gray-800/70 backdrop-blur-sm px-3 py-2.5
                       shadow-[0_8px_24px_-12px_rgba(16,185,129,0.4)] dark:shadow-[0_8px_24px_-12px_rgba(16,185,129,0.5)]
                       focus-within:border-emerald-400 dark:focus-within:border-emerald-400
                       focus-within:shadow-[0_8px_28px_-8px_rgba(16,185,129,0.55)]
                       transition-all"
          >
            <div className="flex items-end gap-3">
              {/* 左侧 Logo 图标 */}
              <div className="w-9 h-9 shrink-0 mb-0.5 rounded-xl overflow-hidden
                              bg-emerald-100/60 dark:bg-emerald-900/30
                              ring-1 ring-emerald-200/60 dark:ring-emerald-700/40
                              flex items-center justify-center">
                <img src="/img/logo.svg" alt="" className="w-7 h-7" />
              </div>
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  autoResizeInput(e.target);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    ask(input);
                  }
                }}
                placeholder="向面试知识库提问：例如 GraphRAG、Agent 记忆设计..."
                className="flex-1 resize-none bg-transparent px-1 py-2
                           text-sm text-slate-800 dark:text-gray-100
                           placeholder:text-slate-400 dark:placeholder:text-gray-500
                           focus:outline-none leading-relaxed"
                rows={1}
              />
              <button
                onClick={() => ask(input)}
                disabled={loading || !input.trim()}
                aria-label="发送问题"
                className="w-10 h-10 flex items-center justify-center rounded-xl text-white
                           bg-gradient-to-br from-emerald-500 to-teal-600
                           shadow-lg shadow-emerald-500/30
                           hover:from-emerald-600 hover:to-teal-700
                           hover:shadow-xl hover:shadow-emerald-500/40
                           disabled:opacity-40 disabled:cursor-not-allowed disabled:shadow-none
                           transition-all duration-200"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {/* 底部辅助行：居中布局 - 快捷键 + 模型徽章 + 清空 */}
          <div className="mt-3 flex flex-wrap items-center justify-center gap-x-3 gap-y-2 text-xs text-slate-500 dark:text-gray-400">
            <div className="flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-emerald-500" />
              <span>按 Enter 发送，</span>
              <kbd className="px-1.5 py-0.5 rounded-md bg-white dark:bg-gray-800 border border-slate-200 dark:border-gray-700 font-mono text-[10px] text-slate-600 dark:text-gray-300">
                Shift + Enter
              </kbd>
              <span>换行</span>
            </div>
            {activeModel && (
              <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full
                              bg-emerald-50/80 dark:bg-emerald-900/30
                              border border-emerald-200/70 dark:border-emerald-700/50
                              text-emerald-700 dark:text-emerald-300">
                <span className="inline-block w-1.5 h-1.5 rounded-full
                                 bg-gradient-to-br from-emerald-500 to-teal-500
                                 shadow-[0_0_6px_rgba(16,185,129,0.6)]" />
                <span className="font-medium">{activeModel.modelName}</span>
                <span className="text-emerald-400/80">·</span>
                <span className="text-emerald-500/80">{activeModel.providerName}</span>
              </div>
            )}
            {messages.length > 0 && (
              <button
                onClick={reset}
                className="flex items-center gap-1 hover:text-slate-700 dark:hover:text-gray-200 transition-colors"
              >
                <RotateCcw className="w-3 h-3" />
                清空对话
              </button>
            )}
          </div>
        </div>
      </footer>

      {/* 引用来源详情弹窗 */}
      {sourceModal.open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={closeSource}
        >
          <div
            className="w-full max-w-2xl max-h-[85vh] flex flex-col bg-white dark:bg-gray-900 rounded-2xl shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* 弹窗头部 */}
            <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-slate-200 dark:border-gray-700">
              <div className="flex items-start gap-3 min-w-0">
                <div className="w-9 h-9 rounded-lg bg-emerald-100 dark:bg-emerald-900/40 flex items-center justify-center shrink-0">
                  <FileText className="w-4.5 h-4.5 text-emerald-600 dark:text-emerald-400" />
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-slate-800 dark:text-gray-100 leading-snug">
                    {sourceModal.title}
                  </div>
                  <div className="text-xs text-slate-400 dark:text-gray-500 mt-0.5 truncate">
                    来源文件：{sourceModal.sourceFile}
                  </div>
                </div>
              </div>
              <button
                onClick={closeSource}
                className="p-1.5 rounded-lg text-slate-400 dark:text-gray-500 hover:bg-slate-100 dark:hover:bg-gray-800 hover:text-slate-600 dark:hover:text-gray-300 transition-colors shrink-0"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* 弹窗内容 */}
            <div ref={sourceContentRef} className="flex-1 overflow-y-auto px-5 py-4">
              {sourceModal.loading ? (
                <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500 dark:text-gray-400">
                  <Loader2 className="w-4 h-4 animate-spin text-emerald-500" />
                  正在加载来源内容...
                </div>
              ) : sourceModal.error ? (
                <div className="p-3 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900/40 text-sm text-red-600 dark:text-red-400">
                  {sourceModal.error}
                </div>
              ) : (
                <MarkdownPreview content={sourceModal.content} />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
