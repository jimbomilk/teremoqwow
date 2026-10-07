#!/usr/bin/env bash

# Margen (s) que se suma a la ventana de captura al acotar ffprobe con timeout.
# Medido: docker run + join MoQ + primera keyframe consumen ~6 s antes de que
# empiece a contar la ventana; con +5 s el timeout mataba ffprobe (exit 124)
# justo antes de terminar. No es sobrescribible por entorno a propósito.
QOS_FFPROBE_TIMEOUT_MARGIN_SEC=15

# Holgura (s) del timeout externo del gate de readiness sobre el de ffprobe:
# el externo debe sobrevivir al interno para que el exit=124 llegue al
# diagnóstico en vez de clasificarse como DATA_PATH_FAILURE.
QOS_GATE_TIMEOUT_SLACK_SEC=10

validate_duration() {
  local candidate="${1:-}"
  if [[ ! "$candidate" =~ ^[0-9]{1,4}$ ]] ||
     (( 10#$candidate < 1 || 10#$candidate > 3600 )); then
    printf '[ERROR] Invalid duration: expected a decimal integer from 1 to 3600 seconds\n' >&2
    return 2
  fi
}

# Valida WINDOW_SEC (entero decimal 1..3600) y lo normaliza a base 10.
# DEBE llamarse antes de cualquier aritmética con WINDOW_SEC: $(( )) evalúa
# subíndices como x[$(cmd)], lo que ejecutaría código del entorno.
qos_require_window_sec() {
  if ! validate_duration "${WINDOW_SEC:-}" 2>/dev/null; then
    printf '[ERROR] Invalid WINDOW_SEC: expected a decimal integer from 1 to 3600 seconds\n' >&2
    return 2
  fi
  WINDOW_SEC=$((10#$WINDOW_SEC))
}

# Verdadero si $1 es un decimal no negativo (123 o 123.45). Los datos externos
# (JSON de /metrics/latency, entorno) DEBEN pasar por aquí antes de entrar en
# $(( )) o en una comparación: x[$(cmd)] se ejecutaría como subíndice.
qos_is_decimal() {
  [[ "${1:-}" =~ ^[0-9]+(\.[0-9]+)?$ ]]
}

# Falla (rc 2) si la variable cuyo NOMBRE se pasa no es un decimal válido.
qos_require_decimal() {
  local name="$1"
  if ! qos_is_decimal "${!name:-}"; then
    printf '[ERROR] Invalid %s: expected a non-negative decimal number\n' "$name" >&2
    return 2
  fi
}

# Verdadero si el stderr del exporter es SOLO el cierre de pipe: el último
# mensaje es "broken pipe" y ninguna otra línea reporta error.
_qos_exporter_stderr_is_only_broken_pipe() {
  python3 - "$1" <<'PYTHON_EOF'
import pathlib
import re
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)
lines = [line.strip() for line in text.splitlines() if line.strip()]
if not lines or not re.search(r"broken pipe", lines[-1], re.I):
    sys.exit(1)
other_error = re.compile(r"\b(?:error|fatal|panic(?:ked)?|fail(?:ed|ure)?)\b", re.I)
sys.exit(1 if any(other_error.search(line) for line in lines[:-1]) else 0)
PYTHON_EOF
}

# Estado efectivo del exporter. ffprobe cierra el pipe al terminar su
# -read_intervals y `moq export ts` sale con 1 por "broken pipe". Se tolera
# SOLO si: exporter==1, ffprobe==0 y su stderr es únicamente ese cierre.
# Imprime el estado efectivo (0 si se tolera; el original en otro caso).
# Quien llama sigue exigiendo frames reales de audio y vídeo.
qos_effective_exporter_status() {
  local exporter_rc="$1"
  local ffprobe_rc="$2"
  local stderr_file="$3"

  if [[ "$exporter_rc" == "1" && "$ffprobe_rc" == "0" ]] &&
     _qos_exporter_stderr_is_only_broken_pipe "$stderr_file"; then
    printf '[QOS-DIAGNOSTIC] stage=exporter note=broken-pipe-tolerated raw_status=%s\n' \
      "$exporter_rc" >&2
    printf '0'
  else
    printf '%s' "$exporter_rc"
  fi
}

qos_report_tool_diagnostic() {
  local stage="$1"
  local exit_status="$2"
  local stderr_file="$3"

  printf '[QOS-DIAGNOSTIC] stage=%s exit=%s\n' "$stage" "$exit_status" >&2
  if [[ -s "$stderr_file" ]]; then
    python3 - "$stage" "$stderr_file" >&2 <<'PYTHON_EOF'
import functools
import re
import sys

stage, stderr_path = sys.argv[1:]
sys.stdout.reconfigure(errors="replace")

# 0) Tope de entrada: se lee como mucho MAX_INPUT_BYTES (el resto se descarta
# y se anuncia con una marca DESPUÉS de redactar, para que una comilla abierta
# en el corte no pueda redactar la propia marca).
MAX_INPUT_BYTES = 8 * 1024 * 1024
with open(stderr_path, "rb") as handle:
    raw = handle.read(MAX_INPUT_BYTES + 1)
truncated = len(raw) > MAX_INPUT_BYTES
diagnostic = raw[:MAX_INPUT_BYTES].decode("utf-8", errors="replace")

# 1) Secuencias de terminal y controles: ANTES de redactar, para que no puedan
# partir una clave (to\x00ken=...) ni separar clave y '=' (tracing-subscriber
# colorea ambos con ANSI). Sin pegar palabras: \r suelto => salto de línea;
# CSI y OSC (BEL o ST; sin terminador => fin de línea) => espacio; el resto de
# C0 (salvo \n y \t), DEL y C1 se eliminan.
diagnostic = diagnostic.replace("\r\n", "\n").replace("\r", "\n")
diagnostic = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", " ", diagnostic)
diagnostic = re.sub(r"\x1b\][^\x07\x1b\n]*(?:\x07|\x1b\\)?", " ", diagnostic)
diagnostic = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", diagnostic)

# 2) Bloques de clave privada PEM completos, con o sin clave sensible delante.
# BEGIN sin END (salida truncada) => hasta el final del texto.
PEM_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----"
    r".*?(?:-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|\Z)",
    re.S,
)
diagnostic = PEM_RE.sub("[REDACTED]", diagnostic)

# 3) Pares clave/valor. Enfoque lineal: se recorren las PALABRAS completas
# ([\w.-]+) y solo las que van seguidas de ':'/'=' se clasifican; no hay
# cuantificadores anidados ni reintentos desde cada posición.
STEMS_RE = re.compile(
    r"token|passw(?:or)?d|passphrase|secret|jwt|signature|session|credential|"
    r"authorization|cookie|pwd|psk|api[_-]?key|access[_-]?key|private[_-]?key|"
    r"hmac|hdnts|hdnea|passcode|client[_-]?key[_-]?data",
    re.I,
)
SHORT_COMPONENTS = frozenset(("pass", "otp"))
COMPONENT_SPLIT = re.compile(r"[_.\-]+|(?<=[a-z0-9])(?=[A-Z])")
# Sufijo key/pass (case-insensitive, pegado o con separador): streamKEY,
# dbpass, my-key. Palabras corrientes que terminan igual NO son sensibles.
SECRET_SUFFIXES = ("key", "pass")
SUFFIX_LOOKALIKES = ("monkey", "donkey", "turkey", "hockey", "jockey",
                     "bypass", "compass")
# Un nombre de fichero seguido de ':' es una ruta en un mensaje de error
# ("failed to open /certs/relay.key: No such file"), no un par clave/valor.
KEY_FILE_EXT_RE = re.compile(r"\.(?:key|pem|crt|p12|jks)$", re.I)
WORD = re.compile(r"[\w.\-]+")
SEPARATOR = re.compile(r"""\\*["']?\s*[:=]>?\s*""")
QUOTE_OPEN = re.compile(r"""\\*["']""")
QUOTED_VALUE = {
    '"': re.compile(r'(?:[^"\\\n]|\\.)*"'),
    "'": re.compile(r"(?:[^'\\\n]|\\.)*'"),
}
QUERY_VALUE = re.compile(r"""[^&#\r\n"']*""")


def has_secret_suffix(lowered):
    return (lowered.endswith(SECRET_SUFFIXES)
            and lowered not in SECRET_SUFFIXES
            and not lowered.endswith(SUFFIX_LOOKALIKES))


def is_sensitive(word, in_query, bare_colon=False):
    lowered = word.lower()
    if KEY_FILE_EXT_RE.search(lowered):
        return not bare_colon
    if lowered == "sig" or (in_query and lowered == "key"):
        return True
    if STEMS_RE.search(word) or has_secret_suffix(lowered):
        return True
    return any(c.lower() in SHORT_COMPONENTS for c in COMPONENT_SPLIT.split(word))


@functools.lru_cache(maxsize=64)
def escaped_closing_re(quote):
    # El cierre lleva exactamente los mismos backslashes que la apertura; una
    # comilla interna escapada lleva más.
    return re.compile(r"(?<!\\)" + re.escape(quote[:-1]) + re.escape(quote[-1]))


class LineEnds:
    """Fin de línea desde `start`, en O(1) amortizado: el recorrido es
    monótono, así que se reutiliza el último '\\n' hallado mientras siga
    siendo el primero a partir de `start` (evita un find() O(n) por clave)."""

    def __init__(self, text):
        self.text = text
        self.begin = 0
        self.end = -2

    def __call__(self, start):
        if not (self.begin <= start <= self.end):
            end = self.text.find("\n", start)
            self.begin = start
            self.end = len(self.text) if end == -1 else end
        return self.end


def closing_quote_end(text, start, quote, end_of_line):
    """Índice tras la comilla de cierre en la MISMA línea, o -1 si no hay."""
    if len(quote) == 1:
        match = QUOTED_VALUE[quote].match(text, start)
        return match.end() - 1 if match else -1
    match = escaped_closing_re(quote).search(text, start, end_of_line(start))
    return match.start() if match else -1


def redact_key_values(text):
    out = []
    pos = 0
    end_of_line = LineEnds(text)
    while True:
        word = WORD.search(text, pos)
        if not word:
            out.append(text[pos:])
            return "".join(out)
        separator = SEPARATOR.match(text, word.end())
        in_query = word.start() > 0 and text[word.start() - 1] in "?&"
        if not separator or not is_sensitive(
                word.group(0), in_query,
                separator.group(0).lstrip().startswith(":")):
            out.append(text[pos:word.end()])
            pos = word.end()
            continue
        index = separator.end()
        out.append(text[pos:index])
        quote_match = QUOTE_OPEN.match(text, index)
        if quote_match:
            quote = quote_match.group(0)
            closing = closing_quote_end(text, quote_match.end(), quote, end_of_line)
            if closing == -1:
                # Comilla abierta sin cierre en la línea: fail-closed hasta EOF.
                out.append(f"{quote}[REDACTED]")
                return "".join(out)
            out.append(f"{quote}[REDACTED]{quote}")
            pos = closing + len(quote)
        else:
            # Valor sin comillas: fail-closed hasta fin de línea (cubre
            # Some("x"), [1, 2], a;b, {...}); en query string solo hasta &/#.
            end = (QUERY_VALUE.match(text, index).end() if in_query
                   else end_of_line(index))
            if end > index:
                out.append("[REDACTED]")
            pos = end


diagnostic = redact_key_values(diagnostic)
diagnostic = re.sub(
    r"(?i)(\bbearer\s+)[^\s,;}\"']+",
    r"\1[REDACTED]",
    diagnostic,
)
diagnostic = re.sub(
    r"(?i)(?<![a-z0-9+.-])([a-z][a-z0-9+.-]*://)([^/@\s:]*):([^/\r\n]*?)@(?=[^/\s@]+(?:[/\s]|$))",
    r"\1[REDACTED]@",
    diagnostic,
)
for line in diagnostic.splitlines():
    print(f"[{stage}] {line}")
if truncated:
    print(f"[{stage}] [TRUNCATED]")
PYTHON_EOF
  fi
}
