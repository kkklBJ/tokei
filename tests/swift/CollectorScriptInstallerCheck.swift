import Foundation

private enum CheckError: Error, CustomStringConvertible {
    case failed(String)

    var description: String {
        switch self {
        case .failed(let message): return message
        }
    }
}

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw CheckError.failed(message) }
}

@main
struct CollectorScriptInstallerCheck {
    static func main() throws {
        let fileManager = FileManager.default
        let root = fileManager.temporaryDirectory
            .appendingPathComponent("tokei-collector-installer-\(UUID().uuidString)")
        let resources = root.appendingPathComponent("resources")
        let userDir = root.appendingPathComponent("user")
        try fileManager.createDirectory(at: resources, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: userDir, withIntermediateDirectories: true)
        defer { try? fileManager.removeItem(at: root) }

        let bundledScript = "# TOKEI_COLLECTOR_REVISION=1\nprint('new parser')\n"
        let legacyScript = "print('legacy parser')\n"
        try bundledScript.write(
            to: resources.appendingPathComponent("usage.30s.py"),
            atomically: true,
            encoding: .utf8
        )
        try legacyScript.write(
            to: userDir.appendingPathComponent("usage.30s.py"),
            atomically: true,
            encoding: .utf8
        )
        try "v1.0.213".write(
            to: userDir.appendingPathComponent("script.version"),
            atomically: true,
            encoding: .utf8
        )

        CollectorScriptInstaller.sync(
            resourceDir: resources.path,
            userDir: userDir,
            bundledRelease: "v1.0.38"
        )

        let installed = try String(
            contentsOf: userDir.appendingPathComponent("usage.30s.py"),
            encoding: .utf8
        )
        let recorded = try String(
            contentsOf: userDir.appendingPathComponent("script.version"),
            encoding: .utf8
        )
        try expect(installed == bundledScript,
                   "legacy collector with a high app version must be replaced")
        try expect(recorded == "v1.0.38",
                   "script.version must follow the installed bundled collector")

        let newerDir = root.appendingPathComponent("newer-user")
        try fileManager.createDirectory(at: newerDir, withIntermediateDirectories: true)
        let newerScript = "# TOKEI_COLLECTOR_REVISION=2\nprint('future parser')\n"
        try newerScript.write(
            to: newerDir.appendingPathComponent("usage.30s.py"),
            atomically: true,
            encoding: .utf8
        )
        try "v1.0.39".write(
            to: newerDir.appendingPathComponent("script.version"),
            atomically: true,
            encoding: .utf8
        )
        CollectorScriptInstaller.sync(
            resourceDir: resources.path,
            userDir: newerDir,
            bundledRelease: "v1.0.38"
        )
        let preserved = try String(
            contentsOf: newerDir.appendingPathComponent("usage.30s.py"),
            encoding: .utf8
        )
        try expect(preserved == newerScript,
                   "a collector with a newer revision must not be downgraded")
        print("Collector script installer checks passed")
    }
}
