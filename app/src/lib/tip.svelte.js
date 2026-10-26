// One floating tooltip for the whole app. Use it as an action: <a use:tip={'text'}> or use:tip={{ text, html }}.
// Tip.svelte (mounted in the layout) draws it next to the pointer; text updates follow the action's parameter.
export const tipState = $state({ text: '', html: false, x: 0, y: 0, on: false });

export function tip(node, param) {
  let p = norm(param);
  const show = (e) => { if (!p.text) return; tipState.text = p.text; tipState.html = p.html; move(e); tipState.on = true; };
  const move = (e) => { tipState.x = e.clientX; tipState.y = e.clientY; };
  const hide = () => { tipState.on = false; };
  node.addEventListener('pointerenter', show); node.addEventListener('pointermove', move); node.addEventListener('pointerleave', hide); node.addEventListener('pointerdown', hide);
  return {
    update(next) { p = norm(next); if (tipState.on) { tipState.text = p.text; tipState.html = p.html; } },
    destroy() { hide(); node.removeEventListener('pointerenter', show); node.removeEventListener('pointermove', move); node.removeEventListener('pointerleave', hide); node.removeEventListener('pointerdown', hide); }
  };
}
const norm = (p) => typeof p === 'string' ? { text: p, html: false } : { text: p?.text || '', html: !!p?.html };
