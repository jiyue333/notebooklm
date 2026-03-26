import { useCallback, useEffect, useMemo, useState } from 'react';
import { ThemeContext } from './themeStore';

const THEME_STORAGE_KEY = '[REDACTED]-theme';
const ACCENT_STORAGE_KEY = '[REDACTED]-accent';
const THEME_OPTIONS = new Set(['light', 'dark', 'auto']);

function getSystemTheme() {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
        return 'light';
    }
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function resolveStoredTheme() {
    if (typeof window === 'undefined' || !window.localStorage) {
        return 'light';
    }
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    return THEME_OPTIONS.has(saved) ? saved : 'light';
}

function resolveStoredAccent() {
    if (typeof window === 'undefined' || !window.localStorage) {
        return 'ocean';
    }
    return window.localStorage.getItem(ACCENT_STORAGE_KEY) || 'ocean';
}

export function ThemeProvider({ children }) {
    const [theme, setTheme] = useState(resolveStoredTheme);
    const [accentColor, setAccentColor] = useState(resolveStoredAccent);
    const [systemTheme, setSystemTheme] = useState(getSystemTheme);

    const resolvedTheme = theme === 'auto' ? systemTheme : theme;

    useEffect(() => {
        if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
            return undefined;
        }
        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        const handleChange = (event) => {
            setSystemTheme(event.matches ? 'dark' : 'light');
        };
        setSystemTheme(mediaQuery.matches ? 'dark' : 'light');
        mediaQuery.addEventListener('change', handleChange);
        return () => mediaQuery.removeEventListener('change', handleChange);
    }, []);

    useEffect(() => {
        if (typeof window !== 'undefined' && window.localStorage) {
            window.localStorage.setItem(THEME_STORAGE_KEY, theme);
        }
        document.documentElement.setAttribute('data-theme', resolvedTheme);
        document.documentElement.setAttribute('data-color-mode', theme);
    }, [theme, resolvedTheme]);

    useEffect(() => {
        if (typeof window !== 'undefined' && window.localStorage) {
            window.localStorage.setItem(ACCENT_STORAGE_KEY, accentColor);
        }
        document.documentElement.setAttribute('data-accent', accentColor);
    }, [accentColor]);

    const syncTheme = useCallback((nextTheme) => {
        if (!THEME_OPTIONS.has(nextTheme)) return;
        setTheme(nextTheme);
    }, []);

    const toggleTheme = useCallback(() => {
        setTheme((previous) => {
            const current = previous === 'auto' ? systemTheme : previous;
            return current === 'dark' ? 'light' : 'dark';
        });
    }, [systemTheme]);

    const value = useMemo(() => ({
        theme,
        resolvedTheme,
        systemTheme,
        setTheme: syncTheme,
        toggleTheme,
        accentColor,
        setAccentColor,
    }), [accentColor, resolvedTheme, syncTheme, systemTheme, theme, toggleTheme]);

    return (
        <ThemeContext.Provider value={value}>
            {children}
        </ThemeContext.Provider>
    );
}
