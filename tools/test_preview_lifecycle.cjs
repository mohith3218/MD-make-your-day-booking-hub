/* Exercise the actual preview lifecycle handlers without requiring a GPU. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../templates/vr_seat_preview.html'), 'utf8');

function preview() {
    const listeners = {};
    const frames = new Set();
    let next = 0;
    const document = {hidden:false, addEventListener:(type, fn) => { listeners[type] = fn; }};
    const window = {parent:{}, addEventListener:(type, fn) => { listeners[type] = fn; }};
    const ctx = vm.createContext({document, window, location:{origin:'http://localhost'},
        container:{isConnected:true}, clock:{start() {}}, animate() {},
        requestAnimationFrame:() => { frames.add(++next); return next; },
        cancelAnimationFrame:id => frames.delete(id)});
    const start = source.indexOf('        function startAnimationLoop()');
    const end = source.indexOf('        function destroyPreview()', start);
    const visibility = source.indexOf("        document.addEventListener('visibilitychange'");
    const messageEnd = source.indexOf('        // Ambient & House Lights', visibility);
    assert.ok(start > 0 && end > start && visibility > end && messageEnd > visibility);
    const handlers = source.slice(visibility, messageEnd)
        .replace("        window.addEventListener('pagehide', destroyPreview, { once: true });", '');
    vm.runInContext('let animationDestroyed=false, previewPausedByParent=false, animationFrameId=0;'
        + source.slice(start, end) + handlers, ctx);
    const send = (type, origin='http://localhost', sender=window.parent) =>
        listeners.message({origin, source:sender, data:{type}});
    return {ctx, frames, document, listeners, send};
}

test('a booking-page pause survives hiding and returning to the tab until explicit resume', () => {
    const p = preview();
    vm.runInContext('startAnimationLoop()', p.ctx);
    assert.equal(p.frames.size, 1);
    p.send('cinewave:pause');
    p.document.hidden = true; p.listeners.visibilitychange();
    p.document.hidden = false; p.listeners.visibilitychange();
    assert.equal(p.frames.size, 0);
    p.send('cinewave:resume');
    assert.equal(p.frames.size, 1);
    p.send('cinewave:resume');
    assert.equal(p.frames.size, 1, 'resume never creates duplicate loops');
});

test('hidden, detached and destroyed previews do not schedule frames', () => {
    const p = preview();
    p.document.hidden = true; p.send('cinewave:resume');
    assert.equal(p.frames.size, 0);
    p.document.hidden = false;
    vm.runInContext('container.isConnected=false; startAnimationLoop()', p.ctx);
    assert.equal(p.frames.size, 0);
    vm.runInContext('container.isConnected=true; animationDestroyed=true; startAnimationLoop()', p.ctx);
    assert.equal(p.frames.size, 0);
});

test('untrusted message origins and senders cannot resume the preview', () => {
    const p = preview();
    p.send('cinewave:pause');
    p.send('cinewave:resume', 'https://untrusted.invalid');
    p.send('cinewave:resume', 'http://localhost', {});
    assert.equal(p.frames.size, 0);
    p.send('cinewave:resume');
    assert.equal(p.frames.size, 1);
});
