from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter(tags=["online-admin-web"])


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
.items{margin:12px 0;padding-top:10px;border-top:1px solid #eee}.item{display:flex;justify-content:space-between;gap:12px;padding:4px 0}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.warning{background:#fff4e5;border:1px solid #ffd79a;padding:10px;border-radius:10px;margin-top:10px}.empty{padding:36px;text-align:center;color:#777}
@media(max-width:760px){.cards{grid-template-columns:repeat(2,1fr)}.top{align-items:flex-start;flex-direction:column}.order-head{flex-direction:column}}
</style>
</head>
<body>
<div class="shell">
  <div class="top">
    <h1>Whatzabi Online — Commandes</h1>
    <div class="auth">
      <input id="merchant-id" type="number" min="1" placeholder="Merchant ID">
      <input id="admin-token" type="password" placeholder="Admin token">
      <button id="connect">Charger</button>
    </div>
  </div>

  <div id="summary" class="cards"></div>

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
  function actionButtons(order){
    const a=order.actions||{}, buttons=[];
    if(a.can_revalidate_stock)buttons.push('<button data-action="revalidate">Revalider le stock</button>');
    if(a.can_confirm)buttons.push('<button data-status="confirmed">Confirmer</button>');
    if(a.can_prepare)buttons.push('<button data-status="preparing">Préparer</button>');
    if(a.can_mark_ready)buttons.push('<button data-status="ready">Marquer prête</button>');
    if(a.can_complete)buttons.push('<button data-status="completed">Terminer</button>');
    if(a.can_cancel)buttons.push('<button class="danger" data-status="cancelled">Annuler</button>');
    return buttons.join("");
  }
  function renderOrders(orders){
    if(!orders.length){ordersEl.innerHTML='<div class="empty">Aucune commande.</div>';return;}
    ordersEl.innerHTML=orders.map(o=>{
      const warning=o.actions?.needs_revalidation?'<div class="warning">Réservation expirée : revalidez le stock avant confirmation.</div>':'';
      const items=(o.items||[]).map(i=>'<div class="item"><span>'+esc(i.quantity)+' × '+esc(i.name)+'</span><strong>'+money(i.line_total)+'</strong></div>').join("");
      return '<article class="order" data-order-id="'+o.id+'"><div class="order-head"><div><div class="ref">'+esc(o.reference)+'</div><div class="meta">'+esc(o.customer_name)+' · '+esc(o.customer_phone)+'</div><div class="meta">'+esc(o.delivery_mode)+(o.delivery_address?' · '+esc(o.delivery_address):'')+'</div></div><div><span class="badge">'+esc(o.status)+'</span> <span class="badge">stock: '+esc(o.reservation_status)+'</span></div></div>'+warning+'<div class="items">'+items+'</div><div class="order-head"><strong>'+money(o.total)+'</strong><div class="actions">'+actionButtons(o)+'</div></div></article>';
    }).join("");
  }
  function renderSummary(s){
    const a=s.attention||{};
    const cards=[
      ["À confirmer",a.can_confirm||0],
      ["À revalider",a.needs_revalidation||0],
      ["À préparer",a.to_prepare||0],
      ["Prêtes",a.to_complete||0],
      ["CA commandes",money(s.gross_order_amount)]
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
      const [orders,summary]=await Promise.all([
        api("/online-admin/merchants/"+merchant+"/orders?"+params.toString()),
        api("/online-admin/merchants/"+merchant+"/orders-summary")
      ]);
      renderOrders(orders);renderSummary(summary);
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
      }
      await load();
    }catch(err){alert(err.message);}finally{button.disabled=false;}
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
