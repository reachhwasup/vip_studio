(() => {
  const el = id => document.getElementById(id), video = el('subtitleTimingVideo');
  let videoURL;
  window.refreshSubtitleTiming = () => {
    const end = importedSubtitles.reduce((max, cue) => Math.max(max, cue.end_time), 0);
    el('subtitleTargetEnd').value = end || '';
    el('subtitleApplyTiming').disabled = el('subtitleResetTiming').disabled = !importedSubtitles.length;
    const duration = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : null;
    el('subtitleUseDuration').disabled = !duration || !importedSubtitles.length;
    el('subtitleTimingSummary').textContent = `Last caption end: ${end.toFixed(3)}s` + (duration ? ` · Video: ${duration.toFixed(3)}s · Difference: ${(end - duration).toFixed(3)}s` : ' · Choose a video to compare duration.');
  };
  el('subtitleTimingVideoFile').onchange = () => {
    video.pause(); video.removeAttribute('src'); video.load();
    if (videoURL) URL.revokeObjectURL(videoURL);
    const file = el('subtitleTimingVideoFile').files[0]; video.hidden = !file;
    if (file) { videoURL = URL.createObjectURL(file); video.src = videoURL; }
    window.refreshSubtitleTiming();
  };
  video.addEventListener('loadedmetadata', window.refreshSubtitleTiming);
  video.addEventListener('error', () => { el('subtitleTimingSummary').textContent = 'Cannot read this video. Enter the target caption end manually.'; el('subtitleUseDuration').disabled = true; });
  el('subtitleUseDuration').onclick = () => { el('subtitleTargetEnd').value = video.duration.toFixed(3); };
  el('subtitleApplyTiming').onclick = () => {
    try {
      importedSubtitles = window.retimeSubtitles(importedSubtitles, el('subtitleTargetEnd').valueAsNumber, el('subtitleTimingOffset').valueAsNumber);
      previewSubtitles(); el('subtitleTimingOffset').value = 0;
      el('subtitleImportStatus').textContent = 'Timing adjusted. Export subtitles to save the corrected file.';
    } catch (error) { el('subtitleImportStatus').textContent = error.message; }
  };
  el('subtitleResetTiming').onclick = () => { importedSubtitles = originalImportedSubtitles.map(c => ({...c})); el('subtitleTimingOffset').value = 0; previewSubtitles(); el('subtitleImportStatus').textContent = 'Original imported timings restored.'; };
})();
