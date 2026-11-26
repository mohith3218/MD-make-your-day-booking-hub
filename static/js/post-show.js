(() => {
  const mount = document.querySelector('[data-review-prompt]');
  if (!mount) return;
  const key = `cinewave.review-prompt-dismissed.${mount.dataset.reviewMember}`;
  try {
    if (sessionStorage.getItem(key)) return;
  } catch {}

  fetch(mount.dataset.reviewPrompt, { headers: { Accept: 'text/html' }, credentials: 'same-origin' })
    .then((response) => response.status === 200 && !response.redirected ? response.text() : '')
    .then((html) => {
      if (!html || document.querySelector('dialog[open]')) return;
      mount.innerHTML = html;
      const dialog = mount.querySelector('dialog');
      if (!dialog?.showModal) return;
      const dismiss = () => {
        try { sessionStorage.setItem(key, '1'); } catch {}
      };
      dialog.addEventListener('close', dismiss);
      dialog.addEventListener('cancel', dismiss);
      dialog.querySelectorAll('[data-close-review]').forEach((button) => {
        button.addEventListener('click', () => {
          dismiss();
          dialog.close();
        });
      });
      dialog.querySelector('form').addEventListener('submit', dismiss);
      dialog.showModal();
    }).catch(() => {});
})();
