import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { appApi } from '../services/appApi';
import './LoginPage.css';

export default function LoginPage() {
    const navigate = useNavigate();
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState('');

    const handleLogin = async (e) => {
        e.preventDefault();
        setError('');
        setIsLoading(true);
        try {
            await appApi.auth.login({ username, password });
            navigate('/home');
        } catch (err) {
            setError(err.message || '登录失败，请稍后重试');
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="auth-container">
            <div className="auth-box animate-scale-in">
                <h1 className="auth-title">NotebookLM</h1>
                <p className="auth-subtitle">登录以继续使用</p>

                <form className="auth-form" onSubmit={handleLogin}>
                    <input
                        className="auth-input"
                        placeholder="用户名"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        autoFocus
                    />
                    <input
                        className="auth-input"
                        type="password"
                        placeholder="密码"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                    />
                    <button type="submit" className="auth-button" disabled={isLoading}>
                        {isLoading ? '登录中...' : '登录'}
                    </button>
                </form>
                {error && <p className="auth-error">{error}</p>}
            </div>
        </div>
    );
}
