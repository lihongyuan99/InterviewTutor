import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import type { ReactNode } from "react";

import "katex/dist/katex.min.css";
import "highlight.js/styles/github.css";
import { CodeBlock } from "./CodeBlock";

interface MarkdownPreviewProps {
  content: string;
  className?: string;
  /** 强制反色文字（用于深色背景气泡，如用户消息） */
  invert?: boolean;
  /** 启用内联 HTML 渲染（用于 <sup> 上角标引用等） */
  enableRawHtml?: boolean;
}

// 先解析原始 HTML，再用白名单净化。默认安全 schema 保留 Markdown
// 正常生成的标签；额外只允许引用上角标所需的精确 class。
const SAFE_RAW_HTML_SCHEMA = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    sup: [["className", "cite-sup"]],
  },
};

function allowCitationSupOnly(text: string): string {
  return text.replace(/<[^>]*>/g, (tag) => {
    if (tag === '<sup class="cite-sup">' || tag === "</sup>") return tag;
    return tag.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  });
}

/**
 * 修复 LLM 生成 Markdown 时的常见缺陷：表格行之间的换行符被空格吞掉，
 * 以及标题/正文与表格之间缺少空行。
 *
 * 例如模型输出：
 *   关键差异对比
 *   | 维度 | 传统 RAG | Agentic RAG | |------|---------|-------------| | ... |
 * （整张表挤在一行，GFM 无法解析）
 *
 * 分两步：
 * 1. 把「单元格右边界 `|` 后跟空白再跟 `|`」的位置恢复为换行，使每行独占一行。
 * 2. 给表格块前后补空行（GFM 要求表格前后有空行，否则可能不渲染）。
 *
 * 只处理「同一行同时包含分隔行特征（---）和多个 `|`」的挤成一行的表格，
 * 且跳过代码块（``` 围栏）内的内容，避免误伤正常多行表格与代码。
 */
function repairInlineTable(text: string): string {
  // 第一步：还原挤成一行的表格
  const lines = text.split("\n");
  const step1: string[] = [];
  let inFence = false;

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith("```")) {
      inFence = !inFence;
      step1.push(line);
      continue;
    }
    if (inFence) {
      step1.push(line);
      continue;
    }

    const pipeCount = (line.match(/\|/g) || []).length;
    const hasSeparator = /\|\s*:?-{3,}:?\s*\|/.test(line);
    if (hasSeparator && pipeCount >= 4) {
      // 分隔行 `|------|` 中间是连续的 `-`，不含 `| + 空白 + |`，不会被误拆。
      step1.push(line.replace(/\|\s+(?=\|)/g, "|\n").replace(/\n{3,}/g, "\n\n"));
    } else {
      step1.push(line);
    }
  }

  // 第二步：给表格块前后补空行。
  // 识别「以 | 开头的行」为表格行；遇到「非空、非表格行 → 表格行」的边界补空行。
  const rows = step1.join("\n").split("\n");
  const step2: string[] = [];
  let inFence2 = false;
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const t = row.trim();
    if (t.startsWith("```")) {
      inFence2 = !inFence2;
      step2.push(row);
      continue;
    }
    if (inFence2) {
      step2.push(row);
      continue;
    }

    const isTableRow = t.startsWith("|");
    const prev = step2[step2.length - 1];
    const prevIsBlank = prev === undefined || prev.trim() === "";
    const prevIsTableRow = prev !== undefined && prev.trim().startsWith("|");

    if (isTableRow && !prevIsBlank && !prevIsTableRow) {
      // 表格块开始：在非表格内容与表格之间补空行
      step2.push("");
    } else if (!isTableRow && t !== "" && prevIsTableRow) {
      // 表格块结束：在表格与非空内容之间补空行
      step2.push("");
    }

    step2.push(row);
  }

  return step2.join("\n");
}

export function MarkdownPreview({ content, className = "", invert = false, enableRawHtml = false }: MarkdownPreviewProps) {
  const normalized = repairInlineTable(
    enableRawHtml ? allowCitationSupOnly(content) : content,
  );
  return (
    <div
      className={`prose prose-sm max-w-none ${invert ? "prose-invert" : "dark:prose-invert"} ${className}`}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={
          enableRawHtml
            ? [rehypeRaw, [rehypeSanitize, SAFE_RAW_HTML_SCHEMA], rehypeKatex, rehypeHighlight]
            : [rehypeKatex, rehypeHighlight]
        }
        components={{
          h1: ({ node, ...props }) => (
            <h1 className="text-2xl font-bold mt-6 mb-4" {...props} />
          ),
          h2: ({ node, ...props }) => (
            <h2 className="text-xl font-semibold mt-5 mb-3" {...props} />
          ),
          h3: ({ node, ...props }) => (
            <h3 className="text-lg font-medium mt-4 mb-2" {...props} />
          ),
          p: ({ node, ...props }) => (
            <p className="my-3 leading-relaxed" {...props} />
          ),
          ul: ({ node, ...props }) => (
            <ul className="my-3 ml-6 list-disc space-y-1" {...props} />
          ),
          ol: ({ node, ...props }) => (
            <ol className="my-3 ml-6 list-decimal space-y-1" {...props} />
          ),
          li: ({ node, ...props }) => (
            <li className="leading-relaxed" {...props} />
          ),
          blockquote: ({ node, ...props }) => (
            <blockquote
              className="border-l-4 border-indigo-500 pl-4 my-4 italic bg-gray-50 dark:bg-gray-800/50 py-2 pr-4 rounded-r"
              {...props}
            />
          ),
          code: ({ node, className, children, ...props }) => {
            const isInline =
              !className ||
              (!String(className).includes("language-") &&
                !String(className).includes("hljs"));
            if (isInline) {
              return (
                <code
                  className="rounded px-1.5 py-0.5 text-sm font-mono text-indigo-600 dark:text-indigo-400"
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return <code className={className} {...props}>{children}</code>;
          },
          pre: ({ node, children, ...props }) => {
            const codeChild = Array.isArray(children)
              ? (children.find(
                  (child) =>
                    child &&
                    typeof child === "object" &&
                    "props" in child &&
                    typeof (child as { props?: { className?: string } }).props?.className === "string" &&
                    ((child as { props?: { className?: string } }).props!.className!.includes("language-") ||
                      (child as { props?: { className?: string } }).props!.className!.includes("hljs"))
                ) as { props?: { className?: string; children?: ReactNode } } | undefined)
              : undefined;
            const lang = codeChild?.props?.className;
            return (
              <CodeBlock className={lang} {...props}>
                {codeChild ? codeChild.props?.children : children}
              </CodeBlock>
            );
          },
          table: ({ node, ...props }) => (
            <div className="overflow-x-auto my-4">
              <table className="min-w-full border-collapse border border-gray-300 dark:border-gray-700" {...props} />
            </div>
          ),
          th: ({ node, ...props }) => (
            <th
              className="border border-gray-300 dark:border-gray-700 px-4 py-2 text-left text-sm font-semibold bg-gray-50 dark:bg-gray-800"
              {...props}
            />
          ),
          td: ({ node, ...props }) => (
            <td
              className="border border-gray-300 dark:border-gray-700 px-4 py-2 text-sm"
              {...props}
            />
          ),
          strong: ({ node, ...props }) => (
            <strong className="font-semibold" {...props} />
          ),
          em: ({ node, ...props }) => (
            <em className="italic" {...props} />
          ),
          a: ({ node, ...props }) => (
            <a
              className="text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 underline"
              target="_blank"
              rel="noopener noreferrer"
              {...props}
            />
          ),
          hr: ({ node, ...props }) => (
            <hr className="my-6 border-gray-200 dark:border-gray-700" {...props} />
          ),
        }}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  );
}
