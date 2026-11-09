const {test} = require('node:test');
const assert = require('node:assert/strict');
const {inspectMapping, classifySeat} = require('./static/js/seat-preview-state.js');
test('Non-Premium is standard; named premium and recliner rows retain their category',()=>{
    for(const className of ['First Class (Non-Premium)','Non Premium','Non_Premium'])
        assert.equal(classifySeat({className}),0);
    assert.equal(classifySeat({className:'First Class',classCode:'NONPREM'}),0);
    for(const className of ['Prime','Premium (Upper Balcony)','Gold','VIP'])
        assert.equal(classifySeat({className}),1);
    assert.equal(classifySeat({className:'Premium Recliner'}),2);
});
function fixture() {
    const batches = ['cushion','back','armrest'].map(kind => ({count:4,userData:{partKind:kind,instanceSeatIds:['A1','A1','B2','B2']}}));
    const seat = {id:'A1', row:'A', num:1, rowIndex:0, tier:'Standard',price:150,isOccupied:false,
        instanceParts:batches.flatMap(mesh=>[0,1].map(index=>({mesh,index})))};
    const registry = new Map([['A1',seat]]);
    const rows = [{seats:{A1:'available', B2:'available'}}];
    return {seat,batches,registry,rows,inspect(){return inspectMapping('A1',registry,batches,rows);}};
}
test('multiple components per seat are legitimate; every pair round-trips',()=>{
    const f=fixture(), before=JSON.stringify(f);
    const result=f.inspect(); assert.equal(result.mappingValid,true); assert.equal(result.instances.length,6);
    assert.equal(new Set(result.instances.map(i=>`${i.batch}:${i.index}`)).size,6);
    assert.ok(result.instances.every(i=>i.resolvedSeatId==='A1'));
    assert.equal(JSON.stringify(f),before);
});
test('unknown seat is explicitly missing',()=>{
    const f=fixture(); assert.deepEqual(inspectMapping('missing',f.registry,f.batches,f.rows).errors,['missing-seat']);
});
test('a known seat with no component mappings is rejected',()=>{
    const f=fixture();f.seat.instanceParts=[];f.batches.forEach(mesh=>{mesh.count=0;});
    assert.ok(f.inspect().errors.includes('missing-seat-components'));
});
test('duplicate reference within a seat is rejected',()=>{
    const f=fixture(); f.seat.instanceParts.push(f.seat.instanceParts[0]);
    assert.ok(f.inspect().errors.some(e=>e.startsWith('duplicate-reference')));
});
test('instance shared by two database seat IDs is rejected',()=>{
    const f=fixture(); f.registry.set('B2',{id:'B2',instanceParts:[f.seat.instanceParts[0]]});
    assert.ok(f.inspect().errors.includes('shared-instance:B2'));
});
test('reverse mapping to another seat is rejected',()=>{
    const f=fixture(); f.batches[0].userData.instanceSeatIds[0]='B2';
    assert.ok(f.inspect().errors.includes('wrong-seat:0:0'));
});
test('out-of-range instance is rejected',()=>{
    const f=fixture(); f.seat.instanceParts[0]={mesh:f.batches[0],index:99};
    assert.ok(f.inspect().errors.includes('missing-instance:0:99'));
});
test('unexpected extra reverse mapping is rejected',()=>{
    const f=fixture(); f.batches[0].userData.instanceSeatIds[3]='A1';
    assert.ok(f.inspect().errors.includes('unexpected-instance:0:3'));
});
test('database ID repeated across row definitions is rejected',()=>{
    const f=fixture(); f.rows.push({seats:{A1:'available'}});
    assert.ok(f.inspect().errors.includes('seat-id-occurrences:2'));
});
