/* Native WebAuthn transport. No biometric data, credential secrets or tokens persisted. */
(() => {
  'use strict';
  function decode(value) {
    const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
    const binary = atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, '='));
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  }
  function encode(value) {
    const bytes = new Uint8Array(value);
    let binary = '';
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function optionsFromJSON(options) {
    const result = { ...options, challenge: decode(options.challenge) };
    if (options.user) result.user = { ...options.user, id: decode(options.user.id) };
    for (const name of ['allowCredentials', 'excludeCredentials']) {
      if (options[name]) result[name] = options[name].map((item) => ({ ...item, id: decode(item.id) }));
    }
    return result;
  }
  function credentialToJSON(credential) {
    if (!credential) throw new Error('Aucune Passkey sélectionnée.');
    const response = {};
    for (const field of ['clientDataJSON', 'attestationObject', 'authenticatorData', 'signature', 'userHandle']) {
      if (field in credential.response) {
        response[field] = credential.response[field] === null ? null : encode(credential.response[field]);
      }
    }
    if (credential.response.getTransports) response.transports = credential.response.getTransports();
    return { id: credential.id, rawId: encode(credential.rawId), type: credential.type, response };
  }
  function supported() {
    return Boolean(globalThis.isSecureContext && globalThis.PublicKeyCredential && navigator.credentials);
  }
  function message(error) {
    if (error?.name === 'NotAllowedError' || error?.name === 'AbortError') {
      return 'Opération annulée ou délai dépassé. Vous pouvez réessayer ou utiliser votre mot de passe.';
    }
    if (error?.name === 'InvalidStateError') return 'Cette Passkey est déjà enregistrée.';
    if (error?.name === 'SecurityError') return 'Les Passkeys ne sont pas disponibles sur cette adresse.';
    return error?.message || 'Impossible de vérifier la Passkey. Utilisez votre mot de passe.';
  }
  async function register(api, password, name) {
    const ceremony = await api('/auth/passkeys/register/options', {
      method: 'POST', body: JSON.stringify({ password, name }),
    });
    const credential = await navigator.credentials.create({ publicKey: optionsFromJSON(ceremony.options) });
    return api('/auth/passkeys/register/verify', { method: 'POST', body: JSON.stringify({
      challenge_id: ceremony.challenge_id, credential: JSON.stringify(credentialToJSON(credential)),
    }) });
  }
  async function authenticate(api) {
    const ceremony = await api('/auth/passkeys/authenticate/options', { method: 'POST' });
    const credential = await navigator.credentials.get({ publicKey: optionsFromJSON(ceremony.options) });
    return api('/auth/passkeys/authenticate/verify', { method: 'POST', body: JSON.stringify({
      challenge_id: ceremony.challenge_id, credential: JSON.stringify(credentialToJSON(credential)),
    }) });
  }
  globalThis.WhatzabiPasskeys = Object.freeze({ supported, register, authenticate, message,
                                              optionsFromJSON, credentialToJSON });
})();
