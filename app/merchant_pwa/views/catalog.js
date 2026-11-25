import {el, empty} from '../components/ui.js';
import {api} from '../api.js';

const MODES = [['tracked', 'Je suis mon stock'], ['daily', 'Quantité du jour'], ['unlimited', 'Sur commande']];
const money = (value, currency) => new Intl.NumberFormat('fr-FR', {style:'currency', currency, maximumFractionDigits:0}).format(value);

export function catalogView(initial) {
  let data = initial; let openId = null; let message = '';
  const root = el('section', {});
  async function act(task) {
    try { data = await task(); message = ''; } catch (error) { message = error.message; }
    draw();
  }
  const save = (id, body) => act(async () => {
    const res = await api(`/catalog/${id}`, {method:'PUT', body:JSON.stringify(body)});
    return {...data, items:data.items.map(i => i.product_id === id ? res.item : i), published_count:res.published_count};
  });
  function row(item) {
    const open = openId === item.product_id;
    const toggle = el('button', {type:'button', class:`switch${item.is_published ? ' on' : ''}`, role:'switch',
      'aria-checked':String(item.is_published), 'aria-label':`Publier ${item.name} en ligne`,
      onclick:() => save(item.product_id, {published:!item.is_published})}, el('span', {class:'knob'}));
    const detail = open ? el('div', {class:'catalog-detail'},
      !item.is_published ? el('p', {class:'muted'}, 'Mettez ce produit en ligne pour régler son stock.') : [
        el('p', {class:'eyebrow'}, 'Comment gérer le stock ?'),
        MODES.map(([mode, label]) => el('button', {type:'button', class:`mode${item.stock_mode === mode ? ' active' : ''}`, 'aria-pressed':String(item.stock_mode === mode),
          onclick:() => save(item.product_id, mode === 'daily' ? {stock_mode:mode, daily_quantity:item.daily_quantity || 10} : {stock_mode:mode})}, label)),
        item.stock_mode === 'daily' ? el('div', {class:'daily'}, el('span', {}, 'Quantité du jour'),
          el('button', {type:'button', class:'step', 'aria-label':'Moins', onclick:() => save(item.product_id, {stock_mode:'daily', daily_quantity:Math.max(1, (item.daily_quantity || 10) - 5)})}, '−'),
          el('strong', {}, String(item.daily_quantity ?? 10)),
          el('button', {type:'button', class:'step', 'aria-label':'Plus', onclick:() => save(item.product_id, {stock_mode:'daily', daily_quantity:(item.daily_quantity || 10) + 5})}, '+')) : null
      ]) : null;
    return el('li', {class:'catalog-row'}, el('div', {class:'catalog-main'},
      el('button', {type:'button', class:'catalog-name', 'aria-expanded':String(open), onclick:() => { openId = open ? null : item.product_id; draw(); }},
        el('strong', {}, item.name), el('span', {class:'muted'}, `${money(item.price, item.currency)} · ${item.stock_mode_label}`)), toggle), detail);
  }
  function draw() {
    root.replaceChildren(el('p', {class:'eyebrow'}, 'VOTRE BOUTIQUE EN LIGNE'), el('h1', {}, 'Mes produits'),
      el('p', {class:'intro'}, `${data.published_count} produit(s) en ligne sur ${data.total_count}.`),
      el('div', {class:'catalog-actions'}, el('button', {type:'button', class:'primary',
        onclick:() => act(async () => { const res = await api('/catalog/publish-all', {method:'POST', body:'{}'}); return res; })}, 'Tout publier')),
      message ? el('p', {role:'alert', class:'form-error'}, message) : null,
      data.items.length ? el('ul', {class:'catalog-list'}, data.items.map(row)) : empty('Aucun produit', 'Ajoutez vos produits dans Whatzabi Shop, ils apparaîtront ici.'));
  }
  draw();
  return root;
}
