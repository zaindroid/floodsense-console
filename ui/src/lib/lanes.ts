/**
 * Display labels for judge model ids on the contract.
 *
 * Routing names and `deterministic` are shown as stored. A concrete
 * Nightshift id is "answered by" that model. Which model answers a routing
 * name today is the table at the top of docs/architecture/c4.md. Super VL
 * answers both lanes, so this label does not assign it to fast or deep.
 * Lightning is not shown as meterless/fast.
 */
const ANSWERED_BY: Record<string, string> = {
  "nvidia/nemotron-3.5-super-vl-120b-a12b": "answered by Nemotron 3.5 Super VL 120B A12B",
  "nvidia/nemotron-3.5-lightning-30b-a3b": "answered by Nemotron 3.5 Lightning 30B A3B",
};

export function laneLabel(modelId: string): string {
  return ANSWERED_BY[modelId] ?? modelId;
}
