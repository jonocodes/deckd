import { useEffect, useRef, useState } from "react";
import { Keyboard } from "lucide-react";

import { Trackpad } from "./Trackpad";

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
  { combo: "esc", label: "esc" },
  { combo: "tab", label: "tab" },
  { combo: "left", label: "←" },
  { combo: "up", label: "↑" },
  { combo: "down", label: "↓" },
  { combo: "right", label: "→" },
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

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    const onBeforeInput = (ev: Event) => {
      const ie = ev as InputEvent;
      const inputType = ie.inputType;
      if (inputType === "insertParagraph" || inputType === "insertLineBreak") {
        ev.preventDefault();
        onKey("enter");
      } else if (inputType === "deleteContentBackward") {
        ev.preventDefault();
        onKey("backspace");
      }
    };
    el.addEventListener("beforeinput", onBeforeInput);
    return () => el.removeEventListener("beforeinput", onBeforeInput);
  }, [onKey]);

  const sendDelta = (next: string) => {
    const prev = prevValue.current;
    if (next === prev) return;
    prevValue.current = next;
    let i = 0;
    while (i < prev.length && i < next.length && prev[i] === next[i]) i++;
    for (let n = prev.length - i; n > 0; n--) onKey("backspace");
    const inserted = next.slice(i);
    if (inserted) onType(inserted);
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
              onKey(combo);
            }}
          >
            {label}
          </button>
        ))}
        <button
          className={`chrome-btn kbd-strip-btn kbd-strip-ime${imeOpen ? " kbd-strip-ime-open" : ""}`}
          aria-label="keyboard"
          aria-pressed={imeOpen}
          onPointerDown={(e) => {
            e.preventDefault();
            toggleIme();
          }}
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
              onKey(combo);
            } else if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
              e.preventDefault();
              onType(e.key);
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