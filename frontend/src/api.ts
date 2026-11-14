export type DocumentStatus = "queued" | "processing" | "completed" | "failed";

export interface DocumentSummary {
  id: string;
  original_filename: string;
  media_type: string;
  size_bytes: number;
  status: DocumentStatus;
  progress: number;
  created_at: string;
}

export interface ValidationIssue {
  code: string;
  severity: string;
  field: string;
  message: string;
}

export interface InvoiceData {
  invoice_number: string | null;
  invoice_date: string | null;
  supplier_name: string | null;
  customer_name: string | null;
  subtotal: string | number | null;
  tax: string | number | null;
  total: string | number | null;
  currency: string | null;
  line_items: Array<Record<string, unknown>>;
  uncertain_fields: string[];
  extraction_method?: string;
}

export interface DocumentDetail extends DocumentSummary {
  extracted_text: string | null;
  extracted_data: InvoiceData | null;
  validation_issues: ValidationIssue[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const body = (await response.json()) as { detail?: string };
      message = body.detail ?? message;
    } catch {
      // Keep the HTTP status message when the response is not JSON.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export const documentApi = {
  list: () => request<DocumentSummary[]>("/api/documents"),
  detail: (id: string) => request<DocumentDetail>(`/api/documents/${id}`),
  search: (query: string, mode: "keyword" | "semantic") =>
    request<DocumentSummary[]>(
      `/api/search?q=${encodeURIComponent(query)}&mode=${mode}`,
    ),
  upload: (files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return request<DocumentSummary[]>("/api/documents/upload", {
      method: "POST",
      body: form,
    });
  },
  correct: (id: string, extractedData: Partial<InvoiceData>) =>
    request<DocumentDetail>(`/api/documents/${id}/correction`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ extracted_data: extractedData }),
    }),
  retry: (id: string) =>
    request<DocumentSummary>(`/api/documents/${id}/retry`, { method: "POST" }),
};
