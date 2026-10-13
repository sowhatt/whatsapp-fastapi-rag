STOREFRONT_CSS = r'''
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#171717;background:#fafafa}
*{box-sizing:border-box}body{margin:0}.store-header{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.96);border-bottom:1px solid #ececec;backdrop-filter:blur(10px)}
.header-inner{max-width:1200px;margin:auto;padding:18px 24px;display:flex;align-items:center;gap:16px}.header-inner h1{font-size:1.35rem;margin:0}.header-inner p{margin:3px 0 0;color:#666}
.store-logo{width:52px;height:52px;border-radius:14px;object-fit:cover}.cart-button{margin-left:auto;border:0;border-radius:999px;padding:11px 16px;background:#171717;color:#fff;font-weight:700;cursor:pointer}
.store-main{max-width:1200px;margin:auto;padding:28px 24px}.catalog-toolbar{margin-bottom:24px}.catalog-toolbar form{display:flex;gap:10px;max-width:620px}.catalog-toolbar input{flex:1;border:1px solid #ddd;border-radius:12px;padding:13px 15px;font-size:1rem}.catalog-toolbar button{border:0;border-radius:12px;padding:13px 18px;background:#171717;color:#fff}
.catalog-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:20px}.product-card{background:#fff;border:1px solid #eee;border-radius:18px;overflow:hidden;box-shadow:0 6px 20px rgba(0,0,0,.04)}
.product-image{display:block;aspect-ratio:1/1;background:#f1f1f1}.product-image img{width:100%;height:100%;object-fit:cover}.product-placeholder,.detail-placeholder{height:100%;display:grid;place-items:center;color:#888;padding:20px;text-align:center}
.product-body{padding:16px}.product-name{display:block;text-decoration:none;color:#171717;font-weight:750;min-height:42px}.product-meta{display:flex;justify-content:space-between;align-items:center;margin:12px 0;gap:8px}.product-price{font-weight:800}.availability{font-size:.8rem;color:#666}
.add-to-cart,.primary-action,.checkout-submit{width:100%;border:0;border-radius:12px;padding:12px;background:#111;color:#fff;font-weight:750;cursor:pointer}.add-to-cart:disabled,.checkout-submit:disabled{opacity:.4;cursor:not-allowed}
.product-detail{max-width:1100px;margin:40px auto;padding:0 24px;display:grid;grid-template-columns:1.1fr .9fr;gap:50px}.detail-media{aspect-ratio:1/1;background:#fff;border-radius:24px;overflow:hidden;border:1px solid #eee}.detail-image{width:100%;height:100%;object-fit:cover}.detail-content{align-self:center}.detail-content h1{font-size:2.2rem;line-height:1.08;margin:0 0 16px}.detail-price{font-size:1.7rem;font-weight:850;margin-bottom:10px}.detail-stock{color:#555;margin-bottom:24px}.detail-content p{line-height:1.6;color:#555}.back-link{text-decoration:none;color:#222;font-weight:700}.store-name{font-weight:800}.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#171717;color:#fff;padding:12px 18px;border-radius:999px;z-index:40}
.cart-overlay{position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:29}.cart-drawer{position:fixed;top:0;right:0;width:min(430px,100%);height:100dvh;background:#fff;z-index:30;box-shadow:-20px 0 40px rgba(0,0,0,.14);display:flex;flex-direction:column}
.cart-head{display:flex;align-items:center;justify-content:space-between;padding:18px;border-bottom:1px solid #eee}.cart-head h2{margin:0;font-size:1.2rem}.cart-close{border:0;background:#f4f4f4;border-radius:999px;width:36px;height:36px;cursor:pointer}
.cart-body{padding:16px;overflow:auto;flex:1}.cart-empty{padding:40px 0;text-align:center;color:#777}.cart-item{display:grid;grid-template-columns:64px 1fr auto;gap:12px;padding:12px 0;border-bottom:1px solid #eee}.cart-thumb{width:64px;height:64px;border-radius:12px;object-fit:cover;background:#f2f2f2}.cart-item-name{font-weight:750}.cart-item-price{font-size:.9rem;color:#666;margin-top:4px}.qty-controls{display:flex;align-items:center;gap:8px;margin-top:10px}.qty-controls button{border:1px solid #ddd;background:#fff;width:30px;height:30px;border-radius:8px;cursor:pointer}.remove-item{border:0;background:none;color:#b42318;cursor:pointer;padding:4px}.cart-footer{border-top:1px solid #eee;padding:16px;background:#fff}.cart-total{display:flex;justify-content:space-between;font-weight:800;font-size:1.08rem;margin-bottom:14px}.checkout-panel{margin-top:16px;padding-top:16px;border-top:1px solid #eee}.checkout-panel h3{margin:0 0 12px}.checkout-grid{display:grid;gap:10px}.checkout-grid input,.checkout-grid select,.checkout-grid textarea{width:100%;padding:12px;border:1px solid #ddd;border-radius:10px;font:inherit}.checkout-grid textarea{min-height:72px;resize:vertical}.order-success{padding:20px;background:#f6f7f5;border-radius:14px}.order-reference{font-size:1.25rem;font-weight:850;margin:8px 0}
@media(max-width:900px){.catalog-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.product-detail{grid-template-columns:1fr;gap:24px}.detail-content h1{font-size:1.8rem}}
@media(max-width:520px){.header-inner{padding:14px 16px}.store-main{padding:20px 16px}.catalog-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.product-body{padding:12px}.product-name{font-size:.92rem}.product-meta{align-items:flex-start;flex-direction:column}.product-detail{margin:20px auto;padding:0 16px}}
'''

STOREFRONT_JS = r'''
(function () {
  var slug = document.body.dataset.storeSlug;
  if (!slug) return;

  var tokenKey = "whatzabi_cart_" + slug;
  var toast = document.getElementById("toast");
  var count = document.getElementById("cart-count");
  var currentCart = null;

  function money(value, currency){
    return new Intl.NumberFormat("fr-FR").format(Number(value || 0)) + " " + (currency || "XOF");
  }
  function esc(value){
    return String(value == null ? "" : value).replace(/[&<>"']/g,function(c){return({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c];});
  }
  function show(message){
    if(!toast)return;
    toast.textContent=message;
    toast.hidden=false;
    clearTimeout(window.__wzToast);
    window.__wzToast=setTimeout(function(){toast.hidden=true;},2400);
  }
  async function problem(response,fallback){
    try{var body=await response.json();return body.detail||fallback;}catch(_){return fallback;}
  }
  async function ensureCart(){
    var token=localStorage.getItem(tokenKey);
    if(token)return token;
    var response=await fetch("/online/"+encodeURIComponent(slug)+"/cart",{method:"POST"});
    if(!response.ok)throw new Error(await problem(response,"Impossible de créer le panier."));
    var cart=await response.json();
    localStorage.setItem(tokenKey,cart.token);
    currentCart=cart;
    return cart.token;
  }
  async function loadCart(){
    var token=localStorage.getItem(tokenKey);
    if(!token){currentCart=null;if(count)count.textContent="0";return null;}
    var response=await fetch("/online/"+encodeURIComponent(slug)+"/cart/"+encodeURIComponent(token));
    if(!response.ok){
      if(response.status===404){localStorage.removeItem(tokenKey);currentCart=null;if(count)count.textContent="0";return null;}
      throw new Error(await problem(response,"Impossible de lire le panier."));
    }
    currentCart=await response.json();
    if(count)count.textContent=String(currentCart.quantity_total||0);
    return currentCart;
  }
  async function setQuantity(productId,quantity){
    var token=await ensureCart();
    var response=await fetch("/online/"+encodeURIComponent(slug)+"/cart/"+encodeURIComponent(token)+"/items",{
      method:"PUT",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({product_id:Number(productId),quantity:Number(quantity)})
    });
    if(!response.ok)throw new Error(await problem(response,"Impossible de mettre à jour le panier."));
    currentCart=await response.json();
    if(count)count.textContent=String(currentCart.quantity_total||0);
    renderDrawer();
    return currentCart;
  }

  function ensureDrawer(){
    if(document.getElementById("cart-drawer"))return;
    var overlay=document.createElement("div");
    overlay.id="cart-overlay";overlay.className="cart-overlay";overlay.hidden=true;
    var drawer=document.createElement("aside");
    drawer.id="cart-drawer";drawer.className="cart-drawer";drawer.hidden=true;
    drawer.innerHTML='<div class="cart-head"><h2>Votre panier</h2><button class="cart-close" aria-label="Fermer">×</button></div><div id="cart-body" class="cart-body"></div><div id="cart-footer" class="cart-footer"></div>';
    document.body.appendChild(overlay);document.body.appendChild(drawer);
    overlay.addEventListener("click",closeDrawer);
    drawer.querySelector(".cart-close").addEventListener("click",closeDrawer);
    drawer.addEventListener("click",async function(event){
      var button=event.target.closest("[data-cart-action]");
      if(!button)return;
      var id=Number(button.dataset.productId);
      var item=(currentCart&&currentCart.items||[]).find(function(x){return x.product_id===id;});
      if(!item)return;
      try{
        if(button.dataset.cartAction==="inc")await setQuantity(id,item.quantity+1);
        if(button.dataset.cartAction==="dec")await setQuantity(id,Math.max(0,item.quantity-1));
        if(button.dataset.cartAction==="remove")await setQuantity(id,0);
      }catch(error){show(error.message);}
    });
    drawer.addEventListener("change",function(event){
      if(event.target.id==="delivery-mode"){
        var address=document.getElementById("delivery-address-wrap");
        if(address)address.hidden=event.target.value!=="delivery";
      }
    });
    drawer.addEventListener("submit",submitCheckout);
  }
  function closeDrawer(){
    var drawer=document.getElementById("cart-drawer"),overlay=document.getElementById("cart-overlay");
    if(drawer)drawer.hidden=true;if(overlay)overlay.hidden=true;
  }
  async function openDrawer(){
    ensureDrawer();
    try{await loadCart();renderDrawer();document.getElementById("cart-drawer").hidden=false;document.getElementById("cart-overlay").hidden=false;}
    catch(error){show(error.message);}
  }
  function renderDrawer(){
    ensureDrawer();
    var body=document.getElementById("cart-body"),footer=document.getElementById("cart-footer");
    if(!currentCart||!(currentCart.items||[]).length){
      body.innerHTML='<div class="cart-empty">Votre panier est vide.</div>';
      footer.innerHTML="";return;
    }
    body.innerHTML=currentCart.items.map(function(item){
      var image=item.image_url?'<img class="cart-thumb" src="'+esc(item.image_url)+'" alt="">':'<div class="cart-thumb"></div>';
      return '<div class="cart-item">'+image+'<div><div class="cart-item-name">'+esc(item.name)+'</div><div class="cart-item-price">'+money(item.unit_price,currentCart.currency)+'</div><div class="qty-controls"><button data-cart-action="dec" data-product-id="'+item.product_id+'">−</button><strong>'+item.quantity+'</strong><button data-cart-action="inc" data-product-id="'+item.product_id+'">+</button></div></div><button class="remove-item" data-cart-action="remove" data-product-id="'+item.product_id+'">Suppr.</button></div>';
    }).join("");
    footer.innerHTML='<div class="cart-total"><span>Total</span><span>'+money(currentCart.subtotal,currentCart.currency)+'</span></div><div class="checkout-panel"><h3>Finaliser la commande</h3><form id="checkout-form" class="checkout-grid"><input name="customer_name" placeholder="Nom et prénom" required maxlength="150"><input name="customer_phone" placeholder="Téléphone" required maxlength="40"><select id="delivery-mode" name="delivery_mode"><option value="pickup">Retrait</option><option value="delivery">Livraison</option></select><select name="payment_method"><option value="cash_on_delivery">Paiement à la livraison / au retrait</option><option value="mobile_money">Mobile Money (à confirmer)</option></select><div id="delivery-address-wrap" hidden><input name="delivery_address" placeholder="Adresse de livraison" maxlength="500"></div><textarea name="notes" placeholder="Note pour le commerçant" maxlength="500"></textarea><button class="checkout-submit" type="submit">Commander</button></form></div>';
  }
  async function submitCheckout(event){
    if(event.target.id!=="checkout-form")return;
    event.preventDefault();
    var form=event.target,button=form.querySelector("button[type=submit]");
    var token=localStorage.getItem(tokenKey);
    if(!token)return;
    var data=new FormData(form);
    var payload={
      customer_name:data.get("customer_name"),
      customer_phone:data.get("customer_phone"),
      delivery_mode:data.get("delivery_mode"),
      payment_method:data.get("payment_method")||"cash_on_delivery",
      delivery_address:data.get("delivery_address")||null,
      notes:data.get("notes")||null
    };
    button.disabled=true;
    try{
      var response=await fetch("/online/"+encodeURIComponent(slug)+"/cart/"+encodeURIComponent(token)+"/checkout",{
        method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)
      });
      if(!response.ok)throw new Error(await problem(response,"Impossible de créer la commande."));
      var order=await response.json();
      localStorage.removeItem(tokenKey);currentCart=null;if(count)count.textContent="0";
      document.getElementById("cart-body").innerHTML='<div class="order-success"><strong>Commande enregistrée</strong><div class="order-reference">'+esc(order.reference)+'</div><div>Total : '+money(order.total,order.currency)+'</div><div>Statut : '+esc(order.status)+'</div><div>Paiement : '+esc(order.payment_status)+'</div></div>';
      document.getElementById("cart-footer").innerHTML="";
    }catch(error){show(error.message);}finally{button.disabled=false;}
  }

  document.querySelectorAll(".add-to-cart").forEach(function(button){
    button.addEventListener("click",async function(){
      button.disabled=true;
      try{
        await loadCart();
        var productId=Number(button.dataset.productId);
        var existing=(currentCart&&currentCart.items||[]).find(function(x){return x.product_id===productId;});
        await setQuantity(productId,(existing?existing.quantity:0)+1);
        show("Produit ajouté au panier");
      }catch(error){show(error.message||"Une erreur est survenue.");}
      finally{button.disabled=false;}
    });
  });

  var cartButton=document.getElementById("cart-button");
  if(cartButton)cartButton.addEventListener("click",openDrawer);
  loadCart().catch(function(){});
})();
'''
