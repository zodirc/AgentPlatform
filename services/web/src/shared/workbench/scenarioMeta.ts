import type { ScenarioId } from "./types";

export type ScenarioMeta = {
  id: ScenarioId;
  title: string;
  navLabel: string;
  chatEyebrow: string;
};

export const SCENARIO_META: Record<ScenarioId, ScenarioMeta> = {
  writing: {
    id: "writing",
    title: "写作工作台",
    navLabel: "写作",
    chatEyebrow: "写作模式",
  },
  agent: {
    id: "agent",
    title: "Agent 工作台",
    navLabel: "Agent",
    chatEyebrow: "Agent 模式",
  },
  interview: {
    id: "interview",
    title: "访谈纪要工作台",
    navLabel: "访谈",
    chatEyebrow: "访谈模式",
  },
};

export function scenarioMeta(id: ScenarioId): ScenarioMeta {
  return SCENARIO_META[id];
}
