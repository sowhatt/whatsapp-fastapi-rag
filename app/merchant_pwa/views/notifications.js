import {el, empty} from '../components/ui.js';
import {api} from '../api.js';
export function notifications(data, refresh) {
  return el('section', {}, el('p', {class:'eyebrow'}, 'RESTEZ INFORMÉ'), el('h1', {}, 'Notifications'),
    el('p', {class:'intro'}, `${data.unread_count} notification(s) non lue(s) · 100 dernières notifications`),
    data.items.length ? el('div', {class:'notification-list'}, data.items.map(item => {
      const feedback = el('p', {role:'status', class:'feedback'});
      const button = item.read ? el('span', {class:'muted'}, 'Lue') : el('button', {class:'secondary', onclick:async event => {
        event.currentTarget.disabled = true;
        try { await api(`/notifications/${item.id}/read`, {method:'PATCH', body:'{}'}); refresh(); }
        catch (error) { feedback.textContent = error.message; button.disabled = false; }
      }}, 'Marquer comme lue');
      return el('article', {class:`panel notification ${item.read ? '' : 'unread'}`},
        el('span', {class:'eyebrow'}, item.read ? 'LUE' : 'NOUVELLE'), el('h2', {}, item.title), el('p', {}, item.body),
        el('time', {datetime:item.created_at}, new Date(item.created_at.endsWith('Z') ? item.created_at : `${item.created_at}Z`).toLocaleString('fr-FR')),
        el('div', {class:'notification-actions'}, item.href ? el('a', {href:item.href, class:'primary'}, 'Voir la commande') : null, button), feedback);
    })) : empty('Vous êtes à jour', 'Les prochaines notifications de votre boutique apparaîtront ici.'));
}
