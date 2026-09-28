(() => {
  const labels = {DRAFT: 'Vista previa', QUEUED: 'En cola', CLAIMED: 'Reservado', STARTED: 'Enviando',
    SENT: 'Enviado', DELIVERED: 'Entregado', FAILED: 'Fallido', UNKNOWN: 'Desconocido',
    CANCELLED: 'Cancelado', STOPPED: 'Detenida', COMPLETE: 'Finalizada', EXPIRED: 'Vencida'};
  const type = document.getElementById('gateway-alert-type');
  const cause = document.getElementById('gateway-cause');
  const toggle = () => { cause.hidden = type.value !== 'technical'; };
  type.addEventListener('change', toggle); toggle();
  async function refresh() {
    try {
      const response = await fetch('/gateway/status', {cache: 'no-store'});
      if (!response.ok) throw new Error('Panel sin conexión');
      const data = await response.json();
      document.getElementById('phone-state').textContent = data.control.connected ? 'Teléfono activo' : 'Esperando al teléfono';
      document.getElementById('queue-state').textContent = data.control.enabled ? 'Envíos habilitados' : 'Gateway pausado';
      document.getElementById('sim-state').textContent = data.control.sim_label || 'SIM sin informar';
      for (const batch of data.batches) {
        const count = document.querySelector(`[data-counts="${batch.id}"]`);
        if (count) count.textContent = Object.entries(batch.counts).filter(([, n]) => n > 0)
          .map(([s, n]) => `${labels[s] || s}: ${n}`).join(' · ');
        const state = document.querySelector(`[data-batch-state="${batch.id}"]`);
        if (state) state.textContent = labels[batch.status] || batch.status;
        for (const job of batch.jobs) {
          const row = document.querySelector(`[data-job="${job.id}"]`);
          if (!row) continue;
          row.querySelector('.job-state').textContent = labels[job.status] || job.status;
          row.querySelector('.job-detail').textContent = job.detail;
        }
      }
    } catch (_) { document.getElementById('phone-state').textContent = 'Sin conexión con el servidor de la PC'; }
    finally { setTimeout(refresh, 4000); }
  }
  refresh();
})();
