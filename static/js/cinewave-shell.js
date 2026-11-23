(() => {
  const root = document.documentElement;
  const preference = window.matchMedia('(prefers-color-scheme: light)');
  const storageKey = 'cw_theme_mode';
  let mode = 'system';

  try {
    const saved = localStorage.getItem(storageKey);
    const legacy = localStorage.getItem('cw_theme_override');
    const candidate = saved || legacy || 'system';
    if (['system', 'light', 'dark'].includes(candidate)) mode = candidate;
  } catch { /* The system preference still works when storage is unavailable. */ }

  // Set the root theme before the shared stylesheet is loaded to avoid a flash.
  root.dataset.theme = mode;

  function applyTheme() {
    const light = mode === 'light' || (mode === 'system' && preference.matches);
    document.body?.classList.toggle('light-mode', light);
    document.body?.classList.toggle('dark-mode', !light);
    document.querySelectorAll('[data-theme-choice]').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.themeChoice === mode));
    });
    const summary = document.querySelector('.cw-theme-menu > summary');
    if (summary) summary.setAttribute('aria-label', `Appearance settings. Current theme: ${mode === 'system' ? 'system default' : mode}.`);
  }

  function setTheme(choice) {
    if (!['system', 'light', 'dark'].includes(choice)) return;
    mode = choice;
    root.dataset.theme = mode;
    try { localStorage.setItem(storageKey, mode); } catch { /* Keep this choice for the current page. */ }
    applyTheme();
  }

  function closeNavigation() {
    const menu = document.getElementById('cw-main-nav');
    const toggle = document.getElementById('cw-menu-toggle');
    menu?.classList.remove('is-open');
    toggle?.setAttribute('aria-expanded', 'false');
    toggle?.setAttribute('aria-label', 'Open navigation menu');
  }

  function initializeControls() {
    applyTheme();
    document.querySelectorAll('[data-theme-choice]').forEach((button) => {
      button.addEventListener('click', () => setTheme(button.dataset.themeChoice));
    });

    const menu = document.getElementById('cw-main-nav');
    const toggle = document.getElementById('cw-menu-toggle');
    toggle?.addEventListener('click', () => {
      const open = !menu?.classList.contains('is-open');
      menu?.classList.toggle('is-open', open);
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', open ? 'Close navigation menu' : 'Open navigation menu');
    });
    menu?.querySelectorAll('a').forEach((link) => link.addEventListener('click', closeNavigation));
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeNavigation();
    });
    const desktopNavigation = window.matchMedia(menu?.classList.contains('cw-admin-nav')
      ? '(min-width: 1101px)' : '(min-width: 901px)');
    window.addEventListener('resize', () => {
      if (desktopNavigation.matches) closeNavigation();
    }, { passive: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeControls, { once: true });
  } else {
    initializeControls();
  }
  if (preference.addEventListener) preference.addEventListener('change', () => { if (mode === 'system') applyTheme(); });
  else preference.addListener(() => { if (mode === 'system') applyTheme(); });
})();
