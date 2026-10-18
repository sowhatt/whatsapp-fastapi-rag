from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response


router = APIRouter(tags=["online-admin-web"])


@router.get("/online-admin-sw.js")
def online_admin_service_worker():
    return Response(
        content=r"""
self.addEventListener("push", event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) {}
  const title = data.title || "Whatzabi";
  const options = {
    body: data.body || "Nouvelle activité",
    data: { url: data.url || "/online-admin-ui" },
    tag: data.notification_id ? "wz-" + data.notification_id : undefined
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const url = event.notification.data?.url || "/online-admin-ui";
  event.waitUntil(clients.openWindow(url));
});
""",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/online-admin-ui", response_class=HTMLResponse)
def online_admin_ui():
    return HTMLResponse(
        """
<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Whatzabi Online — Commandes</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#181818;background:#f6f6f4}
*{box-sizing:border-box}body{margin:0}.shell{max-width:1180px;margin:auto;padding:24px}
.top{display:flex;gap:12px;align-items:center;justify-content:space-between;margin-bottom:20px}.top h1{font-size:1.5rem;margin:0}
.auth,.toolbar{display:flex;gap:10px;flex-wrap:wrap}.auth input,.toolbar input,.toolbar select{padding:10px 12px;border:1px solid #d8d8d8;border-radius:10px;background:white}
button{border:0;border-radius:10px;padding:10px 14px;background:#181818;color:white;font-weight:700;cursor:pointer}button.secondary{background:#eee;color:#181818}button.danger{background:#b42318}
.cards{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:18px 0}.card{background:white;border:1px solid #e8e8e8;border-radius:14px;padding:16px}.card strong{display:block;font-size:1.5rem;margin-top:6px}
.order{background:white;border:1px solid #e8e8e8;border-radius:16px;padding:16px;margin:12px 0}.order-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.ref{font-weight:850}.meta{color:#666;font-size:.92rem;margin-top:4px}.badge{display:inline-block;padding:5px 9px;border-radius:999px;background:#f0f0f0;font-size:.8rem;font-weight:700}
.items{margin:12px 0;padding-top:10px;border-top:1px solid #eee}.item{display:flex;justify-content:space-between;gap:12px;padding:4px 0}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.warning{background:#fff4e5;border:1px solid #ffd79a;padding:10px;border-radius:10px;margin-top:10px}.empty{padding:36px;text-align:center;color:#777}.priority{font-size:.82rem;font-weight:800;margin-top:8px}.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px}.detail-box{background:#fafafa;border-radius:10px;padding:10px}.detail-box small{display:block;color:#777;margin-bottom:4px}.whatsapp{background:#1f7a45}.muted{color:#777;font-size:.85rem}
.notif-wrap{position:relative}.notif-btn{background:white;color:#181818;border:1px solid #ddd}.notif-count{display:inline-flex;align-items:center;justify-content:center;min-width:22px;height:22px;padding:0 6px;border-radius:999px;background:#181818;color:white;font-size:.75rem;margin-left:6px}.notif-panel{display:none;background:white;border:1px solid #e5e5e5;border-radius:16px;padding:14px;margin:0 0 18px}.notif-panel.open{display:block}.notif-row{padding:12px 0;border-bottom:1px solid #eee}.notif-row:last-child{border-bottom:0}.notif-row.unread{font-weight:650}.notif-head{display:flex;justify-content:space-between;gap:12px}.notif-body{margin-top:5px;color:#555;font-weight:400}.notif-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}.notif-actions a{display:inline-block;text-decoration:none;border-radius:9px;padding:8px 11px;background:#181818;color:white;font-weight:700;font-size:.86rem}
@media(max-width:760px){.cards{grid-template-columns:repeat(2,1fr)}.top{align-items:flex-start;flex-direction:column}.order-head{flex-direction:column}}
</style>
</head>
<body>
<div class="shell">
  <div class="top">
    <h1>Whatzabi Online — Commandes</h1>
    <div class="auth">
      <div class="notif-wrap">
        <button id="notifications-toggle" class="notif-btn" type="button">Notifications <span id="notifications-count" class="notif-count">0</span></button>
        <button id="push-enable" class="secondary" type="button">Activer notifications</button>
      </div>
      <input id="merchant-id" type="number" min="1" placeholder="Merchant ID">
      <input id="admin-token" type="password" placeholder="Admin token">
      <button id="connect">Charger</button>
    </div>
  </div>

  <div id="summary" class="cards"></div>
  <section id="notifications-panel" class="notif-panel">
    <div class="order-head">
      <div>
        <div class="ref">Notifications</div>
        <div class="meta">Commandes et actions importantes</div>
      </div>
      <button id="notifications-refresh" class="secondary" type="button">Actualiser</button>
    </div>
    <div id="notifications-list"></div>
  </section>

  <div class="toolbar">
    <input id="search" placeholder="Référence, nom, téléphone">
    <select id="status">
      <option value="">Tous les statuts</option>
      <option value="pending">À confirmer</option>
      <option value="confirmed">Confirmées</option>
      <option value="preparing">En préparation</option>
      <option value="ready">Prêtes</option>
      <option value="completed">Terminées</option>
      <option value="cancelled">Annulées</option>
    </select>
    <button id="refresh" class="secondary">Actualiser</button>
  </div>

  <div id="orders"></div>
</div>
<script>
(function(){
  const merchantInput=document.getElementById("merchant-id");
  const tokenInput=document.getElementById("admin-token");
  const ordersEl=document.getElementById("orders");
  const summaryEl=document.getElementById("summary");
  const searchInput=document.getElementById("search");
  const statusInput=document.getElementById("status");
  const notificationsToggle=document.getElementById("notifications-toggle");
  const notificationsCount=document.getElementById("notifications-count");
  const notificationsPanel=document.getElementById("notifications-panel");
  const notificationsList=document.getElementById("notifications-list");
  const pushEnable=document.getElementById("push-enable");

  function cfg(){
    return {
      merchant:merchantInput.value.trim(),
      token:tokenInput.value.trim()
    };
  }
  function headers(){return {"X-Admin-Token":cfg().token};}
  function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
  function money(v){return new Intl.NumberFormat("fr-FR").format(Number(v||0))+" XOF";}
  async function api(path,opts={}){
    const res=await fetch(path,{...opts,headers:{...(opts.headers||{}),...headers()}});
    if(!res.ok){let d={};try{d=await res.json()}catch{};throw new Error(d.detail||("Erreur "+res.status));}
    return res.json();
  }
  function whatsappHref(order){
    const phone=String(order.customer_phone||"").replace(/[^0-9]/g,"");
    if(!phone)return "";
    const text="Bonjour "+(order.customer_name||"")+", concernant votre commande "+order.reference+" chez Whatzabi : statut "+order.status+".";
    return "https://wa.me/"+phone+"?text="+encodeURIComponent(text);
  }
  function ageLabel(minutes){
    minutes=Number(minutes||0);
    if(minutes<60)return minutes+" min";
    const hours=Math.floor(minutes/60), rest=minutes%60;
    if(hours<24)return hours+" h"+(rest?" "+rest+" min":"");
    const days=Math.floor(hours/24);
    return days+" j "+(hours%24)+" h";
  }
  function actionButtons(order){
    const a=order.actions||{}, buttons=[];
    const wa=whatsappHref(order);
    if(wa)buttons.push('<a class="whatsapp" href="'+esc(wa)+'" target="_blank" rel="noopener" style="text-decoration:none;border-radius:10px;padding:10px 14px;color:white;font-weight:700">WhatsApp</a>');
    if(a.can_revalidate_stock)buttons.push('<button data-action="revalidate">Revalider le stock</button>');
    if(a.can_confirm)buttons.push('<button data-status="confirmed">Confirmer</button>');
    if(a.can_prepare)buttons.push('<button data-status="preparing">Préparer</button>');
    if(a.can_mark_ready)buttons.push('<button data-status="ready">Marquer prête</button>');
    if(a.can_complete)buttons.push('<button data-status="completed">Terminer</button>');
    if(a.can_mark_paid)buttons.push('<button data-payment-status="paid">Marquer payé</button>');
    if(a.can_mark_payment_failed)buttons.push('<button class="secondary" data-payment-status="failed">Paiement échoué</button>');
    if(a.can_retry_mobile_money)buttons.push('<button class="secondary" data-payment-status="mobile_money_pending">Réessayer Mobile Money</button>');
    if(a.can_cancel)buttons.push('<button class="danger" data-status="cancelled">Annuler</button>');
    return buttons.join("");
  }
  function urlBase64ToUint8Array(base64String){
    const padding="=".repeat((4-base64String.length%4)%4);
    const base64=(base64String+padding).replace(/-/g,"+").replace(/_/g,"/");
    const raw=atob(base64);
    return Uint8Array.from([...raw].map(ch=>ch.charCodeAt(0)));
  }
  async function enablePush(){
    const {merchant,token}=cfg();
    if(!merchant||!token)throw new Error("Chargez d’abord le commerçant.");
    if(!("serviceWorker" in navigator)||!("PushManager" in window)){
      throw new Error("Web Push non supporté sur cet appareil.");
    }
    const config=await api("/online-admin/push/config");
    if(!config.enabled||!config.public_key){
      throw new Error("Web Push n’est pas configuré sur le serveur.");
    }
    const permission=await Notification.requestPermission();
    if(permission!=="granted")throw new Error("Permission de notification refusée.");
    const registration=await navigator.serviceWorker.register("/online-admin-sw.js");
    let subscription=await registration.pushManager.getSubscription();
    if(!subscription){
      subscription=await registration.pushManager.subscribe({
        userVisibleOnly:true,
        applicationServerKey:urlBase64ToUint8Array(config.public_key)
      });
    }
    await api("/online-admin/merchants/"+merchant+"/push-subscriptions",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify(subscription.toJSON())
    });
    pushEnable.textContent="Notifications activées";
    pushEnable.disabled=true;
  }
  function renderNotifications(rows){
    const unread=rows.filter(n=>n.status==="unread").length;
    notificationsCount.textContent=String(unread);
    notificationsCount.style.display=unread?"inline-flex":"none";
    if(!rows.length){
      notificationsList.innerHTML='<div class="empty">Aucune notification.</div>';
      return;
    }
    notificationsList.innerHTML=rows.map(n=>{
      const unreadClass=n.status==="unread"?" unread":"";
      const action=n.action_url?'<a href="'+esc(n.action_url)+'" data-notification-link="'+n.id+'">Voir</a>':'';
      const mark=n.status==="unread"?'<button class="secondary" data-notification-read="'+n.id+'">Marquer lue</button>':'';
      return '<div class="notif-row'+unreadClass+'" data-notification-id="'+n.id+'"><div class="notif-head"><span>'+esc(n.title||"Whatzabi")+'</span><span class="badge">'+esc(n.status)+'</span></div><div class="notif-body">'+esc(n.body||"")+'</div><div class="notif-actions">'+action+mark+'</div></div>';
    }).join("");
  }
  async function loadNotifications(){
    const {merchant,token}=cfg();
    if(!merchant||!token){renderNotifications([]);return;}
    const rows=await api("/online-admin/merchants/"+merchant+"/notifications?recipient_role=merchant&limit=50");
    renderNotifications(rows);
  }
  function renderOrders(orders){
    if(!orders.length){ordersEl.innerHTML='<div class="empty">Aucune commande.</div>';return;}
    ordersEl.innerHTML=orders.map(o=>{
      const warning=o.actions?.needs_revalidation?'<div class="warning">Réservation expirée : revalidez le stock avant confirmation.</div>':'';
      const items=(o.items||[]).map(i=>'<div class="item"><span>'+esc(i.quantity)+' × '+esc(i.name)+'</span><strong>'+money(i.line_total)+'</strong></div>').join("");
      const address=o.delivery_address?'<div class="detail-box"><small>Adresse</small>'+esc(o.delivery_address)+'</div>':'';
      const notes=o.notes?'<div class="detail-box"><small>Note client</small>'+esc(o.notes)+'</div>':'';
      const details=(address||notes)?'<div class="detail-grid">'+address+notes+'</div>':'';
      return '<article class="order" id="order-'+o.id+'" data-order-id="'+o.id+'"><div class="order-head"><div><div class="ref">'+esc(o.reference)+'</div><div class="meta">'+esc(o.customer_name)+' · '+esc(o.customer_phone)+'</div><div class="meta">'+esc(o.delivery_mode)+' · créée il y a '+esc(ageLabel(o.age_minutes))+'</div><div class="priority">'+esc(o.priority?.label||"")+'</div></div><div><span class="badge">'+esc(o.status)+'</span> <span class="badge">stock: '+esc(o.reservation_status)+'</span> <span class="badge">paiement: '+esc(o.payment_status)+'</span></div></div>'+warning+details+'<div class="items">'+items+'</div><div class="order-head"><strong>'+money(o.total)+'</strong><div class="actions">'+actionButtons(o)+'</div></div></article>';
    }).join("");
  }
  function renderSummary(s){
    const a=s.attention||{};
    const cards=[
      ["À confirmer",a.can_confirm||0],
      ["À revalider",a.needs_revalidation||0],
      ["À préparer",a.to_prepare||0],
      ["Prêtes",a.to_complete||0],
      ["Payé",money(s.paid_amount)]
    ];
    summaryEl.innerHTML=cards.map(x=>'<div class="card">'+esc(x[0])+'<strong>'+esc(x[1])+'</strong></div>').join("");
  }
  async function load(){
    const {merchant,token}=cfg();
    if(!merchant||!token){ordersEl.innerHTML='<div class="empty">Renseignez Merchant ID et Admin token.</div>';return;}
    localStorage.setItem("wz_online_merchant",merchant);
    const params=new URLSearchParams();
    if(searchInput.value.trim())params.set("q",searchInput.value.trim());
    if(statusInput.value)params.set("status",statusInput.value);
    try{
      const [orders,summary,notifications]=await Promise.all([
        api("/online-admin/merchants/"+merchant+"/orders?"+params.toString()),
        api("/online-admin/merchants/"+merchant+"/orders-summary"),
        api("/online-admin/merchants/"+merchant+"/notifications?recipient_role=merchant&limit=50")
      ]);
      renderOrders(orders);renderSummary(summary);renderNotifications(notifications);
    }catch(e){ordersEl.innerHTML='<div class="warning">'+esc(e.message)+'</div>';}
  }
  ordersEl.addEventListener("click",async e=>{
    const button=e.target.closest("button");if(!button)return;
    const card=button.closest("[data-order-id]");if(!card)return;
    const orderId=card.dataset.orderId, merchant=cfg().merchant;
    button.disabled=true;
    try{
      if(button.dataset.action==="revalidate"){
        await api("/online-admin/merchants/"+merchant+"/orders/"+orderId+"/reservations/revalidate",{method:"POST"});
      }else if(button.dataset.status){
        await api("/online-admin/merchants/"+merchant+"/orders/"+orderId+"/status",{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({status:button.dataset.status})});
      }else if(button.dataset.paymentStatus){
        await api("/online-admin/merchants/"+merchant+"/orders/"+orderId+"/payment-status",{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({status:button.dataset.paymentStatus})});
      }
      await load();
    }catch(err){alert(err.message);}finally{button.disabled=false;}
  });
  notificationsToggle.addEventListener("click",()=>{
    notificationsPanel.classList.toggle("open");
  });
  document.getElementById("notifications-refresh").addEventListener("click",async()=>{
    try{await loadNotifications();}catch(e){notificationsList.innerHTML='<div class="warning">'+esc(e.message)+'</div>';}
  });
  notificationsList.addEventListener("click",async e=>{
    const readButton=e.target.closest("[data-notification-read]");
    const link=e.target.closest("[data-notification-link]");
    const target=readButton||link;
    if(!target)return;
    const id=target.dataset.notificationRead||target.dataset.notificationLink;
    try{
      await api("/online-admin/merchants/"+cfg().merchant+"/notifications/"+id+"/read",{method:"PATCH"});
      await loadNotifications();
    }catch(err){
      if(readButton){alert(err.message);}
    }
  });
  pushEnable.addEventListener("click",async()=>{
    pushEnable.disabled=true;
    try{await enablePush();}
    catch(err){alert(err.message);pushEnable.disabled=false;}
  });
  document.getElementById("connect").addEventListener("click",load);
  document.getElementById("refresh").addEventListener("click",load);
  searchInput.addEventListener("keydown",e=>{if(e.key==="Enter")load();});
  statusInput.addEventListener("change",load);
  merchantInput.value=localStorage.getItem("wz_online_merchant")||"";
})();
</script>
</body>
</html>
        """
    )
