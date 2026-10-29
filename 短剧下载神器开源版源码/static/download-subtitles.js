/* Keep saved videos available while the shared subtitle worker processes its queue. */
let pollingDownloadSubtitles = false;
async function pollDownloadSubtitles() {
  if (pollingDownloadSubtitles) return;
  const pending = tasks.filter(t => t.subtitleJobId && (['queued', 'running'].includes(t.subtitleStatus) || (t.subtitleStatus === 'unavailable' && t.url)));
  if (!pending.length) return;
  pollingDownloadSubtitles = true;
  try {
    const response = await fetch('/api/subtitles/status?ids=' + encodeURIComponent(pending.slice(0, 200).map(t => t.subtitleJobId).join(',')));
    const data = await vipReadJSON(response);
    if (!response.ok) return;
    const missing = pending.slice(0, 200).filter(task => !data.jobs[task.subtitleJobId] && task.url);
    let recovered = {};
    if (missing.length) {
      const response = await fetch('/api/subtitles/reconcile', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({urls: missing.map(task => new URL(task.url, window.location.href).pathname)})});
      if (response.ok) recovered = (await vipReadJSON(response)).jobs || {};
    }
    let changed = false;
    for (const task of pending.slice(0, 200)) {
      const job = data.jobs[task.subtitleJobId] || (task.url && recovered[new URL(task.url, window.location.href).pathname]);
      if (job?.id) task.subtitleJobId = job.id;
      const status = job?.status || 'unavailable';
      const stage = job?.stage || '';
      const progress = Number.isFinite(job?.progress) ? job.progress : null;
      if (task.subtitleStatus === status && task.subtitleStage === stage && task.subtitleProgress === progress) continue;
      task.subtitleStatus = status; task.subtitleStage = stage; task.subtitleProgress = progress; task.subtitleCompleted = job?.completed; task.subtitleTotal = job?.total; changed = true;
      const base = (task.msg || 'Download complete').replace(/ · subtitles queued(?= · |$)/gi, '').replace(/ · Subtitles:.*$/i, '');
      if (status === 'done') {
        task.subtitle = job.subtitle_url;
        task.subtitleQualityState = job.quality_state || 'ready';
        task.msg = base + (task.subtitleQualityState === 'needs_review' ? ' · Subtitles: saved · review needed' : ' · Subtitles: ready');
        task.detail = [task.detail, ...(job.warnings || [])].filter(Boolean).join(' · ');
        window.dispatchEvent(new CustomEvent('vip-subtitles-saved', {detail: {url: new URL(task.url, window.location.href).pathname, subtitle_url: job.subtitle_url}}));
      } else if (status === 'error') {
        task.msg = base + ' · Subtitles: failed — retry in Library';
        task.detail = [task.detail, job.error].filter(Boolean).join(' · ');
      } else if (status === 'unavailable') {
        task.msg = base + ' · Subtitles: checking saved files and recovering processing status';
      } else if (status === 'interrupted') {
        task.msg = base + ' · Subtitles: interrupted before saving — create again from Library';
      } else {
        task.msg = base + ' · Subtitles: ' + (status === 'queued' ? 'waiting for subtitle worker' : (stage || 'processing') + (progress !== null ? ` · ${Math.round(progress)}%` : '') + (job.total ? ` · ${job.completed}/${job.total} images` : ''));
      }
      window.dispatchEvent(new CustomEvent('vip-subtitle-progress', {detail: {url: new URL(task.url, window.location.href).pathname, job}}));
    }
    if (changed) renderTasks();
  } catch (_) { /* A transient connection failure leaves jobs available for the next poll. */ }
  finally { pollingDownloadSubtitles = false; }
}
setInterval(pollDownloadSubtitles, 2000);

window.downloadSubtitleJobForURL = url => {
  const task = tasks.find(task => task.url && task.subtitleJobId && ['queued', 'running'].includes(task.subtitleStatus) && new URL(task.url, window.location.href).pathname === url);
  return task ? {id: task.subtitleJobId, status: task.subtitleStatus, stage: task.subtitleStage, progress: task.subtitleProgress, completed: task.subtitleCompleted, total: task.subtitleTotal} : null;
};

// A replacement Library job reconnects legacy Download rows to its new durable ID.
window.addEventListener('vip-subtitle-progress', event => {
  const {url, job} = event.detail || {};
  if (!url || !job?.id) return;
  let changed = false;
  for (const task of tasks) {
    if (task.url && ['unavailable', 'interrupted'].includes(task.subtitleStatus) && new URL(task.url, window.location.href).pathname === url) {
      task.subtitleJobId = job.id; task.subtitleStatus = 'queued'; changed = true;
    }
  }
  if (changed) pollDownloadSubtitles();
});
