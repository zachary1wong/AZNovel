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

        return CLIConfig(
            sourceRoot: dict["SourceRoot"] as? String ?? "",
            pythonPath: dict["PythonPath"] as? String ?? fallbackPython
        )
    }
}

struct LLMProfile {
    let name: String
    let provider: String
    let model: String
    let baseURL: String
    let apiKey: String

    var menuTitle: String {
        "\(name)  ·  \(model.isEmpty ? "未设置模型" : model)"
    }

    var detail: String {
        let url = baseURL.isEmpty ? "默认端点" : baseURL
        return "\(provider.isEmpty ? "provider 未设置" : provider) / \(model.isEmpty ? "model 未设置" : model) / \(url)"
    }
}

enum ProfileLoader {
    static func loadProfiles() -> [LLMProfile] {
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

        return profiles.compactMap { item in
            guard let name = item["name"] as? String, !name.isEmpty else { return nil }
            return LLMProfile(
                name: name,
                provider: item["provider"] as? String ?? "",
                model: item["model"] as? String ?? "",
                baseURL: item["base_url"] as? String ?? "",
                apiKey: item["api_key"] as? String ?? ""
            )
        }
        .sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
    }

    static func saveProfiles(_ profiles: [LLMProfile]) throws {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let file = home.appendingPathComponent(".aznovel/llm_profiles.json")
        let payload: [String: Any] = [
            "profiles": profiles.map { profile in
                [
                    "name": profile.name,
                    "provider": profile.provider,
                    "model": profile.model,
                    "api_key": profile.apiKey,
                    "base_url": profile.baseURL
                ]
            }
        ]
        let data = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: file)
    }

    static func globalConfigSummary() -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let file = home.appendingPathComponent(".aznovel/config.json")
        guard let data = try? Data(contentsOf: file) else {
            return "全局默认配置：未找到 ~/.aznovel/config.json"
        }
        guard let config = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return "全局默认配置：~/.aznovel/config.json 无法解析"
        }

        let provider = config["provider"] as? String ?? "未设置 provider"
        let model = config["model"] as? String ?? "未设置 model"
        let url = (config["base_url"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "默认端点"
        return "全局默认配置：\(provider) / \(model) / \(url)"
    }
}

final class ProfileEditor: NSObject {
    private var profiles: [LLMProfile]
    private let popup = NSPopUpButton()
    private let nameField = NSTextField()
    private let providerPopup = NSPopUpButton()
    private let modelField = NSTextField()
    private let apiKeyField = NSSecureTextField()
    private let baseURLField = NSTextField()

    init(profiles: [LLMProfile]) {
        self.profiles = profiles
        super.init()
    }

    func runModal() -> [LLMProfile]? {
        let alert = NSAlert()
        alert.messageText = "编辑 LLM Profile"
        alert.informativeText = "保存后会写入 ~/.aznovel/llm_profiles.json，并可被 CLI 与每条流水线共同使用。"
        alert.alertStyle = .informational
        alert.addButton(withTitle: "保存")
        alert.addButton(withTitle: "删除所选")
        alert.addButton(withTitle: "取消")

        popup.target = self
        popup.action = #selector(selectionChanged)
        providerPopup.addItems(withTitles: ["openai", "anthropic"])

        rebuildPopup()
        populateFields(for: nil)

        let form = NSStackView()
        form.orientation = .vertical
        form.alignment = .width
        form.spacing = 8
        form.frame = NSRect(x: 0, y: 0, width: 520, height: 210)
        form.addArrangedSubview(row("Profile", popup))
        form.addArrangedSubview(row("名称", nameField))
        form.addArrangedSubview(row("Provider", providerPopup))
        form.addArrangedSubview(row("Model", modelField))
        form.addArrangedSubview(row("API Key", apiKeyField))
        form.addArrangedSubview(row("Base URL", baseURLField))
        alert.accessoryView = form

        let result = alert.runModal()
        if result == .alertFirstButtonReturn {
            let profile = currentFieldProfile()
            guard !profile.name.isEmpty else {
                showValidation("Profile 名称不能为空。")
                return runModal()
            }
            upsert(profile)
            return profiles
        }

        if result == .alertSecondButtonReturn {
            let index = selectedProfileIndex()
            if let index {
                profiles.remove(at: index)
                return profiles
            }
            return profiles
        }

        return nil
    }

    @objc private func selectionChanged() {
        populateFields(for: selectedProfileIndex())
    }

    private func rebuildPopup() {
        popup.removeAllItems()
        popup.addItem(withTitle: "新建 profile")
        if !profiles.isEmpty {
            popup.menu?.addItem(.separator())
            profiles.forEach { popup.addItem(withTitle: $0.menuTitle) }
        }
        popup.selectItem(at: 0)
    }

    private func populateFields(for index: Int?) {
        guard let index, profiles.indices.contains(index) else {
            nameField.stringValue = ""
            providerPopup.selectItem(withTitle: "openai")
            modelField.stringValue = "gpt-4o"
            apiKeyField.stringValue = ""
            baseURLField.stringValue = ""
            return
        }

        let profile = profiles[index]
        nameField.stringValue = profile.name
        providerPopup.selectItem(withTitle: profile.provider.isEmpty ? "openai" : profile.provider)
        modelField.stringValue = profile.model
        apiKeyField.stringValue = profile.apiKey
        baseURLField.stringValue = profile.baseURL
    }

    private func selectedProfileIndex() -> Int? {
        let index = popup.indexOfSelectedItem
        guard index >= 2 else { return nil }
        let profileIndex = index - 2
        return profiles.indices.contains(profileIndex) ? profileIndex : nil
    }

    private func currentFieldProfile() -> LLMProfile {
        LLMProfile(
            name: nameField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines),
            provider: providerPopup.titleOfSelectedItem ?? "openai",
            model: modelField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines),
            baseURL: baseURLField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines),
            apiKey: apiKeyField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        )
    }

    private func upsert(_ profile: LLMProfile) {
        if let index = profiles.firstIndex(where: { $0.name == profile.name }) {
            profiles[index] = profile
        } else {
            profiles.append(profile)
        }
        profiles.sort { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
    }

    private func row(_ label: String, _ field: NSView) -> NSView {
        let title = NSTextField(labelWithString: label)
        title.alignment = .right
        title.textColor = .secondaryLabelColor
        title.widthAnchor.constraint(equalToConstant: 78).isActive = true
        let row = NSStackView(views: [title, field])
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 8
        return row
    }

    private func showValidation(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "无法保存"
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.runModal()
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

final class FlippedView: NSView {
    override var isFlipped: Bool { true }
}

final class FlippedClipView: NSClipView {
    override var isFlipped: Bool { true }
}

final class ChatInputTextView: NSTextView {
    var onSubmit: (() -> Void)?
    var placeholderString = "" {
        didSet { needsDisplay = true }
    }

    override var intrinsicContentSize: NSSize {
        NSSize(width: NSView.noIntrinsicMetric, height: NSView.noIntrinsicMetric)
    }

    override func keyDown(with event: NSEvent) {
        let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        let key = event.charactersIgnoringModifiers ?? ""
        if flags.contains(.command), key == "\r" || key == "\n" {
            onSubmit?()
            return
        }
        super.keyDown(with: event)
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        guard string.isEmpty, !placeholderString.isEmpty else { return }

        let attributes: [NSAttributedString.Key: Any] = [
            .font: font ?? NSFont.systemFont(ofSize: 12),
            .foregroundColor: NSColor.placeholderTextColor
        ]
        let point = NSPoint(x: textContainerInset.width + 2, y: textContainerInset.height)
        placeholderString.draw(at: point, withAttributes: attributes)
    }
}

final class MainViewController: NSViewController {
    private let cliConfig = CLIConfig.bundled()
    private let lanesStack = NSStackView()
    private let lanesDocumentView = NSView()
    private let scrollView = NSScrollView()
    private let profileSummary = NSTextField(labelWithString: "")

    private var profiles: [LLMProfile] = []
    private var lanes: [NovelLaneView] = []
    private var nextLaneNumber = 1
    private var lanesDocumentWidthConstraint: NSLayoutConstraint?

    override func loadView() {
        view = NSView(frame: NSRect(x: 0, y: 0, width: 900, height: 720))
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        setupLayout()
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        refreshProfiles()
        addLane()
        DispatchQueue.main.async { [weak self] in
            self?.updateLaneWidths()
        }
    }

    override func viewDidLayout() {
        super.viewDidLayout()
        updateLaneWidths()
    }

    private func setupLayout() {
        let toolbar = makeConfigPanel()
        let lanesView = makeLaneScrollView()
        toolbar.translatesAutoresizingMaskIntoConstraints = false
        lanesView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(toolbar)
        view.addSubview(lanesView)

        NSLayoutConstraint.activate([
            toolbar.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 10),
            toolbar.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -10),
            toolbar.topAnchor.constraint(equalTo: view.topAnchor, constant: 8),

            lanesView.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 10),
            lanesView.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -10),
            lanesView.topAnchor.constraint(equalTo: toolbar.bottomAnchor, constant: 8),
            lanesView.bottomAnchor.constraint(equalTo: view.bottomAnchor, constant: -10)
        ])
    }

    private func makeConfigPanel() -> NSView {
        profileSummary.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        profileSummary.textColor = .secondaryLabelColor
        profileSummary.lineBreakMode = .byTruncatingTail
        profileSummary.maximumNumberOfLines = 1
        profileSummary.cell?.truncatesLastVisibleLine = true

        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 8

        let titleLabel = NSTextField(labelWithString: "LLM")
        titleLabel.font = .systemFont(ofSize: 12, weight: .semibold)
        titleLabel.textColor = .secondaryLabelColor

        let refreshButton = NSButton(title: "刷新", target: self, action: #selector(refreshProfiles))
        let editButton = NSButton(title: "编辑 Profile", target: self, action: #selector(editProfiles))
        let openConfigButton = NSButton(title: "配置目录", target: self, action: #selector(openConfigDirectory))
        let addButton = NSButton(title: "添加流水线", target: self, action: #selector(addLane))

        [refreshButton, editButton, openConfigButton, addButton].forEach(styleSmallButton)

        row.addArrangedSubview(titleLabel)
        row.addArrangedSubview(profileSummary)
        row.addArrangedSubview(refreshButton)
        row.addArrangedSubview(editButton)
        row.addArrangedSubview(openConfigButton)
        row.addArrangedSubview(addButton)

        profileSummary.setContentHuggingPriority(.defaultLow, for: .horizontal)
        profileSummary.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        [refreshButton, editButton, openConfigButton, addButton].forEach { button in
            button.setContentHuggingPriority(.required, for: .horizontal)
            button.setContentCompressionResistancePriority(.required, for: .horizontal)
        }
        row.heightAnchor.constraint(equalToConstant: 30).isActive = true
        return row
    }

    private func styleSmallButton(_ button: NSButton) {
        button.bezelStyle = .rounded
        button.controlSize = .small
        button.font = .systemFont(ofSize: 12)
    }

    private func makeLaneScrollView() -> NSView {
        lanesDocumentView.translatesAutoresizingMaskIntoConstraints = false
        lanesStack.orientation = .horizontal
        lanesStack.alignment = .height
        lanesStack.spacing = 12
        lanesStack.translatesAutoresizingMaskIntoConstraints = false
        lanesDocumentView.addSubview(lanesStack)

        NSLayoutConstraint.activate([
            lanesStack.leadingAnchor.constraint(equalTo: lanesDocumentView.leadingAnchor),
            lanesStack.trailingAnchor.constraint(equalTo: lanesDocumentView.trailingAnchor),
            lanesStack.topAnchor.constraint(equalTo: lanesDocumentView.topAnchor),
            lanesStack.bottomAnchor.constraint(equalTo: lanesDocumentView.bottomAnchor)
        ])

        scrollView.documentView = lanesDocumentView
        scrollView.hasHorizontalScroller = true
        scrollView.hasVerticalScroller = false
        scrollView.autohidesScrollers = false
        scrollView.borderType = .noBorder
        scrollView.drawsBackground = false
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        scrollView.setContentHuggingPriority(.defaultLow, for: .vertical)
        scrollView.setContentCompressionResistancePriority(.defaultLow, for: .vertical)

        lanesDocumentWidthConstraint = lanesDocumentView.widthAnchor.constraint(equalToConstant: 1200)
        lanesDocumentWidthConstraint?.isActive = true

        let scrollMinHeight = scrollView.heightAnchor.constraint(greaterThanOrEqualToConstant: 360)
        scrollMinHeight.priority = .defaultLow

        NSLayoutConstraint.activate([
            lanesDocumentView.leadingAnchor.constraint(equalTo: scrollView.contentView.leadingAnchor),
            lanesDocumentView.topAnchor.constraint(equalTo: scrollView.contentView.topAnchor),
            lanesDocumentView.heightAnchor.constraint(equalTo: scrollView.contentView.heightAnchor),
            scrollMinHeight
        ])

        return scrollView
    }

    @objc private func refreshProfiles() {
        profiles = ProfileLoader.loadProfiles()
        let profileLines: [String]
        if profiles.isEmpty {
            profileLines = ["profile：未发现 ~/.aznovel/llm_profiles.json；流水线仍可使用项目/全局默认配置。"]
        } else {
            profileLines = profiles.map { "profile：\($0.name) | \($0.detail)" }
        }

        profileSummary.stringValue = ([ProfileLoader.globalConfigSummary()] + profileLines).joined(separator: "    ")
        lanes.forEach { $0.updateProfiles(profiles) }
    }

    @objc private func openConfigDirectory() {
        let url = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".aznovel")
        NSWorkspace.shared.open(url)
    }

    @objc private func editProfiles() {
        let editor = ProfileEditor(profiles: profiles)
        guard let updatedProfiles = editor.runModal() else { return }
        do {
            try ProfileLoader.saveProfiles(updatedProfiles)
            refreshProfiles()
        } catch {
            showAlert("保存 LLM profiles 失败：\(error.localizedDescription)")
        }
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
        lane.heightAnchor.constraint(equalTo: lanesDocumentView.heightAnchor).isActive = true
        updateLaneWidths()
        DispatchQueue.main.async { [weak self] in
            self?.updateLaneWidths()
        }
    }

    private func removeLane(_ lane: NovelLaneView) {
        lane.stopProcess()
        lanes.removeAll { $0 === lane }
        lanesStack.removeArrangedSubview(lane)
        lane.removeFromSuperview()
        if lanes.isEmpty {
            addLane()
        }
        updateLaneWidths()
    }

    private func updateLaneWidths() {
        guard !lanes.isEmpty else { return }

        let viewportWidth = max(scrollView.contentView.bounds.width, view.bounds.width - 20, 640)
        let laneCount = lanes.count
        let visibleColumns = min(max(laneCount, 1), 3)
        let spacingTotal = CGFloat(max(visibleColumns - 1, 0)) * lanesStack.spacing
        let idealWidth = floor((viewportWidth - spacingTotal) / CGFloat(visibleColumns))
        let laneWidth = max(260, idealWidth)
        let documentWidth = max(
            viewportWidth,
            laneWidth * CGFloat(laneCount) + lanesStack.spacing * CGFloat(max(laneCount - 1, 0))
        )

        lanesDocumentWidthConstraint?.constant = documentWidth
        lanes.forEach { $0.setPreferredWidth(laneWidth) }
    }

    private func showAlert(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "AZNovel"
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.runModal()
    }
}

final class NovelLaneView: NSBox, NSTextViewDelegate {
    private let cliConfig: CLIConfig
    private let onRemove: (NovelLaneView) -> Void
    private let laneTitle: String

    private let projectField = NSTextField()
    private let profilePopup = NSPopUpButton()
    private let profileDetailLabel = NSTextField(labelWithString: "")
    private let statusLabel = NSTextField(labelWithString: "未启动")
    private let transcriptView = NSTextView()
    private let chatInput = ChatInputTextView()
    private let chatInputScroll = NSScrollView()
    private let newProjectButton = NSButton()
    private let chooseProjectButton = NSButton()
    private let openProjectButton = NSButton()
    private let startButton = NSButton()
    private let initButton = NSButton()
    private let stopButton = NSButton()
    private let sendButton = NSButton()
    private let removeButton = NSButton()
    private let bodyStack = NSStackView()
    private var logColumn: NSStackView!
    private var workflowPanel: NSView!

    private var profiles: [LLMProfile]
    private var process: Process?
    private var outputPipe: Pipe?
    private var inputPipe: Pipe?
    private var sessionKind = "chat"
    private var widthConstraint: NSLayoutConstraint?
    private var workflowWidthConstraint: NSLayoutConstraint?
    private var logHeightConstraint: NSLayoutConstraint?
    private var chatInputHeightConstraint: NSLayoutConstraint?
    private var showingPlaceholder = false

    init(
        laneNumber: Int,
        cliConfig: CLIConfig,
        profiles: [LLMProfile],
        onRemove: @escaping (NovelLaneView) -> Void
    ) {
        self.cliConfig = cliConfig
        self.profiles = profiles
        self.onRemove = onRemove
        self.laneTitle = "流水线 \(laneNumber)"
        super.init(frame: .zero)
        title = ""
        boxType = .primary
        contentViewMargins = NSSize(width: 10, height: 8)
        translatesAutoresizingMaskIntoConstraints = false
        widthConstraint = widthAnchor.constraint(equalToConstant: 300)
        widthConstraint?.isActive = true
        setupUI()
        updateProfiles(profiles)
        showPlaceholder()
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func layout() {
        super.layout()
        DispatchQueue.main.async { [weak self] in
            self?.updateLogHeightForCurrentBounds()
            self?.updateChatInputHeight()
        }
    }

    func setPreferredWidth(_ width: CGFloat) {
        widthConstraint?.constant = width
        // 两条流水线时每列仍然足够宽，保持 log + 右侧流程；三列及更窄时改为竖排。
        let compact = width < 620

        bodyStack.orientation = compact ? .vertical : .horizontal
        bodyStack.alignment = compact ? .width : .top

        workflowWidthConstraint?.isActive = !compact
        logHeightConstraint?.constant = compact ? 220 : 320
        updateLogHeightForCurrentBounds()
        scheduleChatInputHeightUpdate()
    }

    private func updateLogHeightForCurrentBounds() {
        guard let logHeightConstraint, contentView != nil else { return }
        let compact = bodyStack.orientation == .vertical
        let reservedHeight: CGFloat = compact ? 300 : 150
        let minimumHeight: CGFloat = compact ? 220 : 320
        let target = max(minimumHeight, bounds.height - reservedHeight)
        if abs(logHeightConstraint.constant - target) > 2 {
            logHeightConstraint.constant = target
        }
    }

    private func chatInputLineHeight() -> CGFloat {
        let font = chatInput.font ?? NSFont.systemFont(ofSize: 12)
        return ceil(font.ascender - font.descender + font.leading)
    }

    private func chatInputMinimumHeight() -> CGFloat {
        chatInputLineHeight() + chatInput.textContainerInset.height * 2 + 8
    }

    private func chatInputMaximumHeight() -> CGFloat {
        chatInputLineHeight() * 6 + chatInput.textContainerInset.height * 2 + 8
    }

    private func scheduleChatInputHeightUpdate() {
        DispatchQueue.main.async { [weak self] in
            self?.updateChatInputHeight()
        }
    }

    private func updateChatInputHeight() {
        guard let chatInputHeightConstraint else { return }

        let font = chatInput.font ?? NSFont.systemFont(ofSize: 12)
        let measureWidth = max(
            120,
            chatInputScroll.contentSize.width - chatInput.textContainerInset.width * 2 - 12
        )
        let normalizedText = chatInput.string
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
        let measureText = normalizedText.isEmpty ? " " : normalizedText
        let measuredRect = (measureText as NSString).boundingRect(
            with: NSSize(width: measureWidth, height: CGFloat.greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            attributes: [.font: font]
        )
        let explicitLineCount = max(
            1,
            normalizedText.components(separatedBy: "\n").count
        )
        let contentHeight = max(
            ceil(measuredRect.height),
            CGFloat(explicitLineCount) * chatInputLineHeight()
        )
        let rawHeight = ceil(contentHeight + chatInput.textContainerInset.height * 2 + 8)

        let target = min(
            chatInputMaximumHeight(),
            max(chatInputMinimumHeight(), rawHeight)
        )
        if abs(chatInputHeightConstraint.constant - target) > 1 {
            chatInputHeightConstraint.constant = target
        }
        chatInputScroll.hasVerticalScroller = rawHeight > chatInputMaximumHeight()
        chatInputScroll.needsLayout = true
        chatInput.scrollRangeToVisible(NSRange(location: (chatInput.string as NSString).length, length: 0))
    }

    private func setupUI() {
        guard let contentView else { return }

        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .width
        root.spacing = 6
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
        projectField.setContentHuggingPriority(.defaultLow, for: .horizontal)
        projectField.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)

        let headerLabel = NSTextField(labelWithString: laneTitle)
        headerLabel.font = .systemFont(ofSize: 13, weight: .semibold)

        statusLabel.font = .systemFont(ofSize: 12)
        statusLabel.textColor = .secondaryLabelColor

        removeButton.title = "关闭"
        removeButton.target = self
        removeButton.action = #selector(removeLane)
        styleSmallButton(removeButton)
        removeButton.toolTip = "关闭这条流水线；如果正在运行，会先停止 CLI 会话"

        root.addArrangedSubview(makeRow([
            headerLabel,
            makeSpacer(),
            makeStatusPill(),
            removeButton
        ]))

        newProjectButton.title = "新建项目"
        newProjectButton.target = self
        newProjectButton.action = #selector(createNewProject)
        styleSmallButton(newProjectButton)
        newProjectButton.toolTip = "创建一个新的 AZNovel 项目目录，并启动方向定义流程"

        chooseProjectButton.title = "选择"
        chooseProjectButton.target = self
        chooseProjectButton.action = #selector(chooseProjectDirectory)
        styleSmallButton(chooseProjectButton)
        chooseProjectButton.toolTip = "选择已有 AZNovel 小说项目目录"

        openProjectButton.title = "打开"
        openProjectButton.target = self
        openProjectButton.action = #selector(openProjectDirectory)
        styleSmallButton(openProjectButton)
        openProjectButton.toolTip = "在 Finder 中打开当前项目目录"

        root.addArrangedSubview(makeRow([
            makeLabel("项目", width: 46),
            projectField,
            newProjectButton,
            chooseProjectButton,
            openProjectButton
        ]))

        profilePopup.target = self
        profilePopup.action = #selector(profileChanged)
        profilePopup.widthAnchor.constraint(greaterThanOrEqualToConstant: 140).isActive = true
        profilePopup.widthAnchor.constraint(lessThanOrEqualToConstant: 280).isActive = true
        profilePopup.setContentHuggingPriority(.defaultLow, for: .horizontal)
        profilePopup.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)

        startButton.title = "聊天"
        startButton.toolTip = "启动这条流水线的 chat 会话"
        startButton.target = self
        startButton.action = #selector(startChatSession)
        styleSmallButton(startButton)

        initButton.title = "方向"
        initButton.toolTip = "进入方向和参数定义阶段"
        initButton.target = self
        initButton.action = #selector(startInitSession)
        styleSmallButton(initButton)

        stopButton.title = "停"
        stopButton.toolTip = "停止这条流水线"
        stopButton.target = self
        stopButton.action = #selector(stopProcessAction)
        styleSmallButton(stopButton)
        stopButton.isEnabled = false

        profileDetailLabel.font = .systemFont(ofSize: 11)
        profileDetailLabel.textColor = .secondaryLabelColor
        profileDetailLabel.lineBreakMode = .byTruncatingTail
        profileDetailLabel.maximumNumberOfLines = 1
        profileDetailLabel.cell?.truncatesLastVisibleLine = true
        profileDetailLabel.setContentHuggingPriority(.defaultLow, for: .horizontal)
        profileDetailLabel.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)

        root.addArrangedSubview(makeRow([
            makeLabel("LLM", width: 46),
            profilePopup,
            profileDetailLabel,
            makeSpacer(),
            initButton,
            startButton,
            stopButton
        ]))

        let logScroll = NSScrollView()
        logScroll.hasVerticalScroller = true
        logScroll.borderType = .bezelBorder
        logScroll.drawsBackground = true
        logScroll.backgroundColor = .textBackgroundColor
        logScroll.setContentHuggingPriority(.defaultLow, for: .vertical)
        logScroll.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        logHeightConstraint = logScroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 320)
        logHeightConstraint?.isActive = true

        transcriptView.isEditable = false
        transcriptView.isSelectable = true
        transcriptView.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        transcriptView.textContainerInset = NSSize(width: 8, height: 8)
        transcriptView.backgroundColor = .textBackgroundColor
        transcriptView.isHorizontallyResizable = false
        transcriptView.isVerticallyResizable = true
        transcriptView.autoresizingMask = [.width]
        transcriptView.textContainer?.widthTracksTextView = true
        transcriptView.textContainer?.containerSize = NSSize(
            width: logScroll.contentSize.width,
            height: CGFloat.greatestFiniteMagnitude
        )
        logScroll.documentView = transcriptView

        chatInput.placeholderString = "输入自然语言指令；Return 换行，Command+Return 发送"
        chatInput.delegate = self
        chatInput.font = .systemFont(ofSize: 12)
        chatInput.isRichText = false
        chatInput.importsGraphics = false
        chatInput.allowsUndo = true
        chatInput.isEditable = true
        chatInput.isSelectable = true
        chatInput.drawsBackground = false
        chatInput.textContainerInset = NSSize(width: 6, height: 4)
        chatInput.isHorizontallyResizable = false
        chatInput.isVerticallyResizable = true
        chatInput.minSize = NSSize(width: 0, height: 0)
        chatInput.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        chatInput.autoresizingMask = [.width]
        chatInput.textContainer?.widthTracksTextView = true
        chatInput.onSubmit = { [weak self] in
            self?.sendChatCommand()
        }

        chatInputScroll.borderType = .bezelBorder
        chatInputScroll.drawsBackground = true
        chatInputScroll.backgroundColor = .textBackgroundColor
        chatInputScroll.hasVerticalScroller = false
        chatInputScroll.autohidesScrollers = true
        chatInputScroll.documentView = chatInput
        chatInputScroll.setContentHuggingPriority(.defaultLow, for: .horizontal)
        chatInputScroll.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        chatInputScroll.setContentHuggingPriority(.required, for: .vertical)
        chatInputScroll.setContentCompressionResistancePriority(.required, for: .vertical)
        chatInputHeightConstraint = chatInputScroll.heightAnchor.constraint(equalToConstant: chatInputMinimumHeight())
        chatInputHeightConstraint?.priority = .required
        chatInputHeightConstraint?.isActive = true
        chatInputScroll.heightAnchor.constraint(greaterThanOrEqualToConstant: chatInputMinimumHeight()).isActive = true
        chatInputScroll.heightAnchor.constraint(lessThanOrEqualToConstant: chatInputMaximumHeight()).isActive = true

        sendButton.title = "发送"
        sendButton.target = self
        sendButton.action = #selector(sendChatCommand)
        styleSmallButton(sendButton)

        let clearButton = NSButton(title: "清空", target: self, action: #selector(clearLog))
        styleSmallButton(clearButton)

        logColumn = NSStackView()
        logColumn.orientation = .vertical
        logColumn.alignment = .width
        logColumn.spacing = 6
        logColumn.setContentHuggingPriority(.defaultLow, for: .vertical)
        logColumn.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        logColumn.addArrangedSubview(logScroll)
        logColumn.addArrangedSubview(makeRow([chatInputScroll, sendButton, clearButton]))

        workflowPanel = makeWorkflowPanel()
        workflowWidthConstraint = workflowPanel.widthAnchor.constraint(equalToConstant: 88)
        workflowWidthConstraint?.isActive = true

        bodyStack.orientation = .horizontal
        bodyStack.alignment = .top
        bodyStack.spacing = 8
        bodyStack.setContentHuggingPriority(.defaultLow, for: .vertical)
        bodyStack.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        bodyStack.addArrangedSubview(logColumn)
        bodyStack.addArrangedSubview(workflowPanel)
        root.addArrangedSubview(bodyStack)
    }

    private func makeWorkflowPanel() -> NSView {
        let box = NSBox()
        box.title = "阶段流程"
        box.boxType = .primary
        box.contentViewMargins = NSSize(width: 6, height: 6)

        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 5
        stack.translatesAutoresizingMaskIntoConstraints = false

        stack.addArrangedSubview(makeButtonRow("1 方向参数", [
            ("方向定义", #selector(startInitSession)),
            ("项目状态", #selector(sendStatusCommand)),
            ("梳理参数", #selector(sendDirectionCommand))
        ]))
        stack.addArrangedSubview(makeButtonRow("2 大纲迭代", [
            ("生成大纲", #selector(sendGenerateOutlineCommand)),
            ("修改大纲", #selector(sendReviseOutlineCommand)),
            ("查看大纲", #selector(sendShowOutlineCommand))
        ]))
        stack.addArrangedSubview(makeButtonRow("3 逐章写作", [
            ("下一章", #selector(sendNextChapterCommand)),
            ("连写3章", #selector(sendBatchCommand)),
            ("重写某章", #selector(sendRewriteChapterCommand))
        ]))
        stack.addArrangedSubview(makeButtonRow("4 校验精修", [
            ("审查最新", #selector(sendReviewLatestCommand)),
            ("安全修复", #selector(sendSafeRepairCommand)),
            ("终稿精修", #selector(sendFinalPolishCommand))
        ]))
        stack.addArrangedSubview(makeButtonRow("5 产出", [
            ("EPUB", #selector(sendExportEPUBCommand)),
            ("多格式", #selector(sendExportAllCommand)),
            ("角色改名", #selector(sendRenameCharacterCommand))
        ]))

        if let contentView = box.contentView {
            contentView.addSubview(stack)
            NSLayoutConstraint.activate([
                stack.leadingAnchor.constraint(equalTo: contentView.leadingAnchor),
                stack.trailingAnchor.constraint(lessThanOrEqualTo: contentView.trailingAnchor),
                stack.topAnchor.constraint(equalTo: contentView.topAnchor),
                stack.bottomAnchor.constraint(lessThanOrEqualTo: contentView.bottomAnchor)
            ])
        }

        return box
    }

    private func makeButtonRow(_ label: String, _ buttons: [(String, Selector)]) -> NSView {
        let titleLabel = NSTextField(labelWithString: label)
        titleLabel.font = .systemFont(ofSize: 11, weight: .semibold)
        titleLabel.textColor = .secondaryLabelColor

        let buttonViews: [NSView] = buttons.map { title, selector in
            let button = NSButton(title: title, target: self, action: selector)
            styleSmallButton(button)
            button.controlSize = .mini
            button.font = .systemFont(ofSize: 11)
            button.alignment = .left
            button.setContentHuggingPriority(.required, for: .horizontal)
            button.setContentCompressionResistancePriority(.required, for: .horizontal)
            return button
        }

        let stack = NSStackView(views: [titleLabel] + buttonViews)
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 3
        return stack
    }

    func updateProfiles(_ profiles: [LLMProfile]) {
        let previousName = selectedProfile()?.name
        self.profiles = profiles
        profilePopup.removeAllItems()
        profilePopup.addItem(withTitle: "使用项目/全局默认配置")
        if !profiles.isEmpty {
            profilePopup.menu?.addItem(.separator())
            profiles.forEach { profilePopup.addItem(withTitle: $0.menuTitle) }
        }

        if let previousName, let index = profiles.firstIndex(where: { $0.name == previousName }) {
            profilePopup.selectItem(at: index + 2)
        } else {
            profilePopup.selectItem(at: 0)
        }
        updateProfileDetail()
    }

    @objc private func profileChanged() {
        updateProfileDetail()
    }

    private func updateProfileDetail() {
        if let profile = selectedProfile() {
            profileDetailLabel.stringValue = profile.detail
        } else {
            profileDetailLabel.stringValue = "使用 CLI 默认解析：项目 .aznovel/config.json 覆盖 ~/.aznovel/config.json"
        }
        profileDetailLabel.toolTip = profileDetailLabel.stringValue
    }

    @objc private func createNewProject() {
        guard process == nil else {
            showAlert("当前流水线正在运行。请先停止会话，再新建小说项目。")
            return
        }

        let typedPath = projectField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if !typedPath.isEmpty {
            createProjectDirectoryAndStartInit(URL(fileURLWithPath: typedPath))
            return
        }

        let panel = NSSavePanel()
        panel.title = "新建小说项目"
        panel.message = "选择要创建的新项目目录。创建后会自动进入方向定义流程。"
        panel.prompt = "创建并开始"
        panel.nameFieldLabel = "项目目录"
        panel.nameFieldStringValue = "未命名小说"
        panel.canCreateDirectories = true
        panel.showsTagField = false

        if !projectField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            panel.directoryURL = URL(fileURLWithPath: projectField.stringValue).deletingLastPathComponent()
        }

        guard panel.runModal() == .OK, let url = panel.url else { return }
        createProjectDirectoryAndStartInit(url)
    }

    private func createProjectDirectoryAndStartInit(_ url: URL) {
        do {
            if FileManager.default.fileExists(atPath: url.path) {
                let contents = (try? FileManager.default.contentsOfDirectory(atPath: url.path)) ?? []
                if !contents.isEmpty {
                    guard confirm(
                        title: "目录不为空",
                        message: "这个目录已经有内容。仍然把它作为 AZNovel 项目目录并启动初始化吗？"
                    ) else { return }
                }
            } else {
                try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
            }
            projectField.stringValue = url.path
            clearPlaceholderIfNeeded()
            appendTranscript("[GUI] 新建小说项目目录：\(url.path)\n")
            startInitSession()
        } catch {
            showAlert("创建项目目录失败：\(error.localizedDescription)")
        }
    }

    @objc private func chooseProjectDirectory() {
        guard process == nil else {
            showAlert("当前流水线正在运行。请先停止会话，再切换小说项目目录。")
            return
        }

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

    @objc private func removeLane() {
        if process != nil {
            guard confirm(
                title: "关闭流水线",
                message: "这条流水线正在运行。关闭会先停止当前 CLI 会话。"
            ) else { return }
        }
        onRemove(self)
    }

    @objc private func startChatSession() {
        launchChatSession(initialCommand: nil)
    }

    @objc private func startInitSession() {
        launchInteractiveSession(command: "init", initialCommand: nil)
    }

    private func launchChatSession(initialCommand: String?) {
        launchInteractiveSession(command: "chat", initialCommand: initialCommand)
    }

    private func launchInteractiveSession(command: String, initialCommand: String?) {
        guard process == nil else {
            if let initialCommand {
                sendLine(initialCommand)
            }
            return
        }

        let projectPath = projectField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !projectPath.isEmpty else {
            showAlert("请选择小说项目目录。")
            return
        }
        guard FileManager.default.fileExists(atPath: projectPath) else {
            showAlert("目录不存在：\(projectPath)")
            return
        }

        var args = ["-m", "aznovel"]
        if let profile = selectedProfile() {
            args.append(contentsOf: ["--profile", profile.name])
        }
        args.append(command)

        let process = Process()
        process.executableURL = URL(fileURLWithPath: cliConfig.pythonPath)
        process.arguments = args
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

        let outputPipe = Pipe()
        let inputPipe = Pipe()
        process.standardOutput = outputPipe
        process.standardError = outputPipe
        process.standardInput = inputPipe

        outputPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            DispatchQueue.main.async {
                self?.appendTranscript(stripANSIEscapes(text.replacingOccurrences(of: "\r", with: "\n")))
            }
        }

        process.terminationHandler = { [weak self] finished in
            DispatchQueue.main.async {
                self?.processDidExit(finished.terminationStatus)
            }
        }

        do {
            clearPlaceholderIfNeeded()
            appendTranscript("$ \(shellDisplay([cliConfig.pythonPath] + args))\n")
            try process.run()
            self.process = process
            self.outputPipe = outputPipe
            self.inputPipe = inputPipe
            sessionKind = command
            setRunning(true)
            if let initialCommand {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
                    self?.sendLine(initialCommand)
                }
            }
        } catch {
            outputPipe.fileHandleForReading.readabilityHandler = nil
            showAlert("启动 \(command) 失败：\(error.localizedDescription)")
        }
    }

    @objc private func stopProcessAction() {
        stopProcess()
    }

    func stopProcess() {
        guard let process else { return }
        appendTranscript("\n[GUI] 停止流水线。\n")
        sendLine("退出")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { [weak self, process] in
            if process.isRunning {
                process.terminate()
            }
            if self?.process === process {
                self?.process = nil
            }
        }
    }

    @objc private func sendChatCommand() {
        let command = normalizedCLIInput(chatInput.string)
        guard !command.isEmpty else { return }
        chatInput.string = ""
        chatInput.needsDisplay = true
        scheduleChatInputHeightUpdate()
        if process == nil {
            launchChatSession(initialCommand: command)
        } else {
            sendLine(command)
        }
    }

    @objc private func sendStatusCommand() {
        sendPreparedCommand("显示项目状态")
    }

    @objc private func sendDirectionCommand() {
        sendPreparedCommand("请梳理这本书当前的方向和硬参数，包括题材、主角目标、核心卖点、目标章数、每章字数、当前缺失信息，并给出下一步建议。")
    }

    @objc private func sendGenerateOutlineCommand() {
        let extra = promptForText(
            title: "生成大纲",
            message: "可输入额外创作需求；留空则按当前设定生成。"
        )
        var command = "生成大纲"
        if let extra, !extra.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            command += "，要求：\(extra)"
        }
        sendPreparedCommand(command)
    }

    @objc private func sendReviseOutlineCommand() {
        guard let feedback = promptForText(title: "修改大纲", message: "输入修改意见。") else { return }
        let trimmed = feedback.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        sendPreparedCommand("修改大纲：\(trimmed)")
    }

    @objc private func sendShowOutlineCommand() {
        sendPreparedCommand("查看大纲")
    }

    @objc private func sendNextChapterCommand() {
        sendPreparedCommand("写下一章")
    }

    @objc private func sendBatchCommand() {
        sendPreparedCommand("连续写3章")
    }

    @objc private func sendRewriteChapterCommand() {
        guard let chapter = promptForText(title: "重写章节", message: "输入章节号。") else { return }
        let number = chapter.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !number.isEmpty else { return }
        let modification = promptForText(title: "重写章节", message: "输入重写要求。") ?? ""
        let trimmed = modification.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            sendPreparedCommand("重写第\(number)章")
        } else {
            sendPreparedCommand("重写第\(number)章，要求：\(trimmed)")
        }
    }

    @objc private func sendReviewLatestCommand() {
        sendPreparedCommand("审查最新一章")
    }

    @objc private func sendSafeRepairCommand() {
        sendPreparedCommand("最终安全修复全书硬逻辑问题")
    }

    @objc private func sendFinalPolishCommand() {
        sendPreparedCommand("终稿精修全书")
    }

    @objc private func sendExportEPUBCommand() {
        sendPreparedCommand("导出全书为 epub")
    }

    @objc private func sendExportAllCommand() {
        sendPreparedCommand("导出全书为 epub,pdf,docx")
    }

    @objc private func sendRenameCharacterCommand() {
        guard let oldName = promptForText(title: "角色改名", message: "输入旧角色名。") else { return }
        let oldTrimmed = oldName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !oldTrimmed.isEmpty else { return }

        guard let newName = promptForText(title: "角色改名", message: "输入新角色名。") else { return }
        let newTrimmed = newName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !newTrimmed.isEmpty else { return }

        let aliases = promptForText(title: "角色改名", message: "可输入称谓映射，例如 小禾=小森,禾禾=森森；留空跳过。") ?? ""
        let aliasTrimmed = aliases.trimmingCharacters(in: .whitespacesAndNewlines)
        if aliasTrimmed.isEmpty {
            sendPreparedCommand("把角色\(oldTrimmed)改名为\(newTrimmed)，同步正文、大纲、设定和审查报告")
        } else {
            sendPreparedCommand("把角色\(oldTrimmed)改名为\(newTrimmed)，称谓映射：\(aliasTrimmed)，同步正文、大纲、设定和审查报告")
        }
    }

    private func sendPreparedCommand(_ command: String) {
        if process == nil {
            launchChatSession(initialCommand: command)
        } else {
            sendLine(command)
        }
    }

    private func normalizedCLIInput(_ value: String) -> String {
        let normalizedNewlines = value
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)

        guard normalizedNewlines.contains("\n") else {
            return normalizedNewlines
        }

        return normalizedNewlines
            .components(separatedBy: "\n")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .joined(separator: " \\n ")
    }

    private func sendLine(_ line: String) {
        guard let inputPipe else { return }
        let cliLine = normalizedCLIInput(line)
        guard !cliLine.isEmpty else { return }
        clearPlaceholderIfNeeded()
        appendTranscript("\n你 > \(cliLine)\n")
        if let data = "\(cliLine)\n".data(using: .utf8) {
            inputPipe.fileHandleForWriting.write(data)
        }
    }

    func textDidChange(_ notification: Notification) {
        guard let textView = notification.object as? NSTextView, textView === chatInput else { return }
        chatInput.needsDisplay = true
        chatInput.invalidateIntrinsicContentSize()
        scheduleChatInputHeightUpdate()
    }

    @objc private func clearLog() {
        showPlaceholder()
    }

    private func processDidExit(_ status: Int32) {
        outputPipe?.fileHandleForReading.readabilityHandler = nil
        outputPipe = nil
        inputPipe = nil
        process = nil
        setRunning(false)
        appendTranscript("\n[GUI] 流水线结束，退出码：\(status)\n")
    }

    private func setRunning(_ running: Bool) {
        if running {
            statusLabel.stringValue = sessionKind == "init" ? "方向定义运行中" : "聊天运行中"
        } else {
            statusLabel.stringValue = "未启动"
        }
        statusLabel.textColor = running ? .systemGreen : .secondaryLabelColor
        startButton.isEnabled = !running
        stopButton.isEnabled = running
        removeButton.isEnabled = true
        sendButton.isEnabled = true
        profilePopup.isEnabled = !running
        projectField.isEnabled = !running
        newProjectButton.isEnabled = !running
        chooseProjectButton.isEnabled = !running
        openProjectButton.isEnabled = true
    }

    private func appendTranscript(_ text: String) {
        clearPlaceholderIfNeeded()
        guard let storage = transcriptView.textStorage else { return }
        storage.append(NSAttributedString(
            string: text,
            attributes: [
                .font: NSFont.monospacedSystemFont(ofSize: 12, weight: .regular),
                .foregroundColor: NSColor.textColor
            ]
        ))
        DispatchQueue.main.async { [weak self] in
            self?.scrollTranscriptToBottom()
        }
    }

    private func scrollTranscriptToBottom() {
        let length = (transcriptView.string as NSString).length
        guard length > 0 else { return }

        transcriptView.scrollRangeToVisible(NSRange(location: length, length: 0))
        guard let scrollView = transcriptView.enclosingScrollView else { return }
        var usedTextHeight: CGFloat = 0
        if let layoutManager = transcriptView.layoutManager, let textContainer = transcriptView.textContainer {
            layoutManager.ensureLayout(for: textContainer)
            usedTextHeight = layoutManager.usedRect(for: textContainer).height
        }
        let contentHeight = max(
            scrollView.documentView?.bounds.height ?? 0,
            usedTextHeight
        )
        let visibleHeight = scrollView.contentView.bounds.height
        let target = NSPoint(x: 0, y: max(0, contentHeight - visibleHeight))
        scrollView.contentView.scroll(to: target)
        scrollView.reflectScrolledClipView(scrollView.contentView)
    }

    private func showPlaceholder() {
        showingPlaceholder = true
        let text = [
            "等待启动 chat 会话。",
            "",
            "1. 新建小说项目，或选择已有 AZNovel 小说项目目录。",
            "2. 选择这条流水线使用的 LLM profile，或使用项目/全局默认配置。",
            "3. 新项目会自动进入方向定义；已有项目可点“方向”或“聊天”。",
            "4. 后续可用阶段按钮或自然语言输入继续指挥同一个 chat 会话。",
            "",
            "示例：写下一章 / 连续写3章 / 审查最新一章 / 导出全书为 epub,pdf,docx"
        ].joined(separator: "\n")
        transcriptView.string = text
        let range = NSRange(location: 0, length: (text as NSString).length)
        transcriptView.textStorage?.setAttributes(
            [
                .font: NSFont.monospacedSystemFont(ofSize: 12, weight: .regular),
                .foregroundColor: NSColor.secondaryLabelColor
            ],
            range: range
        )
    }

    private func clearPlaceholderIfNeeded() {
        if showingPlaceholder {
            transcriptView.string = ""
            showingPlaceholder = false
        }
    }

    private func selectedProfile() -> LLMProfile? {
        let index = profilePopup.indexOfSelectedItem
        guard index >= 2 else { return nil }
        let profileIndex = index - 2
        guard profiles.indices.contains(profileIndex) else { return nil }
        return profiles[profileIndex]
    }

    private func showAlert(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "AZNovel"
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.runModal()
    }

    private func confirm(title: String, message: String) -> Bool {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.addButton(withTitle: "继续")
        alert.addButton(withTitle: "取消")
        return alert.runModal() == .alertFirstButtonReturn
    }

    private func promptForText(title: String, message: String) -> String? {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.alertStyle = .informational
        alert.addButton(withTitle: "确定")
        alert.addButton(withTitle: "取消")

        let input = NSTextField(frame: NSRect(x: 0, y: 0, width: 420, height: 24))
        alert.accessoryView = input
        let response = alert.runModal()
        guard response == .alertFirstButtonReturn else { return nil }
        return input.stringValue
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

    private func makeSpacer() -> NSView {
        let spacer = NSView()
        spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        spacer.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return spacer
    }

    private func makeStatusPill() -> NSTextField {
        statusLabel.alignment = .right
        statusLabel.setContentHuggingPriority(.required, for: .horizontal)
        statusLabel.setContentCompressionResistancePriority(.required, for: .horizontal)
        return statusLabel
    }

    private func styleSmallButton(_ button: NSButton) {
        button.bezelStyle = .rounded
        button.controlSize = .small
        button.font = .systemFont(ofSize: 12)
    }

    private func makeSectionTitle(_ text: String) -> NSTextField {
        let label = NSTextField(labelWithString: text)
        label.font = .systemFont(ofSize: 11, weight: .semibold)
        label.textColor = .secondaryLabelColor
        return label
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var window: NSWindow?
    private var keyMonitor: Any?

    func applicationDidFinishLaunching(_ notification: Notification) {
        UserDefaults.standard.set(true, forKey: "ApplePersistenceIgnoreState")
        setupMainMenu()
        installTextInputShortcutFallbacks()
        showMainWindow()
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let keyMonitor {
            NSEvent.removeMonitor(keyMonitor)
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showMainWindow()
        return true
    }

    @objc private func showMainWindowAction(_ sender: Any?) {
        showMainWindow()
    }

    private func showMainWindow() {
        if let window {
            updateWindowSizeLimits(window)
            moveBackOnScreenIfNeeded(window)
            if window.isVisible || window.isMiniaturized {
                if window.isMiniaturized {
                    window.deminiaturize(nil)
                }
                window.makeKeyAndOrderFront(nil)
                window.orderFrontRegardless()
                NSApp.unhide(nil)
                NSApp.activate(ignoringOtherApps: true)
                return
            }
            self.window = nil
        }

        let controller = MainViewController()
        let frame = preferredWindowFrame()
        let window = NSWindow(
            contentRect: frame,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "AZNovel"
        window.contentViewController = controller
        window.minSize = preferredMinimumSize()
        window.maxSize = preferredMaximumSize()
        window.setFrame(frame, display: false, animate: false)
        window.isRestorable = false
        window.isReleasedWhenClosed = false
        window.isOpaque = true
        window.backgroundColor = .windowBackgroundColor
        window.collectionBehavior = [.managed]
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
        self.window = window
        NSApp.unhide(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func updateWindowSizeLimits(_ window: NSWindow) {
        window.minSize = preferredMinimumSize()
        window.maxSize = preferredMaximumSize()
    }

    private func moveBackOnScreenIfNeeded(_ window: NSWindow) {
        let visible = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1200, height: 800)
        guard !visible.intersects(window.frame) else { return }
        window.setFrame(preferredWindowFrame(), display: true, animate: false)
    }

    private func preferredWindowFrame() -> NSRect {
        let visible = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1200, height: 800)
        // 默认打开为“最大化但非全屏”：保留一点边距和系统菜单栏/Dock 空间。
        let horizontalInset: CGFloat = 8
        let verticalInset: CGFloat = 8
        let width = max(640, visible.width - horizontalInset * 2)
        let height = max(480, visible.height - verticalInset * 2)
        return NSRect(
            x: visible.midX - width / 2,
            y: visible.midY - height / 2,
            width: width,
            height: height
        )
    }

    private func preferredMinimumSize() -> NSSize {
        let visible = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1200, height: 800)
        return NSSize(
            width: min(640, max(visible.width - 360, 540)),
            height: min(480, max(visible.height - 280, 420))
        )
    }

    private func preferredMaximumSize() -> NSSize {
        let visible = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1200, height: 800)
        // 允许用户拖到屏幕可见区边缘（保留 4pt 边距，避免贴边），但不进入全屏模式
        return NSSize(
            width: visible.width - 4,
            height: visible.height - 4
        )
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    private func installTextInputShortcutFallbacks() {
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
            guard flags.contains(.command), event.charactersIgnoringModifiers?.lowercased() == "v" else {
                return event
            }

            return self?.pasteIntoCurrentTextInput() == true ? nil : event
        }
    }

    private func pasteIntoCurrentTextInput() -> Bool {
        guard
            let text = NSPasteboard.general.string(forType: .string),
            !text.isEmpty,
            let textView = NSApp.keyWindow?.firstResponder as? NSTextView,
            textView.isEditable
        else {
            return false
        }

        textView.insertText(text, replacementRange: textView.selectedRange())
        return true
    }

    private func setupMainMenu() {
        let mainMenu = NSMenu()

        let appMenuItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(
            withTitle: "关于 AZNovel",
            action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)),
            keyEquivalent: ""
        )
        appMenu.addItem(.separator())
        appMenu.addItem(
            withTitle: "退出 AZNovel",
            action: #selector(NSApplication.terminate(_:)),
            keyEquivalent: "q"
        )
        appMenuItem.submenu = appMenu
        mainMenu.addItem(appMenuItem)

        let editMenuItem = NSMenuItem()
        let editMenu = NSMenu(title: "编辑")
        editMenu.addItem(
            withTitle: "撤销",
            action: Selector(("undo:")),
            keyEquivalent: "z"
        )
        editMenu.addItem(
            withTitle: "重做",
            action: Selector(("redo:")),
            keyEquivalent: "Z"
        )
        editMenu.addItem(.separator())
        editMenu.addItem(
            withTitle: "剪切",
            action: #selector(NSText.cut(_:)),
            keyEquivalent: "x"
        )
        editMenu.addItem(
            withTitle: "复制",
            action: #selector(NSText.copy(_:)),
            keyEquivalent: "c"
        )
        editMenu.addItem(
            withTitle: "粘贴",
            action: #selector(NSText.paste(_:)),
            keyEquivalent: "v"
        )
        editMenu.addItem(
            withTitle: "粘贴并匹配样式",
            action: #selector(NSTextView.pasteAsPlainText(_:)),
            keyEquivalent: "V"
        )
        editMenu.addItem(.separator())
        editMenu.addItem(
            withTitle: "全选",
            action: #selector(NSStandardKeyBindingResponding.selectAll(_:)),
            keyEquivalent: "a"
        )
        editMenuItem.submenu = editMenu
        mainMenu.addItem(editMenuItem)

        let windowMenuItem = NSMenuItem()
        let windowMenu = NSMenu(title: "窗口")
        let showItem = windowMenu.addItem(
            withTitle: "显示主窗口",
            action: #selector(showMainWindowAction(_:)),
            keyEquivalent: "0"
        )
        showItem.target = self
        windowMenu.addItem(.separator())
        windowMenu.addItem(
            withTitle: "最小化",
            action: #selector(NSWindow.miniaturize(_:)),
            keyEquivalent: "m"
        )
        windowMenuItem.submenu = windowMenu
        mainMenu.addItem(windowMenuItem)

        NSApp.mainMenu = mainMenu
        NSApp.windowsMenu = windowMenu
    }
}

private let app = NSApplication.shared
private let appDelegate = AppDelegate()
app.setActivationPolicy(.regular)
app.delegate = appDelegate
app.run()
