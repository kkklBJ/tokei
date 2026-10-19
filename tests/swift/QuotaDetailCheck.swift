import Foundation

// Run the real repository without scanning user data or contacting providers.
enum DataLoader {
    struct ScriptResult {
        var stdout: String
        var exitCode: Int32 = 0
        var timedOut = false
    }

    private static let lock = NSLock()
    private static var calls = 0
    static var callCount: Int {
        lock.lock()
        defer { lock.unlock() }
        return calls
    }

    static func runScriptRaw(args: [String], timeout: TimeInterval) -> ScriptResult {
        precondition(args == ["--quota-detail"] && timeout == 30)
        lock.lock()
        calls += 1
        let call = calls
        lock.unlock()
        if call == 3 { return ScriptResult(stdout: "", exitCode: 1) }
        let cycle = QuotaCycle(
            tool: "codex", start: 1792292415, end: 1792897215,
            used_pct: call == 1 ? 2 : 9, tokens: 321_798_091,
            devices: ["local": 321_798_091], approx: false, current: true
        )
        let payload = QuotaDetailPayload(
            daily: [], cycles: [cycle], devices: ["local"], missing: [], now: call
        )
        return ScriptResult(stdout: String(data: try! JSONEncoder().encode(payload), encoding: .utf8)!)
    }
}

@main
struct QuotaDetailCheck {
    static func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
        if !condition() { throw NSError(domain: message, code: 1) }
    }

    static func finish(_ repository: QuotaDetailRepository) throws {
        let deadline = Date().addingTimeInterval(3)
        while repository.refreshing && Date() < deadline {
            RunLoop.main.run(until: Date().addingTimeInterval(0.01))
        }
        try expect(!repository.refreshing, "detail refresh must finish")
    }

    static func main() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("quota_detail.json")
        let repository = QuotaDetailRepository(fileURL: url)

        repository.load()
        try finish(repository)
        try expect(repository.payload?.cycles.first?.projectedTotal == nil, "2% hides projection")
        repository.load()
        try expect(DataLoader.callCount == 1, "fresh detail must not rescan")

        repository.load(force: true)
        repository.load(force: true)
        try finish(repository)
        try expect(DataLoader.callCount == 2, "overlapping refreshes must share one scan")
        try expect(repository.payload?.cycles.first?.used_pct == 9, "refresh must publish latest quota")
        try expect(repository.payload?.cycles.first?.projectedTotal == 3_575_534_344,
                   "9% must reveal the updated token projection")
        let cached = QuotaDetailRepository(fileURL: url)
        try expect(cached.payload?.cycles.first?.used_pct == 9, "updated detail must persist")

        repository.load(force: true)
        try finish(repository)
        try expect(repository.payload?.cycles.first?.used_pct == 9, "failed refresh must preserve last good detail")
        print("quota detail checks passed")
    }
}
