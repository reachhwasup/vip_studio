/* Keep saved videos available while the shared subtitle worker processes its queue. */
let pollingDownloadSubtitles = false;
async function pollDownloadSubtitles() {
  if (pollingDownloadSubtitles) return;
  const pending = tasks.filter(t => t.subtitleJobId && ['queued', 'running'].includes(t.subtitleStatus));
  if (!pending.length) return;
  pollingDownloadSubtitles = true;
  try {
    const response = await fetch('/api/subtitles/status?ids=' + encodeURIComponent(pending.slice(0, 200).map(t => t.subtitleJobId).join(',')));
    const data = await vipReadJSON(response);
    if (!response.ok) return;
    let changed = false;
    for (const task of pending.slice(0, 200)) {
      const job = data.jobs[task.subtitleJobId];
      const status = job?.status || 'unavailable';
      const stage = job?.stage || '';
      if (task.subtitleStatus === status && task.subtitleStage === stage) continue;
      task.subtitleStatus = status; task.subtitleStage = stage; changed = true;
      const base = (task.msg || 'Download complete').replace(/ · subtitles queued(?= · |$)/gi, '').replace(/ · Subtitles:.*$/i, '');
      if (status === 'done') {
        task.subtitle = job.subtitle_url;
        task.msg = base + ' · Subtitles: ready';
        task.detail = [task.detail, ...(job.warnings || [])].filter(Boolean).join(' · ');
        window.dispatchEvent(new CustomEvent('vip-subtitles-saved', {detail: {url: new URL(task.url, window.location.href).pathname, subtitle_url: job.subtitle_url}}));
      } else if (status === 'error') {
        task.msg = base + ' · Subtitles: failed — retry in Library';
        task.detail = [task.detail, job.error].filter(Boolean).join(' · ');
      } else if (status === 'unavailable') {
        task.msg = base + ' · Subtitles: check Library; processing status was lost after restart';
      } else {
        task.msg = base + ' · Subtitles: ' + (status === 'queued' ? 'queued' : stage || 'processing');
      }
    }
    if (changed) renderTasks();
  } catch (_) { /* A transient connection failure leaves jobs available for the next poll. */ }
  finally { pollingDownloadSubtitles = false; }
}
setInterval(pollDownloadSubtitles, 2000);
