export default function EmptyState({
    icon = '🗂️',
    title,
    description,
    actionLabel,
    onAction,
    compact = false,
}) {
    return (
        <div className={`ui-empty-state${compact ? ' compact' : ''}`}>
            <div className="ui-empty-state-icon" aria-hidden="true">{icon}</div>
            {title ? <h3 className="ui-empty-state-title">{title}</h3> : null}
            {description ? <p className="ui-empty-state-description">{description}</p> : null}
            {actionLabel && onAction ? (
                <button type="button" className="btn btn-primary ui-empty-state-action" onClick={onAction}>
                    {actionLabel}
                </button>
            ) : null}
        </div>
    );
}
