import type { ScenarioId } from "./types";

const SCENARIO_IDS: ScenarioId[] = ["writing", "agent", "interview"];

export function isScenarioId(value: string | undefined): value is ScenarioId {
  return SCENARIO_IDS.includes(value as ScenarioId);
}

export function scenarioFromPathname(pathname: string): ScenarioId | null {
  const segment = pathname.replace(/^\/+|\/+$/g, "").split("/")[0];
  return isScenarioId(segment) ? segment : null;
}
