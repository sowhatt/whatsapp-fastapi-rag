import {el, icon} from './ui.js';
import {state} from '../store.js';
export function shell(bootstrap, selected) {
  const nav = bootstrap?.navigation || [];
  const merchant = bootstrap?.merchant;
  function link(item) {
    return el('a', {href:item.href, class:`nav-link ${item.key === selected ? 'active' : ''} ${item.enabled ? '' : 'inactive'}`,
      'aria-current':item.key === selected ? 'page' : null}, icon(item.key), el('span', {}, item.label),
      item.enabled ? null : el('span', {class:'sr-only'}, ' — Module non activé'));
  }
  const brand = el('a', {class:'brand', href:'/merchant'}, el('span', {class:'brand-mark'}, 'w'), el('span', {}, 'Whatzabi', el('small', {}, 'ESPACE COMMERÇANT')));
  const side = el('aside', {class:'sidebar'}, brand, el('div', {class:'workspace-label'}, 'VOTRE BOUTIQUE'),
    el('nav', {'aria-label':'Navigation principale'}, nav.filter(n => n.key !== 'more').map(link)),
    el('p', {class:'side-note'}, 'Votre activité, à portée de main.'));
  const badge = el('span', {class:'badge', 'aria-label':'Notifications non lues'}, String(bootstrap?.notifications.unread_count ?? 0));
  const header = el('header', {class:'topbar'},
    el('a', {class:'identity', href:'/merchant/module/profile'}, el('span', {class:'monogram'}, merchant?.monogram || 'W'),
      el('span', {}, el('strong', {}, merchant?.display_name || 'Whatzabi'), el('small', {}, merchant?.business_label || 'Espace commerçant'))),
    el('div', {class:'header-actions'}, el('span', {class:'network'}, navigator.onLine ? 'En ligne' : 'Hors ligne'),
      bootstrap?.pwa.push_enabled || nav.some(n => n.key === 'notifications' && n.enabled) ? el('a', {class:'notification-link', href:'/merchant/notifications', 'aria-label':`Notifications : ${badge.textContent} non lues`}, icon('notifications'), badge) : null,
      state.installPrompt ? el('button', {class:'install', onclick:async () => { await state.installPrompt.prompt(); state.installPrompt = null; window.dispatchEvent(new Event('merchant-refresh')); }}, 'Installer') : null));
  const content = el('main', {id:'content', tabindex:'-1'});
  const offline = navigator.onLine ? null : el('div', {class:'offline', role:'status'}, 'Vous êtes hors ligne. Les commandes, notifications et modifications sont indisponibles.');
  const bottom = el('nav', {class:'bottom-nav', 'aria-label':'Navigation mobile'}, nav.filter(n => n.mobile).map(link));
  const app = el('div', {class:'layout'}, side, el('div', {class:'workspace'}, header, offline, content), bottom);
  document.querySelector('#app').replaceChildren(app);
  return content;
}
