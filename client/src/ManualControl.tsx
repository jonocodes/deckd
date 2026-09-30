import { useCallback, useEffect, useRef, useState } from "react";
import { Keyboard } from "lucide-react";

import { Trackpad } from "./Trackpad";
import { onActivate } from "./a11y";

type Props = {
  onType: (text: string) => void;
  onKey: (combo: string) => void;
  onPad: (dx: number, dy: number) => void;
  onTap: (fingers: number) => void;
  onDrag: (state: "start" | "end") => void;
  /** Trackpad sensitivity multiplier (px → uinput units). */
  sensitivity: number;
};

const KEYDOWN_COMBOS: Record<string, string> = {
  Enter: "enter",
  Backspace: "backspace",
  Tab: "tab",
  Escape: "esc",
  ArrowUp: "up",
  ArrowDown: "down",
  ArrowLeft: "left",
  ArrowRight: "right",
};

const STRIP_KEYS: Array<{ combo: string; label: string }> = [
  // Arrows first so the 4-column strip lays them out together on the top
  // row, then the command keys (with Ctrl + IME filling the bottom row).
  { combo: "left", label: "←" },
  { combo: "up", label: "↑" },
  { combo: "down", label: "↓" },
  { combo: "right", label: "→" },
  { combo: "esc", label: "esc" },
  { combo: "tab", label: "tab" },
];

export function ManualControl({
  onType,
  onKey,
  onPad,
  onTap,
  onDrag,
  sensitivity,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const prevValue = useRef("");
  const composing = useRef(false);
  const [imeOpen, setImeOpen] = useState(false);
  // Sticky one-shot Ctrl: arm it, then the next named key or typed
  // character is sent as a `ctrl+<key>` combo and the modifier clears.
  // A ref mirrors the state so the `beforeinput` listener (registered
  // once per `sendKey`) reads the live value without re-subscribing.
  const [ctrlArmed, setCtrlArmed] = useState(false);
  const ctrlArmedRef = useRef(false);
  ctrlArmedRef.current = ctrlArmed;

  const consumeCtrl = useCallback(() => {
    if (!ctrlArmedRef.current) return false;
    ctrlArmedRef.current = false;
    setCtrlArmed(false);
    return true;
  }, []);

  /** Emit a named key combo, prefixing `ctrl+` when the sticky Ctrl is
   * armed (and disarming it). */
  const sendKey = useCallback(
    (combo: string) => {
      if (consumeCtrl()) onKey(`ctrl+${combo}`);
      else onKey(combo);
    },
    [consumeCtrl, onKey],
  );

  /** Emit typed text. With Ctrl armed, the first character rides as a
   * `ctrl+<char>` combo (so Ctrl+C works from the IME/keydown path) and
   * any remainder is typed normally. */
  const sendType = useCallback(
    (text: string) => {
      if (text.length > 0 && consumeCtrl()) {
        onKey(`ctrl+${text[0]}`);
        const rest = text.slice(1);
        if (rest) onType(rest);
      } else {
        onType(text);
      }
    },
    [consumeCtrl, onKey, onType],
  );

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    const onBeforeInput = (ev: Event) => {
      const ie = ev as InputEvent;
      const inputType = ie.inputType;
      if (inputType === "insertParagraph" || inputType === "insertLineBreak") {
        ev.preventDefault();
        sendKey("enter");
      } else if (inputType === "deleteContentBackward") {
        ev.preventDefault();
        sendKey("backspace");
      }
    };
    el.addEventListener("beforeinput", onBeforeInput);
    return () => el.removeEventListener("beforeinput", onBeforeInput);
  }, [sendKey]);

  const sendDelta = (next: string) => {
    const prev = prevValue.current;
    if (next === prev) return;
    prevValue.current = next;
    let i = 0;
    while (i < prev.length && i < next.length && prev[i] === next[i]) i++;
    for (let n = prev.length - i; n > 0; n--) sendKey("backspace");
    const inserted = next.slice(i);
    if (inserted) sendType(inserted);
  };

  const toggleIme = () => {
    const el = inputRef.current;
    if (!el) return;
    if (document.activeElement === el) {
      el.blur();
      setImeOpen(false);
    } else {
      el.focus();
      setImeOpen(true);
    }
  };

  return (
    <div className="manual-control">
      <div className="kbd-strip">
        {STRIP_KEYS.map(({ combo, label }) => (
          <button
            key={combo}
            className="chrome-btn kbd-strip-btn"
            aria-label={combo}
            onPointerDown={(e) => {
              e.preventDefault();
              sendKey(combo);
            }}
            onKeyDown={onActivate(() => sendKey(combo))}
          >
            {label}
          </button>
        ))}
        <button
          className={`chrome-btn kbd-strip-btn kbd-strip-ctrl${ctrlArmed ? " kbd-strip-ctrl-armed" : ""}`}
          aria-label="ctrl"
          aria-pressed={ctrlArmed}
          onPointerDown={(e) => {
            e.preventDefault();
            setCtrlArmed((v) => !v);
          }}
          onKeyDown={onActivate(() => setCtrlArmed((v) => !v))}
        >
          ctrl
        </button>
        <button
          className={`chrome-btn kbd-strip-btn kbd-strip-ime${imeOpen ? " kbd-strip-ime-open" : ""}`}
          aria-label="keyboard"
          aria-pressed={imeOpen}
          onPointerDown={(e) => {
            e.preventDefault();
            toggleIme();
          }}
          onKeyDown={onActivate(toggleIme)}
        >
          <Keyboard size={18} />
        </button>
      </div>
      <div className="manual-surface">
        <Trackpad onPad={onPad} onTap={onTap} onDrag={onDrag} sensitivity={sensitivity} />
        <input
          ref={inputRef}
          className="kbd-input"
          type="text"
          autoComplete="off"
          spellCheck={false}
          enterKeyHint="enter"
          aria-label="Remote keyboard"
          tabIndex={-1}
          onFocus={() => setImeOpen(true)}
          onBlur={() => setImeOpen(false)}
          onCompositionStart={() => {
            composing.current = true;
          }}
          onCompositionEnd={() => {
            composing.current = false;
          }}
          onKeyDown={(e) => {
            if (e.key === "Unidentified") return;
            const combo = KEYDOWN_COMBOS[e.key];
            if (combo) {
              e.preventDefault();
              sendKey(combo);
            } else if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
              e.preventDefault();
              sendType(e.key);
            }
          }}
          onInput={(e) => {
            sendDelta(e.currentTarget.value);
            if (!composing.current) {
              e.currentTarget.value = "";
              prevValue.current = "";
            }
          }}
        />
      </div>
    </div>
  );
}