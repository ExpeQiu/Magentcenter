import { KnowledgePage } from "@/components/knowledge/knowledge-page";
import type { KnowledgeHit } from "@/lib/types";

const INTERNAL_API =
  process.env.INTERNAL_API_BASE ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://127.0.0.1:8013";

async function fetchInitialEntries(): Promise<KnowledgeHit[]> {
  const url =
    `${INTERNAL_API}/api/knowledge/entries?limit=50` +
    `&kind=${encodeURIComponent(
      "playbook,precedent,shared_fact,incident,artifact_ref"
    )}`;
  try {
    const res = await fetch(url, { cache: "no-store", next: { revalidate: 0 } });
    if (!res.ok) {
      console.error("[knowledge/page] entries http", res.status);
      return [];
    }
    const data = (await res.json()) as KnowledgeHit[];
    console.info("[knowledge/page] ssr entries=%d", Array.isArray(data) ? data.length : 0);
    return Array.isArray(data) ? data : [];
  } catch (err) {
    console.error("[knowledge/page] ssr fetch failed", err);
    return [];
  }
}

export default async function Page() {
  const initialHits = await fetchInitialEntries();
  return <KnowledgePage initialHits={initialHits} />;
}
