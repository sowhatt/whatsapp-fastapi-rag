/* Browser proof only: non-exportable P-256 private key in IndexedDB. No PIN/token storage. */
(() => {
  'use strict';
  const encode = value => btoa(String.fromCharCode(...new Uint8Array(value)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const decode = value => Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')
    .padEnd(Math.ceil(value.length / 4) * 4, '=')), c => c.charCodeAt(0));
  const supported = () => Boolean(isSecureContext && globalThis.crypto?.subtle && globalThis.indexedDB);
  async function storage(mode, operation) {
    const db = await new Promise((resolve, reject) => {
      const request = indexedDB.open('whatzabi-device-proof', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('keys', { keyPath: 'id' });
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(new Error('Stockage sécurisé indisponible. Utilisez votre mot de passe.'));
    });
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction('keys', mode);
        const request = operation(tx.objectStore('keys'));
        tx.oncomplete = () => resolve(request.result);
        tx.onerror = tx.onabort = () => reject(new Error('Impossible de mémoriser cet appareil.'));
      });
    } finally { db.close(); }
  }
  const saved = async () => (await storage('readonly', store => store.getAll())).filter(key => key.deviceId);
  const forget = id => storage('readwrite', store => store.delete(id));
  async function enroll(api, { password, pin, confirmation, name, merchant }) {
    if (!supported()) throw new Error('Utilisez votre mot de passe sur ce navigateur.');
    if (!/^[0-9]{6}$/.test(pin) || pin !== confirmation) throw new Error('Saisissez deux fois le même PIN de six chiffres.');
    const keys = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign', 'verify']);
    // Verify durable CryptoKey support before changing server state, without replacing
    // any already-enrolled key (the alternate implementation had only one slot).
    const probeId = 'pending-' + crypto.randomUUID();
    let privateKey;
    try {
      await storage('readwrite', store => store.put({ id: probeId, privateKey: keys.privateKey }));
      privateKey = (await storage('readonly', store => store.get(probeId))).privateKey;
      await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, privateKey, new Uint8Array(32));
    } finally { await forget(probeId); }
    const publicKey = encode(await crypto.subtle.exportKey('spki', keys.publicKey));
    const device = await api('/auth/quick/devices/enroll', { method: 'POST', body: JSON.stringify({
      password, device_name: name, public_key: publicKey,
    }) });
    try {
      const signature = encode(await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' },
        privateKey, decode(device.enrollment_message)));
      await api('/auth/quick/pin/setup', { method: 'POST', body: JSON.stringify({
        device_id: device.device_id, pin, confirmation, signature,
      }) });
      const entry = { id: device.device_handle, deviceId: device.device_id, privateKey,
        merchantId: merchant.id, userId: merchant.user_id, shopId: merchant.shop_id,
        name: name + ' — ' + (merchant.active_shop_name || merchant.shop_name) };
      await storage('readwrite', store => store.put(entry));
      return entry;
    } catch (error) {
      await api('/auth/quick/devices/revoke', { method: 'POST', body: JSON.stringify({
        device_id: device.device_id, password,
      }) }).catch(() => {});
      throw error;
    }
  }
  async function authenticate(api, id, pin) {
    const key = await storage('readonly', store => store.get(id));
    if (!key) throw new Error('Appareil inconnu. Connectez-vous avec votre mot de passe.');
    const challenge = await api('/auth/quick/pin/challenge', { method: 'POST',
      body: JSON.stringify({ device_handle: id }) });
    const signature = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, key.privateKey, decode(challenge.message));
    return api('/auth/quick/pin/unlock', { method: 'POST', body: JSON.stringify({
      challenge_id: challenge.challenge_id, signature: encode(signature), pin,
    }) });
  }
  function init({ api, identity, accept, logout }) {
    const $ = id => document.getElementById(id);
    let enabled = false;
    let busy = false;
    let revision = 0;
    async function choices() {
      const keys = supported() ? await saved().catch(() => []) : [];
      $('pinDevice').replaceChildren(...keys.map(key => {
        const option = document.createElement('option'); option.value = key.id; option.textContent = key.name; return option;
      }));
      $('pinLoginForm').hidden = !enabled || !keys.length;
    }
    async function update(globalEnabled) {
      enabled = globalEnabled;
      const current = ++revision;
      const merchant = identity();
      $('pinCard').hidden = true;
      await choices();
      if (!merchant?.user_id || !enabled) return;
      try {
        const status = await api('/auth/quick/status');
        if (current !== revision) return;
        $('pinCard').hidden = !status.enabled || !supported();
        $('passkeyCard').hidden = !status.enabled;
        if (!status.enabled || !supported()) return;
        const devices = await api('/auth/quick/devices');
        if (current !== revision) return;
        $('pinDeviceList').replaceChildren(...devices.map(device => {
          const item = document.createElement('li');
          item.append(document.createTextNode((device.name || 'Appareil') + ' '));
          const button = document.createElement('button'); button.type = 'button'; button.className = 'ghost'; button.textContent = 'Révoquer';
          button.onclick = () => action(async () => {
            if (!$('pinPassword').reportValidity()) return;
            const password = $('pinPassword').value;
            $('pinPassword').value = '';
            await api('/auth/quick/devices/revoke', { method: 'POST', body: JSON.stringify({ device_id: device.id, password }) });
            for (const key of await saved()) {
              if (key.deviceId === device.id && key.merchantId === merchant.id && key.userId === merchant.user_id) await forget(key.id);
            }
            $('pinStatus').textContent = 'Appareil révoqué.';
            await api('/auth/me');
            await update(enabled);
          });
          item.append(button); return item;
        }));
      } catch { if (current === revision) { $('pinCard').hidden = true; $('passkeyCard').hidden = true; } }
    }
    async function action(work, output = 'pinStatus') {
      if (busy) return;
      busy = true;
      $('pinCard').querySelectorAll('button').forEach(b => { b.disabled = true; });
      $('pinLoginForm').querySelector('button').disabled = true;
      $(output).textContent = '';
      try { await work(); }
      catch (error) { $(output).textContent = error.message || 'Utilisez votre mot de passe.'; }
      finally {
        busy = false;
        for (const id of ['pinPassword', 'pinSetup', 'pinConfirmation', 'pinLogin']) $(id).value = '';
        $('pinCard').querySelectorAll('button').forEach(b => { b.disabled = false; });
        $('pinLoginForm').querySelector('button').disabled = false;
      }
    }
    $('pinEnrollForm').onsubmit = event => {
      event.preventDefault();
      action(async () => {
        const input = { password: $('pinPassword').value, pin: $('pinSetup').value,
          confirmation: $('pinConfirmation').value, name: $('pinName').value.trim() || 'Mon appareil', merchant: identity() };
        for (const id of ['pinPassword', 'pinSetup', 'pinConfirmation']) $(id).value = '';
        await enroll(api, input);
        $('pinStatus').textContent = 'PIN enregistré pour cette boutique. Vous pouvez vous déconnecter puis utiliser votre PIN.';
        await update(enabled);
      });
    };
    $('pinLoginForm').onsubmit = event => {
      event.preventDefault();
      action(async () => {
        const pin = $('pinLogin').value; $('pinLogin').value = '';
        await accept(await authenticate(api, $('pinDevice').value, pin));
      }, 'loginError');
    };
    $('pinRecover').onclick = () => action(async () => {
      if (!$('pinPassword').reportValidity()) return;
      if (!confirm('Révoquer tous vos appareils PIN ? Votre mot de passe et vos Passkeys restent utilisables.')) return;
      const merchant = identity();
      const password = $('pinPassword').value; $('pinPassword').value = '';
      await api('/auth/quick/recover', { method: 'POST', body: JSON.stringify({ password }) });
      for (const key of await saved()) {
        if (key.merchantId === merchant.id && key.userId === merchant.user_id) await forget(key.id);
      }
      logout();
      $('loginError').textContent = 'Appareils PIN révoqués. Reconnectez-vous avec votre mot de passe pour définir un nouveau PIN.';
    });
    return { update, clear: () => {
      revision++;
      for (const id of ['pinPassword', 'pinSetup', 'pinConfirmation', 'pinLogin']) $(id).value = '';
      $('pinCard').hidden = true; $('pinDeviceList').replaceChildren();
    } };
  }
  globalThis.WhatzabiQuickAuth = Object.freeze({ supported, saved, forget, enroll, authenticate, init });
})();
