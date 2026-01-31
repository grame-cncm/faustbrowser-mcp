---
name: faust-internal-metering
description: How to add RMS/Peak metering at any point in a Faust DSP for debugging with MCP
---

## Faust MCP Internal Metering

By default, the Faust MCP automatically adds RMS/Peak meters on the DSP **outputs**. Add measurement points **anywhere** in the signal graph to debug intermediate stages or to expose custom probes to `get_audio_metrics()`.

## Using `debug.lib`

Faust provides a `debug.lib` library that includes the standard `probe_*` functions
with UI bargraphs and `[probe:N]` metadata already wired in. It also supports a
`DEBUG` compile-time switch so probes can be compiled out entirely.

Example:

```faust
import("stdfaust.lib");
db = library("debug.lib");

process = _ : db.probe_rms_db(0, 1) : db.probe_peak_db(1, 1);
```

Compile out probes for release builds:

```faust
process = _ : db[DEBUG=0;].probe_rms_db(0, 1);
```

### Standard probe bargraphs

If you use `debug.lib`, you already have the standard probe definition at https://raw.githubusercontent.com/grame-cncm/faustlibraries/refs/heads/master/doc/docs/libs/debug.md or https://raw.githubusercontent.com/grame-cncm/faustlibraries/refs/heads/master/debug.lib

The `[hidden:1]` metadata hides the metering probes in the GUI. Keep them visible when you want to help developers debug, or hide them when not needed.

## Usage

### Measuring an intermediate signal (probe ids)

```faust
// Measure after oscillator, before filter
osc = os.sawtooth(freq) : db.probe_rms_db(0, 1);
filtered = osc : fi.lowpass(2, cutoff) : db.probe_peak_db(1, 1);
process = filtered;
```

### Mixing dB + linear probes

```faust
osc = os.sawtooth(freq) : db.probe_rms_db(2, 1);
env = en.adsr(0.01, 0.1, 0.7, 0.3, gate) : db.probe_peak_lin(3, 1);
process = osc * env;
```

### Measuring multiple points

```faust
import("stdfaust.lib");

freq = hslider("freq", 440, 20, 2000, 1);
gain = hslider("gain", 0.5, 0, 1, 0.01);
gate = button("gate");

// Pipeline with probes at each stage
osc = os.sawtooth(freq) : db.probe_rms_db(0, 1);
shaped = osc * en.adsr(0.01, 0.1, 0.7, 0.3, gate) : db.probe_rms_db(1, 1);
output = shaped * gain : db.probe_rms_db(2, 1);

process = output <: _,_;
```

## Reading Values

Probe bargraphs appear in `get_param_values()` with their raw values (linear if you emit linear, dB if you emit dB). Example paths for the standard probe labels:

```json
{
  "path": "/dsp/Probe_RMS_dB_0",
  "value": -16.9
},
{
  "path": "/dsp/Probe_Peak_dB_1",
  "value": -14.0
},
{
  "path": "/dsp/Probe_RMS_dB_2",
  "value": -12.3
}
```

Probes containing `[probe:N]` are returned in `get_audio_metrics()`:

```json
{
  "probes": [
    { "id": 0, "value": 0.57 },
    { "id": 1, "value": 0.42 }
  ]
}
```

These values are directly comparable with `get_audio_metrics()` output when the probes are linear (or when you use `[unit:dB]` and the conversion to linear is applied).

## Use Cases

1. **Debug a disappearing signal**: Add meters at each stage to locate where the signal drops to zero or becomes NaN.

2. **Check levels before/after an effect**: Compare the gain of a filter or distortion.

3. **Monitor an envelope**: Verify that the ADSR rises and falls correctly.

4. **Detect internal clipping**: Find where the signal exceeds 1.0 before the final output.

## Notes

- `attach(x, y)` passes `x` through unchanged, but forces computation of `y` (side-effect for the bargraph)
- Meters add slight CPU overhead (0.1s RMS/Peak window)
- Use groups (`h:Debug/...`) to organize meters in the UI
- If you want `get_audio_metrics()` to convert dB to linear, include `[unit:dB]` in the bargraph label
- Values are linear (not dB) for easy comparison: `0.5` = half amplitude, `1.0` = full scale, `> 1.0` = clipping
