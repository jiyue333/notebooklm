import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { appApi, clearStoredSession, getStoredSession, isAuthError } from '../services/appApi';
import { useToast } from '../components/common/useToast';
import './LoginPage.css';

const INITIAL_STEP = 'identify';
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function GoogleIcon() {
    return (
        <svg viewBox="0 0 18 18" aria-hidden="true" focusable="false">
            <path fill="#4285F4" d="M17.64 9.2045c0-.6382-.0573-1.2518-.1636-1.8409H9v3.4818h4.8436c-.2086 1.125-.8427 2.0782-1.7959 2.7164v2.2582h2.9082c1.7023-1.5668 2.6837-3.8741 2.6837-6.6155z" />
            <path fill="#34A853" d="M9 18c2.43 0 4.4673-.8059 5.9564-2.1805l-2.9082-2.2582c-.8059.54-1.8368.8591-3.0482.8591-2.3427 0-4.3282-1.5818-5.0373-3.7064H.9573v2.3327C2.4382 15.9832 5.4818 18 9 18z" />
            <path fill="#FBBC05" d="M3.9627 10.7136c-.18-.54-.2823-1.1168-.2823-1.7136s.1023-1.1736.2823-1.7136V4.9536H.9573C.3477 6.1677 0 7.5436 0 9s.3477 2.8323.9573 4.0464l3.0054-2.3328z" />
            <path fill="#EA4335" d="M9 3.5795c1.3214 0 2.5077.4541 3.4405 1.3459l2.5809-2.5809C13.4632.8918 11.4264 0 9 0 5.4818 0 2.4382 2.0168.9573 4.9536l3.0054 2.3327C4.6718 5.1614 6.6573 3.5795 9 3.5795z" />
        </svg>
    );
}

function GitHubIcon() {
    return (
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <path d="M8 0C3.58 0 0 3.58 0 8a8 8 0 0 0 5.47 7.59c.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.5-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.01.08-2.1 0 0 .67-.21 2.2.82A7.64 7.64 0 0 1 8 4.85c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.09.16 1.9.08 2.1.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.001 8.001 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
        </svg>
    );
}

export default function LoginPage() {
    const navigate = useNavigate();
    const { showToast } = useToast();
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

    const handleOAuthClick = (providerName) => {
        showToast({
            type: 'info',
            title: `${providerName} 登录`,
            message: '暂未接入，敬请期待',
        });
        setNotice('');
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

    const subtitle = step === 'login'
        ? '检测到已有账号，请输入密码继续'
        : step === 'register'
            ? '未找到账号，请补充资料完成注册'
            : '';

    return (
        <div className="auth-container">
            <div className="auth-card animate-scale-in">
                <h1 className="auth-title">NotebookLM</h1>
                {subtitle ? <p className="auth-subtitle">{subtitle}</p> : null}

                {step === 'identify' && (
                    <>
                        <div className="auth-provider-list">
                            <button
                                type="button"
                                className="auth-provider-button"
                                onClick={() => handleOAuthClick('Google')}
                            >
                                <span className="auth-provider-icon google"><GoogleIcon /></span>
                                <span>继续使用 Google 登录</span>
                            </button>
                            <button
                                type="button"
                                className="auth-provider-button"
                                onClick={() => handleOAuthClick('GitHub')}
                            >
                                <span className="auth-provider-icon github"><GitHubIcon /></span>
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
