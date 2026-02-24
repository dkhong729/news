import { useEffect, useMemo, useState } from 'react';

export function useAuth() {
  const [user, setUser] = useState(null);

  const syncFromStorage = () => {
    if (typeof window === 'undefined') return;
    const token = localStorage.getItem('ai_pulse_token');
    const userId = localStorage.getItem('ai_pulse_user_id');
    const email = localStorage.getItem('ai_pulse_email');
    const role = localStorage.getItem('ai_pulse_role');
    const displayName = localStorage.getItem('ai_pulse_display_name');
    if (token && userId) {
      setUser({ token, userId: Number(userId), email: email || '', role: role || 'tech', displayName: displayName || '' });
    } else {
      setUser(null);
    }
  };

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    const userId = params.get('user_id');
    const email = params.get('email');
    const role = params.get('role');
    const displayName = params.get('display_name');

    if (token && userId) {
      localStorage.setItem('ai_pulse_token', token);
      localStorage.setItem('ai_pulse_user_id', userId);
      if (email) localStorage.setItem('ai_pulse_email', email);
      if (role) localStorage.setItem('ai_pulse_role', role);
      if (displayName) localStorage.setItem('ai_pulse_display_name', displayName);
      const clean = window.location.origin + window.location.pathname;
      window.history.replaceState({}, '', clean);
    }

    syncFromStorage();
  }, []);

  const logout = () => {
    if (typeof window === 'undefined') return;
    localStorage.removeItem('ai_pulse_token');
    localStorage.removeItem('ai_pulse_user_id');
    localStorage.removeItem('ai_pulse_email');
    localStorage.removeItem('ai_pulse_role');
    localStorage.removeItem('ai_pulse_display_name');
    setUser(null);
  };

  const authHeaders = useMemo(() => {
    if (!user?.token) return {};
    return { Authorization: `Bearer ${user.token}` };
  }, [user]);

  return { user, setUser, logout, authHeaders, syncFromStorage };
}
