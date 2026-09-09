import SwiftUI

// Measure the content, not the ScrollView's proposed viewport. This lets short
// pages shrink while long pages keep scrolling within the anchor screen.
struct ContentFittingScrollView<Content: View>: View {
    let width: CGFloat
    let maximumHeight: CGFloat
    @ViewBuilder var content: () -> Content
    @State private var contentHeight: CGFloat = 1

    var body: some View {
        ScrollView(.vertical, showsIndicators: false) {
            content()
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity)
                .background {
                    GeometryReader { proxy in
                        Color.clear.preference(key: PanelNaturalHeightKey.self, value: proxy.size.height)
                    }
                }
        }
        .frame(width: width, height: min(contentHeight, maximumHeight))
        .onPreferenceChange(PanelNaturalHeightKey.self) { height in
            guard height > 0, abs(height - contentHeight) > 0.5 else { return }
            contentHeight = height
        }
    }
}

private struct PanelNaturalHeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = max(value, nextValue())
    }
}

struct PanelContentSizeKey: PreferenceKey {
    static var defaultValue: CGSize = .zero
    static func reduce(value: inout CGSize, nextValue: () -> CGSize) {
        let next = nextValue()
        // Native background/tooltip views may contribute the default zero size.
        if next.width > 0 && next.height > 0 { value = next }
    }
}
