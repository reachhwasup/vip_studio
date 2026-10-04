(() => {
  const el = id => document.getElementById(id);
  let items = [], selected = null, requestId = 0;
  const video = el('libraryVideo');
  let selectedEpisode = null;
  const subtitleJobs = new Map();
  function renderSubtitleStatus() {
    const episode = selectedEpisode, job = episode && subtitleJobs.get(episode.url);
    const button = el('regenerateLibrarySubtitles'), link = el('librarySubtitleLink');
    const busy = job && ['queued', 'running', 'starting'].includes(job.status);
    button.disabled = !episode || !!busy;
    el('reviewLibrarySubtitles').disabled = !episode?.subtitle_url || !!busy;
    button.textContent = busy ? (job.status === 'running' ? 'Reading subtitles…' : 'Queued…') : episode && episode.subtitle_url ? 'Regenerate subtitles' : 'Create subtitles';
    const status = !episode ? 'Choose an episode.' : job?.status === 'error' ? job.error : job?.status === 'done' ? `${job.captions} captions saved · ${job.method === 'picture' ? 'Read from video' : 'From speech recognition'}` : busy ? 'Processing locally. You can keep browsing while this finishes.' : episode.subtitle_url ? 'SRT available for this episode.' : 'No subtitle file saved yet.';
    el('librarySubtitleStatus').textContent = status;
    link.hidden = !episode?.subtitle_url;
    if (episode?.subtitle_url) link.href = episode.subtitle_url + (episode.subtitle_url.includes('?') ? '&' : '?') + 'v=' + (job?.updated_at || Date.now());
  }
  function rememberSubtitleJobs() {
    try { localStorage.setItem('vip_subtitle_jobs', JSON.stringify(Array.from(subtitleJobs).filter(([, job]) => ['queued', 'running'].includes(job.status)))); } catch (_) {}
  }
  async function watchSubtitleJob(url, job) {
    try {
      const response = await fetch('/api/subtitles/regenerate?id=' + encodeURIComponent(job.id));
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not check subtitle status.');
      subtitleJobs.set(url, data); rememberSubtitleJobs();
      if (data.status === 'done') {
        items.forEach(drama => drama.episodes.forEach(episode => { if (episode.url === url) episode.subtitle_url = data.subtitle_url; }));
        if (selectedEpisode?.url === url) selectedEpisode.subtitle_url = data.subtitle_url;
        toast(`Subtitles ready: ${data.title} · ${data.captions} captions`, 'success');
        notifyDone('Subtitles ready', `${data.title} · ${data.captions} captions`);
      } else if (data.status === 'error') toast('Subtitle regeneration failed: ' + data.error, 'error');
      else setTimeout(() => watchSubtitleJob(url, data), 1500);
      renderSubtitleStatus();
    } catch (error) {
      subtitleJobs.set(url, {...job, status: 'error', error: error.message + ' Reopen regeneration to check or retry.'});
      rememberSubtitleJobs(); renderSubtitleStatus();
    }
  }
  el('reviewLibrarySubtitles').onclick = () => { if (selectedEpisode?.subtitle_url) { video.pause(); window.openSubtitleReview(selectedEpisode.url, selectedEpisode.title); } };
  el('regenerateLibrarySubtitles').onclick = async () => {
    const episode = selectedEpisode;
    if (!episode) return;
    askNotifyPermission();
    subtitleJobs.set(episode.url, {status: 'starting'}); renderSubtitleStatus();
    try {
      const response = await fetch('/api/subtitles/regenerate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url: episode.url})});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not start subtitle regeneration.');
      subtitleJobs.set(episode.url, data); rememberSubtitleJobs(); renderSubtitleStatus();
      toast('Subtitle regeneration queued: ' + episode.title);
      watchSubtitleJob(episode.url, data);
    } catch (error) {
      subtitleJobs.set(episode.url, {status: 'error', error: error.message}); renderSubtitleStatus();
      toast(error.message, 'error');
    }
  };
  try {
    const saved = JSON.parse(localStorage.getItem('vip_subtitle_jobs') || '[]');
    if (Array.isArray(saved)) saved.forEach(entry => {
      if (!Array.isArray(entry) || typeof entry[0] !== 'string' || !entry[1] || typeof entry[1].id !== 'string') return;
      subtitleJobs.set(entry[0], entry[1]); watchSubtitleJob(entry[0], entry[1]);
    });
  } catch (_) {}

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function play(episode, button) {
    selectedEpisode = episode; renderSubtitleStatus();
    video.pause();
    video.src = episode.url;
    el('libraryEpisodeTitle').textContent = episode.title;
    el('libraryPlaybackStatus').textContent = '';
    el('libraryEpisodes').querySelectorAll('button').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    video.play().catch(() => { el('libraryPlaybackStatus').textContent = 'Press Play to start. If this video cannot play in your browser, open its folder to use your video player.'; });
  }
  function openDrama(drama) {
    selected = drama;
    el('libraryTitle').textContent = drama.title;
    video.poster = drama.poster;
    el('libraryEpisodes').replaceChildren();
    drama.episodes.forEach(episode => {
      const button = node('button', episode.title, 'btn2');
      button.onclick = () => play(episode, button);
      el('libraryEpisodes').append(button);
    });
    el('libraryDialog').showModal();
    play(drama.episodes[0], el('libraryEpisodes').firstElementChild);
  }
  function render() {
    const query = el('librarySearch').value.trim().toLocaleLowerCase();
    const visible = items.filter(drama => drama.title.toLocaleLowerCase().includes(query) || drama.episodes.some(ep => ep.title.toLocaleLowerCase().includes(query)));
    el('libraryGrid').replaceChildren();
    el('libraryStatus').textContent = items.length ? `${items.length} dramas · ${items.reduce((count, drama) => count + drama.episodes.length, 0)} saved episodes${query ? ` · ${visible.length} matching dramas` : ''}` : 'No saved episodes yet. Download a drama, then refresh your library.';
    visible.forEach(drama => {
      const card = node('article', '', 'library-card');
      const poster = node('button', '', 'library-poster');
      poster.setAttribute('aria-label', `Watch ${drama.title}`);
      poster.append(node('span', '▶'));
      if (drama.poster) {
        const image = node('img'); image.src = drama.poster; image.alt = ''; image.loading = 'lazy'; image.onerror = () => image.remove(); poster.append(image);
      }
      poster.onclick = () => openDrama(drama);
      card.append(poster, node('h2', drama.title), node('p', `${drama.episodes.length} episodes · ${(drama.episodes.reduce((sum, ep) => sum + ep.size, 0) / 1024 ** 3).toFixed(2)} GB`));
      const watch = node('button', 'View episodes', 'btn3'); watch.onclick = () => openDrama(drama); card.append(watch);
      el('libraryGrid').append(card);
    });
  }
  window.loadLibrary = async () => {
    const id = ++requestId;
    el('libraryStatus').textContent = 'Looking for saved episodes…';
    el('refreshLibrary').disabled = true;
    try {
      const response = await fetch('/api/library');
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not load library.');
      if (id !== requestId) return;
      items = data.items; render();
    } catch (error) { if (id === requestId) el('libraryStatus').textContent = error.message; }
    finally { if (id === requestId) el('refreshLibrary').disabled = false; }
  };
  el('refreshLibrary').onclick = window.loadLibrary;
  el('librarySearch').oninput = render;
  el('closeLibraryPlayer').onclick = () => el('libraryDialog').close();
  el('libraryDialog').addEventListener('close', () => { video.pause(); video.removeAttribute('src'); video.load(); });
  video.addEventListener('error', () => { el('libraryPlaybackStatus').textContent = 'This video could not play. Open its folder to watch it with your video player.'; });
  el('openLibraryFolder').onclick = async () => {
    if (!selected) return;
    try {
      const response = await fetch('/api/library/open-folder', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({root: selected.root, folder: selected.folder})});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not open folder.');
      toast('Download folder opened', 'success');
    } catch (error) { toast(error.message, 'error'); }
  };
  if (el('library').classList.contains('active')) window.loadLibrary();
})();
