import React from 'react';
import { ErrorIcon } from '../Icons';

function Score({ label, value }) {
  if (value == null) return null;
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="uppercase tracking-wider text-[10px] text-red-300/70 w-24 shrink-0">
        {label}
      </span>
      <div className="flex-1 h-1.5 bg-red-950/60 rounded-full overflow-hidden">
        <div className="h-full bg-red-400" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-red-200 font-mono w-10 text-right">{pct}%</span>
    </div>
  );
}

/**
 * 409 fingerprint-block banner. Renders the AI slice's MatchDecision detail:
 * { kind: "fingerprint_block", message, band, composite, fingerprint, reasons[] }.
 * For other 409s (file locked, not confirmed) the parent should render a
 * plain banner — this component only handles the structured-block case.
 */
export default React.memo(function BlockReasonsBanner({ detail, onFindDifferent }) {
  const reasons = Array.isArray(detail?.reasons) ? detail.reasons : [];
  return (
    <div
      role="alert"
      className="rounded-xl border border-red-500/40 bg-red-950/40 p-4 space-y-3"
    >
      <div className="flex items-start gap-2">
        <ErrorIcon className="w-5 h-5 text-red-300 shrink-0 mt-0.5" />
        <div className="min-w-0">
          <p className="text-sm font-semibold text-red-200">
            Swap blocked — match looks wrong
          </p>
          <p className="text-xs text-red-300/90 mt-0.5">
            {detail?.message
              || 'The fingerprint or metadata for this pool hit does not look like the file you are replacing. The original was not touched.'}
          </p>
        </div>
      </div>

      <div className="space-y-1.5 pl-7">
        <Score label="Composite" value={detail?.composite} />
        <Score label="Fingerprint" value={detail?.fingerprint} />
      </div>

      {reasons.length > 0 && (
        <ul className="pl-7 space-y-1">
          {reasons.map((r, i) => (
            <li key={i} className="text-xs text-red-200 flex items-start gap-2">
              <span className="text-red-400 shrink-0">•</span>
              <span className="min-w-0">{r}</span>
            </li>
          ))}
        </ul>
      )}

      {onFindDifferent && (
        <div className="flex justify-end pt-1">
          <button
            type="button"
            onClick={onFindDifferent}
            className="px-3 py-1.5 text-xs bg-red-900/40 hover:bg-red-900/60 text-red-100 border border-red-500/30 rounded-lg transition-colors"
          >
            Find a different match
          </button>
        </div>
      )}
    </div>
  );
});
