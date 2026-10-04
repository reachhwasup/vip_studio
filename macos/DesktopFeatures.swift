import Cocoa
import WebKit
import UserNotifications

extension StudioApp: WKScriptMessageHandler, UNUserNotificationCenterDelegate {
    func sendDesktopEvent(_ name: String, _ detail: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: detail), let json = String(data: data, encoding: .utf8) else { return }
        DispatchQueue.main.async { self.web.evaluateJavaScript("window.dispatchEvent(new CustomEvent('\(name)', {detail: \(json)}))", completionHandler: nil) }
    }
    func desktopSettings() {
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            let state: String
            switch settings.authorizationStatus {
            case .authorized, .provisional: state = "enabled"
            case .denied: state = "blocked"
            default: state = "not enabled"
            }
            self.sendDesktopEvent("vip-native-settings", ["version": Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.2.0", "notifications": state, "updateURL": vipUpdateFeed])
        }
    }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, message.frameInfo.securityOrigin.host == "127.0.0.1", message.frameInfo.securityOrigin.port == 5056,
              let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
        switch type {
        case "settings": desktopSettings()
        case "requestNotifications":
            UNUserNotificationCenter.current().requestAuthorization(options: [.alert,.sound,.badge]) { _, error in
                if let error = error { self.sendDesktopEvent("vip-native-message", ["error": error.localizedDescription]) }
                self.desktopSettings()
            }
        case "notify":
            let title = String((body["title"] as? String ?? "VIP Studio").prefix(160))
            let text = String((body["body"] as? String ?? "").prefix(1000))
            let content = UNMutableNotificationContent(); content.title = title; content.body = text; content.sound = .default
            UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)) { error in
                if let error = error { self.sendDesktopEvent("vip-native-message", ["error": error.localizedDescription]) }
            }
        case "checkUpdates": checkForUpdates()
        case "openReleases": NSWorkspace.shared.open(URL(string: "https://github.com/reachhwasup/vip_studio/releases")!)
        default: break
        }
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification, withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner,.sound])
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse, withCompletionHandler completionHandler: @escaping () -> Void) {
        DispatchQueue.main.async { self.window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true) }; completionHandler()
    }
}
