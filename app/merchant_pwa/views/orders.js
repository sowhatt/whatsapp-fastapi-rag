import {el, empty, orderCards} from '../components/ui.js';
export function orders(data, page, detail) {
  if (detail) {
    const order = data.items[0];
    return el('section', {}, el('a', {href:'/merchant/orders', class:'back'}, '← Toutes les commandes'),
      el('h1', {}, order.reference), orderCards([order]),
      el('section', {class:'panel'}, el('h2', {}, 'Articles de la commande'),
        order.items.length ? el('ul', {}, order.items.map(i => el('li', {}, `${i.quantity} × ${i.name}`))) : empty('Aucun article', 'Le détail des articles n’est pas disponible.')),
      order.whatsapp_url ? el('a', {href:order.whatsapp_url, class:'primary', target:'_blank', rel:'noopener noreferrer'}, 'Contacter le client sur WhatsApp') : null,
      el('p', {class:'muted'}, 'Consultation uniquement. Les actions de traitement arrivent avec les modules Commerce.'));
  }
  return el('section', {}, el('p', {class:'eyebrow'}, 'VOTRE ACTIVITÉ'), el('h1', {}, 'Commandes'),
    el('p', {class:'intro'}, 'Retrouvez les commandes reçues et leur état de traitement.'),
    orderCards(data.items), el('div', {class:'pagination'}, page > 0 ? el('a', {href:`/merchant/orders?page=${page-1}`}, 'Précédentes') : null,
      data.has_more ? el('a', {href:`/merchant/orders?page=${page+1}`}, 'Suivantes') : null));
}
