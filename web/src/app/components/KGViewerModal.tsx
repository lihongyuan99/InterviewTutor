import { useState, useEffect, useCallback } from "react";
import { X, RefreshCw, AlertCircle, Network } from "lucide-react";
import { API_BASE_URL } from "../../lib/api";

interface KGNode {
  id: string;
  title: string;
  lit: boolean;
  score: number | null;
  count: number;
}

interface KGDimension {
  dimension: string;
  label: string;
  nodes: KGNode[];
}

interface DocGraph {
  task_id: string;
  dimensions: KGDimension[];
  stats: { total: number; lit: number };
}

interface KGViewerModalProps {
  taskId: string;
  isOpen: boolean;
  onClose: () => void;
}

const LIT_COLOR = "#a78bfa"; // 点亮紫色
const DIM_COLOR = "#3f3f46"; // 未点亮暗灰
const DIM_BORDER = "#52525b";

export function KGViewerModal({ taskId, isOpen, onClose }: KGViewerModalProps) {
  const [graph, setGraph] = useState<DocGraph | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hovered, setHovered] = useState<KGNode | null>(null);

  const loadGraph = useCallback(async () => {
    if (!taskId) return;
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `${API_BASE_URL}/kg/doc-graph?task_id=${encodeURIComponent(taskId)}`
      );
      if (!response.ok) {
        throw new Error("加载知识图谱失败");
      }
      const data: DocGraph = await response.json();
      setGraph(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setIsLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    if (isOpen && taskId) {
      loadGraph();
    }
  }, [isOpen, taskId, loadGraph]);

  if (!isOpen) return null;

  const total = graph?.stats.total ?? 0;
  const lit = graph?.stats.lit ?? 0;
  const progress = total > 0 ? Math.round((lit / total) * 100) : 0;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-900 rounded-xl w-[95vw] h-[95vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
          <div className="flex items-center gap-3">
            <Network className="w-5 h-5 text-purple-400" />
            <h2 className="text-xl font-semibold text-white">知识图谱</h2>
            <span className="text-sm text-gray-400">
              已点亮 {lit} / {total}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={loadGraph}
              disabled={isLoading}
              className="flex items-center gap-2 px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-600 disabled:opacity-50 transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
              <span className="text-sm font-medium">刷新</span>
            </button>
            <button
              onClick={onClose}
              className="p-2 text-gray-400 hover:text-white transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Progress bar */}
        <div className="px-6 pt-4">
          <div className="h-2 w-full bg-gray-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-purple-500 transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 relative overflow-auto p-6">
          {isLoading ? (
            <div className="absolute inset-0 flex items-center justify-center">
              <RefreshCw className="w-8 h-8 text-purple-400 animate-spin" />
            </div>
          ) : error ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
              <AlertCircle className="w-12 h-12 text-yellow-400" />
              <p className="text-gray-300">{error}</p>
            </div>
          ) : !graph || graph.dimensions.length === 0 ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
              <AlertCircle className="w-12 h-12 text-yellow-400" />
              <p className="text-gray-300">暂无知识图谱数据</p>
              <p className="text-sm text-gray-500">
                请先确保知识库已构建索引（调用重建接口）
              </p>
            </div>
          ) : (
            <div className="space-y-8">
              {graph.dimensions.map((dim) => (
                <DimensionBlock
                  key={dim.dimension}
                  dimension={dim}
                  onHover={setHovered}
                />
              ))}
            </div>
          )}
        </div>

        {/* Hover tooltip */}
        {hovered && (
          <div className="absolute bottom-4 left-6 right-6 pointer-events-none">
            <div className="bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 shadow-lg">
              <p className="text-white text-sm font-medium">{hovered.title}</p>
              <p className="text-gray-400 text-xs mt-1">
                {hovered.lit
                  ? `已点亮 · 相似度 ${hovered.score?.toFixed(2)} · 命中 ${hovered.count} 次`
                  : "尚未点亮"}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

interface DimensionBlockProps {
  dimension: KGDimension;
  onHover: (node: KGNode | null) => void;
}

function DimensionBlock({ dimension, onHover }: DimensionBlockProps) {
  const litCount = dimension.nodes.filter((n) => n.lit).length;

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <h3 className="text-lg font-semibold text-gray-200">{dimension.label}</h3>
        <span className="text-xs text-gray-500">
          {litCount} / {dimension.nodes.length}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        {dimension.nodes.map((node) => (
          <button
            key={node.id}
            onMouseEnter={() => onHover(node)}
            onMouseLeave={() => onHover(null)}
            className="px-3 py-1.5 rounded-full text-sm transition-colors border"
            style={{
              backgroundColor: node.lit ? LIT_COLOR : DIM_COLOR,
              borderColor: node.lit ? "#c4b5fd" : DIM_BORDER,
              color: node.lit ? "#1e1b4b" : "#9ca3af",
            }}
          >
            {node.title}
          </button>
        ))}
      </div>
    </div>
  );
}
