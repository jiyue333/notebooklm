import { LOGO_OPTION_META } from './logoOptions';

const APP_NAME = String.fromCharCode(78, 111, 116, 101, 98, 111, 111, 107, 76, 77);

const LOGO_ICONS = {
    stack: (
        <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
            <rect x="8" y="10" width="24" height="28" rx="8" fill="currentColor" opacity="0.22" />
            <rect x="16" y="6" width="24" height="28" rx="8" fill="currentColor" opacity="0.9" />
            <path d="M22 14h12M22 20h12M22 26h8" stroke="white" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
    ),
    'spark-notes': (
        <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
            <rect x="8" y="8" width="32" height="32" rx="12" fill="currentColor" opacity="0.16" />
            <path d="M24 10l2.9 8.1L35 21l-8.1 2.9L24 32l-2.9-8.1L13 21l8.1-2.9L24 10Z" fill="currentColor" />
            <path d="M18 35h12" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" opacity="0.55" />
        </svg>
    ),
    orbit: (
        <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
            <circle cx="24" cy="24" r="6" fill="currentColor" />
            <path d="M9 24c0-7.73 6.27-14 14-14s14 6.27 14 14-6.27 14-14 14S9 31.73 9 24Z" stroke="currentColor" strokeWidth="2.4" opacity="0.34" />
            <path d="M15 13c7.2 1.3 13.7 5.8 18 12" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" opacity="0.72" />
            <path d="M32 33c-7.2-1.3-13.7-5.8-18-12" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" opacity="0.72" />
        </svg>
    ),
};

const LOGO_OPTIONS = LOGO_OPTION_META.map((item) => ({
    ...item,
    icon: LOGO_ICONS[item.id] || LOGO_ICONS.stack,
}));

export default function AppLogo({ option = 'stack', text = APP_NAME, size = 'md', showText = true }) {
    const active = LOGO_OPTIONS.find((item) => item.id === option) || LOGO_OPTIONS[0];

    return (
        <div className={`ui-app-logo ui-app-logo-${size}`} title={active.label}>
            <span className="ui-app-logo-mark">{active.icon}</span>
            {showText ? <span className="ui-app-logo-text">{text}</span> : null}
        </div>
    );
}
