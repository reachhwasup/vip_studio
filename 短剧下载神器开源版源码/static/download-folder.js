/* Preserve pending episodes while the user reconnects or chooses a download folder. */
let downloadFolderRecovery = null, downloadFolderPreflight = null, downloadFolderRecoveryNeeded = false;
async function checkDownloadFolder() {
  if (downloadFolderPreflight) return downloadFolderPreflight;
  downloadFolderPreflight = (async () => {
    try {
      const response = await fetch('/api/download-path?check=1');
      const data = await readFolderResponse(response);
      if (!response.ok) throw new Error(data.error || 'Could not check the download folder.');
      if (data.available !== false) return true;
      await recoverDownloadFolder();
    } catch (error) { toast(error.message, 'error'); }
    return false;
  })();
  try { return await downloadFolderPreflight; }
  finally { downloadFolderPreflight = null; }
}
async function recoverDownloadFolder() {
  if (downloadFolderRecovery) return downloadFolderRecovery;
  running = false; downloadFolderRecoveryNeeded = true;
  renderTasks(); setTab('settings');
  $('downloadPathCard').scrollIntoView({block: 'center'});
  $('downloadPathStatus').textContent = 'Downloads paused. Select an available download folder to continue.';
  downloadFolderRecovery = (async () => {
    try {
      const response = await fetch('/api/download-path/browse', {method: 'POST'});
      const data = await readFolderResponse(response);
      if (!response.ok) throw new Error(data.error || 'Select a folder with Browse or enter its path.');
      if (data.cancelled) {
        $('downloadPathStatus').textContent = 'Folder selection cancelled. Your episodes remain queued. Select and save a folder when ready.';
        return false;
      }
      $('downloadPath').value = data.download_path;
      const saved = await fetch('/api/download-path', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({download_path: data.download_path})});
      const result = await readFolderResponse(saved);
      if (!saved.ok) throw new Error(result.error || 'Could not save the download folder.');
      showDownloadPath(result.download_path);
      downloadFolderRecoveryNeeded = false;
      toast('Download folder saved. Resuming your queue.', 'success');
      setTimeout(() => startQueue(), 0);
      return true;
    } catch (error) {
      $('downloadPathStatus').textContent = error.message + ' Select a folder using Browse or enter its path, then Save folder.';
      return false;
    }
  })();
  try { return await downloadFolderRecovery; }
  finally { downloadFolderRecovery = null; }
}
