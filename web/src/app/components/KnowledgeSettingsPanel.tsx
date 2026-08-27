import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  ExternalLink,
  History,
  Loader2,
  RefreshCw,
} from "lucide-react";

import { API_BASE_URL, extractErrorMessage } from "../../lib/api";

type SyncPhase =
  | "idle"
  | "checking"
  | "downloading"
  | "parsing"
  | "embedding"
  | "validating"
  | "activating"
  | "failed";

interface KnowledgeVersion {
  snapshot_id: string;
  bundled: boolean;
  source_sha: string;
  source_date: string;
  built_at: string | null;
  question_count: number;
  dimension_count: number;
  embedding_model: string;
  embedding_dimension: number;
}

interface KnowledgeSyncStatus {
  enabled: boolean;
  phase: SyncPhase;
  progress: { completed: number; total: number };
  current: KnowledgeVersion;
  latest_source_sha: string;
  latest_source_date: string;
  update_available: boolean;
  last_checked_at: string | null;
  last_success_at: string | null;
  next_check_at: string | null;
  last_error: string;
  can_rollback: boolean;
  suppressed_sha: string;
  interval_seconds: number;
  source_repository: string;
  source_ref: string;
  source_path: string;
}

const BUSY_PHASES = new Set<SyncPhase>([
  "checking",
  "downloading",
  "parsing",
  "embedding",
  "validating",
  "activating",
]);

const PHASE_LABELS: Record<SyncPhase, string> = {
  idle: "已是最新状态",
  checking: "正在检查上游版本",
  downloading: "正在下载固定版本",
  parsing: "正在解析知识题库",
  embedding: "正在生成增量向量",
  validating: "正在执行发布校验",
  activating: "正在切换知识快照",
  failed: "上次更新失败",
};

function formatTime(value: string | null | undefined): string {
  if (!value) return "尚无记录";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleString("zh-CN", { hour12: false });
}

function shortSha(value: string): string {
  return value ? value.slice(0, 8) : "内置基线";
}

export function KnowledgeSettingsPanel({ active }: { active: boolean }) {
  const [status, setStatus] = useState<KnowledgeSyncStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [action, setAction] = useState<"sync" | "rollback" | "">("");
  const [error, setError] = useState("");

  const loadStatus = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/knowledge/status`);
      if (!response.ok) throw new Error(await extractErrorMessage(response));
      setStatus((await response.json()) as KnowledgeSyncStatus);
      setError("");
    } catch (loadError: any) {
      setError(loadError?.message || "无法读取知识库状态");
    } finally {
      if (showLoading) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!active) return;
    void loadStatus(true);
  }, [active, loadStatus]);

  const busy = Boolean(status && BUSY_PHASES.has(status.phase));

  useEffect(() => {
    if (!active || !busy) return;
    const timer = window.setInterval(() => void loadStatus(), 1000);
    return () => window.clearInterval(timer);
  }, [active, busy, loadStatus]);

  const sourceUrl = useMemo(() => {
    if (!status) return "";
    const ref = status.current.source_sha || status.source_ref;
    return `https://github.com/${status.source_repository}/tree/${ref}/${status.source_path}`;
  }, [status]);

  const syncNow = async () => {
    setAction("sync");
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/knowledge/sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force: false }),
      });
      if (!response.ok) throw new Error(await extractErrorMessage(response));
      setStatus((await response.json()) as KnowledgeSyncStatus);
    } catch (syncError: any) {
      setError(syncError?.message || "无法启动知识库更新");
    } finally {
      setAction("");
    }
  };

  const rollback = async () => {
    if (!window.confirm("确定回滚到上一个成功的知识库版本吗？")) return;
    setAction("rollback");
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/knowledge/rollback`, {
        method: "POST",
      });
      if (!response.ok) throw new Error(await extractErrorMessage(response));
      setStatus((await response.json()) as KnowledgeSyncStatus);
    } catch (rollbackError: any) {
      setError(rollbackError?.message || "知识库回滚失败");
    } finally {
      setAction("");
    }
  };

  if (loading && !status) {
    return (
      <div className="flex min-h-72 items-center justify-center text-gray-500 dark:text-gray-400">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        正在读取知识库状态…
      </div>
    );
  }

  if (!status) {
    return (
      <div className="rounded-xl border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-900/20 p-4 text-sm text-red-700 dark:text-red-300">
        {error || "暂无知识库状态"}
      </div>
    );
  }

  const { completed, total } = status.progress;
  const progressPercent = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;
  const intervalHours = status.interval_seconds / 3600;
  const intervalLabel = Number.isInteger(intervalHours)
    ? intervalHours.toFixed(0)
    : intervalHours.toFixed(1);

  return (
    <div>
      <div className="mb-5">
        <h2 className="text-base font-semibold text-gray-950 dark:text-gray-100">知识库</h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          自动跟踪上游面试题库；校验失败时继续使用当前版本。
        </p>
      </div>

      {error && (
        <div className="mb-4 flex gap-2 rounded-xl border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-900/20 p-3 text-sm text-red-700 dark:text-red-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-emerald-50 dark:bg-emerald-900/30">
              <Database className="h-5 w-5 text-emerald-600 dark:text-emerald-300" />
            </span>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-semibold text-gray-950 dark:text-gray-100">当前知识快照</h3>
                <span className="rounded-full bg-gray-100 dark:bg-gray-700 px-2 py-0.5 font-mono text-[11px] text-gray-600 dark:text-gray-300">
                  {shortSha(status.current.source_sha)}
                </span>
                {status.current.bundled && (
                  <span className="rounded-full bg-blue-50 dark:bg-blue-900/30 px-2 py-0.5 text-[11px] text-blue-700 dark:text-blue-300">内置</span>
                )}
              </div>
              <a
                href={sourceUrl}
                target="_blank"
                rel="noreferrer"
                className="mt-1 inline-flex items-center gap-1 text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
              >
                {status.source_repository}/{status.source_path}
                <ExternalLink className="h-3 w-3" />
              </a>
            </div>
          </div>
          <div className="flex items-center gap-2 text-sm">
            {status.phase === "failed" ? (
              <AlertTriangle className="h-4 w-4 text-amber-500" />
            ) : busy ? (
              <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />
            ) : (
              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
            )}
            <span className="text-gray-600 dark:text-gray-300">{PHASE_LABELS[status.phase]}</span>
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="题目数" value={String(status.current.question_count)} />
          <Metric label="有效维度" value={String(status.current.dimension_count)} />
          <Metric
            label="Embedding"
            value={status.current.embedding_dimension ? `${status.current.embedding_dimension} 维` : "未记录"}
          />
          <Metric label="自动更新" value={status.enabled ? `每 ${intervalLabel} 小时` : "已关闭"} />
        </div>

        {busy && (
          <div className="mt-5">
            <div className="mb-2 flex justify-between text-xs text-gray-500 dark:text-gray-400">
              <span>{PHASE_LABELS[status.phase]}</span>
              <span>{total > 0 ? `${completed} / ${total}` : "准备中"}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-700">
              <div
                className="h-full rounded-full bg-indigo-500 transition-all duration-300"
                style={{ width: `${total > 0 ? Math.max(progressPercent, 2) : 12}%` }}
              />
            </div>
          </div>
        )}

        {status.last_error && (
          <div className="mt-5 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-3 text-sm text-amber-800 dark:text-amber-300">
            <p className="font-medium">旧版本仍在正常使用</p>
            <p className="mt-1 break-words text-xs leading-5">{status.last_error}</p>
          </div>
        )}

        <div className="mt-5 grid gap-2 border-t border-gray-100 dark:border-gray-700 pt-5 text-xs text-gray-500 dark:text-gray-400 sm:grid-cols-2">
          <p>上次检查：{formatTime(status.last_checked_at)}</p>
          <p>上次成功：{formatTime(status.last_success_at || status.current.built_at)}</p>
          <p>下次检查：{status.enabled ? formatTime(status.next_check_at) : "自动更新已关闭"}</p>
          <p>上游最新：{shortSha(status.latest_source_sha)}</p>
        </div>

        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <button
            type="button"
            onClick={rollback}
            disabled={!status.can_rollback || busy || Boolean(action)}
            className="flex items-center gap-2 rounded-full border border-gray-300 dark:border-gray-600 px-4 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {action === "rollback" ? <Loader2 className="h-4 w-4 animate-spin" /> : <History className="h-4 w-4" />}
            回滚上一版本
          </button>
          <button
            type="button"
            onClick={syncNow}
            disabled={busy || Boolean(action)}
            className="flex items-center gap-2 rounded-full bg-gray-950 px-4 py-2.5 text-sm text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy || action === "sync" ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {busy ? "正在更新" : "立即检查并更新"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-gray-50 dark:bg-gray-900/50 p-3">
      <span className="block text-xs text-gray-500 dark:text-gray-400">{label}</span>
      <span className="mt-1 block truncate text-sm font-semibold text-gray-900 dark:text-gray-100" title={value}>{value}</span>
    </div>
  );
}
