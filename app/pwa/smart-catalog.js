(() => {
  let controls=null, scanning=false, zxingPromise=null, detectedBarcode='', nativeStream=null, nativeTimer=null, lastDetectionAt=0;
  const $=id=>document.getElementById(id);

  function ensureUI(){
    if($('barcodeLiveView'))return;
    const v=document.createElement('section');
    v.id='barcodeLiveView';v.className='barcode-live-view';v.hidden=true;
    v.innerHTML=`
      <div class="barcode-live-head"><button id="barcodeLiveBack" type="button" class="ghost">‹ Retour</button><strong>Scanner le code-barres</strong></div>
      <div class="barcode-camera-frame" style="position:relative;overflow:hidden">
        <video id="barcodeLiveVideo" autoplay playsinline muted></video>
        <div id="barcodeTarget" class="barcode-target" aria-hidden="true"><span></span></div>
        <div id="barcodeLockBox" hidden style="position:absolute;border:4px solid #20b486;border-radius:12px;box-shadow:0 0 0 2px rgba(255,255,255,.7),0 0 28px rgba(32,180,134,.55);pointer-events:none;transition:all .08s linear"></div>
        <div id="barcodeFlash" hidden style="position:absolute;inset:0;background:rgba(255,255,255,.7);pointer-events:none"></div>
      </div>
      <div id="barcodeDetectedBox" hidden style="margin:14px 0;padding:12px;border-radius:14px;background:#e8f3f1;text-align:center">
        <small style="display:block;color:#607874">✓ Code-barres détecté et capturé</small>
        <strong id="barcodeDetectedValue" style="display:block;margin-top:4px;font-size:20px;letter-spacing:.06em"></strong>
        <img id="barcodeCapturedPreview" hidden alt="Capture automatique du code-barres" style="display:block;width:100%;max-height:120px;object-fit:contain;margin-top:10px;border-radius:10px;background:#fff">
      </div>
      <p id="barcodeLiveStatus" class="barcode-live-status">Place le code-barres dans le cadre.</p>
      <p class="muted small">Comme une détection de visage : Whatzabi repère, verrouille puis capture automatiquement.</p>
      <div id="barcodeUnknownActions" hidden style="display:grid;gap:8px"><button id="barcodePhotoFallback" type="button">📷 Photographier le produit</button><button id="barcodeNameBtn" type="button" class="ghost">⌨️ Saisir le nom</button><button id="barcodeVoiceBtn" type="button" class="ghost">🎙️ Dicter le nom</button></div>`;
    document.querySelector('.catalog-sheet-card')?.appendChild(v);
    $('barcodeLiveBack').onclick=stopLiveScanner;
    $('barcodePhotoFallback').onclick=openPhotoFallback;
    $('barcodeNameBtn').onclick=enterName;
    $('barcodeVoiceBtn').onclick=dictateName;
  }

  function setStatus(t){if($('barcodeLiveStatus'))$('barcodeLiveStatus').textContent=t}
  function normalizeCode(v){const c=String(v||'').replace(/\D/g,'');return c.length>=8&&c.length<=14?c:''}
  function showDetected(code){detectedBarcode=code;$('barcodeDetectedValue').textContent=`EAN / GTIN : ${code}`;$('barcodeDetectedBox').hidden=false;$('barcodeTarget')?.classList.add('detected');sessionStorage.setItem('whatzabi_pending_barcode',code)}

  function lockBox(box){
    const video=$('barcodeLiveVideo'), frame=video?.parentElement, overlay=$('barcodeLockBox');
    if(!video||!frame||!overlay||!box)return;
    const fw=frame.clientWidth, fh=frame.clientHeight, vw=video.videoWidth||fw, vh=video.videoHeight||fh;
    if(!vw||!vh)return;
    const scale=Math.max(fw/vw,fh/vh), shownW=vw*scale, shownH=vh*scale, offsetX=(fw-shownW)/2, offsetY=(fh-shownH)/2;
    const x=offsetX+box.x*scale, y=offsetY+box.y*scale, w=box.width*scale, h=box.height*scale;
    overlay.style.left=`${Math.max(0,x)}px`;overlay.style.top=`${Math.max(0,y)}px`;overlay.style.width=`${Math.min(fw-Math.max(0,x),w)}px`;overlay.style.height=`${Math.min(fh-Math.max(0,y),h)}px`;overlay.hidden=false;
  }

  async function autoCapture(box){
    const video=$('barcodeLiveVideo');if(!video?.videoWidth||!video?.videoHeight)return null;
    const vw=video.videoWidth,vh=video.videoHeight;
    let sx=0,sy=0,sw=vw,sh=vh;
    if(box?.width&&box?.height){const padX=box.width*.28,padY=box.height*.8;sx=Math.max(0,box.x-padX);sy=Math.max(0,box.y-padY);sw=Math.min(vw-sx,box.width+padX*2);sh=Math.min(vh-sy,box.height+padY*2)}
    else{sw=vw*.82;sh=vh*.42;sx=(vw-sw)/2;sy=(vh-sh)/2}
    const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(sw));canvas.height=Math.max(1,Math.round(sh));const ctx=canvas.getContext('2d');ctx.drawImage(video,sx,sy,sw,sh,0,0,canvas.width,canvas.height);
    const data=canvas.toDataURL('image/jpeg',.88);sessionStorage.setItem('whatzabi_pending_barcode_capture',data);window.whatzabiBarcodeCapture=data;
    const img=$('barcodeCapturedPreview');if(img){img.src=data;img.hidden=false}
    const flash=$('barcodeFlash');if(flash){flash.hidden=false;setTimeout(()=>flash.hidden=true,130)}
    return data;
  }

  function beep(){try{const C=window.AudioContext||window.webkitAudioContext;if(!C)return;const c=new C(),o=c.createOscillator(),g=c.createGain();o.connect(g);g.connect(c.destination);o.frequency.value=880;g.gain.value=.05;o.start();setTimeout(()=>{o.stop();c.close()},90)}catch{}}
  function loadZXing(){if(window.ZXingBrowser)return Promise.resolve(window.ZXingBrowser);if(zxingPromise)return zxingPromise;zxingPromise=new Promise((ok,no)=>{const s=document.createElement('script');s.src='https://unpkg.com/@zxing/browser@0.2.1';s.async=true;s.onload=()=>window.ZXingBrowser?ok(window.ZXingBrowser):no();s.onerror=no;document.head.appendChild(s)});return zxingPromise}

  async function lookup(code){showDetected(code);setStatus('Recherche du produit…');navigator.vibrate?.([70,40,70]);beep();const token=localStorage.getItem('whatzabi_token')||'',r=await fetch(`/pwa/catalog/barcode/${encodeURIComponent(code)}`,{headers:{Authorization:`Bearer ${token}`}});let b=null;try{b=await r.json()}catch{}if(!r.ok)throw new Error(b?.detail||'Produit absent du référentiel.');return b}

  function renderResult(b){const cs=b?.candidates||[],list=$('catalogCandidateList');list.innerHTML='';$('catalogResultCount').textContent=cs.length?`${cs.length} produit détecté`:'Code reconnu';cs.forEach(c=>{const a=document.createElement('article');a.className='catalog-candidate';const h=document.createElement('h3');h.textContent=c.name||'Produit';a.appendChild(h);const m=document.createElement('div');m.className='catalog-meta';[c.brand,c.packaging,c.barcode&&`EAN : ${c.barcode}`].filter(Boolean).forEach(x=>{const s=document.createElement('span');s.className='catalog-chip';s.textContent=x;m.appendChild(s)});a.appendChild(m);list.appendChild(a)});$('barcodeLiveView').hidden=true;$('catalogResults').hidden=false;$('catalogModes').hidden=true;$('catalogCapture').hidden=true}

  async function onDetected(raw,box=null){
    if(!scanning)return;
    const code=normalizeCode(raw);if(!code)return;
    const now=Date.now();if(now-lastDetectionAt<350)return;lastDetectionAt=now;
    lockBox(box);setStatus('Code repéré — verrouillage et capture automatique…');
    await autoCapture(box);
    scanning=false;showDetected(code);stopCameraOnly();
    try{renderResult(await lookup(code))}catch{showDetected(code);setStatus('Produit inconnu de nos référentiels. Le code et sa capture ont été conservés.');$('barcodeUnknownActions').hidden=false}
  }

  async function startNative(){
    if(!('BarcodeDetector'in window))throw new Error();
    const formats=await BarcodeDetector.getSupportedFormats();
    const wanted=['ean_13','ean_8','upc_a','upc_e','code_128'].filter(f=>formats.includes(f));if(!wanted.length)throw new Error();
    const detector=new BarcodeDetector({formats:wanted});
    nativeStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:1920},height:{ideal:1080},advanced:[{focusMode:'continuous'}]},audio:false});
    const video=$('barcodeLiveVideo');video.srcObject=nativeStream;await video.play();setStatus('Scanner prêt — approche le code, Whatzabi capture tout seul.');
    const scan=async()=>{if(!scanning)return;try{const codes=await detector.detect(video);if(codes?.length){const hit=codes[0];const box=hit.boundingBox||null;if(box)lockBox(box);if(hit.rawValue){await onDetected(hit.rawValue,box);return}}else{$('barcodeLockBox').hidden=true}}catch{}nativeTimer=setTimeout(scan,90)};scan();
  }

  async function startZXing(){
    const Z=await loadZXing(),reader=new Z.BrowserMultiFormatReader();
    controls=await reader.decodeFromConstraints({video:{facingMode:{ideal:'environment'},width:{ideal:1920},height:{ideal:1080}}},$('barcodeLiveVideo'),r=>{
      if(!r)return;let box=null;try{const pts=r.getResultPoints?.()||r.resultPoints||[];if(pts.length>=2){const xs=pts.map(p=>p.getX?p.getX():p.x),ys=pts.map(p=>p.getY?p.getY():p.y),minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);box={x:minX,y:Math.max(0,minY-40),width:Math.max(80,maxX-minX),height:Math.max(80,maxY-minY+80)}}}catch{}onDetected(r.getText?r.getText():r.text,box)
    });
    setStatus('Scanner prêt — approche le code, Whatzabi capture tout seul.');
  }

  async function startLiveScanner(){
    ensureUI();detectedBarcode='';lastDetectionAt=0;sessionStorage.removeItem('whatzabi_pending_barcode');sessionStorage.removeItem('whatzabi_pending_barcode_capture');
    $('barcodeDetectedBox').hidden=true;$('barcodeCapturedPreview').hidden=true;$('barcodeUnknownActions').hidden=true;$('barcodeTarget')?.classList.remove('detected');$('barcodeLockBox').hidden=true;
    $('catalogModes').hidden=true;$('catalogCapture').hidden=true;$('catalogResults').hidden=true;$('barcodeLiveView').hidden=false;scanning=true;setStatus('Ouverture de la caméra…');
    try{await startNative()}catch{try{await startZXing()}catch{scanning=false;stopCameraOnly();setStatus('Scanner caméra indisponible. Utilise Photo produit.')}}
  }

  function stopCameraOnly(){if(nativeTimer){clearTimeout(nativeTimer);nativeTimer=null}try{controls?.stop?.()}catch{}controls=null;if(nativeStream){nativeStream.getTracks().forEach(t=>t.stop());nativeStream=null}const v=$('barcodeLiveVideo');if(v?.srcObject){v.srcObject.getTracks().forEach(t=>t.stop());v.srcObject=null}}
  function stopLiveScanner(){scanning=false;stopCameraOnly();if($('barcodeLiveView'))$('barcodeLiveView').hidden=true;$('catalogModes').hidden=false;$('catalogCapture').hidden=true;$('catalogResults').hidden=true}
  function openPhotoFallback(){const c=detectedBarcode;stopCameraOnly();$('barcodeLiveView').hidden=true;$('catalogModes').hidden=false;$('catalogCapture').hidden=true;if(c)sessionStorage.setItem('whatzabi_pending_barcode',c);document.querySelector('[data-catalog-source="product"]')?.click()}
  function saveManualDraft(name,source){const n=String(name||'').trim();if(!n)return;const d={source:'barcode',candidates:[{name:n,barcode:detectedBarcode,confidence:1}],matches:{},requires_confirmation:true,identification_source:source,barcode_capture:sessionStorage.getItem('whatzabi_pending_barcode_capture')||null};sessionStorage.setItem('whatzabi_catalog_draft',JSON.stringify(d));sessionStorage.setItem('whatzabi_pending_barcode',detectedBarcode);$('barcodeLiveView').hidden=true;renderResult(d)}
  function enterName(){const n=window.prompt(`Nom du produit\nEAN / GTIN : ${detectedBarcode}`,'');if(n)saveManualDraft(n,'manual')}
  function dictateName(){const S=window.SpeechRecognition||window.webkitSpeechRecognition;if(!S){setStatus('Dictée indisponible. Utilise “Saisir le nom” ou photographie le produit.');return}const r=new S();r.lang='fr-FR';r.interimResults=false;r.maxAlternatives=1;setStatus('🎙️ Dis le nom du produit…');r.onresult=e=>saveManualDraft(e.results?.[0]?.[0]?.transcript||'','voice');r.onerror=()=>setStatus('Je n’ai pas compris. Réessaie ou saisis le nom.');r.start()}

  document.addEventListener('click',e=>{const b=e.target.closest('[data-catalog-source="barcode"]');if(!b)return;e.preventDefault();e.stopImmediatePropagation();startLiveScanner()},true);
  document.addEventListener('click',e=>{if(e.target.closest('#catalogCloseBtn')||e.target.closest('#catalogRestartBtn')){scanning=false;stopCameraOnly()}},true);
})();