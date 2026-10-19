import {el, empty} from '../components/ui.js';
import {enablePush} from '../push.js';
export function moduleView(module, bootstrap) {
  if (!module) return empty('Page introuvable', 'Ce module n’appartient pas à votre espace. Revenez à l’accueil.');
  if (!module.enabled) return el('section', {}, el('p', {class:'eyebrow'}, bootstrap.merchant.business_label), el('h1', {}, module.label), empty('Module non activé', module.description), el('p', {class:'muted'}, 'Ce module sera disponible après son activation pour votre boutique.'));
  if (module.key === 'profile') return el('section', {class:'panel'}, el('h1', {}, 'Profil de la boutique'),
    el('h2', {}, bootstrap.merchant.display_name), el('p', {}, bootstrap.merchant.business_label), el('p', {}, `${bootstrap.merchant.country_code} · ${bootstrap.merchant.currency}`), el('p', {class:'muted'}, 'La gestion du profil et de la session sera reliée à la connexion commerçant sécurisée.'));
  if (module.key === 'settings') {
    const feedback = el('p', {role:'status'});
    return el('section', {class:'panel'}, el('h1', {}, 'Paramètres'), el('h2', {}, 'Votre application, partout'),
      el('p', {}, 'Installez Whatzabi depuis le menu de votre navigateur. Sur iPhone : Partager, puis Sur l’écran d’accueil.'),
      el('h2', {}, 'Notifications sur cet appareil'),
      bootstrap.pwa.push_enabled ? el('button', {class:'primary', onclick:async event => {
        const button = event.currentTarget; button.disabled = true;
        try { await enablePush(); feedback.textContent = 'Les notifications sont activées sur cet appareil.'; }
        catch (error) { feedback.textContent = error.message; }
        finally { button.disabled = false; }
      }}, 'Activer les notifications') : el('p', {}, 'Les notifications Push ne sont pas encore disponibles.'), feedback);
  }
  return el('section', {}, el('h1', {}, 'Tous vos espaces'), el('div', {class:'module-grid'}, bootstrap.navigation.filter(n => n.key !== 'more').map(n =>
    el('a', {class:'panel module-link', href:n.href}, el('h2', {}, n.label), el('p', {}, n.description), el('span', {class:'pill'}, n.enabled ? 'Ouvrir' : 'Module non activé')))));
}
