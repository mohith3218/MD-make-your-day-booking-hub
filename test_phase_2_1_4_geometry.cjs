// Integration assertions over genuine browser output; regenerate via the
// Phase 2.1.4 browser runner before using these as a renderer regression gate.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base='docs/screenshots/phase-2.1.4-premium-seats/';
const read=name=>JSON.parse(fs.readFileSync(base+name,'utf8'));
test('all drawn chair components resolve to real canonical seat IDs',()=>{
 const screens=read('integrity.json');assert.equal(screens.length,5);
 for(const screen of screens){assert.ok(screen.integrity.checked>0);assert.deepEqual(screen.integrity.errors,[]);}
 assert.equal(screens.find(s=>s.key==='jagadamba').integrity.checked,886);
});
test('couple seating has two pans, two backs and two headrests under one original ID',()=>{
 const seat=read('after.json').find(s=>s.key==='couple').couple;
 assert.ok(seat.mappingValid);
 for(const kind of ['cushion','back','headrest'])assert.equal(seat.instances.filter(p=>p.kind===kind).length,2);
 assert.ok(seat.instances.every(p=>p.resolvedSeatId===seat.seatId));
});
test('recliner back, attached headrest and footrest respond to all three controls',()=>{
 const motion=read('after.json').find(s=>s.key==='recliner').motion;
 assert.equal(motion.length,3);
 for(let i=0;i<3;i++){
  const back=motion[i].find(p=>p.kind==='back'),head=motion[i].find(p=>p.kind==='headrest');
  assert.ok(Math.abs(back.angle - [8,25,45][i]*Math.PI/180)<1e-8);
  assert.equal(head.angle,back.angle);
 }
 const first=motion[0].find(p=>p.kind==='footrest'),last=motion[2].find(p=>p.kind==='footrest');
 assert.ok(last.position[1]>first.position[1]);assert.ok(last.position[2]<first.position[2]);
 assert.ok(Math.abs(last.position[2])<=0.46+1e-8);
});

test('booked and held have different markers; deselection restores category upholstery exactly',()=>{
 const colors=read('after.json').find(s=>s.key==='inox').stateColors;
 assert.equal(colors.booked.status,'booked');assert.equal(colors.held.status,'held');
 assert.notDeepEqual(colors.booked.color,colors.held.color);
 assert.notDeepEqual(colors.selectedMarker.color,colors.booked.color);
 assert.deepEqual(colors.restored,colors.category.map(Math.fround));
 assert.notDeepEqual(colors.selectedUpholstery,colors.restored);
 for(const state of [colors.booked,colors.held,colors.selectedMarker])assert.ok(state.mapping.mappingValid);
});

test('all required auditoriums render under Showtime, Preshow and House lighting',()=>{
 for(const key of ['melody','inox','jagadamba']){
  const record=read('after.json').find(s=>s.key===key);
  assert.deepEqual(record.lighting.map(l=>l.mode),['movie','preshow','house']);
  for(const {metrics} of record.lighting){assert.ok(metrics.averageFps>0);assert.ok(metrics.sceneUsableMs>0);}
 }
});
