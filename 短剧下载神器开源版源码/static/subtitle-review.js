(() => {
  const dialog = document.createElement('dialog'); dialog.id = 'subtitleReviewDialog'; dialog.className = 'detail subtitle-review';
  dialog.innerHTML = `<div class="library-player-heading"><h2 id="reviewTitle">Subtitle review</h2><button id="reviewClose" class="btn2">Close</button></div><div class="review-layout"><div class="review-preview"><div class="review-video-wrap"><video id="reviewVideo" controls playsinline preload="metadata"></video><div id="reviewCaption" aria-hidden="true"></div></div><p class="hint">Preview shows your edited captions. Click a caption’s time to jump to it.</p><div class="review-toolbar"><label>Shift all timings (seconds)<input id="reviewOffset" type="number" step="0.1" value="0"></label><button id="reviewShift" class="btn2">Apply shift</button></div><p id="reviewTimingSummary" class="hint"></p><div class="review-toolbar"><label>Last caption end (seconds)<input id="reviewTargetEnd" type="number" min="0.001" step="0.001"></label><button id="reviewUseDuration" class="btn2">Use video duration</button><button id="reviewRetime" class="btn2">Stretch / compress</button></div><p class="hint">Correct gradual drift by changing the last caption end. Dialogue may end before the video. For a fixed delay, use Shift above. Undo restores the previous timings.</p><div class="review-toolbar"><button id="reviewAdd" class="btn2">Add at playhead</button><button id="reviewUndo" class="btn2" disabled>Undo</button><button id="reviewRedo" class="btn2" disabled>Redo</button><button id="reviewSave">Save SRT</button></div><p id="reviewStatus" role="status"></p><small>Saving creates a backup. Changes stay local until you save.</small></div><div class="review-editor"><section class="review-quality" aria-labelledby="reviewQualityTitle"><h3 id="reviewQualityTitle">Quality checks</h3><p class="hint">Gaps of 5+ seconds, overlaps and unusual text are flagged for review. Silence and intentional text can also be flagged; missing dialogue cannot be confirmed automatically.</p><p id="reviewQualitySummary" role="status"></p><div id="reviewIssues" class="review-issues"></div></section><div id="reviewCues" class="review-cues"></div></div></div>`;
  document.body.append(dialog);
  const el = id => document.getElementById(id), video = el('reviewVideo');
  let speechSuggestions = [];
  let segments = [], url = '', revision = '', dirty = false, saving = false, generation = 0, loaded = false, qualityTimer;
  const message = text => el('reviewStatus').textContent = text;
  function markDirty() { const current = JSON.stringify(segments); if (current !== lastState) { undo.push(lastState); if (undo.length > 60) undo.shift(); redo = []; lastState = current; historyButtons(); } dirty = true; message('Unsaved changes'); preview(); clearTimeout(qualityTimer); qualityTimer = setTimeout(checkQuality, 250); }
  let undo = [], redo = [], lastState = '[]';
  function historyButtons() { el('reviewUndo').disabled = saving || !undo.length; el('reviewRedo').disabled = saving || !redo.length; }
  function resetHistory() { undo = []; redo = []; lastState = JSON.stringify(segments); historyButtons(); }
  function restore(from, to) {
    if (saving || !from.length) return;
    to.push(JSON.stringify(segments)); segments = JSON.parse(from.pop()); lastState = JSON.stringify(segments);
    dirty = true; render(); historyButtons(); message('Unsaved changes');
  }
  el('reviewUndo').onclick = () => restore(undo, redo);
  el('reviewRedo').onclick = () => restore(redo, undo);
  let shown = null;
  function preview() {
    const current = video.currentTime, active = [];
    segments.forEach((c, i) => { if (current >= c.start_time && current < c.end_time) active.push(i); });
    const caption = active.map(i => (segments[i].speaker ? segments[i].speaker + ': ' : '') + segments[i].text).join('\n'), state = active.join(',') + '\n' + caption;
    if (state === shown) return;
    shown = state; el('reviewCaption').textContent = caption;
    el('reviewCues').querySelectorAll('.review-cue').forEach((row, i) => row.classList.toggle('is-current', active.includes(i)));
  }
  // timeupdate fires only a few times a second, which shows captions late and skips short ones: follow each video frame while playing.
  function follow() { preview(); if (!video.paused && !video.ended) (video.requestVideoFrameCallback ? video.requestVideoFrameCallback.bind(video) : requestAnimationFrame)(follow); }
  function checkQuality() {
    clearTimeout(qualityTimer);
    const end = segments.reduce((max, cue) => Math.max(max, cue.end_time || 0), 0);
    el('reviewTimingSummary').textContent = `Last caption end: ${end.toFixed(3)}s · Video: ${Number.isFinite(video.duration) ? video.duration.toFixed(3) + 's' : 'loading…'}`;
    el('reviewRetime').disabled = saving || !loaded || !segments.length;
    el('reviewUseDuration').disabled = saving || !loaded || !Number.isFinite(video.duration) || video.duration <= 0;
    const list = el('reviewIssues'); list.replaceChildren();
    if (!loaded) { el('reviewQualitySummary').textContent = 'Load subtitles to check quality.'; return; }
    const issues = window.analyzeSubtitleQuality(segments, video.duration);
    el('reviewQualitySummary').textContent = issues.length ? `${issues.length} timing/text issues · ${speechSuggestions.length} speech suggestions · Click to review` : (speechSuggestions.length ? `${speechSuggestions.length} speech suggestions · Click to compare with the video` : 'No issues found by these checks.');
    el('reviewCues').querySelectorAll('.review-cue').forEach((row, index) => row.classList.toggle('has-issue', issues.some(issue => issue.index === index)));
    for (const issue of issues) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'review-issue';
      const seconds = Math.floor(issue.time);
      button.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')} · ${issue.index === null ? 'End of video' : 'Caption #' + (issue.index + 1)} · ${issue.text}`;
      button.onclick = () => {
        video.pause(); video.currentTime = Math.min(issue.time, Number.isFinite(video.duration) ? video.duration : issue.time); preview();
        if (issue.index !== null) {
          const row = el('reviewCues').children[issue.index];
          row.scrollIntoView({block: 'nearest', behavior: 'smooth'});
          row.querySelector(issue.kind === 'overlap' || issue.kind === 'timing' ? 'input' : 'textarea').focus({preventScroll: true});
        } else video.focus();
      };
      list.append(button);
    }
    for (const cue of speechSuggestions) {
      if (!Number.isFinite(cue.start_time) || !Number.isFinite(cue.end_time)) continue;
      const button = document.createElement('button'); button.type = 'button'; button.className = 'review-issue';
      button.textContent = `Speech suggestion at ${cue.start_time.toFixed(1)}s: ${cue.text} — compare before editing`;
      button.onclick = () => {
        video.pause(); video.currentTime = Math.max(0, cue.start_time); preview();
        const index = segments.findIndex(c => c.start_time < cue.end_time && c.end_time > cue.start_time);
        if (index >= 0) {
          const row = el('reviewCues').children[index]; row.scrollIntoView({block: 'nearest'}); row.querySelector('textarea').focus({preventScroll: true});
        }
      };
      list.append(button);
    }
  }
  video.addEventListener('loadedmetadata', checkQuality);
  video.addEventListener('durationchange', checkQuality);
  function render() {
    el('reviewCues').replaceChildren();
    segments.forEach((cue, index) => {
      const row = document.createElement('div'); row.className = 'review-cue';
      const controls = document.createElement('div'); controls.className = 'review-cue-times';
      const seek = document.createElement('button'); seek.className = 'btn3'; seek.textContent = '#' + (index + 1); seek.title = 'Jump to caption'; seek.onclick = () => { video.currentTime = cue.start_time; preview(); };
      controls.append(seek);
      for (const [key, label] of [['start_time', 'Start'], ['end_time', 'End']]) {
        const field = document.createElement('label'); field.textContent = label + ' (s)'; const input = document.createElement('input'); input.type = 'number'; input.min = '0'; input.step = '0.125'; input.value = cue[key]; input.setAttribute('aria-label', `${label} time for caption ${index + 1}`); input.oninput = () => { cue[key] = input.valueAsNumber; markDirty(); }; field.append(input); controls.append(field);
      }
      const remove = document.createElement('button'); remove.className = 'btn2'; remove.textContent = '×'; remove.setAttribute('aria-label', 'Delete caption ' + (index + 1)); remove.onclick = () => { segments.splice(index, 1); markDirty(); render(); }; controls.append(remove);
      const text = document.createElement('textarea'); text.rows = 2; text.value = cue.text; text.setAttribute('aria-label', 'Text for caption ' + (index + 1)); text.oninput = () => { cue.text = text.value; markDirty(); };
      const speaker = document.createElement('input'); speaker.placeholder = 'Speaker (optional)'; speaker.value = cue.speaker || ''; speaker.setAttribute('aria-label', 'Speaker for caption ' + (index + 1)); speaker.oninput = () => { cue.speaker = speaker.value; markDirty(); };
      row.append(controls, text, speaker); el('reviewCues').append(row);
    }); shown = null; preview(); checkQuality();
  }
  async function open(urlValue, title) {
    if (saving) return;
    el('reviewTargetEnd').value = '';
    const token = ++generation; url = urlValue; revision = ''; dirty = false; loaded = false; segments = []; speechSuggestions = []; resetHistory(); render();
    el('reviewTitle').textContent = title + ' · Subtitle review'; el('reviewSave').disabled = true;
    el('reviewAdd').disabled = true; el('reviewShift').disabled = true;
    video.src = url; message('Loading subtitles…'); if (!dialog.open) dialog.showModal();
    try {
      const response = await fetch('/api/subtitles/review?url=' + encodeURIComponent(url)); const data = await vipReadJSON(response);
      if (!response.ok) throw new Error(data.error || 'Could not load subtitles.');
      if (token !== generation) return;
      segments = data.segments; speechSuggestions = Array.isArray(data.analysis?.review_candidates) ? data.analysis.review_candidates : []; revision = data.revision; loaded = true; resetHistory(); render(); message(`${segments.length} captions loaded`);
      el('reviewSave').disabled = false; el('reviewAdd').disabled = false; el('reviewShift').disabled = false;
    } catch (error) { if (token === generation) message(error.message); }
  }
  window.openSubtitleReview = open;
  el('reviewUseDuration').onclick = () => { el('reviewTargetEnd').value = video.duration.toFixed(3); };
  el('reviewRetime').onclick = () => {
    if (saving || !loaded) return;
    try { segments = window.retimeSubtitles(segments, el('reviewTargetEnd').valueAsNumber); markDirty(); render(); }
    catch (error) { message(error.message); }
  };
  function close() { if (saving) return; if (dirty && !confirm('Discard your unsaved subtitle edits?')) return; ++generation; dialog.close(); }
  el('reviewClose').onclick = close; dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  dialog.addEventListener('close', () => { video.pause(); video.removeAttribute('src'); video.load(); }); video.addEventListener('timeupdate', preview); video.addEventListener('seeked', preview); video.addEventListener('play', follow);
  el('reviewAdd').onclick = () => { const start = Math.round(video.currentTime * 1000) / 1000; segments.push({start_time: start, end_time: start + 2, text: '', speaker: ''}); markDirty(); render(); el('reviewCues').lastElementChild.scrollIntoView({block: 'nearest'}); };
  el('reviewShift').onclick = () => { const offset = el('reviewOffset').valueAsNumber; if (!Number.isFinite(offset) || segments.some(c => !Number.isFinite(c.start_time) || !Number.isFinite(c.end_time) || c.start_time + offset < 0)) { message('Enter a valid shift that keeps every caption at or after 0 seconds.'); return; } segments.forEach(c => { c.start_time = Math.round((c.start_time + offset) * 1000) / 1000; c.end_time = Math.round((c.end_time + offset) * 1000) / 1000; }); markDirty(); render(); };
  el('reviewSave').onclick = async () => {
    if (saving) return;
    saving = true; checkQuality(); historyButtons(); el('reviewSave').disabled = true; el('reviewClose').disabled = true;
    el('reviewCues').inert = true; el('reviewAdd').disabled = true; el('reviewShift').disabled = true; message('Saving…');
    try {
      const response = await fetch('/api/subtitles/review', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url, revision, segments})}); const data = await vipReadJSON(response);
      if (!response.ok) throw new Error(data.error || 'Could not save subtitles.');
      revision = data.revision; segments = data.segments; dirty = false; resetHistory(); render(); message(`${data.captions} captions saved. Previous SRT backed up.`); toast('Subtitle edits saved', 'success'); window.dispatchEvent(new CustomEvent('vip-subtitles-saved', {detail: {url}}));
    } catch (error) { message(error.message); }
    finally { saving = false; checkQuality(); historyButtons(); el('reviewSave').disabled = false; el('reviewClose').disabled = false; el('reviewCues').inert = false; el('reviewAdd').disabled = false; el('reviewShift').disabled = false; }
  };
})();
