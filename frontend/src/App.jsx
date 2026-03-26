import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { ThemeProvider } from './contexts/ThemeContext';
import { ToastProvider } from './components/common/ToastProvider';
import { getStoredSession } from './services/appApi';
import LoginPage from './pages/LoginPage';
import HomePage from './pages/HomePage';
import NotebookPage from './pages/NotebookPage';
import './App.css';

function RequireSession({ children }) {
  const location = useLocation();
  const session = getStoredSession();

  if (!session?.token) {
    return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}${location.hash}` }} />;
  }

  return children;
}

function SessionEntryRedirect() {
  const session = getStoredSession();
  return <Navigate to={session?.token ? '/home' : '/login'} replace />;
}

function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/home" element={<RequireSession><HomePage /></RequireSession>} />
            <Route path="/notebook/:id" element={<RequireSession><NotebookPage /></RequireSession>} />
            <Route path="/" element={<SessionEntryRedirect />} />
            <Route path="*" element={<SessionEntryRedirect />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </ThemeProvider>
  );
}

export default App;
