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

test('overview assets reduce triangles inside the full-detail component envelope',()=>{
 for(const kind of ['padding','backrest','armrest','cupHolder']){
  const near=assets[kind](THREE),far=assets[kind](THREE,'far');
  const triangles=g=>(g.index?g.index.count:g.attributes.position.count)/3;
  assert.ok(triangles(far)<triangles(near),kind);
  near.computeBoundingBox();far.computeBoundingBox();
  for(const axis of ['x','y','z']){
   assert.ok(far.boundingBox.min[axis]>=near.boundingBox.min[axis]-1e-5,kind);
   assert.ok(far.boundingBox.max[axis]<=near.boundingBox.max[axis]+1e-5,kind);
  }
 }
});

test('full-detail armrest has an open recessed cup position and a supporting top',()=>{
 const mesh=new THREE.Mesh(assets.armrest(THREE),new THREE.MeshBasicMaterial({side:THREE.DoubleSide}));
 mesh.updateMatrixWorld(true);
 const ray=x=>new THREE.Raycaster(new THREE.Vector3(x,3,-0.42),new THREE.Vector3(0,-1,0)).intersectObject(mesh);
 assert.equal(ray(0).length,0,'cup opening must pass through the padded arm');
 assert.ok(ray(0.9).length>0,'foam must remain beside the well');
});
