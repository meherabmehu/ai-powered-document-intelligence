import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import App from "./App";

describe("document intelligence workspace", () => {
  it("shows upload, search, and review controls", () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    ));
    render(<App />);

    expect(screen.getByRole("heading", { name: /make every document easier to trust/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /upload files/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /search/i })).toBeVisible();
    expect(screen.getByRole("heading", { name: /review with confidence/i })).toBeVisible();
  });

  it("shows API failures instead of hiding them", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network unavailable")));
    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/network unavailable/i);
    });
  });

  it("submits a search and displays returned document rows", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{
        id: "doc-1",
        original_filename: "invoice.pdf",
        media_type: "application/pdf",
        size_bytes: 4096,
        status: "completed",
        progress: 100,
        created_at: "2025-01-01T00:00:00Z",
      }]), { status: 200 })));
    render(<App />);
    fireEvent.change(screen.getByRole("textbox", { name: /search documents/i }), { target: { value: "invoice" } });
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));

    await waitFor(() => {
      expect(screen.getByText("invoice.pdf")).toBeVisible();
    });
  });
});
