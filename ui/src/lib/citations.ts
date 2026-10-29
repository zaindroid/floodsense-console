import type { Answer, Citation } from "../types/contract";

export interface NumberedCitation {
  /** 1-based, in the answer's own citation order. The Evidence page and drawer list them in that order. */
  n: number;
  citation: Citation;
}

export function numberedCitations(answer: Answer): NumberedCitation[] {
  return answer.citations.map((citation, index) => ({ n: index + 1, citation }));
}

export function citationsForClaim(answer: Answer, claimId: string): NumberedCitation[] {
  return numberedCitations(answer).filter((item) => item.citation.claim_id === claimId);
}

/** Ids that do not match a citation on the answer are dropped, not numbered. */
export function citationsById(answer: Answer, ids: readonly string[]): NumberedCitation[] {
  const wanted = new Set(ids);
  return numberedCitations(answer).filter((item) => wanted.has(item.citation.citation_id));
}

export function citationMarks(items: NumberedCitation[]): string {
  return items.map((item) => `[${item.n}]`).join("");
}
