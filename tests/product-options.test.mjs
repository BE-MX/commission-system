import test from 'node:test';
import assert from 'node:assert/strict';
import { initialVariants, option, validateVariants, normalizeCart, priceCart, minimumPrice } from '../app/lib/product-options.ts';

test('each hairstyle initially exposes only its documented original length',()=>{
  for(const length of [15,20,25,30,35,40,45]) assert.deepEqual([...new Set(initialVariants(`${length}厘米`).map(x=>x.length))],[length]);
});
test('short and long styles cannot acquire each other’s lengths even through a forged API body',()=>{
  assert.throws(()=>validateVariants([option('递针旋',40)],'15厘米'),/长度不能混用/);
  assert.throws(()=>validateVariants([option('递针旋',15)],'40厘米'),/长度不能混用/);
  assert.throws(()=>validateVariants([option('递针旋',35)],'25厘米'),/长度不能混用/);
});
test('approved cap-length prices match the supplied price chart without guessing missing prices',()=>{
  assert.equal(option('递针旋',20).price,1498);
  assert.equal(option('递针前顶',20).price,1798);
  assert.equal(option('递针分界',20).price,1598);
  assert.equal(option('递针旋',35).price,2050);
  assert.equal(option('递针旋',45).price,null);
  assert.equal(option('递针前顶',15).price,null);
  assert.equal(minimumPrice(initialVariants('45厘米')),null);
});
test('price validation rejects invalid numbers, accepts two decimals and rejects duplicate variants',()=>{
  for(const price of [-1,0,NaN,Infinity,1.001,'1198']) assert.throws(()=>validateVariants([{...option('递针旋',15),price}],'15厘米'));
  assert.equal(validateVariants([{...option('递针旋',15),price:10.01}],'15厘米')[0].price,10.01);
  assert.throws(()=>validateVariants([option('递针旋',15),option('递针旋',15)],'15厘米'));
});
test('cart distinguishes cap-length variants and consolidates duplicates without losing quantity',()=>{
  const a={id:1,variantKey:'cap0-20',quantity:2},b={id:1,variantKey:'cap1-20',quantity:1};
  const result=normalizeCart([a,b,a]);assert.equal(result.length,2);assert.equal(result[0].quantity,4);
  assert.throws(()=>normalizeCart([{id:1,quantity:1}]),/重新选择/);
  assert.throws(()=>normalizeCart([{...a,quantity:1.5}]));
});
test('server prices only the chosen variant and enforces shared product stock and manual account permissions',()=>{
  const product={id:1,name:'测试款',length:'20厘米',variants:initialVariants('20厘米'),stock:3,status:'active',minLevel:'retail'};
  const lines=[{id:1,variantKey:'cap0-20',quantity:2},{id:1,variantKey:'cap1-20',quantity:1}];
  const priced=priceCart([product],lines,'retail');assert.equal(priced[0].price,1498);assert.equal(priced[1].price,1798);
  assert.throws(()=>priceCart([product],[...lines,{...lines[0],quantity:1}],'retail'),/库存不足/);
  assert.throws(()=>priceCart([{...product,minLevel:'b'}],lines,'retail'),/无购买权限/);
  assert.throws(()=>priceCart([{...product,minLevel:'constructor'}],lines,'b'),/无购买权限/);
  assert.equal(priceCart([{...product,minLevel:'b'}],lines,'b').length,2);
  assert.throws(()=>priceCart([{...product,length:'45厘米',variants:initialVariants('45厘米')}],[{id:1,variantKey:'cap0-45',quantity:1}],'b'),/不可购买/);
});
