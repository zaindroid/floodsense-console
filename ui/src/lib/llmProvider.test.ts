import { describe, expect, it } from "vitest";
import { effectiveProvider, parseProviders, showProviderSelect } from "./llmProvider";

describe("LLM provider select", () => {
  it("is hidden when the gate is off (one provider or none listed)", () => {
    expect(showProviderSelect(parseProviders({ llm_providers: ["nightshift"] }))).toBe(false);
    expect(showProviderSelect(parseProviders({}))).toBe(false);
    expect(showProviderSelect(parseProviders(null))).toBe(false);
  });

  it("shows when /config lists Anthropic too", () => {
    const providers = parseProviders({ llm_providers: ["nightshift", "anthropic"] });
    expect(providers).toEqual(["nightshift", "anthropic"]);
    expect(showProviderSelect(providers)).toBe(true);
  });

  it("ignores unknown providers and always keeps Nightshift", () => {
    expect(parseProviders({ llm_providers: ["openai"] })).toEqual(["nightshift"]);
  });

  it("falls back to Nightshift when the stored choice is no longer offered", () => {
    expect(effectiveProvider("anthropic", ["nightshift"])).toBe("nightshift");
    expect(effectiveProvider("anthropic", ["nightshift", "anthropic"])).toBe("anthropic");
    expect(effectiveProvider(null, ["nightshift", "anthropic"])).toBe("nightshift");
  });
});
