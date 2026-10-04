import Cocoa
import Sparkle

let vipUpdateFeed = "https://github.com/reachhwasup/vip_studio/releases/latest/download/appcast.xml"

extension StudioApp: SPUUpdaterDelegate {
    func configureUpdater() {
        updaterController = SPUStandardUpdaterController(startingUpdater: true, updaterDelegate: self, userDriverDelegate: nil)
    }
    @objc func checkForUpdates() {
        // Sparkle owns downloading, signature verification, installation and relaunch.
        updaterController?.checkForUpdates(nil)
    }
    func updater(_ updater: SPUUpdater, shouldPostponeRelaunchForUpdate item: SUAppcastItem, untilInvokingBlock installHandler: @escaping () -> Void) -> Bool {
        pendingUpdateInstall = installHandler
        sendDesktopEvent("vip-native-update", ["message": "Update ready. Waiting for active downloads/subtitle jobs to finish and the subtitle editor to close before restarting.", "available": false])
        waitForSafeUpdate()
        return true
    }
    func waitForSafeUpdate() {
        guard pendingUpdateInstall != nil else { return }
        let script = """
        const response = await fetch('/api/desktop/activity');
        if (!response.ok) return true;
        const activity = await response.json();
        return activity.busy || running || activeWorkers > 0 || !!document.querySelector('#subtitleReviewDialog')?.open;
        """
        web.callAsyncJavaScript(script, arguments: [:], in: nil, in: .page) { result in
            if case .success(let value) = result, let busy = value as? Bool, !busy {
                let install = self.pendingUpdateInstall; self.pendingUpdateInstall = nil; install?()
            } else {
                DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in self?.waitForSafeUpdate() }
            }
        }
    }
}
