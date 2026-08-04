import Charts
import SwiftUI

private extension QuotaHistoryTool {
    var tint: Color { self == .claude ? Theme.claude : Theme.codex }
}

private enum QuotaHistorySpan: Int, CaseIterable, Identifiable {
    case hour = 1
    case sixHours = 6
    case day = 24

    var id: Int { rawValue }
    var label: String {
        switch self {
        case .hour: return "1h"
        case .sixHours: return "6h"
        case .day: return "24h"
        }
    }
    var axisStride: Int {
        switch self {
        case .hour: return 1
        case .sixHours: return 2
        case .day: return 6
        }
    }
}

private struct QuotaHistoryFrame {
    var now: Date
    var start: Date
    var projection: QuotaHistoryProjection
}

struct QuotaHistoryView: View {
    @ObservedObject var history: QuotaHistoryStore
    @State private var tool: QuotaHistoryTool = .claude
    @State private var span: QuotaHistorySpan = .day

    var body: some View {
        let frame = makeFrame()
        return VStack(alignment: .leading, spacing: 13) {
            controls
            Card(tint: tool.tint) {
                VStack(alignment: .leading, spacing: 12) {
                    summary(frame.projection)
                    if frame.projection.lineData.isEmpty {
                        emptyState
                    } else {
                        quotaChart(frame)
                    }
                }
            }
            changesSection(frame.projection)
            activitySection(frame.projection)
            Text("额度曲线来自本机定时快照；模型标记来自同一分钟内本地会话 token 增量，仅表示相关活动，不等同于官方逐模型扣费归因。")
                .font(.system(size: Theme.fontSize(9.5)))
                .foregroundStyle(Theme.tTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var controls: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text("额度轨迹")
                    .font(.system(size: Theme.fontSize(14), weight: .bold))
                    .foregroundStyle(Theme.tPrimary)
                Text("按分钟聚合 · 剩余额度")
                    .font(.system(size: Theme.fontSize(9.5)))
                    .foregroundStyle(Theme.tTertiary)
            }
            Spacer()
            Picker("", selection: $tool) {
                ForEach(QuotaHistoryTool.allCases) { tool in
                    Text(tool.rawValue).tag(tool)
                }
            }
            .pickerStyle(.segmented)
            .frame(width: 145)
            .controlSize(.mini)
            Picker("", selection: $span) {
                ForEach(QuotaHistorySpan.allCases) { span in
                    Text(span.label).tag(span)
                }
            }
            .pickerStyle(.segmented)
            .frame(width: 138)
            .controlSize(.mini)
        }
    }

    private func summary(_ projection: QuotaHistoryProjection) -> some View {
        HStack(spacing: 13) {
            ForEach(projection.windowNames, id: \.self) { window in
                quotaSummary(
                    title: summaryTitle(for: window),
                    value: projection.latestValues[window],
                    tint: seriesColor(for: window)
                )
            }
            VStack(alignment: .leading, spacing: 3) {
                Text("采样点")
                    .font(.system(size: Theme.fontSize(9.5)))
                    .foregroundStyle(Theme.tTertiary)
                Text("\(projection.points.count)")
                    .font(.system(size: Theme.fontSize(15), weight: .bold, design: .rounded))
                    .foregroundStyle(Theme.tPrimary)
            }
            Spacer()
            if let largest = projection.dropEvents.max(by: { $0.drop < $1.drop }) {
                VStack(alignment: .trailing, spacing: 3) {
                    Text("最大区间下降")
                        .font(.system(size: Theme.fontSize(9.5)))
                        .foregroundStyle(Theme.tTertiary)
                    Text(String(format: "-%.1f%% / %dmin", largest.drop, largest.durationMinutes))
                        .font(.system(size: Theme.fontSize(12), weight: .semibold, design: .monospaced))
                        .foregroundStyle(seriesColor(for: largest.window))
                }
            }
        }
    }

    private func quotaSummary(title: String, value: Double?, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.system(size: Theme.fontSize(9.5)))
                .foregroundStyle(Theme.tTertiary)
            Text(value.map { String(format: "%.1f%%", $0) } ?? "—")
                .font(.system(size: Theme.fontSize(15), weight: .bold, design: .rounded))
                .foregroundStyle(value.map { $0 <= 15 ? Color.red : tint } ?? Theme.tTertiary)
        }
    }

    private func quotaChart(_ frame: QuotaHistoryFrame) -> some View {
        QuotaHistoryChart(
            projection: frame.projection,
            start: frame.start,
            end: frame.now,
            span: span,
            colors: Dictionary(
                uniqueKeysWithValues: frame.projection.windowNames.map {
                    ($0, seriesColor(for: $0))
                }
            )
        )
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "chart.xyaxis.line")
                .font(.system(size: Theme.fontSize(24)))
                .foregroundStyle(tool.tint.opacity(0.8))
            Text("正在开始记录额度轨迹")
                .font(.system(size: Theme.fontSize(12), weight: .semibold))
                .foregroundStyle(Theme.tSecondary)
            Text("Tokei 每 30 秒刷新，曲线按分钟聚合。保持应用运行后，这里会逐步出现数据。")
                .font(.system(size: Theme.fontSize(10)))
                .foregroundStyle(Theme.tTertiary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .frame(height: 210)
    }

    private func changesSection(_ projection: QuotaHistoryProjection) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("最近额度变化")
                .font(.system(size: Theme.fontSize(12), weight: .bold))
                .foregroundStyle(Theme.tPrimary)
            if projection.dropEvents.isEmpty {
                Text("当前时间范围内还没有检测到额度下降")
                    .font(.system(size: Theme.fontSize(10)))
                    .foregroundStyle(Theme.tTertiary)
            } else {
                ForEach(Array(projection.dropEvents.prefix(8))) { event in
                    HStack(spacing: 8) {
                        Text(Self.timeFormatter.string(from: event.timestamp))
                            .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
                            .foregroundStyle(Theme.tTertiary)
                            .frame(width: 40, alignment: .leading)
                        Text(event.window)
                            .font(.system(size: Theme.fontSize(9.5), weight: .semibold))
                            .foregroundStyle(tool.tint)
                            .frame(width: 42, alignment: .leading)
                        Text(String(format: "-%.1f%%", event.drop))
                            .font(.system(size: Theme.fontSize(10.5), weight: .semibold, design: .monospaced))
                            .foregroundStyle(Theme.tPrimary)
                            .frame(width: 54, alignment: .trailing)
                        Text("\(event.durationMinutes) 分钟")
                            .font(.system(size: Theme.fontSize(9.5)))
                            .foregroundStyle(Theme.tTertiary)
                        activityText(event.activity)
                        Spacer()
                    }
                }
            }
        }
    }

    private func activitySection(_ projection: QuotaHistoryProjection) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("模型活动标记")
                .font(.system(size: Theme.fontSize(12), weight: .bold))
                .foregroundStyle(Theme.tPrimary)
            if projection.activityEvents.isEmpty {
                Text("尚未检测到该工具的模型 token 增量")
                    .font(.system(size: Theme.fontSize(10)))
                    .foregroundStyle(Theme.tTertiary)
            } else {
                ForEach(Array(projection.activityEvents.prefix(8))) { event in
                    HStack(spacing: 8) {
                        Text(Self.timeFormatter.string(
                            from: Date(timeIntervalSince1970: TimeInterval(event.timestamp))
                        ))
                            .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
                            .foregroundStyle(Theme.tTertiary)
                            .frame(width: 40, alignment: .leading)
                        activityText(event.activity)
                        Spacer()
                    }
                }
            }
        }
    }

    private func activityText(_ activity: [QuotaModelActivity]) -> some View {
        Text(activity.map { "\($0.model) +\(Fmt.human($0.tokenDelta))" }.joined(separator: " · "))
            .font(.system(size: Theme.fontSize(9.5), design: .monospaced))
            .foregroundStyle(Theme.tSecondary)
            .lineLimit(1)
    }

    private func makeFrame() -> QuotaHistoryFrame {
        let now = Date()
        let start = now.addingTimeInterval(TimeInterval(-span.rawValue * 60 * 60))
        return QuotaHistoryFrame(
            now: now,
            start: start,
            projection: QuotaHistoryProjection(
                points: history.points(since: start),
                tool: tool
            )
        )
    }

    private func seriesColor(for window: String) -> Color {
        switch (tool, window) {
        case (.claude, "5 小时"):
            return Color(red: 1.00, green: 0.43, blue: 0.28)
        case (.claude, "周 · 全部"):
            return Color(red: 0.66, green: 0.55, blue: 1.00)
        case (.claude, "周 · Fable"):
            return Color(red: 1.00, green: 0.72, blue: 0.16)
        case (.codex, "周"):
            return Theme.codex
        default:
            return tool.tint
        }
    }

    private func summaryTitle(for window: String) -> String {
        window == "5 小时" ? "5h 剩余" : "\(window)剩余"
    }

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }()
}

/// Owns hover state so pointer movement redraws only the chart, not the parent
/// page and its complete history projection.
private struct QuotaHistoryChart: View {
    let projection: QuotaHistoryProjection
    let start: Date
    let end: Date
    let span: QuotaHistorySpan
    let colors: [String: Color]

    @State private var hover: (sample: QuotaHoverSample, x: CGFloat)?

    var body: some View {
        Chart {
            ForEach(projection.lineData) { item in
                LineMark(
                    x: .value("时间", item.timestamp),
                    y: .value("剩余额度", item.remaining),
                    series: .value("额度窗口", item.window)
                )
                .foregroundStyle(by: .value("额度窗口", item.window))
                .interpolationMethod(.stepEnd)
                .lineStyle(StrokeStyle(lineWidth: 2.2, lineCap: .round, lineJoin: .round))
            }
            ForEach(projection.markerData) { item in
                let isLatest = projection.latestDatumIDs.contains(item.id)
                PointMark(
                    x: .value("活动时间", item.timestamp),
                    y: .value("活动额度", item.remaining)
                )
                .foregroundStyle(by: .value("额度窗口", item.window))
                .symbolSize(isLatest ? 16 : 8)
                .opacity(isLatest ? 1 : 0.62)
            }
        }
        .chartXScale(domain: start ... end)
        .chartYScale(domain: 0 ... 100)
        .chartForegroundStyleScale(
            domain: projection.windowNames,
            range: projection.windowNames.map { colors[$0] ?? Theme.claude }
        )
        .chartLegend(position: .top, alignment: .trailing, spacing: 10)
        .chartXAxis {
            AxisMarks(values: .stride(by: .hour, count: span.axisStride)) { value in
                AxisGridLine().foregroundStyle(Color.white.opacity(0.06))
                AxisTick().foregroundStyle(Color.white.opacity(0.18))
                AxisValueLabel(format: .dateTime.hour().minute())
                    .font(.system(size: Theme.fontSize(8.5), design: .monospaced))
                    .foregroundStyle(Theme.tTertiary)
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading, values: [0, 25, 50, 75, 100]) { value in
                AxisGridLine().foregroundStyle(Color.white.opacity(0.08))
                AxisValueLabel {
                    if let number = value.as(Int.self) {
                        Text("\(number)%")
                    }
                }
                .font(.system(size: Theme.fontSize(8.5), design: .monospaced))
                .foregroundStyle(Theme.tTertiary)
            }
        }
        .frame(height: 235)
        .chartOverlay { proxy in
            GeometryReader { geometry in
                let plot = geometry[proxy.plotAreaFrame]
                Rectangle()
                    .fill(.clear)
                    .contentShape(Rectangle())
                    .onContinuousHover { phase in
                        switch phase {
                        case .active(let location):
                            guard plot.contains(location),
                                  let date: Date = proxy.value(atX: location.x - plot.minX),
                                  let sample = projection.nearestHoverSample(to: date),
                                  let x = proxy.position(forX: sample.timestamp)
                            else {
                                hover = nil
                                return
                            }
                            hover = (sample: sample, x: x + plot.minX)
                        case .ended:
                            hover = nil
                        }
                    }
                if let hover {
                    hoverBubble(at: hover, plot: plot)
                }
            }
        }
    }

    @ViewBuilder
    private func hoverBubble(
        at hover: (sample: QuotaHoverSample, x: CGFloat),
        plot: CGRect
    ) -> some View {
        if !hover.sample.rows.isEmpty {
            let bubbleWidth: CGFloat = 154
            let rightmost = max(plot.minX, plot.maxX - bubbleWidth)
            let anchor = min(
                max(hover.x - bubbleWidth / 2, plot.minX),
                rightmost
            )
            ZStack(alignment: .topLeading) {
                Rectangle()
                    .fill(Color.white.opacity(0.32))
                    .frame(width: 1, height: plot.height)
                    .position(x: hover.x, y: plot.midY)
                VStack(alignment: .leading, spacing: 3) {
                    Text(Self.timeFormatter.string(from: hover.sample.timestamp))
                        .font(.system(size: Theme.fontSize(9.5), weight: .semibold, design: .monospaced))
                        .foregroundStyle(Theme.tPrimary)
                    ForEach(hover.sample.rows) { row in
                        HStack(spacing: 4) {
                            Circle()
                                .fill(colors[row.window] ?? Theme.claude)
                                .frame(width: 5, height: 5)
                            Text(row.window)
                                .font(.system(size: Theme.fontSize(9)))
                                .foregroundStyle(Theme.tSecondary)
                                .lineLimit(1)
                            Spacer(minLength: 4)
                            Text(String(format: "%.1f%%", row.remaining))
                                .font(.system(size: Theme.fontSize(9.5), weight: .semibold, design: .monospaced))
                                .foregroundStyle(Theme.tPrimary)
                        }
                    }
                    if !hover.sample.activity.isEmpty {
                        Text(
                            hover.sample.activity
                                .map { "\($0.model) +\(Fmt.human($0.tokenDelta))" }
                                .joined(separator: " · ")
                        )
                        .font(.system(size: Theme.fontSize(8.5), design: .monospaced))
                        .foregroundStyle(Theme.tTertiary)
                        .lineLimit(1)
                    }
                }
                .padding(.horizontal, 7)
                .padding(.vertical, 6)
                .frame(width: bubbleWidth, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: 7)
                        .fill(Color(red: 0.10, green: 0.11, blue: 0.14).opacity(0.96))
                        .shadow(color: Color.black.opacity(0.32), radius: 5, y: 2)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 7)
                        .strokeBorder(Color.white.opacity(0.14), lineWidth: 0.75)
                )
                .offset(x: anchor, y: plot.minY + 4)
                .allowsHitTesting(false)
            }
        }
    }

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }()
}
