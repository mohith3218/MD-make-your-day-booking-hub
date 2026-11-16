/* Exercise the account-page progressive enhancement without external packages. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'auth.js'), 'utf8');

function createHarness() {
  const input = { id: 'register-password', type: 'password' };
  const button = {
    textContent: 'Show', attrs: new Map([['aria-controls', input.id], ['aria-pressed', 'false']]),
    listeners: {},
    getAttribute(name) { return this.attrs.get(name) ?? null; },
    setAttribute(name, value) { this.attrs.set(name, value); },
    addEventListener(name, callback) { this.listeners[name] = callback; },
  };
  const submit = {
    disabled: false, attrs: new Map(),
    setAttribute(name, value) { this.attrs.set(name, value); },
    removeAttribute(name) { this.attrs.delete(name); },
  };
  const form = {
    attrs: new Map(), listeners: {},
    setAttribute(name, value) { this.attrs.set(name, value); },
    removeAttribute(name) { this.attrs.delete(name); },
    querySelector(selector) { return selector === 'button[type="submit"]' ? submit : null; },
    addEventListener(name, callback) { this.listeners[name] = callback; },
  };
  const windowListeners = {};
  const document = {
    querySelectorAll(selector) {
      return selector === '[data-password-toggle]' ? [button]
        : selector === '[data-auth-form]' ? [form] : [];
    },
    getElementById(id) { return id === input.id ? input : null; },
  };
  vm.runInNewContext(script, { document, window: {
    addEventListener(name, callback) { windowListeners[name] = callback; },
  } });
  return { input, button, form, submit, windowListeners };
}

test('password visibility toggles input type and accessible state', () => {
  const { input, button } = createHarness();
  button.listeners.click();
  assert.equal(input.type, 'text');
  assert.equal(button.textContent, 'Hide');
  assert.equal(button.attrs.get('aria-pressed'), 'true');
  button.listeners.click();
  assert.equal(input.type, 'password');
  assert.equal(button.textContent, 'Show');
  assert.equal(button.attrs.get('aria-pressed'), 'false');
});

test('auth form shows pending state and restores after page navigation', () => {
  const { form, submit, windowListeners } = createHarness();
  form.listeners.submit();
  assert.equal(form.attrs.get('aria-busy'), 'true');
  assert.equal(submit.disabled, true);
  assert.equal(submit.attrs.get('aria-label'), 'Submitting form');
  windowListeners.pageshow();
  assert.equal(form.attrs.has('aria-busy'), false);
  assert.equal(submit.disabled, false);
  assert.equal(submit.attrs.has('aria-label'), false);
});
