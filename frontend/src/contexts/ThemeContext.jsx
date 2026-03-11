import { useState, useEffect } from 'react';
import { ThemeContext } from './themeStore';

export function ThemeProvider({ children }) {
    const [theme, setTheme] = useState(() => {
        const saved = localStorage.getItem('notebooklm-theme');
        return saved || 'light';
    });

    const [accentColor, setAccentColor] = useState(() => {
        const saved = localStorage.getItem('notebooklm-accent');
        return saved || 'ocean';
    });

    useEffect(() => {
        localStorage.setItem('notebooklm-theme', theme);
        document.documentElement.setAttribute('data-theme', theme);
    }, [theme]);

    useEffect(() => {
        localStorage.setItem('notebooklm-accent', accentColor);
        document.documentElement.setAttribute('data-accent', accentColor);
    }, [accentColor]);

    const toggleTheme = () => {
        setTheme(prev => prev === 'light' ? 'dark' : 'light');
    };

    return (
        <ThemeContext.Provider value={{ theme, setTheme, toggleTheme, accentColor, setAccentColor }}>
            {children}
        </ThemeContext.Provider>
    );
}
