export async function api(path, options = {}) {
  if (!navigator.onLine) throw new Error('Vous êtes hors ligne. Reconnectez-vous pour consulter ou modifier vos données.');
  let response;
  try {
    response = await fetch(`/merchant-api${path}`, {credentials:'same-origin', cache:'no-store', ...options,
      headers:{'Content-Type':'application/json', 'X-Merchant-Request':'1', ...options.headers}});
  } catch { throw new Error('Connexion impossible. Vérifiez votre réseau puis réessayez.'); }
  if (!response.ok) {
    const error = new Error(response.status === 403 ? 'Ce module n’est pas disponible pour votre session.' : response.status === 404 ? 'Cette ressource est introuvable.' : 'Le service est temporairement indisponible. Réessayez dans un instant.');
    error.status = response.status;
    if (error.status === 401) window.dispatchEvent(new Event('merchant-session-ended'));
    throw error;
  }
  return response.json();
}
