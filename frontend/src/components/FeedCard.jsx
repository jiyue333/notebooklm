import { useMemo, useState } from 'react';
import './FeedCard.css';

export default function FeedCard({ feed, delay = 0, onOpen, onRefresh, onRemove }) {
    const [menuOpen, setMenuOpen] = useState(false);

    const unreadLabel = useMemo(() => {
        const count = Number(feed?.unreadCount || 0);
        return count > 0 ? `${count} 篇未读` : '暂无未读';
    }, [feed?.unreadCount]);

    return (
        <article
            className="feed-card animate-fade-in"
            style={{ animationDelay: `${delay}s` }}
            onClick={() => onOpen?.(feed)}
        >
            <div className="feed-card-header">
                <span className="feed-card-icon">📡</span>
                <div className="feed-card-menu-wrap" onClick={(event) => event.stopPropagation()}>
                    <button
                        type="button"
                        className="feed-card-menu-btn"
                        onClick={() => setMenuOpen((current) => !current)}
                    >
                        ⋮
                    </button>
                    {menuOpen ? (
                        <div className="feed-card-menu">
                            <button
                                type="button"
                                onClick={() => {
                                    setMenuOpen(false);
                                    onRefresh?.(feed);
                                }}
                            >
                                刷新
                            </button>
                            <button
                                type="button"
                                className="danger"
                                onClick={() => {
                                    setMenuOpen(false);
                                    onRemove?.(feed);
                                }}
                            >
                                取消订阅
                            </button>
                        </div>
                    ) : null}
                </div>
            </div>
            <div className="feed-card-body">
                <h3 className="feed-card-title">{feed?.title || '未命名订阅源'}</h3>
                <p className="feed-card-meta">{unreadLabel}{feed?.categoryName ? ` · ${feed.categoryName}` : ''}</p>
                <div className="feed-card-tags">
                    <span>{feed?.crawlerEnabled ? 'Crawler ON' : 'Standard'}</span>
                </div>
            </div>
        </article>
    );
}
