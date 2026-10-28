// Phone layout state shared by the map page, the popover sheet and the timeline: whether the narrow layout is on (the
// same 800px breakpoint as the CSS) and how tall the open bottom sheets are, so the timeline dock can sit above them.
export const phone = $state({ on: false, sheetH: 0 });
if (typeof window !== 'undefined') {
  const mq = matchMedia('(max-width: 800px)');
  phone.on = mq.matches;
  mq.addEventListener('change', (e) => { phone.on = e.matches; });
}
const heights = new Map();
/** A sheet reports its height (0 when it closes); the dock clears the tallest. */
export function sheetHeight(id, h) { if (h) heights.set(id, h); else heights.delete(id); phone.sheetH = Math.max(0, ...heights.values()); }
