import AppKit
import Combine

enum PanelPlacement {
    static let verticalMargin: CGFloat = 40
    static let minimumHeight: CGFloat = 320
    static let fallbackVisibleHeight: CGFloat = 900

    static func maximumHeight(anchorVisibleFrame: NSRect?,
                              fallbackVisibleFrame: NSRect? = nil) -> CGFloat {
        let visibleHeight = anchorVisibleFrame?.height
            ?? fallbackVisibleFrame?.height
            ?? fallbackVisibleHeight
        return max(minimumHeight, visibleHeight - verticalMargin)
    }
}

final class PanelLayoutContext: ObservableObject {
    @Published private(set) var maximumHeight: CGFloat

    init(maximumHeight: CGFloat = PanelPlacement.maximumHeight(anchorVisibleFrame: nil)) {
        self.maximumHeight = maximumHeight
    }

    func update(anchorVisibleFrame: NSRect?, fallbackVisibleFrame: NSRect?) {
        let nextHeight = PanelPlacement.maximumHeight(
            anchorVisibleFrame: anchorVisibleFrame,
            fallbackVisibleFrame: fallbackVisibleFrame
        )
        guard abs(maximumHeight - nextHeight) > 0.5 else { return }
        maximumHeight = nextHeight
    }
}
