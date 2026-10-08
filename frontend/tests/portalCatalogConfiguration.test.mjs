import test from 'node:test'
import assert from 'node:assert/strict'
import { catalogConfiguration, sourceIdentity } from '../src/views/portal/catalogConfiguration.mjs'
const form=()=>({display_name:'Straight',color_name:'Black',inventory_unit:'g',sale_unit:'pack',conversion_factor:'20.000001',safety_buffer:'0',min_qty:2,step_qty:2,reason:'Verified',status:'published',product_id:'101'})
test('configuration preserves decimal text and omits source and status fields',()=>{const b=catalogConfiguration(form());assert.equal(b.conversion_factor,'20.000001');assert.equal('product_id' in b,false);assert.equal('status' in b,false)})
test('units and conversion require explicit inputs',()=>{for(const change of [{inventory_unit:''},{sale_unit:''},{conversion_factor:'0'},{conversion_factor:'1e2'},{safety_buffer:'-1'},{min_qty:3},{step_qty:0}])assert.throws(()=>catalogConfiguration({...form(),...change}))})
test('source identities preserve large integer strings and reject noncanonical values',()=>{assert.equal(sourceIdentity({product_id:'9007199254740993',sku_id:'201',product_kind:'hair'}).product_id,'9007199254740993');for(const product_id of ['0101','0','1.0','9223372036854775808'])assert.throws(()=>sourceIdentity({product_id,sku_id:'201',product_kind:'hair'}))})
