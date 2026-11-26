/* Execute the actual rendered booking handlers against a small DOM test surface.
 * These are behavioral unit tests, not a claim of visual/browser verification.
 * Called by test_party.py with an isolated, Flask-rendered booking page.
 */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(process.env.BOOKING_QA_HTML, 'utf8');
const bookingContext = JSON.parse(html.match(/<script[^>]+id="booking-context"[^>]*>([\s\S]*?)<\/script>/)[1]);
const staticScript = fs.readFileSync(path.join(__dirname, '../static/js/booking.js'), 'utf8');
const script = staticScript.split('\n').map((line) => '  ' + line).join('\n');
function slice(start, end) {
    const a = script.indexOf(start), b = script.indexOf(end, a);
    assert.ok(a >= 0 && b > a, start);
    return script.slice(a, b);
}
class Element {
    constructor(id) { this.id=id; this.dataset={}; this.attrs={}; this.style={}; this.classes=new Set(); this.loads=0; this.disabled=false; this.textContent=''; this.children=[]; }
    classList = {
        add:(...xs)=>xs.forEach(x=>this.classes.add(x)),
        remove:(...xs)=>xs.forEach(x=>this.classes.delete(x)),
        contains:x=>this.classes.has(x),
        toggle:(x, force)=>{ const on=force ?? !this.classes.has(x); on?this.classes.add(x):this.classes.delete(x); return on; }
    };
    set className(value) { this.classes = new Set(value.split(/\s+/)); }
    get className() { return [...this.classes].join(' '); }
    setAttribute(k,v) { this.attrs[k]=v; }
    getAttribute(k) { return this.attrs[k] ?? null; }
    hasAttribute(k) { return k in this.attrs; }
    getBoundingClientRect() { return { top: 20, bottom: 420, height: 400 }; }
    set src(value) { this.loads++; this.attrs.src=value; }
    replaceChildren(...children) { this.children=children; }
    appendChild(child) { this.children.push(child); }
}
function booking() {
    const ids = ['seating-viewport','ar-preview-panel','ar-theater-wrapper','btn-view-2d','btn-view-3d',
        'immersive-booking-layout','close-full-preview','vr-inline-frame','party-status','party-squad-banner',
        'party-btn-badge','squad-room-code','party-close','squad-member-roster','party-code-input'];
    const elements = Object.fromEntries(ids.map(id=>[id,new Element(id)]));
    elements['vr-inline-frame'].dataset.src='/book/1/vr-preview?embed=1';
    const seats = ['A1','A2','A3'].map((id,i)=>Object.assign(new Element(id), {dataset:{seat:id,price:String(190-i*30),class:'Class '+i}}));
    const messages=[], listeners={}, timers=new Set(), fetchCalls=[];
    elements['vr-inline-frame'].contentWindow={postMessage:message=>messages.push(message)};
    const doc={hidden:false, body:{style:{}}, getElementById:id=>elements[id] || null,
        createElement:()=>new Element('chip'),
        querySelector:selector=>seats.find(s=>selector.includes(`data-seat="${s.id}"`)) || null,
        querySelectorAll:selector=>{
            if(selector==='.seat-btn')return seats;
            return seats.filter(s=> selector.includes('seat-booked') && s.classes.has('seat-booked')
                || selector.includes('seat-held') && s.classes.has('seat-held')
                || selector.includes('data-party-owner') && s.dataset.partyOwner);
        }};
    const ctx=vm.createContext({bookingContext, document:doc, window:{innerHeight:768,location:{origin:'http://localhost'},addEventListener:(type,fn)=>listeners[type]=fn},
        location:{origin:'http://localhost',href:'http://localhost/book/1'}, history:{replaceState(){}}, URL,
        navigator:{clipboard:{writeText:async()=>{}}},
        setInterval:fn=>{timers.add(fn);return fn;},clearInterval:fn=>timers.delete(fn),
        fetch:async(path,options)=>{fetchCalls.push({path,options});return {ok:true,status:200,json:async()=>({success:true,party_code:'ABC123',showtime_id:1,is_host:true,members:[],squad_seats:{}})};},
        input:{value:''},display:{},priceOut:{},btn:{},classLine:{},
        updateInspector(){},showSeatARPreview(){},renderVRCinemaSeatMap(){},draw3dArScreen(){},updateImmersiveBookingPanel(){},alert(){},
    });
    vm.runInContext(`const selected=new Map(), reservedSeats=[], draftKey='test'; let activePovSeat=null,pendingPreviewTrailer=false,activePartyCode=''; const partyCSRF='fixture', MAX_SEATS=2;let inlineTourTimer=null; const inlineVrFrame=document.getElementById('vr-inline-frame');function toggleInlineTour(){inlineTourTimer=null;}`
        + slice('  function paint(', '  // Build the booking view')
        + slice('  function toggleSeatSelection(', "  document.querySelectorAll('.seat-btn').forEach(b => {")
        + slice('  // ---- WATCH TOGETHER:', '  let availabilityPollRunning')
        + slice('  function toggleTheaterView(', '  let inlineTourTimer')
        + slice('  function open3dArModal(', '  window.addEventListener(\'message\'')
        + slice('  function ensureInlinePreview(', "  toggleTheaterView('2d');"), ctx);
    const run=code=>vm.runInContext(code,ctx);
    const json=code=>JSON.parse(JSON.stringify(run(code)));
    const messageHandler=slice("  window.addEventListener('message'", '  function renderVRCinemaSeatMap(');
    vm.runInContext(messageHandler,ctx);
    return {elements,seats,messages,ctx,run,json,listeners,timers,fetchCalls};
}

test('every actual Flask-rendered inline JavaScript block parses',()=>{
    new vm.Script(staticScript);
    for(const [_,attrs,code] of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
        if(!/src=|application\/ld\+json|application\/json/.test(attrs) && code.trim()) new vm.Script(code);
    }
});

test('2D default initializes no iframe; repeated 3D and fullscreen switches reuse one source',()=>{
    const p=booking(), frame=p.elements['vr-inline-frame'];
    p.run("toggleTheaterView('2d')");
    assert.equal(frame.loads,0);
    assert.equal(p.elements['seating-viewport'].classes.has('hidden'),false);
    p.run("selected.set('A1',{price:190,cls:'Premium'});toggleTheaterView('3d')");
    assert.equal(frame.loads,1); frame.onload();
    p.run("toggleTheaterView('2d');toggleTheaterView('3d');open3dArModal();close3dArModal();toggleTheaterView('2d')");
    assert.equal(frame.loads,1);
    assert.equal(p.run("selected.get('A1').price"),190);
    assert.equal(p.elements['btn-view-2d'].getAttribute('aria-pressed'),'true');
    assert.equal(p.elements['immersive-booking-layout'].classes.has('hidden'),true);
    assert.equal(p.messages.at(-1).type,'cinewave:pause');
});

test('an iframe finishing load after return to 2D stays paused',()=>{
    const p=booking(); p.run("toggleTheaterView('3d');toggleTheaterView('2d')");
    p.elements['vr-inline-frame'].onload();
    assert.equal(p.messages.at(-1).type,'cinewave:pause');
});

test('the trailer shortcut waits for the same-origin preview and sends one play request',()=>{
    const p=booking(), frame=p.elements['vr-inline-frame'];
    p.run('open3dArModal(true)');
    frame.onload();
    assert.equal(p.messages.some(message => message.type === 'cinewave:show-trailer'), false);
    const ready = {source: frame.contentWindow, data: {type: 'cinewave:ready'}};
    p.listeners.message({...ready, origin: 'https://other.invalid'});
    assert.equal(p.messages.some(message => message.type === 'cinewave:show-trailer'), false);
    p.listeners.message({...ready, origin: 'http://localhost'});
    p.run('syncVRPreviewActivity()');
    assert.equal(p.messages.filter(message => message.type === 'cinewave:show-trailer').length, 1);
});

test('2D picks, prices and classes reach 3D; 3D picks update the same booking input',()=>{
    const p=booking();p.run("toggleTheaterView('3d')");p.elements['vr-inline-frame'].onload();
    assert.equal(p.run("toggleSeatSelection(document.querySelector('.seat-btn[data-seat=\"A1\"]'))"),true);
    p.run('postVRPreviewState()');
    assert.deepEqual(JSON.parse(JSON.stringify(p.messages.at(-1).selectedSeats)),['A1']);
    p.listeners.message({origin:'http://localhost',source:p.elements['vr-inline-frame'].contentWindow,data:{type:'cinewave:toggle-seat',seatId:'A2'}});
    assert.equal(p.run('input.value'),'A1,A2');
    assert.equal(p.run('priceOut.textContent'),'₹350');
    assert.equal(p.run('classLine.textContent'),'1 × Class 0  ·  1 × Class 1');
    p.run("toggleTheaterView('2d')");
    assert.equal(p.seats[0].classes.has('seat-sel'),true);
    assert.equal(p.seats[1].classes.has('seat-sel'),true);
});

test('unavailable seats, party picks, maximum quantity and untrusted iframe messages cannot select',()=>{
    const p=booking();p.seats[0].disabled=true;p.seats[1].dataset.partyOwner='Friend';
    assert.equal(p.run("toggleSeatSelection(document.querySelector('.seat-btn[data-seat=\"A1\"]'))"),false);
    assert.equal(p.run("toggleSeatSelection(document.querySelector('.seat-btn[data-seat=\"A2\"]'))"),false);
    p.listeners.message({origin:'https://evil.invalid',source:p.elements['vr-inline-frame'].contentWindow,data:{type:'cinewave:toggle-seat',seatId:'A3'}});
    assert.equal(p.run('selected.size'),0);
    p.run("selected.set('A1',{});selected.set('A2',{})");
    assert.equal(p.run("toggleSeatSelection(document.querySelector('.seat-btn[data-seat=\"A3\"]'))"),false);
});

test('creating a party after page load starts one polling timer and sends authenticated canonical picks',async()=>{
    const p=booking();await p.run('initOrShowParty()');await new Promise(r=>setImmediate(r));
    assert.equal(p.timers.size,1);
    assert.equal(p.run('activePartyCode'),'ABC123');
    const sync=p.fetchCalls.find(c=>c.path.endsWith('/sync'));
    assert.ok(sync);assert.equal(sync.options.headers['X-Party-CSRF'],'fixture');
    assert.deepEqual(JSON.parse(sync.options.body).selected_seats,[]);
    p.run('resetParty()');assert.equal(p.timers.size,0);
});

test('a conflict response removes only conflicting picks and renders names as plain text',async()=>{
    const p=booking();p.run("activePartyCode='ABC123';selected.set('A1',{price:190,cls:'Premium'});selected.set('A2',{price:160,cls:'Premium'})");
    p.ctx.fetch=async()=>({ok:false,status:409,json:async()=>({error:'Seat conflict',conflicts:['A1'],members:[{user_name:'<img src=x onerror=evil()>',seats:['A1']}],squad_seats:{A1:{user_name:'Friend',color:'#3B82F6'}}})});
    await p.run('syncParty()');
    assert.deepEqual(p.json('[...selected.keys()]'),['A2']);
    assert.equal(p.run('input.value'),'A2');
    assert.equal(p.elements['squad-member-roster'].children[0].textContent.startsWith('<img'),true);
    assert.equal(p.seats[0].dataset.partyOwner,'Friend');
});
