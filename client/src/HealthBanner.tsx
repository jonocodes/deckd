import { TriangleAlert as AlertIcon } from "lucide-react";
import type { HealthIssue } from "./protocol";

/** Human words for the wire's ``affects`` primitives. An unknown key
 * renders as-is: a newer daemon can add one without a client release. */
const AFFECTS_LABELS: Record<string, string> = {
  pointer: "trackpad & clicks",
  scroll: "scrolling",
  key: "key presses",
  raise_window: "raising windows from the list",
  focus: "switching decks with the app in front",
};

function describeAffects(affects: string[]): string {
  return affects.map((a) => AFFECTS_LABELS[a] ?? a).join(", ");
}

/** Banner for each active daemon health issue (issue #195).
 *
 * The daemon pushes the full list whenever it changes; an empty list takes
 * every banner down. Dismissal is per issue id and lasts for the page
 * session. The caller owns the dismissed set, so it survives this banner
 * unmounting (the lock takeover replaces the surface it lives in).
 */
export function HealthBanner({
  issues,
  dismissed,
  onDismiss,
}: {
  issues: HealthIssue[];
  dismissed: ReadonlySet<string>;
  onDismiss: (id: string) => void;
}) {
  const visible = issues.filter((i) => !dismissed.has(i.id));
  if (visible.length === 0) return null;
  return (
    <div className="health-banners">
      {visible.map((issue) => (
        <div
          key={issue.id}
          className={`health-banner health-banner--${issue.severity}`}
          role="alert"
        >
          <div className="health-banner-head">
            <AlertIcon className="health-banner-glyph" size={18} aria-hidden />
            <span className="health-banner-title">{issue.title}</span>
            <button
              className="health-banner-dismiss"
              aria-label={`Dismiss: ${issue.title}`}
              onClick={() => onDismiss(issue.id)}
            >
              Dismiss
            </button>
          </div>
          {issue.detail ? <p className="health-banner-detail">{issue.detail}</p> : null}
          {issue.affects.length > 0 ? (
            <p className="health-banner-affects">
              {"Not working: "}
              {describeAffects(issue.affects)}
            </p>
          ) : null}
          {issue.fix_steps.length > 0 ? (
            <ol className="health-banner-steps">
              {issue.fix_steps.map((step, n) => (
                <li key={n}>{step}</li>
              ))}
            </ol>
          ) : null}
        </div>
      ))}
    </div>
  );
}
