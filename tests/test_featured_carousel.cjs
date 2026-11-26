const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function element(attributes = {}) {
  const listeners = new Map();
  const classes = new Set();
  const attrs = new Map(Object.entries(attributes));
  return {
    attrs,
    listeners,
    classes,
    hidden: false,
    inert: false,
    textContent: '',
    classList: {
      add: (...names) => names.forEach(name => classes.add(name)),
      remove: (...names) => names.forEach(name => classes.delete(name)),
      contains: name => classes.has(name),
      toggle: (name, force) => {
        const enabled = force === undefined ? !classes.has(name) : force;
        if (enabled) classes.add(name); else classes.delete(name);
        return enabled;
      },
    },
    addEventListener(name, callback) {
      const callbacks = listeners.get(name) || [];
      callbacks.push(callback);
      listeners.set(name, callbacks);
    },
    dispatch(name, event = {}) {
      for (const callback of listeners.get(name) || []) callback(event);
    },
    setAttribute(name, value) { attrs.set(name, String(value)); },
    getAttribute(name) { return attrs.get(name) ?? null; },
    querySelector() { return null; },
    closest() { return null; },
  };
}

function fixture() {
  const slides = [0, 1, 2].map(index => {
    const slide = element({ 'aria-label': `${index + 1} of 3: Film ${index + 1}` });
    slide.querySelector = selector => selector === '[data-feature-image]' ? null : null;
    return slide;
  });
  const previous = element();
  const next = element();
  const dots = slides.map((_, index) => element({ 'aria-current': String(index === 0) }));
  const count = element();
  const status = element();
  const controls = element();
  controls.hidden = true;
  const carousel = element();
  carousel.querySelectorAll = selector => {
    if (selector === '[data-feature-slide]') return slides;
    if (selector === '[data-feature-dot]') return dots;
    return [];
  };
  carousel.querySelector = selector => ({
    '[data-feature-controls]': controls,
    '[data-feature-prev]': previous,
    '[data-feature-next]': next,
    '[data-feature-count]': count,
    '[data-feature-status]': status,
  })[selector] || null;
  const context = {
    document: { querySelector: () => carousel },
    window: { setTimeout: callback => callback() },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/featured-movies.js'), 'utf8'), context);
  return { carousel, slides, previous, next, dots, count, status, controls };
}

test('next and previous controls update the active film and wrap around', () => {
  const ui = fixture();
  assert.equal(ui.controls.hidden, false);
  ui.next.dispatch('click');
  assert.equal(ui.slides[1].classList.contains('is-active'), true);
  assert.equal(ui.slides[0].getAttribute('aria-hidden'), 'true');
  assert.equal(ui.dots[1].getAttribute('aria-current'), 'true');
  assert.equal(ui.count.textContent, '02 / 03');
  assert.match(ui.status.textContent, /Film 2/);
  ui.previous.dispatch('click');
  assert.equal(ui.slides[0].classList.contains('is-active'), true);
  ui.previous.dispatch('click');
  assert.equal(ui.slides[2].classList.contains('is-active'), true);
});

test('indicators, keyboard arrows, and touch swipes select the expected film', () => {
  const ui = fixture();
  ui.dots[2].dispatch('click');
  assert.equal(ui.slides[2].classList.contains('is-active'), true);
  let prevented = false;
  ui.carousel.dispatch('keydown', { target: ui.carousel, key: 'ArrowLeft', preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(ui.slides[1].classList.contains('is-active'), true);
  const target = { closest: () => null };
  ui.carousel.dispatch('pointerdown', { pointerType: 'touch', clientX: 300, clientY: 10, target });
  ui.carousel.dispatch('pointerup', { clientX: 220, clientY: 12, target });
  assert.equal(ui.slides[2].classList.contains('is-active'), true);
});

test('broken artwork activates its own film placeholder', () => {
  const image = element();
  const art = element();
  image.closest = selector => selector === '.cw-feature-art' ? art : null;
  const slide = element();
  slide.querySelector = selector => selector === '[data-feature-image]' ? image : null;
  const carousel = element();
  carousel.querySelectorAll = selector => selector === '[data-feature-slide]' ? [slide] : [];
  const context = { document: { querySelector: () => carousel }, window: { setTimeout: callback => callback() } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/featured-movies.js'), 'utf8'), context);
  image.dispatch('error');
  assert.equal(image.hidden, true);
  assert.equal(art.classList.contains('is-missing'), true);
});
