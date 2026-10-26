(() => {
  const $ = id => document.getElementById(id);
  const form = $('send-form'), button = $('send-now'), feedback = $('send-feedback');
  const labels = {DRAFT:'Preparado',QUEUED:'En cola',CLAIMED:'Reservado',STARTED:'Enviando',SENT:'Enviado',
    DELIVERED:'Entregado',FAILED:'Fallido',UNKNOWN:'Desconocido',CANCELLED:'Cancelado',STOPPED:'Detenido',COMPLETE:'Finalizado',EXPIRED:'Vencido'};
  let preview = null, connected = false, quoting = false, quoteNumber = 0, timer, pending = null, sending = false;
  try { pending = JSON.parse(sessionStorage.getItem('gateway-pending') || 'null'); } catch (_) {}
  const values = () => Object.fromEntries(new FormData(form));
  const csrf = () => form.elements.csrf_token.value;
  function controls(locked) {
    for (const input of form.querySelectorAll('select,input:not([type=hidden]),textarea')) input.disabled = locked;
  }
  function updateButton() {
    button.disabled = sending || (!pending && (quoting || !connected || !preview || !preview.count));
    button.textContent = pending ? 'Reintentar la misma solicitud' : preview && preview.count ? `Enviar ahora a ${preview.count} personas` : 'Enviar ahora';
  }
  function clearPending() { pending = null; sessionStorage.removeItem('gateway-pending'); controls(false); }
  function completed(id) { clearPending(); window.location.assign(`/gateway?sent=${encodeURIComponent(id)}#batches`); }
  async function quote() {
    if (pending || sending) return;
    const number = ++quoteNumber;
    quoting = true; updateButton();
    $('gateway-cause').hidden = form.elements.alert_type.value !== 'technical';
    const controlled = form.elements.alert_type.value === 'controlled';
    const reasonField = $('controlled-reason');
    $('controlled-fields').hidden = !controlled;
    reasonField.required = controlled;
    try {
      if (controlled) {
        const limitResponse = await fetch(
          `/gateway/reason-limit?building_id=${encodeURIComponent(form.elements.building_id.value)}`,
          {cache:'no-store'}
        );
        const limitData = await limitResponse.json();
        if (!limitResponse.ok) throw new Error(limitData.detail || 'No se pudo calcular el límite del motivo');
        reasonField.maxLength = limitData.max_chars;
        if (reasonField.value.length > limitData.max_chars) {
          reasonField.value = reasonField.value.slice(0, limitData.max_chars);
        }
        $('controlled-reason-counter').textContent =
          `${reasonField.value.length}/${limitData.max_chars}`;
      }
      const query = new URLSearchParams(values()); query.delete('csrf_token');
      const response = await fetch(`/gateway/quote?${query}`, {cache:'no-store'});
      const data = await response.json();
      if (number !== quoteNumber) return;
      if (!response.ok) throw new Error(data.detail || 'No se pudo actualizar la selección');
      preview = data;
      const chosen = $('office').value;
      const offices = [...new Set([...data.offices,...(chosen ? [chosen] : [])])];
      $('office').replaceChildren(new Option('Todas las oficinas',''),...offices.map(o=>new Option(o,o)));
      $('office').value = chosen;
      $('message-preview').textContent = data.message;
      $('segments').textContent = `${data.message.length}/160 caracteres · 1 segmento por persona`;
      $('recipient-count').textContent = data.count ? `${data.count} destinatarios habilitados` : 'No hay destinatarios con SMS habilitado';
      $('recipient-list').replaceChildren(...data.recipients.map(r=>{
        const li=document.createElement('li'); li.textContent=`${r.name} · ${r.phone} · ${r.office || 'Sin oficina'}`;return li;
      }));
    } catch (error) {
      if (number !== quoteNumber) return;
      preview = null; $('recipient-count').textContent = error.message;
    } finally { if (number === quoteNumber) { quoting = false; updateButton(); } }
  }
  form.addEventListener('input', event => {
    if (event.target.name === 'building_id') $('office').value='';
    preview=null; quoting=true; ++quoteNumber; updateButton(); clearTimeout(timer); timer=setTimeout(quote,180);
  });
  $('controlled-reason').addEventListener('input', event => {
    $('controlled-reason-counter').textContent =
      `${event.target.value.length}/${event.target.maxLength}`;
  });
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (sending || button.disabled) return;
    if (!pending) {
      pending={...values(),request_id:crypto.randomUUID(),snapshot:preview.snapshot,message:preview.message,count:preview.count};
      sessionStorage.setItem('gateway-pending',JSON.stringify(pending));
    }
    controls(true); sending=true; feedback.textContent='Poniendo el aviso en cola…'; updateButton();
    try {
      const response = await fetch('/gateway/send',{method:'POST',body:new URLSearchParams({...pending,csrf_token:csrf()})});
      const data = await response.json();
      if (response.ok) { completed(data.batch_id); return; }
      if (response.status < 500) clearPending();
      feedback.textContent=data.detail || 'No se pudo confirmar la recepción de la solicitud';
    } catch (_) {
      feedback.textContent='No llegó la respuesta. Podés reintentar esta misma solicitud sin duplicar el aviso.';
    } finally { sending=false; updateButton(); if (!pending) await quote(); }
  });
  if (pending) {
    for (const name of ['building_id','alert_type','technical_cause','other_description','controlled_reason']) form.elements[name].value=pending[name] || '';
    $('controlled-fields').hidden = pending.alert_type !== 'controlled';
    $('controlled-reason').required = pending.alert_type === 'controlled';
    if (pending.office) $('office').add(new Option(pending.office,pending.office));
    $('office').value=pending.office || ''; controls(true);
    $('message-preview').textContent=pending.message; $('recipient-count').textContent=`Solicitud pendiente: ${pending.count} destinatarios`;
    feedback.textContent='Recuperamos la solicitud anterior. Reintentá para consultar o completar esa misma orden.';
  }
  $('pair-button').addEventListener('click', async () => {
    $('pair-button').disabled=true; $('pair-panel').hidden=false; $('pair-detail').textContent='Generando QR…'; $('pair-image').hidden=true;
    try {
      const response=await fetch('/gateway/pairing',{method:'POST',body:new URLSearchParams({csrf_token:csrf()})});
      const data=await response.json(); if (!response.ok) throw new Error(data.detail || 'No se pudo generar el QR');
      $('pair-image').src=data.qr_png; $('pair-image').hidden=false;
      $('pair-detail').textContent=`PC: ${data.url} · válido hasta ${new Date(data.expires_at*1000).toLocaleTimeString()}`;
    } catch(error) { $('pair-detail').textContent=error.message; }
    finally { $('pair-button').disabled=false; }
  });
  async function refresh() {
    try {
      const response=await fetch('/gateway/status',{cache:'no-store'}); if(!response.ok) throw new Error();
      const data=await response.json(); connected=data.control.connected;
      $('phone-state').textContent=connected?'Celular listo para recibir avisos':'Esperando al celular: abrí la app y activá el gateway';
      $('sim-state').textContent=data.control.sim_label || 'SIM sin informar';
      $('queue-state').textContent=data.control.enabled?'Cola habilitada':'Sin envío activo o pendientes pausados';
      const sync=data.last_sync;
      $('sync-state').textContent=sync ? `Última sincronización: ${new Date(sync.completed_at).toLocaleString()} · ${sync.accepted} registros válidos`+
        (sync.status==='failed'?' · No se pudo actualizar: revisá Destinatarios.':sync.rejected?` · ${sync.rejected} filas inválidas excluidas`:'') : 'La sincronización inicial está pendiente';
      if (pending && data.batches.some(b=>b.id===pending.request_id)) { completed(pending.request_id); return; }
      for(const batch of data.batches) {
        const counts=document.querySelector(`[data-counts="${batch.id}"]`);
        if(counts) counts.textContent=Object.entries(batch.counts).filter(([,n])=>n>0).map(([s,n])=>`${labels[s]||s}: ${n}`).join(' · ');
        const state=document.querySelector(`[data-batch-state="${batch.id}"]`);if(state)state.textContent=labels[batch.status]||batch.status;
        for(const job of batch.jobs) {
          const row=document.querySelector(`[data-job="${job.id}"]`);if(!row)continue;
          row.querySelector('.job-state').textContent=labels[job.status]||job.status;row.querySelector('.job-detail').textContent=job.detail;
        }
      }
      if(!quoting) await quote();
    } catch(_) { connected=false;$('phone-state').textContent='Sin conexión con el programa de la PC'; }
    finally {updateButton();setTimeout(refresh,3000);}
  }
  refresh();
})();
