import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeSettingsPanel } from "../app/components/KnowledgeSettingsPanel";
import { MarkdownPreview } from "../app/components/MarkdownPreview";

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function knowledgeStatus(overrides: Record<string, unknown> = {}) {
  return {
    enabled: true,
    phase: "idle",
    progress: { completed: 0, total: 0 },
    current: {
      snapshot_id: "bundled",
      bundled: true,
      source_sha: "f7c2e45eacb18546dd879a589c12664ef82d2087",
      source_date: "2026-08-26T17:24:24+08:00",
      built_at: "2026-08-26T12:00:00Z",
      question_count: 592,
      dimension_count: 16,
      embedding_model: "Qwen3-Embedding-0.6B-4bit-DWQ",
      embedding_dimension: 1024,
    },
    latest_source_sha: "f7c2e45eacb18546dd879a589c12664ef82d2087",
    latest_source_date: "2026-08-26T17:24:24+08:00",
    update_available: false,
    last_checked_at: "2026-08-26T12:00:00Z",
    last_success_at: "2026-08-26T12:00:00Z",
    next_check_at: "2026-08-26T18:00:00Z",
    last_error: "",
    can_rollback: true,
    suppressed_sha: "",
    interval_seconds: 21600,
    source_repository: "ranxi2001/zero2Agent",
    source_ref: "main",
    source_path: "learn-agent-interview",
    ...overrides,
  };
}

describe("knowledge settings", () => {
  beforeEach(() => {
    vi.stubGlobal("confirm", vi.fn(() => true));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("loads the local status and starts an idempotent background sync", async () => {
    let syncing = false;
    const checking = knowledgeStatus({
      phase: "checking",
      progress: { completed: 0, total: 0 },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "POST") {
          syncing = true;
          return jsonResponse(checking);
        }
        return jsonResponse(syncing ? checking : knowledgeStatus());
      }),
    );

    const user = userEvent.setup();
    render(<KnowledgeSettingsPanel active />);

    expect(await screen.findByText("592")).toBeInTheDocument();
    expect(screen.getByText("16")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /ranxi2001\/zero2Agent/ })).toHaveAttribute(
      "href",
      expect.stringContaining("f7c2e45e"),
    );

    await user.click(screen.getByRole("button", { name: "立即检查并更新" }));
    expect(await screen.findAllByText("正在检查上游版本")).toHaveLength(2);
    const post = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === "POST");
    expect(String(post?.[0])).toContain("/knowledge/sync");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ force: false });
    expect(screen.getByRole("button", { name: "正在更新" })).toBeDisabled();
  });

  it("confirms and rolls back the previous successful version", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "POST") {
          return jsonResponse(
            knowledgeStatus({
              current: {
                ...knowledgeStatus().current,
                snapshot_id: "previous",
                source_sha: "a".repeat(40),
              },
              can_rollback: true,
              suppressed_sha: "f7c2e45eacb18546dd879a589c12664ef82d2087",
            }),
          );
        }
        return jsonResponse(knowledgeStatus());
      }),
    );

    const user = userEvent.setup();
    render(<KnowledgeSettingsPanel active />);
    await user.click(await screen.findByRole("button", { name: "回滚上一版本" }));

    await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
    const rollback = vi.mocked(fetch).mock.calls.find(
      ([input, init]) => String(input).includes("/knowledge/rollback") && init?.method === "POST",
    );
    expect(rollback).toBeTruthy();
  });
});

describe("markdown raw HTML boundary", () => {
  it("keeps only the controlled citation superscript", () => {
    const { container } = render(
      <MarkdownPreview
        enableRawHtml
        content={
          '<sup class="cite-sup">[1]</sup><script>alert(1)</script><img src="x" onerror="alert(2)">'
        }
      />,
    );

    expect(container.querySelector("sup.cite-sup")).toHaveTextContent("[1]");
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<script>");
  });
});
