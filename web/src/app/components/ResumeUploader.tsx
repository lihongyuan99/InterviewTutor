import { useRef, useState } from "react";
import { FileUp, Loader2, X } from "lucide-react";
import { uploadResume, type Resume } from "../../lib/api";
import { notifyError, notifySuccess } from "../../lib/toast";

const ACCEPT = ".pdf,.docx,.md,.markdown,.txt";
const MAX_BYTES = 10 * 1024 * 1024;

interface ResumeUploaderProps {
  onParsed?: (resume: Resume) => void;
  targetRole?: string;
  targetCompanies?: string;
}

export function ResumeUploader({ onParsed, targetRole, targetCompanies }: ResumeUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState("");
  const [parsing, setParsing] = useState(false);
  const [dragging, setDragging] = useState(false);

  const handleFiles = async (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    if (file.size > MAX_BYTES) {
      notifyError("文件超过 10MB 上限");
      return;
    }
    setFileName(file.name);
    setParsing(true);
    try {
      const result = await uploadResume(file, {
        targetRole: targetRole || undefined,
        targetCompanies: targetCompanies || undefined,
      });
      notifySuccess("简历解析完成");
      onParsed?.(result.resume);
    } catch (caught) {
      notifyError(caught instanceof Error ? caught.message : "简历上传失败");
    } finally {
      setParsing(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <div
      className={`group relative flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
        dragging
          ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950/40"
          : "border-gray-300 bg-white hover:border-indigo-400 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:hover:border-indigo-500 dark:hover:bg-gray-800"
      }`}
      onClick={() => inputRef.current?.click()}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        void handleFiles(event.dataTransfer.files);
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(event) => void handleFiles(event.target.files)}
      />

      {parsing ? (
        <>
          <Loader2 className="mb-3 h-8 w-8 animate-spin text-indigo-500" />
          <p className="text-sm font-medium text-gray-700 dark:text-gray-200">正在解析简历…</p>
          <p className="mt-1 text-xs text-gray-400">{fileName}</p>
        </>
      ) : (
        <>
          <FileUp className="mb-3 h-8 w-8 text-gray-400 transition-colors group-hover:text-indigo-500" />
          <p className="text-sm font-medium text-gray-700 dark:text-gray-200">
            拖拽简历到这里，或点击选择文件
          </p>
          <p className="mt-1 text-xs text-gray-400">
            支持 PDF / Word / Markdown / 纯文本，不超过 10MB
          </p>
          {fileName && (
            <span className="mt-3 inline-flex items-center gap-1 rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-600 dark:bg-gray-800 dark:text-gray-300">
              {fileName}
              <button
                type="button"
                aria-label="清除文件"
                onClick={(event) => {
                  event.stopPropagation();
                  setFileName("");
                }}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </span>
          )}
        </>
      )}
    </div>
  );
}
