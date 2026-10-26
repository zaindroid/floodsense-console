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
  /** SHA-256 hex of the stored text, or of the quote when storage is pointer. */
  content_sha256: string;
  storage: Storage;
  locator?: Locator;
  /** One or two sentences. */
  quote?: string;
  query_id?: string;
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
