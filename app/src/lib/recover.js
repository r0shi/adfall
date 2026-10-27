// Recovery from the ways a static deploy leaves a tab stuck. A rebuild replaces every hashed chunk and drops the old
// ones; a tab still holding the previous index.html then fails its next dynamic import with nothing to show for it.
// Failing is fine, staying failed is not: reload once for a stale build, and give every other failure words and a retry.
const STALE = /dynamically imported module|Importing a module script|error loading dynamically|Loading (CSS )?chunk|Unable to preload CSS/i;
export const isStaleBuild = (e) => STALE.test(String(e?.message || e));
const KEY = 'adfall:reloaded';

/** Reload the page, at most once a minute, so a genuinely broken build cannot loop. Returns false when it declined. */
export function reloadOnce() {
  try {
    const last = +sessionStorage.getItem(KEY) || 0;
    if (Date.now() - last < 60_000) return false;
    sessionStorage.setItem(KEY, String(Date.now()));
  } catch {
    // storage blocked: the navigation type is the only memory left, so never reload a page that is itself a reload
    if (performance.getEntriesByType?.('navigation')?.[0]?.type === 'reload') return false;
  }
  location.reload();
  return true;
}

/** Wrap a dynamic import: a chunk missing after a rebuild reloads the tab instead of failing silently. */
export async function lazy(loader) {
  try { return await loader(); }
  catch (e) {
    if (isStaleBuild(e) && reloadOnce()) throw Object.assign(new Error('A new build was published; reloading…'), { reloading: true });
    throw e;
  }
}

/** A short reason for a failed load, in words a visitor can act on. */
export function describe(e) {
  if (e?.reloading) return e.message;
  if (isStaleBuild(e)) return 'this page is from an older build than the server; reload to pick up the new one';
  const m = String(e?.message || e);
  if (/Failed to fetch|NetworkError|Load failed/i.test(m)) return 'the network request failed';
  return m;
}
