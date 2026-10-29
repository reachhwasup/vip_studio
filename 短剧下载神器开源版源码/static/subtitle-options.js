/* Shared choices for Library, automatic downloads and queue labels. */
window.vipSubtitleOptions = (() => {
  const labels = {
    recommended: 'Smart subtitles', picture: 'Video text only', speech: 'Audio only',
    hybrid: 'Video text + Paraformer', auto: 'Video text + Whisper',
    funasr: 'Paraformer audio only', audio: 'Whisper audio only',
  };
  const hints = {
    recommended: 'Reads visible captions and checks one speech engine automatically: Paraformer for Chinese when installed, otherwise Whisper. Keeps caption breaks and flags disagreements. Review speaker turns before dubbing.',
    picture: 'Reads only the captions visible in the video. No audio check; dialogue without visible text may be missed.',
    speech: 'Listens to audio only. Automatically uses Paraformer for Chinese when installed, otherwise Whisper. Review wording and speaker turns before dubbing.',
    hybrid: 'Saved manual override: reads video text and checks Chinese speech with Paraformer. Choose Smart subtitles for automatic engine selection.',
    auto: 'Saved manual override: reads video text and checks Whisper speech. Choose Smart subtitles for automatic engine selection.',
    funasr: 'Saved manual override: transcribes Chinese speech with Paraformer. Choose Audio only for automatic engine selection.',
    audio: 'Saved manual override: transcribes speech with Whisper. Choose Audio only for automatic engine selection.',
  };
  function restore(control, mode) {
    // Retain a saved override without presenting duplicate choices to new users.
    control.querySelectorAll('[data-saved-override]').forEach(option => option.remove());
    if (!['recommended', 'picture', 'speech'].includes(mode) && labels[mode]) {
      const option = document.createElement('option');
      option.value = mode;
      option.textContent = 'Saved override · ' + labels[mode];
      option.dataset.savedOverride = 'true';
      control.append(option);
    }
    control.value = labels[mode] ? mode : 'recommended';
  }
  function describe(mode, language) {
    const chinese = ['hybrid', 'funasr'].includes(mode), picture = mode === 'picture';
    if (chinese) language.value = 'zh';
    language.disabled = chinese || picture;
    return { hint: hints[mode] || hints.recommended, languageHint: chinese ? 'Chinese audio is required for this saved override.' : picture ? 'Audio is not used in this mode.' : 'Language spoken in this episode.' };
  }
  return { labels, restore, describe };
})();
