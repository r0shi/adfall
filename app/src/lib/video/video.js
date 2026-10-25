// Helpers for the Ad-ID → video chain (fields exported by ingest/export.py from creative_video).
export const TIERS = {
  high: { label: 'match', title: 'High confidence: upload date, length and release order all line up', color: '#1f9d55' },
  medium: { label: 'likely', title: 'Medium confidence: lines up on date, but a sibling upload is close', color: '#d98c1f' },
  low: { label: 'guess', title: 'Low confidence: nearest upload by date only', color: 'var(--muted)' },
};
export const tier = (c) => c == null ? null : c >= 0.7 ? 'high' : c >= 0.4 ? 'medium' : 'low';
export const canEmbed = (c) => !!c?.embed_url;

/** Collapse creatives into spot families (one tile per spot: the Ad-ID without the per-airing tail the invoices append). */
export function families(list) {
  const m = new Map();
  for (const c of list) {
    const k = c.family || c.ad_id;
    const e = m.get(k) || { key: k, ad_id: c.ad_id, buyer: c.buyer, category: c.category, airings: 0, ids: [], first: c.first, last: c.last, video: null };
    e.airings += c.airings; e.ids.push(c.ad_id);
    if (c.first < e.first) e.first = c.first; if (c.last > e.last) e.last = c.last;
    if (c.video_url && (!e.video || (c.confidence || 0) > (e.video.confidence || 0))) {
      e.video = { video_url: c.video_url, embed_url: c.embed_url, thumb_url: c.thumb_url, confidence: c.confidence, source: c.source };
      e.ad_id = c.ad_id;
    }
    m.set(k, e);
  }
  return [...m.values()].sort((a, b) => b.airings - a.airings);
}

/** Autoplaying, privacy-enhanced embed URL for a stored embed_url (YouTube only; other sources link out). */
export const playUrl = (embed) => embed ? `${embed}${embed.includes('?') ? '&' : '?'}autoplay=1&rel=0&modestbranding=1&playsinline=1` : null;
