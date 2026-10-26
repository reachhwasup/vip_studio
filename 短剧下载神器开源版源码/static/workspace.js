/* Native update notice and queue menu interactions. */
(() => {
  const el = id => document.getElementById(id);
  el('updateViewActivity').onclick = () => { setTab('downloads'); setDownloadView('queue'); };
  window.addEventListener('vip-native-update', event => {
    if (!event.detail?.postponed) return;
    el('updateNotice').hidden = false;
    el('updateNoticeMessage').textContent = event.detail.message;
  });
  document.addEventListener('click', event => {
    const more = document.querySelector('.queue-more');
    if (more && (!more.contains(event.target) || event.target.closest('button'))) more.open = false;
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      const more = document.querySelector('.queue-more[open]');
      if (more) { more.open = false; more.querySelector('summary').focus(); }
    }
  });
})();
