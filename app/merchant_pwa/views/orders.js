import {el, empty, orderCards} from '../components/ui.js';
import {api} from '../api.js';
const CONFIRM = {cancelled:'Annuler cette commande ? Cette action est définitive.', completed:'Confirmer la remise au client ? Le stock sera mis à jour.'};
function actions(order) {
  const feedback = el('p', {role:'alert', class:'form-error'});
  const run = (path, status, ask) => async event => {
    if (ask && !window.confirm(ask)) return;
    const button = event.currentTarget; button.disabled = true;
    try { await api(path, {method:'PATCH', body:JSON.stringify({status})}); window.dispatchEvent(new Event('merchant-refresh')); }
    catch (error) { feedback.textContent = error.message; button.disabled = false; }
  };
  const next = (order.actions || []).map((a, i) => el('button', {type:'button', class:i === 0 ? 'primary' : 'mode', onclick:run(`/orders/${order.id}/status`, a.status, CONFIRM[a.status])}, a.label));
  const pay = (order.payment_actions || []).map(a => el('button', {type:'button', class:'mode', onclick:run(`/orders/${order.id}/payment`, a.status)}, a.label));
  return el('section', {class:'panel'}, el('h2', {}, 'Traiter la commande'), next.length || pay.length ? [...next, ...pay] : el('p', {class:'muted'}, 'Aucune action disponible : cette commande est terminée ou annulée.'), feedback);
}
export function orders(data, page, detail) {
  if (detail) {
    const order = data.items[0];
    return el('section', {}, el('a', {href:'/merchant/orders', class:'back'}, '← Toutes les commandes'),
      el('h1', {}, order.reference), orderCards([order]),
      el('section', {class:'panel'}, el('h2', {}, 'Articles de la commande'),
        order.items.length ? el('ul', {}, order.items.map(i => el('li', {}, `${i.quantity} × ${i.name}`))) : empty('Aucun article', 'Le détail des articles n’est pas disponible.')),
      order.whatsapp_url ? el('a', {href:order.whatsapp_url, class:'primary', target:'_blank', rel:'noopener noreferrer'}, 'Contacter le client sur WhatsApp') : null,
      actions(order));
  }
  return el('section', {}, el('p', {class:'eyebrow'}, 'VOTRE ACTIVITÉ'), el('h1', {}, 'Commandes'),
    el('p', {class:'intro'}, 'Retrouvez les commandes reçues et leur état de traitement.'),
    orderCards(data.items), el('div', {class:'pagination'}, page > 0 ? el('a', {href:`/merchant/orders?page=${page-1}`}, 'Précédentes') : null,
      data.has_more ? el('a', {href:`/merchant/orders?page=${page+1}`}, 'Suivantes') : null));
}
