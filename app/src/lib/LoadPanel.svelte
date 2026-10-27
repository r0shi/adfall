<script>
  // What a visitor sees while a big load is slow or after it failed: the reason and a way out, never a blank panel.
  // `state` is { status, error, slow } as in timedata.svelte.js.
  let { state, what = 'the data', onretry = null } = $props();
</script>
{#if state.status === 'error'}
  <div class="loadpanel"><b>Couldn't load {what}</b><div class="small muted">{state.error}</div>
    <div class="chips" style="margin-top:6px">{#if onretry}<span class="chip" onclick={onretry} onkeydown={e => e.key === 'Enter' && onretry()} role="button" tabindex="0">Try again</span>{/if}<span class="chip" onclick={() => location.reload()} onkeydown={e => e.key === 'Enter' && location.reload()} role="button" tabindex="0">Reload the page</span></div></div>
{:else if state.status === 'loading' && state.slow}
  <div class="loadpanel"><b>Still loading {what}…</b><div class="small muted">About 9 MB; a slow link takes a while.</div>
    <div class="chips" style="margin-top:6px"><span class="chip" onclick={() => location.reload()} onkeydown={e => e.key === 'Enter' && location.reload()} role="button" tabindex="0">Reload the page</span></div></div>
{/if}
<style>
  .loadpanel { margin-top: 8px; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--line); background: color-mix(in srgb, var(--bg) 60%, transparent); font-size: 12.5px; }
</style>
