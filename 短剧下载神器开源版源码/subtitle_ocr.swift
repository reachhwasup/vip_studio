// Reads text from a folder of video frames with the macOS Vision framework.
// Used by subtitles.py to recover the subtitles drawn into a video's picture.
//
// Usage: subtitle_ocr <folder of .jpg frames>
// Prints one JSON object per frame, in file-name order:
//   {"file": "000012.jpg", "lines": [{"text": "...", "conf": 0.98, "x": 0.31, "y": 0.42, "w": 0.38, "h": 0.09}]}
// x/y are the top-left corner and w/h the size of the text box, as fractions of the frame.

import Foundation
import ImageIO
import Vision

guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write("usage: subtitle_ocr <folder of .jpg frames>\n".data(using: .utf8)!)
    exit(2)
}

let folder = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let files = ((try? FileManager.default.contentsOfDirectory(atPath: folder.path)) ?? [])
    .filter { $0.hasSuffix(".jpg") }
    .sorted()

func recognise(_ name: String) -> [[String: Any]] {
    let url = folder.appendingPathComponent(name)
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { return [] }

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = true

    do {
        try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
    } catch {
        return []
    }

    var lines: [[String: Any]] = []
    for observation in request.results ?? [] {
        guard let best = observation.topCandidates(1).first else { continue }
        let box = observation.boundingBox  // origin is bottom-left in Vision
        lines.append([
            "text": best.string,
            "conf": Double(best.confidence),
            "x": Double(box.minX),
            "y": Double(1 - box.maxY),
            "w": Double(box.width),
            "h": Double(box.height),
        ])
    }
    return lines
}

var results = [[[String: Any]]](repeating: [], count: files.count)
let lock = NSLock()
var completed = 0
func reportProgress(_ count: Int) {
    let message = "VIP_OCR_PROGRESS \(count)/\(files.count)\n"
    FileHandle.standardError.write(Data(message.utf8))
}
reportProgress(0)
let workers = max(1, min(4, Int(ProcessInfo.processInfo.environment["VIP_SUBTITLE_THREADS"] ?? "2") ?? 2))
DispatchQueue.concurrentPerform(iterations: min(workers, files.count)) { worker in
  for index in stride(from: worker, to: files.count, by: workers) {
    let lines = recognise(files[index])
    lock.lock()
    results[index] = lines
    completed += 1
    if completed == files.count || completed % max(1, files.count / 100) == 0 {
        reportProgress(completed)
    }
    lock.unlock()
  }
}

for (index, name) in files.enumerated() {
    let record: [String: Any] = ["file": name, "lines": results[index]]
    if let data = try? JSONSerialization.data(withJSONObject: record, options: []),
       let text = String(data: data, encoding: .utf8) {
        print(text)
    }
}
