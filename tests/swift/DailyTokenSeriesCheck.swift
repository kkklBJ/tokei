import Foundation
import SwiftUI

@main
struct DailyTokenSeriesCheck {
    static func main() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "America/Los_Angeles")!
        let now = ISO8601DateFormatter().date(from: "2026-03-09T12:00:00-07:00")!
        let points = DailyTokenSeries.make(totals: [
            "2026-03-06": 999, "2026-03-07": 3_000_000_000,
            "2026-03-09": 40, "2026-03-10": 999,
        ], days: 3, now: now, calendar: calendar)
        try expect(points.map(\.key) == ["2026-03-07", "2026-03-08", "2026-03-09"], "calendar days must survive DST")
        try expect(points.map(\.tokens) == [3_000_000_000, 0, 40], "missing days must be zero; past/future days excluded")
        try expect(DailyTokenSeries.make(totals: [:], days: 365, now: now, calendar: calendar).count == 365, "year range must include every day")
        try expect(DailyTokenSeries.make(totals: [:], days: 0).isEmpty, "empty range must not crash")

        let suite = "tokei-quota-preference-" + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let first = AppStorage(wrappedValue: QuotaHistoryTool.claude, "quotaHistoryTool", store: defaults)
        first.wrappedValue = .codex
        let reopened = AppStorage(wrappedValue: QuotaHistoryTool.claude, "quotaHistoryTool", store: defaults)
        try expect(reopened.wrappedValue == .codex, "reopening must remember Codex")
        reopened.wrappedValue = .claude
        let reopenedAgain = AppStorage(wrappedValue: QuotaHistoryTool.codex, "quotaHistoryTool", store: defaults)
        try expect(reopenedAgain.wrappedValue == .claude, "later selection must remember Claude")
        print("daily token series checks passed")
    }

    static func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
        if !condition() { throw NSError(domain: message, code: 1) }
    }
}
