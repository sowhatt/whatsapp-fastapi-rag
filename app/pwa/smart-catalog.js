(() => {
  let controls=null,scanning=false,zxingPromise=null,detectedBarcode='',nativeStream=null,nativeTimer=null,aiTimer=null,aiBusy=false,validationBusy=false;
  const $=id=>document.getElementById(id);
  function ensureUI(){if($('barcodeLiveView'))return;const v=document.createElement('section');v.id='barcodeLiveView';v.className='barcode-live-view';v.hidden=true;v.innerHTML=`<div class="barcode-live-head"><button id="barcodeLiveBack" type="button" class="ghost">‹ Retour</button><strong>Scanner le code-barres</strong></div><div class="barcode-camera-frame"><video id="barcodeLiveVideo" autoplay playsinline muted></video><div id="barcodeTarget" class="barcode-target" aria-hidden="true"><span></span></div></div><div id="barcodeDetectedBox" hidden style="margin:14px 0;padding:12px;border-radius:14px;background:#e8f3f1;text-align:center"><small style="display:block;color:#607874">✓ Code-barres détecté</small><strong id="barcodeDetectedValue" style="display:block;margin-top:4px;font-size:20px;letter-spacing:.06em"></strong></div><img id="barcodeAutoCapture" hidden alt="Capture automatique" style="width:100%;max-height:150px;object-fit:contain;border-radius:12px;margin:8px 0"><p id="barcodeLiveStatus" class="barcode-live-status">Recherche du code-barres…</p><p class="muted small">Garde le code dans le cadre. Whatzabi capture automatiquement des images et l’IA tente de lire l’EAN.</p><div id="barcodeUnknownActions" hidden style="display:grid;gap:8px"><button id="barcodePhotoFallback" type="button">📷 Photographier le produit</button><button id="barcodeNameBtn" type="button" class="ghost">⌨️ Saisir le nom</button><button id="barcodeVoiceBtn" type="button" class="ghost">🎙️ Dicter le nom</button></div>`;document.querySelector('.catalog-sheet-card')?.appendChild(v);$('barcodeLiveBack').onclick=openCatalogMenu;$('barcodePhotoFallback').onclick=openPhotoFallback;$('barcodeNameBtn').onclick=enterName;$('barcodeVoiceBtn').onclick=dictateName}
  function setStatus(t){if($('barcodeLiveStatus'))$('barcodeLiveStatus').textContent=t}
  function normalizeCode(v){const c=String(v||'').replace(/\D/g,'');return c.length>=8&&c.length<=14?c:''}
  function showDetected(code){detectedBarcode=code;$('barcodeDetectedValue').textContent=`EAN / GTIN : ${code}`;$('barcodeDetectedBox').hidden=false;$('barcodeTarget')?.classList.add('detected');sessionStorage.setItem('whatzabi_pending_barcode',code)}
  function loadZXing(){if(window.ZXingBrowser)return Promise.resolve(window.ZXingBrowser);if(zxingPromise)return zxingPromise;zxingPromise=new Promise((ok,no)=>{const s=document.createElement('script');s.src='https://unpkg.com/@zxing/browser@0.2.1';s.async=true;s.onload=()=>window.ZXingBrowser?ok(window.ZXingBrowser):no();s.onerror=no;document.head.appendChild(s)});return zxingPromise}
  function captureFrame(){const video=$('barcodeLiveVideo');if(!video?.videoWidth)return null;const c=document.createElement('canvas');const max=1280,scale=Math.min(1,max/video.videoWidth);c.width=Math.round(video.videoWidth*scale);c.height=Math.round(video.videoHeight*scale);c.getContext('2d').drawImage(video,0,0,c.width,c.height);return c}
  async function lookup(code){showDetected(code);setStatus('Recherche du produit…');navigator.vibrate?.(80);const token=localStorage.getItem('whatzabi_token')||'',r=await fetch(`/pwa/catalog/barcode/${encodeURIComponent(code)}`,{headers:{Authorization:`Bearer ${token}`}});let b=null;try{b=await r.json()}catch{}if(!r.ok)throw new Error(b?.detail||'Produit absent du référentiel.');return b}
  function renderResult(b){
    try{catalogAnalysis=b}catch{}

    const cs=b?.candidates||[];
    const list=$('catalogCandidateList');
    const invoiceMode=catalogSource==='invoice'||b?.source==='invoice';

    list.innerHTML='';

    $('catalogResultCount').textContent=cs.length
      ? `${cs.length} produit${cs.length>1?'s':''} détecté${cs.length>1?'s':''}`
      : 'Code reconnu';

    cs.forEach((c,index)=>{
      const a=document.createElement('article');
      a.className='catalog-candidate';

      if(invoiceMode){
        a.dataset.invoiceIndex=String(index);

        const head=document.createElement('label');
        head.style.display='flex';
        head.style.gap='10px';
        head.style.alignItems='center';
        head.style.justifyContent='flex-start';
        head.style.width='100%';
        head.style.boxSizing='border-box';

        const check=document.createElement('input');
        check.type='checkbox';
        check.checked=true;
        check.className='invoice-line-selected';

        const title=document.createElement('strong');
        title.textContent='Ligne '+(index+1);

        head.appendChild(check);
        head.appendChild(title);
        a.appendChild(head);

        const name=document.createElement('input');
        name.className='invoice-line-name';
        name.value=c.name||'';
        name.placeholder='Nom du produit';
        name.style.width='100%';
        name.style.marginTop='10px';
        a.appendChild(name);

        const fields=document.createElement('div');
        fields.style.display='grid';
        fields.style.gridTemplateColumns='1fr 1fr';
        fields.style.gap='8px';
        fields.style.marginTop='8px';

        const qty=document.createElement('input');
        qty.className='invoice-line-quantity';
        qty.type='number';
        qty.min='0';
        qty.inputMode='numeric';
        qty.value=String(c.quantity??0);
        qty.placeholder='Quantité';

        const price=document.createElement('input');
        price.className='invoice-line-purchase-price';
        price.type='number';
        price.min='0';
        price.inputMode='decimal';
        price.value=c.purchase_price==null?'':String(c.purchase_price);
        price.placeholder='Prix achat';

        fields.appendChild(qty);
        fields.appendChild(price);
        a.appendChild(fields);

        const m=document.createElement('div');
        m.className='catalog-meta';
        [
          c.brand,
          c.packaging,
          c.purchase_price!=null&&('Achat : '+c.purchase_price+' '+(c.currency||'')),
          c.quantity!=null&&('Qté : '+c.quantity)
        ].filter(Boolean).forEach(x=>{
          const chip=document.createElement('span');
          chip.className='catalog-chip';
          chip.textContent=x;
          m.appendChild(chip);
        });
        a.appendChild(m);
      }else{
        const h=document.createElement('h3');
        h.textContent=c.name||'Produit';
        a.appendChild(h);

        const m=document.createElement('div');
        m.className='catalog-meta';
        [c.brand,c.packaging,c.barcode&&('EAN : '+c.barcode)]
          .filter(Boolean)
          .forEach(x=>{
            const chip=document.createElement('span');
            chip.className='catalog-chip';
            chip.textContent=x;
            m.appendChild(chip);
          });
        a.appendChild(m);
      }

      list.appendChild(a);
    });

    if($('barcodeLiveView')) $('barcodeLiveView').hidden=true;
    $('catalogResults').hidden=false;
    $('catalogModes').hidden=true;
    $('catalogCapture').hidden=true;
    updateValidationButton();
  }
  async function onDetected(raw){if(!scanning)return;const code=normalizeCode(raw);if(!code)return;scanning=false;stopCameraOnly();showDetected(code);try{renderResult(await lookup(code))}catch{showDetected(code);setStatus('Produit inconnu de nos référentiels. Complète son identité : le code restera associé.');$('barcodeUnknownActions').hidden=false}}
  async function aiReadFrame(){if(!scanning||aiBusy)return;const canvas=captureFrame();if(!canvas)return;aiBusy=true;$('barcodeTarget')?.classList.add('locking');setStatus('Capture automatique — l’IA cherche le numéro…');try{const blob=await new Promise(r=>canvas.toBlob(r,'image/jpeg',.88));const fd=new FormData();fd.append('image',blob,'barcode.jpg');fd.append('source','barcode');const token=localStorage.getItem('whatzabi_token')||'';const r=await fetch('/pwa/catalog/analyze',{method:'POST',headers:{Authorization:`Bearer ${token}`},body:fd});if(r.ok){const b=await r.json(),candidate=(b.candidates||[]).find(c=>normalizeCode(c.barcode));const code=normalizeCode(candidate?.barcode);if(code){const data=canvas.toDataURL('image/jpeg',.88);$('barcodeAutoCapture').src=data;$('barcodeAutoCapture').hidden=false;sessionStorage.setItem('whatzabi_barcode_capture',data);await onDetected(code);return}}}catch{}finally{aiBusy=false;$('barcodeTarget')?.classList.remove('locking')}if(scanning)setStatus('Aucun EAN lisible — rapproche le code, je continue automatiquement.')}
  function startAILoop(){if(aiTimer)clearInterval(aiTimer);setTimeout(()=>aiReadFrame(),700);aiTimer=setInterval(()=>aiReadFrame(),2200)}
  async function openCamera(){nativeStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:1920},height:{ideal:1080}},audio:false});const video=$('barcodeLiveVideo');video.srcObject=nativeStream;await video.play();const track=nativeStream.getVideoTracks()[0];try{const caps=track.getCapabilities?.()||{},advanced=[];if(caps.focusMode?.includes('continuous'))advanced.push({focusMode:'continuous'});if(advanced.length)await track.applyConstraints({advanced})}catch{}setStatus('Recherche du code-barres…');startAILoop()}
  async function startNativeDetector(){if(!('BarcodeDetector'in window))return;const formats=await BarcodeDetector.getSupportedFormats(),wanted=['ean_13','ean_8','upc_a','upc_e','code_128'].filter(f=>formats.includes(f));if(!wanted.length)return;const detector=new BarcodeDetector({formats:wanted}),video=$('barcodeLiveVideo');const scan=async()=>{if(!scanning)return;try{const codes=await detector.detect(video);if(codes?.[0]?.rawValue){onDetected(codes[0].rawValue);return}}catch{}nativeTimer=setTimeout(scan,140)};scan()}
  async function startZXingWatcher(){try{const Z=await loadZXing(),reader=new Z.BrowserMultiFormatReader();controls=await reader.decodeFromVideoElement($('barcodeLiveVideo'),r=>{if(r)onDetected(r.getText?r.getText():r.text)})}catch{}}
  async function startLiveScanner(){const sheet=$('catalogSheet');if(sheet)sheet.hidden=false;ensureUI();detectedBarcode='';aiBusy=false;sessionStorage.removeItem('whatzabi_pending_barcode');sessionStorage.removeItem('whatzabi_barcode_capture');sessionStorage.removeItem('whatzabi_catalog_selected');$('barcodeDetectedBox').hidden=true;$('barcodeUnknownActions').hidden=true;$('barcodeAutoCapture').hidden=true;$('barcodeTarget')?.classList.remove('detected','locking');$('catalogModes').hidden=true;$('catalogCapture').hidden=true;$('catalogResults').hidden=true;$('barcodeLiveView').hidden=false;scanning=true;setStatus('Ouverture de la caméra…');try{await openCamera();startNativeDetector().catch(()=>{});startZXingWatcher().catch(()=>{})}catch{scanning=false;stopCameraOnly();setStatus('Impossible d’ouvrir la caméra. Utilise Photo produit.')}}
  function stopCameraOnly(){if(nativeTimer){clearTimeout(nativeTimer);nativeTimer=null}if(aiTimer){clearInterval(aiTimer);aiTimer=null}try{controls?.stop?.()}catch{}controls=null;if(nativeStream){nativeStream.getTracks().forEach(t=>t.stop());nativeStream=null}const v=$('barcodeLiveVideo');if(v?.srcObject){v.srcObject.getTracks().forEach(t=>t.stop());v.srcObject=null}}
  function stopLiveScanner(){scanning=false;stopCameraOnly();if($('barcodeLiveView'))if($('barcodeLiveView')) $('barcodeLiveView').hidden=true;$('catalogModes').hidden=false;$('catalogCapture').hidden=true;$('catalogResults').hidden=true}
  function openPhotoFallback(){const c=detectedBarcode;stopCameraOnly();if($('barcodeLiveView')) $('barcodeLiveView').hidden=true;$('catalogModes').hidden=false;if(c)sessionStorage.setItem('whatzabi_pending_barcode',c);document.querySelector('[data-catalog-source="product"]')?.click()}
  function saveManualDraft(name,source){const n=String(name||'').trim();if(!n)return;const d={source:'barcode',candidates:[{name:n,barcode:detectedBarcode,confidence:1}],matches:{},requires_confirmation:true,identification_source:source};try{catalogAnalysis=d}catch{}sessionStorage.setItem('whatzabi_catalog_draft',JSON.stringify(d));sessionStorage.setItem('whatzabi_pending_barcode',detectedBarcode);if($('barcodeLiveView')) $('barcodeLiveView').hidden=true;renderResult(d)}
  function enterName(){const n=window.prompt(`Nom du produit\nEAN / GTIN : ${detectedBarcode}`,'');if(n)saveManualDraft(n,'manual')}
  function dictateName(){const S=window.SpeechRecognition||window.webkitSpeechRecognition;if(!S){setStatus('Dictée indisponible.');return}const r=new S();r.lang='fr-FR';r.onresult=e=>saveManualDraft(e.results?.[0]?.[0]?.transcript||'','voice');r.start()}
  function selectedIndex(){const raw=sessionStorage.getItem('whatzabi_catalog_selected');const i=raw===null?0:Number(raw);return Number.isInteger(i)&&i>=0?i:0}
  function markSelectedCard(index){
    const cards=[...document.querySelectorAll('#catalogCandidateList .catalog-candidate')];

    cards.forEach((card,i)=>{
      card.style.outline=i===index?'3px solid #0f766e':'';
      card.style.cursor='pointer';
      card.setAttribute('aria-selected',i===index?'true':'false');
    });

    sessionStorage.setItem(
      'whatzabi_catalog_selected',
      String(index)
    );
  }

  function updateValidationButton(){
    const btn=$('catalogPrepareBtn');
    if(!btn) return;

    const code=normalizeCode(
      sessionStorage.getItem('whatzabi_pending_barcode')
    );

    if(code){
      btn.textContent='✓ Valider et ajouter au catalogue';
      btn.hidden=false;
    }else if(catalogSource === 'product'){
      btn.textContent='✏️ Compléter la fiche produit';
      btn.hidden=false;
    }else if(catalogSource === 'invoice'){
      btn.textContent='✓ Vérifier les produits sélectionnés';
      btn.hidden=false;
    }else{
      btn.textContent='✓ Valider';
      btn.hidden=false;
    }

    const cards=[
      ...document.querySelectorAll(
        '#catalogCandidateList .catalog-candidate'
      )
    ];

    if(
      catalogSource !== 'invoice' &&
      cards.length===1 &&
      sessionStorage.getItem('whatzabi_catalog_selected')===null
    ){
      markSelectedCard(0);
    }
  }

  function exactExistingMatch(body,index,candidate){const matches=body?.matches?.[String(index)]||body?.matches?.[index]||[];const target=String(candidate?.name||'').trim().toLocaleLowerCase();return matches.find(m=>m.score>=0.99&&String(m.name||'').trim().toLocaleLowerCase()===target)||null}
  async function createValidatedProduct(candidate){const payload={name:String(candidate?.name||'').trim(),product_type:null,brand:candidate?.brand||null,variant:candidate?.variant||null,packaging:candidate?.packaging||null,unit:candidate?.unit||'unité',stock:Number(candidate?.quantity||0),purchase_price:Number(candidate?.purchase_price||0),price:0,threshold:0};if(!payload.name)throw new Error('Nom du produit manquant.');const token=localStorage.getItem('whatzabi_token')||'',r=await fetch('/pwa/products',{method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body:JSON.stringify(payload)});let body=null;try{body=await r.json()}catch{}if(!r.ok)throw new Error(body?.detail||'Impossible de créer le produit.');return body}
  async function addSelectedPhotoProduct(e){
    if(e){
      e.preventDefault();
      e.stopImmediatePropagation();
    }

    let body=null;
    try{
      body=catalogAnalysis;
    }catch{}

    if(!body){
      try{
        body=JSON.parse(
          sessionStorage.getItem('whatzabi_catalog_draft') || 'null'
        );
      }catch{}
    }

    const candidates=body?.candidates || [];
    if(!candidates.length){
      try{ toast('Aucun produit à préparer.'); }catch{}
      return;
    }

    const index=Math.min(selectedIndex(), candidates.length - 1);
    const candidate=candidates[index];
    const existing=exactExistingMatch(body, index, candidate);

    const sheet=$('catalogSheet');
    if(sheet) sheet.hidden=true;

    sessionStorage.removeItem('whatzabi_catalog_selected');

    if(existing && typeof window.whatzabiEditProduct === 'function'){
      window.whatzabiEditProduct(existing.product_id);
      try{ toast(`Produit déjà présent : ${candidate.name}. Tu peux le modifier.`); }catch{}
      return;
    }

    if(typeof window.whatzabiOpenProductDraft !== 'function'){
      try{ toast('Le formulaire produit est indisponible.'); }catch{}
      return;
    }

    window.whatzabiOpenProductDraft(candidate);
    try{ toast(`Produit reconnu : ${candidate.name}. Complète la fiche avant validation.`); }catch{}
  }

  async function convertInvoiceCandidates(items){
    const convertible=[];
    const output=items.map((item,index)=>{
      const candidate={...(item.candidate||{})};

      if(candidate.purchase_price == null){
        return {...item,candidate};
      }

      if(!candidate.currency){
        return {
          ...item,
          candidate:{
            ...candidate,
            purchase_price:null,
            invoice_currency_unresolved:true
          }
        };
      }

      convertible.push({
        index,
        amount:String(candidate.purchase_price),
        from_currency:String(candidate.currency).toUpperCase()
      });

      return {...item,candidate};
    });

    if(!convertible.length){
      return output;
    }

    const token=localStorage.getItem('whatzabi_token')||'';
    const started=performance.now();

    const response=await fetch('/pwa/currencies/convert-batch',{
      method:'POST',
      headers:{
        Authorization:`Bearer ${token}`,
        'Content-Type':'application/json'
      },
      body:JSON.stringify({items:convertible})
    });

    let body=null;
    try{body=await response.json()}catch{}

    if(!response.ok){
      throw new Error(
        body?.detail || 'Conversion de devise impossible.'
      );
    }

    (body?.items||[]).forEach(row=>{
      const target=output[Number(row.index)];
      if(!target) return;

      target.candidate={
        ...target.candidate,
        purchase_price:Number(row.converted_amount),
        currency:row.to_currency,
        invoice_original_price:String(row.amount),
        invoice_original_currency:row.from_currency,
        invoice_exchange_rate:String(row.rate),
        invoice_rate_date:row.rate_date,
        invoice_rate_source:row.source
      };
    });

    console.info(
      '[SMART-CATALOG] conversion facture',
      Math.round(performance.now()-started)+' ms',
      'lines='+convertible.length,
      'rates='+(body?.rates?.length||0)
    );

    return output;
  }

  async function prepareInvoiceProducts(e){
    if(e){
      e.preventDefault();
      e.stopImmediatePropagation();
    }

    let body=null;
    try{body=catalogAnalysis}catch{}
    if(!body){
      try{
        body=JSON.parse(
          sessionStorage.getItem('whatzabi_catalog_draft') || 'null'
        );
      }catch{}
    }

    const candidates=body?.candidates||[];
    const cards=[
      ...document.querySelectorAll(
        '#catalogCandidateList .catalog-candidate[data-invoice-index]'
      )
    ];

    const prepared=[];

    cards.forEach(card=>{
      const selected=card.querySelector('.invoice-line-selected');
      if(selected && !selected.checked) return;

      const index=Number(card.dataset.invoiceIndex);
      const original=candidates[index]||{};

      const candidate={
        ...original,
        name:String(
          card.querySelector('.invoice-line-name')?.value||
          original.name||
          ''
        ).trim(),
        quantity:Math.max(
          0,
          Number(
            card.querySelector('.invoice-line-quantity')?.value||
            original.quantity||
            0
          )
        ),
        purchase_price:(()=>{
          const raw=String(
            card.querySelector('.invoice-line-purchase-price')?.value ?? ''
          ).trim();
          if(raw==='') return null;
          const value=Number(raw);
          return Number.isFinite(value) ? Math.max(0,value) : null;
        })()
      };

      if(!candidate.name) return;

      const match=exactExistingMatch(body,index,candidate);

      prepared.push({
        candidate,
        existing_product_id:match?.product_id||null
      });
    });

    if(!prepared.length){
      try{toast('Sélectionne au moins une ligne de facture.')}catch{}
      return;
    }

    const sheet=$('catalogSheet');
    if(sheet) sheet.hidden=true;

    if(typeof window.whatzabiOpenInvoiceDrafts!=='function'){
      try{toast('Le formulaire de validation facture est indisponible.')}catch{}
      return;
    }

    try{
      const converted=await convertInvoiceCandidates(prepared);
      window.whatzabiOpenInvoiceDrafts(converted);
    }catch(err){
      try{toast(err?.message||'Conversion de devise impossible.')}catch{}
    }
  }

  async function associateValidatedBarcode(code,productId){const token=localStorage.getItem('whatzabi_token')||'',r=await fetch(`/pwa/catalog/barcode/${encodeURIComponent(code)}/associate`,{method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body:JSON.stringify({product_id:Number(productId)})});let body=null;try{body=await r.json()}catch{}if(!r.ok)throw new Error(body?.detail||'Impossible d’associer le code-barres.');return body}
  async function validatePendingBarcode(e){const code=normalizeCode(sessionStorage.getItem('whatzabi_pending_barcode'));if(!code)return;if(e){e.preventDefault();e.stopImmediatePropagation()}if(validationBusy)return;let body=null;try{body=catalogAnalysis}catch{}if(!body){try{body=JSON.parse(sessionStorage.getItem('whatzabi_catalog_draft')||'null')}catch{}}const candidates=body?.candidates||[];if(!candidates.length){toast?.('Photographie ou saisis d’abord le produit.');return}const index=Math.min(selectedIndex(),candidates.length-1),candidate=candidates[index];validationBusy=true;const btn=$('catalogPrepareBtn');if(btn){btn.disabled=true;btn.textContent='Validation…'}try{const match=exactExistingMatch(body,index,candidate);const product=match?{id:match.product_id}:await createValidatedProduct(candidate);const learned=await associateValidatedBarcode(code,product.id);sessionStorage.removeItem('whatzabi_pending_barcode');sessionStorage.removeItem('whatzabi_catalog_selected');sessionStorage.setItem('whatzabi_catalog_draft',JSON.stringify(learned));try{await refresh()}catch{}try{toast(`Produit validé — EAN ${code} mémorisé par Whatzabi`)}catch{}renderResult(learned);if(btn){btn.textContent='✓ Produit mémorisé';btn.disabled=true}}catch(err){try{toast(err.message)}catch{}if(btn){btn.disabled=false;btn.textContent='✓ Valider et ajouter au catalogue'}}finally{validationBusy=false}}
  document.addEventListener('click',e=>{const b=e.target.closest('[data-catalog-source="barcode"]');if(!b)return;e.preventDefault();e.stopImmediatePropagation();startLiveScanner()},true);

  function openCatalogMenu(){
    scanning=false;
    stopCameraOnly();

    const sheet=$('catalogSheet');
    if(sheet) sheet.hidden=false;

    if($('barcodeLiveView')) if($('barcodeLiveView')) $('barcodeLiveView').hidden=true;
    if($('catalogModes')) $('catalogModes').hidden=false;
    if($('catalogCapture')) $('catalogCapture').hidden=true;
    if($('catalogResults')) $('catalogResults').hidden=true;

    if($('catalogTitle')){
      $('catalogTitle').textContent='Ajouter un produit';
    }

    if($('catalogStatus')){
      $('catalogStatus').textContent='';
    }

    sessionStorage.removeItem('whatzabi_catalog_selected');
  }

  window.whatzabiOpenCatalogMenu = function(event){
    if(event){
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
    }

    openCatalogMenu();
    return false;
  };


  $('quickScanner')?.addEventListener('click', function(event){
    event.preventDefault();
    event.stopPropagation();
    startLiveScanner();
  });


  // Photo produit / Facture
  let catalogSource = 'product';
  let catalogFile = null;
  let catalogObjectUrl = null;
  let catalogAnalyzeBusy = false;

  function resetCatalogFile(){
    catalogFile = null;

    if(catalogObjectUrl){
      URL.revokeObjectURL(catalogObjectUrl);
      catalogObjectUrl = null;
    }

    const preview = $('catalogPreview');
    if(preview) preview.removeAttribute('src');

    if($('catalogPreviewWrap')) $('catalogPreviewWrap').hidden = true;
    if($('catalogAnalyzeBtn')) $('catalogAnalyzeBtn').disabled = true;
    if($('catalogStatus')) $('catalogStatus').textContent = '';

    if($('catalogCameraInput')) $('catalogCameraInput').value = '';
    if($('catalogGalleryInput')) $('catalogGalleryInput').value = '';
  }

  function openImageCatalog(source){
    catalogSource = source === 'invoice' ? 'invoice' : 'product';

    sessionStorage.removeItem(
      'whatzabi_catalog_selected'
    );

    scanning = false;
    stopCameraOnly();
    resetCatalogFile();

    const sheet = $('catalogSheet');
    if(sheet) sheet.hidden = false;

    if($('barcodeLiveView')) $('barcodeLiveView').hidden = true;
    if($('catalogModes')) $('catalogModes').hidden = true;
    if($('catalogResults')) $('catalogResults').hidden = true;
    if($('catalogCapture')) $('catalogCapture').hidden = false;

    if($('catalogTitle')){
      $('catalogTitle').textContent =
        catalogSource === 'invoice'
          ? 'Scanner une facture'
          : 'Photographier un produit';
    }

    if($('catalogCaptureHint')){
      $('catalogCaptureHint').textContent =
        catalogSource === 'invoice'
          ? 'Photographie la facture entière, bien à plat et avec le texte lisible.'
          : 'Photographie le produit en montrant si possible le nom, la marque ou l’étiquette.';
    }

    if($('catalogStatus')){
      $('catalogStatus').textContent =
        'Prends une photo ou choisis une image dans la galerie.';
    }
  }

  function selectCatalogFile(file){
    if(!file) return;

    if(!String(file.type || '').startsWith('image/')){
      if($('catalogStatus')){
        $('catalogStatus').textContent =
          'Le fichier sélectionné doit être une image.';
      }
      return;
    }

    catalogFile = file;

    if(catalogObjectUrl){
      URL.revokeObjectURL(catalogObjectUrl);
    }

    catalogObjectUrl = URL.createObjectURL(file);

    const preview = $('catalogPreview');
    if(preview) preview.src = catalogObjectUrl;

    if($('catalogPreviewWrap')) $('catalogPreviewWrap').hidden = false;
    if($('catalogAnalyzeBtn')) $('catalogAnalyzeBtn').disabled = false;

    if($('catalogStatus')){
      $('catalogStatus').textContent =
        catalogSource === 'invoice'
          ? 'Facture prête à être analysée.'
          : 'Photo prête à être analysée.';
    }
  }


  window.whatzabiReceiveCatalogImage = function(input){
    const files = input?.files;

    console.log(
      '[SMART-CATALOG] native onchange',
      input?.id,
      files?.length || 0
    );

    if(!files || files.length === 0){
      if($('catalogStatus')){
        $('catalogStatus').textContent =
          'Aucune photo reçue par l’iPhone.';
      }
      return;
    }

    const file = files[0];

    console.log(
      '[SMART-CATALOG] fichier reçu',
      file.name,
      file.type,
      file.size
    );

    selectCatalogFile(file);
  };


  window.whatzabiAnalyzeCatalogImage = function(event){
    if(event){
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
    }

    if(!catalogFile){
      if($('catalogStatus')){
        $('catalogStatus').textContent =
          'Choisis ou prends d’abord une photo.';
      }
      return false;
    }

    analyzeCatalogImage();
    return false;
  };

  async function prepareCatalogImage(file){
    if(!file || !String(file.type || '').startsWith('image/')) return file;

    try{
      const dataUrl=await new Promise((resolve,reject)=>{
        const reader=new FileReader();
        reader.onload=()=>resolve(reader.result);
        reader.onerror=()=>reject(new Error('Lecture image impossible'));
        reader.readAsDataURL(file);
      });

      const image=await new Promise((resolve,reject)=>{
        const element=new Image();
        element.onload=()=>resolve(element);
        element.onerror=()=>reject(new Error('Décodage image impossible'));
        element.src=dataUrl;
      });

      const maxSide=catalogSource === 'invoice' ? 1600 : 1400;
      const ratio=Math.min(1,maxSide/Math.max(image.width,image.height));
      const canvas=document.createElement('canvas');
      canvas.width=Math.max(1,Math.round(image.width*ratio));
      canvas.height=Math.max(1,Math.round(image.height*ratio));
      canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);

      const quality=catalogSource === 'invoice' ? 0.78 : 0.82;
      return await new Promise((resolve,reject)=>{
        canvas.toBlob(
          blob=>blob ? resolve(blob) : reject(new Error('Compression image impossible')),
          'image/jpeg',
          quality
        );
      });
    }catch(err){
      console.warn('[SMART-CATALOG] compression ignorée', err);
      return file;
    }
  }

  async function analyzeCatalogImage(){
    if(!catalogFile || catalogAnalyzeBusy) return;

    const btn = $('catalogAnalyzeBtn');
    const status = $('catalogStatus');

    catalogAnalyzeBusy = true;

    if(btn){
      btn.disabled = true;
      btn.textContent = '⏳ Analyse en cours…';
    }

    if(status){
      status.textContent =
        catalogSource === 'invoice'
          ? 'Lecture de la facture…'
          : 'Reconnaissance du produit…';
    }

    try{
      const startedAt=performance.now();
      if(status) status.textContent =
        catalogSource === 'invoice'
          ? 'Préparation et lecture de la facture…'
          : 'Préparation et reconnaissance du produit…';

      const prepareStarted=performance.now();
      const preparedImage=await prepareCatalogImage(catalogFile);
      const prepareMs=Math.round(performance.now()-prepareStarted);
      const fd = new FormData();
      fd.append(
        'image',
        preparedImage,
        preparedImage === catalogFile
          ? (catalogFile.name || 'catalog-image.jpg')
          : 'catalog-image.jpg'
      );
      fd.append('source', catalogSource);

      const token = localStorage.getItem('whatzabi_token') || '';

      const networkStarted=performance.now();
      const response = await fetch('/pwa/catalog/analyze', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`
        },
        body: fd
      });

      const networkMs=Math.round(performance.now()-networkStarted);

      const parseStarted=performance.now();
      let body = null;
      try{
        body = await response.json();
      }catch{}
      const parseMs=Math.round(performance.now()-parseStarted);

      if(!response.ok){
        throw new Error(
          body?.detail ||
          `Analyse impossible (${response.status}).`
        );
      }

      if(!(body?.candidates || []).length){
        throw new Error(
          catalogSource === 'invoice'
            ? 'Aucune ligne de produit exploitable détectée sur cette facture.'
            : 'Produit non identifié. Essaie avec le nom ou l’étiquette bien visible.'
        );
      }

      try{
        catalogAnalysis = body;
      }catch{}

      sessionStorage.setItem(
        'whatzabi_catalog_draft',
        JSON.stringify(body)
      );

      const renderStarted=performance.now();
      renderResult(body);
      const renderMs=Math.round(performance.now()-renderStarted);
      const totalMs=Math.round(performance.now()-startedAt);

      console.info(
        '[SMART-CATALOG] timings',
        {
          source:catalogSource,
          prepare_ms:prepareMs,
          network_server_ms:networkMs,
          parse_ms:parseMs,
          render_ms:renderMs,
          total_ms:totalMs,
          bytes:preparedImage?.size||0,
          candidates:(body?.candidates||[]).length
        }
      );

      if(status) status.textContent = '';

    }catch(err){
      const message =
        err?.message || 'Analyse Smart Catalog impossible.';

      if(status) status.textContent = message;

      try{
        toast?.(message);
      }catch{}

    }finally{
      catalogAnalyzeBusy = false;

      if(btn){
        btn.disabled = !catalogFile;
        btn.textContent = '✨ Analyser avec Whatzabi';
      }
    }
  }

  document.addEventListener('click', e => {
    const button = e.target.closest(
      '[data-catalog-source="product"],[data-catalog-source="invoice"]'
    );

    if(!button) return;

    e.preventDefault();
    e.stopImmediatePropagation();

    openImageCatalog(button.dataset.catalogSource);
  }, true);






  document.addEventListener('click',e=>{
  if(e.target.closest('#catalogCloseBtn')){
    scanning=false;
    stopCameraOnly();
    const sheet=$('catalogSheet');
    if(sheet) sheet.hidden=true;
    if($('barcodeLiveView')) if($('barcodeLiveView')) $('barcodeLiveView').hidden=true;
    return;
  }
  if(e.target.closest('#catalogRestartBtn')){
    e.preventDefault();
    e.stopImmediatePropagation();
    openCatalogMenu();
    return;
  }
},true);
  document.addEventListener('click',e=>{const card=e.target.closest('#catalogCandidateList .catalog-candidate');if(!card)return;const cards=[...document.querySelectorAll('#catalogCandidateList .catalog-candidate')],index=cards.indexOf(card);if(index>=0)markSelectedCard(index)});
  document.addEventListener('click',e=>{
    if(!e.target.closest('#catalogPrepareBtn')) return;

    const code=normalizeCode(
      sessionStorage.getItem('whatzabi_pending_barcode')
    );

    // Le fallback Photo d'un code-barres conserve
    // volontairement le workflow barcode.
    if(code){
      validatePendingBarcode(e);
      return;
    }

    if(catalogSource === 'product'){
      addSelectedPhotoProduct(e);
      return;
    }

    if(catalogSource === 'invoice'){
      prepareInvoiceProducts(e);
      return;
    }
  },true);
  const observer=new MutationObserver(()=>updateValidationButton());const list=$('catalogCandidateList');if(list)observer.observe(list,{childList:true});
})();
