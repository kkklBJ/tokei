import Charts
import SwiftUI

struct DailyTokenHistoryView: View {
    @ObservedObject var store: Store
    @ObservedObject private var repository = DashboardRepository.shared
    @AppStorage("dailyTokenHistoryDays") private var days = 30
    @State private var hover: DailyTokenDay?
    @State private var showDailyList = false

    private var points: [DailyTokenDay] {
        var totals: [String: Int] = [:]
        let local = repository.payload(for: .all)?.daily ?? []
        let peers = store.syncEnabled && store.showAllDevices
            ? store.peers.flatMap { $0.dashboard?.daily ?? [] } : []
        for day in local + peers {
            totals[day.date, default: 0] += day.tokens
        }
        return DailyTokenSeries.make(totals: totals, days: days)
    }

    var body: some View {
        let points = self.points
        let total = points.reduce(0) { $0 + $1.tokens }
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("每日 token 消耗")
                    .font(.system(size: Theme.fontSize(14), weight: .bold))
                Spacer()
                Picker("时间范围", selection: $days) {
                    Text("近 7 天").tag(7)
                    Text("近 30 天").tag(30)
                    Text("近一年").tag(365)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(width: 216)
                .controlSize(.mini)
            }
            Card(tint: Theme.codex) {
                VStack(alignment: .leading, spacing: 12) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(Fmt.human(total) + " tokens")
                            .font(.system(size: Theme.fontSize(22), weight: .bold, design: .rounded))
                        Text("日均 " + Fmt.human(total / max(points.count, 1)))
                            .font(.system(size: Theme.fontSize(10)))
                            .foregroundStyle(Theme.tTertiary)
                        Spacer()
                        if let hover {
                            Text(hover.key + " · " + Fmt.human(hover.tokens))
                                .font(.system(size: Theme.fontSize(10), design: .monospaced))
                                .foregroundStyle(Theme.codex)
                        }
                    }
                    if repository.payload(for: .all) == nil {
                        Text("每日用量读取中；暂不可用时会随下一次用量刷新重试。")
                            .font(.system(size: Theme.fontSize(10)))
                            .foregroundStyle(Theme.tTertiary)
                            .frame(maxWidth: .infinity, minHeight: 180)
                    } else {
                        tokenChart(points)
                        DisclosureGroup("逐日明细", isExpanded: $showDailyList) {
                            ScrollView {
                                LazyVStack(spacing: 6) {
                                    ForEach(points.reversed()) { point in
                                        HStack {
                                            Text(point.key)
                                            Spacer()
                                            Text(Fmt.grouped(point.tokens) + " tokens")
                                        }
                                    }
                                }
                                .font(.system(size: Theme.fontSize(10), design: .monospaced))
                                .padding(.top, 6)
                            }
                            .frame(height: CGFloat(min(points.count, 8)) * 22)
                        }
                        .font(.system(size: Theme.fontSize(10)))
                        .foregroundStyle(Theme.tSecondary)
                    }
                }
            }
        }
        .onAppear { repository.load(.all) }
        .onReceive(store.$usage.dropFirst()) { _ in repository.load(.all, force: true) }
        .onChange(of: days) { _ in hover = nil }
    }

    private func tokenChart(_ points: [DailyTokenDay]) -> some View {
        Chart(points) { point in
            BarMark(x: .value("日期", point.date, unit: .day), y: .value("Token", point.tokens))
                .foregroundStyle(Theme.codex.gradient)
            if hover?.key == point.key {
                RuleMark(x: .value("日期", point.date, unit: .day))
                    .foregroundStyle(Theme.tTertiary)
            }
        }
        .chartXAxis {
            AxisMarks(values: .stride(by: .day, count: max(days / 6, 1))) { _ in
                AxisValueLabel(format: .dateTime.month(.twoDigits).day(.twoDigits))
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading) { value in
                AxisGridLine().foregroundStyle(Color.white.opacity(0.08))
                AxisValueLabel {
                    if let tokens = value.as(Int.self) { Text(Fmt.human(tokens)) }
                }
            }
        }
        .frame(height: 180)
        .chartOverlay { proxy in
            GeometryReader { geometry in
                let plot = geometry[proxy.plotAreaFrame]
                Rectangle().fill(.clear).contentShape(Rectangle())
                    .onContinuousHover { phase in
                        switch phase {
                        case .active(let location):
                            guard plot.contains(location),
                                  let date: Date = proxy.value(atX: location.x - plot.minX)
                            else { hover = nil; return }
                            hover = points.first { Calendar.current.isDate($0.date, inSameDayAs: date) }
                        case .ended: hover = nil
                        }
                    }
            }
        }
    }
}
