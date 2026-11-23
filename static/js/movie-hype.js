document.querySelectorAll('[data-hype-form]').forEach((form) => {
  const choices = [...form.querySelectorAll('button[name="level"]')];
  const status = form.querySelector('[data-hype-status]');
  let pending = false;

  form.addEventListener('submit', async (event) => {
    const choice = event.submitter;
    if (!choice || !choices.includes(choice)) return;
    event.preventDefault();
    if (pending) return;
    pending = true;
    const body = new FormData(form);
    body.set('level', choice.value);
    form.setAttribute('aria-busy', 'true');
    status.textContent = 'Saving your vote…';
    try {
      const response = await fetch(form.action, {
        method: 'POST', body, headers: { Accept: 'application/json' },
      });
      if (response.status === 401) {
        status.textContent = 'Sign in to vote. Reload this page to sign in again.';
        return;
      }
      if (!response.ok) throw new Error('Vote request failed');
      const result = await response.json();
      if (!choices.some((button) => button.value === result.selected) ||
          choices.some((button) => !Number.isInteger(result.counts?.[button.value]))) {
        throw new Error('Vote response was invalid');
      }
      choices.forEach((button) => {
        button.setAttribute('aria-pressed', String(button.value === result.selected));
        button.querySelector('[data-vote-count]').textContent = result.counts[button.value];
      });
      status.textContent = 'Your hype vote is saved.';
    } catch {
      status.textContent = 'Could not update your vote. If this continues, reload the page and try again.';
    } finally {
      pending = false;
      form.removeAttribute('aria-busy');
    }
  });
});
