export function startRouter(render) {
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const url = new URL(link.href);
    if (url.origin !== location.origin || !(url.pathname === '/merchant' || url.pathname.startsWith('/merchant/'))) return;
    event.preventDefault(); history.pushState({}, '', url); render();
  });
  window.addEventListener('popstate', render);
}
export function activeModule(bootstrap) {
  const path = location.pathname.replace(/\/$/, '');
  return bootstrap.navigation.find(item => item.href === path);
}
