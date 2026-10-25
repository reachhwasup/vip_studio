(() => {
  const el = id => document.getElementById(id);
  let items = [], selected = null, requestId = 0;
  const video = el('libraryVideo');
  let selectedEpisode = null;
  const subtitleJobs = new Map();
  const readSetting = (key, fallback) => { try { return localStorage.getItem(key) ?? fallback; } catch (_) { return fallback; } };
  const writeSetting = (key, value) => { try { localStorage.setItem(key, value); } catch (_) {} };
  let playback = {};
  try { const data = JSON.parse(readSetting('vip_playback', '{}')); if (data && typeof data === 'object' && !Array.isArray(data)) playback = Object.fromEntries(Object.entries(data).filter(([, value]) => value && Number.isFinite(value.time) && Number.isFinite(value.updated)).sort((a, b) => b[1].updated - a[1].updated).slice(0, 500)); } catch (_) {}
  let lastProgressWrite = 0, pendingResume = 0;
  function saveProgress(force = false) {
    if (!selectedEpisode || !Number.isFinite(video.duration) || video.duration <= 0 || (!force && Date.now() - lastProgressWrite < 3000)) return;
    lastProgressWrite = Date.now();
    playback[selectedEpisode.url] = {time: video.currentTime, duration: video.duration, completed: video.ended, updated: Date.now()};
    playback = Object.fromEntries(Object.entries(playback).sort((a, b) => b[1].updated - a[1].updated).slice(0, 500));
    writeSetting('vip_playback', JSON.stringify(playback));
  }
  function rememberSelect(id, key, fallback) {
    const control = el(id), stored = readSetting(key, fallback);
    control.value = Array.from(control.options).some(option => option.value === stored) ? stored : fallback;
    control.addEventListener('change', () => writeSetting(key, control.value));
  }
  rememberSelect('subtitleMethod', 'vip_subtitle_method', 'auto');
  rememberSelect('subtitleLanguage', 'vip_subtitle_language', 'zh');
  rememberSelect('librarySort', 'vip_library_sort', 'recent');
  rememberSelect('librarySpeed', 'vip_playback_speed', '1');
  for (const [id, key, fallback] of [['libraryCaptions', 'vip_show_captions', '1'], ['libraryAutoplay', 'vip_autoplay', '0']]) {
    el(id).checked = readSetting(key, fallback) === '1';
    el(id).addEventListener('change', () => writeSetting(key, el(id).checked ? '1' : '0'));
  }
  function applyCaptions() { for (const track of video.textTracks) track.mode = el('libraryCaptions').checked ? 'showing' : 'hidden'; }
  function refreshTrack() {
    video.querySelectorAll('track').forEach(track => track.remove());
    if (!selectedEpisode?.subtitle_url) return;
    const track = document.createElement('track'); track.kind = 'subtitles'; track.label = 'Saved subtitles'; track.default = el('libraryCaptions').checked;
    track.src = '/api/subtitles/track?url=' + encodeURIComponent(selectedEpisode.url) + '&v=' + Date.now();
    track.addEventListener('load', applyCaptions);
    track.addEventListener('error', () => { if (track.isConnected) el('libraryPlaybackStatus').textContent = 'Subtitles could not load. You can still watch the video, or review the SRT.'; });
    video.append(track); applyCaptions();
  }
  el('libraryCaptions').addEventListener('change', applyCaptions);
  el('librarySpeed').addEventListener('change', () => { video.playbackRate = Number(el('librarySpeed').value); });
  window.addEventListener('vip-subtitles-saved', event => { if (selectedEpisode?.url === event.detail.url) { if (event.detail.subtitle_url) selectedEpisode.subtitle_url = event.detail.subtitle_url; refreshTrack(); renderSubtitleStatus(); } });
  video.addEventListener('loadedmetadata', () => {
    video.playbackRate = Number(el('librarySpeed').value);
    const position = vipLibraryTools.resumePosition(pendingResume, video.duration);
    if (position) { video.currentTime = position; el('libraryPlaybackStatus').textContent = `Resumed at ${Math.floor(position / 60)}:${String(Math.floor(position % 60)).padStart(2, '0')}. Use Start over to replay.`; }
    pendingResume = null;
  });
  video.addEventListener('timeupdate', () => saveProgress());
  video.addEventListener('pause', () => saveProgress(true));
  window.addEventListener('pagehide', () => saveProgress(true));
  function moveEpisode(offset) {
    if (!selected) return;
    const index = selected.episodes.findIndex(episode => episode.url === selectedEpisode?.url) + offset;
    if (index < 0 || index >= selected.episodes.length) return;
    play(selected.episodes[index], el('libraryEpisodes').children[index]);
  }
  el('previousLibraryEpisode').onclick = () => moveEpisode(-1);
  el('nextLibraryEpisode').onclick = () => moveEpisode(1);
  el('restartLibraryEpisode').onclick = () => { pendingResume = null; video.currentTime = 0; saveProgress(true); el('libraryPlaybackStatus').textContent = 'Playing from the beginning.'; video.play().catch(() => {}); };
  video.addEventListener('ended', () => { saveProgress(true); if (el('libraryAutoplay').checked) moveEpisode(1); });
  function renderSubtitleStatus() {
    const episode = selectedEpisode, job = episode && (window.downloadSubtitleJobForURL?.(episode.url) || subtitleJobs.get(episode.url));
    const button = el('regenerateLibrarySubtitles'), link = el('librarySubtitleLink');
    const busy = job && ['queued', 'running', 'starting'].includes(job.status);
    button.disabled = !episode || !!busy;
    el('reviewLibrarySubtitles').disabled = !episode?.subtitle_url || !!busy;
    button.textContent = busy ? (job.status === 'running' ? (job.stage || 'Processing subtitles…') : 'Queued…') : episode && episode.subtitle_url ? 'Regenerate subtitles' : 'Create subtitles';
    const status = !episode ? 'Choose an episode.' : job?.status === 'error' ? job.error : job?.status === 'done' ? `${job.captions} captions saved · ${job.method === 'hybrid' ? `Captions + speech · ${job.audio_added || 0} gaps recovered · ${job.review_count || 0} speech lines to review` : job.method === 'picture' ? 'Read from video' : 'From speech recognition'}${job.warnings?.length ? ' · '+job.warnings.join(' ') : ''}` : busy ? (job.retrying ? 'Reconnecting to subtitle processing. Your job may still be running.' : 'Processing locally. You can keep browsing while this finishes.') : episode.subtitle_url ? 'SRT available for this episode.' : 'No subtitle file saved yet.';
    const percent = Number.isFinite(job?.progress) ? Math.round(job.progress) : null;
    el('librarySubtitleStatus').textContent = busy ? (job.status === 'queued' ? 'Waiting for subtitle worker…' : (job.stage || 'Processing subtitles…') + (percent !== null ? ` · ${percent}%` : '') + (job.total ? ` · ${job.completed}/${job.total} images` : '')) : status;
    const progress = el('librarySubtitleProgress'); progress.hidden = !busy;
    if (job?.status === 'queued') progress.value = 0;
    else if (percent !== null && job?.status === 'running') progress.value = percent;
    else progress.removeAttribute('value');
    link.hidden = !episode?.subtitle_url;
    if (episode?.subtitle_url) link.href = episode.subtitle_url + (episode.subtitle_url.includes('?') ? '&' : '?') + 'v=' + (job?.updated_at || Date.now());
  }
  window.addEventListener('vip-subtitle-progress', event => { if (event.detail.job && selectedEpisode?.url === event.detail.url) {subtitleJobs.set(event.detail.url, event.detail.job); renderSubtitleStatus();} });
  function rememberSubtitleJobs() {
    try { localStorage.setItem('vip_subtitle_jobs', JSON.stringify(Array.from(subtitleJobs).filter(([, job]) => ['queued', 'running'].includes(job.status)))); } catch (_) {}
  }
  async function watchSubtitleJob(url, job) {
    try {
      const response = await fetch('/api/subtitles/regenerate?id=' + encodeURIComponent(job.id));
      const data = await vipReadJSON(response);
      if (!response.ok) { const error = new Error(data.error || 'Could not check subtitle status.'); error.status = response.status; throw error; }
      subtitleJobs.set(url, data); rememberSubtitleJobs();
      window.dispatchEvent(new CustomEvent('vip-subtitle-progress', {detail: {url, job: data}}));
      if (data.status === 'done') {
        items.forEach(drama => drama.episodes.forEach(episode => { if (episode.url === url) episode.subtitle_url = data.subtitle_url; }));
        if (selectedEpisode?.url === url) { selectedEpisode.subtitle_url = data.subtitle_url; refreshTrack(); }
        render();
        toast(`Subtitles ready: ${data.title} · ${data.captions} captions`, 'success');
        notifyDone('Subtitles ready', `${data.title} · ${data.captions} captions`);
      } else if (data.status === 'error') toast('Subtitle regeneration failed: ' + data.error, 'error');
      else setTimeout(() => watchSubtitleJob(url, data), 1500);
      renderSubtitleStatus();
    } catch (error) {
      if (error.status === 404 || error.status === 400) {
        subtitleJobs.set(url, {...job, status: 'error', error: 'This job is no longer available, possibly after an app restart. Refresh Library to check the saved SRT before trying again.'});
      } else {
        const retry = {...job, retrying: true, retries: (job.retries || 0) + 1};
        subtitleJobs.set(url, retry);
        setTimeout(() => watchSubtitleJob(url, retry), Math.min(30000, 1500 * 2 ** Math.min(retry.retries, 5)));
      }
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
      const response = await fetch('/api/subtitles/regenerate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url: episode.url, mode: el('subtitleMethod').value, language: el('subtitleLanguage').value})});
      const data = await vipReadJSON(response);
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
    saveProgress(true); video.pause();
    selectedEpisode = episode; pendingResume = playback[episode.url]; renderSubtitleStatus();
    video.src = episode.url;
    refreshTrack();
    const index = selected.episodes.indexOf(episode);
    el('previousLibraryEpisode').disabled = index <= 0;
    el('nextLibraryEpisode').disabled = index >= selected.episodes.length - 1;
    el('libraryEpisodeTitle').textContent = episode.title;
    el('libraryPlaybackStatus').textContent = '';
    el('libraryEpisodes').querySelectorAll('button').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    if (button?.hidden) { el('playerEpisodeSearch').value = ''; filterPlayerEpisodes(); }
    revealCurrentEpisode();
    video.play().catch(() => { el('libraryPlaybackStatus').textContent = 'Press Play to start. If this video cannot play in your browser, open its folder to use your video player.'; });
  }
  function revealCurrentEpisode() {
    const list = el('libraryEpisodes'), current = list.querySelector('[aria-pressed="true"]');
    if (!current || current.hidden) return;
    const top = current.getBoundingClientRect().top - list.getBoundingClientRect().top + list.scrollTop;
    list.scrollTop = Math.max(0, top - list.clientHeight / 2 + current.offsetHeight / 2);
  }
  function filterPlayerEpisodes() {
    const query = el('playerEpisodeSearch').value.trim().toLocaleLowerCase();
    let visible = 0;
    el('libraryEpisodes').querySelectorAll('button').forEach(button => {
      button.hidden = !!query && !button.dataset.search.includes(query);
      if (!button.hidden) visible++;
    });
    el('playerEpisodeEmpty').hidden = visible > 0;
    el('playerEpisodeCount').textContent = selected ? `${selected.episodes.length} saved${query ? ` · ${visible} matching` : ''}` : '';
  }
  el('playerEpisodeSearch').oninput = filterPlayerEpisodes;
  el('playerCurrentEpisode').onclick = () => { el('playerEpisodeSearch').value = ''; filterPlayerEpisodes(); revealCurrentEpisode(); };
  function openDrama(drama) {
    if (!drama.episodes.length) return;
    selected = drama;
    el('libraryTitle').textContent = drama.title;
    video.poster = drama.poster;
    el('libraryEpisodes').replaceChildren();
    el('playerEpisodeSearch').value = '';
    drama.episodes.forEach((episode, index) => {
      const number = episode.title.match(/Episode\s*(\d+)/i)?.[1] || String(index + 1);
      const button = node('button', '', 'btn2 player-episode');
      button.title = episode.title; button.setAttribute('aria-label', episode.title);
      button.dataset.search = (episode.title + ' ' + Number(number)).toLocaleLowerCase();
      button.append(node('span', 'EP ' + number, 'player-episode-number'), node('small', episode.subtitle_url ? 'SRT' : 'Video', 'player-episode-caption'));
      button.onclick = () => play(episode, button);
      el('libraryEpisodes').append(button);
    });
    filterPlayerEpisodes();
    el('libraryDialog').showModal();
    const ongoing = drama.episodes.filter(ep => playback[ep.url]?.time >= 3 && !playback[ep.url]?.completed).sort((a, b) => playback[b.url].updated - playback[a.url].updated)[0];
    const episode = ongoing || drama.episodes[0];
    play(episode, el('libraryEpisodes').children[drama.episodes.indexOf(episode)]);
  }
  function render() {
    const query = el('librarySearch').value.trim().toLocaleLowerCase();
    const visible = vipLibraryTools.selectLibrary(items, query, el('libraryFilter').value, el('librarySort').value, playback);
    el('libraryGrid').replaceChildren();
    el('libraryStatus').textContent = items.length ? `${items.length} dramas · ${items.reduce((count, drama) => count + drama.episodes.length, 0)} saved episodes${query || el('libraryFilter').value !== 'all' ? ` · ${visible.length} matching dramas` : ''}` : 'No saved episodes yet. Download a drama, then refresh your library.';
    if (!visible.length) {
      const empty = node('div', '', 'library-empty');
      empty.append(node('h2', items.length ? 'No dramas match these filters' : 'Your library is ready for its first drama'), node('p', items.length ? 'Try a different title or show all dramas.' : 'Download an episode from Discover, then refresh this library.'));
      const action = node('button', items.length ? 'Reset filters' : 'Discover dramas', 'btn3');
      action.onclick = () => { if (items.length) { el('librarySearch').value = ''; el('libraryFilter').value = 'all'; render(); } else setTab('search'); };
      empty.append(action); el('libraryGrid').append(empty);
    }
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
      const available = drama.episodes.filter(ep => ep.subtitle_url).length;
      card.append(node('p', `${available}/${drama.episodes.length} episodes with subtitles`, available === drama.episodes.length ? 'library-caption-count ready' : 'library-caption-count'));
      const ongoing = drama.episodes.some(ep => playback[ep.url]?.time >= 3 && !playback[ep.url]?.completed);
      const watch = node('button', ongoing ? 'Continue watching' : 'View episodes', 'btn3'); watch.onclick = () => openDrama(drama); card.append(watch);
      el('libraryGrid').append(card);
    });
  }
  window.loadLibrary = async () => {
    const id = ++requestId;
    el('libraryStatus').textContent = 'Looking for saved episodes…';
    el('refreshLibrary').disabled = true;
    try {
      const response = await fetch('/api/library');
      const data = await vipReadJSON(response);
      if (!response.ok) throw new Error(data.error || 'Could not load library.');
      if (id !== requestId) return;
      items = data.items; render();
    } catch (error) { if (id === requestId) el('libraryStatus').textContent = error.message; }
    finally { if (id === requestId) el('refreshLibrary').disabled = false; }
  };
  el('refreshLibrary').onclick = window.loadLibrary;
  el('librarySearch').oninput = render;
  el('librarySort').addEventListener('change', render);
  el('libraryFilter').onchange = render;
  el('closeLibraryPlayer').onclick = () => el('libraryDialog').close();
  el('libraryDialog').addEventListener('close', () => { saveProgress(true); video.pause(); selectedEpisode = null; video.querySelectorAll('track').forEach(track => track.remove()); video.removeAttribute('src'); video.load(); render(); });
  video.addEventListener('error', () => { el('libraryPlaybackStatus').textContent = 'This video could not play. Open its folder to watch it with your video player.'; });
  el('openLibraryFolder').onclick = async () => {
    if (!selected) return;
    try {
      const response = await fetch('/api/library/open-folder', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({root: selected.root, folder: selected.folder})});
      const data = await vipReadJSON(response);
      if (!response.ok) throw new Error(data.error || 'Could not open folder.');
      toast('Download folder opened', 'success');
    } catch (error) { toast(error.message, 'error'); }
  };
  if (el('library').classList.contains('active')) window.loadLibrary();
})();
