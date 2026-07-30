/** Inline brand marks — same geometry as public favicons; no network dependency. */

export function AppBrandIcon({ className = "h-6 w-6" }: { className?: string }) {
  return (
    <svg
      className={`shrink-0 ${className}`}
      viewBox="0 0 32 32"
      width={32}
      height={32}
      aria-hidden
    >
      <rect width="32" height="32" rx="8" fill="#0f2744" />
      <path
        d="M8.5 20.5 L16 9.5 L23.5 20.5"
        fill="none"
        stroke="#38bdf8"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="16" cy="21.5" r="2.2" fill="#7dd3fc" />
    </svg>
  );
}

export function OpsBrandIcon({ className = "h-6 w-6" }: { className?: string }) {
  return (
    <svg
      className={`shrink-0 ${className}`}
      viewBox="0 0 32 32"
      width={32}
      height={32}
      aria-hidden
    >
      <rect width="32" height="32" rx="8" fill="#2a2112" />
      <path
        d="M8.5 16.5 L13.5 21.5 L23.5 10.5"
        fill="none"
        stroke="#fbbf24"
        strokeWidth="2.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
