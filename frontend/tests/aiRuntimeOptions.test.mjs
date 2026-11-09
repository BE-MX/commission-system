import test from 'node:test'
import assert from 'node:assert/strict'
import { nextTick, ref, effectScope } from 'vue'
import { useImageModelOptions } from '../src/views/design/image-studio/composables/useImageModelOptions.js'
const flush = async () => { await nextTick() }

test('studio takes configured defaults on model selection and preserves choices on same-model refresh', async t => {
 const scope = effectScope()
 t.after(() => scope.stop())
 const state = { config: ref({ models: [] }), model: ref(''), size: ref('1024x1024'), quality: ref('medium') }
 Object.assign(state, scope.run(() => useImageModelOptions(state.config, state.model, state.size, state.quality)))
 const first={id:'preset_a',available:true,sizes:['1024x1024','1536x1024'],qualities:['medium','high'],default_size:'1536x1024',default_quality:'high'}
 const second={id:'preset_b',available:true,sizes:['2048x2048'],qualities:['ultra'],default_size:'2048x2048',default_quality:'ultra'}
 state.config.value={models:[first,second]};state.model.value='preset_a';await flush()
 assert.equal(state.size.value,'1536x1024');assert.equal(state.quality.value,'high')
 state.size.value='1024x1024';state.quality.value='medium'
 state.config.value={models:[{...first},second]};await flush()
 assert.equal(state.size.value,'1024x1024');assert.equal(state.quality.value,'medium')
 state.model.value='preset_b';await flush()
 assert.deepEqual(state.modelSizes.value,['2048x2048']);assert.deepEqual(state.modelQualities.value,['ultra'])
 assert.equal(state.size.value,'2048x2048');assert.equal(state.quality.value,'ultra')
})
