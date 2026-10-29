/* A single view of the shared OCR worker, regardless of where a job started. */
(() => {
  const el = id => document.getElementById(id);
  let jobs = [], loading = false, retrying = false, page = 0, rendered = false;
  const pageSize = 30;
  const expandedErrors = new Set();
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
    rendered = true;
    const latest = new Map();
    jobs.forEach(job => { const key = job.video_url || job.subtitle_url || job.id; if (!latest.has(key)) latest.set(key, job); });
    const failed = Array.from(latest.values()).filter(job => job.status === 'error').length;
    el('retryFailedSubtitles').disabled = retrying || !failed;
    el('retryFailedSubtitles').textContent = retrying ? 'Queuing retries…' : `Retry failed${failed ? ` (${failed})` : ''}`;
    const running = jobs.filter(job => job.status === 'running').length;
    const waiting = jobs.filter(job => job.status === 'queued').length;
    const active = running + waiting;
    const review = job => job.status === 'done' && job.quality_state === 'needs_review';
    el('subtitleBadge').textContent = active || '';
    const filter = el('subtitleJobFilter').value;
    const totals = [
      ['active', 'In progress', active, `${running} processing · ${waiting} waiting`],
      ['review', 'Needs review', jobs.filter(review).length, 'Saved captions to check'],
      ['done', 'Ready', jobs.filter(job => job.status === 'done' && !review(job)).length, 'SRT files available'],
      ['error', 'Failed', jobs.filter(job => job.status === 'error').length, 'Open details to see why']
    ];
    el('subtitleQueueSummary').replaceChildren();
    totals.forEach(([value, label, count, hint]) => {
      const button = node('button', '', 'subtitle-total ' + value);
      button.type = 'button'; button.setAttribute('aria-pressed', String(filter === value));
      button.append(node('span', label), node('strong', String(count)), node('small', hint));
      button.onclick = () => { el('subtitleJobFilter').value = filter === value ? 'all' : value; page = 0; el('subtitleJobList').scrollTop = 0; render(); };
      el('subtitleQueueSummary').append(button);
    });
    const query = el('subtitleJobSearch').value.trim().toLocaleLowerCase();
    const visible = jobs.filter(job => (!query || (job.title || '').toLocaleLowerCase().includes(query)) && (filter === 'all' || (filter === 'active' ? busy(job) : filter === 'review' ? review(job) : filter === 'done' ? job.status === 'done' && !review(job) : job.status === filter)));
    const rank = job => job.status === 'running' ? 0 : job.status === 'queued' ? 1 : 2;
    visible.sort((a, b) => rank(a) - rank(b));
    page = Math.min(page, Math.max(0, Math.ceil(visible.length / pageSize) - 1));
    el('subtitleJobCount').textContent = `${visible.length} of ${jobs.length} jobs`;
    el('subtitlePageInfo').textContent = visible.length ? `${page * pageSize + 1}–${Math.min((page + 1) * pageSize, visible.length)} of ${visible.length}` : '0 jobs';
    el('subtitlePreviousPage').disabled = page === 0;
    el('subtitleNextPage').disabled = (page + 1) * pageSize >= visible.length;
    const list = el('subtitleJobList');
    const scrollTop = list.scrollTop;
    const focused = document.activeElement?.closest('[data-job-id]');
    const focusId = focused?.dataset.jobId, focusAction = document.activeElement?.dataset.action;
    list.replaceChildren();
    if (!visible.length) {
      const empty = node('div', '', 'library-empty');
      empty.append(node('h2', jobs.length ? 'No matching subtitle jobs' : 'Your subtitle queue is clear'), node('p', jobs.length ? 'Try a different title, episode number or status.' : 'Create subtitles from Library or enable them for new downloads.'));
      const button = node('button', jobs.length ? 'Reset filters' : 'Open Library', 'btn3');
      button.onclick = () => { if (jobs.length) { el('subtitleJobFilter').value = 'all'; el('subtitleJobSearch').value = ''; page = 0; el('subtitleJobList').scrollTop = 0; render(); } else setTab('library'); };
      empty.append(button); list.append(empty);
    }
    let section = '';
    const methods = vipSubtitleOptions.labels;
    visible.slice(page * pageSize, (page + 1) * pageSize).forEach(job => {
      const group = job.status === 'running' ? 'Processing now' : job.status === 'queued' ? 'Waiting in queue' : 'Completed & failed';
      if (section !== group) { section = group; list.append(node('h3', group, 'subtitle-list-heading')); }
      const state = review(job) ? 'review' : job.status;
      const card = node('article', '', 'subtitle-job subtitle-job-row ' + state); card.dataset.jobId = job.id;
      const identity = node('div', '', 'subtitle-job-identity');
      const episode = (job.title || '').match(/Episode\s*(\d+)/i)?.[1];
      const title = episode ? (job.title || '').replace(/\s*[-–·]?\s*Episode\s*\d+\s*$/i, '') : job.title;
      const marker = node('span', episode ? 'EP ' + episode : 'SRT', 'subtitle-episode-marker');
      const copy = node('div'); copy.append(node('h3', title || 'Saved episode'), node('small', job.fallback_from === 'paraformer' && job.speech_engine === 'whisper' ? 'Whisper audio · recovered from Paraformer timing failure' : methods[job.mode] || 'Subtitle processing'));
      identity.append(marker, copy); card.append(identity);
      const detail = node('div', '', 'subtitle-job-detail');
      const label = ({queued:job.stage === 'Waiting for download folder' ? 'Drive unavailable' : 'Waiting',running:'Processing',done:'Ready',review:'Needs review',error:'Failed'})[state] || state;
      detail.append(node('span', label, 'pill ' + state));
      const percent = Number.isFinite(job.progress) ? Math.max(0, Math.min(100, Math.round(job.progress))) : null;
      if (job.status === 'running') {
        detail.append(node('p', (job.stage || 'Processing subtitles') + (percent !== null ? ` · ${percent}%` : ''), 'subtitle-row-status'));
        const progress = node('progress'); progress.max = 100;
        if (percent !== null) progress.value = percent;
        progress.setAttribute('aria-label', `Subtitle progress: ${job.title || 'Episode'}`); detail.append(progress);
      } else if (state === 'review') {
        const differences = job.review_count || 0, checks = job.quality_issue_count || 0;
        detail.append(node('p', `${differences} speech difference${differences === 1 ? '' : 's'} · ${checks} caption check${checks === 1 ? '' : 's'}`, 'subtitle-row-status'));
      } else {
        detail.append(node('p', state === 'done' ? 'SRT saved' : state === 'error' ? 'Subtitle generation failed' : job.stage === 'Waiting for download folder' ? 'Reconnect your download drive' : 'Starts when the worker is free', 'subtitle-row-status'));
      }
      card.append(detail);
      const actions = node('div', '', 'subtitle-row-actions');
      if (job.status === 'done' && typeof job.subtitle_url === 'string' && job.subtitle_url.startsWith('/') && !job.subtitle_url.startsWith('//')) {
        const link = node('a', 'Save SRT ↗', 'detail-link'); link.href = job.subtitle_url; link.download = ''; link.dataset.action = 'save'; actions.append(link);
      }
      if (state === 'review') {
        const button = node('button', 'Review captions', 'btn2 sm'); button.dataset.action = 'review';
        button.onclick = () => window.openSubtitleReview(job.video_url || job.subtitle_url?.replace(/\.srt$/, '.mp4'), job.title || 'Episode'); actions.append(button);
      }
      if (job.status === 'error') {
        const details = node('details', '', 'subtitle-error-details'); const summary = node('summary', 'Error details'); summary.dataset.action = 'error';
        details.open = expandedErrors.has(job.id);
        details.ontoggle = () => { if (details.isConnected) { if (details.open) expandedErrors.add(job.id); else expandedErrors.delete(job.id); } };
        details.append(summary, node('p', job.error || 'Retry from Library.')); actions.append(details);
      }
      card.append(actions); list.append(card);
    });
    list.scrollTop = scrollTop;
    if (focusId && focusAction) {
      Array.from(list.querySelectorAll('[data-job-id]')).find(row => row.dataset.jobId === focusId)?.querySelector(`[data-action="${focusAction}"]`)?.focus({preventScroll:true});
    }
  }
  window.loadSubtitleJobs = async () => {
    if (loading) return;
    loading = true; el('refreshSubtitleJobs').disabled = true;
    try {
      const response = await fetch('/api/subtitles/jobs');
      const data = await vipReadJSON(response);
      if (!response.ok || !Array.isArray(data.jobs)) throw new Error(data.error || 'Could not load subtitle activity. Update and restart the app, then try again.');
      const changed = !rendered || JSON.stringify(jobs) !== JSON.stringify(data.jobs);
      const previous = new Map(jobs.map(job => [job.id, job]));
      jobs = data.jobs;
      if (changed) {
        render();
        // Notify other views only about jobs that actually changed.
        jobs.filter(job => JSON.stringify(previous.get(job.id)) !== JSON.stringify(job)).forEach(job => {
          const url = job.video_url || job.subtitle_url?.replace(/\.srt$/, '.mp4');
          window.dispatchEvent(new CustomEvent('vip-subtitle-progress', {detail: {job, url}}));
        });
      }
      el('subtitleJobsStatus').textContent = '';
    } catch (error) { el('subtitleJobsStatus').textContent = error.message; }
    finally { loading = false; el('refreshSubtitleJobs').disabled = false; }
  };
  document.querySelectorAll('[data-subtitle-view]').forEach(button => button.onclick = () => setView(button.dataset.subtitleView));
  el('subtitleOpenLibrary').onclick = () => setTab('library');
  el('refreshSubtitleJobs').onclick = window.loadSubtitleJobs;
  el('retryFailedSubtitles').onclick = async () => {
    if (retrying) return;
    retrying = true; render();
    try {
      const response = await fetch('/api/subtitles/retry-failed', {method: 'POST'});
      const data = await vipReadJSON(response);
      if (!response.ok) throw new Error(data.error || 'Could not retry subtitles.');
      const message = `${data.queued} episode${data.queued === 1 ? '' : 's'} queued for subtitle regeneration.` + (data.failed ? ` ${data.failed} could not be queued. ${data.errors?.[0]?.error || ''}` : '');
      toast(message, data.failed ? 'error' : 'success');
      await window.loadSubtitleJobs();
      el('subtitleJobsStatus').textContent = message;
    } catch (error) { el('subtitleJobsStatus').textContent = error.message; toast(error.message, 'error'); }
    finally { retrying = false; render(); }
  };
  el('subtitleJobFilter').onchange = () => { page = 0; el('subtitleJobList').scrollTop = 0; render(); };
  el('subtitleJobSearch').oninput = () => { page = 0; el('subtitleJobList').scrollTop = 0; render(); };
  el('subtitlePreviousPage').onclick = () => { page = Math.max(0, page - 1); el('subtitleJobList').scrollTop = 0; render(); };
  el('subtitleNextPage').onclick = () => { page++; el('subtitleJobList').scrollTop = 0; render(); };
  try { const saved = sessionStorage.getItem('vip_subtitle_view'); if (['jobs','preferences','files'].includes(saved)) setView(saved); } catch (_) {}
  window.addEventListener('vip-subtitle-progress', event => {
    const job = event.detail?.job;
    if (job?.id && (!jobs.some(saved => saved.id === job.id && saved.status === job.status))) window.loadSubtitleJobs();
  });
  window.loadSubtitleJobs();
  setInterval(() => { if (el('subtitles').classList.contains('active') || jobs.some(busy)) window.loadSubtitleJobs(); }, 2000);
})();
