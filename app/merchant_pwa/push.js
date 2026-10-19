import {api} from './api.js';
export async function enablePush() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) throw new Error('Ce navigateur ne permet pas les notifications Push.');
  if (await Notification.requestPermission() !== 'granted') throw new Error('Les notifications ne sont pas autorisées sur cet appareil.');
  const config = await api('/push/config');
  if (!config.enabled || !config.public_key) throw new Error('Les notifications Push sont indisponibles.');
  const registration = await navigator.serviceWorker.getRegistration('/merchant/');
  if (!registration?.active) throw new Error('L’application se prépare. Réessayez dans un instant.');
  const key = config.public_key.replace(/-/g, '+').replace(/_/g, '/');
  const applicationServerKey = Uint8Array.from(atob(key + '='.repeat((4-key.length%4)%4)), c => c.charCodeAt(0));
  const subscription = await registration.pushManager.getSubscription() || await registration.pushManager.subscribe({userVisibleOnly:true, applicationServerKey});
  await api('/push-subscriptions', {method:'POST', body:JSON.stringify({endpoint:subscription.endpoint, keys:subscription.toJSON().keys})});
}
