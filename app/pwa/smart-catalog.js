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
  function renderResult(b){try{catalogAnalysis=b}catch{}const cs=b?.candidates||[],list=$('catalogCandidateList');list.innerHTML='';$('catalogResultCount').textContent=cs.length?`${cs.length} produit détecté`:'Code reconnu';cs.forEach(c=>{const a=document.createElement('article');a.className='catalog-candidate';const h=document.createElement('h3');h.textContent=c.name||'Produit';a.appendChild(h);const m=document.createElement('div');m.className='catalog-meta';[c.brand,c.packaging,c.barcode&&`EAN : ${c.barcode}`].filter(Boolean).forEach(x=>{const s=document.createElement('span');s.className='catalog-chip';s.textContent=x;m.appendChild(s)});a.appendChild(m);list.appendChild(a)});$('barcodeLiveView').hidden=true;$('catalogResults').hidden=false;$('catalogModes').hidden=true;$('catalogCapture').hidden=true;updateValidationButton()}
  async function onDetected(raw){if(!scanning)return;const code=normalizeCode(raw);if(!code)return;scanning=false;stopCameraOnly();showDetected(code);try{renderResult(await lookup(code))}catch{showDetected(code);setStatus('Produit inconnu de nos référentiels. Complète son identité : le code restera associé.');$('barcodeUnknownActions').hidden=false}}
  async function aiReadFrame(){if(!scanning||aiBusy)return;const canvas=captureFrame();if(!canvas)return;aiBusy=true;$('barcodeTarget')?.classList.add('locking');setStatus('Capture automatique — l’IA cherche le numéro…');try{const blob=await new Promise(r=>canvas.toBlob(r,'image/jpeg',.88));const fd=new FormData();fd.append('image',blob,'barcode.jpg');fd.append('source','barcode');const token=localStorage.getItem('whatzabi_token')||'';const r=await fetch('/pwa/catalog/analyze',{method:'POST',headers:{Authorization:`Bearer ${token}`},body:fd});if(r.ok){const b=await r.json(),candidate=(b.candidates||[]).find(c=>normalizeCode(c.barcode));const code=normalizeCode(candidate?.barcode);if(code){const data=canvas.toDataURL('image/jpeg',.88);$('barcodeAutoCapture').src=data;$('barcodeAutoCapture').hidden=false;sessionStorage.setItem('whatzabi_barcode_capture',data);await onDetected(code);return}}}catch{}finally{aiBusy=false;$('barcodeTarget')?.classList.remove('locking')}if(scanning)setStatus('Aucun EAN lisible — rapproche le code, je continue automatiquement.')}
  function startAILoop(){if(aiTimer)clearInterval(aiTimer);setTimeout(()=>aiReadFrame(),700);aiTimer=setInterval(()=>aiReadFrame(),2200)}
  async function openCamera(){nativeStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:1920},height:{ideal:1080}},audio:false});const video=$('barcodeLiveVideo');video.srcObject=nativeStream;await video.play();const track=nativeStream.getVideoTracks()[0];try{const caps=track.getCapabilities?.()||{},advanced=[];if(caps.focusMode?.includes('continuous'))advanced.push({focusMode:'continuous'});if(advanced.length)await track.applyConstraints({advanced})}catch{}setStatus('Recherche du code-barres…');startAILoop()}
  async function startNativeDetector(){if(!('BarcodeDetector'in window))return;const formats=await BarcodeDetector.getSupportedFormats(),wanted=['ean_13','ean_8','upc_a','upc_e','code_128'].filter(f=>formats.includes(f));if(!wanted.length)return;const detector=new BarcodeDetector({formats:wanted}),video=$('barcodeLiveVideo');const scan=async()=>{if(!scanning)return;try{const codes=await detector.detect(video);if(codes?.[0]?.rawValue){onDetected(codes[0].rawValue);return}}catch{}nativeTimer=setTimeout(scan,140)};scan()}
  async function startZXingWatcher(){try{const Z=await loadZXing(),reader=new Z.BrowserMultiFormatReader();controls=await reader.decodeFromVideoElement($('barcodeLiveVideo'),r=>{if(r)onDetected(r.getText?r.getText():r.text)})}catch{}}
  async function startLiveScanner(){const sheet=$('catalogSheet');if(sheet)sheet.hidden=false;ensureUI();detectedBarcode='';aiBusy=false;sessionStorage.removeItem('whatzabi_pending_barcode');sessionStorage.removeItem('whatzabi_barcode_capture');sessionStorage.removeItem('whatzabi_catalog_selected');$('barcodeDetectedBox').hidden=true;$('barcodeUnknownActions').hidden=true;$('barcodeAutoCapture').hidden=true;$('barcodeTarget')?.classList.remove('detected','locking');$('catalogModes').hidden=true;$('catalogCapture').hidden=true;$('catalogResults').hidden=true;$('barcodeLiveView').hidden=false;scanning=true;setStatus('Ouverture de la caméra…');try{await openCamera();startNativeDetector().catch(()=>{});startZXingWatcher().catch(()=>{})}catch{scanning=false;stopCameraOnly();setStatus('Impossible d’ouvrir la caméra. Utilise Photo produit.')}}
  function stopCameraOnly(){if(nativeTimer){clearTimeout(nativeTimer);nativeTimer=null}if(aiTimer){clearInterval(aiTimer);aiTimer=null}try{controls?.stop?.()}catch{}controls=null;if(nativeStream){nativeStream.getTracks().forEach(t=>t.stop());nativeStream=null}const v=$('barcodeLiveVideo');if(v?.srcObject){v.srcObject.getTracks().forEach(t=>t.stop());v.srcObject=null}}
  function stopLiveScanner(){scanning=false;stopCameraOnly();if($('barcodeLiveView'))$('barcodeLiveView').hidden=true;$('catalogModes').hidden=false;$('catalogCapture').hidden=true;$('catalogResults').hidden=true}
  function openPhotoFallback(){const c=detectedBarcode;stopCameraOnly();$('barcodeLiveView').hidden=true;$('catalogModes').hidden=false;if(c)sessionStorage.setItem('whatzabi_pending_barcode',c);document.querySelector('[data-catalog-source="product"]')?.click()}
  function saveManualDraft(name,source){const n=String(name||'').trim();if(!n)return;const d={source:'barcode',candidates:[{name:n,barcode:detectedBarcode,confidence:1}],matches:{},requires_confirmation:true,identification_source:source};try{catalogAnalysis=d}catch{}sessionStorage.setItem('whatzabi_catalog_draft',JSON.stringify(d));sessionStorage.setItem('whatzabi_pending_barcode',detectedBarcode);$('barcodeLiveView').hidden=true;renderResult(d)}
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
      btn.textContent='➕ Ajouter ce produit au catalogue';
      btn.hidden=false;
    }else if(catalogSource === 'invoice'){
      btn.textContent='✓ Ajouter les produits sélectionnés';
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

    if(validationBusy) return;

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
      try{
        toast('Aucun produit à ajouter.');
      }catch{}
      return;
    }

    const index=Math.min(
      selectedIndex(),
      candidates.length - 1
    );

    const candidate=candidates[index];
    const btn=$('catalogPrepareBtn');

    validationBusy=true;

    if(btn){
      btn.disabled=true;
      btn.textContent='Ajout au catalogue…';
    }

    try{
      const existing=exactExistingMatch(
        body,
        index,
        candidate
      );

      if(existing){
        try{
          await refresh();
        }catch{}

        try{
          toast(
            `Produit déjà présent : ${candidate.name}`
          );
        }catch{}

        if(btn){
          btn.textContent='✓ Déjà au catalogue';
          btn.disabled=true;
        }

        return;
      }

      const product=await createValidatedProduct(candidate);

      try{
        await refresh();
      }catch{}

      sessionStorage.removeItem(
        'whatzabi_catalog_selected'
      );

      try{
        toast(
          `Produit ajouté : ${product.name || candidate.name}`
        );
      }catch{}

      if(btn){
        btn.textContent='✓ Produit ajouté';
        btn.disabled=true;
      }

    }catch(err){

      const message=
        err?.message ||
        'Impossible d’ajouter le produit.';

      try{
        toast(message);
      }catch{}

      if(btn){
        btn.disabled=false;
        btn.textContent=
          '➕ Ajouter ce produit au catalogue';
      }

    }finally{
      validationBusy=false;
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

    if($('barcodeLiveView')) $('barcodeLiveView').hidden=true;
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

  document.addEventListener('click',e=>{
    const button=e.target.closest('#quickScanner');
    if(!button)return;

    e.preventDefault();
    e.stopImmediatePropagation();

    openCatalogMenu();
  },true);


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


  function receiveCatalogImage(event){
    const input = event.currentTarget;
    const files = input?.files;

    console.log(
      '[SMART-CATALOG] file event',
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
      '[SMART-CATALOG] photo reçue',
      file.name,
      file.type,
      file.size
    );

    selectCatalogFile(file);
  }

  $('catalogCameraInput')?.addEventListener(
    'change',
    receiveCatalogImage
  );

  $('catalogGalleryInput')?.addEventListener(
    'change',
    receiveCatalogImage
  );

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
      const fd = new FormData();
      fd.append('image', catalogFile, catalogFile.name || 'catalog-image.jpg');
      fd.append('source', catalogSource);

      const token = localStorage.getItem('whatzabi_token') || '';

      const response = await fetch('/pwa/catalog/analyze', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`
        },
        body: fd
      });

      let body = null;
      try{
        body = await response.json();
      }catch{}

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

      renderResult(body);

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





  document.addEventListener('click', e => {
    const btn = e.target.closest('#catalogAnalyzeBtn');
    if(!btn) return;

    e.preventDefault();
    e.stopImmediatePropagation();

    const status = $('catalogStatus');

    if(!catalogFile){
      if(status){
        status.textContent =
          'Aucune image disponible pour l’analyse.';
      }
      return;
    }

    if(catalogAnalyzeBusy) return;

    if(status){
      status.textContent = 'Analyse demandée…';
    }

    analyzeCatalogImage();
  }, true);

  document.addEventListener('click',e=>{
  if(e.target.closest('#catalogCloseBtn')){
    scanning=false;
    stopCameraOnly();
    const sheet=$('catalogSheet');
    if(sheet) sheet.hidden=true;
    if($('barcodeLiveView')) $('barcodeLiveView').hidden=true;
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
      e.preventDefault();
      e.stopImmediatePropagation();

      try{
        toast(
          'Validation multi-produits facture : étape suivante.'
        );
      }catch{}

      return;
    }
  },true);
  const observer=new MutationObserver(()=>updateValidationButton());const list=$('catalogCandidateList');if(list)observer.observe(list,{childList:true});
})();
