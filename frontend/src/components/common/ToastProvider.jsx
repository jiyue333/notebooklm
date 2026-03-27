import { useCallback, useMemo, useState } from 'react';
import { ToastContext } from './toastContext';

export function ToastProvider({ children }) {
    const [toasts, setToasts] = useState([]);

    const dismissToast = useCallback((id) => {
        setToasts((current) => current.filter((toast) => toast.id !== id));
    }, []);

    const showToast = useCallback(({ type = 'info', title, message, duration = 2600 }) => {
        const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        setToasts((current) => [...current, { id, type, title, message }]);
        if (duration > 0) {
            window.setTimeout(() => {
                setToasts((current) => current.filter((toast) => toast.id !== id));
            }, duration);
        }
        return id;
    }, []);

    const value = useMemo(() => ({ showToast, dismissToast }), [dismissToast, showToast]);

    return (
        <ToastContext.Provider value={value}>
            {children}
            <div className="ui-toast-stack" aria-live="polite" aria-atomic="true">
                {toasts.map((toast) => (
                    <div key={toast.id} className={`ui-toast ui-toast-${toast.type}`}>
                        <div className="ui-toast-body">
                            {toast.title ? <strong>{toast.title}</strong> : null}
                            {toast.message ? <span>{toast.message}</span> : null}
                        </div>
                        <button type="button" className="ui-toast-close" onClick={() => dismissToast(toast.id)}>✕</button>
                    </div>
                ))}
            </div>
        </ToastContext.Provider>
    );
}
