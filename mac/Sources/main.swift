// Клиент трекера в строке меню. Ходит в тот же JSON API, что и веб-морда:
// GET /api/status и четыре POST-действия. Своего состояния не держит — всё,
// что видно в меню, приехало последним ответом сервера.

import Cocoa
import ServiceManagement

let defaultServer = "http://kuzmich-serv:7777"
let refreshSeconds = 60.0

// MARK: - русские формулировки

func plural(_ n: Int, _ one: String, _ few: String, _ many: String) -> String {
    let tail = abs(n) % 100
    if (11...14).contains(tail) { return many }
    switch tail % 10 {
    case 1: return one
    case 2...4: return few
    default: return many
    }
}

func days(_ n: Int) -> String { "\(n) \(plural(n, "день", "дня", "дней"))" }
func weeks(_ n: Int) -> String { "\(n) \(plural(n, "неделя", "недели", "недель"))" }

let months = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]

func ruDate(_ iso: String) -> String {
    let parts = iso.split(separator: "-")
    guard parts.count == 3, let m = Int(parts[1]), let d = Int(parts[2]),
          (1...12).contains(m) else { return iso }
    return "\(d) \(months[m - 1])"
}

// MARK: - то, что показываем

struct Snapshot {
    var title: String           // текст рядом с иконкой в строке меню
    var lines: [String]         // неактивные строки-заголовки меню
    var mode: String            // stage | window | offline
    var canClose = false
}

func snapshot(from json: [String: Any]) -> Snapshot {
    let cycle = json["cycle_no"] as? Int ?? 0
    if (json["mode"] as? String) == "window" {
        let left = json["window_days_left"] as? Int ?? 0
        let next = json["next_stage_weeks"] as? Int ?? 0
        let no = json["next_stage_no"] as? Int ?? 0
        let total = json["stages_in_cycle"] as? Int ?? 0
        var lines = ["Окно, осталось \(days(left))",
                     "Следующий этап — \(weeks(next))"]
        if total > 0 { lines.append("Этап \(no) из \(total), цикл №\(cycle)") }
        if let ends = json["window_ends_on"] as? String {
            lines.append("Окно по \(ruDate(ends)) включительно")
        }
        return Snapshot(title: "окно \(left)д", lines: lines, mode: "window")
    }

    let passed = json["days_passed"] as? Int ?? 0
    let total = json["days_total"] as? Int ?? 0
    let canClose = json["can_close"] as? Bool ?? false
    let penalty = json["penalty_weeks"] as? Int ?? 0
    var lines = [canClose ? "Срок вышел" : "День \(passed + 1) из \(total)"]
    lines.append("Этап \(json["stage_no"] as? Int ?? 0) из \(json["stages_in_cycle"] as? Int ?? 0), цикл №\(cycle)")
    if penalty > 0 {
        lines.append("+\(weeks(penalty)) за \(plural(penalty, "срыв", "срыва", "срывов"))")
    }
    if let end = json["end_date"] as? String { lines.append("Этап до \(ruDate(end))") }
    return Snapshot(title: canClose ? "готово" : "\(passed + 1)/\(total)",
                    lines: lines, mode: "stage", canClose: canClose)
}

// MARK: - сеть

enum Answer {
    case ok([String: Any])
    case refused(String)        // 409: действие недопустимо, сервер объяснил почему
    case failed(String)
}

final class Client {
    var base: String
    /// Куда возвращать ответ. Интерфейсу нужен главный поток, `--probe`
    /// на нём же и ждёт результата, поэтому очередь задаётся снаружи.
    var queue: DispatchQueue = .main

    init(base: String) { self.base = base }

    func status(_ done: @escaping (Answer) -> Void) { send("GET", "/api/status", done) }
    func act(_ path: String, _ done: @escaping (Answer) -> Void) { send("POST", path, done) }

    private func send(_ method: String, _ path: String, _ done: @escaping (Answer) -> Void) {
        guard let url = URL(string: base + path) else {
            return done(.failed("Неверный адрес сервера"))
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 8
        URLSession.shared.dataTask(with: request) { data, response, error in
            let answer: Answer
            if let error {
                answer = .failed(error.localizedDescription)
            } else if let data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                let code = (response as? HTTPURLResponse)?.statusCode ?? 0
                answer = code == 409
                    ? .refused(json["detail"] as? String ?? "Действие сейчас недопустимо")
                    : .ok(json)
            } else {
                answer = .failed("Сервер ответил непонятно")
            }
            self.queue.async { done(answer) }
        }.resume()
    }
}

// MARK: - строка меню

final class Controller: NSObject, NSMenuDelegate {
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let menu = NSMenu()
    private let client = Client(base: UserDefaults.standard.string(forKey: "server") ?? defaultServer)
    private var snap = Snapshot(title: "…", lines: ["Нет связи с сервером"], mode: "offline")
    private var timer: Timer?

    /// Куда система кладёт иконку при первом запуске. Без этого она выбирает
    /// место сама и на ноутбуках с вырезом попадает ровно под вырез — иконка
    /// есть, а увидеть её нельзя. Ноль означает крайнее правое место.
    private static func placeOnFirstLaunch() {
        let key = "NSStatusItem Preferred Position alcodry"
        if UserDefaults.standard.object(forKey: key) == nil {
            UserDefaults.standard.set(0, forKey: key)
        }
    }

    override init() {
        Controller.placeOnFirstLaunch()
        super.init()
        item.autosaveName = "alcodry"
        item.isVisible = true
        item.button?.image = ladderIcon()
        item.button?.imagePosition = .imageLeading
        menu.delegate = self
        item.menu = menu
        redraw()
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: refreshSeconds, repeats: true) { [weak self] _ in
            self?.refresh()
        }
    }

    /// Три ступени, нарисованные как template image: система сама перекрасит
    /// их под светлую и тёмную строку меню.
    private func ladderIcon() -> NSImage {
        let size = NSSize(width: 15, height: 13)
        let image = NSImage(size: size, flipped: false) { _ in
            NSColor.black.setFill()
            for (i, height) in [4.0, 8.0, 12.0].enumerated() {
                let rect = NSRect(x: Double(i) * 5.5, y: 0.5, width: 4, height: height)
                NSBezierPath(roundedRect: rect, xRadius: 2, yRadius: 2).fill()
            }
            return true
        }
        image.isTemplate = true
        return image
    }

    // Меню перечитывает состояние в момент открытия: цифра под курсором должна
    // быть свежей, а не минутной давности.
    func menuWillOpen(_ menu: NSMenu) { refresh() }

    private func refresh() {
        client.status { [weak self] answer in
            guard let self else { return }
            switch answer {
            case .ok(let json): snap = snapshot(from: json)
            case .refused(let text), .failed(let text):
                snap = Snapshot(title: "—", lines: ["Нет связи с сервером", text], mode: "offline")
            }
            redraw()
        }
    }

    private func act(_ path: String) {
        client.act(path) { [weak self] answer in
            guard let self else { return }
            switch answer {
            case .ok(let json): snap = snapshot(from: json); redraw()
            case .refused(let text): report(text); refresh()
            case .failed(let text): report(text)
            }
        }
    }

    private func redraw() {
        item.button?.title = " " + snap.title
        menu.removeAllItems()

        for line in snap.lines {
            let entry = NSMenuItem(title: line, action: nil, keyEquivalent: "")
            entry.isEnabled = false
            menu.addItem(entry)
        }
        menu.addItem(.separator())

        switch snap.mode {
        case "stage":
            add("Сорвался", #selector(relapse))
            add("Этап закрыт", #selector(stageDone), enabled: snap.canClose)
        case "window":
            add("Выпил", #selector(windowDrink))
            add("Начать этап сейчас", #selector(windowEnd))
        default:
            add("Повторить попытку", #selector(reload))
        }

        menu.addItem(.separator())
        add("Открыть в браузере", #selector(openBrowser))
        add("Обновить", #selector(reload))
        add("Адрес сервера…", #selector(setServer))

        let login = NSMenuItem(title: "Запускать при входе",
                               action: #selector(toggleLogin), keyEquivalent: "")
        login.target = self
        login.state = SMAppService.mainApp.status == .enabled ? .on : .off
        menu.addItem(login)

        menu.addItem(.separator())
        add("Выйти", #selector(quit))
    }

    private func add(_ title: String, _ action: Selector, enabled: Bool = true) {
        let entry = NSMenuItem(title: title, action: enabled ? action : nil, keyEquivalent: "")
        entry.target = self
        entry.isEnabled = enabled
        menu.addItem(entry)
    }

    private func report(_ text: String) {
        let alert = NSAlert()
        alert.messageText = text
        alert.addButton(withTitle: "Понятно")
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
    }

    // MARK: действия

    @objc private func relapse() {
        let alert = NSAlert()
        alert.messageText = "Отметить срыв?"
        alert.informativeText = "Этап начнётся заново и станет на неделю длиннее."
        alert.addButton(withTitle: "Отметить")
        alert.addButton(withTitle: "Отмена")
        NSApp.activate(ignoringOtherApps: true)
        if alert.runModal() == .alertFirstButtonReturn { act("/api/relapse") }
    }

    @objc private func stageDone() { act("/api/stage-done") }
    @objc private func windowDrink() { act("/api/window-drink") }
    @objc private func windowEnd() { act("/api/window-end") }
    @objc private func reload() { refresh() }

    @objc private func openBrowser() {
        if let url = URL(string: client.base) { NSWorkspace.shared.open(url) }
    }

    @objc private func setServer() {
        let alert = NSAlert()
        alert.messageText = "Адрес сервера"
        alert.informativeText = "Например, \(defaultServer)"
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 280, height: 24))
        field.stringValue = client.base
        alert.accessoryView = field
        alert.addButton(withTitle: "Сохранить")
        alert.addButton(withTitle: "Отмена")
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        let value = field.stringValue.trimmingCharacters(in: .whitespaces)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard !value.isEmpty else { return }
        client.base = value
        UserDefaults.standard.set(value, forKey: "server")
        refresh()
    }

    /// Автозапуск через SMAppService: система сама поднимет приложение при входе
    /// в учётную запись. Регистрируется тот бандл, из которого запущено, поэтому
    /// приложение должно лежать там, где и останется — в «Программах».
    @objc private func toggleLogin() {
        do {
            if SMAppService.mainApp.status == .enabled {
                try SMAppService.mainApp.unregister()
            } else {
                try SMAppService.mainApp.register()
            }
        } catch {
            report("Не вышло переключить автозапуск: \(error.localizedDescription)")
        }
    }

    @objc private func quit() { NSApp.terminate(nil) }
}

// MARK: - запуск

// `--probe` печатает то, что оказалось бы в строке меню, и выходит: так работу
// клиента можно проверить из терминала, не открывая интерфейс.
if CommandLine.arguments.contains("--probe") {
    let base = CommandLine.arguments.last.flatMap { $0.hasPrefix("http") ? $0 : nil } ?? defaultServer
    let wait = DispatchSemaphore(value: 0)
    print("сервер: \(base)")
    let probe = Client(base: base)
    probe.queue = DispatchQueue.global()
    probe.status { answer in
        switch answer {
        case .ok(let json):
            let snap = snapshot(from: json)
            print("в строке меню: [лестница] \(snap.title)")
            snap.lines.forEach { print("  \($0)") }
        case .refused(let text), .failed(let text):
            print("не вышло: \(text)")
        }
        wait.signal()
    }
    _ = wait.wait(timeout: .now() + 12)
    exit(0)
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)      // без иконки в Dock, живём только в строке меню
let controller = Controller()
app.run()
