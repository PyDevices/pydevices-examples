/*! coi-serviceworker v0.1.7 - Guido Zuidhof and contributors, licensed under MIT */
/*! mini-coi - Andrea Giammarchi and contributors, licensed under MIT */
/** Lightweight Cross-Origin Isolation shim registering ./coi-sw.js */
(({ document: d, navigator: { serviceWorker: s } }) => {
  if (!d || !s) return;
  try { new SharedArrayBuffer(4, { maxByteLength: 8 }); }
  catch (_) {
    const { currentScript: c } = d;
    const scope = (c && c.getAttribute('scope')) || '.';
    s.register('./coi-sw.js', { scope }).then(r => {
      r.addEventListener('updatefound', () => location.reload());
      if (r.active && !s.controller) location.reload();
    });
  }
})(typeof document !== 'undefined' ? globalThis : undefined);
