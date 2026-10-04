(() => {
  const dialog = document.createElement('dialog'); dialog.id = 'subtitleReviewDialog'; dialog.className = 'detail subtitle-review';
  dialog.innerHTML = `<div class="library-player-heading"><h2 id="reviewTitle">Subtitle review</h2><button id="reviewClose" class="btn2">Close</button></div><div class="review-layout"><div class="review-preview"><div class="review-video-wrap"><video id="reviewVideo" controls playsinline preload="metadata"></video><div id="reviewCaption" aria-hidden="true"></div></div><p class="hint">Preview shows your edited captions. Click a caption’s time to jump to it.</p><div class="review-toolbar"><label>Shift all timings (seconds)<input id="reviewOffset" type="number" step="0.1" value="0"></label><button id="reviewShift" class="btn2">Apply shift</button></div><div class="review-toolbar"><button id="reviewAdd" class="btn2">Add at playhead</button><button id="reviewSave">Save SRT</button></div><p id="reviewStatus" role="status"></p><small>Saving creates a backup. Changes stay local until you save.</small></div><div id="reviewCues" class="review-cues"></div></div>`;
  document.body.append(dialog);
  const el = id => document.getElementById(id), video = el('reviewVideo');
  let segments = [], url = '', revision = '', dirty = false, saving = false, generation = 0;
  const message = text => el('reviewStatus').textContent = text;
  function markDirty() { dirty = true; message('Unsaved changes'); preview(); }
  function preview() {
    const current = video.currentTime;
    el('reviewCaption').textContent = segments.filter(c => current >= c.start_time && current < c.end_time).map(c => (c.speaker ? c.speaker + ': ' : '') + c.text).join('\n');
    el('reviewCues').querySelectorAll('.review-cue').forEach((row, i) => row.classList.toggle('is-current', current >= segments[i].start_time && current < segments[i].end_time));
  }
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
    }); preview();
  }
  async function open(urlValue, title) {
    if (saving) return;
    const token = ++generation; url = urlValue; revision = ''; dirty = false; segments = []; render();
    el('reviewTitle').textContent = title + ' · Subtitle review'; el('reviewSave').disabled = true;
    el('reviewAdd').disabled = true; el('reviewShift').disabled = true;
    video.src = url; message('Loading subtitles…'); if (!dialog.open) dialog.showModal();
    try {
      const response = await fetch('/api/subtitles/review?url=' + encodeURIComponent(url)); const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not load subtitles.');
      if (token !== generation) return;
      segments = data.segments; revision = data.revision; render(); message(`${segments.length} captions loaded`);
      el('reviewSave').disabled = false; el('reviewAdd').disabled = false; el('reviewShift').disabled = false;
    } catch (error) { if (token === generation) message(error.message); }
  }
  window.openSubtitleReview = open;
  function close() { if (saving) return; if (dirty && !confirm('Discard your unsaved subtitle edits?')) return; ++generation; dialog.close(); }
  el('reviewClose').onclick = close; dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  dialog.addEventListener('close', () => { video.pause(); video.removeAttribute('src'); video.load(); }); video.addEventListener('timeupdate', preview);
  el('reviewAdd').onclick = () => { const start = Math.round(video.currentTime * 1000) / 1000; segments.push({start_time: start, end_time: start + 2, text: '', speaker: ''}); markDirty(); render(); el('reviewCues').lastElementChild.scrollIntoView({block: 'nearest'}); };
  el('reviewShift').onclick = () => { const offset = el('reviewOffset').valueAsNumber; if (!Number.isFinite(offset) || segments.some(c => !Number.isFinite(c.start_time) || !Number.isFinite(c.end_time) || c.start_time + offset < 0)) { message('Enter a valid shift that keeps every caption at or after 0 seconds.'); return; } segments.forEach(c => { c.start_time = Math.round((c.start_time + offset) * 1000) / 1000; c.end_time = Math.round((c.end_time + offset) * 1000) / 1000; }); markDirty(); render(); };
  el('reviewSave').onclick = async () => {
    if (saving) return;
    saving = true; el('reviewSave').disabled = true; el('reviewClose').disabled = true;
    el('reviewCues').inert = true; el('reviewAdd').disabled = true; el('reviewShift').disabled = true; message('Saving…');
    try {
      const response = await fetch('/api/subtitles/review', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url, revision, segments})}); const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not save subtitles.');
      revision = data.revision; segments = data.segments; dirty = false; render(); message(`${data.captions} captions saved. Previous SRT backed up.`); toast('Subtitle edits saved', 'success');
    } catch (error) { message(error.message); }
    finally { saving = false; el('reviewSave').disabled = false; el('reviewClose').disabled = false; el('reviewCues').inert = false; el('reviewAdd').disabled = false; el('reviewShift').disabled = false; }
  };
})();
