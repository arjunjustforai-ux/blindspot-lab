export function Logo({ className = "" }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
        <defs>
          <linearGradient id="bl-g" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="#818cf8" />
            <stop offset="1" stopColor="#22d3ee" />
          </linearGradient>
        </defs>
        <circle cx="16" cy="16" r="13" fill="none" stroke="url(#bl-g)" strokeWidth="2.5" />
        <path d="M16 3 A13 13 0 0 1 29 16 L16 16 Z" fill="#fbbf24" opacity="0.9" />
        <circle cx="16" cy="16" r="4" fill="url(#bl-g)" />
      </svg>
      <span className="text-[15px] font-semibold tracking-tight">
        Blindspot <span className="text-gradient">Lab</span>
      </span>
    </div>
  );
}
