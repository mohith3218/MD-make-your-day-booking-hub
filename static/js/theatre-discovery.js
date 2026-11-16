/* Progressive enhancement: forms, date links and booking work without JS. */
(() => {
  function restoreForms() {
    document.querySelectorAll('[data-discovery-form]').forEach(form => {
      form.removeAttribute('aria-busy');
      form.querySelector('button[type="submit"]').disabled = false;
      form.querySelector('.td-loading').hidden = true;
    });
  }
  document.querySelectorAll('[data-discovery-form]').forEach(form => {
    form.addEventListener('submit', () => {
      form.setAttribute('aria-busy', 'true');
      form.querySelector('button[type="submit"]').disabled = true;
      form.querySelector('.td-loading').hidden = false;
    });
  });
  window.addEventListener('pageshow', restoreForms);
  document.querySelectorAll('[data-discovery-poster]').forEach(img => {
    function fallback() {
      img.hidden = true;
      img.parentElement.querySelector('.td-poster-fallback').hidden = false;
    }
    img.addEventListener('error', fallback, { once: true });
    if (img.complete && !img.naturalWidth) fallback();
  });
})();
