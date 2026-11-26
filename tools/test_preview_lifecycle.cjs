/* Exercise the actual preview lifecycle handlers without requiring a GPU. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../templates/booking/vr_seat_preview.html'), 'utf8');

function preview() {
    const listeners = {};
    const frames = new Set();
    let next = 0;
    const document = {hidden:false, addEventListener:(type, fn) => { listeners[type] = fn; }};
    const window = {parent:{}, addEventListener:(type, fn) => { listeners[type] = fn; }};
    const ctx = vm.createContext({document, window, location:{origin:'http://localhost'},
        container:{isConnected:true}, clock:{start() {}}, animate() {}, resizePreview() {},
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

test('zero-sized viewports cannot start a render loop', () => {
    const p = preview();
    vm.runInContext('window.innerWidth=0; window.innerHeight=0; startAnimationLoop()', p.ctx);
    assert.equal(p.frames.size, 0);
    vm.runInContext('window.innerWidth=390; window.innerHeight=844; startAnimationLoop()', p.ctx);
    assert.equal(p.frames.size, 1);
});

test('destroy releases unique geometries, materials, textures and context exactly once', () => {
    const p = preview();
    const start = source.indexOf('        function destroyPreview()');
    const end = source.indexOf("        renderer.domElement.addEventListener", start);
    vm.runInContext(`
      let releases=0;
      const shared={dispose(){releases++}}, lod={dispose(){releases++}};
      const screenTexture={isTexture:true,dispose(){releases++}};
      const seatFabricTexture={isTexture:true,dispose(){releases++}};
      const material={map:seatFabricTexture,dispose(){releases++}};
      const scene={traverse(fn){fn({geometry:shared,material});fn({geometry:shared,material})}};
      const seatGeometryVariants=[{near:shared,far:lod}];
      const customVideoEl={pause(){},removeAttribute(){},load(){}};
      const renderer={dispose(){releases++},forceContextLoss(){releases++}};
      ${source.slice(start,end)}
      startAnimationLoop();destroyPreview();destroyPreview();
    `,p.ctx);
    assert.equal(p.frames.size,0);
    assert.equal(vm.runInContext('releases',p.ctx),7);
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
