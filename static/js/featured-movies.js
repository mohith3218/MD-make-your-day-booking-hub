(() => {
  const carousel = document.querySelector('[data-feature-carousel]');
  if (!carousel) return;

  const slides = [...carousel.querySelectorAll('[data-feature-slide]')];
  slides.forEach(slide => {
    const image = slide.querySelector('[data-feature-image]');
    if (image) image.addEventListener('error', () => {
      image.hidden = true;
      image.closest('.cw-feature-art')?.classList.add('is-missing');
    }, { once: true });
  });

  if (slides.length < 2) return;
  const controls = carousel.querySelector('[data-feature-controls]');
  const previous = carousel.querySelector('[data-feature-prev]');
  const next = carousel.querySelector('[data-feature-next]');
  const dots = [...carousel.querySelectorAll('[data-feature-dot]')];
  const count = carousel.querySelector('[data-feature-count]');
  const status = carousel.querySelector('[data-feature-status]');
  if (!controls || !previous || !next || dots.length !== slides.length) return;

  let activeIndex = 0;
  slides.forEach((slide, index) => {
    slide.hidden = false;
    slide.classList.toggle('is-active', index === activeIndex);
    slide.setAttribute('aria-hidden', String(index !== activeIndex));
    slide.inert = index !== activeIndex;
  });
  controls.hidden = false;

  const select = (rawIndex, direction = 1) => {
    const targetIndex = (rawIndex + slides.length) % slides.length;
    if (targetIndex === activeIndex) return;
    const previousIndex = activeIndex;
    const outgoing = slides[previousIndex];
    const incoming = slides[targetIndex];

    outgoing.classList.remove('is-active');
    outgoing.classList.add('is-exiting', direction < 0 ? 'is-exiting-left' : 'is-exiting-right');
    outgoing.setAttribute('aria-hidden', 'true');
    outgoing.inert = true;
    incoming.classList.add('is-active');
    incoming.setAttribute('aria-hidden', 'false');
    incoming.inert = false;
    activeIndex = targetIndex;

    dots.forEach((dot, index) => dot.setAttribute('aria-current', String(index === activeIndex)));
    if (count) count.textContent = `${String(activeIndex + 1).padStart(2, '0')} / ${String(slides.length).padStart(2, '0')}`;
    if (status) status.textContent = `Showing ${slides[activeIndex].getAttribute('aria-label')}`;

    window.setTimeout(() => {
      outgoing.classList.remove('is-exiting', 'is-exiting-left', 'is-exiting-right');
    }, 320);
  };

  previous.addEventListener('click', () => select(activeIndex - 1, -1));
  next.addEventListener('click', () => select(activeIndex + 1, 1));
  dots.forEach((dot, index) => dot.addEventListener('click', () => select(index, index < activeIndex ? -1 : 1)));

  carousel.addEventListener('keydown', event => {
    if (event.target !== carousel) return;
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      select(activeIndex - 1, -1);
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      select(activeIndex + 1, 1);
    }
  });

  let touchStart = null;
  carousel.addEventListener('pointerdown', event => {
    if (event.pointerType !== 'touch' || event.target.closest('a, button')) return;
    touchStart = { x: event.clientX, y: event.clientY };
  }, { passive: true });
  carousel.addEventListener('pointerup', event => {
    if (!touchStart || event.target.closest('a, button')) {
      touchStart = null;
      return;
    }
    const deltaX = event.clientX - touchStart.x;
    const deltaY = event.clientY - touchStart.y;
    touchStart = null;
    if (Math.abs(deltaX) < 48 || Math.abs(deltaX) < Math.abs(deltaY) * 1.2) return;
    select(activeIndex + (deltaX < 0 ? 1 : -1), deltaX < 0 ? 1 : -1);
  }, { passive: true });
  carousel.addEventListener('pointercancel', () => { touchStart = null; });
})();
