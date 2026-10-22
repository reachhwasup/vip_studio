/* Scale timeline positions to correct progressive drift; offset corrects a fixed delay. */
(function (root) {
  function retime(segments, targetEnd, offset = 0) {
    if (!segments.length) throw new Error('Load subtitles first.');
    if (!Number.isFinite(targetEnd) || targetEnd <= 0 || !Number.isFinite(offset)) throw new Error('Enter a positive target end and a valid offset in seconds.');
    let end = 0;
    for (const cue of segments) {
      if (!Number.isFinite(cue.start_time) || !Number.isFinite(cue.end_time) || cue.start_time < 0 || cue.end_time <= cue.start_time) throw new Error('Fix invalid caption timings before synchronizing.');
      end = Math.max(end, cue.end_time);
    }
    const scale = (targetEnd - offset) / end;
    if (scale <= 0) throw new Error('Target end must be after the offset.');
    return segments.map(cue => {
      const start_time = Math.round((cue.start_time * scale + offset) * 1000) / 1000;
      const end_time = Math.round((cue.end_time * scale + offset) * 1000) / 1000;
      if (start_time < 0 || end_time <= start_time) throw new Error('Adjustment would create negative or zero-length captions. Choose different timings.');
      if (end_time - start_time > 30) throw new Error('Adjustment would exceed the 30-second caption limit. Split long captions before stretching.');
      return {...cue, start_time, end_time};
    });
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = retime;
  else root.retimeSubtitles = retime;
})(typeof window !== 'undefined' ? window : globalThis);
