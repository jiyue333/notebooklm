import { useEffect, useRef } from 'react';

export default function AccountMenu({ open, user, onClose, onOpenSettings, onLogout }) {
    const menuRef = useRef(null);

    useEffect(() => {
        if (!open) return undefined;
        const handlePointerDown = (event) => {
            if (menuRef.current && !menuRef.current.contains(event.target)) {
                onClose?.();
            }
        };
        document.addEventListener('mousedown', handlePointerDown);
        return () => document.removeEventListener('mousedown', handlePointerDown);
    }, [onClose, open]);

    if (!open) return null;

    return (
        <div className="ui-account-menu" ref={menuRef} role="menu">
            <div className="ui-account-menu-profile">
                <div className="ui-account-menu-avatar">
                    {user?.avatar ? (
                        <img className="ui-account-menu-avatar-image" src={user.avatar} alt={user?.name || '用户头像'} />
                    ) : (
                        user?.name?.charAt(0) || 'U'
                    )}
                </div>
                <div className="ui-account-menu-meta">
                    <strong>{user?.name || '未登录用户'}</strong>
                    <span>{user?.email || '点击设置完善资料'}</span>
                </div>
            </div>
            <button type="button" className="ui-account-menu-item" onClick={onOpenSettings}>账户设置</button>
            <button type="button" className="ui-account-menu-item danger" onClick={onLogout}>退出登录</button>
        </div>
    );
}
