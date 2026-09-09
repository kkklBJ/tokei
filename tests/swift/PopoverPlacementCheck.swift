import AppKit

private enum TestFailure: Error {
    case assertion(String)
}

@main
struct PopoverPlacementCheck {
    static func main() throws {
        let external = NSRect(x: 1920, y: 0, width: 1920, height: 1040)
        let focused = NSRect(x: 0, y: 0, width: 1512, height: 900)
        try expect(PanelPlacement.maximumHeight(anchorVisibleFrame: external,
                                               fallbackVisibleFrame: focused) == 1000,
                   "the status-item screen must take precedence over the focused screen")
        try expect(PanelPlacement.maximumHeight(anchorVisibleFrame: nil,
                                               fallbackVisibleFrame: focused) == 860,
                   "use the fallback only when the anchor screen is unavailable")
        let short = CGSize(width: 322, height: 240)
        try expect(PanelPlacement.contentSize(measuredSize: short, anchorVisibleFrame: external) == short,
                   "a short single-card panel must not reserve a 640x840 canvas")
        try expect(PanelPlacement.contentSize(measuredSize: CGSize(width: 640, height: 1600),
                                              anchorVisibleFrame: external) == CGSize(width: 640, height: 1000),
                   "long pages must be capped to the clicked screen")
        try expect(PanelPlacement.contentSize(measuredSize: CGSize(width: 640, height: 1600),
                                              anchorVisibleFrame: NSRect(x: 0, y: 0, width: 600, height: 300))
                   == CGSize(width: 600, height: 260), "even small screens must not be overflowed")
        // Grow/shrink repeatedly on screens left of, right of and above the primary.
        for screen in [external, NSRect(x: -1920, y: 0, width: 1920, height: 1040),
                       NSRect(x: 0, y: 1080, width: 1920, height: 1040)] {
            let anchor = NSRect(x: screen.midX, y: screen.maxY, width: 24, height: 24)
            var frame = NSRect(x: anchor.midX - 161, y: screen.maxY - 240, width: 322, height: 240)
            for _ in 0..<20 {
                for size in [CGSize(width: 640, height: 900), short] {
                    frame = PanelPlacement.resizedFrame(previous: frame, size: size,
                                                        anchor: anchor, visibleFrame: screen)
                    try expect(frame.maxY == screen.maxY && frame.midX == anchor.midX,
                               "resizing must preserve the anchor and top edge without drifting")
                    try expect(screen.contains(frame), "resizing must stay on the anchor screen")
                }
            }
            let edgeAnchor = NSRect(x: screen.maxX - 24, y: screen.maxY, width: 24, height: 24)
            let edge = PanelPlacement.resizedFrame(previous: frame, size: short,
                                                   anchor: edgeAnchor, visibleFrame: screen)
            try expect(edge.maxX == screen.maxX, "right-edge anchors must stay inside the screen")
        }
        print("popover placement checks passed")
    }

    private static func expect(_ condition: @autoclosure () -> Bool, _ message: String) throws {
        if !condition() { throw TestFailure.assertion(message) }
    }
}
