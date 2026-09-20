import { api } from "./api";

export type Mood = "BULLISH" | "BEARISH" | "NEUTRAL";
export type Confidence = "HIGH" | "MEDIUM" | "LOW";

export interface SectorHeadline {
  title: string | null;
  source: string | null;
  url: string | null;
  date: string | null;
}

export interface SectorMacroDriver {
  factor: string;
  tilt: "+" | "-" | "0" | string;
  rationale: string;
}

export interface SectorCard {
  sector: string;
  mood: Mood | null;
  score: number | null;
  confidence: Confidence | null;
  signals: string[] | null;
  summary: string | null;
  headline_count: number | null;
  last_run_at: string | null;
  bellwethers: string[];

  // Full-shape only (not present when the row comes from /api/today/brief).
  macro_drivers?: SectorMacroDriver[] | null;
  what_to_watch?: string[] | null;
  top_headlines?: SectorHeadline[] | null;
}

export function getSectors(): Promise<SectorCard[]> {
  return api.get<SectorCard[]>("/api/today/sectors");
}

export function refreshSector(sector: string): Promise<SectorCard> {
  const encoded = encodeURIComponent(sector);
  return api.post<SectorCard>(`/api/today/sectors/${encoded}/refresh`);
}
