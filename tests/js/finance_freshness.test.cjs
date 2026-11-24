const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const source=readFileSync('app/pwa/app.js','utf8');
function setup(){
  const pending=[],rendered=[],elements=new Map(),status=[];
  const scope={token:'token-A',state:{merchant:{id:1,shop_id:1},financePeriod:'month'},
    can:()=>true,toast(){},showTab(){},renderFinancePeriodButtons(){},console,
    $:id=>{if(!elements.has(id))elements.set(id,{textContent:'old'});return elements.get(id);},
    setFinanceStatus:(...args)=>status.push(args),renderFinanceOverview:data=>rendered.push(data),
    api:(path,options)=>new Promise((resolve,reject)=>pending.push({resolve,reject,path,options})),
  };
  vm.runInNewContext(source.slice(source.indexOf('let financeRequestId = 0;'),source.indexOf('\nfunction resetProductForm()')),scope);
  return {scope,pending,rendered,elements,status};
}
test('finance uses latest period only and clears outdated displayed amounts',async()=>{
  const ui=setup();
  const first=ui.scope.loadFinanceOverview('month');
  const second=ui.scope.loadFinanceOverview('all');
  assert.equal(ui.elements.get('financeRevenue').textContent,'—');
  assert.equal(ui.pending[0].options.cache,'no-store');
  ui.pending[1].resolve({period:'all',activity:{sales_total:36000}});await second;
  ui.pending[0].resolve({period:'month',activity:{sales_total:0}});await first;
  assert.equal(ui.rendered.length,1);assert.equal(ui.rendered[0].period,'all');
});
test('finance ignores success or failure from previous shop, including a switch back',async()=>{
  for(const fail of [false,true]){
    const ui=setup();const request=ui.scope.loadFinanceOverview('all');
    ui.scope.state.merchant.shop_id=2;ui.scope.invalidateFinanceOverview();
    ui.scope.state.merchant.shop_id=1;ui.scope.invalidateFinanceOverview();
    if(fail)ui.pending[0].reject(new Error('old shop error'));
    else ui.pending[0].resolve({activity:{sales_total:9999}});
    const before=ui.status.length;
    await request;
    assert.equal(ui.rendered.length,0);assert.equal(ui.status.length,before);
    assert.equal(ui.scope.state.finance,null);
  }
});
test('regular refresh after confirmed operations reloads an already opened Finance panel',async()=>{
  const calls=[];
  const scope={state:{finance:{activity:{sales_total:0}},financePeriod:'all'},
    loadContext:async()=>{},api:async()=>[],render(){},window:{},
    canReadExpenses:()=>false,renderExpenses(){},can:()=>true,
    loadFinanceOverview:async period=>calls.push(period),
  };
  vm.runInNewContext(source.slice(source.indexOf('async function refresh()'),source.indexOf('\nasync function boot()')),scope);
  await scope.refresh();assert.deepEqual(calls,['all']);
});
