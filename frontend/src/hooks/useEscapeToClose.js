import { useEffect } from 'react';

export default function useEscapeToClose(onClose, enabled = true) {
    useEffect(() => {
        if (!enabled || !onClose) return undefined;

        const handleKeyDown = (event) => {
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
