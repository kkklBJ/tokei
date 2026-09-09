import AppKit
import SwiftUI

private final class Fixture: ObservableObject {
    @Published var width: CGFloat = 322
    @Published var height: CGFloat = 240
}

private struct FixtureNativeBackground: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView { NSVisualEffectView() }
    func updateNSView(_ view: NSVisualEffectView, context: Context) {}
}

private struct FixtureView: View {
    @ObservedObject var fixture: Fixture
    let maximumHeight: CGFloat
    let measured: (CGSize) -> Void

    var body: some View {
        ContentFittingScrollView(width: fixture.width, maximumHeight: maximumHeight) {
            VStack(spacing: 0) {
                Text("Tokei layout check").frame(height: 40)
                Color.blue.frame(height: fixture.height - 80)
                Text("Footer").frame(height: 40)
            }
        }
        .background(FixtureNativeBackground())
        .background {
            GeometryReader { proxy in
                Color.clear.preference(key: PanelContentSizeKey.self, value: proxy.size)
            }
        }
        .onPreferenceChange(PanelContentSizeKey.self, perform: measured)
    }
}

@main
struct ContentFittingScrollViewCheck {
    @MainActor
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.regular)
        Task { @MainActor in await runChecks() }
        app.run()
    }

    @MainActor
    private static func runChecks() async {
        let app = NSApplication.shared
        app.activate(ignoringOtherApps: true)
        let fullscreen = CommandLine.arguments.contains("--fullscreen")
        var failures = [String]()
        // A programmatically created status item can have an offscreen proxy
        // window until a physical click. Use visible native button anchors so
        // the geometry regression is deterministic on every connected display.
        for screen in NSScreen.screens {
            let window = NSWindow(contentRect: NSRect(x: screen.frame.minX + 100,
                                                      y: screen.frame.minY + 100,
                                                      width: 700, height: 600),
                                  styleMask: [.titled, .resizable, .closable],
                                  backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false
            window.title = "Tokei fullscreen layout QA"
            window.collectionBehavior = [.fullScreenPrimary]
            let button = NSButton(title: "Tokei QA", target: nil, action: nil)
            button.frame = NSRect(x: 320, y: 550, width: 100, height: 30)
            button.autoresizingMask = [.minYMargin, .minXMargin]
            window.contentView!.addSubview(button)
            window.makeKeyAndOrderFront(nil)
            app.activate(ignoringOtherApps: true)
            await pump(0.5)
            if fullscreen {
                window.toggleFullScreen(nil)
                await pump(2)
            }
            if fullscreen && !window.styleMask.contains(.fullScreen) {
                failures.append("test window did not enter fullscreen on \(screen.frame)")
            } else {
                failures += await check(anchor: button)
            }
            if window.styleMask.contains(.fullScreen) {
                window.toggleFullScreen(nil)
                await pump(2)
            }
            window.close()
        }
        if failures.isEmpty {
            print("content fitting and live popover resize checks passed (fullscreen=\(fullscreen), \(NSScreen.screens.count) screens)")
        } else {
            failures.forEach { print($0) }
        }
        exit(failures.isEmpty ? 0 : 1)
    }

    @MainActor
    private static func check(anchor: NSView) async -> [String] {
        let fixture = Fixture()
        let popover = NSPopover()
        popover.animates = false
        popover.behavior = .applicationDefined
        defer { popover.close() }
        var failures = [String]()
        guard let screen = anchor.window?.screen else { return ["anchor has no screen: window=\(String(describing: anchor.window?.frame))"] }
        // The fullscreen test button is slightly below the menu bar.
        let anchorRect = anchor.window!.convertToScreen(anchor.convert(anchor.bounds, to: nil))
        let maximumHeight = min(PanelPlacement.maximumHeight(anchorVisibleFrame: screen.visibleFrame),
                                anchorRect.minY - screen.visibleFrame.minY - 40)
        let host = NSHostingController(rootView: FixtureView(
            fixture: fixture, maximumHeight: maximumHeight,
            measured: { size in
                guard size.height > 1 else { return }
                DispatchQueue.main.async {
                    PanelPlacement.resize(popover, to: size, anchorButton: anchor)
                }
            }
        ))
        host.sizingOptions = []
        popover.contentViewController = host
        popover.contentSize = CGSize(width: 322, height: 240)
        popover.show(relativeTo: anchor.bounds, of: anchor, preferredEdge: .minY)
        await pump()
        guard let window = host.view.window else { return ["popover did not open"] }
        let initialTop = window.frame.maxY
        for _ in 0..<3 {
            for (width, height) in [(CGFloat(322), CGFloat(240)), (640, 1400), (322, 180)] {
                fixture.width = width
                fixture.height = height
                await pump()
                let expectedHeight = min(height, maximumHeight)
                if abs(popover.contentSize.height - expectedHeight) > 1 || popover.contentSize.width != width {
                    failures.append("content \(width)x\(height): actual viewport \(popover.contentSize)")
                }
                let frame = window.frame
                if abs(frame.maxY - initialTop) > 1 {
                    failures.append("top edge drifted: \(initialTop) -> \(frame.maxY)")
                }
                let expectedCenter = max(screen.visibleFrame.minX + frame.width / 2,
                                         min(anchorRect.midX, screen.visibleFrame.maxX - frame.width / 2))
                if abs(frame.midX - expectedCenter) > 1 {
                    failures.append("horizontal anchor drifted: \(frame.midX) vs \(expectedCenter)")
                }
                if window.screen?.frame != screen.frame {
                    failures.append("popover moved to another screen: \(frame), expected \(screen.frame)")
                }
            }
        }
        return failures
    }

    @MainActor
    private static func pump(_ duration: TimeInterval = 0.25) async {
        try? await Task.sleep(nanoseconds: UInt64(duration * 1_000_000_000))
    }
}
