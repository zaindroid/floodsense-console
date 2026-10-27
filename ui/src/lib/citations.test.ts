import { describe, expect, it } from "vitest";
import { loadFixtures } from "../fixtures/load";
import { citationMarks, citationsById, citationsForClaim, numberedCitations } from "./citations";

const { answer } = loadFixtures();

describe("citations", () => {
  it("numbers citations in the answer's order", () => {
    const numbered = numberedCitations(answer);
    expect(numbered.map((item) => item.n)).toEqual(answer.citations.map((_, index) => index + 1));
    expect(numbered[0].citation.citation_id).toBe(answer.citations[0].citation_id);
  });

  it("keeps the global number when filtering by claim", () => {
    const claimId = answer.citations[answer.citations.length - 1].claim_id;
    const items = citationsForClaim(answer, claimId);
    expect(items.length).toBeGreaterThan(0);
    expect(items.every((item) => item.citation.claim_id === claimId)).toBe(true);
    expect(items.at(-1)?.n).toBe(answer.citations.length);
  });

  it("drops ids that are not on the answer", () => {
    const first = answer.citations[0].citation_id;
    expect(citationsById(answer, [first, "cit_missing"]).map((item) => item.n)).toEqual([1]);
  });

  it("formats marks", () => {
    expect(citationMarks(citationsById(answer, answer.citations.slice(0, 2).map((item) => item.citation_id)))).toBe(
      "[1][2]",
    );
    expect(citationMarks([])).toBe("");
  });
});
