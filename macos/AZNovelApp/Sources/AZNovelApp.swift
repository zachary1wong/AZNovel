import Cocoa

struct CLIConfig {
    let sourceRoot: String
    let pythonPath: String

    static func bundled() -> CLIConfig {
        let fallbackPython = "/usr/bin/python3"
        guard
            let url = Bundle.main.url(forResource: "AZNovelCLI", withExtension: "plist"),
            let dict = NSDictionary(contentsOf: url)
        else {
            return CLIConfig(sourceRoot: "", pythonPath: fallbackPython)
        }

        let sourceRoot = dict["SourceRoot"] as? String ?? ""
        let pythonPath = dict["PythonPath"] as? String ?? fallbackPython
        return CLIConfig(sourceRoot: sourceRoot, pythonPath: pythonPath)
    }
}

func stripANSIEscapes(_ value: String) -> String {
    value.replacingOccurrences(
        of: #"\u{001B}\[[0-9;?]*[A-Za-z]"#,
        with: "",
        options: .regularExpression
    )
}

func shellDisplay(_ parts: [String]) -> String {
    parts.map { part in
        if part.isEmpty { return "''" }
        if part.range(of: #"[^A-Za-z0-9_./:=,+-]"#, options: .regularExpression) == nil {
            return part
        }
        return "'" + part.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }.joined(separator: " ")
}

enum CommandLineSplitError: Error {
    case unterminatedQuote
}

func splitCommandLine(_ input: String) throws -> [String] {
    var result: [String] = []
    var current = ""
    var quote: Character?
    var escaping = false

    for char in input {
        if escaping {
            current.append(char)
            escaping = false
            continue
        }

        if char == "\\" {
            escaping = true
            continue
        }

        if let activeQuote = quote {
            if char == activeQuote {
                quote = nil
            } else {
                current.append(char)
            }
            continue
        }

        if char == "'" || char == "\"" {
            quote = char
            continue
        }

        if char.isWhitespace {
            if !current.isEmpty {
                result.append(current)
                current = ""
            }
            continue
        }

        current.append(char)
    }

    if escaping {
        current.append("\\")
    }

    if quote != nil {
        throw CommandLineSplitError.unterminatedQuote
    }

    if !current.isEmpty {
        result.append(current)
    }

    return result
}

final class MainViewController: NSViewController {
    private let cliConfig = CLIConfig.bundled()
    private let headerStack = NSStackView()
    private let lanesStack = NSStackView()
    private let scrollView = NSScrollView()
    private let sourceLabel = NSTextField(labelWithString: "")

    private var profiles: [String] = []
    private var lanes: [NovelLaneView] = []
    private var nextLaneNumber = 1

    override func loadView() {
        view = NSView(frame: NSRect(x: 0, y: 0, width: 1120, height: 780))
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        setupLayout()
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        refreshProfiles()
        addLane()
    }

    private func setupLayout() {
        let root = NSStackView()
        root.orientation = .vertical
        root.spacing = 14
        root.edgeInsets = NSEdgeInsets(top: 18, left: 20, bottom: 18, right: 20)
        root.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(root)

        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            root.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            root.topAnchor.constraint(equalTo: view.topAnchor),
            root.bottomAnchor.constraint(equalTo: view.bottomAnchor)
        ])

        headerStack.orientation = .horizontal
        headerStack.alignment = .top
        headerStack.spacing = 12

        let titleColumn = NSStackView()
        titleColumn.orientation = .vertical
        titleColumn.spacing = 4

        let title = NSTextField(labelWithString: "AZNovel")
        title.font = .systemFont(ofSize: 28, weight: .semibold)

        let subtitle = NSTextField(labelWithString: "多工作线小说写作壳子：每条线都调用同一套 aznovel CLI，可并行运行。")
        subtitle.font = .systemFont(ofSize: 13)
        subtitle.textColor = .secondaryLabelColor

        sourceLabel.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        sourceLabel.textColor = .tertiaryLabelColor
        sourceLabel.lineBreakMode = .byTruncatingMiddle
        let sourceText = cliConfig.sourceRoot.isEmpty ? "(未写入源码路径)" : cliConfig.sourceRoot
        sourceLabel.stringValue = "CLI: \(cliConfig.pythonPath) -m aznovel    Source: \(sourceText)"

        titleColumn.addArrangedSubview(title)
        titleColumn.addArrangedSubview(subtitle)
        titleColumn.addArrangedSubview(sourceLabel)

        let spacer = NSView()
        spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)

        let addButton = NSButton(title: "添加工作线", target: self, action: #selector(addLane))
        addButton.bezelStyle = .rounded

        let refreshButton = NSButton(title: "刷新配置", target: self, action: #selector(refreshProfiles))
        refreshButton.bezelStyle = .rounded

        headerStack.addArrangedSubview(titleColumn)
        headerStack.addArrangedSubview(spacer)
        headerStack.addArrangedSubview(refreshButton)
        headerStack.addArrangedSubview(addButton)

        let documentView = NSView()
        lanesStack.orientation = .vertical
        lanesStack.alignment = .width
        lanesStack.spacing = 12
        lanesStack.translatesAutoresizingMaskIntoConstraints = false
        documentView.addSubview(lanesStack)

        NSLayoutConstraint.activate([
            lanesStack.leadingAnchor.constraint(equalTo: documentView.leadingAnchor),
            lanesStack.trailingAnchor.constraint(equalTo: documentView.trailingAnchor),
            lanesStack.topAnchor.constraint(equalTo: documentView.topAnchor),
            lanesStack.bottomAnchor.constraint(lessThanOrEqualTo: documentView.bottomAnchor)
        ])

        scrollView.documentView = documentView
        scrollView.hasVerticalScroller = true
        scrollView.drawsBackground = false
        scrollView.borderType = .noBorder

        root.addArrangedSubview(headerStack)
        root.addArrangedSubview(scrollView)

        scrollView.heightAnchor.constraint(greaterThanOrEqualToConstant: 560).isActive = true
    }

    @objc private func addLane() {
        let lane = NovelLaneView(
            laneNumber: nextLaneNumber,
            cliConfig: cliConfig,
            profiles: profiles,
            onRemove: { [weak self] lane in
                self?.removeLane(lane)
            }
        )
        nextLaneNumber += 1
        lanes.append(lane)
        lanesStack.addArrangedSubview(lane)
    }

    private func removeLane(_ lane: NovelLaneView) {
        lane.stopProcess()
        lanes.removeAll { $0 === lane }
        lanesStack.removeArrangedSubview(lane)
        lane.removeFromSuperview()
        if lanes.isEmpty {
            addLane()
        }
    }

    @objc private func refreshProfiles() {
        profiles = ProfileLoader.loadProfileNames()
        lanes.forEach { $0.updateProfiles(profiles) }
    }
}

enum ProfileLoader {
    static func loadProfileNames() -> [String] {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let file = home.appendingPathComponent(".aznovel/llm_profiles.json")
        guard let data = try? Data(contentsOf: file) else {
            return []
        }

        guard
            let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let profiles = root["profiles"] as? [[String: Any]]
        else {
            return []
        }

        return profiles.compactMap { profile in
            profile["name"] as? String
        }.sorted()
    }
}

final class NovelLaneView: NSBox {
    private let cliConfig: CLIConfig
    private let onRemove: (NovelLaneView) -> Void

    private let projectField = NSTextField()
    private let profilePopup = NSPopUpButton()
    private let actionPopup = NSPopUpButton()
    private let argumentField = NSTextField()
    private let modePopup = NSPopUpButton()
    private let statusLabel = NSTextField(labelWithString: "就绪")
    private let logView = NSTextView()
    private let startButton = NSButton()
    private let stopButton = NSButton()
    private let removeButton = NSButton()

    private var process: Process?
    private var outputPipe: Pipe?
    private var currentProfiles: [String]

    init(
        laneNumber: Int,
        cliConfig: CLIConfig,
        profiles: [String],
        onRemove: @escaping (NovelLaneView) -> Void
    ) {
        self.cliConfig = cliConfig
        self.currentProfiles = profiles
        self.onRemove = onRemove
        super.init(frame: .zero)
        title = "工作线 \(laneNumber)"
        boxType = .primary
        borderType = .lineBorder
        contentViewMargins = NSSize(width: 14, height: 12)
        setupUI()
        updateProfiles(profiles)
        updateArgumentHint()
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    private func setupUI() {
        guard let contentView else { return }

        let root = NSStackView()
        root.orientation = .vertical
        root.spacing = 10
        root.translatesAutoresizingMaskIntoConstraints = false
        contentView.addSubview(root)

        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: contentView.leadingAnchor),
            root.trailingAnchor.constraint(equalTo: contentView.trailingAnchor),
            root.topAnchor.constraint(equalTo: contentView.topAnchor),
            root.bottomAnchor.constraint(equalTo: contentView.bottomAnchor)
        ])

        projectField.placeholderString = "选择 AZNovel 小说项目目录"
        projectField.font = .monospacedSystemFont(ofSize: 12, weight: .regular)

        let chooseButton = NSButton(title: "选择目录", target: self, action: #selector(chooseProjectDirectory))
        chooseButton.bezelStyle = .rounded

        let openButton = NSButton(title: "打开目录", target: self, action: #selector(openProjectDirectory))
        openButton.bezelStyle = .rounded

        let directoryRow = makeRow([
            makeLabel("小说目录", width: 64),
            projectField,
            chooseButton,
            openButton
        ])

        profilePopup.setContentHuggingPriority(.defaultHigh, for: .horizontal)
        profilePopup.widthAnchor.constraint(greaterThanOrEqualToConstant: 180).isActive = true

        actionPopup.addItems(withTitles: [
            "无人值守续写",
            "写指定章节",
            "精修指定章节",
            "精修全书",
            "完稿流程",
            "导出全书",
            "项目状态",
            "自定义 CLI 参数"
        ])
        actionPopup.target = self
        actionPopup.action = #selector(actionChanged)
        actionPopup.widthAnchor.constraint(greaterThanOrEqualToConstant: 148).isActive = true

        argumentField.font = .systemFont(ofSize: 13)
        argumentField.placeholderString = "目标章数，可留空"

        modePopup.addItems(withTitles: ["default", "fast", "minimal"])
        modePopup.widthAnchor.constraint(equalToConstant: 96).isActive = true

        startButton.title = "开始"
        startButton.target = self
        startButton.action = #selector(startProcess)
        startButton.bezelStyle = .rounded

        stopButton.title = "停止"
        stopButton.target = self
        stopButton.action = #selector(stopProcessAction)
        stopButton.bezelStyle = .rounded
        stopButton.isEnabled = false

        removeButton.title = "移除"
        removeButton.target = self
        removeButton.action = #selector(removeLane)
        removeButton.bezelStyle = .rounded

        let commandRow = makeRow([
            makeLabel("配置", width: 64),
            profilePopup,
            makeLabel("动作", width: 36),
            actionPopup,
            makeLabel("参数", width: 36),
            argumentField,
            makeLabel("模式", width: 36),
            modePopup,
            startButton,
            stopButton,
            removeButton
        ])

        statusLabel.font = .systemFont(ofSize: 12)
        statusLabel.textColor = .secondaryLabelColor

        let clearButton = NSButton(title: "清空日志", target: self, action: #selector(clearLog))
        clearButton.bezelStyle = .rounded

        let statusSpacer = NSView()
        statusSpacer.setContentHuggingPriority(.defaultLow, for: .horizontal)

        let statusRow = makeRow([
            makeLabel("状态", width: 64),
            statusLabel,
            statusSpacer,
            clearButton
        ])

        let scrollView = NSScrollView()
        scrollView.hasVerticalScroller = true
        scrollView.borderType = .bezelBorder
        scrollView.drawsBackground = true
        scrollView.backgroundColor = .textBackgroundColor
        scrollView.heightAnchor.constraint(equalToConstant: 190).isActive = true

        logView.isEditable = false
        logView.isSelectable = true
        logView.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        logView.textContainerInset = NSSize(width: 8, height: 8)
        logView.backgroundColor = .textBackgroundColor
        scrollView.documentView = logView

        root.addArrangedSubview(directoryRow)
        root.addArrangedSubview(commandRow)
        root.addArrangedSubview(statusRow)
        root.addArrangedSubview(scrollView)
    }

    func updateProfiles(_ profiles: [String]) {
        let previous = selectedProfileName()
        currentProfiles = profiles
        profilePopup.removeAllItems()
        profilePopup.addItem(withTitle: "使用项目/默认配置")
        profilePopup.menu?.addItem(.separator())
        profilePopup.addItems(withTitles: profiles)

        if let previous, profiles.contains(previous) {
            profilePopup.selectItem(withTitle: previous)
        } else {
            profilePopup.selectItem(at: 0)
        }
    }

    @objc private func actionChanged() {
        updateArgumentHint()
    }

    private func updateArgumentHint() {
        modePopup.isEnabled = actionPopup.indexOfSelectedItem == 1
        switch actionPopup.indexOfSelectedItem {
        case 0:
            argumentField.placeholderString = "目标章数，可留空"
        case 1:
            argumentField.placeholderString = "章节号，例如 12"
        case 2:
            argumentField.placeholderString = "章节号，例如 12"
        case 3:
            argumentField.placeholderString = "可留空"
        case 4:
            argumentField.placeholderString = "可留空；输入 --dry-run 可试运行"
        case 5:
            argumentField.placeholderString = "epub,pdf,docx,mobi 或 all"
        case 6:
            argumentField.placeholderString = "可留空"
        default:
            argumentField.placeholderString = "例如 write --chapter 1 --mode fast"
        }
    }

    @objc private func chooseProjectDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.prompt = "选择"
        if !projectField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            panel.directoryURL = URL(fileURLWithPath: projectField.stringValue)
        }

        if panel.runModal() == .OK, let url = panel.url {
            projectField.stringValue = url.path
        }
    }

    @objc private func openProjectDirectory() {
        let path = projectField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !path.isEmpty else { return }
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    @objc private func clearLog() {
        logView.string = ""
    }

    @objc private func removeLane() {
        onRemove(self)
    }

    @objc private func startProcess() {
        guard process == nil else { return }

        let projectPath = projectField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !projectPath.isEmpty else {
            showAlert("请选择小说项目目录。")
            return
        }

        guard FileManager.default.fileExists(atPath: projectPath) else {
            showAlert("目录不存在：\(projectPath)")
            return
        }

        let args: [String]
        do {
            args = try buildArguments()
        } catch CommandLineSplitError.unterminatedQuote {
            showAlert("自定义参数里有未闭合的引号。")
            return
        } catch {
            showAlert("参数解析失败：\(error.localizedDescription)")
            return
        }

        var finalArgs = ["-m", "aznovel"]
        finalArgs.append(contentsOf: args)

        let process = Process()
        process.executableURL = URL(fileURLWithPath: cliConfig.pythonPath)
        process.arguments = finalArgs
        process.currentDirectoryURL = URL(fileURLWithPath: projectPath)

        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONUNBUFFERED"] = "1"
        environment["TERM"] = "xterm-256color"
        if !cliConfig.sourceRoot.isEmpty {
            let existing = environment["PYTHONPATH"]
            environment["PYTHONPATH"] = [cliConfig.sourceRoot, existing]
                .compactMap { $0 }
                .filter { !$0.isEmpty }
                .joined(separator: ":")
        }
        process.environment = environment

        let pipe = Pipe()
        outputPipe = pipe
        process.standardOutput = pipe
        process.standardError = pipe

        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            DispatchQueue.main.async {
                self?.appendLog(stripANSIEscapes(text.replacingOccurrences(of: "\r", with: "\n")))
            }
        }

        process.terminationHandler = { [weak self] finishedProcess in
            DispatchQueue.main.async {
                self?.processDidExit(finishedProcess.terminationStatus)
            }
        }

        do {
            appendLog("\n$ \(shellDisplay([cliConfig.pythonPath] + finalArgs))\n")
            if !FileManager.default.fileExists(atPath: "\(projectPath)/.aznovel/state.json") {
                appendLog("提示：该目录不像 AZNovel 项目。若运行 init 或自定义命令可忽略。\n")
            }
            try process.run()
            self.process = process
            setRunning(true)
        } catch {
            pipe.fileHandleForReading.readabilityHandler = nil
            outputPipe = nil
            showAlert("启动失败：\(error.localizedDescription)")
        }
    }

    @objc private func stopProcessAction() {
        stopProcess()
    }

    func stopProcess() {
        guard let process else { return }
        appendLog("\n正在停止进程...\n")
        process.terminate()
    }

    private func processDidExit(_ status: Int32) {
        outputPipe?.fileHandleForReading.readabilityHandler = nil
        outputPipe = nil
        process = nil
        setRunning(false)
        appendLog("\n进程结束，退出码：\(status)\n")
    }

    private func setRunning(_ running: Bool) {
        statusLabel.stringValue = running ? "运行中" : "就绪"
        statusLabel.textColor = running ? .systemGreen : .secondaryLabelColor
        startButton.isEnabled = !running
        stopButton.isEnabled = running
        removeButton.isEnabled = !running
    }

    private func appendLog(_ text: String) {
        guard let storage = logView.textStorage else { return }
        let attributed = NSAttributedString(
            string: text,
            attributes: [
                .font: NSFont.monospacedSystemFont(ofSize: 12, weight: .regular),
                .foregroundColor: NSColor.textColor
            ]
        )
        storage.append(attributed)
        logView.scrollToEndOfDocument(nil)
    }

    private func buildArguments() throws -> [String] {
        let commandArgs = try selectedCommandArguments()
        let profile = selectedProfileName()

        if let profile, !commandArgs.contains("--profile") {
            return ["--profile", profile] + commandArgs
        }

        return commandArgs
    }

    private func selectedCommandArguments() throws -> [String] {
        let value = argumentField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)

        switch actionPopup.indexOfSelectedItem {
        case 0:
            var args = ["auto-run"]
            if !value.isEmpty {
                args.append(contentsOf: ["--target", value])
            }
            return args
        case 1:
            guard !value.isEmpty else {
                throw NSError(domain: "AZNovelApp", code: 1, userInfo: [NSLocalizedDescriptionKey: "请输入章节号。"])
            }
            return ["write", "--chapter", value, "--mode", modePopup.titleOfSelectedItem ?? "default"]
        case 2:
            guard !value.isEmpty else {
                throw NSError(domain: "AZNovelApp", code: 2, userInfo: [NSLocalizedDescriptionKey: "请输入章节号。"])
            }
            return ["polish", "--chapter", value]
        case 3:
            return ["polish", "--all"]
        case 4:
            if value == "--dry-run" {
                return ["finalize", "--dry-run"]
            }
            return ["finalize"]
        case 5:
            return ["export", "--format", value.isEmpty ? "epub" : value]
        case 6:
            return ["status"]
        default:
            var parts = try splitCommandLine(value)
            if parts.first == "aznovel" || parts.first?.hasSuffix("/aznovel") == true {
                parts.removeFirst()
            } else if parts.count >= 3, parts[1] == "-m", parts[2] == "aznovel" {
                parts.removeFirst(3)
            }
            return parts
        }
    }

    private func selectedProfileName() -> String? {
        let index = profilePopup.indexOfSelectedItem
        guard index >= 2 else { return nil }
        let title = profilePopup.titleOfSelectedItem ?? ""
        return title.isEmpty ? nil : title
    }

    private func showAlert(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "AZNovel"
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.runModal()
    }

    private func makeLabel(_ text: String, width: CGFloat) -> NSTextField {
        let label = NSTextField(labelWithString: text)
        label.textColor = .secondaryLabelColor
        label.alignment = .right
        label.widthAnchor.constraint(equalToConstant: width).isActive = true
        return label
    }

    private func makeRow(_ views: [NSView]) -> NSStackView {
        let row = NSStackView(views: views)
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 8
        return row
    }
}

@main
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var window: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let controller = MainViewController()
        let window = NSWindow(contentViewController: controller)
        window.title = "AZNovel"
        window.setContentSize(NSSize(width: 1120, height: 780))
        window.minSize = NSSize(width: 920, height: 620)
        window.styleMask = [.titled, .closable, .miniaturizable, .resizable]
        window.center()
        window.makeKeyAndOrderFront(nil)
        self.window = window
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}
