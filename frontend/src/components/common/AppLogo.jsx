import { LOGO_OPTION_META } from './logoOptions';

const APP_NAME = String.fromCharCode(78, 111, 116, 101, 98, 111, 111, 107, 76, 77);

const LOGO_ICONS = {
    page: (
        <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
            <rect x="4" y="12" width="22" height="30" rx="4" fill="currentColor" opacity="0.18" />
            <rect x="9" y="6" width="22" height="30" rx="4" fill="currentColor" opacity="0.88" />
            <path d="M15 15h10M15 21h10M15 27h6" stroke="white" strokeWidth="2.2" strokeLinecap="round" />
            <path d="M38 10l1.5 3.5L43 15l-3.5 1.5L38 20l-1.5-3.5L33 15l3.5-1.5Z" fill="currentColor" />
            <path d="M33 4l.7 1.6 1.6.7-1.6.7-.7 1.6-.7-1.6L31 5.7l1.6-.7Z" fill="currentColor" opacity="0.45" />
        </svg>
    ),
    spark: (
        <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
            <circle cx="24" cy="24" r="16" fill="currentColor" opacity="0.1" />
            <path d="M24 6l3.5 14.5L42 24l-14.5 3.5L24 42l-3.5-14.5L6 24l14.5-3.5Z" fill="currentColor" opacity="0.82" />
            <circle cx="24" cy="24" r="4.5" fill="white" opacity="0.85" />
            <circle cx="38" cy="10" r="2.5" fill="currentColor" opacity="0.4" />
        </svg>
    ),
    orbit: (
        <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
            <ellipse cx="24" cy="24" rx="20" ry="10" stroke="currentColor" strokeWidth="2" opacity="0.22" transform="rotate(-25 24 24)" />
            <ellipse cx="24" cy="24" rx="20" ry="10" stroke="currentColor" strokeWidth="2" opacity="0.22" transform="rotate(25 24 24)" />
            <circle cx="24" cy="24" r="7" fill="currentColor" opacity="0.85" />
            <circle cx="23" cy="22.5" r="2.5" fill="white" opacity="0.65" />
            <circle cx="40" cy="14" r="3" fill="currentColor" opacity="0.5" />
            <circle cx="8" cy="34" r="2" fill="currentColor" opacity="0.3" />
        </svg>
    ),
};

const LOGO_OPTIONS = LOGO_OPTION_META.map((item) => ({
    ...item,
    icon: LOGO_ICONS[item.id] || LOGO_ICONS.page,
}));

export default function AppLogo({ option = 'orbit', text = APP_NAME, size = 'md', showText = true }) {
    const active = LOGO_OPTIONS.find((item) => item.id === option) || LOGO_OPTIONS[0];

    return (
        <div className={`ui-app-logo ui-app-logo-${size}`} title={active.label}>
            <span className="ui-app-logo-mark">{active.icon}</span>
            {showText ? <span className="ui-app-logo-text">{text}</span> : null}
        </div>
    );
}
