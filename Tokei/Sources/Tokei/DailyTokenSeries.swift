import Foundation

struct DailyTokenDay: Identifiable {
    var date: Date
    var key: String
    var tokens: Int
    var id: String { key }
}

enum DailyTokenSeries {
    /// 按日历补齐零用量的日期,不把账本中缺少的天压缩掉,也不纳入未来日期。
    static func make(
        totals: [String: Int], days: Int, now: Date = Date(), calendar: Calendar = .current
    ) -> [DailyTokenDay] {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        let today = calendar.startOfDay(for: now)
        return (0..<max(days, 0)).reversed().compactMap { offset in
            guard let date = calendar.date(byAdding: .day, value: -offset, to: today) else { return nil }
            let key = formatter.string(from: date)
            return DailyTokenDay(date: date, key: key, tokens: totals[key] ?? 0)
        }
    }
}
