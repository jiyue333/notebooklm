export default function ErrorBanner({ title = '出了点问题', message, actionLabel, onAction, inline = false }) {
    if (!message) return null;

    return (
        <div className={`ui-error-banner${inline ? ' inline' : ''}`} role="alert">
            <div className="ui-error-banner-content">
                <strong className="ui-error-banner-title">{title}</strong>
                <span className="ui-error-banner-message">{message}</span>
            </div>
            {actionLabel && onAction ? (
                <button type="button" className="ui-error-banner-action" onClick={onAction}>
                    {actionLabel}
                </button>
            ) : null}
        </div>
    );
}
