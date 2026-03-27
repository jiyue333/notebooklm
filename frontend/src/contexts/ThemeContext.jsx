import { useCallback, useEffect, useMemo, useState } from 'react';
import { ThemeContext } from './themeStore';

const THEME_STORAGE_KEY = '[REDACTED]-theme';
const ACCENT_STORAGE_KEY = '[REDACTED]-accent';
const LEGACY_FONT_STORAGE_KEY = '[REDACTED]-font-family';
const FONT_LATIN_STORAGE_KEY = '[REDACTED]-font-latin';
const FONT_CJK_STORAGE_KEY = '[REDACTED]-font-cjk';
const THEME_OPTIONS = new Set(['light', 'dark', 'auto']);
const LATIN_FONT_OPTIONS = new Set([
    'times_new_roman',
    'georgia',
    'source_serif',
    'source_sans',
    'inter',
    'jetbrains_mono',
]);
const CJK_FONT_OPTIONS = new Set([
    'source_han_serif',
    'source_han_sans',
    'songti',
    'kaiti',
    'yahei',
]);
const LATIN_FONT_STACKS = {
    times_new_roman: "'Times New Roman', Times, serif",
    georgia: "Georgia, 'Times New Roman', serif",
    source_serif: "'Source Serif 4', 'Noto Serif', serif",
    source_sans: "'Source Sans 3', 'Helvetica Neue', Arial, sans-serif",
    inter: "'Inter', 'Helvetica Neue', Arial, sans-serif",
    jetbrains_mono: "'JetBrains Mono', 'SF Mono', 'Cascadia Mono', monospace",
};
const CJK_FONT_STACKS = {
    source_han_serif: "'Source Han Serif SC', 'Noto Serif SC', 'Songti SC', 'STSong', 'SimSun', serif",
    source_han_sans: "'Source Han Sans SC', 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif",
    songti: "'Songti SC', 'STSong', 'SimSun', 'Noto Serif SC', serif",
    kaiti: "'Kaiti SC', 'STKaiti', 'KaiTi', 'Source Han Serif SC', serif",
    yahei: "'Microsoft YaHei', 'PingFang SC', 'Source Han Sans SC', sans-serif",
};
const DEFAULT_LATIN_FONT = 'times_new_roman';
const DEFAULT_CJK_FONT = 'source_han_serif';
const LEGACY_FONT_TO_PAIR = {
    sans: { latin: 'source_sans', cjk: 'source_han_sans' },
    serif: { latin: 'times_new_roman', cjk: 'source_han_serif' },
    mono: { latin: 'jetbrains_mono', cjk: 'source_han_sans' },
    inter_cn: { latin: 'inter', cjk: 'source_han_sans' },
    plex_cn: { latin: 'source_sans', cjk: 'source_han_sans' },
    merri_cn: { latin: 'source_serif', cjk: 'source_han_serif' },
    lora_cn: { latin: 'georgia', cjk: 'source_han_serif' },
    noto_sans: { latin: 'source_sans', cjk: 'source_han_sans' },
    source_sans: { latin: 'source_sans', cjk: 'source_han_sans' },
    source_serif: { latin: 'source_serif', cjk: 'source_han_serif' },
    manrope_cn: { latin: 'inter', cjk: 'source_han_sans' },
    georgia_song: { latin: 'georgia', cjk: 'songti' },
    hei: { latin: 'source_sans', cjk: 'source_han_sans' },
    song: { latin: 'times_new_roman', cjk: 'songti' },
    kai: { latin: 'georgia', cjk: 'kaiti' },
    rounded: { latin: 'inter', cjk: 'source_han_sans' },
    display: { latin: 'georgia', cjk: 'source_han_serif' },
};

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

function resolveStoredFontPair() {
    if (typeof window === 'undefined' || !window.localStorage) {
        return {
            latin: DEFAULT_LATIN_FONT,
            cjk: DEFAULT_CJK_FONT,
        };
    }
    const storage = window.localStorage;
    const storedLatin = storage.getItem(FONT_LATIN_STORAGE_KEY);
    const storedCjk = storage.getItem(FONT_CJK_STORAGE_KEY);
    if (LATIN_FONT_OPTIONS.has(storedLatin) && CJK_FONT_OPTIONS.has(storedCjk)) {
        return { latin: storedLatin, cjk: storedCjk };
    }
    const legacy = storage.getItem(LEGACY_FONT_STORAGE_KEY);
    const mapped = LEGACY_FONT_TO_PAIR[legacy];
    if (mapped) {
        return mapped;
    }
    return {
        latin: DEFAULT_LATIN_FONT,
        cjk: DEFAULT_CJK_FONT,
    };
}

export function ThemeProvider({ children }) {
    const [theme, setTheme] = useState(resolveStoredTheme);
    const [accentColor, setAccentColor] = useState(resolveStoredAccent);
    const [fontFamilyLatin, setFontFamilyLatinState] = useState(() => resolveStoredFontPair().latin);
    const [fontFamilyCjk, setFontFamilyCjkState] = useState(() => resolveStoredFontPair().cjk);
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

    useEffect(() => {
        if (typeof window !== 'undefined' && window.localStorage) {
            window.localStorage.setItem(FONT_LATIN_STORAGE_KEY, fontFamilyLatin);
            window.localStorage.setItem(FONT_CJK_STORAGE_KEY, fontFamilyCjk);
        }
        const latinStack = LATIN_FONT_STACKS[fontFamilyLatin] || LATIN_FONT_STACKS[DEFAULT_LATIN_FONT];
        const cjkStack = CJK_FONT_STACKS[fontFamilyCjk] || CJK_FONT_STACKS[DEFAULT_CJK_FONT];
        document.documentElement.setAttribute('data-font-latin', fontFamilyLatin);
        document.documentElement.setAttribute('data-font-cjk', fontFamilyCjk);
        document.documentElement.style.setProperty('--app-font-family-latin', latinStack);
        document.documentElement.style.setProperty('--app-font-family-cjk', cjkStack);
        document.documentElement.style.setProperty('--app-font-family', `${latinStack}, ${cjkStack}`);
    }, [fontFamilyCjk, fontFamilyLatin]);

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

    const setFontFamilyLatin = useCallback((nextFontFamily) => {
        if (!LATIN_FONT_OPTIONS.has(nextFontFamily)) return;
        setFontFamilyLatinState(nextFontFamily);
    }, []);

    const setFontFamilyCjk = useCallback((nextFontFamily) => {
        if (!CJK_FONT_OPTIONS.has(nextFontFamily)) return;
        setFontFamilyCjkState(nextFontFamily);
    }, []);

    const setFontFamily = useCallback((nextLegacyFont) => {
        const mapped = LEGACY_FONT_TO_PAIR[nextLegacyFont];
        if (!mapped) return;
        setFontFamilyLatinState(mapped.latin);
        setFontFamilyCjkState(mapped.cjk);
    }, []);

    const value = useMemo(() => ({
        theme,
        resolvedTheme,
        systemTheme,
        setTheme: syncTheme,
        toggleTheme,
        accentColor,
        setAccentColor,
        fontFamily: `${fontFamilyLatin}:${fontFamilyCjk}`,
        fontFamilyLatin,
        fontFamilyCjk,
        setFontFamily,
        setFontFamilyLatin,
        setFontFamilyCjk,
    }), [
        accentColor,
        fontFamilyCjk,
        fontFamilyLatin,
        resolvedTheme,
        setFontFamily,
        setFontFamilyCjk,
        setFontFamilyLatin,
        syncTheme,
        systemTheme,
        theme,
        toggleTheme,
    ]);

    return (
        <ThemeContext.Provider value={value}>
            {children}
        </ThemeContext.Provider>
    );
}
