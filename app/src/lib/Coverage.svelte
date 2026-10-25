<script>
  // Empty state for places whose stations have no crawled filings yet.
  import { get } from './data.js';
  let { found, idx, what = 'political filings' } = $props();
  let states = $state.raw([]);
  get('methods.json').then(m => states = m.stations?.states || []).catch(() => {});
  const crawled = $derived(found.filter(s => idx?.stations?.[s.fac]).length);
</script>
<div class="card" style="border-style:dashed">
  <b>No {what} here yet.</b>
  <div class="muted small" style="margin-top:4px">{found.length} station{found.length === 1 ? '' : 's'} reach this spot, but {crawled ? `only ${crawled} of them have` : 'none of them has'} been crawled. Political files are in for stations in {states.length ? states.join(', ') : '…'}; the national crawl is in progress. Try a ZIP in one of those states, e.g. 50309 (Des Moines) or 30303 (Atlanta).</div>
</div>
