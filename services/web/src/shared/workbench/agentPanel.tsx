import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useWorkbenchSession } from "./workbenchSession";

type AgentPanelContextValue = {
  /**
   * Right-side tool timeline drawer (secondary sheet).
   * Chat stays in the main column; default closed so it does not steal space.
   */
  open: boolean;
  setOpen: (open: boolean) => void;
  /** Show the tools drawer without replacing the session. */
  openPanel: () => void;
  /** Fold the tools drawer (session kept). */
  closePanel: () => void;
  /** Toggle tools drawer. */
  togglePanel: () => void;
  /** Start a fresh session (Cursor "new agent"); chat stays main. */
  createAgent: () => Promise<void>;
};

const AgentPanelContext = createContext<AgentPanelContextValue | null>(null);

export function AgentPanelProvider({ children }: { children: ReactNode }) {
  const { startNewSession } = useWorkbenchSession();
  const [open, setOpen] = useState(false);

  const openPanel = useCallback(() => setOpen(true), []);
  const closePanel = useCallback(() => setOpen(false), []);
  const togglePanel = useCallback(() => setOpen((v) => !v), []);

  const createAgent = useCallback(async () => {
    await startNewSession();
  }, [startNewSession]);

  const value = useMemo(
    () => ({
      open,
      setOpen,
      openPanel,
      closePanel,
      togglePanel,
      createAgent,
    }),
    [open, openPanel, closePanel, togglePanel, createAgent],
  );

  return (
    <AgentPanelContext.Provider value={value}>
      {children}
    </AgentPanelContext.Provider>
  );
}

export function useAgentPanel(): AgentPanelContextValue {
  const ctx = useContext(AgentPanelContext);
  if (!ctx) {
    throw new Error("useAgentPanel must be used within AgentPanelProvider");
  }
  return ctx;
}
