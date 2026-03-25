import { useEffect } from 'react';

export default function useKeyboardShortcuts(shortcuts = []) {
    useEffect(() => {
        if (!Array.isArray(shortcuts) || shortcuts.length === 0) return undefined;

        const handleKeyDown = (event) => {
            shortcuts.forEach((shortcut) => {
                if (!shortcut?.handler) return;
                const keyMatches = (shortcut.key || '').toLowerCase() === event.key.toLowerCase();
                const metaMatches = shortcut.metaKey === undefined || shortcut.metaKey === event.metaKey;
                const ctrlMatches = shortcut.ctrlKey === undefined || shortcut.ctrlKey === event.ctrlKey;
                const shiftMatches = shortcut.shiftKey === undefined || shortcut.shiftKey === event.shiftKey;
                const altMatches = shortcut.altKey === undefined || shortcut.altKey === event.altKey;
                if (keyMatches && metaMatches && ctrlMatches && shiftMatches && altMatches) {
                    if (shortcut.preventDefault !== false) {
                        event.preventDefault();
                    }
                    shortcut.handler(event);
                }
            });
        };

        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [shortcuts]);
}
