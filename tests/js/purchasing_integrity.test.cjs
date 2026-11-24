const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {readFileSync}=require('node:fs');
const {webcrypto}=require('node:crypto');
const source=readFileSync('app/pwa/purchases.js','utf8');
class Element {
  constructor(){this.handlers={};this.value='';this.hidden=false;this.disabled=false;this.textContent='';this.options=[];}
  addEventListener(name,fn){(this.handlers[name] ||= []).push(fn);}
  async fire(name,extra={}){for(const fn of this.handlers[name]||[])await fn({target:this,preventDefault(){},...extra});}
  set innerHTML(value){this.html=value;this.options=[...value.matchAll(/<option value="([^"]*)"/g)].map(m=>({value:m[1]}));}
  get innerHTML(){return this.html||'';}
  focus(){}
}
async function setup(storage=new Map(),identity={}){
  const elements=new Map(), document=new Element(), calls=[], messages=[];
  const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  const supplier={id:7,name:'ABC',shop_id:1,debt:4000};
  const purchase={id:9,supplier_id:7,total_amount:5000,paid_amount:1000,remaining_amount:4000,status:'partial',due_date:'2026-11-10'};
  let handler=async(path,options)=>{
    if(options?.method==='POST')return {id:42};
    if(path==='/pwa/suppliers')return [supplier];
    if(path==='/pwa/purchases')return [purchase];
    if(path==='/pwa/products')return [{id:3,name:'Riz',stock:15,purchase_price:1000}];
    if(path.startsWith('/pwa/finance/'))return {payables:{total:3000}};
    throw new Error(path);
  };
  const sandbox={
    $:get,document,token:identity.token||'private-token',
    state:{merchant:{id:identity.merchant||1,shop_id:identity.shop||1},products:[{id:3,name:'Riz',stock:10,purchase_price:1000}],currencyContext:{shop_currency:'XOF'},financePeriod:'month'},
    can:()=>true,fmt:value=>String(value),esc:value=>String(value),fmtSaleDate:value=>value,fmtDueDate:value=>value||'—',
    render(){},renderFinanceOverview(value){sandbox.lastFinance=value;},showTab(){},toast:message=>messages.push(message),
    crypto:webcrypto,TextEncoder,AbortController,setTimeout,clearTimeout,
    sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    api:async(path,options)=>{calls.push({path,options});return handler(path,options);}
  };
  vm.runInNewContext(source.replace(/\}\)\(\);\s*$/,`globalThis.purchaseTest={loadPurchasingData,openSupplierPayment,showPurchasePayments,ready,cart:purchaseCart,inspect:()=>({pending,keys})};})();`),sandbox);
  await sandbox.purchaseTest.loadPurchasingData();
  async function cart(){
    get('purchaseProduct').value='3';get('purchaseQty').value='5';get('purchaseUnitCost').value='1000';
    await get('purchaseAddLineBtn').fire('click');
    get('purchaseSupplier').value='7';get('purchasePaidAmount').value='1000';get('purchaseDueDate').value='2026-11-10';get('purchasePaymentChannel').value='cash';
  }
  return {sandbox,get,calls,storage,document,cart,fetch(fn){handler=fn;},writes:()=>calls.filter(c=>c.options?.method==='POST')};
}

test('cash purchase without supplier, credit requires supplier and due date',async()=>{
  const ui=await setup();await ui.cart();
  assert.equal(ui.get('purchaseDetails').hidden,false);
  ui.get('purchaseSupplier').value='';
  await ui.get('purchaseSubmitBtn').fire('click');assert.equal(ui.writes().length,0);
  assert.match(ui.get('purchasingStatus').textContent,/fournisseur/);
  ui.get('purchasePaidAmount').value='5000';
  await ui.get('purchaseSubmitBtn').fire('click');
  const data=JSON.parse(ui.writes()[0].options.body);
  assert.equal(data.supplier_id,null);assert.equal(data.paid_amount,5000);assert.equal(data.due_date,null);
  assert.equal(data.shop_id,1);assert.match(data.idempotency_key,/^[a-f0-9-]{36}$/);
});

test('inline supplier creation keeps cart and selects newly created supplier',async()=>{
  const ui=await setup();await ui.cart();
  ui.get('purchaseQuickSupplierName').value='Nouveau';ui.get('purchaseQuickSupplierPhone').value='123';
  ui.fetch(async()=>({id:8,name:'Nouveau',shop_id:1,debt:0}));
  await ui.get('purchaseQuickSupplierBtn').fire('click');
  assert.equal(ui.sandbox.purchaseTest.cart.size,1);assert.equal(ui.get('purchaseSupplier').value,'8');
  assert.equal(ui.get('purchasePaidAmount').value,'1000');
  const data=JSON.parse(ui.writes()[0].options.body);assert.equal(data.name,'Nouveau');assert.equal(data.shop_id,1);
});

test('double click sends a single write; lost response replays exact payload and key',async()=>{
  const ui=await setup();await ui.cart();
  let reject;ui.fetch(()=>new Promise((_,r)=>{reject=r;}));
  const first=ui.get('purchaseSubmitBtn').fire('click');
  await Promise.resolve();await Promise.resolve();
  await ui.get('purchaseSubmitBtn').fire('click');assert.equal(ui.writes().length,1);
  reject(new TypeError('lost response'));await first;
  assert.equal(ui.sandbox.purchaseTest.cart.size,1);assert.equal(ui.get('purchasePaidAmount').disabled,true);
  const body=ui.writes()[0].options.body;
  ui.get('purchasePaidAmount').value='3000';
  ui.fetch(async(path,options)=>options?.method==='POST'?{id:42}:path.includes('finance')?{}:[]);
  await ui.get('purchaseSubmitBtn').fire('click');assert.equal(ui.writes()[1].options.body,body);
  assert.equal(ui.sandbox.purchaseTest.cart.size,0);
});

test('reload resumes exact uncertain purchase without storing the bearer token',async()=>{
  const ui=await setup();await ui.cart();ui.fetch(async()=>{throw new TypeError('network');});
  await ui.get('purchaseSubmitBtn').fire('click');
  const body=ui.writes()[0].options.body;
  assert.doesNotMatch([...ui.storage.values()][0],/private-token/);
  const reloaded=await setup(ui.storage);
  await reloaded.get('purchaseSubmitBtn').fire('click');
  assert.equal(reloaded.writes()[0].options.body,body);
});

test('definitive validation failure unlocks correction and retains same key',async()=>{
  const ui=await setup();await ui.cart();
  ui.fetch(async()=>{throw Object.assign(new Error('Échéance requise'),{status:400});});
  await ui.get('purchaseSubmitBtn').fire('click');
  assert.equal(ui.get('purchasePaidAmount').disabled,false);
  const first=JSON.parse(ui.writes()[0].options.body);
  ui.get('purchasePaidAmount').value='2000';
  await ui.get('purchaseSubmitBtn').fire('click');
  const second=JSON.parse(ui.writes()[1].options.body);
  assert.equal(first.idempotency_key,second.idempotency_key);assert.equal(second.paid_amount,2000);
});

test('payment replay preserves actual date and never refreshes stock',async()=>{
  const ui=await setup();ui.sandbox.purchaseTest.openSupplierPayment(9);
  ui.get('supplierPaymentAmount').value='1000';ui.get('supplierPaymentDate').value='2026-04-08T12:00';
  ui.fetch(async()=>{throw new TypeError('network');});
  await ui.get('supplierPaymentSubmitBtn').fire('click');
  const initial=ui.writes()[0].options.body;
  assert.equal(JSON.parse(initial).paid_at,new Date('2026-04-08T12:00').toISOString());
  ui.fetch(async(path,options)=>options?.method==='POST'?{id:43}:path.includes('finance')?{}:[]);
  await ui.get('supplierPaymentSubmitBtn').fire('click');
  assert.equal(ui.writes()[1].options.body,initial);
  assert.equal(ui.calls.filter(c=>c.path==='/pwa/products').length,0);
  assert.equal(ui.get('supplierPaymentSheet').hidden,true);
});

test('known success plus failed indicator refresh cannot resubmit purchase',async()=>{
  const ui=await setup();await ui.cart();
  ui.fetch(async(path,options)=>{if(options?.method==='POST')return {id:42};throw new Error('refresh failure');});
  await ui.get('purchaseSubmitBtn').fire('click');
  assert.equal(ui.sandbox.purchaseTest.cart.size,0);
  assert.match(ui.get('purchasingStatus').textContent,/enregistrée.*actualiser/);
  await ui.get('purchaseSubmitBtn').fire('click');assert.equal(ui.writes().length,1);
});

test('late reads and writes cannot apply to another shop or after a switch back',async()=>{
  for(const mode of ['read','write']){
    const ui=await setup();await ui.cart();const resolutions=[];let started;
    const awaiting=new Promise(r=>started=r);
    ui.fetch(()=>new Promise(r=>{resolutions.push(r);started();}));
    const work=mode==='read'?ui.sandbox.purchaseTest.loadPurchasingData():ui.get('purchaseSubmitBtn').fire('click');
    await awaiting;
    ui.sandbox.state.merchant.shop_id=2;
    ui.fetch(async()=>[]);ui.sandbox.render();
    ui.sandbox.state.merchant.shop_id=1;ui.sandbox.render();
    for(const resolve of resolutions) resolve(mode==='read'?[]:{id:42});
    await work;
    assert.equal(ui.sandbox.purchaseTest.cart.size,0);
    assert.doesNotMatch(ui.get('purchasingStatus').textContent,/#42 enregistré/);
  }
});

test('another merchant, shop or session cannot restore a purchase draft',async()=>{
  for(const identity of [{merchant:2},{shop:2},{token:'other-token'}]){
    const ui=await setup();await ui.cart();await ui.document.fire('input');
    const reloaded=await setup(ui.storage,identity);
    assert.equal(reloaded.sandbox.purchaseTest.cart.size,0);
  }
});

test('amount summary updates paid, due and required maturity',async()=>{
  const ui=await setup();await ui.cart();await ui.document.fire('input');
  assert.equal(ui.get('purchasePaidSummary').textContent,'1000');
  assert.equal(ui.get('purchaseRemaining').textContent,'4000');
  assert.equal(ui.get('purchaseDueDate').required,true);
});

test('inline supplier response loss preserves cart and retries identical creation',async()=>{
  const ui=await setup();await ui.cart();ui.get('purchaseQuickSupplierName').value='Nouveau';
  ui.fetch(async()=>{throw new TypeError('response lost');});
  await ui.get('purchaseQuickSupplierBtn').fire('click');
  const body=ui.writes()[0].options.body;
  assert.equal(ui.get('purchaseQuickSupplierName').disabled,true);
  assert.equal(ui.sandbox.purchaseTest.cart.size,1);
  ui.fetch(async()=>({id:8,name:'Nouveau',shop_id:1,debt:0}));
  await ui.get('purchaseQuickSupplierBtn').fire('click');
  assert.equal(ui.writes()[1].options.body,body);
  assert.equal(ui.get('purchaseSupplier').value,'8');
  assert.equal(ui.sandbox.purchaseTest.cart.size,1);
});

test('historical initial credit stays unknown; known credit and later payments remain distinct', async () => {
  const ui=await setup();
  assert.match(ui.get('purchaseList').innerHTML,/Crédit initial inconnu/);
  assert.match(ui.get('purchaseList').innerHTML,/Paiements ultérieurs non déterminables/);
  ui.fetch(async path => path==='/pwa/suppliers' ? [] : [{
    id:9,supplier_id:7,total_amount:5000,initial_paid_amount:1000,
    initial_credit_amount:4000,subsequent_paid_amount:1000,paid_amount:2000,
    remaining_amount:3000,status:'partial',created_at:'2026-04-07T10:00:00',
  }]);
  await ui.sandbox.purchaseTest.loadPurchasingData();
  const rendered=ui.get('purchaseList').innerHTML;
  assert.match(rendered,/Versement initial 1000 · Crédit initial 4000/);
  assert.match(rendered,/Paiements ultérieurs 1000/);
  assert.match(rendered,/Total payé 2000 · Reste dû 3000/);
  assert.match(rendered,/2026-04-07T10:00:00/);
});

test('purchase payment ledger preserves dates and rejects late cross-shop responses', async () => {
  const ui=await setup();
  ui.fetch(async()=>[
    {id:2,amount:1000,paid_at:'2026-04-08T10:00:00',channel:'cash'},
    {id:1,amount:1000,paid_at:'2026-04-07T10:00:00',channel:'cash'},
  ]);
  await ui.sandbox.purchaseTest.showPurchasePayments(9);
  const rendered=ui.get('purchasePayments-9').innerHTML;
  assert.match(rendered,/2026-04-07T10:00:00 · 1000 · cash/);
  assert.ok(rendered.indexOf('2026-04-07')<rendered.indexOf('2026-04-08'));
  let resolve;
  ui.fetch(()=>new Promise(r=>resolve=r));
  const pending=ui.sandbox.purchaseTest.showPurchasePayments(9);
  while(!resolve) await Promise.resolve();
  ui.sandbox.state.merchant.shop_id=2;
  resolve([{id:3,amount:9999,paid_at:'2026-04-09T10:00:00',channel:'cash'}]);
  await pending;
  assert.doesNotMatch(ui.get('purchasePayments-9').innerHTML,/9999/);
});
