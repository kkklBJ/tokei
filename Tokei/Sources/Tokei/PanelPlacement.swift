import AppKit
import Combine

enum PanelPlacement {
    static let verticalMargin: CGFloat = 40
    static let fallbackVisibleFrame = NSRect(x: 0, y: 0, width: 1440, height: 900)

    static func maximumHeight(anchorVisibleFrame: NSRect?,
                              fallbackVisibleFrame: NSRect? = nil) -> CGFloat {
        let frame = anchorVisibleFrame ?? fallbackVisibleFrame ?? Self.fallbackVisibleFrame
        return max(1, frame.height - verticalMargin)
    }

    static func contentSize(measuredSize: CGSize,
                            anchorVisibleFrame: NSRect?,
                            fallbackVisibleFrame: NSRect? = nil) -> CGSize {
        let frame = anchorVisibleFrame ?? fallbackVisibleFrame ?? Self.fallbackVisibleFrame
        return CGSize(
            width: min(max(1, measuredSize.width), max(1, frame.width)),
            height: min(max(1, measuredSize.height), maximumHeight(anchorVisibleFrame: frame))
        )
    }

    // Keep the existing top edge and the clicked button's screen coordinates.
    // Re-showing an open NSPopover lets AppKit select a different fullscreen Space.
    static func resizedFrame(previous: NSRect, size: CGSize,
                             anchor: NSRect, visibleFrame: NSRect) -> NSRect {
        NSRect(
            x: max(visibleFrame.minX, min(anchor.midX - size.width / 2,
                                         visibleFrame.maxX - size.width)),
            // The arrow can extend above visibleFrame into the menu bar.
            y: max(visibleFrame.minY, previous.maxY - size.height),
            width: size.width,
            height: size.height
        )
    }

    static func resize(_ popover: NSPopover, to size: CGSize, anchorButton: NSView?) {
        guard popover.contentSize != size else { return }
        let window = popover.isShown ? popover.contentViewController?.view.window : nil
        let previous = window?.frame
        let anchor = anchorButton.flatMap { button in
            button.window?.convertToScreen(button.convert(button.bounds, to: nil))
        }
        let screen = anchorButton?.window?.screen
        popover.contentSize = size
        if let window, let previous, let anchor, let screen {
            window.contentView?.layoutSubtreeIfNeeded()
            let frame = resizedFrame(previous: previous, size: window.frame.size,
                                     anchor: anchor, visibleFrame: screen.visibleFrame)
            window.setFrameOrigin(frame.origin)
        }
    }
}

final class PanelLayoutContext: ObservableObject {
    @Published private(set) var visibleFrame = PanelPlacement.fallbackVisibleFrame
    private(set) var contentSize = CGSize(width: 322, height: 320)

    var maximumHeight: CGFloat { PanelPlacement.maximumHeight(anchorVisibleFrame: visibleFrame) }

    func update(anchorVisibleFrame: NSRect?, fallbackVisibleFrame: NSRect?) {
        let nextFrame = anchorVisibleFrame ?? fallbackVisibleFrame ?? PanelPlacement.fallbackVisibleFrame
        if visibleFrame != nextFrame { visibleFrame = nextFrame }
        contentSize = fittedSize(contentSize)
    }

    func fittedSize(_ measuredSize: CGSize) -> CGSize {
        PanelPlacement.contentSize(measuredSize: measuredSize, anchorVisibleFrame: visibleFrame)
    }

    func recordContentSize(_ size: CGSize) {
        contentSize = fittedSize(size)
    }
}
