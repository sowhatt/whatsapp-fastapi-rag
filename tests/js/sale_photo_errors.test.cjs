const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');

// Run the actual import UI in isolation; no dependency on Auth V2 or pilot data.
const source = readFileSync('app/pwa/app.js', 'utf8').split('// whatzabi-sale-photo-review-v1')[1];
const requestId = '8b560fd6-bdf6-44a8-9a66-ce4dd8e515ae';
const extraction = {
  merchant_id:1, draft_id:'11111111-1111-4111-8111-111111111111', expires_at:'2099-01-01T00:00:00Z',
  shop_id:1, source_sha256:'a'.repeat(64),
  result:{document_total:18000, daily_totals:[], document_date:'2026-04-07', currency:'XOF', warnings:[], lines:[{
    row_number:1, sale_date:'2026-04-07', description:'Riz', quantity:2, unit_price:9000,
    line_total:18000, paid_amount:18000, warnings:[], uncertain_fields:[]
  }]}
};
function response(status, body = null, headers = {}) {
  return {
    ok:status >= 200 && status < 300, status,
    headers:new Headers(headers),
    json:async () => {
      if (body === null) throw new SyntaxError('private proxy HTML');
      return body;
    }
  };
}
class Element {
  constructor() {
    this.handlers = {};
    this.children = new Map();
    this.value = '';
    this.hidden = false;
    this.textContent = '';
  }
  set innerHTML(value) {
    this.markup = value;
    // Minimal DOM parsing for row reconstruction during reload recovery.
    this.rows = [...value.matchAll(/<fieldset data-row="(\d+)">([\s\S]*?)<\/fieldset>/g)].map(match => {
      const row = new Element();
      row.dataset = {row:match[1]};
      for (const input of match[2].matchAll(/<(?:input|select) data-([a-z-]+)([^>]*)>/g)) {
        const field = row.querySelector('[data-' + input[1] + ']');
        field.value = input[2].match(/value="([^"]*)"/)?.[1] || '';
      }
      return row;
    });
  }
  get innerHTML() { return this.markup || ''; }
  remove() { this.removed = true; }
  addEventListener(name, callback) { this.handlers[name] = callback; }
  async fire(name, extra = {}) {
    return this.handlers[name]?.({target:this, preventDefault() {}, ...extra});
  }
  querySelector(selector) {
    if (!this.children.has(selector)) this.children.set(selector, new Element());
    return this.children.get(selector);
  }
  querySelectorAll(selector) {
    if (selector === '[data-row]') return (this.rows || []).filter(row => !row.removed);
    return [...this.children.values()];
  }
  setAttribute() {}
  removeAttribute() {}
  hasAttribute() { return false; }
  replaceChildren() { this.rows = []; this.innerHTML = ''; }
  reset() { this.resetCount = (this.resetCount || 0) + 1; }
  reportValidity() { return true; }
  showModal() { this.open = true; }
  close() { this.open = false; this.fire('close'); }
}
async function setup(storage = new Map(), identity = {}) {
  const dialog = new Element(), menu = new Element();
  const calls = [], timers = new Map();
  let fetchImpl = async () => response(200, extraction);
  let decodeImpl = async () => {};
  let outputBlob = new Blob(['jpeg'], {type:'image/jpeg'});
  const sandbox = {
    state:{merchant:{id:identity.merchant || 1, shop_id:identity.shop || 1}, products:[], customers:[]},
    token:identity.token || 'private-token', can:() => true, renderPermissions() {}, toast() {},
    logout() { throw new Error('Must not invoke global logout from photo request'); },
    refresh:async () => {}, AbortController, FormData, Headers, TypeError,
    TextEncoder, sessionStorage:{setItem:(key,value) => storage.set(key,value), getItem:key => storage.get(key), removeItem:key => storage.delete(key)},
    crypto:webcrypto, URL:{createObjectURL:() => 'blob:photo', revokeObjectURL() {}},
    Image:class { width = 100; height = 100; decode() { return decodeImpl(); } },
    setTimeout(callback) { const id = Symbol(); timers.set(id, callback); return id; },
    clearTimeout(id) { timers.delete(id); },
    document:{
      getElementById:() => menu, body:{appendChild() {}},
      createElement:tag => tag === 'dialog' ? dialog : {
        getContext:() => ({fillRect() {}, drawImage() {}}),
        toBlob:callback => callback(outputBlob)
      }
    },
    fetch:async (...args) => { calls.push(args); return fetchImpl(...args); }
  };
  // Expose only local helpers for assertions; listeners use unmodified production code.
  vm.runInNewContext(source.replace(/\}\)\(\);\s*$/, `
    globalThis.photoTest = {request, convert};
  })();`), sandbox);
  await menu.fire('click');
  const get = name => dialog.querySelector('[data-' + name + ']');
  async function select(file = {type:'image/jpeg', size:100}) {
    get('gallery-input').files = [file];
    await get('gallery-input').fire('change');
  }
  async function draft() {
    await select();
    const row = new Element();
    row.dataset = {row:'0'};
    for (const [name, value] of Object.entries({
      'sale-date':'2026-04-07', product:7, quantity:2, price:9000, 'line-total':18000, paid:18000,
      channel:'cash', customer:''
    })) row.querySelector('[data-' + name + ']').value = String(value);
    get('lines').rows = [row];
    get('group').value = 'rows';
    get('stock').value = 'deduct';
    get('stock-reason').value = 'Registre non décompté du stock actuel.';
    get('confirm').checked = true;
    return row;
  }
  return {
    sandbox, dialog, menu, get, calls, timers, select, draft, storage,
    fetch(fn) { fetchImpl = fn; },
    decode(fn) { decodeImpl = fn; },
    blob(value) { outputBlob = value; }
  };
}

for (const [status, code] of [
  [401, 'authentication_required'], [413, 'photo_too_large'],
  [415, 'unsupported_photo'], [422, 'validation_error'],
  [503, 'service_unavailable'], [504, 'timeout'], [500, 'http_error']
]) {
  for (const body of [null, {detail:'secret customer / raw server error'}]) {
    test(`HTTP ${status}, ${body ? 'JSON' : 'HTML/empty'}: safe message and draft retained`, async () => {
      const ui = await setup();
      const row = await ui.draft();
      ui.fetch(async () => response(status, body, {'X-Request-ID':requestId}));
      await assert.rejects(ui.sandbox.photoTest.request('/test', {}), error => {
        assert.equal(error.code, code);
        assert.equal(error.status, status);
        assert.equal(error.requestId, requestId);
        return true;
      });
      await ui.get('review').fire('submit');
      assert.equal(ui.get('lines').rows[0], row);
      assert.equal(row.querySelector('[data-price]').value, '9000');
      assert.equal(ui.get('review').hidden, false);
      assert.match(ui.get('status').textContent, /brouillon.*conservé/);
      assert.match(ui.get('status').textContent, new RegExp(requestId));
      assert.doesNotMatch(ui.get('status').textContent, /secret|Load failed|private/);
      ui.dialog.close();
      await ui.menu.fire('click');
      assert.equal(ui.get('lines').rows[0], row);
      assert.equal(ui.timers.size, 0);
    });
  }
}

test('network failure preserves exact confirmation payload for retry', async () => {
  const ui = await setup();
  const row = await ui.draft();
  ui.fetch(async () => { throw new TypeError('Load failed'); });
  await ui.get('review').fire('submit');
  assert.match(ui.get('status').textContent, /Connexion interrompue/);
  assert.doesNotMatch(ui.get('status').textContent, /Load failed/);
  assert.equal(ui.get('lines').rows[0], row);
  const first = ui.calls.at(-1)[1];
  ui.fetch(async () => response(200, {sale_ids:[1], already_imported:true}));
  await ui.get('review').fire('submit');
  assert.equal(ui.calls.at(-1)[1].body, first.body);
  assert.notEqual(ui.calls.at(-1)[1].headers['X-Request-ID'], first.headers['X-Request-ID']);
  assert.match(ui.get('status').textContent, /Aucun doublon/);
  assert.equal(ui.get('review').hidden, true);
});

test('timeout differs from network loss and releases controls', async () => {
  const ui = await setup();
  const row = await ui.draft();
  ui.fetch((path, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('private', 'AbortError')));
  }));
  const submission = ui.get('review').fire('submit');
  for (const timer of ui.timers.values()) timer();
  await submission;
  assert.match(ui.get('status').textContent, /délai de réponse/);
  assert.equal(ui.get('lines').rows[0], row);
  assert.equal(ui.get('confirm').disabled, true);
  assert.equal(ui.timers.size, 0);
});

test('failed extraction can retry the retained photo without selecting it again', async () => {
  const ui = await setup();
  ui.fetch(async () => { throw new TypeError('Load failed'); });
  await ui.select();
  const blob = ui.calls.at(-1)[1].body.get('image');
  assert.equal(ui.get('retry').hidden, false);
  await ui.select({type:'image/heic', size:100});
  assert.equal(ui.get('retry').hidden, false);
  ui.dialog.close();
  await ui.menu.fire('click');
  ui.fetch(async () => response(200, extraction));
  await ui.get('retry').fire('click');
  assert.equal(await ui.calls.at(-1)[1].body.get('image').text(), await blob.text());
  assert.equal(ui.get('review').hidden, false);
  assert.equal(ui.get('retry').hidden, true);
});

test('failed replacement and invalid JSON never discard corrections', async () => {
  const ui = await setup();
  const row = await ui.draft();
  for (const result of [
    response(503), response(200), response(200, {}),
    response(200, {...extraction, result:{warnings:[], lines:[null]}})
  ]) {
    ui.fetch(async () => result);
    await ui.select();
    assert.equal(ui.get('lines').rows[0], row);
    assert.equal(ui.get('review').hidden, false);
  }
});

test('incomplete success response cannot erase a confirmation draft', async () => {
  const ui = await setup();
  const row = await ui.draft();
  ui.fetch(async () => response(200, {sale_ids:[]}));
  await ui.get('review').fire('submit');
  assert.equal(ui.get('lines').rows[0], row);
  assert.match(ui.get('status').textContent, /incomplète/);
});

test('network loss during response body read is classified as network failure', async () => {
  const ui = await setup();
  ui.fetch(async () => ({
    ...response(200), json:async () => { throw new TypeError('Load failed'); }
  }));
  await assert.rejects(ui.sandbox.photoTest.request('/test', {}), {code:'network'});
});

test('session or shop change clears even a closed draft', async () => {
  for (const field of ['shop', 'token']) {
    const ui = await setup();
    await ui.draft();
    ui.dialog.close();
    if (field === 'shop') ui.sandbox.state.merchant.shop_id = 2;
    else ui.sandbox.token = 'new-token';
    ui.sandbox.renderPermissions();
    assert.equal(ui.get('lines').rows.length, 0);
    assert.equal(ui.get('review').hidden, true);
  }
});

test('untrusted server request ID cannot be shown as personal data', async () => {
  const ui = await setup();
  ui.fetch(async () => response(503, null, {'X-Request-ID':'secret customer name'}));
  await assert.rejects(ui.sandbox.photoTest.request('/test', {}), error => {
    assert.equal(error.requestId, ui.calls.at(-1)[1].headers['X-Request-ID']);
    assert.doesNotMatch(error.requestId, /secret/);
    return true;
  });
});

test('photo format, empty file, source and compressed size limits', async () => {
  const ui = await setup();
  const convert = ui.sandbox.photoTest.convert;
  for (const type of ['image/heic', 'image/gif', 'image/svg+xml', 'text/plain', '']) {
    await assert.rejects(convert({type, size:1}), {code:'unsupported_photo'});
  }
  await assert.rejects(convert({type:'image/jpeg', size:0}), {code:'empty_photo'});
  await assert.rejects(convert({type:'image/jpeg', size:20 * 1024 ** 2 + 1}), {code:'photo_too_large'});
  for (const type of ['image/jpeg', 'image/png', 'image/webp']) {
    await convert({type, size:20 * 1024 ** 2});
  }
  ui.blob({size:12 * 1024 ** 2});
  await convert({type:'image/jpeg', size:100});
  ui.blob({size:12 * 1024 ** 2 + 1});
  await assert.rejects(convert({type:'image/jpeg', size:100}), {code:'photo_too_large'});
  ui.decode(async () => { throw new Error('Load failed'); });
  await assert.rejects(convert({type:'image/jpeg', size:100}), error => {
    assert.equal(error.code, 'unsupported_photo');
    assert.doesNotMatch(error.message, /Load failed/);
    return true;
  });
});


test('multi-day review sends original date of each line and declared total', async () => {
  const ui = await setup();
  const row = await ui.draft();
  row.querySelector('[data-sale-date]').value = '2026-04-08';
  ui.fetch(async () => response(409, {error:{code:'business_duplicate'}}));
  await ui.get('review').fire('submit');
  const data = JSON.parse(ui.calls.at(-1)[1].body);
  assert.equal(data.rows[0].sale_date, '2026-04-08');
  assert.equal(data.document_total, 18000);
  assert.equal(data.draft_id, extraction.draft_id);
  assert.match(ui.get('status').textContent, /similaires/);
  assert.equal(ui.get('confirm').disabled, false);
});

test('late analysis cannot affect a different shop, including a switch back', async () => {
  for (const switchBack of [false, true]) {
    const ui = await setup();
    let resolve;
    const started = new Promise(done => {
      ui.fetch(() => new Promise(finish => { resolve = finish; done(); }));
    });
    const analysis = ui.select();
    await started;
    ui.sandbox.state.merchant.shop_id = 2;
    ui.sandbox.renderPermissions();
    if (switchBack) {
      ui.sandbox.state.merchant.shop_id = 1;
      ui.sandbox.renderPermissions();
    }
    resolve(response(200, extraction));
    await analysis;
    assert.equal(ui.get('review').hidden, true);
    assert.equal(ui.get('lines').querySelectorAll('[data-row]').length, 0);
    assert.equal(ui.storage.size, 0);
  }
});

test('reload restores corrected fields in the same session without a photograph or bearer token', async () => {
  const ui = await setup();
  const row = await ui.draft();
  row.querySelector('[data-price]').value = '8500';
  row.querySelector('[data-line-total]').value = '17000';
  row.querySelector('[data-paid]').value = '17000';
  ui.get('total-reason').value = 'Erreur de total vérifiée sur le papier.';
  await ui.get('review').fire('input');
  const stored = [...ui.storage.values()][0];
  assert.doesNotMatch(stored, /private-token|data:image|blob:photo/);
  const reloaded = await setup(ui.storage);
  const restored = reloaded.get('lines').querySelectorAll('[data-row]')[0];
  assert.equal(restored.querySelector('[data-price]').value, '8500');
  assert.equal(restored.querySelector('[data-sale-date]').value, '2026-04-07');
  assert.equal(reloaded.get('total-reason').value, 'Erreur de total vérifiée sur le papier.');
  assert.equal(reloaded.get('confirm').checked, false);
  assert.equal(reloaded.calls.length, 0);
});

test('reload cannot restore another merchant, shop, session or expired draft', async () => {
  for (const identity of [{merchant:2}, {shop:2}, {token:'another-token'}, {expired:true}]) {
    const ui = await setup();
    await ui.draft();
    await ui.get('review').fire('input');
    if (identity.expired) {
      const key = [...ui.storage.keys()][0];
      const saved = JSON.parse(ui.storage.get(key));
      saved.extraction.expires_at = '2000-01-01T00:00:00Z';
      ui.storage.set(key, JSON.stringify(saved));
    }
    const reloaded = await setup(ui.storage, identity);
    assert.equal(reloaded.get('lines').querySelectorAll('[data-row]').length, 0);
    assert.equal(ui.storage.size, 0);
  }
});

test('lost response plus reload retries the exact frozen payload and removes recovery on success', async () => {
  const ui = await setup();
  await ui.draft();
  ui.fetch(async () => { throw new TypeError('network lost after commit'); });
  await ui.get('review').fire('submit');
  const initial = ui.calls.at(-1)[1].body;
  const reloaded = await setup(ui.storage);
  reloaded.fetch(async () => response(200, {sale_ids:[42], already_imported:true}));
  await reloaded.get('review').fire('submit');
  assert.equal(reloaded.calls.at(-1)[1].body, initial);
  assert.equal(ui.storage.size, 0);
  assert.match(reloaded.get('status').textContent, /Aucun doublon/);
});

test('business reconciliation error allows correction and preserves the draft', async () => {
  const ui = await setup();
  const row = await ui.draft();
  ui.fetch(async () => response(409, {error:{code:'total_reconciliation', message:'secret raw OCR'}}));
  await ui.get('review').fire('submit');
  assert.match(ui.get('status').textContent, /justification/);
  assert.doesNotMatch(ui.get('status').textContent, /secret/);
  assert.equal(ui.get('lines').rows[0], row);
  assert.equal(ui.get('confirm').disabled, false);
  ui.get('total-reason').value = 'Le total manuscrit est incorrect après vérification.';
  ui.fetch(async () => response(200, {sale_ids:[1], already_imported:false}));
  await ui.get('review').fire('submit');
  assert.equal(JSON.parse(ui.calls.at(-1)[1].body).total_justification, ui.get('total-reason').value);
});
