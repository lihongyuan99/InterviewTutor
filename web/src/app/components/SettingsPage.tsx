import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  Check,
  ChevronRight,
  Circle,
  CircleDot,
  Cpu,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Pencil,
  Plus,
  Server,
  Trash2,
} from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "./ui/sheet";
import { API_BASE_URL, extractErrorMessage } from "../../lib/api";
import {
  EVENT_LLM_SETTINGS_UPDATED,
  EVENT_OPEN_SETTINGS,
  emitAppEvent,
} from "../../lib/events";
import { KnowledgeSettingsPanel } from "./KnowledgeSettingsPanel";

type Protocol = "openai_compatible" | "anthropic" | "openai_responses";
type TutorStyle = "socratic" | "direct" | "interactive" | "custom";
type SettingsSection = "teaching" | "models" | "knowledge";

interface ModelEntry {
  id: string;
  name: string;
}

interface ProviderConfig {
  id: string;
  name: string;
  protocol: Protocol;
  api_key: string;
  api_key_configured?: boolean;
  api_key_hint?: string;
  api_base_url: string;
  models: ModelEntry[];
  active_model: string;
  temperature: number;
  max_tokens: number;
}

interface TutorPreferences {
  style: TutorStyle;
  custom_prompt: string;
}

interface LLMSettings {
  active_provider_id: string;
  providers: ProviderConfig[];
  tutor_preferences: TutorPreferences;
}

interface SettingsPageProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const PROTOCOLS: Array<{
  value: Protocol;
  label: string;
  shortLabel: string;
  description: string;
  defaultUrl: string;
}> = [
  {
    value: "openai_compatible",
    label: "OpenAI Compatible",
    shortLabel: "OpenAI 兼容",
    description: "适用于 DeepSeek、硅基流动及其他 Chat Completions 兼容服务",
    defaultUrl: "https://api.openai.com/v1",
  },
  {
    value: "anthropic",
    label: "Anthropic",
    shortLabel: "Anthropic",
    description: "使用 Anthropic Messages API 调用 Claude 模型",
    defaultUrl: "https://api.anthropic.com",
  },
  {
    value: "openai_responses",
    label: "OpenAI Responses",
    shortLabel: "OpenAI Responses",
    description: "使用 OpenAI Responses API，适合新一代 OpenAI 模型",
    defaultUrl: "https://api.openai.com/v1",
  },
];

const DEFAULT_TUTOR_PREFERENCES: TutorPreferences = {
  style: "socratic",
  custom_prompt: "",
};

const TUTOR_STYLES: Array<{
  value: TutorStyle;
  label: string;
  badge: string;
  description: string;
  prompt: string;
}> = [
  {
    value: "socratic",
    label: "苏格拉底式教学",
    badge: "引导型",
    description: "通过问题和线索，引导学习者自己推导答案",
    prompt:
      "先判断学习者已经理解到哪一步，再用循序渐进的提问和提示引导其自行发现答案；必要时给出关键线索，每轮最多提出一个核心问题。",
  },
  {
    value: "direct",
    label: "直接讲解型",
    badge: "讲授型",
    description: "先给出清晰结论，再分步骤讲解概念和例子",
    prompt:
      "优先给出清晰结论，再分步骤解释关键概念、依据和例子；少用反问，除非学习者明确要求测验，否则不要用问题代替答案。",
  },
  {
    value: "interactive",
    label: "问答互动型",
    badge: "互动型",
    description: "短讲解结合小问题，持续确认学习者的理解",
    prompt:
      "先做简短讲解，再用一个小问题或选择题确认理解，根据学习者的回答继续补充或纠正；一次只推进一个知识点。",
  },
  {
    value: "custom",
    label: "自定义",
    badge: "个性化",
    description: "使用你自己的教学风格提示词",
    prompt: "",
  },
];

function normalizeSettings(payload: LLMSettings): LLMSettings {
  return {
    ...payload,
    tutor_preferences: payload.tutor_preferences || DEFAULT_TUTOR_PREFERENCES,
  };
}

function protocolMeta(protocol: Protocol) {
  return PROTOCOLS.find((item) => item.value === protocol) || PROTOCOLS[0];
}

function cloneProvider(provider: ProviderConfig): ProviderConfig {
  return {
    ...provider,
    api_key: "",
    models: provider.models.map((model) => ({ ...model })),
  };
}

function createProvider(): ProviderConfig {
  const id = `custom-${Date.now().toString(36)}`;
  return {
    id,
    name: "自定义服务",
    protocol: "openai_compatible",
    api_key: "",
    api_key_configured: false,
    api_key_hint: "",
    api_base_url: "",
    models: [{ id: "", name: "" }],
    active_model: "",
    temperature: 0.7,
    max_tokens: 2000,
  };
}

export function SettingsPage({ open, onOpenChange }: SettingsPageProps) {
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [activeSection, setActiveSection] = useState<SettingsSection>("teaching");
  const [teachingDraft, setTeachingDraft] = useState<TutorPreferences>(
    DEFAULT_TUTOR_PREFERENCES,
  );
  const [draft, setDraft] = useState<ProviderConfig | null>(null);
  const [isNewProvider, setIsNewProvider] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const requestedSectionRef = useRef<SettingsSection | null>(null);

  const activeProvider = useMemo(
    () =>
      settings?.providers.find(
        (provider) => provider.id === settings.active_provider_id,
      ) || null,
    [settings],
  );

  useEffect(() => {
    const selectRequestedSection = (event: Event) => {
      const section = (event as CustomEvent<{ section?: SettingsSection }>).detail
        ?.section;
      if (!section) return;
      requestedSectionRef.current = section;
      setActiveSection(section);
    };
    window.addEventListener(EVENT_OPEN_SETTINGS, selectRequestedSection);
    return () =>
      window.removeEventListener(EVENT_OPEN_SETTINGS, selectRequestedSection);
  }, []);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setIsLoading(true);
    setError("");
    setNotice("");
    setDraft(null);
    setIsNewProvider(false);
    setActiveSection(requestedSectionRef.current || "teaching");
    requestedSectionRef.current = null;

    fetch(`${API_BASE_URL}/settings/llm`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(await extractErrorMessage(response));
        return response.json();
      })
      .then((payload: LLMSettings) => {
        const normalized = normalizeSettings(payload);
        setSettings(normalized);
        setTeachingDraft(normalized.tutor_preferences);
      })
      .catch((loadError) => {
        if (loadError?.name !== "AbortError") {
          setError(loadError?.message || "无法读取模型配置");
        }
      })
      .finally(() => setIsLoading(false));

    return () => controller.abort();
  }, [open]);

  const persistSettings = async (nextSettings: LLMSettings, message: string) => {
    setIsSaving(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(`${API_BASE_URL}/settings/llm`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextSettings),
      });
      if (!response.ok) throw new Error(await extractErrorMessage(response));
      const saved = normalizeSettings(await response.json());
      setSettings(saved);
      setTeachingDraft(saved.tutor_preferences);
      setNotice(message);
      emitAppEvent(EVENT_LLM_SETTINGS_UPDATED, saved);
      return saved;
    } catch (saveError: any) {
      setError(saveError?.message || "保存模型配置失败");
      return null;
    } finally {
      setIsSaving(false);
    }
  };

  const editProvider = (provider: ProviderConfig) => {
    setDraft(cloneProvider(provider));
    setIsNewProvider(false);
    setShowApiKey(false);
    setError("");
    setNotice("");
  };

  const addProvider = () => {
    setDraft(createProvider());
    setIsNewProvider(true);
    setShowApiKey(false);
    setError("");
    setNotice("");
  };

  const validateDraft = () => {
    if (!draft) return "没有可保存的服务";
    if (!draft.name.trim()) return "请输入服务名称";
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(draft.id.trim())) {
      return "服务 ID 只能包含字母、数字、点、下划线和连字符";
    }
    if (draft.api_base_url && !/^https?:\/\//i.test(draft.api_base_url)) {
      return "API 地址需要以 http:// 或 https:// 开头";
    }
    const validModels = draft.models.filter(
      (model) => model.id.trim() && model.name.trim(),
    );
    if (!validModels.length) return "请至少添加一个完整的模型";
    if (new Set(validModels.map((model) => model.id.trim())).size !== validModels.length) {
      return "模型 ID 不能重复";
    }
    if (isNewProvider && !draft.api_key.trim()) return "新服务需要填写 API 密钥";
    return "";
  };

  const saveDraft = async () => {
    if (!settings || !draft) return;
    const validationError = validateDraft();
    if (validationError) {
      setError(validationError);
      return;
    }

    const models = draft.models
      .map((model) => ({ id: model.id.trim(), name: model.name.trim() }))
      .filter((model) => model.id && model.name);
    const normalized: ProviderConfig = {
      ...draft,
      id: draft.id.trim(),
      name: draft.name.trim(),
      api_base_url: draft.api_base_url.trim().replace(/\/$/, ""),
      models,
      active_model: models.some((model) => model.id === draft.active_model)
        ? draft.active_model
        : models[0].id,
    };

    const providers = isNewProvider
      ? [...settings.providers, normalized]
      : settings.providers.map((provider) =>
          provider.id === normalized.id ? normalized : provider,
        );
    const nextSettings = {
      ...settings,
      providers,
      active_provider_id: settings.active_provider_id || normalized.id,
    };
    const saved = await persistSettings(nextSettings, "模型服务已保存");
    if (saved) {
      setDraft(null);
      setIsNewProvider(false);
    }
  };

  const activateProvider = async (providerId: string) => {
    if (!settings || settings.active_provider_id === providerId) return;
    await persistSettings(
      { ...settings, active_provider_id: providerId },
      "已切换当前模型服务",
    );
  };

  const deleteProvider = async () => {
    if (!settings || !draft || isNewProvider) {
      setDraft(null);
      return;
    }
    if (settings.providers.length <= 1) {
      setError("至少需要保留一个模型服务");
      return;
    }
    if (!window.confirm(`确定删除“${draft.name}”及其密钥配置吗？`)) return;

    const providers = settings.providers.filter(
      (provider) => provider.id !== draft.id,
    );
    const activeProviderId =
      settings.active_provider_id === draft.id
        ? providers[0].id
        : settings.active_provider_id;
    const saved = await persistSettings(
      { ...settings, active_provider_id: activeProviderId, providers },
      "模型服务已删除",
    );
    if (saved) setDraft(null);
  };

  const updateDraft = <K extends keyof ProviderConfig>(
    key: K,
    value: ProviderConfig[K],
  ) => {
    setDraft((current) => (current ? { ...current, [key]: value } : current));
  };

  const updateModel = (index: number, patch: Partial<ModelEntry>) => {
    setDraft((current) => {
      if (!current) return current;
      const models = current.models.map((model, modelIndex) =>
        modelIndex === index ? { ...model, ...patch } : model,
      );
      return { ...current, models };
    });
  };

  const removeModel = (index: number) => {
    setDraft((current) => {
      if (!current || current.models.length <= 1) return current;
      const removed = current.models[index];
      const models = current.models.filter((_, modelIndex) => modelIndex !== index);
      return {
        ...current,
        models,
        active_model:
          current.active_model === removed.id ? models[0]?.id || "" : current.active_model,
      };
    });
  };

  const handleProtocolChange = (protocol: Protocol) => {
    if (!draft) return;
    const previousDefault = protocolMeta(draft.protocol).defaultUrl;
    const nextDefault = protocolMeta(protocol).defaultUrl;
    setDraft({
      ...draft,
      protocol,
      api_base_url:
        !draft.api_base_url || draft.api_base_url === previousDefault
          ? nextDefault
          : draft.api_base_url,
    });
  };

  const saveTeachingStyle = async () => {
    if (!settings) return;
    if (teachingDraft.style === "custom" && !teachingDraft.custom_prompt.trim()) {
      setError("请输入自定义教学提示词");
      return;
    }
    await persistSettings(
      {
        ...settings,
        tutor_preferences: {
          ...teachingDraft,
          custom_prompt: teachingDraft.custom_prompt.trim(),
        },
      },
      "教学风格已保存，下一条回复开始生效",
    );
  };

  const selectedTutorStyle =
    TUTOR_STYLES.find((style) => style.value === teachingDraft.style) ||
    TUTOR_STYLES[0];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-0 sm:max-w-[760px]">
        <SheetHeader className="border-b border-gray-200 dark:border-gray-700 px-7 py-5 pr-14">
          <SheetTitle className="flex items-center gap-3 text-xl text-gray-950 dark:text-gray-100">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-50 dark:bg-indigo-900/40">
              <Cpu className="h-5 w-5 text-indigo-600 dark:text-indigo-300" />
            </span>
            <span>系统设置</span>
          </SheetTitle>
          <SheetDescription className="pl-[52px] text-gray-500 dark:text-gray-400">
            管理教学风格、模型服务和知识库更新
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto bg-[#f7f8fa] dark:bg-gray-950">
          <div className="mx-auto max-w-3xl p-6">
            {!draft && (
              <div
                role="tablist"
                aria-label="设置分类"
                className="mb-5 grid grid-cols-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-1 shadow-sm"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeSection === "teaching"}
                  onClick={() => {
                    setActiveSection("teaching");
                    setError("");
                    setNotice("");
                  }}
                  className={`rounded-lg px-4 py-2.5 text-sm font-medium transition-colors ${
                    activeSection === "teaching"
                      ? "bg-gray-950 text-white shadow-sm"
                      : "text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 hover:text-gray-950 dark:hover:text-gray-100"
                  }`}
                >
                  教学风格
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeSection === "models"}
                  onClick={() => {
                    setActiveSection("models");
                    setError("");
                    setNotice("");
                  }}
                  className={`rounded-lg px-4 py-2.5 text-sm font-medium transition-colors ${
                    activeSection === "models"
                      ? "bg-gray-950 text-white shadow-sm"
                      : "text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 hover:text-gray-950 dark:hover:text-gray-100"
                  }`}
                >
                  模型服务
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeSection === "knowledge"}
                  onClick={() => {
                    setActiveSection("knowledge");
                    setError("");
                    setNotice("");
                  }}
                  className={`rounded-lg px-4 py-2.5 text-sm font-medium transition-colors ${
                    activeSection === "knowledge"
                      ? "bg-gray-950 text-white shadow-sm"
                      : "text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 hover:text-gray-950 dark:hover:text-gray-100"
                  }`}
                >
                  知识库
                </button>
              </div>
            )}

            {error && activeSection !== "knowledge" && (
              <div className="mb-4 flex items-start gap-2 rounded-xl border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-900/20 px-4 py-3 text-sm text-red-700 dark:text-red-400">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}
            {notice && activeSection !== "knowledge" && (
              <div className="mb-4 flex items-center gap-2 rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 px-4 py-3 text-sm text-emerald-700 dark:text-emerald-400">
                <Check className="h-4 w-4" />
                <span>{notice}</span>
              </div>
            )}

            {activeSection === "knowledge" && !draft ? (
              <KnowledgeSettingsPanel active={open && activeSection === "knowledge"} />
            ) : isLoading ? (
              <div className="flex min-h-72 items-center justify-center text-gray-500">
                <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                正在读取配置…
              </div>
            ) : draft ? (
              <div>
                <div className="mb-5 flex items-center justify-between">
                  <button
                    type="button"
                    onClick={() => {
                      setDraft(null);
                      setError("");
                    }}
                    className="flex items-center gap-2 text-sm text-gray-600 transition-colors hover:text-gray-950"
                  >
                    <ArrowLeft className="h-4 w-4" />
                    返回模型服务
                  </button>
                  {!isNewProvider && (
                    <button
                      type="button"
                      onClick={deleteProvider}
                      disabled={isSaving}
                      className="flex items-center gap-1.5 text-sm text-red-500 transition-colors hover:text-red-700 disabled:opacity-50"
                    >
                      <Trash2 className="h-4 w-4" />
                      删除服务
                    </button>
                  )}
                </div>

                <form
                  autoComplete="off"
                  onSubmit={(event) => {
                    event.preventDefault();
                    saveDraft();
                  }}
                  className="rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-6 shadow-sm"
                >
                  <div className="mb-6 flex items-center gap-3">
                    <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-gray-950 text-white">
                      <Server className="h-5 w-5" />
                    </span>
                    <div>
                      <h2 className="text-lg font-semibold text-gray-950 dark:text-gray-100">
                        {isNewProvider ? "添加模型服务" : `编辑 ${draft.name}`}
                      </h2>
                      <p className="text-sm text-gray-500 dark:text-gray-400">密钥只保存在本机后端配置中</p>
                    </div>
                  </div>

                  <div className="space-y-6 rounded-2xl bg-gray-50 dark:bg-gray-900/50 p-5">
                    <div className="grid gap-4 sm:grid-cols-2">
                      <Field label="服务名称">
                        <input
                          value={draft.name}
                          autoComplete="organization"
                          onChange={(event) => updateDraft("name", event.target.value)}
                          placeholder="例如 DeepSeek"
                          className="settings-input"
                        />
                      </Field>
                      <Field label="服务 ID" hint="保存后建议保持不变">
                        <input
                          value={draft.id}
                          autoComplete="off"
                          onChange={(event) => updateDraft("id", event.target.value)}
                          disabled={!isNewProvider}
                          placeholder="deepseek-official"
                          className="settings-input disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-500 dark:disabled:bg-gray-700 dark:disabled:text-gray-500"
                        />
                      </Field>
                    </div>

                    <div>
                      <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-200">调用协议</label>
                      <div className="grid gap-2 sm:grid-cols-3">
                        {PROTOCOLS.map((protocol) => {
                          const selected = draft.protocol === protocol.value;
                          return (
                            <button
                              key={protocol.value}
                              type="button"
                              onClick={() => handleProtocolChange(protocol.value)}
                              className={`rounded-xl border px-3 py-3 text-left transition-all ${
                                selected
                                  ? "border-gray-950 bg-gray-950 text-white shadow-sm"
                                  : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 hover:border-gray-300"
                              }`}
                            >
                              <span className="block text-sm font-semibold">{protocol.shortLabel}</span>
                              <span
                                className={`mt-1 block text-[11px] leading-4 ${
                                  selected ? "text-gray-300" : "text-gray-500"
                                }`}
                              >
                                {protocol.value === "openai_compatible"
                                  ? "Chat Completions"
                                  : protocol.value === "anthropic"
                                    ? "Messages API"
                                    : "Responses API"}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                      <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                        {protocolMeta(draft.protocol).description}
                      </p>
                    </div>

                    <Field label="API 密钥">
                      <div className="relative">
                        <KeyRound className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                        <input
                          type={showApiKey ? "text" : "password"}
                          value={draft.api_key}
                          onChange={(event) => updateDraft("api_key", event.target.value)}
                          placeholder={
                            draft.api_key_configured
                              ? `已保存 ${draft.api_key_hint || "••••"}，留空则不修改`
                              : "输入 API 密钥"
                          }
                          autoComplete="new-password"
                          className="settings-input px-10"
                        />
                        <button
                          type="button"
                          onClick={() => setShowApiKey((visible) => !visible)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1 text-gray-400 dark:text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-gray-700 dark:hover:text-gray-200"
                          aria-label={showApiKey ? "隐藏密钥" : "显示密钥"}
                        >
                          {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      </div>
                    </Field>

                    <div className="border-t border-gray-200 dark:border-gray-700 pt-5">
                      <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-gray-700 dark:text-gray-200">
                        <ChevronRight className="h-4 w-4 rotate-90" />
                        自定义设置
                      </div>
                      <Field label="API 地址" hint="可填写代理或兼容服务地址">
                        <input
                          value={draft.api_base_url}
                          autoComplete="url"
                          onChange={(event) => updateDraft("api_base_url", event.target.value)}
                          placeholder={protocolMeta(draft.protocol).defaultUrl}
                          className="settings-input font-mono text-sm"
                        />
                      </Field>
                      <div className="mt-4 grid gap-4 sm:grid-cols-2">
                        <Field label="温度（Temperature）">
                          <input
                            type="number"
                            min="0"
                            max="2"
                            step="0.1"
                            value={draft.temperature}
                            onChange={(event) =>
                              updateDraft("temperature", Number(event.target.value))
                            }
                            className="settings-input"
                          />
                        </Field>
                        <Field label="最大输出长度">
                          <input
                            type="number"
                            min="1"
                            max="200000"
                            value={draft.max_tokens}
                            onChange={(event) =>
                              updateDraft("max_tokens", Number(event.target.value))
                            }
                            className="settings-input"
                          />
                        </Field>
                      </div>
                    </div>

                    <div className="border-t border-gray-200 dark:border-gray-700 pt-5">
                      <div className="mb-1 flex items-center justify-between">
                        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200">模型目录</h3>
                        <span className="text-xs text-gray-400 dark:text-gray-500">点击圆点设为服务默认模型</span>
                      </div>
                      <p className="mb-3 text-xs text-gray-500 dark:text-gray-400">左侧填写 API 模型 ID，右侧填写界面显示名称</p>

                      <div className="space-y-2">
                        {draft.models.map((model, index) => {
                          const selected =
                            Boolean(model.id) && draft.active_model === model.id;
                          return (
                            <div
                              key={index}
                              className={`grid grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)_36px_36px] gap-2 rounded-xl border p-2 ${
                                selected
                                  ? "border-indigo-200 dark:border-indigo-700 bg-indigo-50/60 dark:bg-indigo-900/30"
                                  : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                              }`}
                            >
                              <input
                                value={model.id}
                                autoComplete="off"
                                onChange={(event) => {
                                  const previousId = model.id;
                                  const nextId = event.target.value;
                                  updateModel(index, { id: nextId });
                                  if (draft.active_model === previousId) {
                                    updateDraft("active_model", nextId);
                                  }
                                }}
                                placeholder="model-id"
                                className="min-w-0 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 dark:focus:ring-indigo-900/40"
                              />
                              <input
                                value={model.name}
                                autoComplete="off"
                                onChange={(event) =>
                                  updateModel(index, { name: event.target.value })
                                }
                                placeholder="显示名称"
                                className="min-w-0 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 dark:focus:ring-indigo-900/40"
                              />
                              <button
                                type="button"
                                onClick={() => model.id && updateDraft("active_model", model.id)}
                                disabled={!model.id}
                                className="flex items-center justify-center rounded-lg text-gray-400 dark:text-gray-500 transition-colors hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-indigo-600 disabled:opacity-30"
                                aria-label="设为默认模型"
                              >
                                {selected ? (
                                  <Check className="h-5 w-5 text-indigo-600" />
                                ) : (
                                  <Circle className="h-4 w-4" />
                                )}
                              </button>
                              <button
                                type="button"
                                onClick={() => removeModel(index)}
                                disabled={draft.models.length <= 1}
                                className="flex items-center justify-center rounded-lg text-gray-400 transition-colors hover:bg-red-50 hover:text-red-500 disabled:opacity-25"
                                aria-label="删除模型"
                              >
                                <Trash2 className="h-4 w-4" />
                              </button>
                            </div>
                          );
                        })}
                      </div>

                      <button
                        type="button"
                        onClick={() =>
                          updateDraft("models", [...draft.models, { id: "", name: "" }])
                        }
                        className="mt-3 flex items-center gap-1.5 rounded-full border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3.5 py-2 text-sm text-gray-700 dark:text-gray-200 transition-colors hover:border-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700"
                      >
                        <Plus className="h-4 w-4" />
                        添加模型
                      </button>
                    </div>
                  </div>

                  <div className="mt-6 flex justify-end gap-3">
                    <button
                      type="button"
                      onClick={() => setDraft(null)}
                      disabled={isSaving}
                      className="rounded-full border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-5 py-2.5 text-sm text-gray-700 dark:text-gray-200 transition-colors hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
                    >
                      取消
                    </button>
                    <button
                      type="submit"
                      disabled={isSaving}
                      className="flex min-w-24 items-center justify-center gap-2 rounded-full bg-gray-950 px-5 py-2.5 text-sm text-white transition-colors hover:bg-gray-800 disabled:opacity-50"
                    >
                      {isSaving && <Loader2 className="h-4 w-4 animate-spin" />}
                      保存
                    </button>
                  </div>
                </form>
              </div>
            ) : settings && activeSection === "teaching" ? (
              <div>
                <div className="mb-5">
                  <h2 className="text-base font-semibold text-gray-950 dark:text-gray-100">AI 代理配置</h2>
                  <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">管理教学代理的行为和回答风格</p>
                </div>

                <div className="rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-6 shadow-sm">
                  <div className="mb-5 flex items-start gap-3">
                    <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-violet-50 dark:bg-violet-900/40 text-lg font-semibold text-violet-600 dark:text-violet-300">
                      AI
                    </span>
                    <div>
                      <h3 className="font-semibold text-gray-950 dark:text-gray-100">选择教学风格</h3>
                      <p className="mt-1 text-sm leading-5 text-gray-500 dark:text-gray-400">
                        风格提示词会应用到问题分析、知识讲解、启发追问和最终回复。
                      </p>
                    </div>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    {TUTOR_STYLES.map((style) => {
                      const selected = teachingDraft.style === style.value;
                      return (
                        <button
                          key={style.value}
                          type="button"
                          role="radio"
                          aria-checked={selected}
                          onClick={() => {
                            setTeachingDraft((current) => ({
                              ...current,
                              style: style.value,
                            }));
                            setError("");
                            setNotice("");
                          }}
                          className={`rounded-xl border p-4 text-left transition-all ${
                            selected
                              ? "border-violet-400 dark:border-violet-600 bg-violet-50 dark:bg-violet-900/30 ring-2 ring-violet-100 dark:ring-violet-900/40"
                              : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
                          }`}
                        >
                          <span className="flex items-center justify-between gap-3">
                            <span className="font-medium text-gray-950 dark:text-gray-100">{style.label}</span>
                            <span
                              className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                                selected
                                  ? "bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300"
                                  : "bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400"
                              }`}
                            >
                              {style.badge}
                            </span>
                          </span>
                          <span className="mt-2 block text-xs leading-5 text-gray-500 dark:text-gray-400">
                            {style.description}
                          </span>
                        </button>
                      );
                    })}
                  </div>

                  {teachingDraft.style === "custom" && (
                    <div className="mt-5">
                      <Field
                        label="自定义教学提示词"
                        hint={`${teachingDraft.custom_prompt.length}/4000`}
                      >
                        <textarea
                          value={teachingDraft.custom_prompt}
                          maxLength={4000}
                          onChange={(event) =>
                            setTeachingDraft((current) => ({
                              ...current,
                              custom_prompt: event.target.value,
                            }))
                          }
                          placeholder="例如：你是一位耐心的编程导师。先用生活化比喻解释概念，再给一个可运行的小例子，最后邀请我动手修改其中一处。"
                          className="settings-input min-h-32 resize-y py-3 leading-6"
                        />
                      </Field>
                    </div>
                  )}

                  <div className="mt-5 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 p-4">
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <span className="text-sm font-medium text-gray-700 dark:text-gray-200">当前风格提示词</span>
                      <span className="text-xs text-gray-400 dark:text-gray-500">保存后应用于新回复</span>
                    </div>
                    <p className="text-sm leading-6 text-gray-600 dark:text-gray-300">
                      {teachingDraft.style === "custom"
                        ? teachingDraft.custom_prompt || "输入你的自定义教学提示词后即可保存。"
                        : selectedTutorStyle.prompt}
                    </p>
                  </div>

                  <div className="mt-6 flex items-center justify-between gap-4 border-t border-gray-100 dark:border-gray-700 pt-5">
                    <p className="text-xs leading-5 text-gray-500 dark:text-gray-400">
                      当前已保存：
                      {TUTOR_STYLES.find(
                        (style) => style.value === settings.tutor_preferences.style,
                      )?.label || "苏格拉底式教学"}
                    </p>
                    <button
                      type="button"
                      onClick={saveTeachingStyle}
                      disabled={isSaving}
                      className="flex min-w-28 items-center justify-center gap-2 rounded-full bg-gray-950 px-5 py-2.5 text-sm text-white transition-colors hover:bg-gray-800 disabled:opacity-50"
                    >
                      {isSaving && <Loader2 className="h-4 w-4 animate-spin" />}
                      保存教学风格
                    </button>
                  </div>
                </div>
              </div>
            ) : settings ? (
              <div>
                <div className="mb-5 flex items-end justify-between">
                  <div>
                    <h2 className="text-base font-semibold text-gray-950 dark:text-gray-100">模型服务</h2>
                    <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">选择当前服务，或添加自定义 API</p>
                  </div>
                  <button
                    type="button"
                    onClick={addProvider}
                    className="flex items-center gap-1.5 rounded-full border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3.5 py-2 text-sm text-gray-700 dark:text-gray-200 shadow-sm transition-colors hover:border-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700"
                  >
                    <Plus className="h-4 w-4" />
                    添加服务
                  </button>
                </div>

                <div className="space-y-3">
                  {settings.providers.map((provider) => {
                    const isActive = provider.id === settings.active_provider_id;
                    const selectedModel =
                      provider.models.find((model) => model.id === provider.active_model) ||
                      provider.models[0];
                    return (
                      <div
                        key={provider.id}
                        className={`rounded-2xl border bg-white dark:bg-gray-800 p-5 shadow-sm transition-all ${
                          isActive
                            ? "border-indigo-300 dark:border-indigo-600 ring-2 ring-indigo-100 dark:ring-indigo-900/40"
                            : "border-gray-200 dark:border-gray-700 hover:border-gray-300"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex min-w-0 items-start gap-3">
                            <span
                              className={`mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${
                                isActive
                                  ? "bg-indigo-600 text-white"
                                  : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300"
                              }`}
                            >
                              <Server className="h-5 w-5" />
                            </span>
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <h3 className="truncate font-semibold text-gray-950 dark:text-gray-100">{provider.name}</h3>
                                <span
                                  className={`h-2 w-2 rounded-full ${
                                    provider.api_key_configured ? "bg-emerald-500" : "bg-red-500"
                                  }`}
                                  title={
                                    provider.api_key_configured ? "已配置密钥" : "未配置密钥"
                                  }
                                />
                                {isActive && (
                                  <span className="rounded-full bg-indigo-50 dark:bg-indigo-900/40 px-2 py-0.5 text-[11px] font-medium text-indigo-700 dark:text-indigo-300">
                                    当前使用
                                  </span>
                                )}
                              </div>
                              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                                <span>{provider.id}</span>
                                <span>·</span>
                                <span>{protocolMeta(provider.protocol).label}</span>
                              </div>
                            </div>
                          </div>
                          <button
                            type="button"
                            onClick={() => editProvider(provider)}
                            className="flex shrink-0 items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-600 px-3 py-1.5 text-sm text-gray-700 dark:text-gray-200 transition-colors hover:border-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                            编辑
                          </button>
                        </div>

                        <div className="mt-4 grid gap-3 rounded-xl bg-gray-50 dark:bg-gray-900/50 p-4 sm:grid-cols-2">
                          <div>
                            <span className="block text-xs text-gray-500 dark:text-gray-400">默认模型</span>
                            <span className="mt-1 block truncate text-sm font-medium text-gray-900 dark:text-gray-100">
                              {selectedModel?.name || provider.active_model}
                            </span>
                            <span className="mt-0.5 block truncate font-mono text-xs text-gray-500 dark:text-gray-400">
                              {provider.active_model}
                            </span>
                          </div>
                          <div>
                            <span className="block text-xs text-gray-500 dark:text-gray-400">API 地址</span>
                            <span className="mt-1 block truncate font-mono text-xs text-gray-700 dark:text-gray-300">
                              {provider.api_base_url || protocolMeta(provider.protocol).defaultUrl}
                            </span>
                            <span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">
                              {provider.models.length} 个模型 · T {provider.temperature}
                            </span>
                          </div>
                        </div>

                        {!isActive && (
                          <div className="mt-4 flex justify-end">
                            <button
                              type="button"
                              onClick={() => activateProvider(provider.id)}
                              disabled={isSaving || !provider.api_key_configured}
                              className="flex items-center gap-1.5 text-sm font-medium text-indigo-600 transition-colors hover:text-indigo-800 disabled:cursor-not-allowed disabled:text-gray-400"
                            >
                              设为当前服务
                              <ChevronRight className="h-4 w-4" />
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {activeProvider && !activeProvider.api_key_configured && (
                  <div className="mt-4 flex gap-3 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/30 p-4 text-sm text-amber-800 dark:text-amber-300">
                    <KeyRound className="mt-0.5 h-4 w-4 shrink-0" />
                    <p>
                      当前服务尚未配置 API 密钥。点击“编辑”补充密钥后，聊天请求才会生效。
                    </p>
                  </div>
                )}

                <div className="mt-6 rounded-xl border border-dashed border-gray-300 dark:border-gray-600 bg-white/60 dark:bg-gray-800/60 p-4">
                  <div className="flex gap-3">
                    <CircleDot className="mt-0.5 h-4 w-4 shrink-0 text-gray-500 dark:text-gray-400" />
                    <div className="text-xs leading-5 text-gray-500 dark:text-gray-400">
                      <p className="font-medium text-gray-700 dark:text-gray-200">协议说明</p>
                      <p className="mt-1">
                        OpenAI Compatible 对应 Chat Completions；Anthropic 对应 Messages API；OpenAI
                        Responses 会强制通过 Responses API 发起请求。
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex min-h-72 flex-col items-center justify-center text-center">
                <AlertCircle className="mb-3 h-8 w-8 text-gray-300 dark:text-gray-600" />
                <p className="text-sm text-gray-500 dark:text-gray-400">暂无可用配置</p>
              </div>
            )}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <label className="text-sm font-medium text-gray-700 dark:text-gray-200">{label}</label>
        {hint && <span className="text-xs text-gray-400 dark:text-gray-500">{hint}</span>}
      </div>
      {children}
    </div>
  );
}
