/* Shared response handling and local playback state. */
(function (root) {
  async function readJSON(response) {
    const type = response.headers.get('content-type') || '';
    if (!type.includes('application/json')) {
      const error = new Error(`The app received an unexpected response (HTTP ${response.status}). Try again; if it continues, restart VIP Studio.`);
      error.status = response.status; throw error;
    }
    try { return await response.json(); }
    catch (_) { const error = new Error('The app received an incomplete response. Please try again.'); error.status = response.status; throw error; }
  }
  function resumePosition(saved, duration) {
    if (!saved || saved.completed || !Number.isFinite(saved.time) || !Number.isFinite(duration) || duration <= 0) return 0;
    return saved.time >= 3 && saved.time < duration - 2 ? saved.time : 0;
  }
  function selectLibrary(items, query, filter, order, progress) {
    query = query.trim().toLocaleLowerCase();
    return items.filter(drama => {
      const matches = drama.title.toLocaleLowerCase().includes(query) || drama.episodes.some(ep => ep.title.toLocaleLowerCase().includes(query));
      return matches && (filter === 'missing' ? drama.episodes.some(ep => !ep.subtitle_url) : filter === 'continue' ? drama.episodes.some(ep => progress[ep.url]?.time >= 3 && !progress[ep.url]?.completed) : true);
    }).sort((a, b) => order === 'title' ? a.title.localeCompare(b.title) : order === 'episodes' ? b.episodes.length - a.episodes.length : b.modified - a.modified);
  }
  root.vipReadJSON = readJSON;
  root.vipLibraryTools = {resumePosition, selectLibrary};
  if (typeof module !== 'undefined') module.exports = {readJSON, resumePosition, selectLibrary};
})(globalThis);
