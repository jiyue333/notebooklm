export default function Spinner({ size = 'md', label = '加载中', inline = false }) {
    return (
        <span className={`ui-spinner${inline ? ' ui-spinner-inline' : ''}`} data-size={size} aria-label={label} role="status">
            <span className="ui-spinner-ring" aria-hidden="true" />
            {label ? <span className="ui-spinner-label">{label}</span> : null}
        </span>
    );
}
