const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/pwa/app.js', 'utf8');
const helpers = source.slice(source.indexOf('let expenseConversion = null;'), source.indexOf('let expenseScanPreviewUrl = null;'));
const submit = source.slice(source.indexOf('async function submitExpense(event)'), source.indexOf("$('expenseScanCameraInput')?.addEventListener"));

function harness(currency = 'EUR', failRate = false) {
  const elements = Object.fromEntries(['expenseFormError', 'expenseAmount', 'expenseCurrency', 'expenseLabel',
    'expenseCategory', 'expenseChannel', 'expenseNote', 'expenseSubmitBtn', 'expenseConversionPreview']
    .map(id => [id, { value: '', textContent: '', hidden: true, disabled: false }]));
  Object.assign(elements.expenseAmount, { value: '31,70' });
  elements.expenseCurrency.value = currency;
  elements.expenseLabel.value = 'Ticket';
  elements.expenseChannel.value = 'cash';
  elements.expenseCategory.value = 'autre';
  const calls = [];
  const context = vm.createContext({
    $: id => elements[id], state: { currencyContext: { shop_currency: 'XOF' } },
    api: async (path, options) => {
      calls.push({ path, body: JSON.parse(options.body) });
      if (path.endsWith('/convert')) {
        if (failRate) throw Error('Taux indisponible');
        return { converted_amount: '20794', rate: '655.957', rate_date: '2026-10-12' };
      }
      return {};
    },
    clearExpenseScan() {}, closeExpenseForm() {}, loadExpenses() {}, loadHomeExpenseMetric() {}, toast() {},
  });
  vm.runInContext(helpers + submit, context);
  return { context, elements, calls, run: () => context.submitExpense({ preventDefault() {} }) };
}

(async () => {
  const foreign = harness();
  await foreign.run();
  assert.equal(foreign.calls.length, 1);
  assert.equal(foreign.calls[0].body.amount, '31.70');
  assert.match(foreign.elements.expenseConversionPreview.textContent, /31.70 EUR → 20794 XOF/);
  assert.equal(foreign.elements.expenseSubmitBtn.textContent, 'Confirmer la dépense convertie');
  await foreign.run();
  assert.equal(foreign.calls[1].path, '/pwa/expenses');
  assert.equal(foreign.calls[1].body.amount, '31.70');
  assert.equal(foreign.calls[1].body.source_currency, 'EUR');
  assert.equal(foreign.calls[1].body.expected_amount, '20794');

  const chinese = harness('CNY');
  await chinese.run();
  await chinese.run();
  assert.equal(chinese.calls[0].body.from_currency, 'CNY');
  assert.equal(chinese.calls[1].body.source_currency, 'CNY');

  const modified = harness();
  await modified.run();
  modified.elements.expenseAmount.value = '32,70';
  modified.context.resetExpenseConversion();
  await modified.run();
  assert.equal(modified.calls.length, 2);
  assert.ok(modified.calls.every(call => call.path.endsWith('/convert')));

  const offline = harness('EUR', true);
  await offline.run();
  assert.equal(offline.calls.length, 1);
  assert.match(offline.elements.expenseFormError.textContent, /Taux indisponible/);
  assert.equal(offline.elements.expenseSubmitBtn.disabled, false);

  const local = harness('XOF');
  local.elements.expenseAmount.value = '5 000';
  await local.run();
  assert.equal(local.calls[0].path, '/pwa/expenses');
  assert.equal(local.calls[0].body.amount, '5000');

  const invalid = harness();
  invalid.elements.expenseAmount.value = '1,234.56';
  await invalid.run();
  assert.equal(invalid.calls.length, 0);
  console.log('6 expense UI scenarios passed');
})().catch(error => { console.error(error); process.exit(1); });
