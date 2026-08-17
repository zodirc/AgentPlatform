export type ModelPanelMode = "view" | "edit" | "create";

/** Auto-select a profile after list load/delete. Never steal an in-progress create. */
export function nextModelPanelAfterListChange(args: {
  isLoading: boolean;
  panelMode: ModelPanelMode;
  selectedId: string | null;
  providerIds: string[];
  activeId: string | null;
}): { selectedId: string; panelMode: "view" } | null {
  if (args.isLoading || args.providerIds.length === 0) return null;
  if (args.panelMode === "create") return null;
  if (args.selectedId && args.providerIds.includes(args.selectedId)) return null;
  const id =
    args.activeId && args.providerIds.includes(args.activeId)
      ? args.activeId
      : args.providerIds[0];
  return { selectedId: id, panelMode: "view" };
}
