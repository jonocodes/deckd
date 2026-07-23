import { useEffect, useRef } from "react";

type Props = {
  onType: (text: string) => void;
  onKey: (combo: string) => void;
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

function isSameMachineClient(): boolean {
  if (typeof window === "undefined") return false;
  const h = window.location.hostname;
  return h === "localhost" || h === "127.0.0.1" || h === "[::1]" || h === "::1";
}

export function KbdMode({ onType, onKey }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const prevValue = useRef("");
  const composing = useRef(false);

  useEffect(() => {
    inputRef.current?.focus();
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

  const sameMachine = isSameMachineClient();

  return (
    <div className="kbd" onPointerDown={() => inputRef.current?.focus()}>
      {sameMachine && (
        <div className="kbd-banner" role="status">
          <strong>Same machine as the daemon.</strong> Text injection is
          disabled here to prevent a self-loop. Click another desktop app
          to type into it, or use this from a phone or remote browser.
        </div>
      )}
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
      </div>
      <input
        ref={inputRef}
        className="kbd-input"
        type="text"
        autoFocus
        autoComplete="off"
        spellCheck={false}
        enterKeyHint="enter"
        aria-label="Remote keyboard"
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
      {!sameMachine && <span className="kbd-hint">keyboard</span>}
    </div>
  );
}