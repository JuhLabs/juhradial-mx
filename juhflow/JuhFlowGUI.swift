import SwiftUI
import AppKit

// MARK: - JuhRadial MX Design Tokens

enum JuhTheme {
    static let accent = Color(red: 0, green: 0.831, blue: 1.0)       // #00d4ff
    static let accent2 = Color(red: 0.039, green: 0.741, blue: 0.776) // #0abdc6
    static let crust = Color(red: 0.039, green: 0.047, blue: 0.063)   // #0a0c10
    static let mantle = Color(red: 0.059, green: 0.067, blue: 0.090)  // #0f1117
    static let base = Color(red: 0.071, green: 0.078, blue: 0.094)    // #121418
    static let surface0 = Color(red: 0.102, green: 0.114, blue: 0.141) // #1a1d24
    static let surface1 = Color(red: 0.141, green: 0.157, blue: 0.192) // #242831
    static let text = Color(red: 0.941, green: 0.957, blue: 0.973)    // #f0f4f8
    static let subtext = Color(red: 0.616, green: 0.647, blue: 0.694) // #9da5b1
    static let green = Color(red: 0, green: 0.902, blue: 0.463)       // #00e676
    static let orange = Color(red: 1, green: 0.694, blue: 0.251)      // #ffb140
}

// MARK: - Config Manager

class JuhFlowConfig: ObservableObject {
    static let shared = JuhFlowConfig()
    private let configURL: URL

    @Published var linuxIP: String = ""
    @Published var direction: String = "right"
    @Published var macChannel: Int = 1
    @Published var linuxChannel: Int = 2

    init() {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let configDir = appSupport.appendingPathComponent("JuhFlow")
        try? FileManager.default.createDirectory(at: configDir, withIntermediateDirectories: true)
        configURL = configDir.appendingPathComponent("config.json")
        load()
    }

    func load() {
        guard let data = try? Data(contentsOf: configURL),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        linuxIP = json["linux_ip"] as? String ?? linuxIP
        direction = json["direction"] as? String ?? direction
        macChannel = json["mac_channel"] as? Int ?? macChannel
        linuxChannel = json["linux_channel"] as? Int ?? linuxChannel
    }

    func save() {
        let json: [String: Any] = [
            "linux_ip": linuxIP,
            "direction": direction,
            "mac_channel": macChannel,
            "linux_channel": linuxChannel,
        ]
        if let data = try? JSONSerialization.data(withJSONObject: json, options: .prettyPrinted) {
            try? data.write(to: configURL)
        }
    }
}

// MARK: - Process Manager

class JuhFlowManager: ObservableObject {
    @Published var isRunning = false
    @Published var isConnected = false
    @Published var statusText = "Ready"
    @Published var lastEvent = ""

    private var process: Process?
    private var outputPipe: Pipe?

    let config = JuhFlowConfig.shared

    func toggle() {
        if isRunning { stop() } else { start() }
    }

    func start() {
        guard !isRunning else { return }
        config.save()

        let venvPython = NSString(string: "~/Downloads/juhflow/.venv/bin/python3").expandingTildeInPath
        let script = NSString(string: "~/Downloads/juhflow/juhflow_app.py").expandingTildeInPath

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: venvPython)

        var args = [script, "--cli", "--direction", config.direction,
                    "--mac-channel", String(config.macChannel),
                    "--linux-channel", String(config.linuxChannel)]
        if !config.linuxIP.isEmpty {
            args += ["--ip", config.linuxIP]
        }
        proc.arguments = args
        proc.currentDirectoryURL = URL(fileURLWithPath: NSString(string: "~/Downloads/juhflow").expandingTildeInPath)

        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = pipe

        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let output = String(data: data, encoding: .utf8) else { return }
            DispatchQueue.main.async { self?.processOutput(output) }
        }

        proc.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                self?.isRunning = false
                self?.isConnected = false
                self?.statusText = "Disconnected"
                self?.lastEvent = ""
            }
        }

        do {
            try proc.run()
            process = proc
            outputPipe = pipe
            isRunning = true
            isConnected = false
            statusText = "Connecting..."
        } catch {
            statusText = "Error: \(error.localizedDescription)"
        }
    }

    func stop() {
        guard isRunning, let proc = process else { return }
        proc.terminate()
        process = nil
        outputPipe?.fileHandleForReading.readabilityHandler = nil
        outputPipe = nil
    }

    private func processOutput(_ text: String) {
        for line in text.components(separatedBy: .newlines) {
            if line.contains("Connected to Linux:") {
                isConnected = true
                statusText = "Connected"
            } else if line.contains("Edge hit:") {
                lastEvent = "Edge hit -> Linux"
            } else if line.contains("Cursor warped to") {
                lastEvent = "Cursor <- Linux"
            } else if line.contains("Easy-Switch: switched") {
                lastEvent = line.contains("host \(config.linuxChannel - 1)") ?
                    "MX -> Linux ch\(config.linuxChannel)" : "MX -> Mac ch\(config.macChannel)"
            } else if line.contains("Clipboard synced") {
                lastEvent = "Clipboard synced"
            } else if line.contains("Bluetooth toggled") {
                lastEvent = "BT toggled"
            }
        }
    }
}

// MARK: - Subviews

struct ThemedCard<Content: View>: View {
    let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }

    var body: some View {
        content
            .padding(14)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(
                        LinearGradient(colors: [JuhTheme.surface0, JuhTheme.base],
                                       startPoint: .topLeading, endPoint: .bottomTrailing)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(Color.white.opacity(0.06), lineWidth: 1)
                    )
            )
    }
}

struct DirectionButton: View {
    let label: String
    let icon: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 3) {
                Image(systemName: icon)
                    .font(.system(size: 14, weight: .medium))
                Text(label)
                    .font(.system(size: 9, weight: .medium))
            }
            .frame(width: 50, height: 42)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(isSelected ?
                          LinearGradient(colors: [JuhTheme.accent.opacity(0.2), JuhTheme.accent2.opacity(0.1)],
                                         startPoint: .topLeading, endPoint: .bottomTrailing) :
                          LinearGradient(colors: [Color.clear], startPoint: .top, endPoint: .bottom))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(isSelected ? JuhTheme.accent.opacity(0.5) : Color.white.opacity(0.06), lineWidth: 1)
            )
            .foregroundColor(isSelected ? JuhTheme.accent : JuhTheme.subtext)
        }
        .buttonStyle(.plain)
    }
}

struct ChannelPicker: View {
    let label: String
    let emoji: String
    @Binding var channel: Int

    var body: some View {
        HStack(spacing: 8) {
            HStack(spacing: 4) {
                Text(emoji).font(.system(size: 11))
                Text(label)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundColor(JuhTheme.subtext)
            }
            .frame(width: 60, alignment: .trailing)
            ForEach(1...3, id: \.self) { ch in
                Button(action: { channel = ch }) {
                    Text("\(ch)")
                        .font(.system(size: 12, weight: .semibold, design: .monospaced))
                        .frame(width: 28, height: 28)
                        .background(
                            RoundedRectangle(cornerRadius: 6)
                                .fill(channel == ch ?
                                      LinearGradient(colors: [JuhTheme.accent.opacity(0.2), JuhTheme.accent2.opacity(0.1)],
                                                     startPoint: .topLeading, endPoint: .bottomTrailing) :
                                      LinearGradient(colors: [Color.clear], startPoint: .top, endPoint: .bottom))
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 6)
                                .stroke(channel == ch ? JuhTheme.accent.opacity(0.5) : Color.white.opacity(0.06), lineWidth: 1)
                        )
                        .foregroundColor(channel == ch ? JuhTheme.accent : JuhTheme.subtext)
                }
                .buttonStyle(.plain)
            }
        }
    }
}

struct LayoutPreview: View {
    let direction: String
    let isConnected: Bool

    private var linuxOffset: (CGFloat, CGFloat) {
        switch direction {
        case "left":  return (-52, 0)
        case "right": return (52, 0)
        case "top":   return (0, -36)
        case "bottom": return (0, 36)
        default: return (52, 0)
        }
    }

    var body: some View {
        ZStack {
            // Mac monitor
            RoundedRectangle(cornerRadius: 4)
                .fill(JuhTheme.accent.opacity(0.1))
                .overlay(
                    RoundedRectangle(cornerRadius: 4)
                        .stroke(JuhTheme.accent.opacity(0.3), lineWidth: 1)
                )
                .frame(width: 44, height: 30)
                .overlay(Text("\u{f8ff}").font(.system(size: 12)))

            // Linux monitor
            RoundedRectangle(cornerRadius: 4)
                .fill(isConnected ? JuhTheme.green.opacity(0.1) : JuhTheme.surface1.opacity(0.5))
                .overlay(
                    RoundedRectangle(cornerRadius: 4)
                        .stroke(isConnected ? JuhTheme.green.opacity(0.3) : Color.white.opacity(0.06), lineWidth: 1)
                )
                .frame(width: 44, height: 30)
                .overlay(Text("\u{1F427}").font(.system(size: 12)))
                .offset(x: linuxOffset.0, y: linuxOffset.1)

            // Flow arrow
            if isConnected {
                Image(systemName: arrowIcon)
                    .font(.system(size: 8, weight: .bold))
                    .foregroundColor(JuhTheme.green.opacity(0.7))
                    .offset(x: linuxOffset.0 / 2.4, y: linuxOffset.1 / 2.4)
            }
        }
        .frame(height: 70)
        .animation(.easeInOut(duration: 0.3), value: direction)
        .animation(.easeInOut(duration: 0.3), value: isConnected)
    }

    private var arrowIcon: String {
        switch direction {
        case "left": return "arrow.left"
        case "right": return "arrow.right"
        case "top": return "arrow.up"
        case "bottom": return "arrow.down"
        default: return "arrow.right"
        }
    }
}

// MARK: - Main View

struct ContentView: View {
    @StateObject private var manager = JuhFlowManager()
    @State private var isHovered = false
    @State private var isPressed = false
    @State private var ringRotation: Double = 0
    @State private var showIPField = false

    private var buttonColor: Color {
        if manager.isConnected { return JuhTheme.green }
        if manager.isRunning { return JuhTheme.orange }
        return JuhTheme.accent
    }

    private var glowColor: Color {
        if manager.isConnected { return JuhTheme.green }
        if manager.isRunning { return JuhTheme.orange }
        return JuhTheme.accent
    }

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack(spacing: 8) {
                // Radial wheel icon (matching the Cairo logo)
                ZStack {
                    Circle()
                        .fill(
                            LinearGradient(colors: [JuhTheme.accent.opacity(0.15), JuhTheme.accent2.opacity(0.08)],
                                           startPoint: .topLeading, endPoint: .bottomTrailing)
                        )
                        .frame(width: 28, height: 28)
                        .overlay(
                            Circle().stroke(JuhTheme.accent.opacity(0.25), lineWidth: 1)
                        )
                    Image(systemName: "circle.hexagongrid.fill")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundColor(JuhTheme.accent)
                }

                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 4) {
                        Text("JuhFlow")
                            .font(.system(size: 13, weight: .heavy, design: .rounded))
                            .foregroundColor(JuhTheme.text)
                        Text("MX")
                            .font(.system(size: 13, weight: .heavy, design: .rounded))
                            .foregroundColor(JuhTheme.accent)
                    }
                    Text("COMPANION APP")
                        .font(.system(size: 8, weight: .semibold))
                        .foregroundColor(JuhTheme.subtext)
                        .kerning(1.2)
                }
                Spacer()

                // Gear button for IP config
                Button(action: { withAnimation { showIPField.toggle() } }) {
                    Image(systemName: "gearshape")
                        .font(.system(size: 12))
                        .foregroundColor(JuhTheme.subtext)
                        .frame(width: 24, height: 24)
                        .background(Circle().fill(JuhTheme.surface0))
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(JuhTheme.crust)

            Divider().background(Color.white.opacity(0.06))

            // IP config field (toggled by gear)
            if showIPField {
                ThemedCard {
                    HStack(spacing: 8) {
                        Image(systemName: "network")
                            .font(.system(size: 11))
                            .foregroundColor(JuhTheme.accent)
                        TextField("Linux IP (auto-discover if empty)", text: $manager.config.linuxIP)
                            .textFieldStyle(.plain)
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundColor(JuhTheme.text)
                            .onSubmit { manager.config.save() }
                    }
                }
                .padding(.horizontal, 12)
                .padding(.top, 8)
                .transition(.opacity.combined(with: .move(edge: .top)))
            }

            ScrollView(showsIndicators: false) {
                VStack(spacing: 10) {
                    // Layout preview
                    LayoutPreview(direction: manager.config.direction, isConnected: manager.isConnected)
                        .padding(.top, 4)

                    // Main power button
                    ZStack {
                        Circle()
                            .stroke(
                                AngularGradient(
                                    colors: [glowColor.opacity(0.6), glowColor.opacity(0.1), glowColor.opacity(0.6)],
                                    center: .center
                                ),
                                lineWidth: 2.5
                            )
                            .frame(width: 78, height: 78)
                            .rotationEffect(.degrees(ringRotation))
                            .opacity(manager.isRunning ? 1 : 0)
                            .animation(.easeInOut(duration: 0.5), value: manager.isRunning)

                        Circle()
                            .fill(glowColor.opacity(manager.isRunning ? 0.1 : 0))
                            .frame(width: 68, height: 68)
                            .blur(radius: 16)

                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: [
                                        buttonColor.opacity(isHovered ? 0.3 : 0.15),
                                        buttonColor.opacity(isHovered ? 0.15 : 0.05),
                                    ],
                                    startPoint: .top, endPoint: .bottom
                                )
                            )
                            .frame(width: 60, height: 60)
                            .overlay(
                                Circle().stroke(buttonColor.opacity(isHovered ? 0.5 : 0.25), lineWidth: 1.5)
                            )
                            .shadow(color: glowColor.opacity(manager.isConnected ? 0.3 : 0), radius: 10)
                            .scaleEffect(isPressed ? 0.92 : (isHovered ? 1.04 : 1.0))

                        Image(systemName: manager.isRunning ? "stop.fill" : "power")
                            .font(.system(size: 18, weight: .medium))
                            .foregroundColor(buttonColor)
                            .scaleEffect(isPressed ? 0.9 : 1.0)
                    }
                    .onHover { h in withAnimation(.easeOut(duration: 0.2)) { isHovered = h } }
                    .onTapGesture {
                        withAnimation(.spring(response: 0.3, dampingFraction: 0.6)) { isPressed = true }
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                            withAnimation(.spring(response: 0.3, dampingFraction: 0.6)) { isPressed = false }
                            manager.toggle()
                        }
                    }
                    .onAppear {
                        withAnimation(.linear(duration: 3).repeatForever(autoreverses: false)) {
                            ringRotation = 360
                        }
                    }

                    // Status
                    VStack(spacing: 3) {
                        HStack(spacing: 4) {
                            Circle()
                                .fill(manager.isConnected ? JuhTheme.green : (manager.isRunning ? JuhTheme.orange : JuhTheme.subtext.opacity(0.4)))
                                .frame(width: 6, height: 6)
                            Text(manager.statusText)
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundColor(JuhTheme.subtext)
                        }
                        if !manager.lastEvent.isEmpty {
                            Text(manager.lastEvent)
                                .font(.system(size: 9, weight: .medium, design: .monospaced))
                                .foregroundColor(JuhTheme.subtext.opacity(0.6))
                                .transition(.opacity)
                        }
                    }

                    // Direction card
                    ThemedCard {
                        VStack(spacing: 8) {
                            Text("Linux is on my...")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundColor(JuhTheme.subtext)
                                .kerning(0.3)

                            HStack(spacing: 5) {
                                DirectionButton(label: "Left", icon: "arrow.left.square.fill",
                                    isSelected: manager.config.direction == "left") { manager.config.direction = "left"; manager.config.save() }
                                DirectionButton(label: "Right", icon: "arrow.right.square.fill",
                                    isSelected: manager.config.direction == "right") { manager.config.direction = "right"; manager.config.save() }
                                DirectionButton(label: "Above", icon: "arrow.up.square.fill",
                                    isSelected: manager.config.direction == "top") { manager.config.direction = "top"; manager.config.save() }
                                DirectionButton(label: "Below", icon: "arrow.down.square.fill",
                                    isSelected: manager.config.direction == "bottom") { manager.config.direction = "bottom"; manager.config.save() }
                            }
                        }
                    }
                    .padding(.horizontal, 12)

                    // Channel card
                    ThemedCard {
                        VStack(spacing: 6) {
                            Text("Easy-Switch Channels")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundColor(JuhTheme.subtext)
                                .kerning(0.3)

                            ChannelPicker(label: "Mac", emoji: "\u{f8ff}", channel: $manager.config.macChannel)
                                .onChange(of: manager.config.macChannel) { _ in manager.config.save() }
                            ChannelPicker(label: "Linux", emoji: "\u{1F427}", channel: $manager.config.linuxChannel)
                                .onChange(of: manager.config.linuxChannel) { _ in manager.config.save() }
                        }
                    }
                    .padding(.horizontal, 12)

                    // Security badge
                    HStack(spacing: 4) {
                        Image(systemName: "lock.shield.fill")
                            .font(.system(size: 8))
                            .foregroundColor(JuhTheme.accent.opacity(0.5))
                        Text("AES-256-GCM encrypted")
                            .font(.system(size: 8, weight: .medium))
                            .foregroundColor(JuhTheme.subtext.opacity(0.5))
                    }
                    .padding(.top, 2)
                }
                .padding(.vertical, 8)
            }
        }
        .frame(width: 260, height: 520)
        .background(JuhTheme.mantle)
        .preferredColorScheme(.dark)
    }
}

struct VisualEffectView: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = .hudWindow
        view.blendingMode = .behindWindow
        view.state = .active
        return view
    }
    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {}
}

@main
struct JuhFlowGUIApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentSize)
    }
}
