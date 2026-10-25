<script>
  import StationCard from '../StationCard.svelte';
  import { miles } from '../geo.js';
  let { found, p, idx, api } = $props();
  let sort = $state('distance'), onlyStream = $state(false);
  const anyMoney = $derived(found.some(s => idx.stations[s.fac]?.total));
  const list = $derived.by(() => {
    let l = onlyStream ? found.filter(s => s.newson) : [...found];
    const money = s => idx.stations[s.fac]?.total || 0;
    if (sort === 'money') l.sort((a, b) => money(b) - money(a));
    else if (sort === 'distance') l.sort((a, b) => (a.svc === 'DTV' ? 0 : 1) - (b.svc === 'DTV' ? 0 : 1) || miles(p, a.tx) - miles(p, b.tx));
    return l;
  });
</script>
<div class="chips" style="margin:0 0 8px">
  <span class="muted small">Sort:</span>
  <span class="chip" class:on={sort === 'distance'} onclick={() => sort = 'distance'} role="button" tabindex="0">Nearest</span>
  <span class="chip" class:on={sort === 'money'} style:opacity={anyMoney ? 1 : 0.45} title={anyMoney ? '' : 'No crawled filings for these stations yet'} onclick={() => anyMoney && (sort = 'money')} role="button" tabindex="0">Most money</span>
  <label class="chip" style="display:inline-flex;gap:4px;align-items:center"><input type="checkbox" bind:checked={onlyStream} style="margin:0" /> live stream</label>
</div>
{#each list as s (s.fac)}
  <StationCard {s} {p} spend={idx.stations[s.fac] ? { ...idx.stations[s.fac] } : null} year={idx.year} onhover={fac => api?.highlight(fac)} onzoom={st => api?.fitBounds(st.bbox)} />
{/each}
