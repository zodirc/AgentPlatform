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
  /** Right-side agent chat panel visible (IDE fold). */
  open: boolean;
  setOpen: (open: boolean) => void;
  /** Show the agent panel without replacing the session. */
  openPanel: () => void;
  /** Fold the agent panel (session kept). */
  closePanel: () => void;
  /** Toggle fold. */
  togglePanel: () => void;
  /** Open panel and start a fresh session (Cursor "new agent"). */
  createAgent: () => Promise<void>;
};

const AgentPanelContext = createContext<AgentPanelContextValue | null>(null);

export function AgentPanelProvider({ children }: { children: ReactNode }) {
  const { startNewSession } = useWorkbenchSession();
  const [open, setOpen] = useState(true);

  const openPanel = useCallback(() => setOpen(true), []);
  const closePanel = useCallback(() => setOpen(false), []);
  const togglePanel = useCallback(() => setOpen((v) => !v), []);

  const createAgent = useCallback(async () => {
    setOpen(true);
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
