import { useEffect } from 'react';

export default function useEscapeToClose(onClose, enabled = true) {
    useEffect(() => {
        if (!enabled || !onClose) return undefined;

        const handleKeyDown = (event) => {
            if (event.defaultPrevented) return;
            if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
                return;
            }
            if (event.key === 'Escape') {
                onClose();
            }
        };

        document.addEventListener('keydown', handleKeyDown);
        return () => {
            document.removeEventListener('keydown', handleKeyDown);
        };
    }, [enabled, onClose]);
}
