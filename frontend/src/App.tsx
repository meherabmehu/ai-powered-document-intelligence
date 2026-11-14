import { useCallback, useEffect, useState } from "react";

import {
  documentApi,
  type DocumentDetail,
  type DocumentSummary,
  type InvoiceData,
} from "./api";

const editableFields = [
  ["invoice_number", "Invoice number"],
  ["invoice_date", "Invoice date"],
  ["supplier_name", "Supplier"],
  ["customer_name", "Customer"],
  ["subtotal", "Subtotal"],
  ["tax", "Tax"],
  ["total", "Total"],
  ["currency", "Currency"],
] as const;

function formatSize(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function displayValue(value: unknown): string {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

function App() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selected, setSelected] = useState<DocumentDetail | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchMode, setSearchMode] = useState<"keyword" | "semantic">("keyword");
  const [isSearching, setIsSearching] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadDocuments = useCallback(async () => {
    try {
      setDocuments(await documentApi.list());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load documents.");
    }
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    try {
      setSelected(await documentApi.detail(id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load this document.");
    }
  }, []);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  useEffect(() => {
    if (!documents.some((document) => ["queued", "processing"].includes(document.status))) {
      return;
    }
    const timer = window.setInterval(() => void loadDocuments(), 2500);
    return () => window.clearInterval(timer);
  }, [documents, loadDocuments]);

  useEffect(() => {
    if (selected && ["queued", "processing"].includes(selected.status)) {
      const timer = window.setInterval(() => void loadDetail(selected.id), 2500);
      return () => window.clearInterval(timer);
    }
  }, [loadDetail, selected]);

  async function handleUpload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem("documents");
    if (!(input instanceof HTMLInputElement) || !input.files?.length) {
      setError("Choose one or more files to upload.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const uploaded = await documentApi.upload(Array.from(input.files));
      setNotice(`${uploaded.length} document${uploaded.length === 1 ? "" : "s"} queued for processing.`);
      input.value = "";
      await loadDocuments();
      if (uploaded[0]) await loadDetail(uploaded[0].id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload failed.");
      await loadDocuments();
    } finally {
      setBusy(false);
    }
  }

  async function handleSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!searchQuery.trim()) {
      setIsSearching(false);
      await loadDocuments();
      return;
    }
    setBusy(true);
    setError("");
    try {
      setDocuments(await documentApi.search(searchQuery.trim(), searchMode));
      setIsSearching(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Search failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleCorrection(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected?.extracted_data) return;
    const form = new FormData(event.currentTarget);
    const corrected: Partial<InvoiceData> = {};
    for (const [field] of editableFields) {
      const value = String(form.get(field) ?? "").trim();
      corrected[field] = value || null;
    }
    setBusy(true);
    setError("");
    try {
      const updated = await documentApi.correct(selected.id, corrected);
      setSelected(updated);
      setNotice("Corrections saved and validation updated.");
      await loadDocuments();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save corrections.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRetry(document: DocumentSummary) {
    setBusy(true);
    setError("");
    try {
      const updated = await documentApi.retry(document.id);
      setNotice(`${updated.original_filename} was queued for another attempt.`);
      await loadDocuments();
      await loadDetail(document.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not retry this document.");
    } finally {
      setBusy(false);
    }
  }

  const extracted = selected?.extracted_data;

  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Document Intelligence home">
          <span className="brand-mark" aria-hidden="true">DI</span>
          <span>Document Intelligence</span>
        </a>
        <span className="environment">PRIVATE REVIEW WORKSPACE</span>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">AI-POWERED DOCUMENT REVIEW</p>
          <h1>Make every document easier to trust.</h1>
          <p className="intro">
            Extract invoice details, check totals, and find the records you need.
            Review every result before relying on it.
          </p>
        </div>
        <form className="upload-card" onSubmit={handleUpload}>
          <label htmlFor="documents">Add invoices or spreadsheets</label>
          <p>PDF, JPG, PNG, TIFF, XLSX, XLS, or CSV · up to 25 MB per file</p>
          <div className="upload-controls">
            <input
              id="documents"
              name="documents"
              type="file"
              multiple
              accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff,.xlsx,.xls,.csv"
              aria-label="Choose documents"
            />
            <button type="submit" disabled={busy}> {busy ? "Working…" : "Upload files"} </button>
          </div>
        </form>
      </section>

      {(error || notice) && (
        <div className={`feedback ${error ? "feedback-error" : ""}`} role={error ? "alert" : "status"}>
          {error || notice}
          <button type="button" className="dismiss" onClick={() => { setError(""); setNotice(""); }} aria-label="Dismiss message">
            ×
          </button>
        </div>
      )}

      <section className="workspace">
        <div className="document-column">
          <div className="section-heading">
            <div>
              <p className="eyebrow">YOUR WORKSPACE</p>
              <h2>{isSearching ? "Search results" : "Documents"}</h2>
            </div>
            <span className="result-count">{documents.length} shown</span>
          </div>

          <form className="search-bar" onSubmit={handleSearch}>
            <label className="sr-only" htmlFor="search-query">Search documents</label>
            <input
              id="search-query"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search invoice, supplier, or document text"
            />
            <label className="sr-only" htmlFor="search-mode">Search type</label>
            <select id="search-mode" value={searchMode} onChange={(event) => setSearchMode(event.target.value as "keyword" | "semantic")}>
              <option value="keyword">Keyword</option>
              <option value="semantic">Semantic</option>
            </select>
            <button type="submit" disabled={busy}>Search</button>
            {isSearching && (
              <button
                className="text-button"
                type="button"
                onClick={() => {
                  setSearchQuery("");
                  setIsSearching(false);
                  void loadDocuments();
                }}
              >
                Clear
              </button>
            )}
          </form>

          {documents.length === 0 ? (
            <div className="empty-state">
              <span className="empty-icon" aria-hidden="true">＋</span>
              <h3>{isSearching ? "No matching documents" : "Your document list is empty"}</h3>
              <p>{isSearching ? "Try another search phrase." : "Upload an invoice or spreadsheet to begin."}</p>
            </div>
          ) : (
            <div className="document-list">
              {documents.map((document) => (
                <article className={`document-card ${selected?.id === document.id ? "selected" : ""}`} key={document.id}>
                  <button className="document-main" type="button" onClick={() => void loadDetail(document.id)}>
                    <span className="file-icon" aria-hidden="true">{document.media_type === "application/pdf" ? "PDF" : "DOC"}</span>
                    <span className="document-copy">
                      <strong>{document.original_filename}</strong>
                      <span>{formatSize(document.size_bytes)} · {new Date(document.created_at).toLocaleString()}</span>
                    </span>
                    <span className={`status status-${document.status}`}>{document.status}</span>
                  </button>
                  {(document.status === "processing" || document.status === "queued") && (
                    <div className="progress-track" aria-label={`${document.progress}% complete`}>
                      <span style={{ width: `${document.progress}%` }} />
                    </div>
                  )}
                  {document.status === "failed" && (
                    <button className="retry-button" type="button" disabled={busy} onClick={() => void handleRetry(document)}>
                      Retry processing
                    </button>
                  )}
                </article>
              ))}
            </div>
          )}
        </div>

        <aside className="review-panel" aria-label="Document review">
          {!selected ? (
            <div className="review-empty">
              <span className="review-mark" aria-hidden="true">✓</span>
              <h2>Review with confidence</h2>
              <p>Select a document to inspect extracted fields, validation checks, and source text.</p>
            </div>
          ) : (
            <>
              <div className="section-heading review-heading">
                <div>
                  <p className="eyebrow">DOCUMENT REVIEW</p>
                  <h2>{selected.original_filename}</h2>
                </div>
                <button className="close-button" type="button" onClick={() => setSelected(null)} aria-label="Close review">×</button>
              </div>
              {selected.status !== "completed" ? (
                <div className="processing-state">
                  <span className={`status status-${selected.status}`}>{selected.status}</span>
                  <p>{selected.status === "failed" ? "Processing failed. Retry from the document list." : "Extracting and validating document fields…"}</p>
                </div>
              ) : extracted ? (
                <>
                  <div className="validation-heading">
                    <h3>Validation</h3>
                    <span className={selected.validation_issues.length ? "issue-count" : "clean-count"}>
                      {selected.validation_issues.length ? `${selected.validation_issues.length} to review` : "No issues found"}
                    </span>
                  </div>
                  {selected.validation_issues.length > 0 && (
                    <ul className="issue-list">
                      {selected.validation_issues.map((issue, index) => (
                        <li key={`${issue.code}-${index}`}>
                          <strong>{issue.field.replaceAll("_", " ")}</strong>
                          <span>{issue.message}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  <form className="invoice-form" key={selected.id} onSubmit={handleCorrection}>
                    <h3>Extracted invoice fields</h3>
                    <div className="field-grid">
                      {editableFields.map(([field, label]) => (
                        <label key={field} htmlFor={`field-${field}`}>
                          {label}
                          <input
                            id={`field-${field}`}
                            name={field}
                            defaultValue={String(extracted[field] ?? "")}
                            autoComplete="off"
                          />
                        </label>
                      ))}
                    </div>
                    <button type="submit" disabled={busy}>Save corrections</button>
                  </form>
                  {extracted.line_items.length > 0 && (
                    <section className="line-items" aria-label="Extracted line items">
                      <h3>Line items</h3>
                      <div className="line-item-list">
                        {extracted.line_items.map((item, index) => (
                          <div className="line-item" key={index}>
                            <strong>{displayValue(item.description)}</strong>
                            <span>Qty {displayValue(item.quantity)}</span>
                            <span>Unit {displayValue(item.unit_price)}</span>
                            <span>Amount {displayValue(item.amount)}</span>
                          </div>
                        ))}
                      </div>
                    </section>
                  )}
                  <details className="source-text">
                    <summary>View extracted source text</summary>
                    <pre>{selected.extracted_text || "No readable text was extracted."}</pre>
                  </details>
                </>
              ) : (
                <p>No invoice fields were returned for this document.</p>
              )}
            </>
          )}
        </aside>
      </section>
      <footer>Private by design. AI-generated values are suggestions—verify them against the source.</footer>
    </main>
  );
}

export default App;
