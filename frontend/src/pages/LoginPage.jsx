import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { appApi, clearStoredSession, getStoredSession, isAuthError } from '../services/appApi';
import './LoginPage.css';

const INITIAL_STEP = 'identify';
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function LoginPage() {
    const navigate = useNavigate();
    const [step, setStep] = useState(INITIAL_STEP);
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [username, setUsername] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');
    const [resetToken, setResetToken] = useState('');

    const resetMessages = () => {
        setError('');
        setNotice('');
    };

    const normalizedEmail = email.trim().toLowerCase();

    useEffect(() => {
        let isMounted = true;
        const session = getStoredSession();

        if (!session?.token) {
            return () => {
                isMounted = false;
            };
        }

        setIsLoading(true);
        appApi.auth.getCurrentUser()
            .then(() => {
                if (isMounted) {
                    navigate('/home', { replace: true });
                }
            })
            .catch((err) => {
                if (isAuthError(err)) {
                    clearStoredSession();
                }
                if (isMounted && !isAuthError(err)) {
                    setError(err.message || '验证登录状态失败，请稍后重试');
                }
            })
            .finally(() => {
                if (isMounted) {
                    setIsLoading(false);
                }
            });

        return () => {
            isMounted = false;
        };
    }, [navigate]);

    const handleContinue = async (e) => {
        e.preventDefault();
        resetMessages();
        if (!normalizedEmail) {
            setError('请输入邮箱地址');
            return;
        }
        if (!EMAIL_PATTERN.test(normalizedEmail)) {
            setError('请输入有效的邮箱地址');
            return;
        }
        setIsLoading(true);
        try {
            const result = await appApi.auth.lookupEmail({ email: normalizedEmail });
            setStep(result.exists ? 'login' : 'register');
        } catch (err) {
            setError(err.message || '无法继续，请稍后重试');
        } finally {
            setIsLoading(false);
        }
    };

    const handleLogin = async (e) => {
        e.preventDefault();
        resetMessages();
        if (!password) {
            setError('请输入密码');
            return;
        }
        setIsLoading(true);
        try {
            await appApi.auth.login({ username: normalizedEmail, password });
            navigate('/home');
        } catch (err) {
            setError(err.message || '登录失败，请稍后重试');
        } finally {
            setIsLoading(false);
        }
    };

    const handleRegister = async (e) => {
        e.preventDefault();
        resetMessages();
        if (!EMAIL_PATTERN.test(normalizedEmail)) {
            setError('请输入有效的邮箱地址');
            return;
        }
        if (!username.trim()) {
            setError('请输入用户名');
            return;
        }
        if (!password) {
            setError('请输入密码');
            return;
        }
        if (password.length < 8) {
            setError('密码至少需要 8 位');
            return;
        }
        if (password !== confirmPassword) {
            setError('两次输入的密码不一致');
            return;
        }

        setIsLoading(true);
        try {
            await appApi.auth.register({
                username: username.trim(),
                email: normalizedEmail,
                password,
            });
            navigate('/home');
        } catch (err) {
            setError(err.message || '注册失败，请稍后重试');
        } finally {
            setIsLoading(false);
        }
    };

    const handleBack = () => {
        setStep(INITIAL_STEP);
        setPassword('');
        setConfirmPassword('');
        setError('');
    };

    const handleOAuthClick = async (providerName) => {
        const result = await appApi.auth.startOAuth({ provider: providerName.toLowerCase() });
        setNotice(result.reason || `${providerName} 登录暂不可用`);
        setError('');
    };

    const handleForgotPassword = async () => {
        if (!EMAIL_PATTERN.test(normalizedEmail)) {
            setError('请输入有效的邮箱地址');
            return;
        }
        const result = await appApi.auth.forgotPassword({ email: normalizedEmail });
        setResetToken(result.resetToken || '');
        setNotice(result.sent ? '已生成重置口令（开发环境展示）' : '未找到该邮箱对应账号');
    };

    const handleResetPassword = async () => {
        if (!resetToken || !password || !confirmPassword) {
            setError('请填写重置口令与新密码');
            return;
        }
        await appApi.auth.resetPassword({ token: resetToken, newPassword: password, confirmPassword });
        setNotice('密码已重置，请使用新密码登录');
        setStep('login');
    };

    return (
        <div className="auth-container">
            <div className="auth-card animate-scale-in">
                <h1 className="auth-title">NotebookLM</h1>
                <p className="auth-subtitle">
                    {step === 'identify' && '先输入邮箱，系统会自动判断进入登录还是注册'}
                    {step === 'login' && '检测到已有账号，请输入密码继续'}
                    {step === 'register' && '未找到账号，请补充资料完成注册'}
                </p>

                {step === 'identify' && (
                    <>
                        <div className="auth-provider-list">
                            <button
                                type="button"
                                className="auth-provider-button"
                                onClick={() => handleOAuthClick('Google')}
                            >
                                <span className="auth-provider-icon google">G</span>
                                <span>继续使用 Google 登录</span>
                            </button>
                            <button
                                type="button"
                                className="auth-provider-button"
                                onClick={() => handleOAuthClick('GitHub')}
                            >
                                <span className="auth-provider-icon github">GH</span>
                                <span>继续使用 GitHub 登录</span>
                            </button>
                        </div>

                        <div className="auth-divider">
                            <span>或</span>
                        </div>

                        <form className="auth-form" onSubmit={handleContinue}>
                            <input
                                className="auth-input auth-input-large"
                                type="email"
                                placeholder="电子邮件地址"
                                value={email}
                                onChange={(e) => {
                                    setEmail(e.target.value);
                                    resetMessages();
                                }}
                                autoFocus
                            />
                            <button type="submit" className="auth-button auth-button-primary" disabled={isLoading}>
                                {isLoading ? '继续中...' : '继续'}
                            </button>
                        </form>
                    </>
                )}

                {step === 'login' && (
                    <form className="auth-form" onSubmit={handleLogin}>
                        <div className="auth-email-pill">{normalizedEmail}</div>
                        <input
                            className="auth-input"
                            type="password"
                            placeholder="输入密码"
                            value={password}
                            onChange={(e) => {
                                setPassword(e.target.value);
                                resetMessages();
                            }}
                            autoFocus
                        />
                        <div className="auth-actions">
                            <button type="button" className="auth-button auth-button-secondary" onClick={handleBack}>
                                返回
                            </button>
                            <button
                                type="submit"
                                className="auth-button auth-button-primary"
                                disabled={isLoading}
                            >
                                {isLoading ? '登录中...' : '登录'}
                            </button>
                        </div>
                        <button type="button" className="auth-link-button" onClick={handleForgotPassword}>忘记密码？</button>
                        {resetToken ? (
                            <div className="auth-reset-box">
                                <div className="auth-email-pill">重置口令：{resetToken}</div>
                                <button type="button" className="auth-button auth-button-secondary" onClick={handleResetPassword}>使用当前新密码完成重置</button>
                            </div>
                        ) : null}
                    </form>
                )}

                {step === 'register' && (
                    <form className="auth-form" onSubmit={handleRegister}>
                        <div className="auth-email-pill">{normalizedEmail}</div>
                        <input
                            className="auth-input"
                            placeholder="用户名"
                            value={username}
                            onChange={(e) => {
                                setUsername(e.target.value);
                                resetMessages();
                            }}
                            autoFocus
                        />
                        <input
                            className="auth-input"
                            type="password"
                            placeholder="设置密码（至少 8 位）"
                            value={password}
                            onChange={(e) => {
                                setPassword(e.target.value);
                                resetMessages();
                            }}
                        />
                        <input
                            className="auth-input"
                            type="password"
                            placeholder="确认密码"
                            value={confirmPassword}
                            onChange={(e) => {
                                setConfirmPassword(e.target.value);
                                resetMessages();
                            }}
                        />
                        <div className="auth-actions">
                            <button type="button" className="auth-button auth-button-secondary" onClick={handleBack}>
                                返回
                            </button>
                            <button
                                type="submit"
                                className="auth-button auth-button-primary"
                                disabled={isLoading}
                            >
                                {isLoading ? '注册中...' : '创建账号'}
                            </button>
                        </div>
                    </form>
                )}

                {notice && <p className="auth-notice">{notice}</p>}
                {error && <p className="auth-error">{error}</p>}
            </div>
        </div>
    );
}
