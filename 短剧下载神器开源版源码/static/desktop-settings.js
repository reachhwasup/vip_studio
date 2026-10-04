(() => {
  const bridge = window.webkit?.messageHandlers?.vipStudio;
  if (!bridge) return;
  const card = document.createElement('section'); card.id = 'desktopSettingsCard'; card.className = 'config';
  card.innerHTML = `<div class="setting-title"><span class="setting-icon">↻</span><div><span class="setting-kicker">Desktop preferences</span><h2>Mac app</h2></div></div><p id="desktopVersion" class="status">Loading app information…</p><div class="desktop-controls"><button id="desktopEnableNotifications" class="btn2">Enable notifications</button><button id="desktopTestNotification" class="btn2">Send test notification</button></div><p id="desktopNotificationStatus" class="status" role="status"></p><h3>App updates</h3><p class="hint">Connected to reachhwasup/vip_studio on GitHub. Updates are verified before installation. You choose when to install and restart.</p><div class="desktop-controls"><button id="desktopCheckUpdates" class="btn2">Check for updates</button><button id="desktopOpenReleases" class="btn2">View releases</button></div><p id="desktopUpdateStatus" class="status" role="status">Ready to check GitHub Releases.</p>`;
  document.querySelector('.settings-stack').append(card);
  const el = id => document.getElementById(id), send = data => bridge.postMessage(data);
  window.addEventListener('vip-native-settings', event => {
    const data = event.detail; el('desktopVersion').textContent = 'VIP Studio ' + data.version + ' · Apple Silicon';
    const text = 'macOS notifications: ' + data.notifications + (data.notifications === 'blocked' ? '. Enable VIP Studio in System Settings → Notifications.' : '.');
    el('desktopNotificationStatus').textContent = text;
    el('desktopTestNotification').disabled = data.notifications !== 'enabled';
    el('notifyStatus').textContent = notifyWanted() ? text : 'Notifications are off in VIP Studio.';
  });
  window.addEventListener('vip-native-update', event => { el('desktopUpdateStatus').textContent = event.detail.message; el('desktopCheckUpdates').disabled = !!event.detail.checking; });
  window.addEventListener('vip-native-message', event => { if (event.detail.error) el('desktopNotificationStatus').textContent = event.detail.error; });
  el('desktopEnableNotifications').onclick = () => { saveSetting('duanju_notify', '1'); const toggle = document.getElementById('notifyToggle'); if (toggle) toggle.checked = true; send({type: 'requestNotifications'}); };
  el('desktopTestNotification').onclick = () => send({type: 'notify', title: 'VIP Studio', body: 'Download and subtitle completion notifications are ready.'});
  el('desktopCheckUpdates').onclick = () => send({type: 'checkUpdates'});
  el('desktopOpenReleases').onclick = () => send({type: 'openReleases'});
  send({type: 'settings'});
})();
