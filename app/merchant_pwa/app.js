import {api} from './api.js';
import {state, clearState} from './store.js';
import {startRouter, activeModule} from './router.js';
import {shell} from './components/app-shell.js';
import {el, errorState} from './components/ui.js';
import {home} from './views/home.js';
import {orders} from './views/orders.js';
import {notifications} from './views/notifications.js';
import {moduleView} from './views/module-placeholder.js';
let revision = 0;
async function render() {
  const current = ++revision;
  let content = shell(null);
  content.replaceChildren(el('p', {role:'status'}, 'Chargement de votre boutique…'), el('div', {class:'skeleton'}));
  try {
    // Revalidate identity on each route and resume. Never reuse another session's data.
    const bootstrap = await api('/bootstrap');
    if (current !== revision) return;
    state.bootstrap = bootstrap;
    const module = activeModule(bootstrap);
    content = shell(bootstrap, module?.key);
    content.setAttribute('aria-busy', 'true');
    content.replaceChildren(el('div', {class:'skeleton', role:'status', 'aria-label':'Chargement'}));
    let view;
    if (module?.enabled && module.key === 'home') view = home(bootstrap, await api('/dashboard'));
    else if (module?.enabled && module.key === 'orders') {
      const params = new URLSearchParams(location.search);
      const id = params.get('order_id');
      const page = Math.max(0, Math.min(10000, Number.parseInt(params.get('page') || '0') || 0));
      const query = id ? `?order_id=${encodeURIComponent(id)}` : `?limit=25&offset=${page*25}`;
      view = orders(await api(`/orders${query}`), page, !!id);
    } else if (module?.enabled && module.key === 'notifications') view = notifications(await api('/notifications'), render);
    else view = moduleView(module, bootstrap);
    if (current !== revision) return;
    content.replaceChildren(view); content.removeAttribute('aria-busy');
    document.title = `${module?.label || 'Espace commerçant'} — Whatzabi`;
    content.focus({preventScroll:true}); window.scrollTo(0,0);
  } catch (error) {
    if (current !== revision) return;
    if (error.status === 401 || !navigator.onLine) { clearState(); content = shell(null); }
    content.removeAttribute('aria-busy'); content.replaceChildren(errorState(error, render));
  }
}
window.addEventListener('merchant-session-ended', () => {
  ++revision;
  clearState();
  shell(null).replaceChildren(errorState({status:401}, render));
});
window.addEventListener('merchant-refresh', render);
window.addEventListener('beforeinstallprompt', event => { event.preventDefault(); state.installPrompt = event; render(); });
window.addEventListener('appinstalled', () => { state.installPrompt = null; render(); });
window.addEventListener('offline', () => { clearState(); render(); });
window.addEventListener('online', render);
window.addEventListener('pageshow', event => { if (event.persisted) { clearState(); render(); } });
document.addEventListener('visibilitychange', () => { if (document.hidden) { ++revision; clearState(); shell(null); } else render(); });
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/merchant/service-worker.js', {scope:'/merchant', updateViaCache:'none'}).catch(() => {});
startRouter(render); render();
