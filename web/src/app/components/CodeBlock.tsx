import { useState, type ReactNode } from "react";
import { Copy, Check } from "lucide-react";

/** 代码块组件：带语言标签和复制按钮 */
export function CodeBlock({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  const [copied, setCopied] = useState(false);
  const language = className?.replace("language-", "") || "";

  const extractText = (node: ReactNode): string => {
    if (typeof node === "string" || typeof node === "number") return String(node);
    if (Array.isArray(node)) return node.map(extractText).join("");
    if (node && typeof node === "object" && "props" in node) {
      const props = (node as { props?: { children?: ReactNode } }).props;
      return props?.children ? extractText(props.children) : "";
    }
    return "";
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(extractText(children));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // 忽略剪贴板异常
    }
  };

  return (
    <div className="relative group my-3">
      {language && (
        <span className="absolute top-2 left-3 text-xs font-mono text-gray-400 pointer-events-none">
          {language}
        </span>
      )}
      <button
        type="button"
        aria-label="复制代码"
        onClick={handleCopy}
        className="absolute top-2 right-2 flex items-center gap-1 px-2 py-1 rounded text-xs text-gray-300 hover:text-white hover:bg-gray-700 transition-colors opacity-0 group-hover:opacity-100 focus:opacity-100"
      >
        {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
        {copied ? "已复制" : "复制"}
      </button>
      <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 pt-8 overflow-x-auto">
        <code className={className}>{children}</code>
      </pre>
    </div>
  );
}
