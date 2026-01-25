# faustbrowser-mcp

<p>
  <img src="docs/faust-browser.jpg" alt="Faust Browser UI" style="object-fit: cover;" />
</p>

## Overview

faustbrowser-mcp is a browser-first MCP server for Faust DSP. It runs a tiny
Python MCP proxy locally, serves a static browser UI, and delegates all audio/MIDI
compilation and playback to the browser runtime. This lets MCP clients control
Faust DSP without any native audio runtime on the server side.

## How it works

- The Python server exposes MCP tools and serves the UI.
- The browser UI loads the Faust WebAssembly toolchain (built using [faustwasm](https://github.com/grame-cncm/faustwasm)) and starts AudioContext.
- MCP tool calls are forwarded to the browser over a long-polling bridge.
- Audio and MIDI runs entirely in the browser, the Python process is just a proxy.

## MCP tool surface (high level)

- Compile and start: `compile_and_start`, `compile`, `start`, `stop`, `destroy`
- Load prebuilt DSPs: `load_wasm_module`, `save_wasm_module`, `get_dsp_json`
- Parameters: `get_params`, `get_param`, `set_param`, `get_param_values`, `set_param_values`
- Diagnostics: `check_syntax`, `get_status`, `get_audio_metrics`
- MIDI: `get_midi_inputs`, `select_midi_input`, `get_midi_status`

## MIDI and polyphony

- MIDI input is available through the browser Web MIDI API, and can be used to [control UI items](https://faustdoc.grame.fr/manual/midi/#configuring-midi-in-faust). Use
  `get_midi_inputs` to list ports, then `select_midi_input` to bind one.
- [Polyphonic DSPs](https://faustdoc.grame.fr/manual/midi/#midi-polyphony-support) are detected automatically from the Faust JSON metadata. When a DSP exposes `nvoices`, the runtime enables polyphony and the UI shows active voice counts.
- MIDI note activity is reported via `get_midi_status`, and polyphonic
  patches can be controlled with standard note on/off messages.

## Requirements

- Python 3.10+
- A modern browser with Web Audio and Web MIDI enabled
- Node.js and npm to install UI dependencies

## Install

Clone the repo and install dependencies.

```bash
python -m pip install mcp
cd ui
npm install
```

If `ui/node_modules` is already present, the npm step can be skipped.

## Run

Start the MCP proxy and UI server:

```bash
python faust_browser_server.py
```

Then open the UI in your browser:

```
http://127.0.0.1:8010
```

Once the browser tab is open, MCP tools will start working. If audio is
suspended, unlock it from the UI or call the `unlock_audio` tool.

## Connect with Claude Desktop

Add a new MCP server entry to Claude Desktop and point it at the Python
server. On macOS the config file is usually:

```
~/Library/Application Support/Claude/claude_desktop_config.json
```

Example configuration:

```json
{
  "mcpServers": {
    "faustbrowser-mcp": {
      "command": "python",
      "args": [
        "/path/to/faustbrowser-mcp/faust_browser_server.py"
      ],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "BROWSER_UI_HOST": "127.0.0.1",
        "BROWSER_UI_PORT": "8010",
        "BROWSER_UI_ROOT": "/path/to/faustbrowser-mcp",
        "BROWSER_UI_INDEX": "ui/rt-browser-ui.html"
      }
    }
  }
}
```

Restart Claude Desktop after saving the file, then open the UI in a browser
to establish the audio runtime session.

### Skills

[Claude Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills) are lightweight, repo-local playbooks that teach agents how to perform a specialized task. 

- `skills/faust-internal-metering/SKILL.md`: How to add RMS/Peak metering probes
  anywhere in a Faust DSP, read them via `get_param_values()`, and surface
  probe values in `get_audio_metrics()`.

Example snippet (internal metering with probes):

```faust
import("stdfaust.lib");
db = library("debug.lib");

osc = os.sawtooth(freq) : db.probe_rms_db(0, 1);
filtered = osc : fi.lowpass(2, cutoff) : db.probe_peak_db(1, 1);
process = filtered;
```

Example JSON readback (from `get_param_values()`):

```json
[
  { "path": "/dsp/Probe_RMS_dB_0", "value": -16.9 },
  { "path": "/dsp/Probe_Peak_dB_1", "value": -14.0 }
]
```

## Configuration

Environment variables (defaults shown):

- `MCP_HOST=127.0.0.1`
- `MCP_PORT=8000`
- `BROWSER_UI_HOST=127.0.0.1`
- `BROWSER_UI_PORT=8010`
- `BROWSER_UI_ROOT=.`
- `BROWSER_UI_INDEX=ui/rt-browser-ui.html`

## Example usage

Simple Faust DSP compile and start (from any MCP client):

```json
{
  "tool": "compile_and_start",
  "args": {
    "faust_code": "process = os.osc(440) * 0.2;"
  }
}
```

## Troubleshooting

- If audio is silent, the browser may have suspended audio. Use the UI unlock
  control or call `unlock_audio`.
- If tools report "No browser session connected", open the UI page and keep the
  tab alive so the bridge can register.
- Web MIDI requires user permission; confirm the browser prompt and ensure your
  device is selected in the MIDI panel.

## Security

This server is intended for local, trusted use. Keep it bound to localhost and
avoid exposing it on public networks.

## License

See the repository license file for details.

## Notes

- The browser session is the source of truth; if it closes, tool calls will fail
  until a new session registers.
