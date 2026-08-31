import { Check, Loader2, Settings2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch, apiGet } from "../../lib/api";
import {
  EVENT_LLM_SETTINGS_UPDATED,
  EVENT_OPEN_SETTINGS,
  emitAppEvent,
} from "../../lib/events";
import { notifyError, notifySuccess } from "../../lib/toast";

interface ModelEntry {
  id: string;
  name: string;
}

interface ProviderSummary {
  id: string;
  name: string;
  models?: ModelEntry[];
  active_model: string;
  api_key_configured?: boolean;
  [key: string]: unknown;
}

interface PublicLLMSettings {
  active_provider_id: string;
  providers: ProviderSummary[];
  [key: string]: unknown;
}

type ModelSwitcherTone = "indigo" | "emerald";

const TONE_STYLES: Record<
  ModelSwitcherTone,
  {
    trigger: string;
    dot: string;
    separator: string;
    provider: string;
    accent: string;
    selected: string;
    manage: string;
  }
> = {
  indigo: {
    trigger:
      "border-indigo-200/70 bg-indigo-50/80 text-indigo-600 hover:border-indigo-300 hover:bg-indigo-100/80 focus-visible:ring-indigo-400/50 dark:border-indigo-700/50 dark:bg-indigo-900/30 dark:text-indigo-300 dark:hover:bg-indigo-900/50",
    dot: "bg-gradient-to-br from-indigo-500 to-violet-500 shadow-[0_0_6px_rgba(139,92,246,0.6)]",
    separator: "text-indigo-400/80 dark:text-indigo-400/60",
    provider: "text-indigo-500/80 dark:text-indigo-300/80",
    accent: "text-indigo-500",
    selected:
      "bg-indigo-50 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-200",
    manage:
      "hover:text-indigo-600 dark:hover:text-indigo-300",
  },
  emerald: {
    trigger:
      "border-emerald-200/80 bg-emerald-50/80 text-emerald-700 hover:border-emerald-300 hover:bg-emerald-100/80 focus-visible:ring-emerald-400/50 dark:border-emerald-700/50 dark:bg-emerald-900/30 dark:text-emerald-300 dark:hover:bg-emerald-900/50",
    dot: "bg-gradient-to-br from-emerald-500 to-teal-500 shadow-[0_0_6px_rgba(16,185,129,0.55)]",
    separator: "text-emerald-400/80 dark:text-emerald-400/60",
    provider: "text-emerald-600/80 dark:text-emerald-300/80",
    accent: "text-emerald-500",
    selected:
      "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-200",
    manage:
      "hover:text-emerald-600 dark:hover:text-emerald-300",
  },
};

function readSettings(payload: unknown): PublicLLMSettings | null {
  if (!payload || typeof payload !== "object") return null;
  const value = payload as Partial<PublicLLMSettings>;
  if (!Array.isArray(value.providers) || typeof value.active_provider_id !== "string") {
    return null;
  }
  return value as PublicLLMSettings;
}

function providerModels(provider: ProviderSummary): ModelEntry[] {
  if (Array.isArray(provider.models) && provider.models.length > 0) {
    return provider.models;
  }
  return provider.active_model
    ? [{ id: provider.active_model, name: provider.active_model }]
    : [];
}

export function ModelSwitcher({
  disabled = false,
  tone = "indigo",
}: {
  disabled?: boolean;
  tone?: ModelSwitcherTone;
}) {
  const [settings, setSettings] = useState<PublicLLMSettings | null>(null);
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const toneStyles = TONE_STYLES[tone];

  useEffect(() => {
    let cancelled = false;
    const applySettings = (payload: unknown) => {
      const next = readSettings(payload);
      if (!cancelled && next) setSettings(next);
    };
    const loadSettings = async () => {
      try {
        applySettings(await apiGet<PublicLLMSettings>("/settings/llm"));
      } catch {
        if (!cancelled) setSettings(null);
      }
    };
    const handleSettingsUpdated = (event: Event) => {
      applySettings((event as CustomEvent).detail);
    };

    void loadSettings();
    window.addEventListener(EVENT_LLM_SETTINGS_UPDATED, handleSettingsUpdated);
    return () => {
      cancelled = true;
      window.removeEventListener(EVENT_LLM_SETTINGS_UPDATED, handleSettingsUpdated);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  const activeProvider = useMemo(
    () =>
      settings?.providers.find(
        (provider) => provider.id === settings.active_provider_id,
      ) || settings?.providers[0] || null,
    [settings],
  );
  const activeModel = activeProvider
    ? providerModels(activeProvider).find(
        (model) => model.id === activeProvider.active_model,
      ) || providerModels(activeProvider)[0]
    : null;

  if (!settings || !activeProvider || !activeModel) return null;

  const selectModel = async (provider: ProviderSummary, model: ModelEntry) => {
    if (disabled) return;
    const selectionKey = `${provider.id}\0${model.id}`;
    if (
      provider.id === settings.active_provider_id &&
      model.id === activeProvider.active_model
    ) {
      setOpen(false);
      return;
    }

    setSwitching(selectionKey);
    try {
      const nextSettings: PublicLLMSettings = {
        ...settings,
        active_provider_id: provider.id,
        providers: settings.providers.map((item) =>
          item.id === provider.id
            ? { ...item, active_model: model.id }
            : item,
        ),
      };
      const response = await apiFetch("/settings/llm", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextSettings),
      });
      const saved = readSettings(await response.json());
      if (!saved) throw new Error("模型配置响应无效");
      setSettings(saved);
      setOpen(false);
      emitAppEvent(EVENT_LLM_SETTINGS_UPDATED, saved);
      notifySuccess(`已切换到 ${model.name || model.id}，下一次回复生效`);
    } catch (error) {
      notifyError(error instanceof Error ? error.message : "切换模型失败");
    } finally {
      setSwitching("");
    }
  };

  return (
    <div ref={rootRef} className="relative inline-flex max-w-full">
      <button
        type="button"
        onClick={() => setOpen((visible) => !visible)}
        disabled={disabled}
        className={`inline-flex h-[22px] max-w-full cursor-pointer items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-normal leading-4 transition-colors focus-visible:outline-none focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-60 ${toneStyles.trigger}`}
        title={`${activeModel.name || activeModel.id} · ${activeProvider.name}`}
        aria-label={`当前模型：${activeModel.name || activeModel.id}，服务商：${activeProvider.name}。点击切换模型`}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${toneStyles.dot}`}
          aria-hidden="true"
        />
        <span className="max-w-44 truncate font-medium">
          {activeModel.name || activeModel.id}
        </span>
        <span className={toneStyles.separator}>·</span>
        <span className={`max-w-32 truncate ${toneStyles.provider}`}>
          {activeProvider.name}
        </span>
      </button>

      {open && (
        <div className="absolute bottom-full left-1/2 z-50 mb-2 w-[min(20rem,calc(100vw-2rem))] -translate-x-1/2 overflow-hidden rounded-2xl border border-gray-200 bg-white p-2 text-left shadow-xl shadow-gray-900/10 dark:border-gray-700 dark:bg-gray-900 dark:shadow-black/30">
          <div className="flex items-center justify-between gap-3 px-2.5 pb-2 pt-1.5">
            <div>
              <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">切换模型</p>
              <p className="mt-0.5 text-[11px] text-gray-400">下一条回复开始生效</p>
            </div>
            {switching && <Loader2 className={`h-4 w-4 animate-spin ${toneStyles.accent}`} />}
          </div>

          <div role="listbox" aria-label="可用模型" className="max-h-72 overflow-y-auto">
            {settings.providers.map((provider) => {
              const models = providerModels(provider);
              const available = provider.api_key_configured !== false;
              return (
                <div key={provider.id} className="mt-1 first:mt-0">
                  <div className="flex items-center justify-between gap-2 px-2.5 py-1.5 text-[11px] font-medium text-gray-400">
                    <span className="truncate">{provider.name}</span>
                    {!available && <span className="shrink-0 text-amber-500">未配置密钥</span>}
                  </div>
                  {models.map((model) => {
                    const selected =
                      provider.id === settings.active_provider_id &&
                      model.id === provider.active_model;
                    const selectionKey = `${provider.id}\0${model.id}`;
                    return (
                      <button
                        key={model.id}
                        type="button"
                        role="option"
                        aria-selected={selected}
                        aria-label={`切换到 ${model.name || model.id}（${provider.name}）`}
                        disabled={disabled || !available || Boolean(switching)}
                        onClick={() => void selectModel(provider, model)}
                        className={`flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                          selected
                            ? toneStyles.selected
                            : "text-gray-700 hover:bg-gray-50 dark:text-gray-200 dark:hover:bg-gray-800"
                        }`}
                      >
                        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-white text-[11px] font-semibold uppercase text-gray-500 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:ring-gray-700">
                          {(model.name || model.id).slice(0, 2)}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">
                            {model.name || model.id}
                          </span>
                          {model.name !== model.id && (
                            <span className="mt-0.5 block truncate font-mono text-[10px] text-gray-400">
                              {model.id}
                            </span>
                          )}
                        </span>
                        {switching === selectionKey ? (
                          <Loader2 className={`h-4 w-4 shrink-0 animate-spin ${toneStyles.accent}`} />
                        ) : selected ? (
                          <Check className={`h-4 w-4 shrink-0 ${toneStyles.accent}`} />
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </div>

          <button
            type="button"
            onClick={() => {
              setOpen(false);
              emitAppEvent(EVENT_OPEN_SETTINGS, { section: "models" });
            }}
            className={`mt-2 flex w-full items-center justify-center gap-1.5 border-t border-gray-100 px-3 pt-2.5 text-xs font-medium text-gray-500 transition-colors dark:border-gray-800 dark:text-gray-400 ${toneStyles.manage}`}
          >
            <Settings2 className="h-3.5 w-3.5" />
            管理模型服务
          </button>
        </div>
      )}
    </div>
  );
}
