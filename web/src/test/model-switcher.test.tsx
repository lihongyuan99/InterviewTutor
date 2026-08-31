import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ModelSwitcher } from "../app/components/ModelSwitcher";

vi.mock("../lib/toast", () => ({
  notifyError: vi.fn(),
  notifySuccess: vi.fn(),
}));

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const initialSettings = {
  active_provider_id: "workbuddy",
  providers: [
    {
      id: "workbuddy",
      name: "workbuddy",
      active_model: "hy4-preview",
      api_key_configured: true,
      models: [
        { id: "hy3", name: "hy3" },
        { id: "hy4-preview", name: "hy4-preview" },
      ],
    },
    {
      id: "local",
      name: "本地模型",
      active_model: "qwen-local",
      api_key_configured: true,
      models: [{ id: "qwen-local", name: "Qwen Local" }],
    },
  ],
};

describe("ModelSwitcher", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "PUT") {
          return jsonResponse({
            ...initialSettings,
            providers: initialSettings.providers.map((provider) =>
              provider.id === "workbuddy"
                ? { ...provider, active_model: "hy3" }
                : provider,
            ),
          });
        }
        return jsonResponse(initialSettings);
      }),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("switches the active model from the model badge", async () => {
    const user = userEvent.setup();
    render(<ModelSwitcher />);

    const trigger = await screen.findByRole("button", {
      name: /当前模型：hy4-preview.*点击切换模型/,
    });
    expect(trigger).toHaveClass("h-[22px]", "text-xs", "font-normal", "leading-4");
    await user.click(trigger);
    await user.click(
      screen.getByRole("option", { name: "切换到 hy3（workbuddy）" }),
    );

    await waitFor(() => {
      const switchCall = vi
        .mocked(fetch)
        .mock.calls.find(([, init]) => init?.method === "PUT");
      expect(String(switchCall?.[0])).toMatch(/\/settings\/llm$/);
      const payload = JSON.parse(String(switchCall?.[1]?.body));
      expect(payload.active_provider_id).toBe("workbuddy");
      expect(
        payload.providers.find((provider: { id: string }) => provider.id === "workbuddy")
          .active_model,
      ).toBe("hy3");
    });
    expect(
      await screen.findByRole("button", {
        name: /当前模型：hy3.*点击切换模型/,
      }),
    ).toBeInTheDocument();
  });
});
