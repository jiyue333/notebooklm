import { useEffect, useRef, useState } from 'react';

export default function InlineEditableText({
    value,
    onSave,
    placeholder = '请输入内容',
    className = '',
    inputClassName = '',
    readOnly = false,
    showEditIcon = true,
    maxLength,
}) {
    const [isEditing, setIsEditing] = useState(false);
    const [draft, setDraft] = useState(value || '');
    const [isSaving, setIsSaving] = useState(false);
    const inputRef = useRef(null);

    useEffect(() => {
        if (!isEditing) {
            setDraft(value || '');
        }
    }, [isEditing, value]);

    useEffect(() => {
        if (isEditing) {
            inputRef.current?.focus();
            inputRef.current?.select();
        }
    }, [isEditing]);

    const commit = async () => {
        const nextValue = draft.trim();
        setIsEditing(false);
        if (!nextValue || nextValue === value) {
            setDraft(value || '');
            return;
        }
        try {
            setIsSaving(true);
            await onSave?.(nextValue);
        } finally {
            setIsSaving(false);
        }
    };

    if (isEditing && !readOnly) {
        return (
            <input
                ref={inputRef}
                className={`ui-inline-edit-input ${inputClassName}`.trim()}
                value={draft}
                maxLength={maxLength}
                onChange={(event) => setDraft(event.target.value)}
                onBlur={commit}
                onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                        event.preventDefault();
                        void commit();
                    }
                    if (event.key === 'Escape') {
                        event.preventDefault();
                        setIsEditing(false);
                        setDraft(value || '');
                    }
                }}
            />
        );
    }

    return (
        <button
            type="button"
            className={`ui-inline-edit-trigger ${className}`.trim()}
            onClick={() => {
                if (!readOnly && !isSaving) {
                    setIsEditing(true);
                }
            }}
            disabled={readOnly || isSaving}
            title={readOnly ? undefined : '点击编辑'}
        >
            <span>{value || placeholder}</span>
            {!readOnly && showEditIcon ? <span className="ui-inline-edit-icon">✎</span> : null}
        </button>
    );
}
