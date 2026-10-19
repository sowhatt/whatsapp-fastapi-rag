// Run with the existing Node runtime, without dependencies or a frontend build chain.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const handlers = {}, cached = [], notices = [], opened = [], deleted = [];
const context = {
  URL, self:{location:{origin:'https://example.test'}, addEventListener:(name, fn) => handlers[name]=fn,
    skipWaiting:async()=>{}, clients:{claim:async()=>{},openWindow:async url=>opened.push(url)},
    registration:{showNotification:async(...args)=>notices.push(args)}},
  caches:{open:async()=>({addAll:async paths=>cached.push(...paths),match:async path=>({path})}),
    match:async path=>({path}),keys:async()=>['whatzabi-merchant-shell-v0','other-app-cache'],delete:async key=>deleted.push(key)},
  fetch:async()=>{throw new Error('offline');}
};
vm.runInNewContext(fs.readFileSync('app/merchant_pwa/service-worker.js','utf8'),context);
(async()=>{
  let task;
  handlers.install({waitUntil:p=>task=p}); await task;
  assert(cached.length > 10);
  assert(cached.every(path => path.startsWith('/merchant/assets/') || path === '/merchant/manifest.webmanifest'));
  handlers.activate({waitUntil:p=>task=p}); await task;
  assert.deepEqual(deleted,['whatzabi-merchant-shell-v0']);
  for(const path of ['/merchant-api/bootstrap','/merchant-api/orders','/merchant-api/notifications','/merchant-api/push/config','/merchant-api/push-subscriptions','/online-admin/merchants/1/orders','/shop/demo/order/WO-1?phone=123','/merchant/assets/app.js?token=private','/online-admin-sw.js']){
    let handled=false;
    handlers.fetch({request:{url:'https://example.test'+path,method:'GET',mode:'cors'},respondWith:()=>handled=true});
    assert.equal(handled,false,path);
  }
  let response;
  handlers.fetch({request:{url:'https://example.test/merchant/orders?order_id=42',method:'GET',mode:'navigate'},respondWith:p=>response=p});
  assert.equal((await response).path,'/merchant/assets/index.html');
  assert(!cached.some(p=>p.includes('?')));
  for(const url of ['/online-admin-ui#order-42','https://evil.test/steal','javascript:alert(1)']){
    handlers.push({data:{json:()=>({url,title:'PRIVATE',body:'PRIVATE'})},waitUntil:p=>task=p}); await task;
    const notice = notices.at(-1);
    assert(!JSON.stringify(notice).includes('PRIVATE'));
    handlers.notificationclick({notification:{data:notice[1].data,close:()=>{}},waitUntil:p=>task=p}); await task;
  }
  assert.deepEqual(opened,['/merchant/orders?order_id=42','/merchant/notifications','/merchant/notifications']);
  console.log('Service worker: cache, API exclusion, offline and Push deep links PASS');
})().catch(error=>{console.error(error);process.exitCode=1});
