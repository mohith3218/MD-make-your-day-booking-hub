const {test}=require('node:test'),assert=require('node:assert/strict');
const THREE=require('./static/js/three-r128.min.js');
const assets=require('./static/js/cinema-seat-geometry.js');
test('shared chair assets have bounded triangles and finite normals/UVs',()=>{
 for(const [name,limit] of [['padding',168],['backrest',168]]){
  const g=assets[name](THREE);
  assert.ok(g.index.count/3<=limit);
  for(const attr of ['position','normal','uv'])assert.ok([...g.attributes[attr].array].every(Number.isFinite));
  g.computeBoundingBox();assert.ok(g.boundingBox.max.x>0.25&&g.boundingBox.min.x<-0.25);
 }
});
test('backrest is a closed indexed surface with outward faces and ergonomic depth',()=>{
 const g=assets.backrest(THREE),edges=new Map(),p=g.attributes.position;
 for(let i=0;i<g.index.count;i+=3){
  const t=[0,1,2].map(j=>g.index.getX(i+j));
  for(let j=0;j<3;j++){const key=[t[j],t[(j+1)%3]].sort((a,b)=>a-b).join(':');edges.set(key,(edges.get(key)||0)+1);}
 }
 assert.ok([...edges.values()].every(n=>n===2));
 const center=new THREE.Vector3(0,0.63,0.12);let volume=0;
 for(let i=0;i<g.index.count;i+=3){const [a,b,c]=[0,1,2].map(j=>new THREE.Vector3().fromBufferAttribute(p,g.index.getX(i+j)).sub(center));volume+=a.dot(b.clone().cross(c))/6;}
 assert.ok(volume>0,'winding must face outward');
 assert.ok(g.boundingBox.max.y>1.2&&g.boundingBox.max.z-g.boundingBox.min.z>0.15);
});
