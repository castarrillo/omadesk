import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "local.tablet-usb"
  ipcTarget: "local.tablet-usb"
  manageIpc: true
  implicitWidth: icon.implicitWidth
  implicitHeight: icon.implicitHeight
  property var info: ({})
  property var draft: ({})
  property bool initialized: false
  property bool dirty: false
  property string feedback: ""
  property bool failed: false
  property string diagnostic: ""
  property string actionVerb: ""
  readonly property string backend: (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/omarchy/plugins/local.tablet-usb/backend.py"
  readonly property color ink: Color.foreground
  readonly property color muted: Qt.rgba(ink.r, ink.g, ink.b, 0.65)
  readonly property bool busy: action.running
  readonly property bool online: !!info.connected
  readonly property string stateLabel: online ? "Imagen conectada por USB" : info.active ? "Monitor activo · esperando AVNC" : "Desconectada"

  function edit(key, value) {
    var next = Object.assign({}, draft)
    next[key] = value
    draft = next
    dirty = true
  }
  function setResolution(text) {
    var parts = text.split("×")
    var portrait = Number(draft.height) > Number(draft.width)
    edit("width", Number(parts[portrait ? 1 : 0]))
    edit("height", Number(parts[portrait ? 0 : 1]))
  }
  function orientation(value) {
    if ((value === "Vertical") !== (Number(draft.height) > Number(draft.width))) {
      var width = draft.width
      edit("width", draft.height)
      edit("height", width)
    }
  }
  function preset(name) {
    var cap = info.capabilities || {}
    var w = Math.max(cap.width || draft.width, cap.height || draft.height)
    var h = Math.min(cap.width || draft.width, cap.height || draft.height)
    var factor = Math.min(1, 4096/w, 4096/h, Math.sqrt((4096*2160)/(w*h))) * ({"Texto nítido":1,"Equilibrado":0.75,"Ligero":0.5}[name])
    w = Math.max(480, Math.floor(w * factor / 2) * 2)
    h = Math.max(480, Math.floor(h * factor / 2) * 2)
    var scale = [1.6,1.25,1].filter(s => w/s === Math.round(w/s) && h/s === Math.round(h/s))[0] || 1
    if (w <= 1920) scale = 1
    var rate = Math.min(120, cap.refresh || draft.refresh || 60)
    var values = {width:w,height:h,scale:scale,refresh:rate,fps:Math.min(rate,name === "Texto nítido" ? 60 : 30),quality:name === "Texto nítido" ? 9 : name === "Equilibrado" ? 7 : 5,compression:name === "Ligero" ? 3 : 2}
    var portrait = draft.height > draft.width
    if (portrait) { var w = values.width; values.width = values.height; values.height = w }
    draft = Object.assign({}, draft, values)
    dirty = true
  }
  function refresh() { if (!poll.running && !busy) poll.running = true }
  function send(verb) {
    if (busy || !initialized) return
    feedback = ""
    failed = false
    var args = ["/usr/bin/python", backend, verb]
    actionVerb = verb
    if (verb === "save" || verb === "apply") args.push("--settings", JSON.stringify(draft))
    action.command = args
    action.running = true
  }
  function receive(text, isAction) {
    try {
      var result = JSON.parse(text)
      if (result.error) { feedback = result.error; failed = true; return }
      if (result.logs !== undefined) { diagnostic = result.logs; return }
      if (result.size !== undefined) { diagnostic = result.size + "\n" + result.modes.join("\n"); return }
      info = result
      if (!initialized || !dirty || (isAction && (actionVerb === "save" || actionVerb === "apply"))) {
        draft = Object.assign({}, result.settings)
        initialized = true
        dirty = false
      }
      if (isAction) feedback = "Operación completada"
    } catch (e) { feedback = "No se pudo leer la respuesta del controlador: " + text.slice(0, 180); failed = true }
  }
  onOpenedChanged: if (opened) refresh()
  Component.onCompleted: refresh()
  Timer { interval: root.opened ? 3000 : 10000; running: true; repeat: true; onTriggered: root.refresh() }
  Process {
    id: poll
    command: ["/usr/bin/python", root.backend, "status"]
    stdout: StdioCollector { onStreamFinished: root.receive(text, false) }
  }
  Process {
    id: action
    stdout: StdioCollector { onStreamFinished: root.receive(text, true) }
    stderr: StdioCollector { onStreamFinished: if (text.trim()) { root.feedback = text.trim(); root.failed = true } }
    onExited: (code, status) => { if (code !== 0 && !root.feedback) { root.feedback = "El controlador terminó con error " + code; root.failed = true } root.refresh() }
  }

  BarIconButton {
    id: icon
    anchors.fill: parent
    bar: root.bar
    text: "󰓶"
    foreground: root.online ? Color.accent : root.barForeground
    tooltipText: "Omadesk · " + root.stateLabel
    onPressed: root.toggle()
    Rectangle {
      width: 5; height: 5; radius: 3
      anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 2
      color: root.online ? "#9ece6a" : Color.accent
      visible: !!root.info.active
    }
  }

  component Label : Text {
    color: root.ink
    font.family: "Adwaita Sans"
    font.pixelSize: Style.space(13)
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    Layout.fillWidth: true
  }
  component Choice : QQC.ComboBox {
    id: choice
    property var values: []
    property var labels: []
    property var selectedValue
    signal chosen(var value)
    model: labels.length ? labels : values
    currentIndex: values.indexOf(selectedValue)
    onActivated: choice.chosen(values[currentIndex])
    Layout.fillWidth: true
    implicitHeight: Style.space(34)
    font.family: "Adwaita Sans"
    palette.button: Color.background
    palette.base: Color.background
    palette.text: root.ink
    palette.buttonText: root.ink
    palette.highlight: Color.accent
    palette.highlightedText: Color.background
  }
  component ActionButton : QQC.Button {
    id: control
    Layout.fillWidth: true
    implicitHeight: Style.space(36)
    font.family: "Adwaita Sans"
    palette.button: Color.background
    palette.buttonText: root.ink
    enabled: root.initialized && !root.busy
  }
  component NumberField : QQC.TextField {
    property string settingKey
    text: root.draft[settingKey] === undefined ? "" : String(root.draft[settingKey])
    onEditingFinished: root.edit(settingKey, Number(text))
    selectByMouse: true
    Layout.fillWidth: true
    color: root.ink
    background: Rectangle { color: Color.background; radius: 4; border.width: 1; border.color: root.muted }
    implicitHeight: Style.space(34)
    validator: IntValidator { bottom: -32768; top: 32768 }
  }

  KeyboardPanel {
    id: panel
    anchorItem: icon
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: connectButton
    padding: Style.space(18)
    contentWidth: panel.fittedContentWidth(Style.space(470))
    contentHeight: panel.fittedContentHeight(Style.space(820))

    QQC.ScrollView {
      id: scroller
      anchors.fill: parent
      clip: true
      contentWidth: availableWidth
      ColumnLayout {
        width: scroller.availableWidth
        spacing: Style.space(10)
        Keys.onEscapePressed: root.close()
        RowLayout {
          Label { text: "Omadesk"; font.pixelSize: Style.space(22); font.bold: true }
          QQC.Button { text: "×"; onClicked: root.close() }
        }
        Label { text: root.stateLabel; color: root.online ? "#9ece6a" : root.muted }
        Label {
          text: root.info.monitor ? root.info.monitor.width + " × " + root.info.monitor.height + " · " + Math.round(root.info.monitor.refreshRate) + " Hz · " + Math.round(root.info.monitor.scale * 100) + "% · " + root.info.monitor.x + ", " + root.info.monitor.y : (root.info.capabilities && root.info.capabilities.model ? root.info.capabilities.model + " · " + root.info.capabilities.width + "×" + root.info.capabilities.height + " · " + root.info.capabilities.refresh + " Hz" : "Android por USB · ejecuta omadesk setup para preparar el dispositivo")
          color: root.muted
          font.pixelSize: Style.space(11)
        }
        RowLayout {
          ActionButton { id: connectButton; text: root.info.active ? "Reconectar" : "Conectar"; onClicked: root.send(root.info.active ? "restart" : "start") }
          ActionButton { text: "Desconectar"; enabled: !!root.info.active && !root.busy; onClicked: root.send("stop") }
          ActionButton { text: "Abrir AVNC"; enabled: !!root.info.active && !root.busy; onClicked: root.send("viewer") }
        }
        Label { text: "Imagen"; font.bold: true; font.pixelSize: Style.space(16) }
        RowLayout {
          Repeater {
            model: ["Texto nítido", "Equilibrado", "Ligero"]
            ActionButton { required property string modelData; text: modelData; onClicked: root.preset(modelData) }
          }
        }
        GridLayout {
          columns: 2
          columnSpacing: Style.space(16)
          rowSpacing: Style.space(6)
          Layout.fillWidth: true
          Label { text: "Resolución" }
          Choice {
            values: {
              var cap = root.info.capabilities || {}
              var nativeSize = cap.width ? Math.max(cap.width, cap.height) + "×" + Math.min(cap.width, cap.height) : ""
              var current = Math.max(root.draft.width || 0, root.draft.height || 0) + "×" + Math.min(root.draft.width || 0, root.draft.height || 0)
              return [nativeSize, current, "2560×1600", "1920×1200", "1600×1000", "1280×800"].filter((v,i,a) => v !== "" && a.indexOf(v) === i)
            }
            selectedValue: Math.max(root.draft.width || 0, root.draft.height || 0) + "×" + Math.min(root.draft.width || 0, root.draft.height || 0)
            onChosen: value => root.setResolution(value)
          }
          Label { text: "Orientación" }
          Choice { values: ["Horizontal", "Vertical"]; selectedValue: root.draft.height > root.draft.width ? "Vertical" : "Horizontal"; onChosen: value => root.orientation(value) }
          Label { text: "Frecuencia virtual (Hz)" }
          Choice { values: [30, 60, root.draft.refresh, Math.min(120,(root.info.capabilities || {}).refresh || 60)].filter((v,i,a) => a.indexOf(v) === i).sort((a,b) => a-b); selectedValue: root.draft.refresh; onChosen: value => { root.edit("refresh", value); if (root.draft.fps > value) root.edit("fps", value) } }
          Label { text: "Límite de transmisión (FPS)" }
          Choice { values: [15, 24, 30, 45, 60]; selectedValue: root.draft.fps; onChosen: value => root.edit("fps", value) }
          Label { text: "Escala de interfaz" }
          Choice { values: [1, 1.25, 1.6, 2]; labels: ["100 %", "125 %", "160 %", "200 %"]; selectedValue: root.draft.scale; onChosen: value => root.edit("scale", value) }
          Label { text: "Calidad JPEG (0–9)" }
          Choice { values: [0,1,2,3,4,5,6,7,8,9]; selectedValue: root.draft.quality; onChosen: value => root.edit("quality", value) }
          Label { text: "Compresión (0–9)" }
          Choice { values: [0,1,2,3,4,5,6,7,8,9]; selectedValue: root.draft.compression; onChosen: value => root.edit("compression", value) }
        }
        Label {
          text: "Más calidad: menos pérdidas en las regiones JPEG, más datos. Más compresión: menos datos, más CPU. No es un porcentaje ni garantiza 60 FPS; VNC adapta la codificación al contenido."
          font.pixelSize: Style.space(11); color: root.muted
        }
        Label { text: "Ubicación"; font.bold: true; font.pixelSize: Style.space(16) }
        GridLayout {
          columns: 2; Layout.fillWidth: true; columnSpacing: Style.space(16)
          Label { text: "Posición" }
          Choice { values: ["right", "left", "above", "below", "custom"]; labels: ["Derecha", "Izquierda", "Arriba", "Abajo", "Personalizada"]; selectedValue: root.draft.position; onChosen: value => root.edit("position", value) }
          Label { text: "Monitor de referencia" }
          Choice { values: [""].concat((root.info.monitors || []).map(m => m.name)); selectedValue: root.draft.anchor || ""; displayText: currentIndex === 0 ? "Todos los monitores" : currentText; onChosen: value => root.edit("anchor", value) }
          Label { visible: root.draft.position === "custom"; text: "Coordenada X" }
          NumberField { visible: root.draft.position === "custom"; settingKey: "x" }
          Label { visible: root.draft.position === "custom"; text: "Coordenada Y" }
          NumberField { visible: root.draft.position === "custom"; settingKey: "y" }
        }
        Label { text: "Las posiciones y coordenadas usan píxeles lógicos, después de aplicar la escala."; color: root.muted; font.pixelSize: Style.space(11) }
        RowLayout {
          QQC.CheckBox { text: "Entrada táctil / teclado"; checked: !!root.draft.input; onToggled: root.edit("input", checked); palette.windowText: root.ink }
          QQC.CheckBox { text: "Capturar cursor"; checked: !!root.draft.cursor; onToggled: root.edit("cursor", checked); palette.windowText: root.ink }
        }
        Label { text: "Cambios sin guardar"; visible: root.dirty; color: Color.accent }
        Label { text: root.busy ? "Aplicando…" : root.feedback; visible: root.busy || root.feedback !== ""; color: root.failed ? Color.urgent : root.ink }
        RowLayout {
          ActionButton { text: "Guardar"; enabled: root.initialized && root.dirty && !root.busy; onClicked: root.send("save") }
          ActionButton { text: "Guardar y aplicar"; onClicked: root.send("apply") }
          ActionButton { text: "Descartar"; enabled: root.dirty && !root.busy; onClicked: { root.draft = Object.assign({}, root.info.settings); root.dirty = false } }
        }
        Label { text: "Aplicar reinicia la conexión. Guardar conserva los ajustes para la próxima conexión sin interrumpir la imagen."; color: root.muted; font.pixelSize: Style.space(11) }
        Label { text: "Dispositivo y diagnóstico"; font.bold: true; font.pixelSize: Style.space(16) }
        Choice {
          values: (root.info.devices || []).map(d => d.serial)
          selectedValue: root.draft.serial
          displayText: currentIndex >= 0 ? currentText : "Conecta y autoriza la tablet USB"
          onChosen: value => root.edit("serial", value)
        }
        Label { text: (root.info.devices || []).map(d => d.model + " · " + d.serial + " · " + d.state).join("\n") || "No se detectan dispositivos USB autorizados"; color: root.muted; font.pixelSize: Style.space(11) }
        RowLayout {
          ActionButton { text: "Leer panel nativo"; onClicked: root.send("detect") }
          ActionButton { text: "Ver registro"; onClicked: root.send("logs") }
          ActionButton { text: "Ocultar registro"; visible: root.diagnostic !== ""; onClicked: root.diagnostic = "" }
        }
        QQC.TextArea {
          visible: root.diagnostic !== ""
          Layout.fillWidth: true
          text: root.diagnostic
          readOnly: true
          wrapMode: TextEdit.WrapAnywhere
          color: root.muted
          font.family: "monospace"
          font.pixelSize: Style.space(10)
          background: Rectangle { color: Color.background; radius: 4 }
          selectByMouse: true
        }
        Label { text: "Solo USB · puertos locales 5909/5910 · sin root ni cambios de firmware"; color: root.muted; font.pixelSize: Style.space(11) }
      }
    }
  }
}
