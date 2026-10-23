import { useAuthStore } from '../stores/authStore';
import { useCallback } from 'react';

export const useAuth = () => {
  const user = useAuthStore((state) => state.user);
  const token = useAuthStore((state) => state.token);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isLoading = useAuthStore((state) => state.isLoading);
  const error = useAuthStore((state) => state.error);
  const loginFn = useAuthStore((state) => state.login);
  const registerFn = useAuthStore((state) => state.register);
  const logoutFn = useAuthStore((state) => state.logout);
  const initialize = useAuthStore((state) => state.initialize);
  const clearError = useAuthStore((state) => state.clearError);

  const handleLogout = useCallback(() => {
    logoutFn();
  }, [logoutFn]);

  return {
    user, token, isAuthenticated, isLoading, error,
    login: loginFn,
    register: registerFn,
    logout: handleLogout,
    initialize,
    clearError,
  };
};
