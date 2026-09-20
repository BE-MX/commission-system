import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import ts from 'typescript';
const require = createRequire(import.meta.url);
const wranglerRequire = createRequire(require.resolve('wrangler/package.json'));
const { Miniflare } = wranglerRequire('miniflare');

test('real workerd streams completed R2 multipart to loopback with bounded length and retries', async () => {
  let received; let failed=false; const identities=[];
  const server=createServer(async(req,res)=>{
    if(req.headers['x-ark-storage-key']!=='test-only') {res.writeHead(403).end();return;}
    const chunks=[]; for await(const chunk of req) chunks.push(chunk);
    const body=Buffer.concat(chunks);
    assert.equal(Number(req.headers['x-ark-content-length']),body.length);
    identities.push(req.headers['x-ark-upload-id']);
    if(!failed){failed=true;res.writeHead(503).end();return;}
    received=body;res.setHeader('content-type','application/json');
    res.end(JSON.stringify({key:'test.psd',size:body.length,etag:'test',httpMetadata:{contentType:'application/octet-stream'},customMetadata:{sha256:createHash('sha256').update(body).digest('hex')}}));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const port=server.address().port;
  const source=ts.transpileModule(readFileSync(new URL('../lib/server/cos-files.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
  const mf=new Miniflare({compatibilityDate:'2026-05-15',compatibilityFlags:['nodejs_compat'],r2Buckets:['FILES'],
    modules:[{type:'ESModule',path:'worker.js',contents:`
      import {createCosFiles} from './cos-files.js';
      export default { async fetch(request,env) {
        const files=createCosFiles({endpoint:'http://127.0.0.1:8001/api/colorwork/storage',secret:'test-only',staging:env.FILES,
          fetcher:(url,init)=>{const target=new URL(url);target.port='${port}';return fetch(target,init);}});
        const url=new URL(request.url);
        if(url.pathname==='/init'){const upload=await files.createMultipartUpload('test.psd');return Response.json({id:upload.uploadId});}
        const upload=files.resumeMultipartUpload('test.psd',url.searchParams.get('id'));
        try {
          if(url.pathname==='/part')return Response.json(await upload.uploadPart(Number(url.searchParams.get('part')),await request.arrayBuffer()));
          return Response.json(await upload.complete(await request.json()));
        } catch(error){return Response.json({error:String(error)},{status:503});}
      }};`},{type:'ESModule',path:'cos-files.js',contents:source}],
  });
  try {
    const init=await mf.dispatchFetch('http://local/init');assert.equal(init.status,200);const{id}=await init.json();
    const first=Buffer.alloc(8*1024*1024,17),second=Buffer.alloc(1024*1024+13,33);const parts=[];
    for(const[index,body]of[first,second].entries()){
      const response=await mf.dispatchFetch('http://local/part?id='+encodeURIComponent(id)+'&part='+(index+1),{method:'PUT',body});
      assert.equal(response.status,200);parts.push(await response.json());
    }
    const complete=()=>mf.dispatchFetch('http://local/complete?id='+encodeURIComponent(id),{method:'POST',body:JSON.stringify(parts)});
    assert.equal((await complete()).status,503);
    const response=await complete();assert.equal(response.status,200,await response.clone().text());
    assert.equal((await response.json()).size,first.length+second.length);
    assert.equal(createHash('sha256').update(received).digest('hex'),createHash('sha256').update(first).update(second).digest('hex'));
    assert.equal(identities[0],identities[1]);
    assert.equal((await complete()).status,200);assert.equal(identities.length,2);
  } finally {await mf.dispose();await new Promise(resolve=>server.close(resolve));}
});
