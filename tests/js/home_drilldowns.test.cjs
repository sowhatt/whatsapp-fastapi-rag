const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {readFileSync} = require('node:fs');
const source = readFileSync('app/pwa/app.js', 'utf8');
const html = readFileSync('app/pwa/index.html', 'utf8');

test('stock card opens Stock 360 using the production click handler', () => {
  const markup = html.match(/<button\b[^>]*id="statLowStockCard"[^>]*>/)[0];
  const dataset = Object.fromEntries([...markup.matchAll(/data-([\w-]+)="([^"]+)"/g)]
    .map(([, key, value]) => [key.replace(/-([a-z])/g, (_, c) => c.toUpperCase()), value]));
  const handlers = {}, opened = [];
  const button = {dataset, addEventListener: (name, handler) => handlers[name] = handler};
  const start = source.indexOf("document.querySelectorAll('[data-open-tab]')");
  const end = source.indexOf('\n);', start) + 3;
  vm.runInNewContext(source.slice(start, end), {
    document: {querySelectorAll: () => [button]},
    showTab: tab => opened.push(tab), $: () => null,
    requestAnimationFrame: callback => callback(),
  });
  handlers.click();
  assert.deepEqual(opened, ['stockIntelligence']);
  assert.match(html, /id="stockIntelligence"/);
});

test('critical stock includes zero and negative stock even without a threshold', () => {
  const products = [
    {name:'Zero', stock:0, threshold:0}, {name:'Negative', stock:-1, threshold:0},
    {name:'Low', stock:2, threshold:3}, {name:'At threshold', stock:3, threshold:3},
    {name:'No threshold', stock:1, threshold:0}, {name:'Healthy', stock:4, threshold:3},
  ];
  const start = source.indexOf('  const lowStockProducts = products.filter(');
  const end = source.indexOf('\n  });', start) + 6;
  const context = {products};
  vm.runInNewContext(source.slice(start, end) + '\nglobalThis.names = lowStockProducts.map(p => p.name);', context);
  assert.deepEqual(Array.from(context.names), ['Zero','Negative','Low','At threshold']);
});
