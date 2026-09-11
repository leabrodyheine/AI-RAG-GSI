// Mirrors the JSON shapes returned by POST /api/ask (src/orswater/web.py's AskResponse).

export interface Citation {
  section_number: string;
  heading: string;
  cited_text: string;
  url: string | null;
}

export interface RetrievedSection {
  section_number: string;
  heading: string;
  url: string;
}

export interface AskResponse {
  backend: string;
  text: string;
  citations: Citation[];
  retrieved_sections: RetrievedSection[];
}
