import {el, empty, orderCards} from '../components/ui.js';
export function home(bootstrap, data) {
  const merchant = bootstrap.merchant;
  const links = bootstrap.navigation.filter(n => n.enabled && !['home','more','profile','settings'].includes(n.key));
  return el('div', {},
    el('section', {class:'welcome'}, el('div', {}, el('p', {class:'eyebrow'}, new Intl.DateTimeFormat('fr-FR', {dateStyle:'full'}).format(new Date())),
      el('h1', {}, `Bonjour, ${merchant.display_name}`), el('p', {}, 'Un regard sur votre activité. Une journée bien organisée.')),
      el('span', {class:'welcome-tag'}, merchant.business_label)),
    bootstrap.configuration_required ? empty('Configuration à compléter', 'Votre type d’activité doit être configuré pour activer vos modules.') : null,
    el('section', {class:'stats', 'aria-label':'Votre activité'}, data.stats.map(s => el('article', {class:'stat'}, el('span', {}, s.label), el('strong', {}, String(s.value)))),
      el('article', {class:'stat'}, el('span', {}, 'Notifications non lues'), el('strong', {}, String(data.unread_count)))),
    el('div', {class:'dashboard-grid'},
      el('section', {class:'panel'}, el('div', {class:'section-head'}, el('h2', {}, 'À votre attention'), el('span', {class:'pill'}, 'Aujourd’hui')),
        data.urgent.length ? el('div', {}, data.urgent.map(a => el('a', {href:a.href, class:'attention'}, el('span', {}, a.label), el('strong', {}, String(a.value))))) : empty('Rien à signaler', 'Aucune action urgente dans les modules disponibles.')),
      el('section', {class:'panel'}, el('h2', {}, 'Accès rapides'), links.length ? el('div', {class:'quick-links'}, links.map(n => el('a', {href:n.href}, n.label, el('span', {'aria-hidden':'true'}, '→')))) : el('p', {}, 'Vos raccourcis apparaîtront après activation des modules.'))),
    el('section', {class:'panel activity'}, el('h2', {}, 'Activité récente'),
      links.some(n => n.key === 'orders') ? orderCards(data.recent_orders) : empty('Votre espace prend forme', 'Les modules de votre activité seront activés progressivement.')),
    ['restaurant','rental'].includes(merchant.business_type) ? el('section', {class:'future'}, el('h2', {}, merchant.business_type === 'restaurant' ? 'Votre futur espace cuisine' : 'Votre futur calendrier de location'), el('p', {}, 'Module non activé. Retrouvez sa présentation dans la navigation.')) : null);
}
