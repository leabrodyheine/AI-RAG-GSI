import { useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { ask } from "./api";
import type { AskResponse } from "./types";

// Matches orswater.answer.LEGAL_DISCLAIMER verbatim. The backend includes it in the
// answer text; the interface presents it once, consistently, in the visible legal note.
const LEGAL_DISCLAIMER = "This is general information, not legal advice.";

const EXAMPLE_QUESTIONS = [
  "Can I use a well for my home without a water right?",
  "What does ORS 537.545 allow?",
  "How does Oregon prioritize competing water rights?",
];

const BACKEND_LABELS: Record<string, string> = {
  anthropic: "Claude synthesis",
  deterministic: "Local statute excerpt",
  ollama: "Local AI synthesis",
};

function withoutDisclaimer(text: string): string {
  return text
    .split(LEGAL_DISCLAIMER)
    .join("")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function WaterMarkIcon() {
  return (
    <svg viewBox="0 0 48 48" aria-hidden="true">
      <path d="M24 5.5c-5.2 8.2-12.4 15.5-12.4 24.1A12.4 12.4 0 0 0 24 42a12.4 12.4 0 0 0 12.4-12.4C36.4 21 29.2 13.7 24 5.5Z" />
      <path d="M17.8 30.2c.8 3.7 3.1 5.8 6.7 6.2" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4 4" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

function ExternalLinkIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M14 5h5v5M19 5l-8 8" />
      <path d="M18 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
    </svg>
  );
}

function BookIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H11v16H6.5A2.5 2.5 0 0 0 4 21.5v-16Z" />
      <path d="M20 5.5A2.5 2.5 0 0 0 17.5 3H13v16h4.5a2.5 2.5 0 0 1 2.5 2.5v-16Z" />
    </svg>
  );
}

function App() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);

  async function submitQuestion(questionToAsk: string) {
    const trimmed = questionToAsk.trim();
    if (!trimmed || loading) return;

    setQuestion(trimmed);
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await ask(trimmed));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void submitQuestion(question);
  }

  function handleQuestionKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submitQuestion(question);
    }
  }

  const hasResponse = Boolean(loading || error || result);
  const backendLabel = result
    ? (BACKEND_LABELS[result.backend] ?? `${result.backend} answer`)
    : "";

  return (
    <div className="site-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label="Oregon Water Law home">
          <span className="brand-mark"><WaterMarkIcon /></span>
          <span className="brand-copy">
            <strong>Oregon Water Law</strong>
            <span>Statute research assistant</span>
          </span>
        </a>
        <div className="header-meta">
          <span className="status-dot" aria-hidden="true" />
          ORS Chapters 536–540
        </div>
      </header>

      <main className="app">
        <section className={`hero ${hasResponse ? "hero-compact" : ""}`}>
          <div className="hero-copy">
            <span className="eyebrow">Oregon Revised Statutes</span>
            <h1>Clear answers, grounded in Oregon water law.</h1>
            <p>
              Ask a plain-language question and review the exact statutory sources behind
              the answer.
            </p>
          </div>

          <div className="search-panel">
            <form className="question-form" onSubmit={handleSubmit}>
              <label htmlFor="question">What would you like to understand?</label>
              <div className="question-control">
                <span className="search-icon"><SearchIcon /></span>
                <textarea
                  id="question"
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  onKeyDown={handleQuestionKeyDown}
                  placeholder="Ask about water rights, wells, permits, or priority…"
                  rows={2}
                  disabled={loading}
                />
                <button type="submit" disabled={loading || !question.trim()}>
                  {loading ? (
                    <><span className="spinner" aria-hidden="true" />Researching</>
                  ) : (
                    <>Ask question<ArrowIcon /></>
                  )}
                </button>
              </div>
              <p className="form-hint">Press Enter to ask · Shift + Enter for a new line</p>
            </form>
          </div>

          {!hasResponse && (
            <div className="examples" aria-label="Example questions">
              <span>Try asking</span>
              <div className="example-list">
                {EXAMPLE_QUESTIONS.map((example) => (
                  <button key={example} type="button" onClick={() => void submitQuestion(example)}>
                    {example}<ArrowIcon />
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>

        <div className="response-region" aria-live="polite" aria-busy={loading}>
          {loading && (
            <section className="loading-card" aria-label="Researching your question">
              <div className="loading-heading">
                <span className="loading-mark"><BookIcon /></span>
                <div>
                  <strong>Reviewing Oregon statutes</strong>
                  <span>Finding the most relevant sections…</span>
                </div>
              </div>
              <div className="skeleton skeleton-wide" />
              <div className="skeleton" />
              <div className="skeleton skeleton-short" />
            </section>
          )}

          {error && (
            <section className="error-card" role="alert">
              <span className="error-symbol" aria-hidden="true">!</span>
              <div>
                <strong>We couldn’t complete that search.</strong>
                <p>{error}</p>
              </div>
              <button type="button" onClick={() => void submitQuestion(question)}>Try again</button>
            </section>
          )}

          {result && (
            <section className="result">
              <article className="answer-card">
                <div className="answer-header">
                  <div>
                    <span className="section-label">Research summary</span>
                    <h2>Answer</h2>
                  </div>
                  <span className={`backend-badge backend-${result.backend}`}>
                    <span className="badge-dot" aria-hidden="true" />
                    {backendLabel}
                  </span>
                </div>
                <div className="answer-text">{withoutDisclaimer(result.text)}</div>
                <div className="answer-meta">
                  <BookIcon />
                  Based on {result.retrieved_sections.length} relevant statute
                  {result.retrieved_sections.length === 1 ? "" : "s"}
                </div>
              </article>

              {result.citations.length > 0 && (
                <section className="citations" aria-labelledby="citations-title">
                  <div className="section-heading">
                    <div>
                      <span className="section-label">Primary authority</span>
                      <h2 id="citations-title">Cited sections</h2>
                    </div>
                    <span className="count-badge">{result.citations.length}</span>
                  </div>
                  <div className="citation-list">
                    {result.citations.map((citation, index) => (
                      <article className="citation-card" key={`${citation.section_number}-${index}`}>
                        <div className="citation-topline">
                          <span className="ors-number">ORS {citation.section_number}</span>
                          {citation.url && (
                            <a className="source-link" href={citation.url} target="_blank" rel="noreferrer">
                              View official source<ExternalLinkIcon />
                            </a>
                          )}
                        </div>
                        <h3>{citation.heading}</h3>
                        <blockquote>{citation.cited_text}</blockquote>
                      </article>
                    ))}
                  </div>
                </section>
              )}

              {result.retrieved_sections.length > 0 && (
                <details className="retrieved">
                  <summary>
                    <span><BookIcon />All reviewed sections</span>
                    <span className="summary-count">{result.retrieved_sections.length}</span>
                  </summary>
                  <ul>
                    {result.retrieved_sections.map((section) => (
                      <li key={section.section_number}>
                        <a href={section.url} target="_blank" rel="noreferrer">
                          <span className="retrieved-number">ORS {section.section_number}</span>
                          <span>{section.heading}</span>
                          <ExternalLinkIcon />
                        </a>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </section>
          )}
        </div>

        {!hasResponse && (
          <section className="trust-strip" aria-label="About this research tool">
            <div><span className="trust-number">01</span><p><strong>Ask naturally</strong><span>No legal terminology required.</span></p></div>
            <div><span className="trust-number">02</span><p><strong>Review the answer</strong><span>Built only from retrieved statutes.</span></p></div>
            <div><span className="trust-number">03</span><p><strong>Verify the source</strong><span>Open every citation on Oregon.gov.</span></p></div>
          </section>
        )}
      </main>

      <footer className="site-footer">
        <div className="legal-note">
          <span aria-hidden="true">i</span>
          <p><strong>{LEGAL_DISCLAIMER}</strong> Verify current law with the official Oregon Legislature website or a qualified attorney.</p>
        </div>
        <span className="prototype-label">Research prototype</span>
      </footer>
    </div>
  );
}

export default App;
