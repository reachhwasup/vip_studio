/* A single view of the shared OCR worker, regardless of where a job started. */
(() => {
  const el = id => document.getElementById(id);
  let jobs = [], loading = false;
  const busy = job => ['queued', 'running'].includes(job.status);
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function setView(view) {
    const names = {jobs: 'subtitleJobsView', preferences: 'subtitlePreferencesView', files: 'subtitleFilesView'};
    for (const [name, id] of Object.entries(names)) el(id).hidden = name !== view;
    document.querySelectorAll('[data-subtitle-view]').forEach(button => {
      const selected = button.dataset.subtitleView === view;
      button.classList.toggle('active', selected); button.setAttribute('aria-pressed', String(selected));
    });
    try { sessionStorage.setItem('vip_subtitle_view', view); } catch (_) {}
  }
  function render() {
    const active = jobs.filter(busy).length;
    el('subtitleBadge').textContent = active || '';
    el('subtitleJobCount').textContent = `${active} active · ${jobs.filter(job => job.status === 'done').length} ready · ${jobs.filter(job => job.status === 'error').length} failed`;
    const filter = el('subtitleJobFilter').value;
    const visible = jobs.filter(job => filter === 'all' || (filter === 'active' ? busy(job) : job.status === filter));
    const list = el('subtitleJobList'); list.replaceChildren();
    if (!visible.length) {
      const empty = node('div', '', 'library-empty');
      empty.append(node('h2', jobs.length ? 'No jobs match this filter' : 'Your subtitle queue is clear'), node('p', jobs.length ? 'Choose another filter to see other jobs.' : 'Create subtitles for a saved video in Library, or enable automatic subtitles in Preferences.'));
      const button = node('button', jobs.length ? 'Show all jobs' : 'Choose a video in Library', 'btn3');
      button.onclick = () => { if (jobs.length) { el('subtitleJobFilter').value = 'all'; render(); } else setTab('library'); };
      empty.append(button); list.append(empty);
    }
    // Active jobs first; stable order preserves the backend's newest-first history.
    visible.sort((a, b) => Number(busy(b)) - Number(busy(a))).forEach(job => {
      const card = node('article', '', 'subtitle-job');
      const heading = node('div', '', 'subtitle-job-heading');
      const title = node('h3', job.title || 'Saved episode');
      heading.append(title, node('span', ({queued:'Waiting',running:'Processing',done:'Ready',error:'Failed'})[job.status] || job.status, 'pill ' + job.status));
      card.append(heading);
      const percent = Number.isFinite(job.progress) ? Math.max(0, Math.min(100, Math.round(job.progress))) : null;
      const status = job.status === 'error' ? (job.error || 'Subtitle processing failed. Try again from Library.') : job.status === 'queued' ? 'Waiting for the subtitle worker' : (job.stage || 'Processing subtitles') + (percent !== null ? ` · ${percent}%` : '') + (job.total ? ` · ${job.completed ?? 0}/${job.total} images` : '');
      card.append(node('p', status, 'subtitle-job-status'));
      if (busy(job)) {
        const progress = node('progress'); progress.max = 100;
        progress.setAttribute('aria-label', `Subtitle progress: ${job.title || 'Saved episode'}`);
        if (job.status === 'queued') progress.value = 0;
        else if (percent !== null) progress.value = percent;
        card.append(progress);
      }
      const methods = {auto:'Automatic · captions + speech',picture:'Picture only · on-screen captions',audio:'Audio only · speech recognition'};
      card.append(node('small', methods[job.mode] || 'Subtitle processing'));
      if (job.status === 'done' && typeof job.subtitle_url === 'string' && job.subtitle_url.startsWith('/') && !job.subtitle_url.startsWith('//')) {
        const link = node('a', 'Download SRT', 'detail-link'); link.href = job.subtitle_url; link.download = ''; card.append(link);
      }
      list.append(card);
    });
  }
  window.loadSubtitleJobs = async () => {
    if (loading) return;
    loading = true; el('refreshSubtitleJobs').disabled = true;
    try {
      const response = await fetch('/api/subtitles/jobs');
      const data = await vipReadJSON(response);
      if (!response.ok || !Array.isArray(data.jobs)) throw new Error(data.error || 'Could not load subtitle activity. Update and restart the app, then try again.');
      jobs = data.jobs;
      render(); el('subtitleJobsStatus').textContent = '';
      // Keep the workspace header and Library in sync with jobs from any entry point.
      jobs.forEach(job => window.dispatchEvent(new CustomEvent('vip-subtitle-progress', {detail: {job, url: job.subtitle_url?.replace(/\.srt$/, '.mp4')}})));
    } catch (error) { el('subtitleJobsStatus').textContent = error.message; }
    finally { loading = false; el('refreshSubtitleJobs').disabled = false; }
  };
  document.querySelectorAll('[data-subtitle-view]').forEach(button => button.onclick = () => setView(button.dataset.subtitleView));
  el('subtitleOpenLibrary').onclick = () => setTab('library');
  el('activitySubtitlesLink').onclick = () => { setTab('subtitles'); setView('jobs'); };
  el('refreshSubtitleJobs').onclick = window.loadSubtitleJobs;
  el('subtitleJobFilter').onchange = render;
  try { const saved = sessionStorage.getItem('vip_subtitle_view'); if (['jobs','preferences','files'].includes(saved)) setView(saved); } catch (_) {}
  window.addEventListener('vip-subtitle-progress', event => {
    const job = event.detail?.job;
    if (job?.id && (!jobs.some(saved => saved.id === job.id && saved.status === job.status))) window.loadSubtitleJobs();
  });
  window.loadSubtitleJobs();
  setInterval(() => { if (el('subtitles').classList.contains('active') || jobs.some(busy)) window.loadSubtitleJobs(); }, 2000);
})();
