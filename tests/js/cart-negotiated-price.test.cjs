const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup() {
  const handlers = {}, elements = {}, requests = [], messages = [];
  const element = id => elements[id] ||= {options:[],value:'',innerHTML:'',textContent:'',addEventListener(name, fn){this[name]=fn},focus(){},select(){}};
  element('expressChannel').value = 'cash';
  const product = {id:1,name:'Café',price:2500,stock:20};
  const context = {window:{},document:{addEventListener(name,fn){handlers[name]=fn},querySelectorAll(){return []}},
    $:element, state:{products:[product],customers:[]},fmt:n=>`${n} FCFA`,esc:s=>s,
    toast:s=>messages.push(s),render(){},refresh:async()=>{},showTab(){},
    localStorage:{getItem(){return null}},api:async(url,options)=>{requests.push({url,options});return []}};
  vm.runInNewContext(fs.readFileSync('app/pwa/express-sale.js','utf8'),context);
  function click(selector,dataset={}) {
    handlers.click({target:{closest:s=>s===selector?{dataset}:null}});
  }
  function price(value) {
    handlers.submit({preventDefault(){},target:{closest:s=>s==='[data-price-form]'?{dataset:{priceForm:'1'},elements:{unitPrice:{value}}}:null}});
  }
  return {context,product,element,click,price,requests,messages};
}

test('negotiated price recalculates totals, survives click and voice quantity additions, and reaches checkout',async()=>{
  const s=setup();
  s.click('[data-add-product]',{addProduct:'1'});
  assert.match(s.element('expressCart').innerHTML,/Modifier le prix/);
  s.click('[data-price-edit]',{priceEdit:'1'});
  s.price('2200');
  assert.equal(s.element('expressTotal').textContent,'2200 FCFA');
  assert.equal(s.product.price,2500);
  s.click('[data-add-product]',{addProduct:'1'});
  s.context.window.whatzabiExpressAddVoiceLines([{product_id:1,quantity:1}]);
  assert.equal(s.element('expressTotal').textContent,'6600 FCFA');
  await s.element('expressCheckout').click();
  const payload=JSON.parse(s.requests.find(r=>r.options?.method === 'POST').options.body);
  assert.deepEqual(payload.items,[{product_id:1,quantity:3,unit_price:2200}]);
  assert.equal(payload.paid_amount,6600);
});

test('invalid prices and cancellation preserve price; reset restores catalogue price',()=>{
  const s=setup();
  s.click('[data-add-product]',{addProduct:'1'});
  for(const value of ['', '0','-1','2.5','NaN','9007199254740992']) s.price(value);
  assert.equal(s.messages.length,6);
  assert.equal(s.element('expressTotal').textContent,'2500 FCFA');
  s.click('[data-price-edit]',{priceEdit:'1'});
  s.click('[data-price-cancel]');
  assert.equal(s.element('expressTotal').textContent,'2500 FCFA');
  s.price('2200');
  s.click('[data-cart-plus]',{cartPlus:'1'});
  assert.equal(s.element('expressTotal').textContent,'4400 FCFA');
  s.click('[data-price-reset]',{priceReset:'1'});
  assert.equal(s.element('expressTotal').textContent,'5000 FCFA');
});

test('removing a negotiated line and adding it again starts at catalogue price',()=>{
  const s=setup();
  s.click('[data-add-product]',{addProduct:'1'});
  s.price('2200');
  s.click('[data-cart-minus]',{cartMinus:'1'});
  s.click('[data-add-product]',{addProduct:'1'});
  assert.equal(s.element('expressTotal').textContent,'2500 FCFA');
});
