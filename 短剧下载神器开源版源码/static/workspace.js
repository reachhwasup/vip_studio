/* Activity stays visible without interrupting downloads, playback or editing. */
(() => {
  const el = id => document.getElementById(id);
  const jobs = new Map();
  const active = job => job && ['queued', 'running', 'starting'].includes(job.status);
  function summary(queue, extraJobs, isRunning) {
    const counts = {running: 0, pending: 0, done: 0, error: 0};
    const subtitles = new Map(extraJobs);
    for (const task of queue) {
      if (task.status in counts) counts[task.status]++;
      if (task.subtitleJobId) subtitles.set(task.subtitleJobId, {status: task.subtitleStatus, stage: task.subtitleStage, progress: task.subtitleProgress});
    }
    const processing = [...subtitles.values()].filter(active);
    const reading = processing.find(job => job.status === 'running');
    const waiting = processing.filter(job => job.status !== 'running').length;
    const percent = Number.isFinite(reading?.progress) ? Math.round(reading.progress) : null;
    return {
      videos: counts.running ? `${counts.running} downloading` : counts.pending ? (isRunning ? 'Starting downloads' : 'Queue paused') : counts.done ? `${counts.done} saved` : 'Ready',
      videoDetail: counts.pending || counts.error ? `${counts.pending} waiting · ${counts.error} failed${counts.done ? ` · ${counts.done} saved` : ''}` : counts.done ? 'Your videos are available in Library' : 'Add episodes to start your collection',
      subtitles: reading ? `Processing${percent !== null ? ` · ${percent}%` : ''}` : waiting ? `${waiting} waiting` : 'No active jobs',
      subtitleDetail: reading ? `${reading.stage || 'Preparing subtitles'}${waiting ? ` · ${waiting} waiting` : ''}` : waiting ? 'Subtitles run one episode at a time in the background' : 'Saved videos are ready to watch while subtitles process',
      queueText: counts.running ? `${counts.running} downloading` : processing.length ? (reading ? 'Subtitles processing' : 'Subtitles queued') : counts.pending ? `${counts.pending} in queue` : 'Queue ready',
      busy: counts.running > 0 || processing.length > 0
    };
  }
  window.vipWorkspaceSummary = summary;
  function refresh() {
    const state = summary(typeof tasks === 'undefined' ? [] : tasks, jobs, typeof running !== 'undefined' && running);
    el('workspaceQueueText').textContent = state.queueText;
    el('workspaceQueue').classList.toggle('is-running', state.busy);
  }
  el('updateViewActivity').onclick = () => { setTab('downloads'); setDownloadView('queue'); };
  window.addEventListener('vip-subtitle-progress', event => {
    const job = event.detail?.job;
    if (job?.id) { if (active(job)) jobs.set(job.id, job); else jobs.delete(job.id); }
    refresh();
  });
  window.addEventListener('vip-native-update', event => {
    if (!event.detail?.postponed) return;
    el('updateNotice').hidden = false;
    el('updateNoticeMessage').textContent = event.detail.message;
  });
  const observer = new MutationObserver(refresh);
  observer.observe(el('taskList'), {childList: true, subtree: true});
  document.addEventListener('click', event => {
    const more = document.querySelector('.queue-more');
    if (more && (!more.contains(event.target) || event.target.closest('button'))) more.open = false;
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      const more = document.querySelector('.queue-more[open]');
      if (more) { more.open = false; more.querySelector('summary').focus(); }
    }
  });
  refresh();
})();
