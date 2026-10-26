/**
 * Hand-checked TypeScript mirror of contracts/schemas/floodsense.schema.json.
 *
 * Wire format is snake_case, the same JSON the API will return. The mock UI
 * on spike/mock-ui uses camelCase and is not this contract. Do not edit that
 * branch from here.
 */

export type CitationLayer = "a" | "b" | "c";
export type Storage = "full_text" | "pointer";
export type Grounding = "supported" | "partial" | "unsupported";
export type ServedFrom = "live" | "cache" | "replay";
export type ApprovalStatus = "pending" | "approved" | "edited" | "rejected";
export type ModelId =
  | "meterless/fast"
  | "meterless/deep"
  | "nvidia/nemotron-3.5-super-vl-120b-a12b"
  | "nvidia/nemotron-3.5-lightning-30b-a3b"
  | "deterministic";

export interface Locator {
  section?: string;
  /**
   * Optional on layers a and b. Required on layer c and never null there.
   * A section-structured source still sets a page-like id (1 for the whole
   * document, or one id per section). Section does not replace page.
   */
  page?: number;
  paragraph?: number;
  /** Line range inside the paragraph, for example 3-5. */
  lines?: string;
}

export interface Citation {
  citation_id: string;
  claim_id: string;
  layer: CitationLayer;
  source_url: string;
  title: string;
  publisher: string;
  /** ISO 8601 date-time. */
  accessed_at: string;
  licence: string;
  attribution: string;
  /** When quote is present, SHA-256 hex of that quote as UTF-8 (what the Judge compares). A layer c chunk row keeps a separate hash of the full passage; that hash is not this field. */
  content_sha256: string;
  storage: Storage;
  locator?: Locator;
  /** One or two sentences. Required when layer is c. */
  quote?: string;
  /** Zetaris query id. Required when layer is c. */
  query_id?: string;
  /** pgvector chunk id. Optional on layer c. Layers a and b omit it. */
  chunk_id?: string;
}

export interface Evidence {
  query_id: string;
  view: string;
  sql: string;
  /** At most 20 rows. Column names depend on the view. */
  rows_sample: Record<string, unknown>[];
  /** Full result size. May be larger than rows_sample. */
  row_count: number;
  /** ISO 8601 date-time. */
  executed_at_utc: string;
}

export interface Claim {
  claim_id: string;
  text: string;
}

export interface JudgeClaim {
  claim_id: string;
  grounding: Grounding;
  citation_faithful: boolean;
  numbers_match: boolean;
  /** 0 to 1. */
  score: number;
  rationale: string;
  model_id: ModelId;
}

export interface Judge {
  claims: JudgeClaim[];
  /** 0 to 1. */
  overall_score: number;
}

export interface PlaybookAction {
  action_id: string;
  run_id: string;
  title: string;
  detail: string;
  citation_ids: string[];
}

export interface Approval {
  approval_id: string;
  run_id: string;
  action_id: string;
  status: ApprovalStatus;
  note?: string;
  /** Set when the Judge has scored the run. */
  judge?: Judge;
}

export interface Answer {
  run_id: string;
  question: string;
  claims: Claim[];
  citations: Citation[];
  evidence: Evidence[];
  served_from: ServedFrom;
  /**
   * Timestamp when served_from is cache or replay.
   * Null or omitted when served_from is live.
   */
  cached_at?: string | null;
  playbook_actions?: PlaybookAction[];
  judge?: Judge;
}
