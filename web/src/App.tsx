import { useState } from "react";
import type { FormEvent } from "react";
import { ask } from "./api";
import type { AskResponse } from "./types";

// Matches orswater.answer.LEGAL_DISCLAIMER verbatim. The backend always includes it (the
// README requires a visible "not legal advice" note, and the CLI still shows it) -- this
// prototype's UI just doesn't display it. Stripping it here, rather than in the backend,
// keeps the underlying answer text unchanged for any other caller.
const LEGAL_DISCLAIMER = "This is general information, not legal advice.";

function withoutDisclaimer(text: string): string {
  return text
    .split(LEGAL_DISCLAIMER)
    .join("")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function App() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) return;

    setLoading(true);
    setError(null);
    try {
      setResult(await ask(trimmed));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="app">
      <h1>Oregon Water Law Q&amp;A</h1>

      <form className="question-form" onSubmit={handleSubmit}>
        <input
          type="text"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="e.g. Can I dig a well on my property?"
          aria-label="Question"
        />
        <button type="submit" disabled={loading || !question.trim()}>
          {loading ? "Asking…" : "Ask"}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {result && (
        <section className="result">
          <span className={`backend-badge backend-${result.backend}`}>backend: {result.backend}</span>

          <p className="answer-text">{withoutDisclaimer(result.text)}</p>

          {result.citations.length > 0 && (
            <div className="citations">
              <h2>Cited sections</h2>
              <ul>
                {result.citations.map((citation, index) => (
                  <li key={`${citation.section_number}-${index}`}>
                    {citation.url ? (
                      <a href={citation.url} target="_blank" rel="noreferrer">
                        ORS {citation.section_number} — {citation.heading}
                      </a>
                    ) : (
                      <span>
                        ORS {citation.section_number} — {citation.heading}
                      </span>
                    )}
                    <blockquote>{citation.cited_text}</blockquote>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {result.retrieved_sections.length > 0 && (
            <div className="retrieved">
              <h2>Retrieved sections</h2>
              <ul>
                {result.retrieved_sections.map((section) => (
                  <li key={section.section_number}>
                    <a href={section.url} target="_blank" rel="noreferrer">
                      ORS {section.section_number} — {section.heading}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}
    </main>
  );
}

export default App;
