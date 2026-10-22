/* Advisory checks: gaps and text patterns require human review, not automatic repair. */
(function (root) {
  function analyze(segments, duration) {
    const issues = [];
    const add = (kind, index, time, text) => issues.push({kind, index, time, text});
    const valid = [];
    segments.forEach((cue, index) => {
      const start = cue.start_time, end = cue.end_time, text = String(cue.text || '').trim();
      if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) {
        add('timing', index, Number.isFinite(start) ? Math.max(0, start) : 0, 'Invalid start or end time.');
      } else {
        valid.push({start, end, index});
        if (end - start > 30) add('timing', index, start, 'Caption exceeds 30 seconds.');
        if (Number.isFinite(duration) && duration > 0 && end > duration + 0.1) add('timing', index, start, 'Caption extends beyond the video.');
        if (text && Array.from(text.replace(/\s/g, '')).length / (end - start) > 25) add('reading', index, start, 'Text may be too fast to read (over 25 characters per second).');
      }
      if (!text) add('text', index, Math.max(0, start || 0), 'Empty caption — add text or delete it.');
      else if (/\uFFFD|[\u0000-\u0008\u000B\u000C\u000E-\u001F]|(.)\1{4,}/u.test(text)) add('text', index, Math.max(0, start || 0), 'Possible OCR error: broken characters or repeated symbols.');
    });
    valid.sort((a, b) => a.start - b.start || a.end - b.end);
    let covered = 0, previous = null;
    for (const cue of valid) {
      if (cue.start - covered >= 5) add('gap', cue.index, covered, `${(cue.start - covered).toFixed(1)} seconds without captions — check for missed dialogue.`);
      if (previous && cue.start < covered) add('overlap', cue.index, cue.start, `Overlaps caption #${previous.index + 1}. Adjust the timing.`);
      if (cue.end > covered) { covered = cue.end; previous = cue; }
    }
    if (Number.isFinite(duration) && duration > 0 && duration - covered >= 5) add('gap', null, covered, `${(duration - covered).toFixed(1)} seconds without captions at the end — check for missed dialogue.`);
    return issues.sort((a, b) => a.time - b.time || (a.index ?? -1) - (b.index ?? -1));
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = analyze;
  else root.analyzeSubtitleQuality = analyze;
})(typeof window !== 'undefined' ? window : globalThis);
