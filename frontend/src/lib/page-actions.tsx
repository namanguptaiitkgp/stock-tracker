"use client";

import React, { createContext, useContext, useEffect, useState } from "react";

interface Ctx {
  actions: React.ReactNode;
  setActions: (node: React.ReactNode) => void;
}

const PageActionsContext = createContext<Ctx>({
  actions: null,
  setActions: () => {},
});

export function PageActionsProvider({ children }: { children: React.ReactNode }) {
  const [actions, setActions] = useState<React.ReactNode>(null);
  return (
    <PageActionsContext.Provider value={{ actions, setActions }}>
      {children}
    </PageActionsContext.Provider>
  );
}

/** AppShell uses this to render the current page's actions in the tab bar. */
export function usePageActionsRender() {
  return useContext(PageActionsContext).actions;
}

/**
 * Page hook. Pass the JSX you want rendered in the AppShell tab bar.
 * Cleared when the page unmounts.
 *
 * IMPORTANT: include in `deps` any state the JSX closure depends on so the
 * slot re-renders. (Same rules as useEffect deps.)
 */
export function usePageActions(node: React.ReactNode, deps: React.DependencyList) {
  const { setActions } = useContext(PageActionsContext);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    setActions(node);
    return () => setActions(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
