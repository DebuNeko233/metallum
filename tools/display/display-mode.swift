// Read and restore the display's mode, so a session that changes it can be put back.
//
// Why this exists: a fullscreen client asks the window server for a video mode, and the window server changes the
// display's mode to match. A client that exits cleanly restores it; one that is killed, crashes or is left
// half-started does not, and the display stays on the mode the game asked for. That is machine state this project
// has already recorded moving under a measurement (a crash moved it from 1920x1200 to 3200x1800 and every later
// run was on another target), and it is also the owner's screen: a launch must not leave it somewhere else.
//
// Usage:
//   display-mode read                 -> one line: "WxH@R id=<modeID> pixelWxH"
//   display-mode set WxH              -> set the mode whose width and height are WxH (nearest refresh)
//   display-mode save FILE            -> write the current mode's id and size to FILE
//   display-mode check FILE           -> exit 0 if the display is still the mode saved in FILE
//   display-mode restore FILE         -> set the mode saved in FILE
import CoreGraphics
import Foundation

func describe(_ mode: CGDisplayMode) -> String {
    let refresh = mode.refreshRate == 0 ? 0 : Int(mode.refreshRate.rounded())
    return "\(mode.width)x\(mode.height)@\(refresh) id=\(mode.ioDisplayModeID) pixels=\(mode.pixelWidth)x\(mode.pixelHeight)"
}

func currentMode() -> CGDisplayMode? {
    CGDisplayCopyDisplayMode(CGMainDisplayID())
}

func allModes() -> [CGDisplayMode] {
    (CGDisplayCopyAllDisplayModes(CGMainDisplayID(), nil) as? [CGDisplayMode]) ?? []
}

func setMode(_ mode: CGDisplayMode) -> Bool {
    var config: CGDisplayConfigRef?
    guard CGBeginDisplayConfiguration(&config) == .success, let config else { return false }
    let configured = CGConfigureDisplayWithDisplayMode(config, CGMainDisplayID(), mode, nil)
    guard configured == .success else {
        CGCancelDisplayConfiguration(config)
        return false
    }
    return CGCompleteDisplayConfiguration(config, .forSession) == .success
}

let arguments = CommandLine.arguments
let command = arguments.count > 1 ? arguments[1] : "read"
switch command {
case "read":
    guard let mode = currentMode() else { exit(2) }
    print(describe(mode))
case "save":
    guard arguments.count > 2, let mode = currentMode() else { exit(2) }
    try? "\(mode.ioDisplayModeID) \(mode.width) \(mode.height)\n"
        .write(toFile: arguments[2], atomically: true, encoding: .utf8)
    print(describe(mode))
case "restore":
    guard arguments.count > 2,
          let text = try? String(contentsOfFile: arguments[2], encoding: .utf8) else { exit(2) }
    let fields = text.split(separator: " ")
    guard fields.count >= 3, let wanted = Int(fields[0]) else { exit(2) }
    guard let mode = allModes().first(where: { $0.ioDisplayModeID == wanted }) else {
        FileHandle.standardError.write("no mode with id \(wanted) is available now\n".data(using: .utf8)!)
        exit(3)
    }
    let before = currentMode().map(describe) ?? "unknown"
    let ok = setMode(mode)
    let after = currentMode().map(describe) ?? "unknown"
    print("\(ok ? "restored" : "could not restore") \(before) -> \(after)")
    exit(ok ? 0 : 1)
case "check":
    // Exit 0 when the display is where the file says it was, and non-zero when it moved, so a caller can
    // avoid touching a display that needs nothing done to it.
    guard arguments.count > 2,
          let text = try? String(contentsOfFile: arguments[2], encoding: .utf8) else { exit(2) }
    let fields = text.split(separator: " ")
    guard fields.count >= 3, let wanted = Int(fields[0]), let mode = currentMode() else { exit(2) }
    if mode.ioDisplayModeID == wanted {
        print("unchanged \(describe(mode))")
        exit(0)
    }
    print("moved to \(describe(mode)) from id \(wanted) \(fields[1])x\(fields[2])")
    exit(1)
case "set":
    guard arguments.count > 2 else { exit(2) }
    let parts = arguments[2].lowercased().split(separator: "x")
    guard parts.count == 2, let width = Int(parts[0]), let height = Int(parts[1]) else { exit(2) }
    guard let mode = allModes().first(where: { $0.width == width && $0.height == height }) else {
        FileHandle.standardError.write("no \(width)x\(height) mode is available\n".data(using: .utf8)!)
        exit(3)
    }
    let before = currentMode().map(describe) ?? "unknown"
    let ok = setMode(mode)
    let after = currentMode().map(describe) ?? "unknown"
    print("\(ok ? "set" : "could not set") \(before) -> \(after)")
    exit(ok ? 0 : 1)
default:
    FileHandle.standardError.write("usage: display-mode read|save FILE|restore FILE|set WxH\n".data(using: .utf8)!)
    exit(2)
}
