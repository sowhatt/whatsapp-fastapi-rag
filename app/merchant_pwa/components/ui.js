export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (value !== undefined && value !== null) node.setAttribute(key, value);
  }
  node.append(...children.flat().filter(x => x !== null && x !== undefined));
  return node;
}
const paths = {
  home: 'M3 10 12 3l9 7v10H3z M9 20v-7h6v7',
  orders: 'M6 3h12v18l-3-2-3 2-3-2-3 2z M9 8h6 M9 12h6',
  notifications: 'M5 17h14l-2-3V9a5 5 0 0 0-10 0v5z M10 21h4',
  stock: 'm3 7 9-4 9 4v10l-9 4-9-4z M3 7l9 4 9-4 M12 11v10',
  more: 'M5 5h3v3H5z M16 5h3v3h-3z M5 16h3v3H5z M16 16h3v3h-3z',
  calendar: 'M4 5h16v16H4z M4 10h16 M8 3v4 M16 3v4',
  profile: 'M8 7a4 4 0 1 0 8 0 4 4 0 0 0-8 0 M4 21a8 8 0 0 1 16 0',
  catalog: 'M4 4h7v7H4z M14 4h6v7h-6z M4 14h7v6H4z M14 14h6v6h-6z',
  kitchen: 'M4 3v6c0 4 6 4 6 0V3 M7 3v18 M18 3v18 M18 3c-5 2-5 9 0 9',
};
export function icon(key) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  for (const [k, v] of Object.entries({viewBox:'0 0 24 24', fill:'none', stroke:'currentColor', 'stroke-width':'1.7', 'stroke-linecap':'round', 'stroke-linejoin':'round', 'aria-hidden':'true'})) svg.setAttribute(k, v);
  const path = document.createElementNS(svg.namespaceURI, 'path');
  path.setAttribute('d', paths[key] || paths.catalog); svg.append(path); return svg;
}
export function empty(title, message) { return el('div', {class:'empty'}, icon('catalog'), el('h2', {}, title), el('p', {}, message)); }
export function errorState(error, retry) {
  const auth = error.status === 401;
  return el('section', {class:'empty error', role:'alert'}, icon('profile'),
    el('p', {class:'eyebrow'}, auth ? 'ESPACE SÉCURISÉ' : 'CONNEXION INTERROMPUE'),
    el('h1', {}, auth ? 'Votre boutique vous attend' : 'Impossible de charger cette page'),
    el('p', {}, auth ? 'La connexion commerçant sécurisée n’est pas encore disponible dans cette version. Vos données restent protégées.' : error.message),
    el('button', {class:'primary', onclick:retry}, auth ? 'Vérifier la connexion' : 'Réessayer'));
}
export function orderCards(rows) {
  if (!rows.length) return empty('Aucune commande pour le moment', 'Vos prochaines commandes apparaîtront ici.');
  return el('div', {class:'order-list'}, rows.map(row => el('a', {class:'order-card', href:row.href},
    el('div', {}, el('strong', {}, row.reference), el('p', {}, row.payment_label)),
    el('div', {class:'order-total'}, el('span', {class:'pill'}, row.status_label),
      el('strong', {}, new Intl.NumberFormat('fr-FR', {style:'currency', currency:row.currency}).format(row.total))))));
}
