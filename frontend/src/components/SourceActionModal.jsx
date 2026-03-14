import useEscapeToClose from '../hooks/useEscapeToClose';
import './SourceActionModal.css';

const Ic = {
    close: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" /></svg>,
    edit: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M14.06 9.02l.92.92L5.92 19H5v-.92l9.06-9.06M17.66 3c-.25 0-.51.1-.7.29l-1.83 1.83 3.75 3.75 1.83-1.83c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.2-.2-.45-.29-.71-.29zm-3.6 3.19L3 17.25V21h3.75L17.81 9.94l-3.75-3.75z" /></svg>,
    del: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z" /></svg>,
};

export default function SourceActionModal({
    mode,
    articleTitle,
    nextTitle,
    error,
    isSubmitting,
    onClose,
    onTitleChange,
    onConfirm,
}) {
    useEscapeToClose(onClose, !isSubmitting);

    const isRename = mode === 'rename';

    return (
        <div className="source-action-overlay" onClick={(event) => { if (!isSubmitting && event.target === event.currentTarget) onClose(); }}>
            <div className="source-action-modal">
                <div className="source-action-header">
                    <div className="source-action-title-wrap">
                        <div className={`source-action-icon ${isRename ? 'rename' : 'danger'}`}>
                            {isRename ? Ic.edit : Ic.del}
                        </div>
                        <div>
                            <h3 className="source-action-title">{isRename ? '编辑来源标题' : '删除来源'}</h3>
                            <p className="source-action-subtitle">
                                {isRename
                                    ? '修改后会立即更新左侧来源列表和正文标题。'
                                    : `删除后会移除来源《${articleTitle || '未命名来源'}》及其关联内容。`}
                            </p>
                        </div>
                    </div>
                    <button className="source-action-close" onClick={onClose} disabled={isSubmitting} title="关闭">
                        {Ic.close}
                    </button>
                </div>

                <div className="source-action-body">
                    {isRename ? (
                        <label className="source-action-field">
                            <span className="source-action-label">来源标题</span>
                            <input
                                className="source-action-input"
                                value={nextTitle}
                                onChange={(event) => onTitleChange(event.target.value)}
                                placeholder="输入新的来源标题"
                                disabled={isSubmitting}
                                autoFocus
                            />
                        </label>
                    ) : (
                        <div className="source-action-danger-card">
                            <p>这会删除该来源文章、关联的原始文件，以及当前笔记本中的该条来源记录。</p>
                            <p>如果这是误操作，需要重新导入该来源。</p>
                        </div>
                    )}
                    {error ? <div className="source-action-error">{error}</div> : null}
                </div>

                <div className="source-action-footer">
                    <button className="source-action-cancel" onClick={onClose} disabled={isSubmitting}>取消</button>
                    <button
                        className={`source-action-confirm ${isRename ? '' : 'danger'}`}
                        onClick={onConfirm}
                        disabled={isSubmitting || (isRename && !String(nextTitle || '').trim())}
                    >
                        {isSubmitting ? (isRename ? '保存中...' : '删除中...') : (isRename ? '保存标题' : '确认删除')}
                    </button>
                </div>
            </div>
        </div>
    );
}
