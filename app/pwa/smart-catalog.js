(() => {
  let controls=null,scanning=false,zxingPromise=null,detectedBarcode='',nativeStream=null,nativeTimer=null,aiTimer=null,aiBusy=false,validationBusy=false;
  const $=id=>document.getElementById(id);
  function ensureUI(){if($('barcodeLiveView'))return;const v=document.createElement('section');v.id='barcodeLiveView';v.className='barcode-live-view';v.hidden=true;v.innerHTML=`<div class="barcode-live-head"><button id="barcodeLiveBack" type="button" class="ghost">‹ Retour</button><strong>Scanner le code-barres</strong></div><div class="barcode-camera-frame"><video id="barcodeLiveVideo" autoplay playsinline muted></video><div id="barcodeTarget" class="barcode-target" aria-hidden="true"><span></span></div></div><div id="barcodeDetectedBox" hidden style="margin:14px 0;padding:12px;border-radius:14px;background:#e8f3f1;text-align:center"><small style="display:block;color:#607874">✓ Code-barres détecté</small><strong id="barcodeDetectedValue" style="display:block;margin-top:4px;font-size:20px;letter-spacing:.06em"></strong></div><img id="barcodeAutoCapture" hidden alt="Capture automatique" style="width:100%;max-height:150px;object-fit:contain;border-radius:12px;margin:8px 0"><p id="barcodeLiveStatus" class="barcode-live-status">Recherche du code-barres…</p><p class="muted small">Garde le code dans le cadre. Whatzabi capture automatiquement des images et l’IA tente de lire l’EAN.</p><button id="barcodePhotoNow" type="button" class="ghost" style="width:100%;margin:8px 0">📷 Photo produit</button><input id="barcodeProductPhotoInput" type="file" accept="image/*" capture="environment" hidden><div id="barcodeUnknownActions" hidden style="display:grid;gap:8px"><button id="barcodePhotoFallback" type="button">📷 Photographier le produit</button><button id="barcodeNameBtn" type="button" class="ghost">⌨️ Saisir le nom</button><button id="barcodeVoiceBtn" type="button" class="ghost">🎙️ Dicter le nom</button></div>`;document.querySelector('.catalog-sheet-card')?.appendChild(v);$('barcodeLiveBack').onclick=stopLiveScanner;$('barcodePhotoNow').onclick=chooseProductPhoto;$('barcodeProductPhotoInput').onchange=handleProductPhoto;$('barcodePhotoFallback').onclick=chooseProductPhoto;$('barcodeNameBtn').onclick=enterName;$('barcodeVoiceBtn').onclick=dictateName}
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
  async function startLiveScanner(){const sheet=$('catalogSheet');if(sheet)sheet.hidden=false;ensureUI();detectedBarcode='';aiBusy=false;sessionStorage.removeItem('whatzabi_pending_barcode');sessionStorage.removeItem('whatzabi_barcode_capture');sessionStorage.removeItem('whatzabi_catalog_selected');sessionStorage.removeItem('whatzabi_catalog_draft');const prepare=$('catalogPrepareBtn');if(prepare){prepare.disabled=false;prepare.hidden=false;prepare.textContent='✓ Valider'}$('catalogDetectedBox')?.removeAttribute('data-unused');$('barcodeDetectedBox').hidden=true;$('barcodeUnknownActions').hidden=true;$('barcodeAutoCapture').hidden=true;$('barcodeTarget')?.classList.remove('detected','locking');$('catalogModes').hidden=true;$('catalogCapture').hidden=true;$('catalogResults').hidden=true;$('barcodeLiveView').hidden=false;scanning=true;setStatus('Ouverture de la caméra…');try{await openCamera();startNativeDetector().catch(()=>{});startZXingWatcher().catch(()=>{})}catch{scanning=false;stopCameraOnly();setStatus('Impossible d’ouvrir la caméra. Utilise Photo produit.')}}
  function stopCameraOnly(){if(nativeTimer){clearTimeout(nativeTimer);nativeTimer=null}if(aiTimer){clearInterval(aiTimer);aiTimer=null}try{controls?.stop?.()}catch{}controls=null;if(nativeStream){nativeStream.getTracks().forEach(t=>t.stop());nativeStream=null}const v=$('barcodeLiveVideo');if(v?.srcObject){v.srcObject.getTracks().forEach(t=>t.stop());v.srcObject=null}}
  function stopLiveScanner(){scanning=false;stopCameraOnly();if($('barcodeLiveView'))$('barcodeLiveView').hidden=true;$('catalogModes').hidden=false;$('catalogCapture').hidden=true;$('catalogResults').hidden=true}
  function chooseProductPhoto(){scanning=false;stopCameraOnly();$('barcodeProductPhotoInput')?.click()}
  async function handleProductPhoto(e){
    const input=e?.target;
    const file=input?.files?.[0];
    if(input)input.value='';
    if(!file)return;

    scanning=false;
    stopCameraOnly();
    setStatus('Analyse de la photo produit…');

    const fd=new FormData();
    fd.append('image',file,file.name||'product.jpg');
    fd.append('source','product');

    const token=localStorage.getItem('whatzabi_token')||'';

    try{
      const r=await fetch('/pwa/catalog/analyze',{
        method:'POST',
        headers:{Authorization:`Bearer ${token}`},
        body:fd
      });

      let body=null;
      try{body=await r.json()}catch{}

      if(!r.ok){
        throw new Error(body?.detail||'Impossible d’analyser la photo.');
      }

      if(!body?.candidates?.length){
        throw new Error('Produit non reconnu. Reprends une photo.');
      }

      if(detectedBarcode){
        body.candidates=body.candidates.map((c,i)=>
          i===0?{...c,barcode:c.barcode||detectedBarcode}:c
        );
        sessionStorage.setItem('whatzabi_pending_barcode',detectedBarcode);
      }

      sessionStorage.setItem('whatzabi_catalog_draft',JSON.stringify(body));
      renderResult(body);
    }catch(err){
      $('barcodeLiveView').hidden=false;
      setStatus(err.message||'Impossible d’analyser la photo.');
      try{toast(err.message||'Impossible d’analyser la photo.')}catch{}
    }
  }
  function saveManualDraft(name,source){const n=String(name||'').trim();if(!n)return;const d={source:'barcode',candidates:[{name:n,barcode:detectedBarcode,confidence:1}],matches:{},requires_confirmation:true,identification_source:source};try{catalogAnalysis=d}catch{}sessionStorage.setItem('whatzabi_catalog_draft',JSON.stringify(d));sessionStorage.setItem('whatzabi_pending_barcode',detectedBarcode);$('barcodeLiveView').hidden=true;renderResult(d)}
  function enterName(){const n=window.prompt(`Nom du produit\nEAN / GTIN : ${detectedBarcode}`,'');if(n)saveManualDraft(n,'manual')}
  function dictateName(){const S=window.SpeechRecognition||window.webkitSpeechRecognition;if(!S){setStatus('Dictée indisponible.');return}const r=new S();r.lang='fr-FR';r.onresult=e=>saveManualDraft(e.results?.[0]?.[0]?.transcript||'','voice');r.start()}
  function selectedIndex(){const raw=sessionStorage.getItem('whatzabi_catalog_selected');const i=raw===null?0:Number(raw);return Number.isInteger(i)&&i>=0?i:0}
  function markSelectedCard(index){const cards=[...document.querySelectorAll('#catalogCandidateList .catalog-candidate')];cards.forEach((card,i)=>{card.style.outline=i===index?'3px solid #0f766e':'';card.style.cursor='pointer';card.setAttribute('aria-selected',i===index?'true':'false')});sessionStorage.setItem('whatzabi_catalog_selected',String(index));updateValidationButton()}
  function updateValidationButton(){const btn=$('catalogPrepareBtn');if(!btn)return;const code=normalizeCode(sessionStorage.getItem('whatzabi_pending_barcode'));if(code){btn.textContent='✓ Valider et ajouter au catalogue';btn.hidden=false}else{btn.textContent='Ajouter au catalogue';btn.hidden=false}const cards=[...document.querySelectorAll('#catalogCandidateList .catalog-candidate')];if(cards.length===1)markSelectedCard(0)}
  function exactExistingMatch(body,index,candidate){const matches=body?.matches?.[String(index)]||body?.matches?.[index]||[];const target=String(candidate?.name||'').trim().toLocaleLowerCase();return matches.find(m=>m.score>=0.99&&String(m.name||'').trim().toLocaleLowerCase()===target)||null}
  async function createValidatedProduct(candidate){const payload={name:String(candidate?.name||'').trim(),product_type:null,brand:candidate?.brand||null,variant:candidate?.variant||null,packaging:candidate?.packaging||null,unit:candidate?.unit||'unité',stock:Number(candidate?.quantity||0),purchase_price:Number(candidate?.purchase_price||0),price:0,threshold:0};if(!payload.name)throw new Error('Nom du produit manquant.');const token=localStorage.getItem('whatzabi_token')||'',r=await fetch('/pwa/products',{method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body:JSON.stringify(payload)});let body=null;try{body=await r.json()}catch{}if(!r.ok)throw new Error(body?.detail||'Impossible de créer le produit.');return body}
  async function associateValidatedBarcode(code,productId){const token=localStorage.getItem('whatzabi_token')||'',r=await fetch(`/pwa/catalog/barcode/${encodeURIComponent(code)}/associate`,{method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body:JSON.stringify({product_id:Number(productId)})});let body=null;try{body=await r.json()}catch{}if(!r.ok)throw new Error(body?.detail||'Impossible d’associer le code-barres.');return body}
  async function validatePendingBarcode(e){
    if(e){e.preventDefault();e.stopImmediatePropagation()}
    if(validationBusy)return;

    let body=null;
    try{body=catalogAnalysis}catch{}
    if(!body){
      try{body=JSON.parse(sessionStorage.getItem('whatzabi_catalog_draft')||'null')}catch{}
    }

    const candidates=body?.candidates||[];
    if(!candidates.length){
      try{toast('Aucun produit à valider.')}catch{}
      return;
    }

    const index=Math.min(selectedIndex(),candidates.length-1);
    const candidate=candidates[index];
    const code=normalizeCode(sessionStorage.getItem('whatzabi_pending_barcode'));

    validationBusy=true;
    const btn=$('catalogPrepareBtn');

    if(btn){
      btn.disabled=true;
      btn.textContent='Validation…';
    }

    try{
      const match=exactExistingMatch(body,index,candidate);
      const product=match?{id:match.product_id}:await createValidatedProduct(candidate);

      if(code){
        const learned=await associateValidatedBarcode(code,product.id);

        sessionStorage.removeItem('whatzabi_pending_barcode');
        sessionStorage.removeItem('whatzabi_catalog_selected');
        sessionStorage.setItem('whatzabi_catalog_draft',JSON.stringify(learned));

        try{await refresh()}catch{}
        try{toast(`Produit validé — EAN ${code} mémorisé par Whatzabi`)}catch{}

        renderResult(learned);

        if(btn){
          btn.textContent='✓ Produit mémorisé';
          btn.disabled=true;
        }
      }else{
        sessionStorage.removeItem('whatzabi_catalog_selected');

        try{await refresh()}catch{}
        try{toast('Produit ajouté au catalogue')}catch{}

        if(btn){
          btn.textContent='✓ Produit ajouté';
          btn.disabled=true;
        }
      }
    }catch(err){
      try{toast(err.message)}catch{}
      if(btn){
        btn.disabled=false;
        btn.textContent=code
          ? '✓ Valider et ajouter au catalogue'
          : 'Ajouter au catalogue';
      }
    }finally{
      validationBusy=false;
    }
  }
  document.addEventListener('click',e=>{const b=e.target.closest('[data-catalog-source="barcode"]');if(!b)return;e.preventDefault();e.stopImmediatePropagation();startLiveScanner()},true);
  document.addEventListener('click',e=>{
    const restart=e.target.closest('#catalogRestartBtn');
    if(restart){
      e.preventDefault();
      e.stopImmediatePropagation();
      scanning=false;
      stopCameraOnly();
      startLiveScanner();
      return;
    }

    const close=e.target.closest('#catalogCloseBtn');
    if(close){
      e.preventDefault();
      e.stopImmediatePropagation();
      scanning=false;
      stopCameraOnly();
      const sheet=$('catalogSheet');
      if(sheet)sheet.hidden=true;
    }
  },true);
  document.addEventListener('click',e=>{const card=e.target.closest('#catalogCandidateList .catalog-candidate');if(!card)return;const cards=[...document.querySelectorAll('#catalogCandidateList .catalog-candidate')],index=cards.indexOf(card);if(index>=0)markSelectedCard(index)});
  document.addEventListener('click',e=>{if(!e.target.closest('#catalogPrepareBtn'))return;validatePendingBarcode(e)},true);
  const observer=new MutationObserver(()=>updateValidationButton());const list=$('catalogCandidateList');if(list)observer.observe(list,{childList:true});
})();