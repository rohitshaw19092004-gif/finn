import { createContext, useContext } from "react";

export type Tab = "brief" | "ask" | "people";
export interface Nav {
  tab: (t: Tab) => void;
  company: (sym: string) => void;      // open dossier
  contact: (id: string) => void;       // open someone in my network
  filedPerson: (id: string) => void;   // open someone named in a filing
  ask: (q: string) => void;            // run a query in Ask
}
export const NavCtx = createContext<Nav | null>(null);
export const useNav = () => useContext(NavCtx)!;
