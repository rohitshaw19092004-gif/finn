import { createContext, useContext } from "react";
import type { Dossier, FiledPerson, Filing, Holding, Meta, Network, Registry, Story } from "./types";
import { NetworkIndex } from "./network";

export interface Snapshot {
  meta: Meta; holdings: Holding[]; filings: Filing[]; byId: Map<string, Filing>; stories: Story[];
  people: FiledPerson[]; peopleById: Map<string, FiledPerson>; registry: Registry; network: Network; idx: NetworkIndex; asOf: Date;
}

const BASE = "./data/";
const API = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "");
export const apiBase = API;

async function j<T>(name: string): Promise<T> {
  const r = await fetch(BASE + name, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${name}: ${r.status}`);
  return r.json();
}

export async function loadSnapshot(): Promise<Snapshot> {
  const [meta, holdings, feed, people, registry, network] = await Promise.all([
    j<Meta>("meta.json"), j<Holding[]>("portfolio.json"), j<{ filings: Filing[]; stories: Story[] }>("feed.json"),
    j<FiledPerson[]>("people.json"), j<Registry>("companies.json"), loadNetwork(),
  ]);
  const asOf = new Date(meta.generated_at);
  const byId = new Map(feed.filings.map((f) => [f.id, f] as const));
  return {
    meta, holdings, filings: feed.filings, byId, stories: feed.stories, people,
    peopleById: new Map(people.map((p) => [p.id, p] as const)), registry, network, asOf,
    idx: new NetworkIndex(network, registry, asOf),
  };
}

/** The network lives on the device. First run seeds the synthetic demo network; an import replaces it. */
async function loadNetwork(): Promise<Network> {
  try {
    const own = localStorage.getItem("finn:network");
    if (own) return JSON.parse(own);
  } catch { /* storage unavailable */ }
  return j<Network>("network-demo.json");
}

const dossierCache = new Map<string, Dossier>();

export async function loadDossier(sym: string, onProgress?: (msg: string) => void): Promise<Dossier> {
  if (dossierCache.has(sym)) return dossierCache.get(sym)!;
  const local = await fetch(`${BASE}research/${sym}.json`, { cache: "no-cache" });
  if (local.ok) {
    const d = await local.json();
    dossierCache.set(sym, d);
    return d;
  }
  if (!API) throw new Error("offline");
  return new Promise((resolve, reject) => {
    const es = new EventSource(`${API}/api/research/${encodeURIComponent(sym)}/stream`);
    es.addEventListener("progress", (e) => onProgress?.(JSON.parse((e as MessageEvent).data).msg));
    es.addEventListener("done", (e) => { const d = JSON.parse((e as MessageEvent).data); dossierCache.set(sym, d); es.close(); resolve(d); });
    es.addEventListener("error", (e) => {
      const data = (e as MessageEvent).data;
      es.close();
      reject(new Error(data ? JSON.parse(data).msg : "Research engine unreachable"));
    });
  });
}

export async function searchCompanies(q: string): Promise<{ name: string; symbol: string }[]> {
  if (!API || q.length < 2) return [];
  try {
    const r = await fetch(`${API}/api/search?q=${encodeURIComponent(q)}`);
    return r.ok ? r.json() : [];
  } catch { return []; }
}

export const SnapCtx = createContext<Snapshot | null>(null);
export const useSnap = () => useContext(SnapCtx)!;
