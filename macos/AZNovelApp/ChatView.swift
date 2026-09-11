import SwiftUI

struct ChatView: View {
    let project: Project
    @State private var messages: [ChatMessage] = []
    @State private var inputText: String = ""
    @State private var isLoading: Bool = false
    @State private var streamingText: String = ""
    @State private var llmService: LLMService?

    private let lineHeight: CGFloat = 22
    private let maxInputLines: Int = 6
    private let minInputLines: Int = 1
    private let inputPadding: CGFloat = 12 // top + bottom padding inside input area

    private var currentLineCount: Int {
        let lineBreaks = inputText.filter { $0 == "\n" }.count
        return max(minInputLines, min(lineBreaks + 1, maxInputLines))
    }

    private var inputHeight: CGFloat {
        CGFloat(currentLineCount) * lineHeight + inputPadding
    }

    var body: some View {
        GeometryReader { geometry in
            VStack(spacing: 0) {
                // Message list — fills remaining space above input bar
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 12) {
                            ForEach(messages) { message in
                                MessageBubbleView(message: message)
                                    .id(message.id)
                            }
                        }
                        .padding()
                    }
                    .frame(height: geometry.size.height - inputHeight - 16) // explicit height
                    .onChange(of: messages.count) { _ in
                        withAnimation {
                            proxy.scrollTo(messages.last?.id, anchor: .bottom)
                        }
                    }
                    .onChange(of: messages.last?.content) { _ in
                        withAnimation {
                            proxy.scrollTo(messages.last?.id, anchor: .bottom)
                        }
                    }
                }

                Divider()

                // Input area — pinned to bottom, 1~6 lines elastic
                HStack(alignment: .bottom, spacing: 8) {
                    TextEditor(text: $inputText)
                        .frame(height: inputHeight - inputPadding)
                        .scrollContentBackground(.hidden)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(Color(nsColor: .controlBackgroundColor))
                        .cornerRadius(8)
                        .overlay(
                            RoundedRectangle(cornerRadius: 8)
                                .stroke(Color(nsColor: .separatorColor), lineWidth: 1)
                        )
                        .font(.system(size: 14))

                    Button(action: sendMessage) {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.system(size: 24))
                            .foregroundColor(.accentColor)
                    }
                    .buttonStyle(.plain)
                    .disabled(inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isLoading)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(Color(nsColor: .windowBackgroundColor))
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
        }
        .navigationTitle(project.title)
        .onAppear {
            llmService = LLMService()
            loadHistory()
        }
    }

    // MARK: - Actions

    private func sendMessage() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }

        let userMessage = ChatMessage(role: .user, content: text)
        messages.append(userMessage)
        inputText = ""

        Task {
            await getResponse()
        }
    }

    private func getResponse() async {
        guard let service = llmService else { return }
        isLoading = true

        let assistantMessage = ChatMessage(role: .assistant, content: "")
        messages.append(assistantMessage)
        let messageIndex = messages.count - 1

        do {
            let apiMessages = messages.filter { $0.role != .toolResult }.map { msg -> [String: String] in
                ["role": msg.role.rawValue, "content": msg.content]
            }

            for try await chunk in service.streamChat(messages: apiMessages) {
                streamingText += chunk
                messages[messageIndex].content = streamingText
            }

            streamingText = ""
        } catch {
            messages[messageIndex].content = "Error: \(error.localizedDescription)"
            streamingText = ""
        }

        isLoading = false
        saveHistory()
    }

    private func loadHistory() {
        guard let history = ProjectService.shared.loadChatHistory(for: project.id) else { return }
        messages = history
    }

    private func saveHistory() {
        ProjectService.shared.saveChatHistory(messages: messages, for: project.id)
    }
}

// MARK: - Message Bubble View

struct MessageBubbleView: View {
    let message: ChatMessage

    var body: some View {
        HStack {
            if message.role == .user { Spacer() }

            VStack(alignment: message.role == .user ? .trailing : .leading, spacing: 4) {
                Text(message.content)
                    .textSelection(.enabled)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(bubbleColor)
                    .foregroundColor(message.role == .user ? .white : .primary)
                    .cornerRadius(12)

                if message.role == .assistant {
                    Text(message.content)
                        .font(.system(size: 1))
                        .foregroundColor(.clear)
                }
            }
            .frame(maxWidth: 450, alignment: message.role == .user ? .trailing : .leading)

            if message.role == .assistant { Spacer() }
        }
    }

    private var bubbleColor: Color {
        switch message.role {
        case .user:
            return Color.accentColor
        case .assistant:
            return Color(nsColor: .controlBackgroundColor)
        case .system, .toolResult:
            return Color(nsColor: .controlBackgroundColor).opacity(0.5)
        }
    }
}
