import Cocoa
import WebKit
import UserNotifications
import Sparkle

final class StudioApp: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var backend: Process?
    var ready: URL!
    var timer: Timer?
    var started = Date()
    var stopping = false
    var readyLoaded = false
    var updaterController: SPUStandardUpdaterController?
    var pendingUpdateInstall: (() -> Void)?

    func applicationDidFinishLaunching(_ notification: Notification) {
        UNUserNotificationCenter.current().delegate = self
        configureUpdater()
        let main = NSMenu()
        let appMenu = NSMenu()
        let appItem = NSMenuItem(); main.addItem(appItem); appItem.submenu = appMenu
        appMenu.addItem(withTitle: "About VIP Studio", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(withTitle: "Check for Updates…", action: #selector(checkForUpdates), keyEquivalent: "").target = self
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit VIP Studio", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let editItem = NSMenuItem(); main.addItem(editItem); let edit = NSMenu(title: "Edit"); editItem.submenu = edit
        for (title, selector, key) in [("Undo", "undo:", "z"), ("Cut", "cut:", "x"), ("Copy", "copy:", "c"), ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key)
        }
        let viewItem = NSMenuItem(); main.addItem(viewItem); let view = NSMenu(title: "View"); viewItem.submenu = view
        view.addItem(withTitle: "Reload", action: #selector(reload), keyEquivalent: "r").target = self
        NSApp.mainMenu = main
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 860), styleMask: [.titled,.closable,.miniaturizable,.resizable], backing: .buffered, defer: false)
        window.title = "VIP Studio"; window.minSize = NSSize(width: 760, height: 560); window.delegate = self
        window.isReleasedWhenClosed = false
        window.appearance = NSAppearance(named: .darkAqua)
        window.setFrameAutosaveName("VIPStudioWindow")
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(self, name: "vipStudio")
        configuration.websiteDataStore = .default()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true
        web = WKWebView(frame: window.contentView!.bounds, configuration: configuration)
        web.autoresizingMask = [.width,.height]; web.navigationDelegate = self; web.uiDelegate = self
        window.contentView = web; window.center(); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        web.loadHTMLString("<body style='background:#0c111b;color:#edf2fa;font:20px -apple-system;display:grid;place-content:center;height:90vh'><h1>VIP Studio</h1><p>Opening your workspace…</p></body>", baseURL: nil)
        do {
            let data = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/VIP Studio", isDirectory: true)
            try FileManager.default.createDirectory(at: data, withIntermediateDirectories: true)
            ready = data.appendingPathComponent(".ready-\(UUID().uuidString)")
            let logs = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/VIP Studio", isDirectory: true)
            try FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
            let log = logs.appendingPathComponent("backend.log")
            if !FileManager.default.fileExists(atPath: log.path) { FileManager.default.createFile(atPath: log.path, contents: nil) }
            let handle = try FileHandle(forWritingTo: log); handle.seekToEndOfFile()
            let process = Process()
            process.executableURL = Bundle.main.resourceURL!.appendingPathComponent("backend/VIPStudioBackend")
            process.currentDirectoryURL = data
            var environment = ProcessInfo.processInfo.environment
            environment["VIP_STUDIO_DATA_DIR"] = data.path
            environment["VIP_STUDIO_READY_FILE"] = ready.path
            process.environment = environment; process.standardOutput = handle; process.standardError = handle
            process.terminationHandler = { [weak self] process in DispatchQueue.main.async {
                guard let self = self, !self.stopping else { return }
                self.fail("The local service stopped (code \(process.terminationStatus)). See ~/Library/Logs/VIP Studio/backend.log. If port 5056 is in use, close its application and reopen VIP Studio.")
            }}
            backend = process; try process.run()
            timer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in self?.checkReady() }
        } catch { fail(error.localizedDescription) }
    }
    func checkReady() {
        if let text = try? String(contentsOf: ready, encoding: .utf8), let url = URL(string: text) {
            timer?.invalidate(); try? FileManager.default.removeItem(at: ready); readyLoaded = true; web.load(URLRequest(url: url))
        } else if Date().timeIntervalSince(started) > 60 { fail("The local service took too long to start. See ~/Library/Logs/VIP Studio/backend.log.") }
    }
    func fail(_ message: String) {
        guard !stopping else { return }; timer?.invalidate()
        let alert = NSAlert(); alert.messageText = "VIP Studio could not start"; alert.informativeText = message; alert.runModal(); NSApp.terminate(nil)
    }
    // Optional local smoke report for testing the real WKWebView, not a browser substitute.
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard readyLoaded, let destination = ProcessInfo.processInfo.environment["VIP_STUDIO_SMOKE_DIR"] else { return }
        let script = """
        const response = await fetch('/api/library');
        const library = await response.json();
        const subtitles = await (await fetch('/api/subtitles')).json();
        document.querySelector('[data-tab=library]').click();
        await new Promise(resolve => setTimeout(resolve, 1200));
        const sample = library.items.flatMap(item => item.episodes).find(episode => episode.subtitle_url);
        let editorCaptions = 0;
        if (sample) {
          openSubtitleReview(sample.url, sample.title);
          await new Promise(resolve => setTimeout(resolve, 800));
          editorCaptions = document.querySelectorAll('.review-cue').length;
          document.getElementById('reviewClose').click();
        }
        setTab('settings');
        window.webkit.messageHandlers.vipStudio.postMessage({type:'settings'});
        await new Promise(resolve => setTimeout(resolve, 600));
        return {editorCaptions, nativeVersion: document.getElementById('desktopVersion')?.textContent,
          updateStatus: document.getElementById('desktopUpdateStatus')?.textContent,
          notificationStatus: document.getElementById('desktopNotificationStatus')?.textContent,
          title: document.title, tabs: document.querySelectorAll('.tab').length,
          libraryOK: response.ok, dramas: library.items.length,
          libraryVisible: document.querySelector('#library').classList.contains('active'),
          subtitleAvailable: subtitles.available, width: innerWidth, scrollWidth: document.documentElement.scrollWidth};
        """
        webView.callAsyncJavaScript(script, arguments: [:], in: nil, in: .page) { result in
            let folder = URL(fileURLWithPath: destination)
            try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            switch result {
            case .success(let value):
                if let data = try? JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted]) { try? data.write(to: folder.appendingPathComponent("report.json")) }
            case .failure(let error):
                try? error.localizedDescription.write(to: folder.appendingPathComponent("error.txt"), atomically: true, encoding: .utf8)
            }
            webView.takeSnapshot(with: nil) { image, _ in
                if let tiff = image?.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff), let png = bitmap.representation(using: .png, properties: [:]) { try? png.write(to: folder.appendingPathComponent("window.png")) }
            }
        }
    }
    @objc func reload() { web.reload() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) {
        stopping = true; timer?.invalidate()
        if let process = backend, process.isRunning {
            let pid = process.processIdentifier
            if getpgid(pid) == pid { kill(-pid, SIGTERM) } else { process.terminate() }
        }
        if let ready = ready { try? FileManager.default.removeItem(at: ready) }
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        let local = url.host == "127.0.0.1" && url.port == 5056
        if navigationAction.shouldPerformDownload { decisionHandler(.download); return }
        if local || url.scheme == "about" || url.scheme == "blob" { decisionHandler(.allow) }
        else { if ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }; decisionHandler(.cancel) }
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url { NSWorkspace.shared.open(url) }; return nil
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert(); alert.messageText = "VIP Studio"; alert.informativeText = message
        alert.addButton(withTitle: "Continue"); alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: window) { response in completionHandler(response == .alertFirstButtonReturn) }
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert(); alert.messageText = "VIP Studio"; alert.informativeText = message
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.beginSheetModal(for: window) { response in completionHandler(response == .OK ? panel.urls : nil) }
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }
}
extension StudioApp: WKDownloadDelegate {
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel(); panel.nameFieldStringValue = suggestedFilename
        panel.beginSheetModal(for: window) { response in completionHandler(response == .OK ? panel.url : nil) }
    }
}
@main
struct VIPStudioMain {
    static func main() {
        let application = NSApplication.shared
        let delegate = StudioApp()
        application.setActivationPolicy(.regular)
        application.delegate = delegate
        withExtendedLifetime(delegate) { application.run() }
    }
}
